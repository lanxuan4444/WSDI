$analysis = Get-Content "$env:TEMP\driver_installer\analysis.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$driverFiles = $analysis.drivers | ForEach-Object { $_.file }
$hwData = Get-Content "$env:TEMP\driver_installer\hardware.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$devices = $hwData.devices
Write-Host ("[*] Searching in " + $driverFiles.Count + " driver packs...") -ForegroundColor Yellow
$searchBody = @{ devices = $devices; drivers = $driverFiles } | ConvertTo-Json -Depth 5
try {
    $searchResult = Invoke-RestMethod -Uri 'https://yanhong.online/api/search_and_pack' -Method Post -Body $searchBody -ContentType 'application/json; charset=utf-8' -TimeoutSec 600
    if ($searchResult.success) {
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  Result: " + $searchResult.message)
        Write-Host ("  Extracted: ~" + $searchResult.total_size_mb + " MB")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $searchResult | ConvertTo-Json -Depth 5 | Out-File "$env:TEMP\driver_installer\search_result.json" -Encoding UTF8
        Write-Host '[+] Search done! Downloading...' -ForegroundColor Green
    } else {
        Write-Host ("[!] Search failed: " + $searchResult.error) -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host ("[!] Search failed: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
