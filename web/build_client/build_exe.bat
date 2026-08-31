@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   WSDI GUI Client - Build EXE
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.8+.
    pause
    exit /b 1
)

:: Install dependencies
echo [1/3] Installing dependencies...
pip install pyinstaller -q
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install pyinstaller
    pause
    exit /b 1
)

:: Build EXE (single file, no console window)
echo [2/3] Building WSDI_Client.exe...
pyinstaller --onefile --windowed ^
    --name "WSDI_Client" ^
    --icon=NONE ^
    --add-data "wsdi_core.py;." ^
    --hidden-import tkinter ^
    --clean ^
    wsdi_gui.py

if %errorlevel% neq 0 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

:: Move EXE to parent directory
echo [3/3] Copying EXE...
copy /y "dist\WSDI_Client.exe" "..\WSDI_Client.exe" >nul

echo.
echo ================================================
echo   Build SUCCESS!
echo   Output: web\WSDI_Client.exe
echo ================================================
echo.
echo To run: Just double-click WSDI_Client.exe
echo.
pause
