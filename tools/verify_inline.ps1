$ErrorActionPreference = 'Stop'

function Get-Disposition {
    param([string]$Uri)
    $req = [System.Net.HttpWebRequest]::Create($Uri)
    $req.Method = 'GET'
    $req.Timeout = 15000
    try {
        $resp = $req.GetResponse()
        $headers = $resp.Headers
        $status = [int]$resp.StatusCode
        $ct = $headers['Content-Type']
        $cd = $headers['Content-Disposition']
        $resp.Close()
        return @{ Status = $status; CT = $ct; CD = $cd }
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $status = [int]$resp.StatusCode
            $ct = $resp.Headers['Content-Type']
            $cd = $resp.Headers['Content-Disposition']
            $resp.Close()
            return @{ Status = $status; CT = $ct; CD = $cd }
        }
        throw
    }
}

foreach ($path in @('/tools', '/', '/client.bat')) {
    Write-Host ("=== " + $path + " ===") -ForegroundColor Cyan
    $r = Get-Disposition -Uri ('http://127.0.0.1' + $path)
    Write-Host ("Status:              " + $r.Status)
    Write-Host ("Content-Type:        " + $r.CT)
    Write-Host ("Content-Disposition: " + $r.CD)
    Write-Host ""
}