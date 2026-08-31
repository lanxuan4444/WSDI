# WSDI B2 上传脚本
# 把 D:\SDI\Drivers\ 下大于 512MB 的 38 个文件上传到 B2 的 wsdi-drivers 桶
# 保留原文件名（不传到子目录，直接放在桶根，对应 /Drivers/ 前缀改成根）
#
# 用法：
#   D:\WSDI\upload_to_b2.ps1            # 上传所有大文件
#   D:\WSDI\upload_to_b2.ps1 -DryRun    # 只打印将上传什么，不真的传
#   D:\WSDI\upload_to_b2.ps1 -Verify    # 只校验已上传文件的 MD5

param(
    [switch]$DryRun,
    [switch]$Verify,
    [string]$DriverDir = "D:\SDI\Drivers"
)

$ErrorActionPreference = "Stop"
$rclone = "D:\WSDI\tools\rclone-v1.67.0-windows-amd64\rclone.exe"
$conf = "D:\WSDI\tools\rclone.conf"
$remote = "wsdi-b2:wsdi-drivers"
$threshold = 512MB

if (-not (Test-Path $rclone)) {
    Write-Host "[!] rclone not found at $rclone" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $DriverDir)) {
    Write-Host "[!] Driver dir not found: $DriverDir" -ForegroundColor Red
    exit 1
}

# 列出 > 512MB 的文件
$files = Get-ChildItem $DriverDir -File | Where-Object { $_.Length -gt $threshold } | Sort-Object Name
Write-Host "Found $($files.Count) large files (>512MB) to upload" -ForegroundColor Cyan
$files | ForEach-Object {
    Write-Host ("  {0,-50} {1,10:N2} MB" -f $_.Name, ($_.Length / 1MB))
}

if ($DryRun) {
    Write-Host "`n[DryRun] No files will be uploaded." -ForegroundColor Yellow
    exit 0
}

if ($Verify) {
    Write-Host "`n=== Verifying uploaded files ===" -ForegroundColor Cyan
    foreach ($f in $files) {
        # rclone check 比较本地和远程的 hash
        & $rclone check "$($f.FullName)" "$remote/$($f.Name)" `
            --config $conf --one-way --checkers 4 `
            2>&1 | ForEach-Object {
                if ($_ -match "matching|differ|missing|error") {
                    Write-Host "  $($f.Name): $_"
                }
            }
    }
    Write-Host "Verify done." -ForegroundColor Green
    exit 0
}

# 上传
$start = Get-Date
$ok = 0
$fail = 0
foreach ($f in $files) {
    Write-Host "`n[$($files.IndexOf($f)+1)/$($files.Count)] Uploading $($f.Name) ($([math]::Round($f.Length/1MB,2)) MB)..." -ForegroundColor Cyan
    $t0 = Get-Date
    & $rclone copyto "$($f.FullName)" "$remote/$($f.Name)" `
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
        $speed = $f.Length / 1MB / $elapsed
        Write-Host ("  OK: {0:N1}s, {1:N2} MB/s" -f $elapsed, $speed) -ForegroundColor Green
        $ok++
    } else {
        Write-Host "  FAILED (exit code $LASTEXITCODE)" -ForegroundColor Red
        $fail++
    }
}

$elapsed = ((Get-Date) - $start).TotalMinutes
Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "Uploaded: $ok / $($files.Count)"
Write-Host "Failed:   $fail"
Write-Host "Total time: $([math]::Round($elapsed, 1)) min"
if ($fail -gt 0) {
    Write-Host "`nSome files failed. Re-run the script to retry." -ForegroundColor Yellow
    exit 1
}
