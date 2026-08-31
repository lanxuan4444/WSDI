# Restart WSDI service cleanly
Get-Process python, pythonw, cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$remaining = Get-Process python, pythonw, cloudflared -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Host "Remaining processes, retrying force kill..." -ForegroundColor Red
    $remaining | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
Start-Process -FilePath "C:\Users\Administrator\AppData\Local\Programs\Python\Python315\pythonw.exe" -ArgumentList "D:\WSDI\WSDI_Tray.py" -WindowStyle Hidden
Start-Sleep -Seconds 2
$procs = Get-Process python, pythonw -ErrorAction SilentlyContinue
$procs | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize
