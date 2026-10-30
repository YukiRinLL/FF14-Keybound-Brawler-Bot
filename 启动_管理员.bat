@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Check admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [UAC] Requesting admin...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ========================================
echo   FFXIV Auto Typing Helper (Admin Mode)
echo ========================================
echo.

python --version
echo.

echo [INFO] Starting main.py...
python main.py --autostart --interval 2.0 --pause-between 0.15

if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Exit code: %errorLevel%
    pause
)
