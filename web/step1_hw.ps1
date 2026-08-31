$TEMP_DIR = "$env:TEMP\driver_installer"
$SDI_DIR = "$TEMP_DIR\SDI"
New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $SDI_DIR -Force | Out-Null

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "    WSDI Driver Installer - Hardware Detection" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[*] Collecting hardware info via pnputil..."
$devices = @()
try {
    $raw = pnputil /enum-devices /problem 2>&1
    $lines = $raw -split "`r`n|`n"
    $current = $null
    foreach ($line in $lines) {
        if ($line -match '^Instance ID:\s*(.+)$') {
            if ($current) { $devices += $current }
            $current = @{ hwid = $matches[1].Trim(); description = "" }
        }
        elseif ($line -match '^\s*Device Description:\s*(.+)$') {
            if ($current) { $current.description = $matches[1].Trim() }
        }
    }
    if ($current) { $devices += $current }
} catch {
    Write-Host "[!] Failed to scan devices" -ForegroundColor Red
    exit 1
}

if ($devices.Count -eq 0) {
    Write-Host "[+] No problem devices found! Drivers are all good." -ForegroundColor Green
    exit 0
}

Write-Host ("  Found " + $devices.Count + " problem device(s)") -ForegroundColor Cyan

$hwFile = "$TEMP_DIR\hardware.json"
@{ devices = $devices } | ConvertTo-Json -Depth 3 | Out-File -FilePath $hwFile -Encoding UTF8

if (Test-Path $hwFile) {
    Write-Host "[+] Hardware info saved to: $hwFile" -ForegroundColor Green
} else {
    Write-Host "[!] Failed to collect hardware info" -ForegroundColor Red
    exit 1
}
