$ProgressPreference = 'SilentlyContinue'
$cfToken = 'cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
$acc = '3b9d1ff67a3cf35cd29c14cb4e8d2fed'
$logFile = 'D:\Cloudflar\add_zone.txt'
Set-Content -Path $logFile -Value '' -Encoding UTF8

function Log([string]$m) {
    $t = Get-Date -Format 'HH:mm:ss'
    $line = "[$t] $m"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Output $line
}

$h = @{
    'Authorization' = "Bearer $cfToken"
    'Content-Type'  = 'application/json'
}

Log "Trying to add yanhong.online zone..."
$body = @{
    name      = 'yanhong.online'
    account   = @{ id = $acc }
    type      = 'full'
    jump_start = $true
} | ConvertTo-Json -Compress

Log "Request: $body"

try {
    $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones" -Method POST -Headers $h -Body $body
    Log "Success: $($r.success)"
    if ($r.success) {
        Log "Zone ID: $($r.result.id)"
        Log "Status: $($r.result.status)"
        Log "Name servers: $($r.result.name_servers -join ', ')"
    } else {
        Log "Errors: $($r.errors | ConvertTo-Json)"
    }
} catch {
    Log "ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Log "Detail: $($_.ErrorDetails.Message)" }
}
