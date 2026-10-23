@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 备份 Cloudflare 隧道凭据
echo.
echo ========================================
echo   备份隧道凭据到 D:\Cloudflar\backup\
echo ========================================
echo.

set BACKUP_DIR=D:\Cloudflar\backup

if exist "%BACKUP_DIR%" (
    echo.
    echo ⚠️  备份目录已存在！即将覆盖旧备份。
    echo.
    set /p CONFIRM="确认覆盖？(Y/N): "
    if /i not "!CONFIRM!"=="Y" (
        echo 已取消。
        pause
        exit /b 0
    )
    rmdir /s /q "%BACKUP_DIR%"
)
mkdir "%BACKUP_DIR%"

echo [1/3] 备份 .cloudflared 证书和凭据...
xcopy "%USERPROFILE%\.cloudflared" "%BACKUP_DIR%\.cloudflared" /e /i /q /y

echo [2/3] 备份 config.yml...
copy /y "D:\Cloudflar\config.yml" "%BACKUP_DIR%\config.yml"

echo [3/3] 备份 启动隧道.bat...
copy /y "D:\Cloudflar\启动隧道.bat" "%BACKUP_DIR%\启动隧道.bat"

echo.
echo ========================================
echo   ✅ 备份完成！
echo.
echo   重装系统后，恢复步骤：
echo   1. 把 backup 文件夹拷回 D:\Cloudflar\
echo   2. 运行 D:\Cloudflar\恢复凭据.bat
echo   3. 双击 启动隧道.bat
echo ========================================
echo.
pause
