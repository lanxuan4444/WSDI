$ProgressPreference = 'SilentlyContinue'
$h = @{
    'Authorization' = 'Bearer cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
    'Content-Type'  = 'application/json'
}
$acc = '3b9d1ff67a3cf35cd29c14cb4e8d2fed'
$logFile = 'D:\Cloudflar\setup_log.txt'

function Log($msg) {
    $stamp = Get-Date -Format 'HH:mm:ss'
    Write-Output "[$stamp] $msg"
    Add-Content -Path $logFile -Value "[$stamp] $msg"
}

Log "===== 启动配置 ====="

# Step 1: 检查现有隧道
Log "[1/4] 检查现有隧道..."
try {
    $listUrl = "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel?name=mytunnel"
    Log "URL: $listUrl"
    $existing = Invoke-RestMethod -Uri $listUrl -Headers $h
    Log "Response: $($existing | ConvertTo-Json -Compress)"
    if ($existing.result -and $existing.result.Count -gt 0) {
        $tid = $existing.result[0].id
        Log "EXISTING_TUNNEL_ID: $tid"
        $delUrl = "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel/$tid"
        Invoke-RestMethod -Uri $delUrl -Method DELETE -Headers $h | Out-Null
        Log "DELETED existing tunnel"
    } else {
        Log "No existing tunnel"
    }
} catch {
    Log "ERR (list/delete): $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "ERR detail: $($_.ErrorDetails.Message)" }
}

# Step 2: 创建新隧道
Log "[2/4] 创建新隧道..."
try {
    $body = '{"name":"mytunnel","config_src":"cloudflare"}'
    $createUrl = "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel"
    $created = Invoke-RestMethod -Uri $createUrl -Method POST -Headers $h -Body $body
    Log "Create response: $($created | ConvertTo-Json -Compress)"
    if ($created.success) {
        $TUNNEL_ID = $created.result.id
        Log "NEW_TUNNEL_ID: $TUNNEL_ID"
    } else {
        Log "Create failed: $($created.errors | ConvertTo-Json)"
    }
} catch {
    Log "ERR (create): $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "ERR detail: $($_.ErrorDetails.Message)" }
}

# Step 3: 获取隧道 token (凭据)
if ($TUNNEL_ID) {
    Log "[3/4] 获取隧道凭据..."
    try {
        $tokenUrl = "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel/$TUNNEL_ID/token"
        $tokenResp = Invoke-RestMethod -Uri $tokenUrl -Headers $h
        Log "Token response (first 200 chars): $($tokenResp | ConvertTo-Json -Compress | Select-Object -First 1)"
        $credDir = "$env:USERPROFILE\.cloudflared"
        if (-not (Test-Path $credDir)) { New-Item -ItemType Directory -Path $credDir | Out-Null }
        $credFile = "$credDir\$TUNNEL_ID.json"
        $tokenResp.result | ConvertTo-Json -Compress | Out-File -FilePath $credFile -Encoding ASCII
        Log "Credentials written to: $credFile"
    } catch {
        Log "ERR (token): $($_.Exception.Message)"
        if ($_.ErrorDetails) { Log "ERR detail: $($_.ErrorDetails.Message)" }
    }

    # Step 4: 生成 config.yml
    Log "[4/4] 生成 config.yml..."
    $config = @"
tunnel: $TUNNEL_ID
credentials-file: $credFile

ingress:
  - hostname: mydata.djyanhong09.workers.dev
    service: http://localhost:8080
  - service: http_status:404
"@
    $config | Out-File -FilePath 'D:\Cloudflar\config.yml' -Encoding UTF8
    Log "config.yml written"

    # 保存到全局供后续使用
    "TUNNEL_ID=$TUNNEL_ID" | Out-File -FilePath 'D:\Cloudflar\tunnel_id.txt' -Encoding ASCII
    "CRED_FILE=$credFile" | Out-File -FilePath 'D:\Cloudflar\cred_path.txt' -Encoding ASCII
}

Log "===== 配置结束 ====="
