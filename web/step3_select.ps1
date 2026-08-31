# ========================================
#  Step 3: 选择要下载的驱动包
# ========================================

$TEMP_DIR = "$env:TEMP\driver_installer"
$SDI_DIR = "$TEMP_DIR\SDI"
$SDI_DRIVERS_DIR = "$SDI_DIR\Drivers"

# 从服务端获取的分析结果
$analyzeResult = Get-Content "$TEMP_DIR\analyze_result.json" -Raw | ConvertFrom-Json

if (-not $analyzeResult.success) {
    Write-Host "[!] 驱动分析失败: $($analyzeResult.error)"
    throw "Analyze failed"
}

# 强制转为数组（单个元素时 ConvertFrom-Json 返回对象而非数组）
$drivers = @($analyzeResult.drivers)

if ($drivers.Count -eq 0) {
    Write-Host "[!] 没有找到匹配的驱动包!"
    throw "No drivers matched"
}

# 分类标签
$catLabels = @{
    "Audio"   = "声卡"
    "Lan"     = "有线网卡"
    "Wlan"    = "无线网卡"
    "Blue"    = "蓝牙"
    "Chipset" = "芯片组"
    "Vga"     = "显卡"
    "Touch"   = "触控"
    "IO"      = "IO/串口"
    "Modem"   = "调制解调器"
    "Mass"    = "大容量存储"
    "Camera"  = "摄像头"
    "Card"    = "读卡器"
    "Monitor" = "显示器"
    "USB"     = "USB"
    "TV"      = "电视卡"
    "HID"     = "人体学输入"
    "Sensor"  = "传感器"
}

# 超大驱动阈值 (MB)
$HUGE_THRESHOLD_MB = 3072  # 3GB

Write-Host ""
Write-Host "========================================"
Write-Host "  选择要下载的驱动包"
Write-Host "========================================"
Write-Host ""
Write-Host ("  共找到 " + $drivers.Count + " 个匹配的驱动包，总计 " + $analyzeResult.total_size_mb + " MB")

# 构建选择列表
$index = 0
$selected = @()  # 每个索引是否选中
$info = @()      # 每个索引的显示信息
$hasSpecialDriver = $false  # 是否存在需要用户确认的驱动（显卡或 >3GB）

foreach ($drv in $drivers) {
    $cat = $drv.category
    $label = if ($catLabels.ContainsKey($cat)) { $catLabels[$cat] } else { $cat }
    $sizeMB = $drv.size_mb

    # 显示匹配的设备
    $devNames = @()
    foreach ($dev in $drv.matched_devices) {
        $desc = if ($dev.description -and $dev.description -ne $dev.hwid) { $dev.description } else { "未知" }
        $devNames += $desc
    }
    $devStr = ($devNames | Select-Object -Unique) -join ", "

    # 默认勾选规则：
    # 1) 显卡(Vga)不勾选
    # 2) 超大驱动(>3GB)不勾选
    # 3) 其余全部默认勾选
    $isVga = ($cat -eq "Vga")
    $isHuge = $sizeMB -gt $HUGE_THRESHOLD_MB
    $defaultChecked = (-not $isVga) -and (-not $isHuge)

    # 只要存在 VGA 或 >3GB 的驱动，就需要进入交互菜单让用户确认
    if ($isVga -or $isHuge) {
        $hasSpecialDriver = $true
    }

    $selected += $defaultChecked
    $check = if ($defaultChecked) { "[x]" } else { "[ ]" }

    $info += @{
        file      = $drv.file
        name      = $drv.name
        size_mb   = $sizeMB
        cat       = $cat
        label     = $label
        isHuge    = $isHuge
        devStr    = $devStr
        dlUrl     = $drv.download_url
        binFile   = $drv.bin_file
    }

    $sizeStr = if ($sizeMB -gt 1000) { ("{0:N1} GB" -f ($sizeMB / 1024)) } else { ("{0:N0} MB" -f $sizeMB) }
    $idxStr = ("{0,2}" -f ($index + 1))
    Write-Host ("  " + $check + " " + $idxStr + "  " + $sizeStr.PadLeft(10) + "  [" + $label + "]")
    Write-Host ("      " + $devStr)
    Write-Host ("      文件: " + $drv.file)
    $index++
}

# 没有特殊驱动（显卡或 >3GB）时，跳过交互，直接按默认规则下载
if (-not $hasSpecialDriver) {
    $selCount = ($selected | Where-Object { $_ }).Count
    Write-Host ""
    Write-Host ("[*] 无显卡/超大驱动，自动选择 " + $selCount + " 个包，无需确认...")
} else {
    # 存在特殊驱动，进入交互确认
    Write-Host ""
    Write-Host ("  操作: 输入数字切换选择 (如: 1 2 3) | a=全选 n=全不选 | 回车=确认 q=退出")
    Write-Host ("  显卡(VGA)及超大驱动(>3GB)默认不勾选")
    Write-Host ""

    while ($true) {
        $input = Read-Host "  选择"
        $input = $input.Trim()

        if ($input -eq "" -or $input -eq "ok") {
            break
        }
        if ($input -eq "q") {
            Write-Host "[!] 用户取消"
            throw "User cancelled"
        }
        if ($input -eq "a") {
            for ($i = 0; $i -lt $selected.Count; $i++) { $selected[$i] = $true }
        }
        elseif ($input -eq "n") {
            for ($i = 0; $i -lt $selected.Count; $i++) { $selected[$i] = $false }
        }
        else {
            # 直接选中模式：输入的数字 = 选中的项，其他全部取消
            $nums = $input -split '\s+' | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ }
            if ($nums.Count -gt 0) {
                for ($i = 0; $i -lt $selected.Count; $i++) { $selected[$i] = $false }
                foreach ($n in $nums) {
                    $idx = $n - 1
                    if ($idx -ge 0 -and $idx -lt $selected.Count) {
                        $selected[$idx] = $true
                    }
                }
            }
        }

        # 重新显示
        Write-Host ""
        $totalSelectedMB = 0
        for ($i = 0; $i -lt $info.Count; $i++) {
            $it = $info[$i]
            $check = if ($selected[$i]) { "[x]" } else { "[ ]" }
            $sizeStr = if ($it.size_mb -gt 1000) { ("{0:N1} GB" -f ($it.size_mb / 1024)) } else { ("{0:N0} MB" -f $it.size_mb) }
            $idxStr = ("{0,2}" -f ($i + 1))
            $line = "  " + $check + " " + $idxStr + "  " + $sizeStr.PadLeft(10) + "  [" + $it.label + "]"
            Write-Host $line
            Write-Host ("      " + $it.devStr)
            if ($selected[$i]) { $totalSelectedMB += $it.size_mb }
        }
        $totalStr = if ($totalSelectedMB -gt 1000) { ("{0:N1} GB" -f ($totalSelectedMB / 1024)) } else { ("{0:N0} MB" -f $totalSelectedMB) }
        $selCount = ($selected | Where-Object { $_ }).Count
        Write-Host ("  已选: " + $selCount + "/" + $info.Count + " 个包, 总计 " + $totalStr)
        Write-Host ""
    }
}

# 收集选中的驱动
$selectedDrivers = @()
for ($i = 0; $i -lt $info.Count; $i++) {
    if ($selected[$i]) {
        $selectedDrivers += $info[$i]
    }
}

if ($selectedDrivers.Count -eq 0) {
    Write-Host "[!] 未选择任何驱动包!"
    throw "No drivers selected"
}

# 保存选中结果
$selectedDrivers | ConvertTo-Json -Depth 3 | Set-Content "$TEMP_DIR\selected_drivers.json" -Encoding UTF8

$totalSelMB = 0
foreach ($s in $selectedDrivers) { $totalSelMB += [double]$s["size_mb"] }
$totalStr = if ($totalSelMB -gt 1000) { ("{0:N1} GB" -f ($totalSelMB / 1024)) } else { ("{0:N0} MB" -f $totalSelMB) }
Write-Host ""
Write-Host ("[+] 已选择 " + $selectedDrivers.Count + " 个驱动包, 总计 " + $totalStr)
