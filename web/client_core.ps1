# ============================================================
# WSDI Driver Installer - Core Script (CLI)
# ============================================================
$ErrorActionPreference = "Continue"
$ProgressPreference = 'SilentlyContinue'

$SERVER = "https://yanhong.online"

$TEMP_DIR = "$env:TEMP\WSDI"
$SDI_DIR = "$TEMP_DIR\SDI"
$DRIVERS_DIR = "$TEMP_DIR\Drivers"
$TOOLS_DIR = "$TEMP_DIR\Tools"

New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $SDI_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $DRIVERS_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $TOOLS_DIR -Force | Out-Null

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "    WSDI Driver Installer v1.0" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# =============================================
# Step 0: Download SDI Lite & 7-Zip Portable
# =============================================
Write-Host "[*] Step 0: Preparing tools..." -ForegroundColor Yellow

# Download SDI Lite (7z)
$sdiLitePath = "$TEMP_DIR\SDI_R2601.7z"
if (-not (Test-Path $sdiLitePath)) {
    Write-Host "  Downloading SDI Lite..."
    try {
        Invoke-WebRequest "$SERVER/api/sdi_lite" -OutFile $sdiLitePath -UseBasicParsing -TimeoutSec 120
        Write-Host "  SDI Lite OK" -ForegroundColor Green
    } catch {
        Write-Host ("  [!] SDI Lite download failed: " + $_.Exception.Message) -ForegroundColor Red
        exit 1
    }
}

# Download 7-Zip Portable
$zip7Path = "$TEMP_DIR\7z_portable.zip"
if (-not (Test-Path $zip7Path)) {
    Write-Host "  Downloading 7-Zip Portable..."
    try {
        Invoke-WebRequest "$SERVER/api/7z_portable" -OutFile $zip7Path -UseBasicParsing -TimeoutSec 120
        Write-Host "  7-Zip OK" -ForegroundColor Green
    } catch {
        Write-Host ("  [!] 7-Zip download failed: " + $_.Exception.Message) -ForegroundColor Red
        exit 1
    }
}

# Extract 7-Zip
if (-not (Test-Path "$TOOLS_DIR\7z.exe")) {
    Write-Host "  Extracting 7-Zip..."
    Expand-Archive -Path $zip7Path -DestinationPath $TOOLS_DIR -Force
}

$SEVEN_ZIP = "$TOOLS_DIR\7z.exe"

# Extract SDI Lite
if (-not (Test-Path "$SDI_DIR\SDI_x64_R2606.exe")) {
    Write-Host "  Extracting SDI Lite..."
    & $SEVEN_ZIP x $sdiLitePath -o"$SDI_DIR" -y -aoa | Out-Null
}
Write-Host "[+] Tools ready" -ForegroundColor Green

# =============================================
# Step 1: Collect problem devices via pnputil
# =============================================
Write-Host ""
Write-Host "[*] Step 1: Scanning problem devices..." -ForegroundColor Yellow

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
    Write-Host "[+] No problem devices found! Your drivers are all good." -ForegroundColor Green
    exit 0
}

Write-Host ("  Found " + $devices.Count + " problem device(s):") -ForegroundColor Cyan
foreach ($d in $devices) {
    Write-Host ("    - " + $d.description + " [" + $d.hwid.Substring(0, [Math]::Min(60, $d.hwid.Length)) + "...]")
}
Write-Host "[+] Device scan complete" -ForegroundColor Green

# =============================================
# Step 2: Analyze on server
# =============================================
Write-Host ""
Write-Host "[*] Step 2: Analyzing on server..." -ForegroundColor Yellow

$body = @{ devices = $devices } | ConvertTo-Json -Depth 5
try {
    $result = Invoke-RestMethod -Uri "$SERVER/api/analyze" -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
    if (-not $result.success) {
        Write-Host ("[!] Analysis failed: " + $result.error) -ForegroundColor Red
        exit 1
    }
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ("  Devices: " + $result.total_devices + "  |  Matched Packs: " + $result.matched_drivers)
    Write-Host ("  Total size: ~" + $result.total_size_mb + " MB (full)")
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    $result | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\analysis.json" -Encoding UTF8
    Write-Host "[+] Analysis done!" -ForegroundColor Green
} catch {
    Write-Host ("[!] Connection failed: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "[!] Check server: $SERVER" -ForegroundColor Red
    exit 1
}

# =============================================
# Step 3: Download matched drivers
# =============================================
Write-Host ""
Write-Host "[*] Step 3: Downloading matched drivers..." -ForegroundColor Yellow

$analysis = Get-Content "$TEMP_DIR\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$i = 0
$total = $analysis.drivers.Count
$failed = 0

foreach ($drv in $analysis.drivers) {
    $i++
    Write-Host ("[" + $i + "/" + $total + "] " + $drv.name + " (" + $drv.size_mb + " MB)") -ForegroundColor Cyan
    $url = $SERVER + $drv.download_url
    $outFile = Join-Path $DRIVERS_DIR $drv.file
    try {
        Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600 -UseBasicParsing
        Write-Host "      OK" -ForegroundColor Green
    } catch {
        Write-Host ("      FAIL: " + $_.Exception.Message) -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host ("[+] Download complete: " + ($total - $failed) + "/" + $total + " succeeded") -ForegroundColor $(if ($failed -gt 0) { "Yellow" } else { "Green" })

# =============================================
# Step 4: Extract drivers & install with SDI
# =============================================
Write-Host ""
Write-Host "[*] Step 4: Extracting and installing drivers..." -ForegroundColor Yellow

# Extract all 7z driver packs into Drivers folder
$driverFiles = Get-ChildItem $DRIVERS_DIR -Filter *.7z
foreach ($f in $driverFiles) {
    $name = $f.BaseName
    $destDir = Join-Path $DRIVERS_DIR $name
    if (-not (Test-Path $destDir)) {
        Write-Host ("  Extracting: " + $f.Name)
        & $SEVEN_ZIP x $f.FullName -o"$destDir" -y -aoa | Out-Null
    }
}

# Run SDI Lite to install drivers
Write-Host ""
Write-Host "[*] Launching SDI Lite for auto-install..." -ForegroundColor Yellow

$sdiExe = Get-ChildItem $SDI_DIR -Filter "SDI*.exe" | Select-Object -First 1
if ($sdiExe) {
    Write-Host ("  Starting: " + $sdiExe.Name)
    Write-Host "  SDI will auto-scan the Drivers folder and install drivers." -ForegroundColor Gray
    Write-Host "  Please wait for SDI to finish..." -ForegroundColor Gray
    Start-Process -FilePath $sdiExe.FullName -ArgumentList "-autoinstall" -Wait -NoNewWindow
    Write-Host "[+] SDI install complete!" -ForegroundColor Green
} else {
    Write-Host "[!] SDI executable not found in extracted files" -ForegroundColor Red
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "    All done! Drivers installed successfully." -ForegroundColor Cyan
Write-Host "    You may need to restart your computer." -ForegroundColor Yellow
Write-Host "================================================" -ForegroundColor Cyan
