$body = Get-Content "$env:TEMP\driver_installer\hardware.json" -Raw -Encoding UTF8
try {
    $result = Invoke-RestMethod -Uri 'https://yanhong.online/api/analyze' -Method Post -Body $body -ContentType 'application/json; charset=utf-8' -TimeoutSec 120
    if ($result.success) {
        Write-Host ''
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ("  Devices: " + $result.total_devices + "  |  Matched Packs: " + $result.matched_drivers + "  |  ~" + $result.total_size_mb + " MB (full)") -ForegroundColor Cyan
        Write-Host '========================================' -ForegroundColor Cyan
        Write-Host ''
        $result | ConvertTo-Json -Depth 5 | Out-File "$env:TEMP\driver_installer\analysis.json" -Encoding UTF8
        Write-Host '[+] Analysis done! Starting search...' -ForegroundColor Green
    } else {
        Write-Host ("[!] Analysis failed: " + $result.error) -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host ("[!] Connection failed: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host '[!] Please ensure https://yanhong.online is accessible' -ForegroundColor Red
    exit 1
}
