# ========================================
#  Step 5: 启动 SDI
# ========================================

$TEMP_DIR = "$env:TEMP\driver_installer"
$SDI_DIR = "$TEMP_DIR\SDI"

Write-Host ""
Write-Host "========================================"
Write-Host "  准备启动 SDI"
Write-Host "========================================"
Write-Host ""

# 查找 SDI 可执行文件
$sdiExe = $null
$found = Get-ChildItem -Path $SDI_DIR -Filter "SDI_x64*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $found) {
    $found = Get-ChildItem -Path $SDI_DIR -Filter "SDI_x86*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $found) {
    $found = Get-ChildItem -Path $SDI_DIR -Filter "SDI*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
}

if (-not $found) {
    Write-Host "[!] 找不到 SDI 可执行文件!"
    Write-Host ("  搜索路径: " + $SDI_DIR)
    Write-Host "  目录内容:"
    Get-ChildItem $SDI_DIR -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host ("    " + $_.Name + "  (" + [math]::Round($_.Length/1MB,1) + " MB)")
    }
    throw "SDI executable not found"
}

$sdiExe = $found.FullName
Write-Host ("[*] SDI 可执行文件: " + $found.Name)
Write-Host ""

# 列出下载的驱动包
Write-Host "[*] 已下载的驱动包:"
$driversDir = "$SDI_DIR\Drivers"
if (Test-Path $driversDir) {
    $pkgFiles = Get-ChildItem $driversDir -Filter "*.7z" -ErrorAction SilentlyContinue
    if ($pkgFiles.Count -gt 0) {
        foreach ($pkg in $pkgFiles) {
            Write-Host ("  " + $pkg.Name + "  (" + [math]::Round($pkg.Length/1MB,1) + " MB)")
        }
    } else {
        Write-Host "  (无)"
    }
} else {
    Write-Host "  (Drivers 目录不存在)"
}

# 列出索引文件
Write-Host ""
Write-Host "[*] 索引文件:"
$idxDir = "$SDI_DIR\Index\SDI"
if (Test-Path $idxDir) {
    $idxFiles = Get-ChildItem $idxDir -Filter "*.bin" -ErrorAction SilentlyContinue
    if ($idxFiles.Count -gt 0) {
        foreach ($idx in $idxFiles) {
            Write-Host ("  " + $idx.Name + "  (" + [math]::Round($idx.Length/1KB,1) + " KB)")
        }
    } else {
        Write-Host "  (无，SDI 启动后会重建)"
    }
} else {
    Write-Host "  (Index\SDI 目录不存在)"
}

Write-Host ""
Write-Host "[*] 正在启动 SDI (Snappy Driver Installer)..."
Write-Host ""
Write-Host "  提示:"
Write-Host "    1. SDI 窗口打开后，选择要安装驱动的设备"
Write-Host "    2. 点击 'Install' 安装驱动"
Write-Host "    3. 安装完成后重启电脑"
Write-Host ""

Start-Process -FilePath $sdiExe -WorkingDirectory $SDI_DIR

Write-Host "[+] SDI 已启动! 如未弹出窗口，请检查任务栏"
