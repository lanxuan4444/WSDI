# SDI headless scan experiment on this machine
$ErrorActionPreference = 'Continue'
$work = 'D:\WSDI\tmp_sdi_scan'
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Path "$work\SDI" -Force | Out-Null
New-Item -ItemType Directory -Path "$work\SDI\Index\SDI" -Force | Out-Null
New-Item -ItemType Directory -Path "$work\SDI\Drivers" -Force | Out-Null

# 1) extract SDI lite
& 'D:\WSDI\tools\7z' 2>$null # no-op guard
$7z = 'D:\WSDI\cache\tools\7z_portable.zip'
Write-Host '--- extracting SDI lite ---'
Expand-Archive -Path $7z -DestinationPath "$work\tools" -Force
& "$work\tools\7z.exe" x "D:\WSDI\cache\sdi_lite\SDI_R2601.7z" "-o$work\SDI" -y | Select-Object -Last 2
$exe = Get-ChildItem "$work\SDI" -Filter 'SDI_x64*.exe' -Recurse | Select-Object -First 1
Write-Host "SDI exe: $($exe.FullName)"

# 2) show help
Write-Host ''
Write-Host '=== SDI -help output ==='
& $exe.FullName -help 2>&1 | Out-File "$work\help.txt" -Encoding UTF8
Get-Content "$work\help.txt"
