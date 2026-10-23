$ProgressPreference = 'SilentlyContinue'
$h = @{
    'Authorization' = 'Bearer cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b'
    'Content-Type'  = 'application/json'
}

try {
    $r = Invoke-RestMethod -Uri 'https://api.cloudflare.com/client/v4/zones?name=yanhong.online' -Headers $h
    Write-Output 'Success'
    Write-Output ('Count: ' + $r.result.Count)
    if ($r.result.Count -gt 0) {
        foreach ($z in $r.result) {
            Write-Output ('Zone ID: ' + $z.id + ' | Name: ' + $z.name + ' | Status: ' + $z.status)
        }
    }
} catch {
    Write-Output ('ERR: ' + $_.Exception.Message)
    if ($_.ErrorDetails) { Write-Output ('Detail: ' + $_.ErrorDetails.Message) }
}
