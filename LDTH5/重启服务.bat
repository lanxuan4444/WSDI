@echo off
chcp 65001 >nul 2>&1
title LDTools Restart
cd /d "%~dp0"

echo [1/3] Stopping old server (port 9876 only, other python services untouched)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:":9876 " ^| findstr /c:"LISTENING"') do taskkill /PID %%p /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/3] Starting server in background...
set "PYTHONW=%LocalAppData%\Programs\Python\Python315\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=pythonw.exe"
start "" /b "%PYTHONW%" server.py
timeout /t 5 /nobreak >nul

echo [3/3] Verify:
netstat -ano | findstr /c:":9876 " | findstr /c:"LISTENING"
echo server.pid:
type server.pid
echo.
echo Done. LISTENING PID must match server.pid above.
pause
