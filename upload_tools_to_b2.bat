@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\WSDI\upload_tools_to_b2.ps1" %*
echo.
pause
