$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] Analyzing hardware on server..." -ForegroundColor Yellow
$body = Get-Content "$TEMP_DIR\hardware.json" -Raw -Encoding UTF8
try {
    $result = Invoke-RestMethod -Uri 'https://yanhong.online/api/analyze' -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
    if ($result.success) {
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  Devices: " + $result.total_devices + "  |  Packs: " + $result.matched_drivers + "  |  ~" + $result.total_size_mb + " MB (full)")
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $result | ConvertTo-Json -Depth 5 | Out-File "$TEMP_DIR\analysis.json" -Encoding UTF8
        Write-Host "[+] Analysis done!" -ForegroundColor Green
    } else {
        Write-Host ("[!] Error: " + $result.error) -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host ("[!] Connection failed: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "[!] Please check: https://yanhong.online" -ForegroundColor Red
    exit 1
}
