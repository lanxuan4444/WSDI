$ProgressPreference = 'SilentlyContinue'
$h = @{
    'Authorization' = 'Bearer cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
    'Content-Type'  = 'application/json'
}

Write-Output "===== Token Verify ====="
try {
    $r = Invoke-RestMethod -Uri 'https://api.cloudflare.com/client/v4/user/tokens/verify' -Headers $h
    Write-Output "Token Valid: $($r.success)"
    Write-Output "Account ID: $($r.result.id)"
    Write-Output "Status: $($r.result.status)"
} catch {
    Write-Output "Token ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Write-Output "Detail: $($_.ErrorDetails.Message)" }
}

Write-Output ""
Write-Output "===== All Zones ====="
try {
    $r = Invoke-RestMethod -Uri 'https://api.cloudflare.com/client/v4/zones' -Headers $h
    foreach ($z in $r.result) {
        Write-Output "Zone: $($z.name) | ID: $($z.id) | Status: $($z.status)"
    }
    if ($r.result.Count -eq 0) {
        Write-Output "(No zones found)"
    }
} catch {
    Write-Output "Zone ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Write-Output "Detail: $($_.ErrorDetails.Message)" }
}

Write-Output ""
Write-Output "===== All Tunnels ====="
$acc = '3b9d1ff67a3cf35cd29c14cb4e8d2fed'
try {
    $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/accounts/$acc/cfd_tunnel" -Headers $h
    foreach ($t in $r.result) {
        Write-Output "Tunnel: $($t.name) | ID: $($t.id) | Status: $($t.status)"
    }
    if ($r.result.Count -eq 0) {
        Write-Output "(No tunnels found)"
    }
} catch {
    Write-Output "Tunnel ERR: $($_.Exception.Message)"
    if ($_.ErrorDetails) { Write-Output "Detail: $($_.ErrorDetails.Message)" }
}
