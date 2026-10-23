$ProgressPreference = 'SilentlyContinue'
$logFile = 'D:\Cloudflar\yanhong_setup_log.txt'
$cfToken = 'cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
$acc = '3b9d1ff67a3cf35cd29c14cb4e8d2fed'
$zone = 'yanhong.online'
$subdomain = 'mydata'
$fullDomain = "$subdomain.$zone"
$credDir = "$env:USERPROFILE\.cloudflared"

function Log([string]$m) {
    $t = Get-Date -Format 'HH:mm:ss'
    $line = "[$t] $m"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Output $line
}

# Reset log
Set-Content -Path $logFile -Value '' -Encoding UTF8

Log "=== Setup $fullDomain tunnel ==="

$h = @{
    'Authorization' = "Bearer $cfToken"
    'Content-Type'  = 'application/json'
}

# 1. Get zone ID
Log "[1/6] Getting zone ID for $zone..."
try {
    $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones?name=$zone" -Headers $h
    if ($r.result -and $r.result.Count -gt 0) {
        $zoneId = $r.result[0].id
        Log "Zone ID: $zoneId"
    } else {
        Log "ERROR: zone not found. Response: $($r | ConvertTo-Json -Compress)"
    }
} catch {
    Log "ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "ERR detail: $($_.ErrorDetails.Message)" }
}

if (-not $zoneId) { exit 1 }

# 2. Delete old mytunnel
Log "[2/6] Deleting old mytunnel..."
try {
    $list = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel?name=mytunnel" -Headers $h
    if ($list.result -and $list.result.Count -gt 0) {
        $oldId = $list.result[0].id
        Log "Deleting: $oldId"
        Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel/$oldId" -Method DELETE -Headers $h | Out-Null
    } else {
        Log "No old tunnel to delete"
    }
} catch {
    Log "Delete ERR: $($_.Exception.Message)"
}

# 3. Create new yanhong tunnel
Log "[3/6] Creating named tunnel 'yanhong'..."
try {
    $body = '{"name":"yanhong","config_src":"cloudflare"}'
    $created = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel" -Method POST -Headers $h -Body $body
    if ($created.success) {
        $tid = $created.result.id
        $secret = $created.result.credentials_file.TunnelSecret
        $accountTag = $created.result.credentials_file.AccountTag
        Log "NEW_TUNNEL_ID: $tid"
        Log "AccountTag: $accountTag"

        # 4. Write credential file
        Log "[4/6] Writing credential file..."
        if (-not (Test-Path $credDir)) { New-Item -ItemType Directory -Path $credDir | Out-Null }
        $credFile = "$credDir\$tid.json"
        $credObj = @{
            AccountTag    = $accountTag
            TunnelID      = $tid
            TunnelSecret  = $secret
        } | ConvertTo-Json
        Set-Content -Path $credFile -Value $credObj -Encoding UTF8
        Log "Credential file: $credFile"

        # 5. Add DNS record
        Log "[5/6] Adding DNS record $fullDomain..."
        $dnsBody = @{
            type    = 'CNAME'
            name    = $subdomain
            content = "$tid.cfargotunnel.com"
            proxied = $true
        } | ConvertTo-Json -Compress
        try {
            $dns = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records" -Method POST -Headers $h -Body $dnsBody
            if ($dns.success) {
                Log "DNS record OK: $($dns.result.name) -> $($dns.result.content)"
            } else {
                Log "DNS failed: $($dns.errors | ConvertTo-Json)"
            }
        } catch {
            Log "DNS ERR: $($_.Exception.Message)"
            if ($_.ErrorDetails) { Log "DNS detail: $($_.ErrorDetails.Message)" }
        }

        # 6. Generate config.yml
        Log "[6/6] Generating config.yml..."
        $config = @"
tunnel: $tid
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
        Log "Tunnel ID: $tid"
        Log "Credential: $credFile"
    } else {
        Log "Create failed: $($created.errors | ConvertTo-Json)"
    }
} catch {
    Log "Create ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "ERR detail: $($_.ErrorDetails.Message)" }
}

Log "=== End ==="
