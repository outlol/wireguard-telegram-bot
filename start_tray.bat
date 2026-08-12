@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
    echo [ERROR] File .env not found. Copy .env.example to .env and fill it.
    pause
    exit /b 1
)

set "PYTHONW=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "PYTHONW=.venv\Scripts\pythonw.exe"

start "" "%PYTHONW%" tray.py
