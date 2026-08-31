$devices = @()
$output = pnputil /enum-devices /connected 2>$null
$lines = $output -split "`r`n"
$current = $null
foreach ($line in $lines) {
    if ($line -match '^Instance ID:\s*(.+)$') {
        if ($current) { $devices += $current }
        $current = @{ hwid = $Matches[1].Trim() }
    }
    if ($line -match '^Device Description:\s*(.+)$') {
        if ($current) { $current.description = $Matches[1].Trim() }
    }
}
if ($current) { $devices += $current }
$json = @{ devices = $devices } | ConvertTo-Json -Depth 3
$outDir = "$env:TEMP\driver_installer"
if (!(Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
$json | Out-File -FilePath "$outDir\hardware.json" -Encoding UTF8
Write-Host ("[+] detected " + $devices.Count + " devices") -ForegroundColor Green
