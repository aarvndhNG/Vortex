@echo off
setlocal enabledelayedexpansion
title Vortex — Setup & Requirements Installer

echo =======================================================
echo          Vortex — Setup & Requirements Installer       
echo =======================================================
echo.

:: 1. Check Python
echo [*] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] Python is NOT installed or not on your PATH.
        echo [*] Attempting to install Python via winget...
        where winget >nul 2>&1
        if %errorlevel% equ 0 (
            winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
            echo [*] Please restart this installer after Python finishes installing.
            pause
            exit /b 1
        ) else (
            echo [!] Please download and install Python 3.9+ from:
            echo     https://www.python.org/downloads/
            echo     (Make sure to check "Add Python to PATH" during installation)
            pause
            exit /b 1
        )
    )
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
echo [OK] Found %PYTHON_VER%
echo.

:: 2. Upgrade pip and install Python packages
echo [*] Installing required Python libraries (yt-dlp, rich, flask)...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [!] Failed to install Python dependencies. Please check your internet connection.
    pause
    exit /b 1
)
echo [OK] Python dependencies installed successfully.
echo.

:: 3. Check FFmpeg
echo [*] Checking for FFmpeg (required for merging audio/video and MP3 conversion)...
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] FFmpeg is already installed and ready!
) else (
    echo [!] FFmpeg was not found on your system PATH.
    echo [*] Checking if winget is available to install FFmpeg automatically...
    where winget >nul 2>&1
    if %errorlevel% equ 0 (
        echo [*] Installing FFmpeg via winget (this may take a minute)...
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        if %errorlevel% equ 0 (
            echo [OK] FFmpeg installed successfully!
            echo [*] Note: You may need to reopen your terminal for FFmpeg to be detected.
        ) else (
            echo [!] Winget install was cancelled or encountered an error.
            goto MANUAL_FFMPEG
        )
    ) else (
        :MANUAL_FFMPEG
        echo.
        echo [!] Manual FFmpeg installation instructions:
        echo     1. Download ffmpeg from: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
        echo     2. Extract it, copy 'ffmpeg.exe' from the 'bin' folder, and paste it into this folder.
        echo.
    )
)

echo.
echo =======================================================
echo [OK] Setup complete!
echo You can now start Vortex by running:
echo   - vortex.cmd (or run.cmd)
echo   - python app.py
echo =======================================================
echo.
pause
