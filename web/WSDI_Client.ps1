# ============================================
#  WSDI Driver Installer - WPF GUI Client v3.0
# ============================================
#  用法: 右键 "使用 PowerShell 运行" 或
#        powershell -NoProfile -ExecutionPolicy Bypass -File WSDI_Client.ps1
# ============================================

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms

$Script:ServerURL = "https://yanhong.online"
$Script:TempDir = "$env:TEMP\WSDI_GUI"
$Script:SDIDir = "$Script:TempDir\SDI"
$Script:ToolsDir = "$Script:TempDir\tools"
$Script:SessionId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$Script:AllDevices = @()
$Script:AllDrivers = @()
$Script:SelectedDrivers = @()
$Script:Progress = $null

New-Item -ItemType Directory -Path $Script:TempDir -Force | Out-Null
New-Item -ItemType Directory -Path $Script:SDIDir -Force | Out-Null
New-Item -ItemType Directory -Path $Script:ToolsDir -Force | Out-Null

# ========================================
#  XAML 界面定义
# ========================================
[xml]$XAML = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="WSDI Driver Installer v3.0" Height="700" Width="950"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResizeWithGrip"
        MinHeight="600" MinWidth="800"
        Background="#F0F4F8">
    <Window.Resources>
        <!-- 渐变背景画刷 -->
        <LinearGradientBrush x:Key="HeaderGradient" StartPoint="0,0" EndPoint="1,1">
            <GradientStop Color="#1A73E8" Offset="0"/>
            <GradientStop Color="#4A90D9" Offset="1"/>
        </LinearGradientBrush>
        <LinearGradientBrush x:Key="CardGradient" StartPoint="0,0" EndPoint="1,1">
            <GradientStop Color="#FFFFFF" Offset="0"/>
            <GradientStop Color="#F8FAFC" Offset="1"/>
        </LinearGradientBrush>
        <LinearGradientBrush x:Key="SuccessGradient" StartPoint="0,0" EndPoint="1,0">
            <GradientStop Color="#34A853" Offset="0"/>
            <GradientStop Color="#0F9D58" Offset="1"/>
        </LinearGradientBrush>
        <LinearGradientBrush x:Key="DangerGradient" StartPoint="0,0" EndPoint="1,0">
            <GradientStop Color="#EA4335" Offset="0"/>
            <GradientStop Color="#D93025" Offset="1"/>
        </LinearGradientBrush>

        <!-- 按钮样式 -->
        <Style x:Key="PrimaryButton" TargetType="Button">
            <Setter Property="Background" Value="#1A73E8"/>
            <Setter Property="Foreground" Value="White"/>
            <Setter Property="FontSize" Value="14"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Height" Value="42"/>
            <Setter Property="Padding" Value="24,0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}" CornerRadius="8"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#1557B0"/>
                </Trigger>
                <Trigger Property="IsEnabled" Value="False">
                    <Setter Property="Background" Value="#B0BEC5"/>
                    <Setter Property="Cursor" Value="Arrow"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <Style x:Key="SecondaryButton" TargetType="Button">
            <Setter Property="Background" Value="#E8F0FE"/>
            <Setter Property="Foreground" Value="#1A73E8"/>
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="Height" Value="36"/>
            <Setter Property="Padding" Value="16,0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="BorderBrush" Value="#1A73E8"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}" CornerRadius="6"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="#D2E3FC"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <!-- ListView 样式 -->
        <Style x:Key="DriverItemStyle" TargetType="ListViewItem">
            <Setter Property="Padding" Value="4"/>
            <Setter Property="Margin" Value="0,0,0,2"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="ListViewItem">
                        <Border Background="{TemplateBinding Background}"
                                CornerRadius="6" Padding="{TemplateBinding Padding}">
                            <GridViewRowPresenter/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Grid Margin="0">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 顶部标题栏 -->
        <Border Grid.Row="0" Background="{StaticResource HeaderGradient}" Padding="24,16">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" FontSize="22" FontWeight="Bold" Foreground="White"
                           VerticalAlignment="Center">
                    <Run Text="WSDI Driver Installer"/>
                    <Run Text=" v3.0" FontSize="14" Foreground="#CCFFFFFF"/>
                </TextBlock>
                <StackPanel Grid.Column="2" Orientation="Horizontal" VerticalAlignment="Center">
                    <TextBlock x:Name="txtServerStatus" Text="● Connected" Foreground="#81C995"
                               FontSize="12" VerticalAlignment="Center" Margin="0,0,16,0"/>
                    <TextBlock x:Name="txtSession" Foreground="#FFFFFFAA" FontSize="11"
                               VerticalAlignment="Center"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- 状态栏 -->
        <Border Grid.Row="1" Background="#FFFFFF" BorderBrush="#E0E0E0" BorderThickness="0,0,0,1"
                Padding="20,8">
            <StackPanel Orientation="Horizontal">
                <TextBlock x:Name="txtStatusIcon" Text="&#x2139;" FontSize="14"
                           Foreground="#1A73E8" VerticalAlignment="Center" Margin="0,0,8,0"/>
                <TextBlock x:Name="txtStatus" Text="Ready. Click 'Scan Hardware' to start."
                           FontSize="13" Foreground="#555" VerticalAlignment="Center"
                           TextWrapping="Wrap"/>
            </StackPanel>
        </Border>

        <!-- 操作按钮区 -->
        <Border Grid.Row="2" Background="#FFFFFF" Padding="20,12">
            <StackPanel Orientation="Horizontal">
                <Button x:Name="btnScan" Content="🔍  Scan Hardware" Style="{StaticResource PrimaryButton}"
                        Margin="0,0,12,0"/>
                <Button x:Name="btnSelectAll" Content="☑  Select All" Style="{StaticResource SecondaryButton}"
                        Margin="0,0,12,0"/>
                <Button x:Name="btnDeselectAll" Content="☐  Deselect All" Style="{StaticResource SecondaryButton}"
                        Margin="0,0,12,0"/>
                <Button x:Name="btnDownload" Content="⬇  Download &amp; Install" Style="{StaticResource PrimaryButton}"
                        Background="{StaticResource SuccessGradient}" IsEnabled="False"/>
            </StackPanel>
        </Border>

        <!-- 驱动列表 -->
        <Border Grid.Row="3" Background="{StaticResource CardGradient}" Margin="16,8,16,8"
                CornerRadius="10" Padding="4">
            <ListView x:Name="lvDrivers" BorderThickness="0" Background="Transparent"
                      ItemContainerStyle="{StaticResource DriverItemStyle}"
                      SelectionMode="Extended" HorizontalContentAlignment="Stretch">
                <ListView.View>
                    <GridView>
                        <GridViewColumn Header="" Width="40">
                            <GridViewColumn.CellTemplate>
                                <DataTemplate>
                                    <CheckBox IsChecked="{Binding IsSelected}" HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                                </DataTemplate>
                            </GridViewColumn.CellTemplate>
                        </GridViewColumn>
                        <GridViewColumn Header="Device" Width="280" DisplayMemberBinding="{Binding DeviceDesc}"/>
                        <GridViewColumn Header="HWID" Width="260" DisplayMemberBinding="{Binding Hwid}"/>
                        <GridViewColumn Header="Driver Package" Width="180" DisplayMemberBinding="{Binding PackageName}"/>
                        <GridViewColumn Header="Size" Width="80" DisplayMemberBinding="{Binding SizeDisplay}"/>
                        <GridViewColumn Header="Status" Width="80" DisplayMemberBinding="{Binding Status}"/>
                    </GridView>
                </ListView.View>
            </ListView>
        </Border>

        <!-- 摘要信息 -->
        <Border Grid.Row="4" Background="#FFFFFF" Padding="20,10" Margin="16,0,16,4" CornerRadius="8">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Orientation="Horizontal" Grid.Column="0">
                    <TextBlock x:Name="txtDevicesCount" Text="Devices: 0" FontSize="13" Foreground="#555"
                               Margin="0,0,20,0"/>
                    <TextBlock x:Name="txtDriversCount" Text="Drivers: 0" FontSize="13" Foreground="#555"
                               Margin="0,0,20,0"/>
                    <TextBlock x:Name="txtSelectedCount" Text="Selected: 0" FontSize="13" Foreground="#1A73E8"
                               FontWeight="SemiBold" Margin="0,0,20,0"/>
                    <TextBlock x:Name="txtTotalSize" Text="Total: 0 MB" FontSize="13" Foreground="#34A853"
                               FontWeight="SemiBold"/>
                </StackPanel>
                <TextBlock x:Name="txtElapsed" Grid.Column="2" Text="" FontSize="12"
                           Foreground="#888" VerticalAlignment="Center"/>
            </Grid>
        </Border>

        <!-- 进度条 -->
        <Border Grid.Row="5" Background="#FFFFFF" Padding="20,6,20,12" Margin="16,0,16,8" CornerRadius="8">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <ProgressBar x:Name="pbProgress" Height="8" Minimum="0" Maximum="100" Value="0"
                             Foreground="#1A73E8" Background="#E8F0FE" BorderThickness="0"
                             CornerRadius="4"/>
                <TextBlock x:Name="txtProgressPercent" Grid.Column="1" Text="" FontSize="12"
                           Foreground="#1A73E8" FontWeight="SemiBold" Margin="12,0,0,0"
                           VerticalAlignment="Center"/>
            </Grid>
        </Border>
    </Grid>
</Window>
"@

# ========================================
#  创建 WPF 窗口
# ========================================
$Reader = New-Object System.Xml.XmlNodeReader $XAML
$Window = [Windows.Markup.XamlReader]::Load($Reader)

# 绑定控件变量
$btnScan = $Window.FindName("btnScan")
$btnSelectAll = $Window.FindName("btnSelectAll")
$btnDeselectAll = $Window.FindName("btnDeselectAll")
$btnDownload = $Window.FindName("btnDownload")
$lvDrivers = $Window.FindName("lvDrivers")
$txtStatus = $Window.FindName("txtStatus")
$txtStatusIcon = $Window.FindName("txtStatusIcon")
$txtServerStatus = $Window.FindName("txtServerStatus")
$txtSession = $Window.FindName("txtSession")
$txtDevicesCount = $Window.FindName("txtDevicesCount")
$txtDriversCount = $Window.FindName("txtDriversCount")
$txtSelectedCount = $Window.FindName("txtSelectedCount")
$txtTotalSize = $Window.FindName("txtTotalSize")
$txtElapsed = $Window.FindName("txtElapsed")
$pbProgress = $Window.FindName("pbProgress")
$txtProgressPercent = $Window.FindName("txtProgressPercent")

$txtSession.Text = "Session: $($Script:SessionId)"

# ========================================
#  辅助函数
# ========================================
function Update-Status([string]$Message, [string]$Type = "info") {
    $Window.Dispatcher.Invoke([Action]{
        $txtStatus.Text = $Message
        switch ($Type) {
            "info"    { $txtStatusIcon.Text = "ℹ"; $txtStatusIcon.Foreground = "#1A73E8" }
            "success" { $txtStatusIcon.Text = "✓"; $txtStatusIcon.Foreground = "#34A853" }
            "error"   { $txtStatusIcon.Text = "✗"; $txtStatusIcon.Foreground = "#EA4335" }
            "warn"    { $txtStatusIcon.Text = "⚠"; $txtStatusIcon.Foreground = "#FBBC04" }
            "working" { $txtStatusIcon.Text = "⏳"; $txtStatusIcon.Foreground = "#1A73E8" }
        }
    })
}

function Update-Progress([double]$Value, [string]$Text = "") {
    $Window.Dispatcher.Invoke([Action]{
        $pbProgress.Value = [Math]::Min(100, [Math]::Max(0, $Value))
        $txtProgressPercent.Text = if ($Text) { $Text } else { "{0:F0}%" -f $Value }
    })
}

function Update-Summary {
    $Window.Dispatcher.Invoke([Action]{
        $selected = @($Script:AllDrivers | Where-Object { $_.IsSelected })
        $totalMb = [Math]::Round(($selected | Measure-Object -Property SizeMB -Sum).Sum, 1)
        $txtDevicesCount.Text = "Devices: $($Script:AllDevices.Count)"
        $txtDriversCount.Text = "Drivers: $($Script:AllDrivers.Count)"
        $txtSelectedCount.Text = "Selected: $($selected.Count)"
        $txtTotalSize.Text = "Total: $totalMb MB"
        $btnDownload.IsEnabled = ($selected.Count -gt 0)
    })
}

function Add-Log([string]$Message) {
    # 可以扩展到日志面板
    Write-Host $Message
}

# ========================================
#  Step 1: 扫描需要驱动的设备（按 PnP 状态过滤）
# ========================================
function Invoke-HardwareScan {
    Update-Status "Scanning for devices that need drivers..." "working"
    Update-Progress 5 "Scanning..."

    $devices = @()
    try {
        # IMPORTANT: Use Win32_PnPEntity.ConfigManagerErrorCode (WMI).
        # Get-PnpDevice.Problem returns a string enum where CM_PROB_PHANTOM
        # (ghost devices) is also counted as "problem" — yielding 300+ false
        # positives. WMI's ConfigManagerErrorCode is a pure uint32 where
        # 0 = OK and != 0 means real yellow-bang (e.g. 28 = no driver).
        $pnpDevices = Get-WmiObject Win32_PnPEntity -ErrorAction SilentlyContinue |
            Where-Object { $_.HardwareID -and $_.HardwareID.Count -gt 0 }
        foreach ($dev in $pnpDevices) {
            $hwid = $dev.HardwareID[0]
            if (!$hwid) { continue }
            $errCode = $dev.ConfigManagerErrorCode
            if ($errCode -eq 0) { continue }
            $devObj = @{
                hwid = $hwid.ToUpper().Trim()
                description = if ($dev.Name) { $dev.Name } else { $dev.Description }
                class = $dev.PNPClass
                is_problem = $true
                error_code = $errCode
            }
            $devices += $devObj
        }
    } catch {
        Update-Status "Failed to scan hardware: $($_.Exception.Message)" "error"
        return
    }

    $Script:AllDevices = $devices
    if ($devices.Count -eq 0) {
        Update-Status "No problem devices found. Your system looks healthy!" "success"
        return
    }

    Update-Status "Found $($devices.Count) problem device(s). Analyzing..." "info"
    Update-Progress 15 "Found $($devices.Count) devices"

    # 保存硬件信息
    $json = @{ devices = $devices } | ConvertTo-Json -Depth 3
    $jsonPath = "$Script:TempDir\hardware.json"
    $json | Out-File -FilePath $jsonPath -Encoding UTF8

    # 调用服务端分析
    Invoke-ServerAnalyze $json
}

# ========================================
#  Step 2: 服务端分析
# ========================================
function Invoke-ServerAnalyze([string]$Body) {
    Update-Status "Connecting to server for driver analysis..." "working"
    Update-Progress 20 "Analyzing..."
    $startTime = Get-Date

    try {
        $result = Invoke-RestMethod -Uri "$Script:ServerURL/api/analyze" `
            -Method Post -Body $Body `
            -ContentType "application/json; charset=utf-8" `
            -TimeoutSec 120

        if (-not $result.success) {
            Update-Status "Server analysis failed: $($result.error)" "error"
            return
        }

        $elapsed = [Math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
        Update-Status "Analysis complete! $($result.total_devices) devices, $($result.matched_drivers) driver packs found. ($elapsed s)" "success"
        Update-Progress 30 "Analysis done"

        # 构建驱动列表
        $Script:AllDrivers = @()
        if ($result.drivers) {
            foreach ($drv in $result.drivers) {
                $devNames = @()
                $hwids = @()
                if ($drv.matched_devices) {
                    foreach ($dev in $drv.matched_devices) {
                        $desc = if ($dev.description -and $dev.description -ne $dev.hwid) { $dev.description } else { $dev.hwid }
                        $devNames += $desc
                        $hwids += $dev.hwid
                    }
                }
                $Script:AllDrivers += [PSCustomObject]@{
                    IsSelected  = $true
                    DeviceDesc  = ($devNames -join ", ")
                    Hwid        = ($hwids -join ", ")
                    PackageName = $drv.file
                    SizeMB      = [double]$drv.size_mb
                    SizeDisplay = "{0:F1} MB" -f [double]$drv.size_mb
                    Status      = "Ready"
                    DrvFile     = $drv.file
                    DownloadUrl = if ($drv.url) { $drv.url } else { "" }
                    Recommendations = $drv.recommendations
                }
            }
        }

        # 绑定到 UI
        $Window.Dispatcher.Invoke([Action]{
            $lvDrivers.ItemsSource = $Script:AllDrivers
            $lvDrivers.Items.Refresh()
        })
        Update-Summary
        Update-Progress 0 ""

    } catch {
        $errMsg = $_.Exception.Message
        if ($_.ErrorDetails.Message) { $errMsg = $_.ErrorDetails.Message }
        Update-Status "Connection failed: $errMsg" "error"
        Update-Progress 0 ""
    }
}

# ========================================
#  Step 3: 下载并安装
# ========================================
function Invoke-DownloadAndInstall {
    $selected = @($Script:AllDrivers | Where-Object { $_.IsSelected })
    if ($selected.Count -eq 0) {
        Update-Status "No drivers selected!" "warn"
        return
    }

    # 禁用按钮
    $Window.Dispatcher.Invoke([Action]{
        $btnScan.IsEnabled = $false
        $btnDownload.IsEnabled = $false
        $btnSelectAll.IsEnabled = $false
        $btnDeselectAll.IsEnabled = $false
    })

    $totalMB = [Math]::Round(($selected | Measure-Object -Property SizeMB -Sum).Sum, 1)
    Update-Status "Starting download: $($selected.Count) driver pack(s) ($totalMB MB)..." "working"
    Update-Progress 0 "Preparing..."

    $startTime = Get-Date
    $downloadedMB = 0.0
    $successCount = 0
    $failCount = 0
    $totalDrivers = $selected.Count

    $driversDir = "$Script:SDIDir\Drivers"
    New-Item -ItemType Directory -Path $driversDir -Force | Out-Null

    for ($i = 0; $i -lt $selected.Count; $i++) {
        $drv = $selected[$i]
        $idx = $i + 1
        $pkgName = $drv.DrvFile

        # 更新状态
        Update-Status "[$idx/$totalDrivers] Downloading: $pkgName" "working"
        $drv.Status = "Downloading..."
        $Window.Dispatcher.Invoke([Action]{ $lvDrivers.Items.Refresh() })

        $localPath = Join-Path $driversDir $pkgName

        # 如果文件已存在且大小正确，跳过
        if (Test-Path $localPath) {
            $existingSize = (Get-Item $localPath).Length
            if ([Math]::Round($existingSize / 1MB, 1) -eq $drv.SizeMB) {
                $drv.Status = "Cached"
                $successCount++
                $downloadedMB += $drv.SizeMB
                $progress = ($i + 1) / $totalDrivers * 100
                Update-Progress $progress "$successCount/$totalDrivers done"
                $Window.Dispatcher.Invoke([Action]{ $lvDrivers.Items.Refresh() })
                continue
            }
        }

        # 下载
        try {
            # 优先 COS 直链，回退到服务器 API
            if ($drv.DownloadUrl -and $drv.DownloadUrl -ne "") {
                $downloadUrl = $drv.DownloadUrl
            } else {
                $downloadUrl = "$Script:ServerURL/api/download_pkg/$pkgName"
            }
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $downloadUrl -OutFile $localPath `
                -UseBasicParsing -TimeoutSec 600

            $actualSize = (Get-Item $localPath).Length
            if ($actualSize -lt 1MB) {
                throw "Download too small ($([Math]::Round($actualSize/1KB,1)) KB)"
            }

            $drv.Status = "Downloaded"
            $successCount++
            $downloadedMB += [Math]::Round($actualSize / 1MB, 1)
            Add-Log "  [+] $pkgName ($([Math]::Round($actualSize/1MB,1)) MB)"

        } catch {
            $drv.Status = "Failed"
            $failCount++
            Add-Log "  [!] $pkgName failed: $($_.Exception.Message)"
        }

        # 更新进度
        $progress = ($i + 1) / $totalDrivers * 100
        $elapsed = [Math]::Round(((Get-Date) - $startTime).TotalSeconds, 0)
        Update-Progress $progress "$successCount/$totalDrivers done"
        $txtElapsed.Text = "Time: ${elapsed}s"

        $Window.Dispatcher.Invoke([Action]{ $lvDrivers.Items.Refresh() })
    }

    # 完成
    $totalElapsed = [Math]::Round(((Get-Date) - $startTime).TotalSeconds, 0)
    $txtElapsed.Text = "Time: ${totalElapsed}s"
    Update-Progress 100 "Complete!"

    if ($failCount -gt 0) {
        Update-Status "Download complete! $successCount succeeded, $failCount failed. ($totalElapsed s)" "warn"
    } else {
        Update-Status "All $successCount driver pack(s) downloaded successfully! ($totalElapsed s)" "success"
    }

    # 启动 SDI
    Invoke-LaunchSDI

    # 恢复按钮
    $Window.Dispatcher.Invoke([Action]{
        $btnScan.IsEnabled = $true
        $btnSelectAll.IsEnabled = $true
        $btnDeselectAll.IsEnabled = $true
    })
}

# ========================================
#  Step 4: 下载 SDI Lite + 7-Zip
# ========================================
function Invoke-DownloadTools {
    Update-Status "Checking tools..." "working"
    Update-Progress 5 "Checking tools..."

    # SDI Lite
    $sdiLitePath = Join-Path $Script:TempDir "SDI_R2601.7z"
    $sdiExePath = Join-Path $Script:SDIDir "SDI_x64_R2601.exe"

    # 查找已有的 SDI exe
    $foundExe = Get-ChildItem -Path $Script:SDIDir -Filter "SDI_x64*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($foundExe) {
        $sdiExePath = $foundExe.FullName
        Add-Log "[*] SDI Lite already ready"
    } else {
        Update-Status "Downloading SDI Lite..." "working"
        Update-Progress 10 "Downloading SDI..."
        try {
            Invoke-WebRequest -Uri "$Script:ServerURL/api/sdi_lite" -OutFile $sdiLitePath `
                -UseBasicParsing -TimeoutSec 120

            if ((Get-Item $sdiLitePath).Length -lt 1MB) {
                throw "SDI Lite download invalid"
            }

            # 确保有 7-Zip
            $sevenZip = Join-Path $Script:ToolsDir "7z.exe"
            if (-not (Test-Path $sevenZip)) {
                Update-Status "Downloading 7-Zip..." "working"
                $sevenZipZip = "$Script:ToolsDir\7z_portable.zip"
                try {
                    Invoke-WebRequest -Uri "$Script:ServerURL/api/7z_portable" -OutFile $sevenZipZip `
                        -UseBasicParsing -TimeoutSec 60
                    Expand-Archive -Path $sevenZipZip -DestinationPath $Script:ToolsDir -Force
                } catch {
                    # 尝试从官网下载
                    try {
                        $msiPath = "$Script:ToolsDir\7z_installer.msi"
                        Invoke-WebRequest -Uri "https://www.7-zip.org/a/7z2409-x64.msi" `
                            -OutFile $msiPath -UseBasicParsing -TimeoutSec 120
                        Start-Process msiexec.exe -ArgumentList "/i `"$msiPath`" /qn" -Wait
                        Copy-Item "${env:ProgramFiles}\7-Zip\7z.exe" $sevenZip -Force
                        Copy-Item "${env:ProgramFiles}\7-Zip\7z.dll" "$Script:ToolsDir\7z.dll" -Force
                    } catch {}
                }
            }

            # 解压 SDI
            if (Test-Path $sevenZip) {
                Update-Status "Extracting SDI Lite..." "working"
                & $sevenZip x $sdiLitePath "-o$($Script:SDIDir)" -y | Out-Null
                $foundExe = Get-ChildItem -Path $Script:SDIDir -Filter "SDI_x64*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($foundExe) { $sdiExePath = $foundExe.FullName }
            } else {
                try {
                    & tar -xf $sdiLitePath -C $Script:SDIDir 2>$null
                } catch {}
            }
        } catch {
            Update-Status "SDI Lite download failed: $($_.Exception.Message)" "warn"
        }
    }

    Update-Progress 0 ""
    Update-Status "Tools ready. Click 'Scan Hardware' to begin." "info"
}

# ========================================
#  Step 5: 启动 SDI
# ========================================
function Invoke-LaunchSDI {
    $foundExe = Get-ChildItem -Path $Script:SDIDir -Filter "SDI_x64*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $foundExe) {
        $foundExe = Get-ChildItem -Path $Script:SDIDir -Filter "SDI_x86*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $foundExe) {
        Update-Status "SDI executable not found! Please re-scan and try again." "error"
        return
    }

    $sdiPath = $foundExe.FullName
    Update-Status "Launching SDI (Snappy Driver Installer)..." "success"

    try {
        Start-Process -FilePath $sdiPath -WorkingDirectory $Script:SDIDir
        Update-Status "SDI launched! Select your device and click 'Install' in the SDI window." "success"
    } catch {
        Update-Status "Failed to launch SDI: $($_.Exception.Message)" "error"
    }
}

# ========================================
#  事件绑定
# ========================================
$btnScan.Add_Click({
    Update-Progress 0 ""
    $Script:AllDevices = @()
    $Script:AllDrivers = @()
    $Window.Dispatcher.Invoke([Action]{
        $lvDrivers.ItemsSource = $null
    })
    Update-Summary
    Invoke-DownloadTools
    Invoke-HardwareScan
})

$btnSelectAll.Add_Click({
    foreach ($d in $Script:AllDrivers) { $d.IsSelected = $true }
    $Window.Dispatcher.Invoke([Action]{ $lvDrivers.Items.Refresh() })
    Update-Summary
})

$btnDeselectAll.Add_Click({
    foreach ($d in $Script:AllDrivers) { $d.IsSelected = $false }
    $Window.Dispatcher.Invoke([Action]{ $lvDrivers.Items.Refresh() })
    Update-Summary
})

$btnDownload.Add_Click({
    Invoke-DownloadAndInstall
})

# 列表项选中变化时更新摘要
$lvDrivers.Add_SelectionChanged({
    Update-Summary
})

# 窗口加载时检查服务器连接
$Window.Add_Loaded({
    try {
        $null = Invoke-RestMethod -Uri "$Script:ServerURL/api/analyze" -Method Get -TimeoutSec 10
        $txtServerStatus.Text = "● Connected"
        $txtServerStatus.Foreground = "#81C995"
    } catch {
        $txtServerStatus.Text = "● Offline"
        $txtServerStatus.Foreground = "#F28B82"
    }
    Update-Progress 0 ""
})

# 窗口关闭
$Window.Add_Closing({
    # 清理临时文件
    try {
        Remove-Item "$Script:TempDir\hardware.json" -Force -ErrorAction SilentlyContinue
    } catch {}
})

# ========================================
#  启动窗口
# ========================================
$Window.ShowDialog() | Out-Null
