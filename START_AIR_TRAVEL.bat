@echo off
cd /d "%~dp0"
title AIR TRAVEL - Local Website
 echo ========================================
 echo           AIR TRAVEL STARTER
 echo ========================================
 echo.
python --version
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer, then try again.
  pause
  exit /b 1
)
echo.
echo Installing website packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check your internet connection and Python installation.
  pause
  exit /b 1
)
echo.
echo Starting AIR TRAVEL. Keep this window open.
echo Open Chrome at http://127.0.0.1:5000
 echo.
python app.py
echo.
echo AIR TRAVEL has stopped. If an error appeared above, take a screenshot of this window.
pause
