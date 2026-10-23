# ============================================
# Cloudflare Tunnel 一键配置脚本
# ============================================
Set-Location $PSScriptRoot

Write-Host "========================================"  -ForegroundColor Cyan
Write-Host "  Cloudflare 命名隧道配置工具" -ForegroundColor Cyan
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host ""

# Step 1: 登录 Cloudflare
Write-Host "[1/4] 正在打开浏览器登录 Cloudflare..." -ForegroundColor Yellow
Write-Host "如果浏览器没有自动打开，请手动复制下面提示的链接"
.\cloudflared.exe tunnel login
if ($LASTEXITCODE -ne 0) {
    Write-Host "登录失败！请重试。" -ForegroundColor Red
    Read-Host "按任意键退出"
    exit 1
}
Write-Host ""

# Step 2: 检查是否已有隧道
$existingTunnel = .\cloudflared.exe tunnel list 2>&1 | Select-String "mytunnel"
if ($existingTunnel) {
    Write-Host "[!] 发现已存在的隧道 'mytunnel'" -ForegroundColor Yellow
    $response = Read-Host "是否删除并重建？(y/n)"
    if ($response -eq 'y') {
        $tunnelId = ($existingTunnel -split '\s+')[0]
        .\cloudflared.exe tunnel delete -f $tunnelId 2>$null
        Write-Host "已删除旧隧道"
    } else {
        Write-Host "使用现有隧道"
        $tunnelId = ($existingTunnel -split '\s+')[0]
    }
}

# Step 3: 创建隧道
if (-not $tunnelId) {
    Write-Host "[2/4] 正在创建命名隧道 'mytunnel'..." -ForegroundColor Yellow
    $output = .\cloudflared.exe tunnel create mytunnel 2>&1
    Write-Host $output
    
    # 从输出中提取 Tunnel ID
    $match = $output | Select-String -Pattern '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
    if ($match) {
        $tunnelId = $match.Matches[0].Value
    } else {
        Write-Host "无法获取隧道 ID，请检查输出" -ForegroundColor Red
        Read-Host "按任意键退出"
        exit 1
    }
}

Write-Host "隧道 ID: $tunnelId" -ForegroundColor Green
Write-Host ""

# Step 4: 生成 config.yml
Write-Host "[3/4] 正在生成配置文件..." -ForegroundColor Yellow
$configContent = @"
tunnel: $tunnelId
credentials-file: C:\Users\Administrator\.cloudflared\$tunnelId.json

ingress:
  - hostname: mydata.djyanhong09.workers.dev
    service: http://localhost:8080
  - service: http_status:404
"@

$configContent | Out-File -FilePath "$PSScriptRoot\config.yml" -Encoding UTF8
Write-Host "config.yml 已生成" -ForegroundColor Green
Write-Host ""

# Step 5: 提示下一步
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host "[4/4] 接下来请手动完成以下步骤：" -ForegroundColor Yellow
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host ""
Write-Host "打开浏览器，进入 Cloudflare Zero Trust 控制台：" -ForegroundColor White
Write-Host "  https://one.dash.cloudflare.com/" -ForegroundColor Cyan
Write-Host ""
Write-Host "按以下路径操作：" -ForegroundColor White
Write-Host "  Networks -> Tunnels -> 找到 mytunnel -> Configure" -ForegroundColor Yellow
Write-Host "  -> Public Hostname -> Add a public hostname" -ForegroundColor Yellow
Write-Host ""
Write-Host "填写以下信息：" -ForegroundColor White
Write-Host "  Subdomain:    mydata" -ForegroundColor Cyan
Write-Host "  Domain:       djyanhong09.workers.dev" -ForegroundColor Cyan
Write-Host "  Type:         HTTP" -ForegroundColor Cyan
Write-Host "  URL:          localhost:8080" -ForegroundColor Cyan
Write-Host ""
Write-Host "保存后，运行 [启动隧道.bat] 即可启动！" -ForegroundColor Green
Write-Host ""
Read-Host "按任意键退出"
