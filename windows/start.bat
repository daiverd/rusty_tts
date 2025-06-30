@echo off
echo Starting Windows TTS Service...
echo Python 2.7 / Windows XP Compatible

REM Check if Python 2.7 is available
python --version 2>nul
if errorlevel 1 (
    echo Error: Python not found in PATH
    pause
    exit /b 1
)

REM Check if balcon.exe exists
if not exist "balcon.exe" (
    echo Warning: balcon.exe not found in current directory
    echo Please copy balcon.exe to this directory
    pause
)

REM Create audio files directory if it doesn't exist
if not exist "audio_files" (
    echo Creating audio_files directory...
    mkdir audio_files
)

REM Start the service
echo Starting Flask service on port 5000...
python app.py

pause