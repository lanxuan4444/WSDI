$ProgressPreference = 'SilentlyContinue'
$certDir = "$env:USERPROFILE\.cloudflared"
if (-not (Test-Path $certDir)) {
    New-Item -ItemType Directory -Path $certDir | Out-Null
}
Write-Output "Cert dir: $certDir"

# 尝试用 cloudflared 生成 origin cert
Write-Output "Running: cloudflared origin cert create..."
& 'D:\Cloudflar\cloudflared.exe' origin cert create 2>&1 | Out-File -FilePath 'D:\Cloudflar\cert_out.txt' -Encoding UTF8
Get-Content 'D:\Cloudflar\cert_out.txt'

Write-Output ""
Write-Output "Files in cert dir:"
Get-ChildItem $certDir | Format-Table Name, Length
