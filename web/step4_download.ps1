$TEMP_DIR = "$env:TEMP\driver_installer"
Write-Host "[*] Downloading matched drivers..." -ForegroundColor Yellow
$searchResult = Get-Content "$TEMP_DIR\search_result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$i = 0
$total = $searchResult.results.Count
foreach ($item in $searchResult.results) {
    $i++
    $label = if ($item.matched_folders -gt 0) { "[MATCH]" } else { "[FULL]" }
    Write-Host ("[" + $i + "/" + $total + "] " + $label + " " + $item.original + " (" + $item.extracted_size_mb + " MB)") -ForegroundColor Cyan
    $url = 'https://yanhong.online' + $item.download_url
    $outFile = Join-Path $TEMP_DIR $item.output_name
    try {
        Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 600
        Write-Host '      OK' -ForegroundColor Green
    } catch {
        Write-Host ("      FAIL: " + $_.Exception.Message) -ForegroundColor Red
    }
}
Write-Host "[+] Download complete!" -ForegroundColor Green
