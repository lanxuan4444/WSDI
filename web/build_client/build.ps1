$ErrorActionPreference = "Stop"

$buildDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $buildDir "out"

if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$csproj = @'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <PublishSingleFile>true</PublishSingleFile>
    <SelfContained>false</SelfContained>
    <PublishTrimmed>true</PublishTrimmed>
    <TrimMode>partial</TrimMode>
    <DebugType>none</DebugType>
    <DebugSymbols>false</DebugSymbols>
    <AssemblyName>WSDI_Client</AssemblyName>
  </PropertyGroup>
</Project>
'@

$csprojPath = Join-Path $outDir "Launcher.csproj"
$csPath = Join-Path $outDir "Program.cs"
$launcherPath = Join-Path $buildDir "Launcher.cs"

[System.IO.File]::WriteAllText($csprojPath, $csproj, [System.Text.UTF8Encoding]::new($false))
Copy-Item -Path $launcherPath -Destination $csPath

Write-Host "[*] Building lightweight WSDI_Client.exe (framework-dependent)..." -ForegroundColor Yellow

Push-Location $outDir
try {
    dotnet publish -c Release -r win-x64 --self-contained false -o publish
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }
    
    $exe = Join-Path $outDir "publish\WSDI_Client.exe"
    $dest = Join-Path (Split-Path -Parent $buildDir) "WSDI_Client.exe"
    
    if (Test-Path $exe) {
        Copy-Item -Path $exe -Destination $dest -Force
        $size = (Get-Item $dest).Length
        Write-Host ("[+] Done! {0} ({1:N0} bytes)" -f $dest, $size) -ForegroundColor Green
    } else {
        Write-Host "[!] Output file not found" -ForegroundColor Red
    }
} finally {
    Pop-Location
}

Remove-Item -Recurse -Force $outDir -ErrorAction SilentlyContinue
