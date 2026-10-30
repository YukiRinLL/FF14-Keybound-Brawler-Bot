@echo off

echo ============================================

echo   Interception Driver Installer

echo ============================================

echo.

cd /d "%~dp0"

if not exist "Interception\command line installer\install-interception.exe" (

    echo ERROR: installer not found

    pause

    exit /b 1

)

echo Installing driver...

"Interception\command line installer\install-interception.exe" /install

echo.

echo Return code: %errorlevel%

echo.

echo Done.

pause

