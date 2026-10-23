# 用 cloudflared 自带的命令生成 origin cert
$ProgressPreference = 'SilentlyContinue'
$certDir = "$env:USERPROFILE\.cloudflared"
$logFile = 'D:\Cloudflar\cert_log.txt'

function Log($m) {
    $t = Get-Date -Format 'HH:mm:ss'
    "$t $m" | Out-File -Append -FilePath $logFile -Encoding UTF8
}

Log "==== Start ===="

# 尝试用 cloudflared origin tls 命令
Log "Try: origin tls..."
& 'D:\Cloudflar\cloudflared.exe' origin tls --help 2>&1 | Out-File -FilePath 'D:\Cloudflar\tls_help.txt' -Encoding UTF8

# 列出现有子命令
Log "Try: tunnel --help..."
& 'D:\Cloudflar\cloudflared.exe' tunnel --help 2>&1 | Out-File -FilePath 'D:\Cloudflar\tunnel_help.txt' -Encoding UTF8

Log "==== End ===="
