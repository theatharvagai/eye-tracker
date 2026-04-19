@echo off
title Building Auto-Pause EXE
color 0B
echo.
echo  ============================================
echo    Auto-Pause When Not Looking  –  EXE Build
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

echo  [2/3] Building EXE (this takes ~1-2 minutes)...
echo.

"%PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "AutoPause" ^
    --add-data "face_landmarker.task;." ^
    --hidden-import mediapipe ^
    --hidden-import cv2 ^
    --hidden-import pyautogui ^
    --hidden-import numpy ^
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
echo  The floating bar will appear at the top of your screen.
echo  Click the X on the bar to close and exit.
echo.
pause
