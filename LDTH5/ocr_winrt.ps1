param(
    [Parameter(Mandatory=$true)][string]$Path,
    # [2026-10-12 ROTATE] 旋转角度（90 的倍数）：竖拍照片旋转后再 OCR，识别率大幅提升
    [int]$Rotate = 0,
    # [2026-10-13 JSON] 加 -Json 时输出带每行坐标框的 JSON（微信式看图识字：文字按原位叠加划选）
    [switch]$Json
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$null = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapTransform,Windows.Graphics.Imaging,ContentType=WindowsRuntime]

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    if ($Json) { Write-Output '{"error":"OCR_ENGINE_UNAVAILABLE"}' } else { Write-Output "OCR_ENGINE_UNAVAILABLE" }
    exit 2
}

try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    if ($Rotate -gt 0) {
        $transform = [Windows.Graphics.Imaging.BitmapTransform]::new()
        $transform.Rotation = [int]$Rotate   # WinRT BitmapRotation: 1=90 2=180 3=270
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync(
            [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
            [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
            $transform,
            [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
            [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    } else {
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    }
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    if (-not $Json) {
        Write-Output $result.Text
        exit 0
    }
    # [2026-10-13 JSON] 每行文字 + 行坐标框（各词矩形并集，归一化到 0~1，前端按比例叠加）
    $bw = [double]$bitmap.PixelWidth
    $bh = [double]$bitmap.PixelHeight
    $lines = @()
    foreach ($line in $result.Lines) {
        $x1 = [double]::MaxValue; $y1 = [double]::MaxValue
        $x2 = [double]::MinValue; $y2 = [double]::MinValue
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            if ($r.X -lt $x1) { $x1 = $r.X }
            if ($r.Y -lt $y1) { $y1 = $r.Y }
            if (($r.X + $r.Width)  -gt $x2) { $x2 = $r.X + $r.Width }
            if (($r.Y + $r.Height) -gt $y2) { $y2 = $r.Y + $r.Height }
        }
        if ($x2 -le $x1 -or $y2 -le $y1) { continue }
        $lines += [ordered]@{
            t = $line.Text
            x = [math]::Round($x1 / $bw, 5)
            y = [math]::Round($y1 / $bh, 5)
            w = [math]::Round(($x2 - $x1) / $bw, 5)
            h = [math]::Round(($y2 - $y1) / $bh, 5)
        }
    }
    $out = [ordered]@{
        ok = $true
        width  = $bw
        height = $bh
        lines  = $lines
    }
    Write-Output (ConvertTo-Json -InputObject $out -Depth 4 -Compress)
} catch {
    if ($Json) {
        Write-Output ('{"error":"' + ($_.Exception.Message -replace '"', "'") + '"}')
        exit 1
    }
    Write-Output ("OCR_ERROR: " + $_.Exception.Message)
    exit 1
}
