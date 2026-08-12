@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
    echo [ERROR] File .env not found. Copy .env.example to .env and fill it.
    pause
    exit /b 1
)

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

"%PYTHON%" main.py
