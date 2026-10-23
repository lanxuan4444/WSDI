$ProgressPreference = 'SilentlyContinue'
$logFile = 'D:\Cloudflar\final_setup.txt'
Set-Content -Path $logFile -Value '' -Encoding UTF8

function Log([string]$m) {
    $t = Get-Date -Format 'HH:mm:ss'
    $line = "[$t] $m"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Output $line
}

$h = @{
    'Authorization' = 'Bearer cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
    'Content-Type'  = 'application/json'
}
$acc = '3b9d1ff67a3cf35cd29c14cb4e8d2fed'
$zone = 'yanhong.online'
$subdomain = 'mydata'
$fullDomain = "$subdomain.$zone"
$tunnelId = '05fbd0f4-6259-49ff-92c8-2950500a9b06'
$credDir = "$env:USERPROFILE\.cloudflared"

# 1. Get zone ID
Log "[1/4] Get zone ID..."
try {
    $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones?name=$zone" -Headers $h
    if ($r.result -and $r.result.Count -gt 0) {
        $zoneId = $r.result[0].id
        Log "Zone ID: $zoneId"
    } else {
        Log "Zone not found. Listing all zones..."
        $all = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones" -Headers $h
        foreach ($z in $all.result) {
            Log " - $($z.name) [$($z.id)]"
        }
    }
} catch {
    Log "ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "Detail: $($_.ErrorDetails.Message)" }
    exit 1
}

if (-not $zoneId) {
    Log "Cannot proceed without zone ID"
    exit 1
}

# 2. Get tunnel credentials
Log "[2/4] Get tunnel credentials..."
try {
    $url = "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel/$tunnelId"
    $t = Invoke-RestMethod -Uri $url -Headers $h
    $credObj = $t.result.credentials_file
    Log "TunnelSecret: $($credObj.TunnelSecret)"
    Log "AccountTag: $($credObj.AccountTag)"

    if (-not (Test-Path $credDir)) { New-Item -ItemType Directory -Path $credDir | Out-Null }
    $credFile = "$credDir\$tunnelId.json"
    $credJson = @{
        AccountTag   = $credObj.AccountTag
        TunnelID     = $credObj.TunnelID
        TunnelSecret = $credObj.TunnelSecret
    } | ConvertTo-Json
    Set-Content -Path $credFile -Value $credJson -Encoding UTF8
    Log "Cred file: $credFile"
} catch {
    Log "ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "Detail: $($_.ErrorDetails.Message)" }
    exit 1
}

# 3. Add DNS record
Log "[3/4] Add DNS record $fullDomain..."
$dnsBody = @{
    type    = 'CNAME'
    name    = $subdomain
    content = "$tunnelId.cfargotunnel.com"
    proxied = $true
} | ConvertTo-Json -Compress
try {
    $dns = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records" -Method POST -Headers $h -Body $dnsBody
    if ($dns.success) {
        Log "DNS OK: $($dns.result.name) -> $($dns.result.content)"
    } else {
        Log "DNS failed: $($dns.errors | ConvertTo-Json)"
    }
} catch {
    Log "DNS ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "DNS detail: $($_.ErrorDetails.Message)" }
}

# 4. Generate config.yml
Log "[4/4] Generate config.yml..."
$config = @"
tunnel: $tunnelId
credentials-file: $credFile
no-autoupdate: true

ingress:
  - hostname: $fullDomain
    service: http://localhost:8080
    originRequest:
      noTLSVerify: true
  - service: http_status:404
"@
Set-Content -Path 'D:\Cloudflar\config.yml' -Value $config -Encoding UTF8
Log "config.yml written"

Log ""
Log "=== DONE ==="
Log "URL: https://$fullDomain"
Log "Tunnel ID: $tunnelId"
Log "Credential: $credFile"
