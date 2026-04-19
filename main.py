"""
Auto-Pause When Not Looking  –  Lightweight Edition
────────────────────────────────────────────────────
• No camera preview window
• Tiny translucent floating bar (always on-top)
• Close bar → app exits
• Optimised: low-res capture, frame skipping, minimal threading
"""

import sys
import traceback
import tkinter as tk
import threading
import time
import os
import urllib.request

import cv2
import numpy as np
import pyautogui

pyautogui.FAILSAFE = False  # prevent accidental move-to-corner crash

# ──────────────── Tuneable settings ────────────────────────────────
LOOK_AWAY_DELAY    = 1.5    # seconds away before pausing
LOOK_BACK_DELAY    = 0.5    # seconds back before resuming
CAMERA_INDEX       = 0      # webcam index
CAM_WIDTH          = 320    # capture resolution – low = fast
CAM_HEIGHT         = 240
PROCESS_EVERY_N    = 3      # only run face detection every N frames
EYE_OPEN_THRESHOLD = 0.18   # EAR below this = eyes closed
BLINK_FRAMES       = 3      # blink-grace before counting as "away"
# ───────────────────────────────────────────────────────────────────

# ── Resolve paths correctly for both EXE (frozen) and source runs ──
# PyInstaller --onefile extracts bundled files to sys._MEIPASS.
# The EXE itself lives at sys.executable when frozen.
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = sys._MEIPASS                           # bundled assets (model)
    _EXE_DIR    = os.path.dirname(sys.executable)        # folder where AutoPause.exe sits
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR    = _BUNDLE_DIR

MODEL_PATH = os.path.join(_BUNDLE_DIR, "face_landmarker.task")
LOG_PATH   = os.path.join(_EXE_DIR, "autopause_error.log")   # written next to the EXE
MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

# Eye landmark indices (MediaPipe 478-point mesh)
L_V = (159, 145);  L_H = (33, 133)
R_V = (386, 374);  R_H = (362, 263)


def _log_error(msg: str):
    """Append an error line to the log file next to the EXE."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]  {msg}\n")
    except Exception:
        pass


def _ear(lm, vt, vb, hl, hr, W, H):
    def p(i): return np.array([lm[i].x * W, lm[i].y * H])
    return np.linalg.norm(p(vt) - p(vb)) / (np.linalg.norm(p(hl) - p(hr)) + 1e-6)


def _ensure_model(status_cb) -> bool:
    """Return True if the model file is ready."""
    if os.path.exists(MODEL_PATH):
        return True
    # In a frozen EXE the model should always be bundled — if missing, the build is broken.
    if getattr(sys, 'frozen', False):
        msg = "face_landmarker.task missing from bundle — rebuild EXE with build_exe.bat"
        status_cb(msg)
        _log_error(msg)
        return False
    # Source run: download it
    try:
        status_cb("Downloading face model (~3.7 MB)…")
        def hook(count, blk, total):
            if total > 0:
                status_cb(f"Downloading… {min(count * blk * 100 // total, 100)}%")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, hook)
        return True
    except Exception as e:
        msg = f"Model download failed: {e}"
        status_cb(msg)
        _log_error(msg)
        return False


# ──────────────── Core worker thread ───────────────────────────────

class EyeTrackWorker:
    """
    Runs in a single daemon thread.
    Public attributes (read from UI thread):
        .looking  bool   – face detected and eyes open
        .ear_val  float  – current eye aspect ratio
        .paused   bool   – video currently paused by us
        .status   str    – human-readable status
        .error    str    – non-empty if the worker crashed
        .done     bool   – True when the thread has exited
    """
    def __init__(self):
        self.looking = False
        self.ear_val = 0.0
        self.paused  = False
        self.status  = "Starting…"
        self.error   = ""
        self.done    = False
        self._stop   = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            self._run_inner()
        except Exception:
            tb = traceback.format_exc()
            self.error  = tb.strip().splitlines()[-1]   # last line for the bar
            self.status = f"Error: {self.error}"
            _log_error("Worker crashed:\n" + tb)
        finally:
            self.done = True

    def _run_inner(self):
        # ── import mediapipe here (inside thread) so startup is fast ──
        _log_error(f"MODEL_PATH={MODEL_PATH}  exists={os.path.exists(MODEL_PATH)}")
        import mediapipe as mp
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision as mpv

        if not _ensure_model(lambda s: setattr(self, "status", s)):
            return

        self.status = "Opening camera…"
        _log_error("Opening camera")
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, 15)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            msg = f"Cannot open camera (index {CAMERA_INDEX})"
            self.status = msg
            _log_error(msg)
            return

        _log_error("Camera open — creating FaceLandmarker")
        try:
            opts = mpv.FaceLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=mpv.RunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        except Exception as e:
            msg = f"FaceLandmarker options error: {e}"
            self.status = msg
            _log_error(msg + "\n" + traceback.format_exc())
            cap.release()
            return

        closed_streak = 0
        frame_idx     = 0
        ts_ms         = 0
        away_since    = None
        back_since    = None

        self.status = "Watching…"
        _log_error("Entering detection loop")

        with mpv.FaceLandmarker.create_from_options(opts) as det:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                frame_idx += 1
                ts_ms     += 66      # ~15 fps timestamp increment

                # skip frames to save CPU
                if frame_idx % PROCESS_EVERY_N != 0:
                    time.sleep(0.01)
                    continue

                H, W = frame.shape[:2]

                try:
                    rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    res    = det.detect_for_video(mp_img, ts_ms)
                except Exception:
                    continue

                if res.face_landmarks:
                    lm = res.face_landmarks[0]
                    avg_ear = (
                        _ear(lm, *L_V, *L_H, W, H) +
                        _ear(lm, *R_V, *R_H, W, H)
                    ) / 2
                    self.ear_val  = avg_ear
                    closed_streak = closed_streak + 1 if avg_ear < EYE_OPEN_THRESHOLD else 0
                    looking       = closed_streak < BLINK_FRAMES
                else:
                    looking       = False
                    self.ear_val  = 0.0
                    closed_streak = 0

                self.looking = looking

                # ── pause / resume logic ────────────────────────
                now = time.time()
                if not looking:
                    back_since = None
                    if away_since is None:
                        away_since = now
                    elif now - away_since >= LOOK_AWAY_DELAY and not self.paused:
                        pyautogui.press("space")
                        self.paused  = True
                        away_since   = None
                        self.status  = "Paused (looked away)"
                else:
                    away_since = None
                    if back_since is None:
                        back_since = now
                    elif now - back_since >= LOOK_BACK_DELAY and self.paused:
                        pyautogui.press("space")
                        self.paused  = False
                        back_since   = None
                        self.status  = "Playing (you're back)"

        cap.release()
        self.status = "Stopped"
        _log_error("Worker stopped cleanly")


# ──────────────── Floating bar GUI ──────────────────────────────────

class FloatingBar(tk.Tk):
    BG_LOOKING  = "#1a1a2e"
    BG_AWAY     = "#2a0a0a"
    BG_ERROR    = "#1a0a00"
    FG_MAIN     = "#e8e8f0"
    FG_DIM      = "#8888aa"
    ACCENT      = "#6c63ff"
    GREEN       = "#39d98a"
    RED         = "#ff5a5a"
    YELLOW      = "#f5a623"

    BAR_W = 460
    BAR_H = 58

    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.88)
        self.configure(bg=self.BG_LOOKING)
        self.resizable(False, False)

        sw = self.winfo_screenwidth()
        x  = (sw - self.BAR_W) // 2
        self.geometry(f"{self.BAR_W}x{self.BAR_H}+{x}+18")

        self._worker   = None
        self._drag_x   = 0
        self._drag_y   = 0

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.after(250, self._poll)

    def _build(self):
        self._root_frame = tk.Frame(self, bg=self.BG_LOOKING)
        self._root_frame.pack(fill="both", expand=True)

        # Left dot
        left = tk.Frame(self._root_frame, bg=self.BG_LOOKING, width=46)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self._dot = tk.Label(left, text="●", font=("Segoe UI", 18),
                             bg=self.BG_LOOKING, fg=self.FG_DIM)
        self._dot.place(relx=0.5, rely=0.5, anchor="center")

        # Centre text
        centre = tk.Frame(self._root_frame, bg=self.BG_LOOKING)
        centre.pack(side="left", fill="both", expand=True)

        self._lbl_top = tk.Label(centre, text="👁  Auto-Pause",
                                 font=("Segoe UI", 10, "bold"),
                                 bg=self.BG_LOOKING, fg=self.FG_MAIN,
                                 anchor="w")
        self._lbl_top.pack(fill="x", pady=(7, 0), padx=2)

        self._lbl_bot = tk.Label(centre, text="Press ▶ to start",
                                 font=("Segoe UI", 8),
                                 bg=self.BG_LOOKING, fg=self.FG_DIM,
                                 anchor="w")
        self._lbl_bot.pack(fill="x", padx=2)

        # Right buttons
        right = tk.Frame(self._root_frame, bg=self.BG_LOOKING)
        right.pack(side="right", fill="y", padx=(0, 4))

        self._btn_toggle = tk.Button(right,
                                     text="▶",
                                     font=("Segoe UI", 11, "bold"),
                                     bg=self.ACCENT, fg="white",
                                     activebackground="#9a94ff",
                                     activeforeground="white",
                                     relief="flat", bd=0,
                                     width=3, cursor="hand2",
                                     command=self._toggle)
        self._btn_toggle.pack(side="left", pady=10, padx=(0, 2))

        btn_close = tk.Button(right,
                              text="✕",
                              font=("Segoe UI", 11, "bold"),
                              bg="#333355", fg=self.FG_DIM,
                              activebackground=self.RED,
                              activeforeground="white",
                              relief="flat", bd=0,
                              width=3, cursor="hand2",
                              command=self._quit)
        btn_close.pack(side="left", pady=10)

        # Drag
        for w in (self._root_frame, left, centre,
                  self._lbl_top, self._lbl_bot, self._dot):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",     self._drag_motion)

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_motion(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    def _toggle(self):
        if self._worker is None:
            self._start()
        else:
            self._stop()

    def _start(self):
        self._worker = EyeTrackWorker()
        threading.Thread(target=self._worker.run, daemon=True).start()
        self._btn_toggle.config(text="⏹", bg="#c0392b", activebackground="#e74c3c")
        self._lbl_bot.config(text="Starting…")

    def _stop(self):
        if self._worker:
            self._worker.stop()
            self._worker = None
        self._btn_toggle.config(text="▶", bg=self.ACCENT, activebackground="#9a94ff")
        self._set_bg(self.BG_LOOKING)
        self._lbl_bot.config(text="Stopped — press ▶ to restart")
        self._dot.config(fg=self.FG_DIM)

    def _poll(self):
        if self._worker:
            w = self._worker

            # ── auto-reset if the worker crashed / finished unexpectedly ──
            if w.done and not self._worker._stop.is_set():
                err = w.error or w.status
                self._worker = None
                self._btn_toggle.config(text="▶", bg=self.ACCENT,
                                        activebackground="#9a94ff")
                self._set_bg(self.BG_ERROR if w.error else self.BG_LOOKING)
                self._dot.config(fg=self.RED if w.error else self.FG_DIM)
                # Show error on bar and write log hint
                short = err[:55] + "…" if len(err) > 55 else err
                self._lbl_bot.config(text=f"⚠ {short}  [see autopause_error.log]"
                                     if w.error else short,
                                     fg=self.RED if w.error else self.FG_DIM)
                self.after(250, self._poll)
                return

            looking = w.looking
            paused  = w.paused
            ear     = w.ear_val
            st      = w.status

            bg = self.BG_AWAY if not looking else self.BG_LOOKING
            self._set_bg(bg)

            if looking:
                dot_col = self.GREEN
            elif ear == 0.0:
                dot_col = self.FG_DIM
            else:
                dot_col = self.YELLOW
            self._dot.config(fg=dot_col)

            if paused:
                bot = f"⏸ Paused  (EAR {ear:.2f})"
            elif looking:
                bot = f"▶ Playing  (EAR {ear:.2f})"
            else:
                bot = st
            self._lbl_bot.config(text=bot, fg=self.FG_DIM)

        self.after(250, self._poll)

    def _set_bg(self, colour):
        for w in self.winfo_children():
            try: w.configure(bg=colour)
            except Exception: pass
            for ww in w.winfo_children():
                try: ww.configure(bg=colour)
                except Exception: pass
                for www in ww.winfo_children():
                    try: www.configure(bg=colour)
                    except Exception: pass
        self._root_frame.configure(bg=colour)
        self.configure(bg=colour)

    def _quit(self):
        if self._worker:
            self._worker.stop()
        self.destroy()


# ──────────────── Entry point ────────────────────────────────────────

if __name__ == "__main__":
    _log_error("=" * 60)
    _log_error(f"App starting. frozen={getattr(sys, 'frozen', False)}")
    _log_error(f"BUNDLE_DIR={_BUNDLE_DIR}")
    _log_error(f"EXE_DIR={_EXE_DIR}")
    _log_error(f"MODEL_PATH={MODEL_PATH}  exists={os.path.exists(MODEL_PATH)}")

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    bar = FloatingBar()
    bar.mainloop()
