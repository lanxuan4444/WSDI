# WSDI B2 全量上传脚本
# 把所有驱动包、索引、SDI Lite、7-Zip 便携版全部上传到 B2 桶根目录
# 已存在的文件会跳过（rclone --ignore-existing）
#
# 用法：
#   D:\WSDI\upload_all_to_b2.ps1            # 上传所有
#   D:\WSDI\upload_all_to_b2.ps1 -DryRun    # 只打印将上传什么
#   D:\WSDI\upload_all_to_b2.ps1 -Verify    # 校验已上传文件
#   D:\WSDI\upload_all_to_b2.ps1 -Category Drivers  # 只上传驱动包
#   D:\WSDI\upload_all_to_b2.ps1 -Category Index    # 只上传索引
#   D:\WSDI\upload_all_to_b2.ps1 -Category Tools    # 只上传 SDI Lite + 7z

param(
    [switch]$DryRun,
    [switch]$Verify,
    [string]$Category = "All",  # All / Drivers / Index / Tools
    [string]$DriverDir = "D:\SDI\Drivers",
    [string]$IndexDir = "D:\SDI\Index\SDI",
    [int]$MaxSizeMB = 500  # 只上传 < 500MB 的驱动包（大文件已经传过了）
)

$ErrorActionPreference = "Stop"
$rclone = "D:\WSDI\tools\rclone-v1.67.0-windows-amd64\rclone.exe"
$conf = "D:\WSDI\tools\rclone.conf"
$remote = "wsdi-b2:wsdi-drivers"

if (-not (Test-Path $rclone)) {
    Write-Host "[!] rclone not found at $rclone" -ForegroundColor Red
    exit 1
}

# 收集所有要上传的文件
$tasks = @()

# 1. 驱动包 (< 500MB)
if ($Category -in @("All", "Drivers")) {
    if (Test-Path $DriverDir) {
        $drvFiles = Get-ChildItem $DriverDir -File -Filter "*.7z" |
            Where-Object { $_.Length / 1MB -lt $MaxSizeMB } |
            Sort-Object Name
        foreach ($f in $drvFiles) {
            $tasks += @{
                LocalPath = $f.FullName
                RemoteName = $f.Name  # 直接放桶根，和大文件保持一致
                Size = $f.Length
                Category = "Driver"
            }
        }
    }
}

# 2. 索引文件 (.bin)
if ($Category -in @("All", "Index")) {
    if (Test-Path $IndexDir) {
        $idxFiles = Get-ChildItem $IndexDir -File -Filter "*.bin" | Sort-Object Name
        foreach ($f in $idxFiles) {
            $tasks += @{
                LocalPath = $f.FullName
                RemoteName = $f.Name  # 直接放桶根
                Size = $f.Length
                Category = "Index"
            }
        }
    }
}

# 3. SDI Lite + 7-Zip 便携版
if ($Category -in @("All", "Tools")) {
    $tools = @(
        @{ Path = "D:\WSDI\cache\sdi_lite\SDI_R2601.7z"; Name = "SDI_R2601.7z" }
        @{ Path = "D:\WSDI\cache\tools\7z_portable.zip"; Name = "7z_portable.zip" }
    )
    foreach ($t in $tools) {
        if (Test-Path $t.Path) {
            $f = Get-Item $t.Path
            $tasks += @{
                LocalPath = $f.FullName
                RemoteName = $t.Name
                Size = $f.Length
                Category = "Tool"
            }
        }
    }
}

# 打印计划
Write-Host "===== Upload Plan =====" -ForegroundColor Cyan
Write-Host "Category: $Category"
Write-Host "Total files: $($tasks.Count)"
$byCat = $tasks | Group-Object Category
foreach ($g in $byCat) {
    $totalMB = ($g.Group | ForEach-Object { $_.Size } | Measure-Object -Sum).Sum / 1MB
    Write-Host ("  {0,-10} {1,3} files  {2,10:N2} MB" -f $g.Name, $g.Count, $totalMB)
}
Write-Host ""

if ($tasks.Count -eq 0) {
    Write-Host "No files to upload." -ForegroundColor Yellow
    exit 0
}

# 列出前 10 个
Write-Host "Sample files:" -ForegroundColor DarkGray
$tasks | Select-Object -First 10 | ForEach-Object {
    Write-Host ("  [{0}] {1}  ({2:N2} MB)" -f $_.Category, $_.RemoteName, ($_.Size / 1MB))
}
if ($tasks.Count -gt 10) {
    Write-Host "  ... and $($tasks.Count - 10) more"
}
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] No files will be uploaded." -ForegroundColor Yellow
    exit 0
}

# 校验模式
if ($Verify) {
    Write-Host "===== Verifying uploaded files =====" -ForegroundColor Cyan
    $ok = 0
    $bad = 0
    foreach ($t in $tasks) {
        & $rclone check $t.LocalPath "$remote/$($t.RemoteName)" `
            --config $conf --one-way --checkers 4 2>&1 | ForEach-Object {
            if ($_ -match "matching") {
                Write-Host ("  [OK]   {0}" -f $t.RemoteName) -ForegroundColor Green
                $script:ok++
            } elseif ($_ -match "differ|missing|error") {
                Write-Host ("  [BAD]  {0}: {1}" -f $t.RemoteName, $_) -ForegroundColor Red
                $script:bad++
            }
        }
    }
    Write-Host "`nVerify done: $ok OK, $bad bad" -ForegroundColor Cyan
    exit 0
}

# 上传
Write-Host "===== Uploading =====" -ForegroundColor Cyan
$start = Get-Date
$ok = 0
$fail = 0
$idx = 0
foreach ($t in $tasks) {
    $idx++
    $sizeMB = [math]::Round($t.Size / 1MB, 2)
    Write-Host ("`n[{0}/{1}] [{2}] {3} ({4} MB)..." -f $idx, $tasks.Count, $t.Category, $t.RemoteName, $sizeMB) -ForegroundColor Cyan
    $t0 = Get-Date
    & $rclone copyto $t.LocalPath "$remote/$($t.RemoteName)" `
        --config $conf `
        --progress `
        --transfers 1 `
        --checkers 4 `
        --retries 5 `
        --low-level-retries 10 `
        --bwlimit 0 `
        --ignore-existing
    if ($LASTEXITCODE -eq 0) {
        $elapsed = ((Get-Date) - $t0).TotalSeconds
        $speed = $sizeMB / $elapsed
        Write-Host ("  OK: {0:N1}s, {1:N2} MB/s" -f $elapsed, $speed) -ForegroundColor Green
        $ok++
    } else {
        Write-Host "  FAILED (exit code $LASTEXITCODE)" -ForegroundColor Red
        $fail++
    }
}

$elapsed = ((Get-Date) - $start).TotalMinutes
Write-Host "`n===== Done =====" -ForegroundColor Cyan
Write-Host "Uploaded: $ok / $($tasks.Count)"
Write-Host "Failed:   $fail"
Write-Host "Total time: $([math]::Round($elapsed, 1)) min"
if ($fail -gt 0) {
    Write-Host "`nSome files failed. Re-run the script to retry." -ForegroundColor Yellow
    exit 1
}
