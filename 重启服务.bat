@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set PYTHON=C:\Users\Administrator\AppData\Local\Programs\Python\Python315\python.exe
set PYTHONW=C:\Users\Administrator\AppData\Local\Programs\Python\Python315\pythonw.exe
set TRAY_SCRIPT=D:\WSDI\WSDI_Tray.py

echo ============================================
echo   重启 WSDI 全部服务
echo ============================================
echo.

:kill_all
REM ============================================================
REM [1/3] 彻底杀掉所有相关进程（多轮 + 验证）
REM ============================================================
echo [1/3] 停止所有进程...

REM 多轮杀进程：确保所有 python 和 cloudflared 都死透
for /l %%r in (1,1,3) do (
    REM 停止托盘进程
    powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $name = 'WSDI_Tray'; $p = Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*WSDI*' -or $_.Path -eq '%PYTHON%' -or $_.Path -eq '%PYTHONW%' }; if ($p) { $p | Stop-Process -Force -ErrorAction SilentlyContinue; Write-Host 'Killed tray/worker processes' } else { Write-Host 'No tray/worker found' } }"

    REM 杀掉所有 python 系进程
    powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $p = Get-Process python,pythonw -ErrorAction SilentlyContinue; if ($p) { $p | ForEach-Object { try { taskkill /F /PID $_.Id 2>$null } catch {} }; Write-Host ('Killed ' + $p.Count + ' Python process(es)') } else { Write-Host 'No Python process found' } }"

    REM 杀 cloudflared
    powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $p = Get-Process cloudflared -ErrorAction SilentlyContinue; if ($p) { try { taskkill /F /PID $p.Id 2>$null } catch {}; Write-Host 'Killed cloudflared' } else { Write-Host 'No cloudflared found' } }"

    timeout /t 2 /nobreak >nul
)

REM 最终验证：确保一个都不剩
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $remaining = @(Get-Process python,pythonw,cloudflared -ErrorAction SilentlyContinue); if ($remaining.Count -eq 0) { Write-Host '[OK] All processes stopped' } else { Write-Host ('[WARN] ' + $remaining.Count + ' process(es) still alive, force killing...'); $remaining | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2; $final = @(Get-Process python,pythonw,cloudflared -ErrorAction SilentlyContinue); if ($final.Count -eq 0) { Write-Host '[OK] Force kill succeeded' } else { Write-Host ('[FAIL] ' + $final.Count + ' process(es) could NOT be killed!') } } }"

echo.

REM ============================================================
REM [2/3] 等待端口释放
REM ============================================================
echo       等待端口释放...
timeout /t 2 /nobreak >nul
echo       完成
echo.

REM ============================================================
REM [3/3] 启动 WSDI 托盘（托管 server + ldth5 + tunnel）
REM ============================================================
echo [2/3] 启动 WSDI 服务...

REM 使用系统托盘方式启动（隐藏窗口，管理全部子进程）
start "" "%PYTHONW%" "%TRAY_SCRIPT%"

REM 等待启动
timeout /t 6 /nobreak >nul

REM 验证
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1/api/health' -UseBasicParsing -TimeoutSec 5; Write-Host '[OK] API health check: ' $r.StatusCode } catch { Write-Host '[WARN] Port 80 not responding yet (may need more time)' } }"
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $p = @(Get-Process python,pythonw -ErrorAction SilentlyContinue); $c = @(Get-Process cloudflared -ErrorAction SilentlyContinue); Write-Host ('[INFO] Running: ' + ($p.Count + $c.Count) + ' process(es) - ' + $p.Count + ' Python + ' + $c.Count + ' cloudflared') }"

echo.
echo ============================================
echo   重启完成！
echo   WSDI 访问地址: https://yanhong.online
echo ============================================
echo.
echo 提示: 右键系统托盘图标可查看日志 / 重启
echo.
pause
