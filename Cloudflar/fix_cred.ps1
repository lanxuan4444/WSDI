$ProgressPreference = 'SilentlyContinue'
$logFile = 'D:\Cloudflar\fix_cred_log.txt'
function Log($m) {
    $t = Get-Date -Format 'HH:mm:ss'
    "$t $m" | Out-File -Append -FilePath $logFile -Encoding UTF8
    Write-Output "[$t] $m"
}

Log "==== Fix credentials ===="

# 读取 token
$tokenBase64 = (Get-Content 'C:\Users\Administrator\.cloudflared\0fc7e3be-84c0-4a12-b549-c038ed1d0fc0.json' -Raw -Encoding UTF8).Trim()
# 去掉外层引号
$tokenBase64 = $tokenBase64.Trim('"')
Log "Token (first 50): $($tokenBase64.Substring(0, [Math]::Min(50, $tokenBase64.Length)))..."

# 尝试重新调用 API 拿完整的凭据
$h = @{
    'Authorization' = 'Bearer cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
    'Content-Type'  = 'application/json'
}
$acc = '3b9d1ff67a3cf35cd29c14cb4e8d2fed'
$tid = '0fc7e3be-84c0-4a12-b549-c038ed1d0fc0'

# 尝试不同的端点
Log "Try /token endpoint..."
$url1 = "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel/$tid/token"
Log "URL: $url1"
try {
    $r1 = Invoke-RestMethod -Uri $url1 -Headers $h
    Log "Result: $($r1 | ConvertTo-Json -Compress)"
} catch {
    Log "ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "ERR detail: $($_.ErrorDetails.Message)" }
}

# 尝试用 token 解析 base64 看里面有什么
Log "Decode token..."
try {
    $decoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($tokenBase64))
    Log "Decoded: $decoded"
} catch {
    Log "Decode ERR: $($_.Exception.Message)"
}
