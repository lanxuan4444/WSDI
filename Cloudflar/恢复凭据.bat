@echo off
chcp 65001 >nul
title 恢复 Cloudflare 隧道凭据
echo.
echo ========================================
echo   恢复隧道凭据（重装后运行此脚本）
echo ========================================
echo.

set BACKUP_DIR=D:\Cloudflar\backup

if not exist "%BACKUP_DIR%\.cloudflared" (
    echo ❌ 未找到备份！请先把 backup 文件夹放在 D:\Cloudflar 下
    pause
    exit /b 1
)

echo [1/2] 恢复 .cloudflared 凭据...
if not exist "%USERPROFILE%\.cloudflared" mkdir "%USERPROFILE%\.cloudflared"
xcopy "%BACKUP_DIR%\.cloudflared\*" "%USERPROFILE%\.cloudflared\" /e /i /q /y

echo [2/2] 恢复 config.yml 和启动脚本...
copy /y "%BACKUP_DIR%\config.yml" "D:\Cloudflar\config.yml"
copy /y "%BACKUP_DIR%\启动隧道.bat" "D:\Cloudflar\启动隧道.bat"

echo.
echo ========================================
echo   ✅ 恢复完成！现在可以启动了
echo ========================================
echo.
pause
