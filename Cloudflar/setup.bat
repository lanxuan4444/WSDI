@echo off
title Cloudflare 隧道一键配置
chcp 65001 >nul
setlocal enabledelayedexpansion

D:
cd \Cloudflar

echo ========================================
echo   Cloudflare 命名隧道配置工具
echo ========================================
echo.

echo [1/4] 正在打开浏览器登录 Cloudflare...
echo 如果浏览器没自动打开，请手动复制下面显示的链接
echo.
cloudflared.exe tunnel login
if %errorlevel% neq 0 (
    echo 登录失败！请检查网络后重试。
    pause
    exit /b 1
)
echo.

echo [2/4] 检查是否已有隧道...
cloudflared.exe tunnel list 2>nul | findstr "mytunnel" >nul
if %errorlevel% equ 0 (
    echo [!] 已存在名为 mytunnel 的隧道
    set /p choice="是否删除并重建？(y/n): "
    if /i "!choice!"=="y" (
        for /f "tokens=1" %%i in ('cloudflared.exe tunnel list 2^>nul ^| findstr "mytunnel"') do (
            cloudflared.exe tunnel delete -f %%i 2>nul
        )
        echo 已删除旧隧道
    ) else (
        for /f "tokens=1" %%i in ('cloudflared.exe tunnel list 2^>nul ^| findstr "mytunnel"') do (
            set TUNNEL_ID=%%i
        )
        echo 使用现有隧道: !TUNNEL_ID!
        goto :makeConfig
    )
)

echo [3/4] 正在创建命名隧道...
for /f "tokens=1 delims= " %%i in ('cloudflared.exe tunnel create mytunnel 2^>^&1 ^| findstr /r "[a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9][a-f0-9]-"') do (
    set TUNNEL_ID=%%i
)

if "!TUNNEL_ID!"=="" (
    echo 无法提取隧道 ID，请检查 cloudflared 输出
    pause
    exit /b 1
)

:makeConfig
echo 隧道 ID: !TUNNEL_ID!
echo.

echo [4/4] 正在生成配置文件...
(
echo tunnel: !TUNNEL_ID!
echo credentials-file: C:\Users\Administrator\.cloudflared\!TUNNEL_ID!.json
echo.
echo ingress:
echo   - hostname: mydata.djyanhong09.workers.dev
echo     service: http://localhost:8080
echo   - service: http_status:404
) > config.yml

echo config.yml 已生成！
echo.

echo ========================================
echo   ✅ 配置完成！
echo ========================================
echo.
echo 📋 你的隧道 UUID:
echo    !TUNNEL_ID!
echo.
echo 📝 接下来：
echo    1. 复制上面的 UUID
echo    2. 去 Cloudflare Workers 编辑 mydata 的代码
echo    3. 把 Worker 代码里的 PASTE_YOUR_TUNNEL_UUID_HERE 替换成这个 UUID
echo    4. 部署 Worker
echo    5. 双击【启动隧道.bat】启动
echo.
pause
