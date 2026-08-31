import os

FILES = {
    r'D:\WSDI\web\step1_hw.ps1': r"""$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] 正在检测硬件..." -ForegroundColor Yellow
$devices = @()
$output = pnputil /enum-devices /connected 2>$null
$lines = $output -split "`r`n"
$current = $null
foreach ($line in $lines) {
    if ($line -match '^Instance ID:\s*(.+)$') {
        if ($current) { $devices += $current }
        $current = @{ hwid = $Matches[1].Trim() }
    }
    if ($line -match '^Device Description:\s*(.+)$') {
        if ($current) { $current.description = $Matches[1].Trim() }
    }
}
if ($current) { $devices += $current }
$json = @{ devices = $devices } | ConvertTo-Json -Depth 3
New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
$json | Out-File -FilePath "$TEMP_DIR\hardware.json" -Encoding UTF8
$msg = "[+] 检测到 " + $devices.Count + " 个设备"
Write-Host $msg -ForegroundColor Green
""",

    r'D:\WSDI\web\step2_analyze.ps1': r"""$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] 正在服务器分析硬件..." -ForegroundColor Yellow
$body = Get-Content "$TEMP_DIR\hardware.json" -Raw -Encoding UTF8
try {
    $result = Invoke-RestMethod -Uri 'https://yanhong.online/api/analyze' -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
    if ($result.success) {
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  设备: " + $result.total_devices + "  |  驱动包: " + $result.matched_drivers + "  |  ~" + $result.total_size_mb + " MB (完整)")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $result | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\analysis.json" -Encoding UTF8
        Write-Host "[+] 分析完成!" -ForegroundColor Green
    } else {
        Write-Host ("[!] 错误: " + $result.error) -ForegroundColor Red
        exit 1
    }
} catch {
        Write-Host ("[!] 连接失败: " + $_.Exception.Message) -ForegroundColor Red
        Write-Host "[!] 请检查: https://yanhong.online" -ForegroundColor Red
    exit 1
}
""",

    r'D:\WSDI\web\step3_search.ps1': r"""$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] 正在精准搜索驱动 (可能需要几分钟)..." -ForegroundColor Yellow
$analysis = Get-Content "$TEMP_DIR\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$driverFiles = $analysis.drivers | ForEach-Object { $_.file }
$hwData = Get-Content "$TEMP_DIR\hardware.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$searchBody = @{ devices = $hwData.devices; drivers = $driverFiles } | ConvertTo-Json -Depth 5
Write-Host ("  正在扫描 " + $driverFiles.Count + " 个驱动包...") -ForegroundColor Gray
try {
    $searchResult = Invoke-RestMethod -Uri 'https://yanhong.online/api/search_and_pack' -Method Post -Body $searchBody -ContentType 'application/json; charset=utf-8' -TimeoutSec 900
    if ($searchResult.success) {
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  " + $searchResult.message)
        Write-Host ("  提取后大小: ~" + $searchResult.total_size_mb + " MB")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $searchResult | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\search_result.json" -Encoding UTF8
        Write-Host "[+] 搜索完成!" -ForegroundColor Green
    } else {
        Write-Host ("[!] 搜索失败: " + $searchResult.error) -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host ("[!] 搜索失败: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
""",

    r'D:\WSDI\web\step4_download.ps1': r"""$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] 正在下载匹配的驱动..." -ForegroundColor Yellow
$searchResult = Get-Content "$TEMP_DIR\search_result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$i = 0
$total = $searchResult.results.Count
foreach ($item in $searchResult.results) {
    $i++
    $label = if ($item.matched_folders -gt 0) { "[MATCH]" } else { "[FULL]" }
    Write-Host ("[" + $i + "/" + $total + "] " + $label + " " + $item.original + " (" + $item.extracted_size_mb + " MB)") -ForegroundColor Cyan
    $url = 'https://yanhong.online' + $item.download_url
    $outFile = Join-Path $TEMP_DIR $item.output_name
    try {
        Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600
        Write-Host '      OK' -ForegroundColor Green
    } catch {
        Write-Host ("      失败: " + $_.Exception.Message) -ForegroundColor Red
    }
}
Write-Host "[+] 下载完成!" -ForegroundColor Green
""",

    r'D:\WSDI\web\fallback.ps1': r"""$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] 备用方案: 下载完整驱动包..." -ForegroundColor Yellow
$analysis = Get-Content "$TEMP_DIR\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$total = $analysis.drivers.Count
$i = 0
foreach ($drv in $analysis.drivers) {
    $i++
    Write-Host ("[" + $i + "/" + $total + "] " + $drv.file + " (" + $drv.size_mb + " MB)") -ForegroundColor Yellow
    $url = 'https://yanhong.online' + $drv.download_url
    $outFile = Join-Path $TEMP_DIR $drv.file
    try { Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600 } catch { Write-Host 'FAIL' -ForegroundColor Red }
}
Write-Host "[+] 下载完成!" -ForegroundColor Green
""",
}

# Write with UTF-8 BOM (PowerShell default)
for path, content in FILES.items():
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(content)
    size = os.path.getsize(path)
    print(f'OK {path} ({size} bytes)')

# Also fix client.bat
client_bat = r"""@echo off
chcp 65001 >nul
title 在线驱动安装工具 - Client
cd /d "%~dp0"

echo ===============================================
echo        在线驱动安装工具 v2.3
echo   自动检测 + 精准匹配 + 一键安装
echo ===============================================
echo.

set "TEMP_DIR=%TEMP%\driver_installer"
if not exist "%TEMP_DIR%" mkdir "%TEMP_DIR%"

set "SERVER_URL=https://yanhong.online"

echo [*] 正在下载辅助脚本...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s='%SERVER_URL%'; $f='%TEMP_DIR%'; Invoke-WebRequest ($s+'/web/client_core.ps1') -OutFile ($f+'\client_core.ps1') -UseBasicParsing"
if errorlevel 1 (
    echo [!] 下载失败! 请检查网络或访问 https://yanhong.online
    pause
    exit /b 1
)
echo [+] 下载完成!
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP_DIR%\client_core.ps1"
set EXITCODE=%errorlevel%

if %EXITCODE% equ 0 (
    echo.
    echo ===============================================
    echo        安装完成!
    echo ===============================================
    echo.
    set /p REBOOT="是否立即重启? (Y/N): "
    if /i "%REBOOT%"=="Y" shutdown /r /t 5 /c "驱动安装完成，正在重启..."
) else (
    echo.
    echo [!] 安装过程中出现错误，请检查上面的日志。
)

echo.
pause
"""
with open(r'D:\WSDI\web\client.bat', 'w', encoding='utf-8-sig', newline='') as f:
    f.write(client_bat)
print(f'OK D:\\WSDI\\web\\client.bat')

# Also check if client_core.ps1 exists - if so, the server.py generates it on the fly, so no need
print('All files written')