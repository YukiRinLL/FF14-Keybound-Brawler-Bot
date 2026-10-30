@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Re-run as admin if not already
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [UAC] Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ========================================
echo   FF14 Keybound Brawler Bot (Admin)
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
