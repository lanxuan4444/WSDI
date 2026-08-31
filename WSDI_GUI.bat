@echo off
title WSDI Driver Installer v3.0 GUI
echo ===============================================
echo         WSDI Driver Installer v3.0
echo    WPF GUI - Auto Detect + One-Click Install
echo ===============================================
echo.
echo Starting GUI Client...
echo.

set "SCRIPT_PATH=%~dp0WSDI_Client.ps1"

if not exist "%SCRIPT_PATH%" (
    echo [!] WSDI_Client.ps1 not found!
    echo     Please download the GUI client first.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%SCRIPT_PATH%"
exit /b %errorlevel%
