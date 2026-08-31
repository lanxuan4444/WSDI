<#
WSDI Client Core v5.0
新流程（不依赖SDI日志）：
  1. 下载 SDI 便捷版 + 7z + 解压
  2. 用 WMI 直接获取本机所有设备 HWID
  3. 上传 HWID 到服务器 → 服务器用 .bin 索引精确匹配
  4. 下载匹配到的 .7z + .bin
  5. SDI 正常启动，用户点击安装
#>

param(
    [string]$Server = "yanhong.online"
)

# Force UTF-8 output to avoid garbled text
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# ============================================================
# Config
# ============================================================
$BaseURL      = "https://$Server"
$TempDir      = Join-Path $env:TEMP "WSDI"
$SDIDir       = Join-Path $TempDir "SDI"
$DriversDir   = Join-Path $SDIDir "Drivers"
$IndexDir     = Join-Path $SDIDir "Index\SDI"
$ToolsDir     = Join-Path $TempDir "tools"
$LogDir       = $SDIDir  # SDI 会把日志写到当前工作目录的 logs/

$SdiLite7z    = Join-Path $TempDir "SDI_R2601.7z"
$Zip7z        = Join-Path $ToolsDir "7z_portable.zip"
$SevenZipExe  = Join-Path $ToolsDir "7z.exe"
$SdiExe       = Join-Path $SDIDir "SDI_x64_R2606.exe"

# COS bucket info (must match server.py)
$CosBase      = "https://wsdi-drivers-2026-1449166909.cos.ap-guangzhou.myqcloud.com"
$CosDrivers   = "$CosBase/Drivers"
$CosIndex     = "$CosBase/Index/SDI"

# ============================================================
# Helper Functions
# ============================================================
function Write-Step($msg) { Write-Host "`n[$([char]0x25B6)] $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "  ... $msg" -ForegroundColor Gray }

# Strip instance suffix to get base HWID
function Get-BaseHwid($hwid) {
    # 保留 VID/PID 等关键 ID，只去掉 SUBSYS 和 REV（这些是机器特定的）
    # 例如 USB\VID_8087&PID_0A2A&REV_0001 -> USB\VID_8087&PID_0A2A
    #      PCI\VEN_10EC&DEV_8168&SUBSYS_36F217AA&REV_0C -> PCI\VEN_10EC&DEV_8168
    $h = $hwid.ToUpper().Trim()
    # 去掉 &REV_xxx 部分
    $h = $h -replace '&REV_[0-9A-F]+$', ''
    # 去掉 &SUBSYS_xxx 部分
    $h = $h -replace '&SUBSYS_[0-9A-F]+', ''
    return $h
}

function Format-Bytes($bytes) {
    if ($bytes -ge 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
    if ($bytes -ge 1MB) { return "{0:N2} MB" -f ($bytes / 1MB) }
    if ($bytes -ge 1KB) { return "{0:N2} KB" -f ($bytes / 1KB) }
    return "$bytes B"
}

$script:ProgressLineLength = 0
function Write-ProgressLine($percent, $desc, $downloadedStr, $totalStr, $speedStr, $extra = "") {
    $barLen = 20
    $filled = [math]::Floor($percent / 100 * $barLen)
    if ($filled -lt 0) { $filled = 0 }
    if ($filled -gt $barLen) { $filled = $barLen }
    $empty = $barLen - $filled
    $bar = ("█" * $filled) + ("░" * $empty)
    $line = "  [$bar] {0,5:N1}%  {1,8} / {2,8}  {3,10}  {4} {5}" -f $percent, $downloadedStr, $totalStr, $speedStr, $desc, $extra
    if ($line.Length -lt $script:ProgressLineLength) {
        $line = $line + (" " * ($script:ProgressLineLength - $line.Length))
    }
    $script:ProgressLineLength = $line.Length
    Write-Host "`r$line" -NoNewline -ForegroundColor Cyan
}
function Clear-ProgressLine() {
    if ($script:ProgressLineLength -gt 0) {
        Write-Host ("`r" + (" " * $script:ProgressLineLength) + "`r") -NoNewline
        $script:ProgressLineLength = 0
    }
}

# 单文件流式下载
function Download-File($url, $dest, $desc) {
    Write-Host "  [↓] 准备下载 $desc" -ForegroundColor Gray
    try {
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Timeout = 120000
        $req.ReadWriteTimeout = 120000
        $req.UserAgent = "WSDI-Client/4.0"
        $req.KeepAlive = $true
        $req.AllowAutoRedirect = $true   # 跟随 302 到 B2
        $req.Headers.Add("Accept-Encoding", "identity")  # 大文件不压缩
        $resp = $req.GetResponse()
        $total = $resp.ContentLength
        $stream = $resp.GetResponseStream()
        $fs = [System.IO.File]::Create($dest)
        $buf = New-Object byte[] 131072
        $read = 0
        $downloaded = 0
        $lastReport = [DateTime]::Now
        $startTime = [DateTime]::Now
        $reportInterval = [TimeSpan]::FromMilliseconds(300)

        do {
            $read = $stream.Read($buf, 0, $buf.Length)
            if ($read -gt 0) {
                $fs.Write($buf, 0, $read)
                $downloaded += $read
            }
            $now = [DateTime]::Now
            if (($now - $lastReport) -ge $reportInterval -or $read -eq 0) {
                $pct = if ($total -gt 0) { [math]::Round($downloaded / $total * 100, 1) } else { 100.0 }
                $secs = ($now - $startTime).TotalSeconds
                $speed = if ($secs -gt 0) { $downloaded / $secs } else { 0 }
                $speedStr = (Format-Bytes $speed) + "/s"
                Write-ProgressLine $pct $desc (Format-Bytes $downloaded) (Format-Bytes $total) $speedStr
                $lastReport = $now
            }
        } while ($read -gt 0)

        $fs.Close()
        $stream.Close()
        $resp.Close()
        Clear-ProgressLine
        Write-OK "$desc 下载完成 ($(Format-Bytes $downloaded))"
        return $true
    }
    catch {
        Clear-ProgressLine
        Write-Err "下载失败: $desc`n  $($_.Exception.Message)"
        return $false
    }
}

# 多文件并行下载
function Invoke-ParallelDownloads($tasks) {
    $jobs = @()
    $taskMap = @{}
    $id = 0
    foreach ($task in $tasks) {
        $id++
        $taskMap[$id] = $task
        $partFile = "$($task.Dest).part"
        if (Test-Path $partFile) { Remove-Item $partFile -Force }
        $job = Start-Job -ScriptBlock {
            param($url, $dest, $desc)
            try {
                $req = [System.Net.HttpWebRequest]::Create($url)
                $req.Timeout = 120000
                $req.ReadWriteTimeout = 120000
                $req.UserAgent = "WSDI-Client/4.0"
                $resp = $req.GetResponse()
                $total = $resp.ContentLength
                $stream = $resp.GetResponseStream()
                $fs = [System.IO.File]::Create($dest)
                $buf = New-Object byte[] 131072
                $read = 0
                $downloaded = 0
                $reportInterval = [TimeSpan]::FromMilliseconds(500)
                $lastReport = [DateTime]::Now
                $startTime = [DateTime]::Now
                $statusFile = "$dest.status"
                do {
                    $read = $stream.Read($buf, 0, $buf.Length)
                    if ($read -gt 0) {
                        $fs.Write($buf, 0, $read)
                        $downloaded += $read
                    }
                    $now = [DateTime]::Now
                    if (($now - $lastReport) -ge $reportInterval -or $read -eq 0) {
                        $pct = if ($total -gt 0) { [math]::Round($downloaded / $total * 100, 1) } else { 0 }
                        $secs = ($now - $startTime).TotalSeconds
                        $speed = if ($secs -gt 0) { $downloaded / $secs } else { 0 }
                        $status = "{0}|{1}|{2}|{3}|{4}" -f $pct, $downloaded, $total, $speed, $desc
                        # Retry write to .status file (main thread may be reading
                        # it concurrently; "file in use" errors are transient).
                        $writeOk = $false
                        for ($wRetry = 0; $wRetry -lt 5 -and -not $writeOk; $wRetry++) {
                            try {
                                [System.IO.File]::WriteAllText($statusFile, $status)
                                $writeOk = $true
                            } catch {
                                Start-Sleep -Milliseconds 50
                            }
                        }
                        $lastReport = $now
                    }
                } while ($read -gt 0)
                $fs.Close(); $stream.Close(); $resp.Close()
                if (Test-Path $statusFile) { Remove-Item $statusFile -Force }
                return @{ Status = "OK"; Dest = $dest; Desc = $desc; Bytes = $downloaded }
            }
            catch {
                return @{ Status = "ERR"; Dest = $dest; Desc = $desc; Error = $_.Exception.Message }
            }
        } -ArgumentList $task.Url, $task.Dest, $task.Desc
        $jobs += $job
    }

    $startTime = [DateTime]::Now
    $completed = 0
    while ($completed -lt $jobs.Count) {
        Start-Sleep -Milliseconds 800
        $completed = ($jobs | Where-Object { $_.State -in @("Completed", "Failed", "Stopped") }).Count
        $now = [DateTime]::Now
        $totalDownloaded = 0
        $totalExpected = 0
        foreach ($id in $taskMap.Keys) {
            $t = $taskMap[$id]
            $totalExpected += $t.Size
            $sf = "$($t.Dest).status"
            $readOk = $false
            if (Test-Path $sf) {
                # Retry read (worker thread may be writing concurrently)
                for ($rRetry = 0; $rRetry -lt 3 -and -not $readOk; $rRetry++) {
                    try {
                        $parts = ([System.IO.File]::ReadAllText($sf) -split "\|")
                        if ($parts.Count -ge 2) {
                            $totalDownloaded += [long]$parts[1]
                        }
                        $readOk = $true
                    } catch {
                        Start-Sleep -Milliseconds 30
                    }
                }
            }
            if (-not $readOk -and (Test-Path $t.Dest)) {
                $totalDownloaded += (Get-Item $t.Dest).Length
            }
        }
        $pct = if ($totalExpected -gt 0) { [math]::Round($totalDownloaded / $totalExpected * 100, 1) } else { 0 }
        $secs = ($now - $startTime).TotalSeconds
        $speed = if ($secs -gt 0) { $totalDownloaded / $secs } else { 0 }
        $speedStr = (Format-Bytes $speed) + "/s"
        Write-ProgressLine $pct "并行下载 [$completed/$($jobs.Count)]" (Format-Bytes $totalDownloaded) (Format-Bytes $totalExpected) $speedStr
    }
    Clear-ProgressLine

    $results = @()
    foreach ($job in $jobs) {
        $r = Receive-Job $job
        Remove-Job $job -Force
        $results += $r
        if ($r.Status -eq "OK") {
            Write-OK "$($r.Desc) 完成 ($(Format-Bytes $r.Bytes))"
        }
        else {
            Write-Err "$($r.Desc) 失败: $($r.Error)"
        }
    }
    return $results
}

# ============================================================
# Header
# ============================================================
Clear-Host
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "    WSDI 驱动安装工具 v5.0" -ForegroundColor White
Write-Host "    服务器: $Server" -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Cyan

# ============================================================
# Step 0: 准备环境
# ============================================================
Write-Step "第 0 步：准备环境..."

$dirs = @($TempDir, $SDIDir, $DriversDir, $IndexDir, $ToolsDir)
foreach ($d in $dirs) {
    if (!(Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}
Write-OK "临时目录: $TempDir"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---- 下载 7-Zip ----
if (!(Test-Path $SevenZipExe)) {
    if (!(Download-File "$BaseURL/api/7z_portable" $Zip7z "7-Zip 便携版")) {
        Write-Err "无法下载 7-Zip，已中止。"
        exit 1
    }
    Write-Info "正在解压 7-Zip..."
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip7z, $ToolsDir)
        Write-OK "7-Zip 就绪"
    }
    catch {
        Write-Err "解压 7-Zip 失败: $($_.Exception.Message)"
        exit 1
    }
}
else {
    Write-OK "7-Zip 已存在"
}

# ---- 下载 SDI Lite (只有 SDI.exe + 主题 + 语言，不含索引) ----
# Check for SDI + themes/langs (otherwise the existing extraction may be
# incomplete — e.g. only the .exe was preserved when the user ran the script
# multiple times with a partially wiped temp directory).
$needDownload = $false
$needReextract = $false
if (!(Test-Path $SdiExe)) {
    $needDownload = $true
} else {
    # Verify themes/lang dirs are present (SDI needs them at runtime)
    $themesDir = Join-Path $SDIDir "Tools\SDI\themes"
    $langsDir = Join-Path $SDIDir "Tools\SDI\langs"
    if (-not (Test-Path $themesDir) -or -not (Test-Path $langsDir)) {
        Write-Warn "SDI themes/langs 目录缺失，需要重新解压"
        $needReextract = $true
    }
}

if ($needDownload -or $needReextract) {
    if ($needDownload) {
        Write-Info "下载 SDI Lite（仅 SDI.exe 程序）..."
        if (!(Download-File "$BaseURL/api/sdi_lite" $SdiLite7z "SDI Lite")) {
            Write-Err "无法下载 SDI Lite，已中止。"
            exit 1
        }
    }
    # Clean SDI dir so extraction starts fresh
    if (Test-Path $SDIDir) {
        Remove-Item -Path $SDIDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $SDIDir -Force | Out-Null
    }
    Write-Info "正在解压 SDI Lite..."
    $argList = "x `"$SdiLite7z`" -o`"$TempDir`" -aoa -y"
    $proc = Start-Process -FilePath $SevenZipExe -ArgumentList $argList -Wait -NoNewWindow -PassThru
    if ($proc.ExitCode -eq 0) {
        # Verify themes/lang dirs are present
        $themesDir = Join-Path $SDIDir "Tools\SDI\themes"
        $langsDir = Join-Path $SDIDir "Tools\SDI\langs"
        if ((Test-Path $themesDir) -and (Test-Path $langsDir)) {
            Write-OK "SDI 解压完成 (themes + langs 就绪)"
        } else {
            Write-Err "SDI 解压不完整，themes/langs 目录缺失"
            exit 1
        }
    }
    else {
        Write-Err "7z 解压失败 (退出码: $($proc.ExitCode))"
        exit 1
    }
}
else {
    Write-OK "SDI 已存在 (含 themes/langs)"
}

# ============================================================
# Step 2: 直接用 WMI 获取本机所有设备 HWID（不依赖 SDI 日志）
# ============================================================
Write-Step "第 2 步：获取本机设备 HWID..."

$allDevices = @()
$allHwids = @()

try {
    Write-Info "查询设备列表 (WMI ConfigManagerErrorCode)..."
    # IMPORTANT: Use Win32_PnPEntity.ConfigManagerErrorCode, NOT Get-PnpDevice.Problem.
    # Get-PnpDevice returns Problem as a string enum, and CM_PROB_PHANTOM (ghost
    # devices that no longer exist) gets counted as "problem" — yielding 300+
    # false positives. Win32_PnPEntity.ConfigManagerErrorCode is a pure uint32
    # where 0 = OK and != 0 means actual yellow-bang in Device Manager
    # (e.g. 28 = driver not installed). This matches what local SDI shows.
    $pnpDevices = Get-WmiObject Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.HardwareID -and $_.HardwareID.Count -gt 0 }

    $totalCount = $pnpDevices.Count
    $current = 0
    $problemCount = 0
    Write-Info "扫描设备 (0/$totalCount)..."
    foreach ($dev in $pnpDevices) {
        $current++
        $hwid = $dev.HardwareID[0]
        if (!$hwid) { continue }
        $baseHwid = Get-BaseHwid $hwid
        if (!$baseHwid) { continue }

        if ($current % 25 -eq 0 -or $current -eq $totalCount) {
            Write-Info "扫描设备 ($current/$totalCount)..."
        }

        # Only include devices with real yellow-bang: ConfigManagerErrorCode != 0
        $errCode = $dev.ConfigManagerErrorCode
        if ($errCode -eq 0) { continue }

        $name = if ($dev.Name) { $dev.Name } else { $dev.Description }
        $problemCount++

        $devObj = @{
            Name = $name
            Hwids = @($baseHwid)
            IsProblem = $true
            ErrorCode = $errCode
            Status = $dev.Status
        }
        $allDevices += $devObj
        $allHwids += $baseHwid
    }
    Write-OK "找到 $problemCount 个黄色感叹号设备 (共扫描 $totalCount 个 PnP 设备)"
}
catch {
    Write-Err "WMI 查询失败，尝试 Get-PnpDevice + Get-PnpDeviceProperty..."
    try {
        # Fallback: use Get-PnpDevice + Get-PnpDeviceProperty to read the
        # ProblemCode reliably (DEVPKEY_Device_ProblemCode is numeric and
        # excludes CM_PROB_PHANTOM ghost devices that pollute the .Problem property).
        $pnpDevices = Get-PnpDevice -ErrorAction SilentlyContinue |
            Where-Object { $_.InstanceId -and ($_.InstanceId -match '\\') }
        $validPrefixes = @('PCI','USB','HDAUDIO','ACPI','HID','SCSI','IDE','ROOT','SD','BTH','SW','MF','DISPLAY','MEDIA','NET','PRINT','PORTS','SYSTEM','PROCESSOR','COMPUTER','VOLUME','SWD','UEFI','MONITOR','STREAM','BTHENUM','STORAGE')
        foreach ($dev in $pnpDevices) {
            $instId = $dev.InstanceId
            if (!$instId) { continue }
            $parts = $instId -split '\\', 2
            if ($parts.Count -lt 2) { continue }
            $prefix = $parts[0]
            if ($prefix -notin $validPrefixes) { continue }
            $hwid = "$prefix\$($parts[1])"
            $baseHwid = Get-BaseHwid $hwid

            # Read DEVPKEY_Device_ProblemCode (numeric, excludes phantom devices)
            $probProp = Get-PnpDeviceProperty -InstanceId $instId -KeyName 'DEVPKEY_Device_ProblemCode' -ErrorAction SilentlyContinue
            $errCode = 0
            if ($probProp -and $probProp.Data) { $errCode = [int]$probProp.Data }
            if ($errCode -eq 0) { continue }

            $devObj = @{
                Name = $dev.FriendlyName
                Hwids = @($baseHwid)
                IsProblem = $true
                ErrorCode = $errCode
                Status = $dev.Status
            }
            $allDevices += $devObj
            $allHwids += $baseHwid
        }
        Write-OK "获取到 $($allDevices.Count) 个需要驱动的设备"
    }
    catch {
        Write-Err "设备枚举失败: $($_.Exception.Message)"
        exit 1
    }
}

$allHwids = $allHwids | Where-Object { $_ } | Select-Object -Unique

if ($allHwids.Count -eq 0) {
    Write-Err "未检测到任何设备 HWID"
    exit 2
}

Write-Host "    唯一 HWID: $($allHwids.Count) 个" -ForegroundColor Gray

# Build device payload for server
$devicePayload = @($allDevices | ForEach-Object {
    @{
        hwid = $_.Hwids[0]
        instance_id = $_.Hwids[0]
        description = $_.Name
        class = "Unknown"
        is_problem = $_.IsProblem
    }
})

# ============================================================
# Step 3: 上传 HWID 到服务器分析
# ============================================================
Write-Step "第 3 步：上传 HWID 到服务器分析..."

Write-Info "准备请求数据 ($($allHwids.Count) 个 HWID)..."

$payload = @{
    hwids = @($allHwids)
    devices = $devicePayload
} | ConvertTo-Json -Depth 4

try {
    Write-Info "上传并等待服务器匹配 .bin 索引..."
    $response = Invoke-RestMethod -Uri "$BaseURL/api/analyze" -Method POST -Body $payload `
        -ContentType "application/json; charset=utf-8" -TimeoutSec 60
}
catch {
    Write-Err "服务器连接失败: $($_.Exception.Message)"
    exit 1
}

if (!$response.matched) {
    $msg = if ($response.message) { $response.message } else { "No driver packages matched" }
    Write-Host "`n================================================" -ForegroundColor Cyan
    Write-Host "      $msg" -ForegroundColor Yellow
    Write-Host "================================================" -ForegroundColor Cyan
    exit 0
}

$allDrivers = @()
if ($response.drivers) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  缺失驱动 (必需安装)" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    $idx = 0
    foreach ($drv in $response.drivers) {
        $idx++
        $pkgName = $drv.pkg
        $sizeMb = $drv.size_mb
        $sizeDisplay = if ($sizeMb -ge 1024) { "$([math]::Round($sizeMb / 1024, 2)) GB" } else { "$sizeMb MB" }
        $hwidsInfo = if ($drv.for_hwids -and $drv.for_hwids.Count -gt 0) {
            ($drv.for_hwids | ForEach-Object { $_.Substring([Math]::Max(0, $_.Length - 40)) }) -join ", "
        } else { "" }
        Write-Host ("  [{0}] {1}" -f $idx, $pkgName) -ForegroundColor White
        Write-Host ("      大小: {0}" -f $sizeDisplay) -ForegroundColor Gray
        if ($hwidsInfo) {
            Write-Host ("      设备: {0}" -f $hwidsInfo) -ForegroundColor DarkGray
        }
        $allDrivers += $drv
    }
    Write-Host ""
}
# 按类目分组可选更新
if ($response.optional_drivers) {
    $categoryMap = @{
        'bluetooth' = @{ DisplayName = '蓝牙 (Bluetooth)'; Patterns = @('Bluetooth', 'Bluetooth_', 'BTH') }
        'wlan' = @{ DisplayName = '无线网卡 (Wi-Fi/WLAN)'; Patterns = @('WLAN', 'WiFi', 'Wi-Fi', 'WiFi_') }
        'lan' = @{ DisplayName = '有线网卡 (Ethernet/LAN)'; Patterns = @('LAN_', 'Net_', 'Network') }
        'video' = @{ DisplayName = '显卡 (Graphics)'; Patterns = @('Video', 'Videos', 'Vendor_26061', 'Video_AMD', 'Video_nVIDIA') }
        'sound' = @{ DisplayName = '声卡 (Audio)'; Patterns = @('Sound', 'Sounds') }
        'storage' = @{ DisplayName = '存储 (Storage/NVMe)'; Patterns = @('Storage', 'NVMe', 'SATA') }
        'chipset' = @{ DisplayName = '芯片组 (Chipset)'; Patterns = @('Chipset') }
        'touchpad' = @{ DisplayName = '触摸板 (Touchpad)'; Patterns = @('Touchpad') }
        'cardreader' = @{ DisplayName = '读卡器 (Card Reader)'; Patterns = @('CardReader', 'CardReader_') }
        'webcam' = @{ DisplayName = '摄像头 (Webcam)'; Patterns = @('WebCam') }
        'monitor' = @{ DisplayName = '显示器 (Monitor)'; Patterns = @('Monitor') }
        'printer' = @{ DisplayName = '打印机 (Printer)'; Patterns = @('Printer', 'ThermoPrinter', 'TV_') }
        'misc' = @{ DisplayName = '其他 (Misc)'; Patterns = @('Misc', 'SoftwareComponent', 'xMobile', 'HIDClass', 'xUSB') }
    }

    function Get-DriverCategory($pkg, $categoryMap) {
        foreach ($key in $categoryMap.Keys) {
            foreach ($pat in $categoryMap[$key].Patterns) {
                if ($pkg -like "*$pat*") {
                    return $key
                }
            }
        }
        return 'misc'
    }

    # 按类目分组
    $grouped = @{}
    foreach ($drv in $response.optional_drivers) {
        $cat = Get-DriverCategory $drv.pkg $categoryMap
        if (-not $grouped.ContainsKey($cat)) {
            $grouped[$cat] = @()
        }
        $grouped[$cat] += $drv
    }

    Write-Host ""
    Write-Host "============================================" -ForegroundColor Yellow
    Write-Host "  可选更新 (输入编号多选，A=全部，N=跳过)" -ForegroundColor Yellow
    Write-Host "============================================" -ForegroundColor Yellow
    Write-Host ""

    # 类目排序优先级
    $order = @('bluetooth', 'wlan', 'lan', 'video', 'sound', 'storage', 'chipset', 'touchpad', 'cardreader', 'webcam', 'monitor', 'printer', 'misc')
    $displayCats = @()
    foreach ($cat in $order) {
        if (-not $grouped.ContainsKey($cat)) { continue }
        $drvList = $grouped[$cat]
        $catSize = 0
        foreach ($d in $drvList) { $catSize += $d.size }
        $sizeMb = [math]::Round($catSize / 1MB, 2)
        $displayName = $categoryMap[$cat].DisplayName
        $idx = $displayCats.Count + 1
        $displayCats += $cat
        Write-Host ("  [{0}] {1}  ({2} 个包, {3} MB)" -f $idx, $displayName, $drvList.Count, $sizeMb) -ForegroundColor Cyan
    }

    Write-Host ""
    $choice = Read-Host "请输入要下载的类目编号 (如 1,3 或 A=全部 / N=跳过)"

    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "N" }
    $choice = $choice.Trim().ToUpper()

    if ($choice -eq 'A' -or $choice -eq 'Y' -or $choice -eq 'ALL') {
        # 全部选择
        foreach ($cat in $displayCats) {
            foreach ($drv in $grouped[$cat]) {
                $allDrivers += $drv
            }
        }
        Write-Host "  -> 已添加全部 $($grouped.Values | ForEach-Object { $_.Count } | Measure-Object -Sum).Sum 个包" -ForegroundColor Green
    }
    elseif ($choice -ne 'N' -and $choice -ne 'NO' -and $choice -ne '') {
        # 解析编号列表（如 "1,3,5" 或 "1 3 5"）
        $selectedCount = 0
        $tokens = $choice -split '[,，\s]+' | Where-Object { $_ }
        foreach ($tok in $tokens) {
            $idx = 0
            if ([int]::TryParse($tok, [ref]$idx) -and $idx -ge 1 -and $idx -le $displayCats.Count) {
                $cat = $displayCats[$idx - 1]
                $drvList = $grouped[$cat]
                foreach ($drv in $drvList) {
                    $allDrivers += $drv
                }
                $selectedCount += $drvList.Count
            }
        }
        if ($selectedCount -gt 0) {
            Write-Host "  -> 已添加 $selectedCount 个包" -ForegroundColor Green
        }
        else {
            Write-Host "  -> 未选择任何类目" -ForegroundColor DarkGray
        }
    }
    else {
        Write-Host "  -> 跳过所有可选更新" -ForegroundColor DarkGray
    }
    Write-Host ""
}

if ($allDrivers.Count -eq 0) {
    Write-Host "`n================================================" -ForegroundColor Cyan
    Write-Host "      未选择任何驱动包" -ForegroundColor Yellow
    Write-Host "================================================" -ForegroundColor Cyan
    exit 0
}

# 显卡提示
if ($response.gpu_notices) {
    Write-Host ""
    foreach ($notice in $response.gpu_notices) {
        Write-Host "显卡：$notice" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  下载清单" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""

# Diagnostics from server
if ($response.diagnostics) {
    $diag = $response.diagnostics
    Write-Host ("  提交 HWID: {0} 个 | 有效硬件: {1} 个 | 已匹配: {2} 个" -f $diag.total_hwids, $diag.driver_hwids, $diag.hwids_matched) -ForegroundColor DarkGray
    if ($diag.skipped_composite -gt 0) {
        Write-Host ("  已跳过: {0} 个复合/虚拟父设备 (MF\*)" -f $diag.skipped_composite) -ForegroundColor DarkGray
    }
}

# Full package listing
$requiredCount = 0
$optionalCount = 0
$requiredSize = 0
$optionalSize = 0
$idx = 0

if ($response.drivers) {
    Write-Host "`n  --- 必需驱动 ---" -ForegroundColor Cyan
    foreach ($drv in $response.drivers) {
        $idx++
        $sizeMb = $drv.size_mb
        $sizeDisplay = if ($sizeMb -ge 1024) { "$([math]::Round($sizeMb / 1024, 2)) GB" } else { "$sizeMb MB" }
        Write-Host ("  [{0}] {1}  ({2})" -f $idx, $drv.pkg, $sizeDisplay) -ForegroundColor White
        $requiredCount++
        $requiredSize += $drv.size
    }
}

if ($response.optional_drivers) {
    Write-Host "`n  --- 可选更新 ---" -ForegroundColor DarkYellow
    foreach ($drv in $allDrivers) {
        if ($drv.pkg -in ($response.drivers | ForEach-Object { $_.pkg })) { continue }
        $idx++
        $sizeMb = $drv.size_mb
        $sizeDisplay = if ($sizeMb -ge 1024) { "$([math]::Round($sizeMb / 1024, 2)) GB" } else { "$sizeMb MB" }
        $cat = $drv.category
        if (-not $cat) { $cat = "" }
        Write-Host ("  [{0}] {1}  ({2}) [{3}]" -f $idx, $drv.pkg, $sizeDisplay, $cat) -ForegroundColor Gray
        $optionalCount++
        $optionalSize += $drv.size
    }
}

$allTotalSize = 0
foreach ($drv in $allDrivers) { $allTotalSize += $drv.size }
$totalDisplay = if ($allTotalSize -ge 1073741824) { "$([math]::Round($allTotalSize / 1GB, 2)) GB" } else { "$([math]::Round($allTotalSize / 1MB, 2)) MB" }

Write-Host ""
Write-OK ("共 {0} 个驱动包 (必需: {1}, 可选: {2}), 总大小: {3}" -f $allDrivers.Count, $requiredCount, $optionalCount, $totalDisplay)

# ============================================================
# Step 4: 下载 .7z 和 .bin
# ============================================================
Write-Step "第 4 步：下载驱动包和索引..."

$pkgTasks = @()
$idxTasks = @()

foreach ($drv in $allDrivers) {
    $pkgName = $drv.pkg
    $pkgDest = Join-Path $DriversDir $pkgName
    if (!(Test-Path $pkgDest)) {
        $dlUrl = if ($drv.url) { $drv.url } else { "$CosDrivers/$pkgName" }
        $pkgTasks += @{
            Url  = $dlUrl
            Dest = $pkgDest
            Desc = $pkgName
            Size = [long]$drv.size
        }
    }

    if ($drv.index) {
        $idxDest = Join-Path $IndexDir $drv.index
        if (!(Test-Path $idxDest)) {
            $idxUrl = if ($drv.index_url) { $drv.index_url } else { "$CosIndex/$($drv.index)" }
            $idxTasks += @{
                Url  = $idxUrl
                Dest = $idxDest
                Desc = $drv.index
                Size = 0
            }
        }
    }
}

if ($pkgTasks.Count -gt 0) {
    Write-Info "下载 $($pkgTasks.Count) 个驱动包..."
    $results = Invoke-ParallelDownloads $pkgTasks
    $failed = $results | Where-Object { $_.Status -ne "OK" }
    if ($failed) { Write-Err "部分驱动包下载失败" }
}

if ($idxTasks.Count -gt 0) {
    Write-Info "下载 $($idxTasks.Count) 个索引..."
    $results = Invoke-ParallelDownloads $idxTasks
}

# ============================================================
# Step 5: 启动 SDI 安装
# ============================================================
Write-Step "第 5 步：启动 SDI..."

if (!(Test-Path $SdiExe)) {
    Write-Err "找不到 SDI: $SdiExe"
    exit 1
}

$driverCount = (Get-ChildItem $DriversDir -Filter "*.7z" -ErrorAction SilentlyContinue).Count
$indexCount = (Get-ChildItem $IndexDir -Filter "*.bin" -ErrorAction SilentlyContinue).Count
Write-OK "驱动: $driverCount 个 | 索引: $indexCount 个"

Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host "      一切就绪！" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  SDI 即将启动，请在列表中选择要安装的驱动后点击安装" -ForegroundColor White
Write-Host ""

Start-Process -FilePath $SdiExe -WorkingDirectory $SDIDir
Write-OK "SDI 已启动"

# 退出选项
Write-Host ""
Write-Host "  [Y] 清理临时文件并退出" -ForegroundColor Yellow
Write-Host "  [N] 保留临时文件并退出 (默认)" -ForegroundColor Yellow
Write-Host "  [B] 备份临时目录到其他盘后退出" -ForegroundColor Yellow

$cleanChoice = ""
while ($cleanChoice -notin @("Y", "N", "B", "y", "n", "b")) {
    $cleanChoice = Read-Host "请选择 (Y/N/B)"
    if ([string]::IsNullOrWhiteSpace($cleanChoice)) { $cleanChoice = "N" }
}

if ($cleanChoice -in @("Y", "y")) {
    try {
        if (Test-Path $TempDir) { Remove-Item -Path $TempDir -Recurse -Force -ErrorAction Stop }
        Write-OK "临时文件已清理"
    }
    catch {
        Write-Info "清理失败，请手动删除: $TempDir"
    }
}
elseif ($cleanChoice -in @("B", "b")) {
    # 备份到其他盘
    $availableDrives = @()
    foreach ($letter in @('D','E','F','G','H')) {
        $drive = "$($letter):\"
        if (Test-Path $drive) {
            try {
                $freeGB = [math]::Round((Get-PSDrive -PSProvider FileSystem -Name $letter -ErrorAction SilentlyContinue).Free / 1GB, 1)
                $availableDrives += [PSCustomObject]@{ Letter = $letter; FreeGB = $freeGB }
            } catch {}
        }
    }

    if ($availableDrives.Count -eq 0) {
        Write-Info "未找到可用的其他盘，临时文件已保留"
    }
    else {
        Write-Host ""
        Write-Host "  可用目标盘:" -ForegroundColor Yellow
        foreach ($d in $availableDrives) {
            Write-Host "    [$($d.Letter)]  $($d.Letter):\  (可用空间: $($d.FreeGB) GB)" -ForegroundColor White
        }
        $targetDrive = ""
        while ($true) {
            $targetDrive = (Read-Host "请输入目标盘符 (如 D)").ToUpper()
            if ([string]::IsNullOrWhiteSpace($targetDrive)) { $targetDrive = $availableDrives[0].Letter }
            if ($availableDrives | Where-Object { $_.Letter -eq $targetDrive }) { break }
            Write-Info "无效的盘符，请重试"
        }

        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupName = "WSDI_backup_$timestamp"
        $backupPath = Join-Path "${targetDrive}:\" $backupName

        try {
            Write-Info "正在备份 $TempDir 到 $backupPath ..."
            Copy-Item -Path $TempDir -Destination $backupPath -Recurse -Force -ErrorAction Stop
            $sizeMB = [math]::Round((Get-ChildItem $backupPath -Recurse | Measure-Object Length -Sum).Sum / 1MB, 2)
            Write-OK "备份完成: $backupPath ($sizeMB MB)"

            # 备份完成后清理临时目录
            $delBackup = Read-Host "备份成功，是否清理原临时目录? (Y/N)"
            if ($delBackup -in @("Y", "y")) {
                Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue
                Write-OK "原临时目录已清理"
            }
            else {
                Write-Info "原临时目录已保留: $TempDir"
            }
        }
        catch {
            Write-Info "备份失败: $($_.Exception.Message)"
            Write-Info "临时文件已保留: $TempDir"
        }
    }
}
else {
    Write-Info "已保留临时文件: $TempDir"
}

Write-Host "`n按任意键退出..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")