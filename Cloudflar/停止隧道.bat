@echo off
title 停止 Cloudflare Tunnel
echo 正在停止 Cloudflare Tunnel...
taskkill /f /im cloudflared.exe 2>nul
if %errorlevel% equ 0 (
    echo 隧道已停止。
) else (
    echo 没有运行中的隧道。
)
timeout /t 2 >nul
