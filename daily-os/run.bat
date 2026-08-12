@echo off
cd /d "%~dp0"
start "" "C:\Users\JOY\.workbuddy\binaries\python\versions\3.13.12\python.exe" app.py
timeout /t 2 >nul
start "" http://127.0.0.1:8777
