@echo off
cd /d "%~dp0"
py --version >nul 2>&1
if errorlevel 1 (
  python --version >nul 2>&1
  if errorlevel 1 (
    echo Python was not found. Install it from https://www.python.org/downloads/windows/ and check Add Python to PATH.
    pause
    exit /b 1
  )
  set PYTHON=python
) else (
  set PYTHON=py
)
echo Installing required packages...
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Could not install packages. Check your internet connection and Python installation.
  pause
  exit /b 1
)
echo Starting Air Travel...
%PYTHON% app.py
pause
