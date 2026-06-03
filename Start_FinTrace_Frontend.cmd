@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting FinTrace frontend...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_frontend.ps1" %*

echo.
echo FinTrace frontend session ended.
echo Press any key to close this window.
pause >nul
