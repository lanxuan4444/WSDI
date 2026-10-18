# Full-index SDI headless scan experiment
$ErrorActionPreference = 'Continue'
$root = 'D:\WSDI\tmp_sdi_scan\SDI\SDI'   # exe + sdi.cfg live here
$exe = "$root\SDI_x64_R2606.exe"

# 1) junction full index into working dir
if (Test-Path "$root\Index\SDI") { Remove-Item "$root\Index\SDI" -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Junction -Path "$root\Index\SDI" -Target 'D:\SDI\Index\SDI' | Out-Null
Write-Host ("junction created -> " + (Get-ChildItem "$root\Index\SDI" -Filter *.bin).Count + " bins")

# 2) clean old logs so we parse only the fresh one
Remove-Item "$env:TEMP\SDI_logs\*" -Force -ErrorAction SilentlyContinue

# 3) run headless scan (console mode; process exits by itself after scan+state save)
Write-Host '--- running SDI scan (checkupdates off) ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $exe -ArgumentList '-checkupdates:0' -WorkingDirectory $root -Wait -PassThru -WindowStyle Hidden
Write-Host ("exit code: " + $p.ExitCode + "  elapsed: " + [int]$sw.Elapsed.TotalSeconds + "s")

# 4) find fresh log + state
Get-ChildItem "$env:TEMP\SDI_logs" | ForEach-Object { Write-Host ("LOGDIR: " + $_.Name + " " + $_.Length + "B") }
