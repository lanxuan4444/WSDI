$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] Fallback: downloading full driver packs..." -ForegroundColor Yellow
$analysis = Get-Content "$TEMP_DIR\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$total = $analysis.drivers.Count
$i = 0
foreach ($drv in $analysis.drivers) {
    $i++
    Write-Host ("[" + $i + "/" + $total + "] " + $drv.file + " (" + $drv.size_mb + " MB)") -ForegroundColor Yellow
    $url = 'https://yanhong.online' + $drv.download_url
    $outFile = Join-Path $TEMP_DIR $drv.file
    try { Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600 } catch { Write-Host 'FAIL' -ForegroundColor Red }
}
Write-Host "[+] Download complete!" -ForegroundColor Green
