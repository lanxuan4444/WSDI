# Test the full client flow locally
$TEMP_DIR = "$env:TEMP\driver_installer"
$SERVER_URL = "http://localhost:5000"

Write-Host "=== Step 1: Collect Hardware ===" -ForegroundColor Cyan
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
New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
$json | Out-File -FilePath "$TEMP_DIR\hardware.json" -Encoding UTF8
Write-Host "[+] detected $($devices.Count) devices" -ForegroundColor Green

Write-Host "`n=== Step 2: Analyze ===" -ForegroundColor Cyan
$body = Get-Content "$TEMP_DIR\hardware.json" -Raw -Encoding UTF8
try {
    $result = Invoke-RestMethod -Uri "$SERVER_URL/api/analyze" -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
    if ($result.success) {
        Write-Host "Devices: $($result.total_devices)  Packs: $($result.matched_drivers)  ~$($result.total_size_mb) MB" -ForegroundColor Green
        $result | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\analysis.json" -Encoding UTF8
    } else {
        Write-Host "Error: $($result.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Step 3: Search ===" -ForegroundColor Cyan
$analysis = Get-Content "$TEMP_DIR\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$driverFiles = $analysis.drivers | ForEach-Object { $_.file }
$hwData = Get-Content "$TEMP_DIR\hardware.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$searchBody = @{ devices = $hwData.devices; drivers = $driverFiles } | ConvertTo-Json -Depth 5
Write-Host "Searching in $($driverFiles.Count) packs..." -ForegroundColor Yellow
try {
    $searchResult = Invoke-RestMethod -Uri "$SERVER_URL/api/search_and_pack" -Method Post -Body $searchBody -ContentType 'application/json; charset=utf-8' -TimeoutSec 600
    if ($searchResult.success) {
        Write-Host $searchResult.message -ForegroundColor Green
        Write-Host "Extracted: ~$($searchResult.total_size_mb) MB" -ForegroundColor Green
        $searchResult | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\search_result.json" -Encoding UTF8
    } else {
        Write-Host "Error: $($searchResult.error)" -ForegroundColor Red
    }
} catch {
    Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "Results saved to: $TEMP_DIR"
