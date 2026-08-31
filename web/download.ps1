$searchResult = Get-Content "$env:TEMP\driver_installer\search_result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$i = 0
$total = $searchResult.results.Count
foreach ($item in $searchResult.results) {
    $i++
    Write-Host ("[0/1] Download: 2 (3 MB)" -f $i, $total, $item.original, $item.extracted_size_mb) -ForegroundColor Cyan
    $url = 'https://yanhong.online' + $item.download_url
    $outFile = Join-Path "$env:TEMP\driver_installer" $item.output_name
    try {
        Invoke-WebRequest -Uri $url -OutFile $outFile -TimeoutSec 300
        Write-Host '      OK' -ForegroundColor Green
    } catch {
        Write-Host ("      FAIL: " + $_.Exception.Message) -ForegroundColor Red
    }
}
