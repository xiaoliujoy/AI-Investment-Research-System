@echo off
chcp 65001 >nul
echo ============================================
echo   Investment Research OS - Daily Data Pipeline
echo   step1 (collect) -> step1b (tech) -> step2 -> step2b (memo)
echo ============================================
echo.

REM Python interpreter: prefer the env override, else "python" on PATH.
if defined WORKBUDDY_PYTHON (set "PYTHON=%WORKBUDDY_PYTHON%") else (set "PYTHON=python")

REM Repo-relative backend directory (this .bat lives at repo root).
set "BACKEND_DIR=%~dp0backend"

cd /d "%BACKEND_DIR%" || (echo [ERROR] cannot find backend dir & pause & exit /b 1)

echo Running daily pipeline...
echo.

"%PYTHON%" run_daily.py

echo.
echo ============================================
echo   Done! Artifacts:
echo     - output\memo_YYYY-MM-DD.html        (local OS2 memo)
echo     - output\memo_YYYY-MM-DD_wechat.html (WeChat inline, copy-paste to publish)
echo ============================================
pause
