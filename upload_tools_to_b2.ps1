# WSDI Tools 上传脚本
# 把 D:\WSDI\tools\public\ 下的文件上传到 B2 桶的 tools/ 前缀下
# 访问 yanhong.online/tools 即可看到文件列表
#
# 用法：
#   D:\WSDI\upload_tools_to_b2.ps1                    # 交互式（提示输入密码）
#   D:\WSDI\upload_tools_to_b2.ps1 -Password "xxx"    # 命令行传密码
#   D:\WSDI\upload_tools_to_b2.ps1 -DryRun            # 只打印将上传什么
#   D:\WSDI\upload_tools_to_b2.ps1 -List              # 列出 B2 上已有的 tools/ 文件
#   D:\WSDI\upload_tools_to_b2.ps1 -Delete "tools/old.zip"  # 删除 B2 上的指定文件
#
# 上传后会自动刷新服务端缓存，无需重启服务

param(
    [string]$Password,
    [switch]$DryRun,
    [switch]$List,
    [string]$Delete,
    [switch]$Yes,
    [string]$SourceDir = "D:\WSDI\tools\public",
    [string]$B2Prefix = "tools"
)

$ErrorActionPreference = "Stop"

# 安全的「按任意键退出」函数
# [Console]::ReadKey 在 PowerShell ISE / 无控制台 / stdin 重定向时会抛异常
# 这里先检测环境，避免闪退
function Wait-KeyPress {
    try {
        # 检测是否有真实控制台
        if ($Host.Name -eq "ConsoleHost" -and -not [Console]::IsInputRedirected) {
            Write-Host "按任意键退出..." -ForegroundColor Yellow
            [Console]::ReadKey($true) | Out-Null
        } else {
            # ISE / 重定向环境：用 Read-Host 兜底（用户可按回车）
            $null = Read-Host "按回车退出"
        }
    } catch {
        # 实在不行就 sleep 2 秒后退出
        Start-Sleep -Seconds 2
    }
}

# 捕获所有未处理异常，避免闪退看不到错误
trap {
    Write-Host ""
    Write-Host "[FATAL] 脚本异常: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "        位置: $($_.InvocationInfo.ScriptName):$($_.InvocationInfo.ScriptLineNumber)" -ForegroundColor DarkRed
    Write-Host ""
    Wait-KeyPress
    exit 1
}

# ============================================================
# 配置
# ============================================================

# 上传密码（SHA256 hash，避免明文存储）
# 默认密码：djyanhong@520  → 运行下面的命令生成 hash：
#   powershell -c "[BitConverter]::ToString((Get-FileHash -Algorithm SHA256 -InputStream ([System.IO.MemoryStream]::new([System.Text.Encoding]::UTF8.GetBytes('djyanhong@520')))).Hash).Replace('-','').ToLower()"
# 如需修改密码，生成新 hash 替换下面的值
$PASSWORD_HASH = "BC7CBA1B50C4BE4E1860921B238F4F6C69C74950FA602FF741E534BC0D627C39"

$rclone = "D:\WSDI\tools\rclone-v1.67.0-windows-amd64\rclone.exe"
$conf = "D:\WSDI\tools\rclone.conf"
$remote = "wsdi-b2:wsdi-drivers"

# ============================================================
# 密码验证
# ============================================================

function Test-Password($pwd) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($pwd)
    $stream = [System.IO.MemoryStream]::new($bytes)
    $hash = (Get-FileHash -Algorithm SHA256 -InputStream $stream).Hash
    return $hash -eq $PASSWORD_HASH
}

# ============================================================
# 主逻辑
# ============================================================

if (-not (Test-Path $rclone)) {
    Write-Host "[!] rclone not found at $rclone" -ForegroundColor Red
    Wait-KeyPress
    exit 1
}

# --list 模式：列出 B2 上已有的 tools/ 文件
if ($List) {
    Write-Host "===== B2 上的 tools/ 文件 =====" -ForegroundColor Cyan
    & $rclone lsjson "$remote/$B2Prefix" --config $conf 2>&1 | ConvertFrom-Json |
        Sort-Object Name |
        ForEach-Object {
            $size = if ($_.Size -ge 1MB) { "{0:N2} MB" -f ($_.Size / 1MB) }
                    elseif ($_.Size -ge 1KB) { "{0:N1} KB" -f ($_.Size / 1KB) }
                    else { "$($_.Size) B" }
            $date = if ($_.ModTime) { ([DateTime]$_.ModTime).ToString("yyyy-MM-dd") } else { "" }
            Write-Host ("  {0,-40} {1,10}  {2}" -f $_.Name, $size, $date) -ForegroundColor White
        }
    exit 0
}

# --delete 模式：删除 B2 上的文件
if ($Delete) {
    # 需要密码
    if (-not $Password) {
        $sec = Read-Host "请输入上传密码" -AsSecureString
        $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
    if (-not (Test-Password $Password)) {
        Write-Host "[!] 密码错误" -ForegroundColor Red
        exit 1
    }
    Write-Host "删除 B2 上的文件: $Delete" -ForegroundColor Yellow
    & $rclone deletefile "$remote/$Delete" --config $conf 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 已删除: $Delete" -ForegroundColor Green
    } else {
        Write-Host "[!] 删除失败" -ForegroundColor Red
        exit 1
    }
    exit 0
}

# 默认模式：上传
# 验证密码
if (-not $Password) {
    # 直接用 Read-Host 明文读取。
    # 之前用 -AsSecureString + PtrToStringAuto 在非中文系统的管理员 cmd
    # 里会把 BSTR 解码成乱码导致密码永远对不上。
    $Password = Read-Host "请输入上传密码"
}
if (-not (Test-Password $Password)) {
    Write-Host "[!] 密码错误" -ForegroundColor Red
    Wait-KeyPress
    exit 1
}
Write-Host "[OK] 密码验证通过" -ForegroundColor Green

# 检查源目录
if (-not (Test-Path $SourceDir)) {
    Write-Host "[!] 源目录不存在: $SourceDir" -ForegroundColor Red
    Write-Host "    请创建该目录并放入要上传的工具文件" -ForegroundColor Yellow
    Write-Host "    或用 -SourceDir 参数指定其他目录" -ForegroundColor Yellow
    Wait-KeyPress
    exit 1
}

# 收集要上传的文件
$files = Get-ChildItem $SourceDir -File -Recurse | Sort-Object FullName
# 修正：当 Get-ChildItem 只返回一个文件时，$files 是单个对象不是数组
if ($null -eq $files) {
    Write-Host "[!] 源目录为空: $SourceDir" -ForegroundColor Red
    Wait-KeyPress
    exit 1
}
if (-not ($files -is [array])) {
    $files = @($files)
}
if ($files.Count -eq 0) {
    Write-Host "[!] 源目录为空: $SourceDir" -ForegroundColor Red
    Wait-KeyPress
    exit 1
}

Write-Host ""
Write-Host "===== 上传计划 =====" -ForegroundColor Cyan
Write-Host "源目录:   $SourceDir"
Write-Host "B2 前缀:  $B2Prefix/"
Write-Host "文件数:   $($files.Count)"
$totalSize = ($files | Measure-Object Length -Sum).Sum
Write-Host ("总大小:   {0:N2} MB" -f ($totalSize / 1MB))
Write-Host ""

# 打印文件列表
$files | ForEach-Object {
    $relPath = $_.FullName.Substring($SourceDir.Length).TrimStart('\').Replace('\', '/')
    $b2Path = "$B2Prefix/$relPath"
    $size = if ($_.Length -ge 1MB) { "{0:N2} MB" -f ($_.Length / 1MB) }
            elseif ($_.Length -ge 1KB) { "{0:N1} KB" -f ($_.Length / 1KB) }
            else { "$($_.Length) B" }
    Write-Host ("  {0,-40} {1,10}" -f $b2Path, $size) -ForegroundColor Gray
}
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] 不会实际上传" -ForegroundColor Yellow
    exit 0
}

# 确认
if (-not $Yes) {
    $confirm = Read-Host "确认上传？(Y/N)"
    if ($confirm -ne "Y" -and $confirm -ne "y") {
        Write-Host "已取消" -ForegroundColor Yellow
        exit 0
    }
}

# 上传
Write-Host ""
Write-Host "===== 开始上传 =====" -ForegroundColor Cyan
$startTime = Get-Date

# 一次性 rclone copy 整个 public 目录到 B2 的 tools/ 前缀。
# rclone copy 会按目录结构复制，保持本地 public/ 下的相对路径
# 作为 tools/ 前缀下的子路径，正确生成 tools/README.txt 等。
& $rclone copy $SourceDir "$remote/$B2Prefix" `
    --config $conf `
    --progress `
    --transfers 4 `
    --checkers 8 `
    --retries 5 `
    --low-level-retries 10 `
    --ignore-existing

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host ("[OK] 全部文件已上传（共 {0} 个，{1:N2} MB）" -f $files.Count, ($totalSize / 1MB)) -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[!] rclone 上传失败 (exit code $LASTEXITCODE)" -ForegroundColor Red
    Wait-KeyPress
    exit 1
}

$elapsed = ((Get-Date) - $startTime).TotalMinutes
Write-Host ("耗时: {0:N1} 分钟" -f $elapsed)

# 通知服务端刷新 B2 文件缓存
Write-Host ""
Write-Host "===== 刷新服务端缓存 =====" -ForegroundColor Cyan
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1/api/b2_status?refresh=1" -TimeoutSec 30 -UseBasicParsing
    $data = $resp.Content | ConvertFrom-Json
    Write-Host "[OK] B2 文件列表已刷新: $($data.total_files) 个文件" -ForegroundColor Green
} catch {
    Write-Host "[!] 刷新失败（不影响上传，10 分钟后自动刷新）: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "现在访问 https://yanhong.online/tools 即可看到新上传的工具" -ForegroundColor Cyan
Wait-KeyPress
