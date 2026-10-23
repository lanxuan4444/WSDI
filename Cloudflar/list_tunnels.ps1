$ProgressPreference = 'SilentlyContinue'
$logFile = 'D:\Cloudflar\tunnels.txt'
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

Log "Listing all tunnels in account $acc..."
try {
    $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel" -Headers $h
    foreach ($t in $r.result) {
        Log "Tunnel: $($t.name) ID: $($t.id) Status: $($t.status)"
    }
    Log "Total: $($r.result.Count)"
} catch {
    Log "ERR: $($_.Exception.Message)"
}
