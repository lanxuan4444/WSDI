# ========================================
#  Step 0: 准备工具 (SDI Lite + 7-Zip)
# ========================================

$TEMP_DIR = "$env:TEMP\driver_installer"
$SDI_DIR = "$TEMP_DIR\SDI"
$SDI_TOOLS_DIR = "$TEMP_DIR\tools"
$SERVER = "https://yanhong.online"

New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $SDI_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $SDI_TOOLS_DIR -Force | Out-Null

# ====== 1. 下载 SDI Lite ======
$sdiLitePath = Join-Path $TEMP_DIR "SDI_R2601.7z"
$sdiExePath = Join-Path $SDI_DIR "SDI_x64_R2606.exe"
$sdiExePathAlt = Join-Path $SDI_DIR "SDI_x64.exe"

if ((Test-Path $sdiExePath) -or (Test-Path $sdiExePathAlt)) {
    if (Test-Path $sdiExePathAlt) { $sdiExePath = $sdiExePathAlt }
    Write-Host "[*] SDI Lite 已就绪"
} else {
    Write-Host "[*] 正在从服务器下载 SDI Lite..."
    try {
        $sdiLiteTemp = "$sdiLitePath.part"
        $request = [System.Net.HttpWebRequest]::Create("$SERVER/api/sdi_lite")
        $request.Timeout = 120000
        $response = $request.GetResponse()
        $totalBytes = [long]$response.ContentLength
        $stream = $response.GetResponseStream()
        $fileStream = [System.IO.File]::Create($sdiLiteTemp)
        $buffer = New-Object byte[] 65536
        $downloadedBytes = 0
        $lastUpdate = [DateTime]::Now

        try {
            while ($true) {
                $read = $stream.Read($buffer, 0, $buffer.Length)
                if ($read -le 0) { break }
                $fileStream.Write($buffer, 0, $read)
                $downloadedBytes += $read
                $now = [DateTime]::Now
                if (($now - $lastUpdate).TotalMilliseconds -gt 300) {
                    $pct = [math]::Min(100, [math]::Floor(($downloadedBytes / $totalBytes) * 100))
                    $barLen = 25
                    $filled = [math]::Floor($pct / 100 * $barLen)
                    $bar = ("[" + ("=" * $filled) + (" " * ($barLen - $filled)) + "]")
                    $curMB = [math]::Round($downloadedBytes / 1MB, 1)
                    $totMB = [math]::Round($totalBytes / 1MB, 1)
                    Write-Host ("`r  " + $bar + " " + $pct + "%  " + $curMB + "/" + $totMB + " MB  SDI Lite") -NoNewline
                    $lastUpdate = $now
                }
            }
        } finally {
            $fileStream.Close()
            $stream.Close()
            $response.Close()
        }

        Move-Item $sdiLiteTemp $sdiLitePath -Force
        $sdiSize = (Get-Item $sdiLitePath).Length
        # 收尾进度条
        Write-Host ("`r  [" + ("=" * 25) + "] 100%  " + [math]::Round($sdiSize/1MB,1) + "/" + [math]::Round($sdiSize/1MB,1) + " MB  SDI Lite")
        if ($sdiSize -lt 1MB) {
            Write-Host "[!] SDI Lite 下载无效"
            Remove-Item $sdiLitePath -Force
            throw "SDI Lite download invalid"
        }
        Write-Host ("  [+] SDI Lite 下载完成: " + [math]::Round($sdiSize/1MB,1) + " MB")

        # 解压到 SDI 目录
        Write-Host "[*] 正在解压 SDI Lite..."
        $sevenZip = Join-Path $SDI_TOOLS_DIR "7z.exe"
        if (-not (Test-Path $sevenZip)) {
            $sevenzZipPath = "$SDI_TOOLS_DIR\7z_portable.zip"

            # 方案1: 从服务器下载
            Write-Host "[*] 正在下载 7-Zip 便携版 (服务器)..."
            try {
                Invoke-WebRequest -Uri "$SERVER/api/7z_portable" -OutFile $sevenzZipPath -UseBasicParsing -TimeoutSec 60
                $zipSize = (Get-Item $sevenzZipPath).Length
                if ($zipSize -lt 1024) {
                    Remove-Item $sevenzZipPath -Force
                    Write-Host "[!] 7z 下载不完整"
                }
            } catch {
                Write-Host ("[!] 服务器下载失败: " + $_)
                if (Test-Path $sevenzZipPath) { Remove-Item $sevenzZipPath -Force }
            }

            # 方案2: 从 7-zip.org 官方下载安装包
            if (-not (Test-Path $sevenzZipPath)) {
                Write-Host "[*] 正在从 7-zip.org 下载..."
                try {
                    $sevenzMsi = "$SDI_TOOLS_DIR\7z_installer.msi"
                    Invoke-WebRequest -Uri "https://www.7-zip.org/a/7z2409-x64.msi" -OutFile $sevenzMsi -UseBasicParsing -TimeoutSec 120
                    if ((Get-Item $sevenzMsi).Length -gt 1MB) {
                        Write-Host "[*] 正在安装 7-Zip..."
                        Start-Process msiexec.exe -ArgumentList "/i `"$sevenzMsi`" /qn" -Wait
                        $installed7z = "${env:ProgramFiles}\7-Zip\7z.exe"
                        if (Test-Path $installed7z) {
                            Copy-Item $installed7z $sevenZip -Force
                            Copy-Item "${env:ProgramFiles}\7-Zip\7z.dll" "$SDI_TOOLS_DIR\7z.dll" -Force
                            Write-Host "  [+] 7-Zip 安装成功"
                        }
                    }
                } catch {
                    Write-Host ("[!] 官方下载也失败了: " + $_)
                }
            }

            # 解压服务器下载的 ZIP
            if ((Test-Path $sevenzZipPath) -and (-not (Test-Path $sevenZip))) {
                try {
                    Expand-Archive -Path $sevenzZipPath -DestinationPath $SDI_TOOLS_DIR -Force
                    if (Test-Path $sevenZip) {
                        Write-Host "  [+] 7-Zip 便携版就绪"
                    }
                } catch {
                    Write-Host ("[!] 解压 7-Zip 失败: " + $_)
                }
            }
        }

        if (Test-Path $sevenZip) {
            & $sevenZip x $sdiLitePath "-o$TEMP_DIR" -y | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host ("[!] 7z 解压 SDI Lite 失败 (exit=" + $LASTEXITCODE + ")")
                throw ("7z extraction failed with exit code " + $LASTEXITCODE)
            }
        } else {
            Write-Host "[*] 尝试系统自带 tar 解压..."
            try {
                & tar -xf $sdiLitePath -C $TEMP_DIR 2>$null
            } catch {}
            if (-not (Test-Path $sdiExePath)) {
                Write-Host "[!] 无法解压 .7z 文件，缺少 7-Zip"
                throw "Cannot extract .7z: 7-Zip not available"
            }
        }

        $foundExe = Get-ChildItem -Path $SDI_DIR -Filter "SDI_x64*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($foundExe) {
            $sdiExePath = $foundExe.FullName
            Write-Host ("  [+] SDI Lite 解压完成 (" + $foundExe.Name + ")")
        } else {
            Write-Host "[!] 解压失败，SDI_x64*.exe 未找到"
            Get-ChildItem $SDI_DIR -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ("    " + $_) }
            throw "SDI extraction failed"
        }
    } catch {
        Write-Host ("[!] SDI Lite 准备失败: " + $_.Exception.Message)
        throw
    }
}

Write-Host ""
