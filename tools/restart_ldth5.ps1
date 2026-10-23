$ErrorActionPreference = 'SilentlyContinue'

Get-Process pythonw -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ("Killing PID " + $_.Id)
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 3

$conn = Get-NetTCPConnection -LocalPort 9876 -ErrorAction SilentlyContinue
if ($conn) {
    Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

Write-Host "Starting LDTH5..." -ForegroundColor Cyan
Start-Process -FilePath 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe' `
    -ArgumentList 'D:\WSDI\LDTH5\server.py' `
    -WorkingDirectory 'D:\WSDI\LDTH5' `
    -WindowStyle Hidden

Start-Sleep -Seconds 6

$proc = Get-Process pythonw -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host ("[OK] LDTH5 started (PID " + $proc.Id + ")") -ForegroundColor Green
} else {
    Write-Host "[!] LDTH5 failed to start" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Recent log ===" -ForegroundColor Cyan
$logFile = 'D:\WSDI\LDTH5\Run_log\2026_8\server.log'
if (Test-Path $logFile) {
    Get-Content $logFile -Tail 12 -Encoding UTF8
}
