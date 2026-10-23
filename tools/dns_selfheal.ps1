# ============================================================
# yanhong.online apex DNS record self-heal
# Called by the WSDI service restart batch (D:\WSDI, Chinese filename)
# after all services start.
#
# What it does:
#   1. Query yanhong.online (apex) via 1.1.1.1 (bypasses local DNS cache)
#   2. If NODATA (tunnel CNAME record lost at Cloudflare side),
#      recreate it with: cloudflared tunnel route dns <tunnel> <domain>
#      using the cert.pem (restored 2026-10-16, backup at
#      D:\WSDI\Cloudflar\backup\.cloudflared\cert.pem)
#   3. Verify resolution after the fix
#
# NOTE: intentionally ASCII-only (no Chinese) - PS 5.1 reads BOM-less
# .ps1 as ANSI, Chinese literals would garble.
# ============================================================

$ErrorActionPreference = 'SilentlyContinue'

$domain      = 'yanhong.online'
$tunnelId    = '2967bed7-9021-4ed4-bf20-9b2658ba516c'
$cloudflared = 'D:\WSDI\Cloudflar\cloudflared.exe'
$certPath    = Join-Path $env:USERPROFILE '.cloudflared\cert.pem'

function Test-ApexDns {
    # True if the apex resolves to at least one address via 1.1.1.1
    $r4 = Resolve-DnsName -Name $domain -Server 1.1.1.1 -Type A -ErrorAction SilentlyContinue
    if ($r4 | Where-Object { $_.IPAddress }) { return $true }
    $r6 = Resolve-DnsName -Name $domain -Server 1.1.1.1 -Type AAAA -ErrorAction SilentlyContinue
    if ($r6 | Where-Object { $_.IPAddress }) { return $true }
    return $false
}

# ---- Fast path: record is fine (normal case, ~1s) ----
if (Test-ApexDns) {
    Write-Host '[OK] yanhong.online DNS record present'
    exit 0
}

# ---- Record missing: self-heal ----
Write-Host '[WARN] yanhong.online apex DNS record MISSING (NODATA) - self-healing...'

if (-not (Test-Path $cloudflared)) {
    Write-Host '[FAIL] cloudflared.exe not found at D:\WSDI\Cloudflar\cloudflared.exe'
    exit 1
}
$cert = Get-Item $certPath -ErrorAction SilentlyContinue
if (-not $cert -or $cert.Length -lt 100) {
    $size = 0
    if ($cert) { $size = $cert.Length }
    Write-Host "[FAIL] cert.pem invalid ($size bytes). Restore it from D:\WSDI\Cloudflar\backup\.cloudflared\cert.pem"
    Write-Host "       or run: D:\WSDI\Cloudflar\cloudflared.exe login  (browser auth, then copy cert.pem)"
    exit 1
}

# Distinguish "network down" from "record really missing": if we cannot
# even reach the Cloudflare API, do not attempt the fix.
$net = Test-NetConnection -ComputerName 'api.cloudflare.com' -Port 443 -WarningAction SilentlyContinue
if (-not $net.TcpTestSucceeded) {
    Write-Host '[FAIL] cannot reach api.cloudflare.com - network issue, DNS not touched'
    exit 1
}

Write-Host "Recreating: $domain -> $tunnelId.cfargotunnel.com"
$out = & $cloudflared tunnel route dns $tunnelId $domain 2>&1
Write-Host ("  " + ($out -join "`n  "))

# Verify (retry loop: resolver negative-cache may lag up to ~1 min)
for ($i = 1; $i -le 6; $i++) {
    Start-Sleep -Seconds 10
    if (Test-ApexDns) {
        Write-Host "[OK] $domain DNS record RECREATED and resolving (try $i/6)"
        exit 0
    }
    Write-Host "  ...not resolving yet ($i/6)"
}
Write-Host '[FAIL] route recreated but apex still not resolving.'
Write-Host '       Check Cloudflare dashboard for conflicting A/AAAA records at the apex.'
exit 1
