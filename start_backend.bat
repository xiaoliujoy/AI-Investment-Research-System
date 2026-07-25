@echo off
chcp 65001 >nul
echo ============================================
echo   Investment Research OS - Start Backend
echo ============================================
echo.

REM Python interpreter: prefer the env override, else "python" on PATH.
if defined WORKBUDDY_PYTHON (set "PYTHON=%WORKBUDDY_PYTHON%") else (set "PYTHON=python")

REM Repo-relative backend directory (this .bat lives at repo root).
set "BACKEND_DIR=%~dp0backend"

echo Starting backend service...
cd /d "%BACKEND_DIR%" || (echo [ERROR] cannot find backend dir & pause & exit /b 1)
start "Investment-Research-OS Backend" "%PYTHON%" -m uvicorn app:app --host 127.0.0.1 --port 8900

echo.
echo Backend started: http://127.0.0.1:8900
echo API docs:        http://127.0.0.1:8900/docs
echo.
echo In another terminal run the frontend:
echo   cd frontend
echo   pnpm dev
echo.
pause
