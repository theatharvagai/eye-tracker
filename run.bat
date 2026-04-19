@echo off
title Auto-Pause When Not Looking
color 0B
echo.
echo  ========================================
echo    Auto-Pause When Not Looking
echo  ========================================
echo.

:: Use the specific Python 3.12 installation
set PYTHON=C:\Users\conta\AppData\Local\Programs\Python\Python312\python.exe

:: Fallback: try generic python if specific path doesn't exist
if not exist "%PYTHON%" set PYTHON=python

:: Install dependencies
echo  [1/2] Installing / checking dependencies...
"%PYTHON%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo  [2/2] Launching app...
echo.
"%PYTHON%" main.py
pause
