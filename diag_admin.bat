@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Admin Diagnostic
echo ========================================
echo.

:: 1. Admin check
echo [1] Admin check...
net session >nul 2>&1
if %errorLevel% equ 0 (
    echo     OK - Running as admin
) else (
    echo     FAIL - NOT admin! Right-click and Run as Administrator
    pause
    exit /b 1
)

:: 2. Python
echo.
echo [2] Python...
python --version
echo     Path:
where python

:: 3. Dependencies
echo.
echo [3] Dependencies...
python -c "import tkinter; print('     tkinter OK')" 2>nul || echo     FAIL tkinter
python -c "import rapidocr_onnxruntime; print('     rapidocr OK')" 2>nul || echo     FAIL rapidocr
python -c "import pyautogui; print('     pyautogui OK')" 2>nul || echo     FAIL pyautogui
python -c "import pyperclip; print('     pyperclip OK')" 2>nul || echo     FAIL pyperclip
python -c "import PIL; print('     PIL OK')" 2>nul || echo     FAIL PIL

:: 4. Syntax check
echo.
echo [4] Syntax check...
python -m py_compile main.py && echo     OK || echo     FAIL

:: 5. Run main.py
echo.
echo ========================================
echo   Launching main.py (errors shown below!)
echo ========================================
echo.
python main.py --autostart --interval 2.0 --pause-between 0.15

echo.
echo main.py exited, code: %errorLevel%
echo.
pause
