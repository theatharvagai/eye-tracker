@echo off
title Building Auto-Pause EXE
color 0B
echo.
echo  ============================================
echo    Auto-Pause When Not Looking  --  EXE Build
echo  ============================================
echo.

:: Use the specific Python 3.12 installation
set PYTHON=C:\Users\conta\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON%" set PYTHON=python

:: Install dependencies + PyInstaller
echo  [1/3] Installing dependencies...
"%PYTHON%" -m pip install -r requirements.txt --quiet
"%PYTHON%" -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause
    exit /b 1
)

:: Clean any old build
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist AutoPause.spec del /q AutoPause.spec

echo  [2/3] Building EXE (this takes 2-4 minutes - mediapipe is large)...
echo.

:: IMPORTANT: --collect-all mediapipe is required.
:: --hidden-import alone does NOT bundle mediapipe's internal .so/.pyd
:: binary extensions, tflite models, and protobuf descriptors.
"%PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "AutoPause" ^
    --add-data "face_landmarker.task;." ^
    --collect-all mediapipe ^
    --collect-all cv2 ^
    --hidden-import pyautogui ^
    --hidden-import numpy ^
    --hidden-import tkinter ^
    --noconfirm ^
    main.py

if errorlevel 1 (
    echo.
    echo  [ERROR] PyInstaller build failed. See above for details.
    pause
    exit /b 1
)

echo.
echo  [3/3] Done!
echo.
echo  EXE is at:  dist\AutoPause.exe
echo.
echo  Double-click dist\AutoPause.exe to run.
echo  The floating bar appears at the top-centre of your screen.
echo  Press the play button to start tracking.
echo  Click X on the bar to close and exit.
echo.
echo  If something goes wrong, check:  dist\autopause_error.log
echo.
pause
