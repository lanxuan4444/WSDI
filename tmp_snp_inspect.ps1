# Inspect SDI state snapshot (.snp) format
$ErrorActionPreference = 'SilentlyContinue'
$logdir = "$env:TEMP\SDI_logs"
Get-ChildItem $logdir | Sort-Object LastWriteTime -Descending | Select-Object -First 6 | ForEach-Object {
    Write-Host ("FILE: " + $_.Name + "  " + $_.Length + " bytes  " + $_.LastWriteTime)
}

$snp = Get-ChildItem "$logdir\*_state.snp" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($snp) {
    Write-Host ''
    Write-Host ("=== inspecting: " + $snp.FullName + " ===")
    $bytes = [System.IO.File]::ReadAllBytes($snp.FullName)
    Write-Host ("first 64 bytes hex: " + (($bytes[0..63] | ForEach-Object { $_.ToString('X2') }) -join ' '))
    # try read as text
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    Write-Host ("starts with printable text: " + ($text.Substring(0, [Math]::Min(200, $text.Length)) -replace '[^\x20-\x7E]', '.'))
}

# also peek the log for match info
$log = Get-ChildItem "$logdir\*_log.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) {
    Write-Host ''
    Write-Host ("=== log tail (match info): " + $log.Name + " ===")
    Get-Content $log.FullName -Tail 60
}
