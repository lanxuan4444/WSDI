@echo off
title Cloudflare Tunnel - mytunnel2
chcp 65001 >nul
D:
cd \Cloudflar

::: 凭据目录
set CERT_DIR=%USERPROFILE%\.cloudflared

::: 占位 cert.pem
set CERT_FILE=%CERT_DIR%\cert.pem
if not exist "%CERT_FILE%" (
    > "%CERT_FILE%" echo.
)
set TUNNEL_ORIGIN_CERT=%CERT_FILE%

echo ========================================
echo   Cloudflare 命名隧道正在启动...
echo   目标: http://localhost:8080
echo   域名: https://mydata.yanhong.online
echo ========================================
echo.
echo 按 Ctrl+C 停止隧道
echo.

::: 用 UUID 启动（--protocol quic 可改善国内连接）
cloudflared.exe tunnel --no-autoupdate --protocol quic --config config.yml run 2967bed7-9021-4ed4-bf20-9b2658ba516c

if %errorlevel% neq 0 (
    echo.
    echo 启动失败，错误码: %errorlevel%
    pause
)
