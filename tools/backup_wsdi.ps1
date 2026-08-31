# WSDI 项目备份脚本
# 用 7-Zip 打包项目代码和配置，排除大文件和临时文件
# 输出: D:\WSDI_Backup\WSDI_backup_YYYYMMDD_HHMMSS.7z

$ErrorActionPreference = "Stop"

# 路径配置
$ProjectRoot = "D:\WSDI"
$BackupDir = "D:\WSDI_Backup"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFile = Join-Path $BackupDir "WSDI_backup_$Timestamp.7z"

# 7-Zip 路径（优先用项目自带的，其次系统安装的）
$SevenZip = "D:\WSDI\cache\tools\7z.exe"
if (-not (Test-Path $SevenZip)) {
    $SevenZip = "C:\Program Files\7-Zip\7z.exe"
}
if (-not (Test-Path $SevenZip)) {
    Write-Host "[!] 7z.exe not found, trying 7za" -ForegroundColor Red
    $SevenZip = "7za"
}

# 创建备份目录
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

# 排除列表（文件名 + 通配符）
$excludeList = @(
    # 大文件目录
    "cache",
    "SDI",
    "Drivers",
    "index",
    # 临时文件
    "*.pyc",
    "*.cache",
    "*.log",
    "err.txt",
    "out.txt",
    "sdi_diag.log",
    "sdi_stderr*.txt",
    "sdi_stdout*.txt",
    "rclone.zip",
    # 编译产物
    "server\__pycache__",
    "server\*.pyc",
    "server\*.bak",
    # IDE/系统
    ".git",
    ".vscode",
    ".codebuddy",
    "*.tmp"
)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  WSDI 项目备份" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "源目录:    $ProjectRoot" -ForegroundColor Gray
Write-Host "备份文件:  $BackupFile" -ForegroundColor Gray
Write-Host "7-Zip:     $SevenZip" -ForegroundColor Gray
Write-Host ""
Write-Host "排除项:" -ForegroundColor Gray
$excludeList | ForEach-Object { Write-Host "  - $_" -ForegroundColor DarkGray }
Write-Host ""

# 构造 7z 命令参数
$excludeArgs = $excludeList | ForEach-Object { "-xr!$_" }
$archiveArgs = @("a", "-t7z", "-mx=9", "-mmt=on", $BackupFile, "$ProjectRoot\*") + $excludeArgs

Write-Host "[1/2] 打包中..." -ForegroundColor Yellow
$startTime = Get-Date
& $SevenZip @archiveArgs 2>&1 | ForEach-Object {
    # 过滤掉进度行，只显示关键信息
    if ($_ -notmatch '^\s*$' -and $_ -notmatch '^\s+\d+%' -and $_ -notmatch '^Adding') {
        Write-Host "  $_" -ForegroundColor DarkGray
    }
}

if ($LASTEXITCODE -ne 0 -and -not (Test-Path $BackupFile)) {
    Write-Host "[!] 备份失败，7z 退出码: $LASTEXITCODE" -ForegroundColor Red
    exit 1
}

$elapsed = ((Get-Date) - $startTime).TotalSeconds

# 验证备份文件
if (Test-Path $BackupFile) {
    $size = (Get-Item $BackupFile).Length
    $sizeMB = [math]::Round($size / 1MB, 2)
    
    Write-Host ""
    Write-Host "[2/2] 验证备份..." -ForegroundColor Yellow
    & $SevenZip t $BackupFile 2>&1 | Select-String "Everything is Ok|Files:|Size:" | ForEach-Object {
        Write-Host "  $_" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "  备份完成！" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  文件: $BackupFile" -ForegroundColor White
    Write-Host "  大小: $sizeMB MB" -ForegroundColor White
    Write-Host "  耗时: $([math]::Round($elapsed, 1)) 秒" -ForegroundColor White
    Write-Host ""
    
    # 列出备份文件里包含什么
    Write-Host "备份内容概览（顶层目录）:" -ForegroundColor Cyan
    & $SevenZip l $BackupFile 2>&1 | Select-String "D:\\\\WSDI\\\\[^\\\\]+(\\\\|$)" | ForEach-Object {
        Write-Host "  $_" -ForegroundColor DarkGray
    }
} else {
    Write-Host "[!] 备份文件未生成: $BackupFile" -ForegroundColor Red
    exit 1
}
