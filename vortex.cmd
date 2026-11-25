@echo off
setlocal
cd /d "%~dp0"
python app.py %*
if "%~1"=="" pause
