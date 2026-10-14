@echo off
chcp 65001 >nul 2>&1
title Backup Parts Archive
cd /d "%~dp0"

REM ==== LDTools 配件档案加密备份（7z AES-256，含文件名加密）====
REM 密码改这里（改完保存即可，备份文件名带日期自动滚动）
set "PASS=19008"
set "SEVENZIP=C:\Program Files\7-Zip\7z.exe"

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%d"
if not exist "Backups" mkdir "Backups"

echo [1/2] Packing Parts_Archive (photos + meta, exclude .thumbs cache and tmp) ...
"%SEVENZIP%" a -t7z -mx=9 -p%PASS% -mhe=on "Backups\Parts_%TS%.7z" ".\Parts_Archive" -xr!".thumbs" -xr!".tmp_*"
if errorlevel 1 (
  echo.
  echo [X] Backup FAILED.
  pause
  exit /b 1
)

echo.
echo [2/2] Done:
dir /b "Backups\Parts_%TS%.7z" | findstr /v "^$"
for %%F in ("Backups\Parts_%TS%.7z") do echo Size: %%~zF bytes
echo.
echo Encrypted with password (change PASS in this script).
echo Old backups keep rolling in Backups\ folder, delete manually if not needed.
pause
