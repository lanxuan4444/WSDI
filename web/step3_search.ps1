$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] Searching drivers precisely (this may take a few minutes)..." -ForegroundColor Yellow
$analysis = Get-Content "$TEMP_DIR\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$driverFiles = $analysis.drivers | ForEach-Object { $_.file }
$hwData = Get-Content "$TEMP_DIR\hardware.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$searchBody = @{ devices = $hwData.devices; drivers = $driverFiles } | ConvertTo-Json -Depth 5
Write-Host ("  Scanning " + $driverFiles.Count + " driver packs...") -ForegroundColor Gray
try {
    $searchResult = Invoke-RestMethod -Uri 'https://yanhong.online/api/search_and_pack' -Method Post -Body $searchBody -ContentType 'application/json; charset=utf-8' -TimeoutSec 900
    if ($searchResult.success) {
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  " + $searchResult.message)
        Write-Host ("  Extracted size: ~" + $searchResult.total_size_mb + " MB")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $searchResult | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\search_result.json" -Encoding UTF8
        Write-Host "[+] Search done!" -ForegroundColor Green
    } else {
        Write-Host ("[!] Search failed: " + $searchResult.error) -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host ("[!] Search failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
