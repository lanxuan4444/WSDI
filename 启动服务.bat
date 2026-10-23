@echo off
chcp 65001 >nul
title WSDI Service Panel

set PYTHON=C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe
set CLOUDFLARED=D:\WSDI\Cloudflar\cloudflared.exe
set SERVER_DIR=D:\WSDI\server
set CONFIG=D:\WSDI\cloudflared-config.yml

echo ============================================
echo   启动在线驱动安装服务
echo ============================================
echo.
echo  [前台模式 - 可看到实时日志]
echo.

REM 先杀掉可能残留的旧进程
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2"

REM 1. 启动 Python 后端（80端口）
echo [1/2] 启动 Python 后端服务 (端口 80)...
start "WSDI-Server" cmd /c "cd /d %SERVER_DIR% && %PYTHON% server.py"
echo       等待启动...
timeout /t 3 /nobreak >nul

REM 2. 启动 Cloudflare Tunnel
echo [2/2] 启动 Cloudflare Tunnel...
echo.
echo   主站:     https://yanhong.online
echo   本地:     http://localhost:80
echo.
echo 按 Ctrl+C 停止所有服务
echo ============================================

%CLOUDFLARED% tunnel --config %CONFIG% run

echo.
echo Tunnel 已停止
taskkill /FI "WINDOWTITLE eq WSDI-Server" /F >nul 2>&1
pause
