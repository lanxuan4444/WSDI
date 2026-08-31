@echo off
chcp 65001 >nul 2>&1
title LDTools
cd /d "%~dp0"

echo ============================================
echo   LDTools Log Viewer
echo ============================================
echo.

REM ---- 1. Check Python ----
echo [1/3] Python ...
set "PYTHON="
set "PYTHONW="
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
    set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
)
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python315\python.exe" (
    set "PYTHON=%LocalAppData%\Programs\Python\Python315\python.exe"
    set "PYTHONW=%LocalAppData%\Programs\Python\Python315\pythonw.exe"
)
if not defined PYTHON set "PYTHON=python.exe"
if not defined PYTHONW set "PYTHONW=pythonw.exe"
"%PYTHON%" --version >nul 2>&1
if %errorlevel% neq 0 goto :no_python
echo   [OK] Python found: %PYTHON%
echo.

REM ---- 2. Check pycryptodome ----
echo [2/3] pycryptodome ...
"%PYTHON%" -c "from Crypto.Cipher import AES" >nul 2>&1
if %errorlevel% neq 0 goto :install_dep
echo   [OK] pycryptodome ready
goto :check_files

:install_dep
echo   [..] installing pycryptodome ...
"%PYTHON%" -m pip install pycryptodome -q
if %errorlevel% neq 0 goto :dep_failed
echo   [OK] pycryptodome installed

REM ---- 2.5 Check pystray + pillow ----
echo.
echo [..] Checking pystray + pillow ...
"%PYTHON%" -c "import pystray; from PIL import Image" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [..] installing pystray pillow ...
    "%PYTHON%" -m pip install pystray pillow -q
)
echo   [OK] pystray + pillow ready
goto :check_files

:dep_failed
echo.
echo   [X] pip install failed
echo       Run manually: pip install pycryptodome
echo.
pause
exit /b 1

:no_python
echo.
echo   [X] Python not found
echo       Download: https://www.python.org/downloads/
echo       Check "Add Python to PATH" when installing
echo.
pause
exit /b 1

:check_files
REM ---- 3. Check files ----
echo.
echo [3/3] Checking files ...
if not exist "server.py" goto :no_file
if not exist "index.html" goto :no_file
echo   [OK] server.py + index.html
echo.
echo ============================================
echo   Starting server (background) ...
echo   Tray icon will appear in taskbar
echo   Right-click tray icon for menu
echo   Log: server.log
echo ============================================
echo.

REM ---- Open browser after 2 seconds ----
start "" /b cmd /c "ping -n 3 127.0.0.1 >nul & start http://localhost:9876"

REM ---- Start server with pythonw (NO console window) ----
start "" /b "%PYTHONW%" server.py

echo   Server started in background.
echo   Double-click tray icon or visit:
echo   http://localhost:9876
echo.

timeout /t 3 >nul
exit /b 0

:no_file
echo.
echo   [X] server.py or index.html not found
echo       Make sure start.bat is in the same folder
echo.
pause
exit /b 1
