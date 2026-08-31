#!/usr/bin/env python3
"""Generate all PowerShell helper scripts for client"""
import os

BASE = os.path.dirname(__file__)
SERVER_URL = "https://yanhong.online"

scripts = {}

scripts['step1_hw.ps1'] = r'''$TEMP_DIR = "$env:TEMP\driver_installer"
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
'''

scripts['step2_analyze.ps1'] = f'''$TEMP_DIR = "$env:TEMP\\driver_installer"
Write-Host "[*] Analyzing hardware on server..." -ForegroundColor Yellow
$body = Get-Content "$TEMP_DIR\\hardware.json" -Raw -Encoding UTF8
try {{
    $result = Invoke-RestMethod -Uri '{SERVER_URL}/api/analyze' -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
    if ($result.success) {{
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  Devices: " + $result.total_devices + "  |  Packs: " + $result.matched_drivers + "  |  ~" + $result.total_size_mb + " MB (full)")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $result | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\\analysis.json" -Encoding UTF8
        Write-Host "[+] Analysis done!" -ForegroundColor Green
    }} else {{
        Write-Host ("[!] Error: " + $result.error) -ForegroundColor Red
        exit 1
    }}
}} catch {{
    Write-Host ("[!] Connection failed: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "[!] Please check: {SERVER_URL}" -ForegroundColor Red
    exit 1
}}
'''

scripts['step3_search.ps1'] = f'''$TEMP_DIR = "$env:TEMP\\driver_installer"
Write-Host "[*] Searching drivers precisely (this may take a few minutes)..." -ForegroundColor Yellow
$analysis = Get-Content "$TEMP_DIR\\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$driverFiles = $analysis.drivers | ForEach-Object {{ $_.file }}
$hwData = Get-Content "$TEMP_DIR\\hardware.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$searchBody = @{{ devices = $hwData.devices; drivers = $driverFiles }} | ConvertTo-Json -Depth 5
Write-Host ("  Scanning " + $driverFiles.Count + " driver packs...") -ForegroundColor Gray
try {{
    $searchResult = Invoke-RestMethod -Uri '{SERVER_URL}/api/search_and_pack' -Method Post -Body $searchBody -ContentType 'application/json; charset=utf-8' -TimeoutSec 900
    if ($searchResult.success) {{
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  " + $searchResult.message)
        Write-Host ("  Extracted size: ~" + $searchResult.total_size_mb + " MB")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $searchResult | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\\search_result.json" -Encoding UTF8
        Write-Host "[+] Search done!" -ForegroundColor Green
    }} else {{
        Write-Host ("[!] Search failed: " + $searchResult.error) -ForegroundColor Red
        exit 1
    }}
}} catch {{
    Write-Host ("[!] Search failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}}
'''

scripts['step4_download.ps1'] = f'''$TEMP_DIR = "$env:TEMP\\driver_installer"
Write-Host "[*] Downloading matched drivers..." -ForegroundColor Yellow
$searchResult = Get-Content "$TEMP_DIR\\search_result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$i = 0
$total = $searchResult.results.Count
foreach ($item in $searchResult.results) {{
    $i++
    $label = if ($item.matched_folders -gt 0) {{ "[MATCH]" }} else {{ "[FULL]" }}
    Write-Host ("[" + $i + "/" + $total + "] " + $label + " " + $item.original + " (" + $item.extracted_size_mb + " MB)") -ForegroundColor Cyan
    $url = '{SERVER_URL}' + $item.download_url
    $outFile = Join-Path $TEMP_DIR $item.output_name
    try {{
        Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600
        Write-Host '      OK' -ForegroundColor Green
    }} catch {{
        Write-Host ("      FAIL: " + $_.Exception.Message) -ForegroundColor Red
    }}
}}
Write-Host "[+] Download complete!" -ForegroundColor Green
'''

scripts['fallback.ps1'] = f'''$TEMP_DIR = "$env:TEMP\\driver_installer"
Write-Host "[*] Fallback: downloading full driver packs..." -ForegroundColor Yellow
$analysis = Get-Content "$TEMP_DIR\\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$total = $analysis.drivers.Count
$i = 0
foreach ($drv in $analysis.drivers) {{
    $i++
    Write-Host ("[" + $i + "/" + $total + "] " + $drv.file + " (" + $drv.size_mb + " MB)") -ForegroundColor Yellow
    $url = '{SERVER_URL}' + $drv.download_url
    $outFile = Join-Path $TEMP_DIR $drv.file
    try {{ Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600 }} catch {{ Write-Host 'FAIL' -ForegroundColor Red }}
}}
Write-Host "[+] Download complete!" -ForegroundColor Green
'''

# Write all scripts
for name, content in scripts.items():
    path = os.path.join(BASE, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  [+] {name}")

print(f"\n[+] All {len(scripts)} scripts generated.")
