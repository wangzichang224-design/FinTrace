@echo off
chcp 65001 >nul

set "FINTRACE_ROOT=D:\03_AI_Projects\FinTrace"
cd /d "%FINTRACE_ROOT%"

echo Starting FinTrace frontend...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%FINTRACE_ROOT%\scripts\start_frontend.ps1" %*

echo.
echo FinTrace frontend session ended.
echo Press any key to close this window.
pause >nul
