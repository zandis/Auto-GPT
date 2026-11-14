# NEW-WIN-1 (D-600): the logic of deploy/windows/box-install.ps1 with every Windows command behind a seam.
# Run: pwsh -NoProfile -File tests/windows/run-pester.ps1   (PowerShell 7 on Linux; Pester 5)
# What this proves: the order of the steps, every refusal, what a second run and an interrupted run do, what is
# logged. What it cannot prove: any real Windows behaviour (docs/handover/P-0-windows-rehearsal.md).

BeforeAll {
  $script:Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
  $script:Ps1 = Join-Path $script:Root "deploy/windows/box-install.ps1"
  . $script:Ps1 -LoadOnly

  function New-Scenario {
    # one fake machine: a media folder, a state folder, a data drive, and the answers of every seam
    $base = Join-Path $TestDrive ([guid]::NewGuid().ToString("N"))
    $media = Join-Path $base "media"
    foreach ($d in @("windows/wsl", "linux/debs")) { New-Item -ItemType Directory -Force -Path (Join-Path $media $d) | Out-Null }
    $files = @(
      "windows/box-install.ps1", "windows/box-install.messages.json", "windows/wsl-setup.sh", "windows/register_keepalive.ps1",
      "windows/wsl/wsl.2.4.13.0.x64.msi", "windows/wsl/ubuntu-24.04-wsl-amd64.tar.gz",
      "linux/debs/docker-ce_27.deb", "linux/trialbox-host.tar", "linux/trialbox-1.0.0.tar", "linux/vendor_ed25519.pub"
    )
    $sums = @()
    foreach ($f in $files) {
      $p = Join-Path $media $f
      $src = Join-Path $script:Root ("deploy/windows/" + (Split-Path -Leaf $f))
      if ($f -like "windows/box-install.*" -or $f -like "windows/wsl-setup.sh" -or $f -like "windows/register_keepalive.ps1") { Copy-Item -LiteralPath $src -Destination $p }
      else { Set-Content -LiteralPath $p -Value ("content of " + $f) -NoNewline }
      $sums += ("{0}  {1}" -f (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower(), $f)
    }
    Set-Content -LiteralPath (Join-Path $media "SHA256SUMS") -Value $sums
    $s = @{
      Base = $base; Media = $media; StateDir = (Join-Path $base "state"); Data = (Join-Path $base "data")
      Edition = "ProfessionalWorkstation"; Build = 26100; VirtFirmware = $true; Hypervisor = $false
      Account = "BOX\owner"; IsAdmin = $true; FreeGB = 3000; MemoryGB = 192; Processors = 32
      Features = @{ "VirtualMachinePlatform" = $false; "Microsoft-Windows-Subsystem-Linux" = $false }
      FeatureRestart = $true; WslInstalled = $false; Distros = @(); WinGpu = $true
      Pid1 = "systemd"; SetupFail = @{}; InstallExit = 0; StateLine = "installed=1"
      Calls = New-Object System.Collections.ArrayList; Console = New-Object System.Collections.ArrayList
      BootInfo = $null; BootRegistered = 0; NetMode = "mirrored"; Firewall = @(); FwDefault = "Block"; FwRule = $null; FwBlockSet = 0
      HostFw = $null; HostFwWrites = New-Object System.Collections.ArrayList; HyperVCalls = 0
      ProxyTask = $null; ProxyRegistered = 0; ProxyRuns = 0; ProxyStatus = "added"; ProxyAddress = "172.28.14.5"
      EgressVerdict = "verdict=held"; LanLine = "firewall open to '192.0.2.0/24'; this PC's network address '192.0.2.10/24'"
      Tpm = @{ Present = $true; Ready = $true }; BLCalls = New-Object System.Collections.ArrayList
      Asked = New-Object System.Collections.ArrayList; Answers = New-Object System.Collections.ArrayList
      Printed = New-Object System.Collections.ArrayList; Machine = @{}
      BL = @{}; Keys = @{}; KeyIds = @{}; Printer = "Office-Printer"; Transcription = $false; AutoUnlockFails = $false
      OwnDrives = @("C", "D"); Bus = @{ "E" = "USB"; "F" = "SATA" }; Marks = New-Object System.Collections.ArrayList
      Upd = @{}; UpdWrites = New-Object System.Collections.ArrayList; UpdFailAt = 0; ShutSticks = $true
      Shut = @{ Sids = @("S-1-5-32-544", "S-1-5-32-545", "S-1-5-32-551"); AtSignIn = $true }; ShutWrites = 0; ShutFails = $false
      Restarted = 0; ResumeTask = $false; FoundMedia = ""; ImportDies = $false; Said = New-Object System.Collections.ArrayList
    }
    New-Item -ItemType Directory -Force -Path $s.Data | Out-Null
    # as most new PCs come: both drives encrypted already, the system drive by the TPM
    $s.BL["C:"] = @{ Status = "FullyEncrypted"; Protection = "On"; AutoUnlock = $false; Protectors = @("Tpm", "RecoveryPassword") }
    $s.BL[$s.Data] = @{ Status = "FullyEncrypted"; Protection = "On"; AutoUnlock = $true; Protectors = @("RecoveryPassword") }
    $s.Keys["C:"] = "111111-222222-333333-444444-555555-666666-777777-123456"
    $s.Keys[$s.Data] = "888888-999999-000000-111111-222222-333333-444444-654321"
    $s.KeyIds["C:"] = "{id-C-first}"; $s.KeyIds[$s.Data] = "{id-D-first}"
    $script:S = $s
    return $s
  }

  function Invoke-Run([switch]$Resume, [switch]$Ask) {
    $s = $script:S
    $p = @{ MediaRoot = $s.Media; DataDrive = $s.Data; StateDir = $s.StateDir; Lang = "en"; Yes = (-not $Ask) }
    if ($Resume) { $p.Remove("MediaRoot"); $p["Resume"] = $true }
    return (Invoke-TbInstall @p)
  }
  function Get-Log { return (Get-Content -LiteralPath (Join-Path $script:S.StateDir "box-install.log") -Raw) }
  function Get-SetupSteps { return @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh (\S+)" } | ForEach-Object { $Matches[1] }) }
}

Describe "box-install.ps1" {
  BeforeEach {
    New-Scenario | Out-Null
    Mock Get-TbWindowsFacts {
      $s = $script:S
      return @{ EditionId = $s.Edition; Build = $s.Build; VirtualizationFirmware = $s.VirtFirmware
        HypervisorPresent = $s.Hypervisor; Account = $s.Account; IsAdmin = $s.IsAdmin; UiCulture = "en-US"
        SystemDrive = "C:"; UserProfile = (Join-Path $s.Base "profile") }
    }
    Mock Get-TbDriveFacts { return @{ FreeGB = $script:S.FreeGB; Fixed = $true; FileSystem = "NTFS"; SizeBytes = 4000787030016 } }
    Mock Get-TbHardware { return @{ MemoryGB = $script:S.MemoryGB; Processors = $script:S.Processors } }
    Mock Get-TbDataDriveCandidates { return @() }
    Mock Protect-TbDirectory { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
    Mock Get-TbFeatureEnabled { return [bool]$script:S.Features[$Name] }
    Mock Enable-TbFeature { $script:S.Features[$Name] = $true; return [bool]$script:S.FeatureRestart }
    Mock Register-TbResumeTask { $script:S.ResumeTask = $true; $script:S.ResumeMore = $More; $script:S.ResumeScript = $ScriptPath }
    Mock Unregister-TbResumeTask { $script:S.ResumeTask = $false }
    Mock Restart-TbComputer { $script:S.Restarted++ }
    # the Hyper-V firewall (NEW-WIN-4): WSL's default for inbound traffic and the one rule, as plain values
    Mock Get-TbWslInboundDefault { $script:S.HyperVCalls++; return [string]$script:S.FwDefault }
    Mock Set-TbWslInboundBlock { $script:S.HyperVCalls++; $script:S.FwDefault = "Block"; $script:S.FwBlockSet++ }
    Mock Get-TbConsoleFirewallRule { $script:S.HyperVCalls++; return $script:S.FwRule }
    # Windows 10 (NEW-WIN-10): a Windows Firewall rule, the forwarding task and one run of the forwarding script
    Mock Get-TbHostFirewallRule { return $script:S.HostFw }
    Mock Write-TbHostFirewallRule {
      [void]$script:S.HostFwWrites.Add("$RuleName|$Port|exists=$Exists")
      $script:S.HostFw = @{ Enabled = "True"; Direction = "Inbound"; Action = "Allow"; Protocol = "TCP"; LocalPort = [string]$Port
        RemoteAddress = "LocalSubnet"; Profile = "Domain, Private" }
    }
    Mock Get-TbProxyTaskInfo { return $script:S.ProxyTask }
    Mock Register-TbProxyTask {
      $script:S.ProxyRegistered++
      $script:S.ProxyTask = @{ State = "Ready"; Action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Script`" -Distro $Distro -Port $Port" }
      $script:S.ProxyScript = $Script; $script:S.ProxyEvery = $EveryMinutes; $script:S.ProxyAccount = $Account
    }
    Mock Invoke-TbConsoleProxy { $script:S.ProxyRuns++; return @{ Status = [string]$script:S.ProxyStatus; Address = [string]$script:S.ProxyAddress } }
    Mock Write-TbConsoleFirewallRule {
      $script:S.Firewall += ,"$RuleName|$Port|exists=$Exists"
      $script:S.FwRule = @{ Enabled = "True"; Direction = "Inbound"; Action = "Allow"; Protocol = "TCP"; LocalPorts = [string]$Port
        RemoteAddresses = "LocalSubnet"; VMCreatorId = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" }
    }
    Mock Register-TbBootTask {
      $script:S.BootTask = "$Account|$Distro|$TaskName"; $script:S.BootRegistered++
      $script:S.BootInfo = @{ State = "Running"; LastResult = "267009"; Action = "wsl.exe -d $Distro --exec /bin/sh -c 'exec sleep infinity' " }
    }
    Mock Get-TbBootTaskInfo { return $script:S.BootInfo }
    Mock Find-TbMedia { return [string]$script:S.FoundMedia }
    Mock Start-TbSleep { }
    Mock Read-TbLine {
      [void]$script:S.Asked.Add($Prompt)
      if ($script:S.Answers.Count -gt 0) { $a = $script:S.Answers[0]; $script:S.Answers.RemoveAt(0); return $a }
      return ""
    }
    # BitLocker (NEW-WIN-8): a fake TPM and a fake state per drive; the system drive is C:, the data drive the test's folder
    Mock Get-TbTpm { return $script:S.Tpm }
    Mock Get-TbBitLocker { return $script:S.BL[$Drive] }
    # Windows reports protection Off while the first encryption runs (review M2)
    Mock Enable-TbBitLockerSystem { [void]$script:S.BLCalls.Add("system $Drive"); $b = $script:S.BL[$Drive]; $b.Status = "EncryptionInProgress"; $b.Protection = "Off"; $b.Protectors = @($b.Protectors) + "Tpm" }
    Mock Enable-TbBitLockerData { [void]$script:S.BLCalls.Add("data $Drive"); $b = $script:S.BL[$Drive]; $b.Status = "EncryptionInProgress"; $b.Protection = "Off"; $b.Protectors = @($b.Protectors) + "RecoveryPassword" }
    Mock Enable-TbAutoUnlock { [void]$script:S.BLCalls.Add("auto $Drive"); if ($script:S.AutoUnlockFails) { throw "the system volume is not protected yet" }; $script:S.BL[$Drive].AutoUnlock = $true }
    Mock Add-TbRecoveryPassword { [void]$script:S.BLCalls.Add("recovery $Drive"); $script:S.BL[$Drive].Protectors = @($script:S.BL[$Drive].Protectors) + "RecoveryPassword"; return @{ Id = $script:S.KeyIds[$Drive]; Password = $script:S.Keys[$Drive] } }
    Mock Get-TbRecoveryPassword { return @{ Id = $script:S.KeyIds[$Drive]; Password = $script:S.Keys[$Drive] } }
    Mock Get-TbDefaultPrinter { return [string]$script:S.Printer }
    Mock Test-TbTranscription { return [bool]$script:S.Transcription }
    Mock Clear-TbScreen { [void]$script:S.BLCalls.Add("cleared") }
    Mock Set-TbMachineSetting { $script:S.Machine[$Name] = $Value }
    # Windows Update policy and the shutdown right (NEW-WIN-5): the registry values and the right, as plain values
    Mock Get-TbUpdatePolicy {
      $p = @{ Ours = [string]$script:S.Machine["update_window"] }
      foreach ($n in @("NoAutoUpdate", "AUOptions", "ScheduledInstallDay", "ScheduledInstallTime", "SetActiveHours", "ActiveHoursStart",
          "ActiveHoursEnd", "ExcludeWUDriversInQualityUpdate", "NoAutoRebootWithLoggedOnUsers", "AlwaysAutoRebootAtScheduledTime",
          "SetComplianceDeadline", "ConfigureDeadlineForQualityUpdates", "ConfigureDeadlineForFeatureUpdates", "Mdm")) { $p[$n] = $script:S.Upd[$n] }
      return $p
    }
    Mock Write-TbUpdateValue {
      if ($script:S.UpdFailAt -gt 0 -and $script:S.UpdWrites.Count -ge $script:S.UpdFailAt) { throw "Requested registry access is not allowed" }
      $script:S.Upd[$Name] = $Value; [void]$script:S.UpdWrites.Add("$Sub|$Name=$Value")
    }
    Mock Get-TbDriveBus { if (-not $script:S.Bus.ContainsKey($Letter)) { throw "no such drive" }; return [string]$script:S.Bus[$Letter] }
    Mock Write-TbOutsideMark { [void]$script:S.Marks.Add("$Letter|" + ($Lines -join " ")) }
    Mock Get-TbOwnDrives { if ($script:S.OwnDrives -eq "fail") { throw "Get-Disk is not available" }; return @($script:S.OwnDrives) }
    Mock Get-TbShutdownRight { return @{ Sids = @($script:S.Shut.Sids); AtSignIn = [bool]$script:S.Shut.AtSignIn } }
    Mock Write-TbShutdownRight {
      if ($script:S.ShutFails) { throw "secedit /configure ended with code 3" }
      $script:S.ShutWrites++
      if ($script:S.ShutSticks) { $script:S.Shut = @{ Sids = @($Sid); AtSignIn = $false } }
    }
    Mock Send-TbToPrinter { [void]$script:S.Printed.Add(($Lines -join "|")) }
    Mock Write-TbScreen { [void]$script:S.Said.Add($Text) }
    Mock Test-TbMsiSignature { return $true }
    Mock Invoke-TbNative {
      $s = $script:S
      $line = ($Exe + " " + ($Arguments -join " "))
      [void]$s.Calls.Add($line)
      $r = @{ ExitCode = 0; Output = @() }
      if ($Exe -eq "nvidia-smi.exe") {
        if ($s.WinGpu) { $r.Output = @("NVIDIA RTX PRO 6000 Blackwell, 581.15, 97887 MiB") } else { $r.ExitCode = -1 }
      } elseif ($Exe -eq "msiexec.exe") { $s.WslInstalled = $true }
      elseif ($line -match "wsl\.exe --version") { if (-not $s.WslInstalled) { $r.ExitCode = 1 } }
      elseif ($line -match "wsl\.exe --list") { $r.Output = @($s.Distros) }
      elseif ($line -match "wsl\.exe --import (\S+)") {
        $s.Distros = @($s.Distros) + $Matches[1]
        if ($s.ImportDies) { $s.ImportDies = $false; throw "the window was closed" }
      }
      elseif ($line -match "wsl-setup\.sh (\S+)") {
        $step = $Matches[1]
        if ($s.SetupFail.ContainsKey($step)) { $r.ExitCode = 1; $r.Output = @("wsl-setup: " + $s.SetupFail[$step]) }
        elseif ($step -eq "pid1") { $r.Output = @($s.Pid1) }
        elseif ($step -eq "wslconf") { $r.Output = @("changed") }
        elseif ($step -eq "state") { $r.Output = @($s.StateLine) }
        elseif ($step -eq "network-mode") { $r.Output = @($s.NetMode) }
        elseif ($step -eq "egress-proof") { $r.Output = @("egress_container=trialbox-gateway-1 target=192.0.2.1", $s.EgressVerdict) }
        elseif ($step -eq "lan-check") { $r.Output = @($s.LanLine) }
        elseif ($step -eq "gpu") { $r.Output = @("NVIDIA RTX PRO 6000 Blackwell, 581.15, 97887 MiB") }
        elseif ($step -eq "host-tree") { $r.Output = @("unpacked: /opt/trialbox", "vendor key sha256 0123abcd") }
      }
      return $r
    }
    Mock Invoke-TbNativeConsole {
      [void]$script:S.Console.Add(($Exe + " " + ($Arguments -join " ")))
      return [int]$script:S.InstallExit
    }
  }

  Context "refusals before anything is changed" {
    It "refuses Windows Home and changes nothing" {
      $script:S.Edition = "Core"
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
      ($script:S.Calls -join "`n") | Should -Not -Match "import|msiexec"
      Get-Log | Should -Match "STOP step 2/\d+ windows: .*Core"
    }
    It "refuses a build before Windows 10 22H2 (owner ruling D-503 lowered it from Windows 11 22H2)" {
      $script:S.Build = 19044
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 2/\d+ windows"
    }
    It "tells a Windows before 10 22H2 which build it needs, not which edition (NEW-WIN-4, review L10)" {
      $script:S.Build = 19041
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
      Get-Log | Should -Match "STOP step 2/\d+ windows: This Windows is build 19041. TrialBox needs build 19045"
    }
    It "refuses a machine without virtualisation" {
      $script:S.VirtFirmware = $false; $script:S.Hypervisor = $false
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
      Get-Log | Should -Match "STOP step 2/\d+ windows: .*virtualisation"
    }
    It "refuses when it is not run as administrator" {
      $script:S.IsAdmin = $false
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
    }
    It "refuses a machine without the Windows NVIDIA driver" {
      $script:S.WinGpu = $false
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
      Get-Log | Should -Match "STOP step 3/\d+ gpu-driver"
    }
    It "refuses a data drive with too little room, by the declared figure" {
      $script:S.FreeGB = 120
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*120"
    }
    It "refuses media whose file does not match SHA256SUMS" {
      Add-Content -LiteralPath (Join-Path $script:S.Media "linux/trialbox-1.0.0.tar") -Value "x"
      Invoke-Run | Should -Be 1
      Should -Invoke Enable-TbFeature -Times 0
      Get-Log | Should -Match "STOP step 1/\d+ media: .*trialbox-1.0.0.tar"
    }
    It "refuses media with a file missing" {
      Remove-Item -LiteralPath (Join-Path $script:S.Media "linux/trialbox-host.tar")
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 1/\d+ media"
    }
    It "refuses a WSL package that Microsoft did not sign" {
      Mock Test-TbMsiSignature { return $false }
      Invoke-Run | Should -Be 1
      ($script:S.Calls -join "`n") | Should -Not -Match "msiexec"
    }
  }

  Context "the restart that enabling WSL2 needs" {
    It "registers the resume task, keeps its place and restarts; nothing is imported yet" {
      Invoke-Run | Should -Be 3010
      $script:S.ResumeTask | Should -BeTrue
      $script:S.Restarted | Should -Be 1
      ($script:S.Calls -join "`n") | Should -Not -Match "--import"
      $state = Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json
      $state.restart_pending | Should -BeTrue
      $state.media_root | Should -Be $script:S.Media
      # the copy the task runs after the restart does not depend on the media's drive letter
      Test-Path -LiteralPath (Join-Path $script:S.StateDir "scripts/box-install.ps1") | Should -BeTrue
      Test-Path -LiteralPath (Join-Path $script:S.StateDir "scripts/box-install.messages.json") | Should -BeTrue
      Test-Path -LiteralPath (Join-Path $script:S.StateDir "scripts/register_keepalive.ps1") | Should -BeTrue
      $script:S.ResumeScript | Should -Be (Join-Path $script:S.StateDir "scripts/box-install.ps1")
    }
    It "hands this run's settings to the run after the restart, and no path or secret beyond them" {
      $MinFreeGB = 200; $script:S.FreeGB = 250
      Invoke-Run | Should -Be 3010
      $script:S.ResumeMore | Should -Be "-MinFreeGB 200 -MinWindowsBuild 19045 -ProxyEveryMinutes 5 -StartWaitSeconds 120 -DesktopSharePercent 25 -UpdateWindowStart 19 -UpdateWindowHours 6 -Distro TrialBox -Lang en -BitLockerUnlock tpm"
    }
    It "continues by itself after the restart and removes the resume task" {
      Invoke-Run | Should -Be 3010
      Invoke-Run -Resume | Should -Be 0
      $script:S.ResumeTask | Should -BeFalse
      $script:S.Restarted | Should -Be 1
      @($script:S.Calls | Where-Object { $_ -match "--import" }).Count | Should -Be 1
      $script:S.Console.Count | Should -Be 1
    }
    It "does not restart when the features were already on" {
      $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }
      $script:S.WslInstalled = $true
      Invoke-Run | Should -Be 0
      $script:S.Restarted | Should -Be 0
      ($script:S.Calls -join "`n") | Should -Not -Match "msiexec"
    }
    It "finds the media again when its drive letter changed over the restart (review H1)" {
      Invoke-Run | Should -Be 3010
      $moved = Join-Path $script:S.Base "media-on-another-letter"
      Move-Item -LiteralPath $script:S.Media -Destination $moved
      $script:S.FoundMedia = $moved
      Invoke-Run -Resume | Should -Be 0
      ($script:S.Calls -join "`n") | Should -Match ([regex]::Escape($moved) + "\S*ubuntu-24\.04")
    }
    It "says to connect the media when it is nowhere after the restart, and leaves no task that fires for ever (H1, L3)" {
      Invoke-Run | Should -Be 3010
      Move-Item -LiteralPath $script:S.Media -Destination (Join-Path $script:S.Base "unplugged")
      Invoke-Run -Resume | Should -Be 1
      Get-Log | Should -Match "STOP step 1/\d+ media: .*Connect the media"
      $script:S.ResumeTask | Should -BeFalse
    }
    It "does not restart when the resume task could not be registered (review H2)" {
      Mock Register-TbResumeTask { Write-Error "Access is denied." }
      Invoke-Run | Should -Be 1
      $script:S.Restarted | Should -Be 0
      Get-Log | Should -Match "STOP step 5/\d+ wsl-enable: .*Access is denied"
    }
    It "refuses to continue under another Windows account" {
      Invoke-Run | Should -Be 3010
      $script:S.Account = "BOX\somebody"
      Invoke-Run -Resume | Should -Be 1
      ($script:S.Calls -join "`n") | Should -Not -Match "--import"
      Get-Log | Should -Match "STOP .*BOX\\owner"
    }
  }

  Context "the whole install" {
    BeforeEach {
      $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }
      $script:S.WslInstalled = $true
    }
    It "runs the steps in order and hands over to box-install.sh in its own window" {
      Invoke-Run | Should -Be 0
      $calls = $script:S.Calls -join "`n"
      $calls | Should -Match "wsl\.exe --import TrialBox \S+wsl \S+ubuntu-24\.04-wsl-amd64\.tar\.gz --version 2"
      Get-SetupSteps | Should -Be @("wslconf", "pid1", "no-linux-driver", "packages", "no-linux-driver", "gpu", "host-tree", "update-window", "windows-drives", "network-mode", "state", "boot-check", "egress-check", "egress-proof", "lan-check")
      $script:S.Console.Count | Should -Be 1
      $script:S.Console[0] | Should -Match "wsl\.exe -d TrialBox -u root .*wsl-setup\.sh install \S+/linux/trialbox-1\.0\.0\.tar"
      $state = Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json
      $state.finished | Should -BeTrue
    }
    It "writes .wslconfig from the hardware before WSL2 first starts: the desktop's share kept, swap off, the disk limit" {
      # NEW-WIN-3 (D-601) replaced NEW-WIN-1's file, which had swap=0 and no memory line
      Invoke-Run | Should -Be 0
      $cfg = Get-Content -LiteralPath (Join-Path $script:S.Base "profile/.wslconfig") -Raw
      $cfg | Should -Match "(?m)^swap=0"
      $cfg | Should -Match "(?m)^memory=144GB"        # 192 GB installed less the declared 25 percent
      $cfg | Should -Match "(?m)^processors=24"       # 32 logical processors less 25 percent
      $cfg | Should -Match "(?m)^defaultVhdSize=4000787030016"
      $cfg | Should -Match "(?m)^sparseVhd=true"
      $cfg | Should -Match "(?m)^networkingMode=mirrored"   # NEW-WIN-4 (D-604)
      $log = Get-Log
      $log.IndexOf("wslconfig: ok") | Should -BeLessThan $log.IndexOf("import: start")
    }
    It "never replaces a .wslconfig that is already there" {
      $p = Join-Path $script:S.Base "profile"
      New-Item -ItemType Directory -Force -Path $p | Out-Null
      Set-Content -LiteralPath (Join-Path $p ".wslconfig") -Value "[wsl2]`nmemory=8GB"
      Invoke-Run | Should -Be 0
      (Get-Content -LiteralPath (Join-Path $p ".wslconfig") -Raw) | Should -Match "memory=8GB"
      ($script:S.Said -join "`n") | Should -Match "swap"
    }
    It "writes its own .wslconfig again when the hardware changed, and upgrades the file NEW-WIN-1 wrote" {
      $p = Join-Path $script:S.Base "profile"
      New-Item -ItemType Directory -Force -Path $p | Out-Null
      Set-Content -LiteralPath (Join-Path $p ".wslconfig") -Value "# TrialBox (NEW-WIN-1, D-421): no swap`n[wsl2]`nswap=0"
      $script:S.MemoryGB = 256
      Invoke-Run | Should -Be 0
      (Get-Content -LiteralPath (Join-Path $p ".wslconfig") -Raw) | Should -Match "(?m)^memory=192GB"
    }
    It "follows the hardware on a finished install too, keeps the earlier file and says when it applies (review H2, M2, M3)" {
      Invoke-Run | Should -Be 0
      $p = Join-Path $script:S.Base "profile"
      $n = $script:S.Calls.Count
      Invoke-Run | Should -Be 0     # nothing changed: not written again, no copy
      @(Get-ChildItem -LiteralPath $p -Force -Filter ".wslconfig.before-trialbox-*").Count | Should -Be 0
      $script:S.MemoryGB = 256      # memory was added
      Invoke-Run | Should -Be 0
      (Get-Content -LiteralPath (Join-Path $p ".wslconfig") -Raw) | Should -Match "(?m)^memory=192GB"
      $kept = @(Get-ChildItem -LiteralPath $p -Force -Filter ".wslconfig.before-trialbox-*")
      $kept.Count | Should -Be 1
      (Get-Content -LiteralPath $kept[0].FullName -Raw) | Should -Match "(?m)^memory=144GB"
      ($script:S.Said -join "`n") | Should -Match "apply when WSL2 next starts"
      # nothing else was touched: the only commands are the read-only question for WSL2's networking mode (NEW-WIN-4)
      @($script:S.Calls | Select-Object -Skip $n | Where-Object { $_ -notmatch "wsl-setup\.sh network-mode$" }).Count | Should -Be 0
    }
    It "keeps the share this install used when it is started again without the parameter (review M2)" {
      $script:S.SetupFail["packages"] = "interrupted"
      $script:TbShareGiven = $true; $script:TbShareDefault = 50
      try { Invoke-Run | Should -Be 1 } finally { $script:TbShareGiven = $false; $script:TbShareDefault = 25 }
      $p = Join-Path $script:S.Base "profile/.wslconfig"
      (Get-Content -LiteralPath $p -Raw) | Should -Match "(?m)^memory=96GB"
      $script:S.SetupFail = @{}
      Invoke-Run | Should -Be 0
      (Get-Content -LiteralPath $p -Raw) | Should -Match "(?m)^memory=96GB"
    }
    It "writes over an empty .wslconfig as over a missing one (review M1)" {
      $p = Join-Path $script:S.Base "profile"
      New-Item -ItemType Directory -Force -Path $p | Out-Null
      [IO.File]::WriteAllBytes((Join-Path $p ".wslconfig"), [byte[]]@())
      Invoke-Run | Should -Be 0
      (Get-Content -LiteralPath (Join-Path $p ".wslconfig") -Raw) | Should -Match "(?m)^memory=144GB"
    }
    It "keeps a file in another encoding even when it starts like ours (review M3)" {
      $p = Join-Path $script:S.Base "profile"
      New-Item -ItemType Directory -Force -Path $p | Out-Null
      $f = Join-Path $p ".wslconfig"
      [IO.File]::WriteAllText($f, "# TrialBox notes of my own`r`n[wsl2]`r`nmemory=100GB`r`n", [Text.Encoding]::Unicode)
      $before = [IO.File]::ReadAllBytes($f)
      Invoke-Run | Should -Be 0
      [Convert]::ToBase64String([IO.File]::ReadAllBytes($f)) | Should -Be ([Convert]::ToBase64String($before))
      ($script:S.Said -join "`n") | Should -Match "not computed from this machine"
    }
    It "stops when the desktop's share leaves nothing for WSL2" {
      $script:S.MemoryGB = 1; $script:S.Processors = 1
      Invoke-Run | Should -Be 1
      ($script:S.Calls -join "`n") | Should -Not -Match "--import"
      Get-Log | Should -Match "STOP step 6/\d+ wslconfig"
    }
    It "registers the start-at-boot task for this account and distribution, with sleep and hibernation off, before the Linux installer waits" {
      Invoke-Run | Should -Be 0
      $script:S.BootTask | Should -Be "BOX\owner|TrialBox|TrialBox-WSL2"
      $calls = $script:S.Calls -join "`n"
      $calls | Should -Match "powercfg\.exe /hibernate off"
      foreach ($t in @("standby-timeout-ac", "hibernate-timeout-ac", "standby-timeout-dc", "hibernate-timeout-dc")) {
        $calls | Should -Match ("powercfg\.exe /change " + $t + " 0")
      }
      Get-Log | Should -Match "task TrialBox-WSL2: registered; state Running"
      $log = Get-Log
      $log.IndexOf("boot-task: ok") | Should -BeLessThan $log.IndexOf("linux-install: start")
    }
    It "stops when the task cannot be registered, before the Linux installer runs" {
      Mock Register-TbBootTask { throw "Access is denied." }
      Invoke-Run | Should -Be 1
      $script:S.Console.Count | Should -Be 0
      Get-Log | Should -Match "STOP step 12/\d+ boot-task: .*Access is denied"
    }
    It "says so and goes on when Windows refuses a power setting (review M4)" {
      Mock Invoke-TbNative { return @{ ExitCode = 1; Output = @("Hibernation is not supported") } } -ParameterFilter { $Exe -eq "powercfg.exe" -and ($Arguments -join " ") -eq "/hibernate off" }
      Invoke-Run | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "did not accept a power setting \(powercfg /hibernate off, exit 1\)"
    }
    It "keeps a task that is there and starts this distribution: it is not registered or started again (review M6)" {
      $script:S.SetupFail["gpu"] = "interrupted"
      $script:S.BootInfo = @{ State = "Running"; LastResult = "267009"; Action = "wsl.exe -d TrialBox --exec /bin/sh -c 'exec sleep infinity' " }
      Invoke-Run | Should -Be 1
      $script:S.SetupFail = @{}
      Invoke-Run | Should -Be 0
      $script:S.BootRegistered | Should -Be 0
      Get-Log | Should -Match "task TrialBox-WSL2: kept"
    }
    It "registers the task again when it is for another distribution or disabled (review M3)" {
      $script:S.BootInfo = @{ State = "Ready"; LastResult = "0"; Action = "wsl.exe -d Ubuntu-24.04 --exec /bin/sh -c 'exec sleep infinity' " }
      Invoke-Run | Should -Be 0
      $script:S.BootTask | Should -Be "BOX\owner|TrialBox|TrialBox-WSL2"
      Get-Log | Should -Match "task TrialBox-WSL2: restored"
    }
    It "puts the task back on a finished install when it was deleted, and changes nothing else (review M6)" {
      Invoke-Run | Should -Be 0
      $n = $script:S.Calls.Count
      $script:S.BootInfo = $null; $script:S.BootRegistered = 0
      Invoke-Run | Should -Be 0
      $script:S.BootRegistered | Should -Be 1
      ($script:S.Said -join "`n") | Should -Match "registered again"
      @($script:S.Calls | Select-Object -Skip $n | Where-Object { $_ -notmatch "wsl-setup\.sh network-mode$" }).Count | Should -Be 0   # only the read-only question for the networking mode (NEW-WIN-4)
      $script:S.Console.Count | Should -Be 1
    }
    It "opens the console's one port to the site's own network, once, before the Linux installer runs (NEW-WIN-4)" {
      Invoke-Run | Should -Be 0
      $script:S.Firewall | Should -Be @("TrialBox-Console|443|exists=False")
      $script:S.FwBlockSet | Should -Be 0      # the default was Block already: not touched
      $log = Get-Log
      $log.IndexOf("network: ok") | Should -BeLessThan $log.IndexOf("linux-install: start")
      $log | Should -Match "firewall rule TrialBox-Console: added"
      ($script:S.Said -join "`n") | Should -Match "port 443, to computers on the same network"
    }
    It "keeps its rule on a second run and writes nothing (review L14)" {
      $script:S.SetupFail["gpu"] = "interrupted"   # stops before step 13 the first time? no: gpu is step 10, so stop, then run again
      Invoke-Run | Should -Be 1
      $script:S.SetupFail = @{}
      Invoke-Run | Should -Be 0
      Invoke-Run | Should -Be 0                    # the finished install is started once more
      $script:S.Firewall.Count | Should -Be 1
      Get-Log | Should -Not -Match "firewall rule TrialBox-Console: corrected"
    }
    It "puts a rule of its name right when it is wider, for another port or switched off (review M4)" {
      foreach ($bad in @(@{ RemoteAddresses = "Any" }, @{ LocalPorts = "443,8090" }, @{ Enabled = "False" }, @{ Action = "Block" })) {
        New-Scenario | Out-Null
        $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }; $script:S.WslInstalled = $true
        $rule = @{ Enabled = "True"; Direction = "Inbound"; Action = "Allow"; Protocol = "TCP"; LocalPorts = "443"; RemoteAddresses = "LocalSubnet"; VMCreatorId = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" }
        foreach ($k in $bad.Keys) { $rule[$k] = $bad[$k] }
        $script:S.FwRule = $rule
        Invoke-Run | Should -Be 0 -Because ($bad.Keys -join ",")
        $script:S.Firewall | Should -Be @("TrialBox-Console|443|exists=True") -Because ($bad.Keys -join ",")
        ($script:S.Said -join "`n") | Should -Match "was there but wider than it should be"
        Get-Log | Should -Match "rule TrialBox-Console was: enabled"
      }
    }
    It "closes WSL's default for inbound traffic when it was open, and says that this is for every WSL system (review M5)" {
      $script:S.FwDefault = "Allow"
      Invoke-Run | Should -Be 0
      $script:S.FwBlockSet | Should -Be 1
      Get-Log | Should -Match "default for inbound traffic was 'Allow': set to Block"
      ($script:S.Said -join "`n") | Should -Match "every WSL system on this PC"
    }
    It "is not finished when a container could reach outside, and says the box must not get real data (review H1)" {
      $script:S.EgressVerdict = "verdict=OUT"
      Invoke-Run | Should -Be 1
      (Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json).finished | Should -BeFalse
      Get-Log | Should -Match "STOP step 14/\d+ linux-install: A TrialBox container could reach an outside address"
    }
    It "finishes with a plain warning when the egress table was not seen to act, or the box's firewall is open to another network" {
      $script:S.EgressVerdict = "verdict=inconclusive: no connection, but the table counted no dropped packet"
      $script:S.SetupFail["lan-check"] = "firewall open to '10.255.255.254/32'; this PC's network address '192.0.2.10/24'"
      Invoke-Run | Should -Be 0
      $said = $script:S.Said -join "`n"
      $said | Should -Match "could not show that a container is stopped from reaching outside \(verdict=inconclusive"
      $said | Should -Match "not open to the network this PC is on"
    }
    It "tells an install made before this card to restart, then adds the rule on the next start (review M6)" {
      Invoke-Run | Should -Be 0
      $script:S.Firewall = @(); $script:S.FwRule = $null     # as on a box finished before NEW-WIN-4
      $script:S.NetMode = "nat"                              # WSL2 still runs with the earlier networking
      Invoke-Run | Should -Be 0
      $script:S.Firewall.Count | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "Restart Windows, then start the installer once more"
      $script:S.NetMode = "mirrored"                         # after the restart
      Invoke-Run | Should -Be 0
      $script:S.Firewall | Should -Be @("TrialBox-Console|443|exists=False")
    }
    It "stops when WSL2 does not run with mirrored networking, and opens nothing" {
      $script:S.NetMode = "nat"
      Invoke-Run | Should -Be 1
      $script:S.Firewall.Count | Should -Be 0
      $script:S.Console.Count | Should -Be 0
      Get-Log | Should -Match "STOP step 13/\d+ network: .*it reports: nat"
    }
    It "is not finished while the egress table is not loaded under WSL2" {
      $script:S.SetupFail["egress-check"] = "the nftables table inet trialbox_egress is not loaded"
      Invoke-Run | Should -Be 1
      $state = Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json
      $state.finished | Should -BeFalse
      Get-Log | Should -Match "STOP step 14/\d+ linux-install: .*trialbox_egress"
    }
    It "is not finished while Docker or the stack would not start with the distribution" {
      $script:S.SetupFail["boot-check"] = "not enabled to start with the distribution: trialbox.service"
      Invoke-Run | Should -Be 1
      $state = Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json
      $state.finished | Should -BeFalse
      Get-Log | Should -Match "STOP step 14/\d+ linux-install: .*trialbox\.service"
    }
    It "sets the update window and the shutdown right during the install, in the owner's words (NEW-WIN-5)" {
      Invoke-Run | Should -Be 0
      $script:S.Upd.ScheduledInstallTime | Should -Be 19
      $script:S.Upd.ExcludeWUDriversInQualityUpdate | Should -Be 1
      $script:S.Shut.Sids | Should -Be @("S-1-5-32-544")
      $said = $script:S.Said -join "`n"
      $said | Should -Match "restarts this PC by itself only between 19:00 and 1:00"
      $said | Should -Match "Only administrators can shut this PC down now"
      Get-Log | Should -Match "Windows Update: installs daily at 19:00; restarts by itself only from 19:00 to 1:00"
      Get-Log | Should -Match "shutdown right was: S-1-5-32-544,S-1-5-32-545,S-1-5-32-551; offered at the sign-in screen: True"
    }
    It "goes on when Windows refuses the update settings, and says what that means (D-606 point 8)" {
      $script:S.UpdFailAt = 2
      Invoke-Run | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "Windows Update settings could not be written \(Requested registry access is not allowed\)"
      ($script:S.Said -join "`n") | Should -Match "Only administrators can shut this PC down now"    # the other half still done
    }
    It "tells the box which window Windows holds, once, and again when it changes" {
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh update-window 19\+6$" }).Count | Should -Be 1
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh update-window" }).Count | Should -Be 1
    }
    It "tells the box that IT's policy was kept, and says so to the owner once, not at every start" {
      $script:S.Upd = @{ NoAutoUpdate = 0; AUOptions = 3 }
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh update-window kept$" }).Count | Should -Be 1
      $script:S.Said.Clear()
      Invoke-Run | Should -Be 0
      ($script:S.Said -join "`n") | Should -Not -Match "Windows Update"
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh update-window" }).Count | Should -Be 1
    }
    It "tells the box which drives are this PC's own, once, the system drive always among them (NEW-WIN-7)" {
      $script:S.OwnDrives = @("D", "E")            # Windows lists two disks that are not on USB
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh windows-drives C,D,E$" }).Count | Should -Be 1
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh windows-drives" }).Count | Should -Be 1
      $script:S.OwnDrives = @("D")                 # the disk E: was taken out
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh windows-drives C,D$" }).Count | Should -Be 1
    }
    It "marks a USB disk as an outside drive for backups, on a finished install too (NEW-WIN-7)" {
      Invoke-Run | Should -Be 0
      $script:S.Marks.Count | Should -Be 0          # never without being asked
      $BackupDrive = "e:"
      Invoke-Run | Should -Be 0
      $script:S.Marks.Count | Should -Be 1
      $script:S.Marks[0] | Should -Match "^E\|TrialBox: an outside drive for backups"
      ($script:S.Said -join "`n") | Should -Match "Drive E: is marked as an outside drive for backups. Inside TrialBox it is /mnt/e"
      Get-Log | Should -Match "drive E: marked as an outside drive for backups \(bus USB\)"
    }
    It "does not mark <drive>: <why>" -ForEach @(
      @{ drive = "C:"; why = "the system drive"; says = "Drive C: is one of this PC's own drives" },
      @{ drive = "D"; why = "one of the PC's own disks"; says = "Drive D: is one of this PC's own drives" },
      @{ drive = "F:"; why = "not attached by USB"; says = "Drive F: is not a disk attached by USB \(Windows says: SATA\)" },
      @{ drive = "G:"; why = "not there"; says = "Drive G: could not be checked or marked \(no such drive\)" }
    ) {
      $BackupDrive = $drive
      Invoke-Run | Should -Be 0
      $script:S.Marks.Count | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match $says
    }
    It "does not mark any drive when Windows will not list its disks" {
      $script:S.OwnDrives = "fail"; $BackupDrive = "E:"
      Invoke-Run | Should -Be 0
      $script:S.Marks.Count | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "Drive E: could not be checked or marked \(Get-Disk is not available\)"
    }
    It "goes on when Windows does not list its disks: no drive is recorded, so no Windows drive counts as off-box" {
      $script:S.OwnDrives = "fail"
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "wsl-setup\.sh windows-drives" }).Count | Should -Be 0
      Get-Log | Should -Match "own drives could not be recorded for the backup check: Get-Disk is not available"
    }
    It "goes on when the shutdown right cannot be set, and says what to tell the users" {
      $script:S.ShutFails = $true
      Invoke-Run | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "could not be set \(secedit /configure ended with code 3\)"
    }
    It "keeps IT's Windows Update policy during the install and says so" {
      $script:S.Upd = @{ NoAutoUpdate = 1 }
      Invoke-Run | Should -Be 0
      $script:S.Upd.ContainsKey("AUOptions") | Should -BeFalse
      ($script:S.Said -join "`n") | Should -Match "already has a Windows Update policy"
    }
    It "gives an install made before NEW-WIN-5 the window on its next start, once, and is silent after that" {
      Invoke-Run | Should -Be 0
      $script:S.Upd = @{}; $script:S.Machine.Remove("update_window"); $script:S.Shut = @{ Sids = @("S-1-5-32-544", "S-1-5-32-545"); AtSignIn = $true }
      $script:S.Said.Clear()
      Invoke-Run | Should -Be 0
      $script:S.Upd.ScheduledInstallTime | Should -Be 19
      $script:S.Shut.Sids | Should -Be @("S-1-5-32-544")
      ($script:S.Said -join "`n") | Should -Match "restarts this PC by itself only between"
      $script:S.Said.Clear(); $script:S.UpdWrites.Clear()
      Invoke-Run | Should -Be 0
      $script:S.UpdWrites.Count | Should -Be 0
      ($script:S.Said -join "`n") | Should -Not -Match "Windows Update|shut this PC down"
    }
    It "does nothing on a second run of a finished install" {
      Invoke-Run | Should -Be 0
      $n = $script:S.Calls.Count
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Select-Object -Skip $n | Where-Object { $_ -notmatch "wsl-setup\.sh network-mode$" }).Count | Should -Be 0   # only the read-only question for the networking mode (NEW-WIN-4)
      $script:S.Console.Count | Should -Be 1
    }
    It "refuses a distribution of that name it did not import, and never removes one" {
      $script:S.Distros = @("TrialBox")
      Invoke-Run | Should -Be 1
      $calls = $script:S.Calls -join "`n"
      $calls | Should -Not -Match "--import|--unregister|wsl-setup"
      Get-Log | Should -Match "STOP step 7/\d+ import"
    }
    It "takes up its own import when the window was closed while it ran (review M2)" {
      $script:S.ImportDies = $true
      Invoke-Run | Should -Be 1
      Invoke-Run | Should -Be 0
      @($script:S.Calls | Where-Object { $_ -match "--import" }).Count | Should -Be 1
    }
    It "names its own unfinished virtual disk as such, and still does not remove it (review M2)" {
      $script:S.ImportDies = $true
      Invoke-Run | Should -Be 1
      $script:S.Distros = @()   # the import died before the name was registered
      $d = Join-Path $script:S.Data "TrialBox/wsl"
      Set-Content -LiteralPath (Join-Path $d "ext4.vhdx") -Value "half a disk"
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 7/\d+ import: An earlier run of this installer was interrupted"
      Test-Path -LiteralPath (Join-Path $d "ext4.vhdx") | Should -BeTrue
    }
    It "removes the resume task on a finished install too (review L3)" {
      Invoke-Run | Should -Be 0
      $script:S.ResumeTask = $true
      Invoke-Run | Should -Be 0
      $script:S.ResumeTask | Should -BeFalse
    }
    It "stops with a plain message when the owner gives no drive (review L4)" {
      Mock Get-TbDataDriveCandidates { return @("D:", "E:") }
      Invoke-TbInstall -MediaRoot $script:S.Media -StateDir $script:S.StateDir -Lang en | Should -Be 1
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*not a fixed NTFS drive"
      Get-Log | Should -Not -Match "unexpected"
    }
    It "refuses a data folder that already holds a virtual disk" {
      $d = Join-Path $script:S.Data "TrialBox/wsl"
      New-Item -ItemType Directory -Force -Path $d | Out-Null
      Set-Content -LiteralPath (Join-Path $d "ext4.vhdx") -Value "old data"
      Invoke-Run | Should -Be 1
      ($script:S.Calls -join "`n") | Should -Not -Match "--import"
      (Get-Content -LiteralPath (Join-Path $d "ext4.vhdx") -Raw) | Should -Match "old data"
    }
    It "refuses a Linux NVIDIA driver before any package is installed" {
      $script:S.SetupFail["no-linux-driver"] = "a Linux NVIDIA driver is installed: nvidia-driver-570"
      Invoke-Run | Should -Be 1
      Get-SetupSteps | Should -Not -Contain "packages"
      $script:S.Console.Count | Should -Be 0
      Get-Log | Should -Match "STOP step 9/\d+ packages: .*nvidia-driver-570"
    }
    It "stops when no container sees the card, before the Linux installer runs" {
      $script:S.SetupFail["gpu"] = "no container sees the card"
      Invoke-Run | Should -Be 1
      $script:S.Console.Count | Should -Be 0
      Get-Log | Should -Match "STOP step 10/\d+ gpu-container"
    }
    It "stops when systemd is not the first process" {
      $script:S.Pid1 = "init"
      Invoke-Run | Should -Be 1
      Get-SetupSteps | Should -Not -Contain "packages"
    }
    It "keeps the install unfinished when the Linux installer stopped" {
      $script:S.InstallExit = 1; $script:S.StateLine = "installed=0"
      Invoke-Run | Should -Be 1
      $state = Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json
      $state.finished | Should -BeFalse
      Get-Log | Should -Match "STOP step 14/\d+ linux-install"
    }
    It "counts an install whose host check still has FAIL lines as installed, and says so" {
      $script:S.InstallExit = 1
      Invoke-Run | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "host check"
    }
    It "continues an interrupted run from any step and imports exactly once" {
      foreach ($step in @("wslconf", "packages", "gpu", "host-tree")) {
        New-Scenario | Out-Null
        $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }
        $script:S.WslInstalled = $true
        $script:S.SetupFail[$step] = "interrupted"
        Invoke-Run | Should -Be 1 -Because $step
        $script:S.SetupFail = @{}
        Invoke-Run | Should -Be 0 -Because $step
        @($script:S.Calls | Where-Object { $_ -match "--import" }).Count | Should -Be 1 -Because $step
      }
    }
    It "logs every step and never the Linux installer's window (the first-run code)" {
      Invoke-Run | Should -Be 0
      $log = Get-Log
      foreach ($name in @("media", "windows", "gpu-driver", "drive", "wsl-enable", "wslconfig", "import", "systemd",
          "packages", "gpu-container", "host-tree", "boot-task", "network", "linux-install")) { $log | Should -Match ("step \d+/14 " + $name + ": ok") }
      Should -Invoke Invoke-TbNative -Times 0 -ParameterFilter { ($Arguments -join " ") -match "wsl-setup\.sh install" }
    }
  }

  Context "Windows 10 22H2 (NEW-WIN-10, D-613; owner ruling D-503)" {
    BeforeEach {
      $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }
      $script:S.WslInstalled = $true
      $script:S.Build = 19045; $script:S.Edition = "Professional"; $script:S.NetMode = "nat"
    }
    It "installs on Windows 10 Pro 22H2 to the end, with the console forwarded through WSL2's own address" {
      Invoke-Run | Should -Be 0
      (Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json).finished | Should -BeTrue
      $script:S.HostFwWrites | Should -Be @("TrialBox-Console|443|exists=False")
      $script:S.ProxyRegistered | Should -Be 1
      $script:S.ProxyRuns | Should -Be 1
      $script:S.ProxyAccount | Should -Be "BOX\owner"
      $script:S.ProxyEvery | Should -Be 5
      Test-Path -LiteralPath $script:S.ProxyScript | Should -BeTrue      # copied where only administrators write
      Split-Path -Parent $script:S.ProxyScript | Should -Be $script:S.StateDir
      $script:S.HyperVCalls | Should -Be 0                             # no Hyper-V firewall on Windows 10
      Get-Log | Should -Match "console forwarding: added, port 443 to WSL2 at 172\.28\.14\.5"
      ($script:S.Said -join "`n") | Should -Match "forwarded to TrialBox"
    }
    It "writes .wslconfig without the setting Windows 10 does not have, and keeps WSL2's localhost forwarding off" {
      Invoke-Run | Should -Be 0
      $cfg = Get-Content -LiteralPath (Join-Path $script:S.Base "profile/.wslconfig") -Raw
      $cfg | Should -Not -Match "networkingMode"
      $cfg | Should -Match "(?m)^localhostForwarding=false"
      $cfg | Should -Match "(?m)^memory=144GB"
      $cfg | Should -Match "(?m)^swap=0"
    }
    It "refuses Windows 10 before 22H2 and Windows 10 Home, and changes nothing" {
      $script:S.Build = 19044
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "build 19044\. TrialBox needs build 19045 or later"
      New-Scenario | Out-Null
      $script:S.Build = 19045; $script:S.Edition = "Core"
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "edition Core"
      $script:S.HostFwWrites.Count | Should -Be 0
    }
    It "keeps its rule and task on a second run and only re-points the forwarding" {
      Invoke-Run | Should -Be 0
      Invoke-Run | Should -Be 0
      $script:S.HostFwWrites.Count | Should -Be 1
      $script:S.ProxyRegistered | Should -Be 1
      $script:S.ProxyRuns | Should -Be 2
    }
    It "puts a Windows Firewall rule of its name right when it is wider, on a public network, or switched off" {
      foreach ($bad in @(@{ RemoteAddress = "Any" }, @{ Profile = "Any" }, @{ Profile = "Public" }, @{ LocalPort = "443,8090" }, @{ Enabled = "False" })) {
        New-Scenario | Out-Null
        $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }; $script:S.WslInstalled = $true
        $script:S.Build = 19045; $script:S.Edition = "Professional"; $script:S.NetMode = "nat"
        $rule = @{ Enabled = "True"; Direction = "Inbound"; Action = "Allow"; Protocol = "TCP"; LocalPort = "443"; RemoteAddress = "LocalSubnet"; Profile = "Domain, Private" }
        foreach ($k in $bad.Keys) { $rule[$k] = $bad[$k] }
        $script:S.HostFw = $rule
        Invoke-Run | Should -Be 0 -Because ($bad.Keys -join ",")
        $script:S.HostFwWrites | Should -Be @("TrialBox-Console|443|exists=True") -Because ($bad.Keys -join ",")
      }
    }
    It "registers the forwarding task again when it was deleted or switched off" {
      Invoke-Run | Should -Be 0
      $script:S.ProxyTask = $null
      Invoke-Run | Should -Be 0
      $script:S.ProxyRegistered | Should -Be 2
      $script:S.ProxyTask.State = "Disabled"
      Invoke-Run | Should -Be 0
      $script:S.ProxyRegistered | Should -Be 3
    }
    It "stops when WSL2 gives no address to forward to, and says what to do" {
      $script:S.ProxyStatus = "no_address"; $script:S.ProxyAddress = ""
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 13/\d+ network: .*WSL2 gave no address"
      $script:S.Console.Count | Should -Be 0
    }
    It "keeps mirrored networking on Windows 11: no forwarding there" {
      $script:S.Build = 26100; $script:S.Edition = "ProfessionalWorkstation"; $script:S.NetMode = "mirrored"
      Invoke-Run | Should -Be 0
      $script:S.ProxyRegistered | Should -Be 0
      $script:S.ProxyRuns | Should -Be 0
      $script:S.HostFwWrites.Count | Should -Be 0
      $script:S.Firewall | Should -Be @("TrialBox-Console|443|exists=False")
    }
    It "takes the Windows 10 form on a Windows 11 build without mirrored networking (21H2)" {
      $script:S.Build = 22000; $script:S.Edition = "Professional"; $script:S.NetMode = "nat"
      Invoke-Run | Should -Be 0
      $script:S.ProxyRegistered | Should -Be 1
      $script:S.HyperVCalls | Should -Be 0
    }
  }

  Context "small pieces" {
    It "turns a Windows path into the path WSL2 mounts it at" {
      ConvertTo-TbWslPath "D:\TrialBox\install\wsl-setup.sh" | Should -Be "/mnt/d/TrialBox/install/wsl-setup.sh"
      ConvertTo-TbWslPath "e:\TRIALBOX-1.0\linux\x.tar" | Should -Be "/mnt/e/TRIALBOX-1.0/linux/x.tar"
    }
    It "computes WSL2's share by rounding down, and refuses a share that leaves nothing" {
      Get-TbWslConfigText 255 20 25 0 | Should -Match "memory=191GB"
      Get-TbWslConfigText 255 20 25 0 | Should -Match "processors=15"
      Get-TbWslConfigText 255 20 25 0 | Should -Not -Match "defaultVhdSize"
      Get-TbWslConfigText 64 8 0 0 | Should -Match "memory=64GB"
      Get-TbWslConfigText 1 1 25 0 | Should -BeNullOrEmpty
    }
    It "picks the language from the Windows display language" {
      Get-TbLang "" "ja-JP" | Should -Be "ja"
      Get-TbLang "" "zh-TW" | Should -Be "zh-TW"
      Get-TbLang "" "zh-Hant-HK" | Should -Be "zh-TW"
      Get-TbLang "" "de-DE" | Should -Be "en"
      Get-TbLang "ja" "en-US" | Should -Be "ja"
    }
    It "is plain ASCII, so Windows PowerShell 5.1 reads it the same on every display language" {
      foreach ($f in @("box-install.ps1", "Install-TrialBox.cmd")) {
        $bytes = [IO.File]::ReadAllBytes((Join-Path $script:Root ("deploy/windows/" + $f)))
        @($bytes | Where-Object { $_ -gt 127 }).Count | Should -Be 0 -Because $f
      }
    }
    It "has no command that removes a distribution or a disk" {
      $text = Get-Content -LiteralPath $script:Ps1 -Raw
      $text | Should -Not -Match "--unregister|Remove-Item|Format-Volume|Clear-Disk|diskpart"
    }
  }

  Context "BitLocker (NEW-WIN-8, D-603)" {
    BeforeAll {
      function Set-DrivesOff {
        $s = $script:S
        foreach ($d in @("C:", $s.Data)) { $s.BL[$d] = @{ Status = "FullyDecrypted"; Protection = "Off"; AutoUnlock = $false; Protectors = @() } }
      }
      function Get-AllText {
        $s = $script:S
        return ((Get-Content -LiteralPath (Join-Path $s.StateDir "box-install.log") -Raw) + (Get-Content -LiteralPath (Join-Path $s.StateDir "state.json") -Raw))
      }
    }
    BeforeEach {
      $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }
      $script:S.WslInstalled = $true
    }
    It "keeps drives that are already encrypted, records the unlock setting, and turns nothing on or off" {
      Invoke-Run | Should -Be 0
      $script:S.BLCalls.Count | Should -Be 0
      $script:S.Machine["BitlockerUnlock"] | Should -Be "tpm"
      ($script:S.Said -join "`n") | Should -Match "nobody confirmed that its recovery key is held"
      Get-Log | Should -Match "step 4/\d+ drive: ok"
    }
    It "hands each key to the owner BEFORE the drive is encrypted, both before anything is imported (review H1, H2)" {
      Set-DrivesOff
      foreach ($a in @("n", "123456", "y", "654321")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 0
      $d = $script:S.Data
      # per drive: the key is made, shown and confirmed (the window cleared), only then the encryption starts
      $script:S.BLCalls | Should -Be @("recovery C:", "cleared", "system C:", "recovery $d", "cleared", "data $d", "auto $d")
      $said = $script:S.Said -join "`n"
      $said | Should -Match "111111-222222-333333-444444-555555-666666-777777-123456"   # shown in the window
      $said | Should -Match "888888-999999-000000-111111-222222-333333-444444-654321"
      $script:S.Printed.Count | Should -Be 1                                           # the one the owner asked for
      $script:S.Printed[0] | Should -Match "654321"
      ($script:S.Asked -join "`n") | Should -Match "printer 'Office-Printer'"           # the printer is named
      $log = Get-Log
      $log.IndexOf("turning BitLocker on for C:") | Should -BeLessThan $log.IndexOf("import: start")
      $log.IndexOf("recovery key of C:: shown, confirmed") | Should -BeLessThan $log.IndexOf("turning BitLocker on for C:")
    }
    It "never starts encryption when the owner did not confirm the key (review H2)" {
      Set-DrivesOff
      foreach ($a in @("n", "")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 1
      @($script:S.BLCalls | Where-Object { $_ -like "system*" -or $_ -like "data*" }).Count | Should -Be 0
      $script:S.BL["C:"].Status | Should -Be "FullyDecrypted"
    }
    It "stops with the key already in the owner's hands when the data drive cannot be set to open by itself (review H1)" {
      Set-DrivesOff
      $script:S.AutoUnlockFails = $true
      foreach ($a in @("n", "123456", "n", "654321")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 1
      $d = $script:S.Data
      $script:S.BLCalls.IndexOf("cleared") | Should -BeLessThan $script:S.BLCalls.IndexOf("data $d")
      ($script:S.Said -join "`n") | Should -Match "you hold its recovery key, but Windows did not set it to open together"
      ($script:S.Said -join "`n") | Should -Match "this install turned BitLocker on for C:,"
    }
    It "goes on at a second start while the first encryption still runs (review M2)" {
      Set-DrivesOff
      foreach ($a in @("n", "123456", "n", "654321")) { [void]$script:S.Answers.Add($a) }
      $script:S.SetupFail["packages"] = "interrupted"
      Invoke-Run -Ask | Should -Be 1
      $script:S.BL["C:"].Status | Should -Be "EncryptionInProgress"
      $script:S.BL["C:"].Protection | Should -Be "Off"
      $script:S.SetupFail = @{}
      Invoke-Run -Ask | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "this install turned BitLocker on for C:"   # said at the first stop
    }
    It "hands over a NEW key when a drive was decrypted and is encrypted again (review M1)" {
      Set-DrivesOff
      foreach ($a in @("n", "123456", "n", "654321")) { [void]$script:S.Answers.Add($a) }
      $script:S.SetupFail["packages"] = "interrupted"
      Invoke-Run -Ask | Should -Be 1
      # somebody decrypted C: by hand; Windows makes another key for it
      $script:S.BL["C:"] = @{ Status = "FullyDecrypted"; Protection = "Off"; AutoUnlock = $false; Protectors = @() }
      $script:S.Keys["C:"] = "121212-222222-333333-444444-555555-666666-777777-999000"; $script:S.KeyIds["C:"] = "{id-C-second}"
      $script:S.SetupFail = @{}
      foreach ($a in @("n", "999000")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 0
      ($script:S.Said -join "`n") | Should -Match "121212-222222-333333-444444-555555-666666-777777-999000"
    }
    It "does not show a key on a PC that records every PowerShell window (review M5)" {
      Set-DrivesOff
      $script:S.Transcription = $true
      foreach ($a in @("n", "123456")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 1
      ($script:S.Said -join "`n") | Should -Not -Match "\d{6}-\d{6}"
      @($script:S.BLCalls | Where-Object { $_ -like "system*" }).Count | Should -Be 0
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*records every PowerShell window"
    }
    It "asks no printer question when there is no default printer, and refuses a key of an unexpected form (review M6, L4)" {
      Set-DrivesOff
      $script:S.Printer = ""
      foreach ($a in @("123456", "654321")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 0
      @($script:S.Asked | Where-Object { $_ -match "Print" }).Count | Should -Be 0
      New-Scenario | Out-Null
      $script:S.Features = @{ "VirtualMachinePlatform" = $true; "Microsoft-Windows-Subsystem-Linux" = $true }; $script:S.WslInstalled = $true
      Set-DrivesOff
      $script:S.Keys["C:"] = "12345"
      foreach ($a in @("n", "12345")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 1
      @($script:S.BLCalls | Where-Object { $_ -like "system*" }).Count | Should -Be 0
    }
    It "writes no digit group of a recovery key to the log or the state" {
      Set-DrivesOff
      foreach ($a in @("n", "123456", "n", "654321")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 0
      $all = Get-AllText
      foreach ($group in (($script:S.Keys.Values -join "-") -split "-" | Sort-Object -Unique)) { $all | Should -Not -Match $group }
      (Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json).recovery_confirmed | Should -Match "C:"
    }
    It "does not ask again for a key the owner confirmed" {
      Set-DrivesOff
      foreach ($a in @("n", "123456", "n", "654321")) { [void]$script:S.Answers.Add($a) }
      $script:S.SetupFail["packages"] = "interrupted"
      Invoke-Run -Ask | Should -Be 1
      $script:S.SetupFail = @{}
      $n = $script:S.Asked.Count
      Invoke-Run -Ask | Should -Be 0
      @($script:S.Asked | Select-Object -Skip $n | Where-Object { $_ -match "six digits|Print" }).Count | Should -Be 0
      @($script:S.BLCalls | Where-Object { $_ -like "system*" -or $_ -like "data*" }).Count | Should -Be 2
    }
    It "asks again after wrong digits, and stops when the owner gives none: the key was not received" {
      Set-DrivesOff
      foreach ($a in @("n", "999999", "123456", "n", "")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 1
      ($script:S.Said -join "`n") | Should -Match "not the last six digits"
      Get-Log | Should -Match "STOP step 4/\d+ drive: Drive .*recovery key must be handed to a person"
      ($script:S.Calls -join "`n") | Should -Not -Match "--import"
      @($script:S.BLCalls | Where-Object { $_ -like "data*" }).Count | Should -Be 0   # the data drive is still plain
      # started again: the data drive's key is shown again (read back from Windows), then it is encrypted once
      foreach ($a in @("n", "654321")) { [void]$script:S.Answers.Add($a) }
      Invoke-Run -Ask | Should -Be 0
      @($script:S.BLCalls | Where-Object { $_ -like "data*" }).Count | Should -Be 1
      @($script:S.BLCalls | Where-Object { $_ -like "system*" }).Count | Should -Be 1
    }
    It "does not turn BitLocker on with nobody to receive the key (-Yes)" {
      Set-DrivesOff
      Invoke-Run | Should -Be 1
      $script:S.BLCalls.Count | Should -Be 0
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*handed to a person"
    }
    It "stops on a machine with no security chip, before anything is changed" {
      $script:S.Tpm = @{ Present = $true; Ready = $false }
      Set-DrivesOff
      Invoke-Run -Ask | Should -Be 1
      $script:S.BLCalls.Count | Should -Be 0
      Should -Invoke Enable-TbFeature -Times 0
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*security chip"
    }
    It "does not touch a drive whose BitLocker is suspended or being removed" {
      $script:S.BL["C:"] = @{ Status = "FullyEncrypted"; Protection = "Off"; AutoUnlock = $false; Protectors = @("Tpm", "RecoveryPassword") }
      Invoke-Run | Should -Be 1
      $script:S.BLCalls.Count | Should -Be 0
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*suspended"
    }
    It "stops when the system drive is encrypted but not opened by the TPM" {
      $script:S.BL["C:"].Protectors = @("Password", "RecoveryPassword")
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*TPM does not open it by itself"
    }
    It "says that BitLocker stays on when a later step stops, and no longer says nothing was changed (review M4)" {
      Set-DrivesOff
      foreach ($a in @("n", "123456", "n", "654321")) { [void]$script:S.Answers.Add($a) }
      $script:S.Distros = @("TrialBox")      # a distribution of that name this install did not make: stop at step 7
      Invoke-Run -Ask | Should -Be 1
      $said = $script:S.Said -join "`n"
      $said | Should -Match "this install turned BitLocker on for C:,"
      $said | Should -Not -Match "Nothing was changed"
      $said | Should -Match "The installer did not touch it"
    }
    It "turns on automatic unlock for a data drive that would stay locked after a restart" {
      $script:S.BL[$script:S.Data].AutoUnlock = $false
      Invoke-Run | Should -Be 0
      $script:S.BLCalls | Should -Be @(("auto " + $script:S.Data))
    }
    It "takes tpm_pin only when the PIN unlock is already there, never sets a PIN, and never turns tpm_pin into tpm (review M3)" {
      $script:TbUnlockGiven = $true; $script:TbUnlockDefault = "tpm_pin"
      try { Invoke-Run | Should -Be 1 } finally { $script:TbUnlockGiven = $false; $script:TbUnlockDefault = "tpm" }
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*no TPM-and-PIN unlock"
      $script:S.Machine.ContainsKey("BitlockerUnlock") | Should -BeFalse
      $script:S.BL["C:"].Protectors = @("TpmPin", "RecoveryPassword")
      Invoke-Run | Should -Be 0       # started again WITHOUT the parameter: the choice of the first start holds
      $script:S.Machine["BitlockerUnlock"] | Should -Be "tpm_pin"
      $script:S.BLCalls.Count | Should -Be 0
    }
    It "under tpm does not take a drive that asks for a PIN as one that starts with nobody there (review L1)" {
      $script:S.BL["C:"].Protectors = @("TpmPin", "RecoveryPassword")
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 4/\d+ drive: .*does not open it by itself"
    }
    It "records who keeps the recovery keys for the host check (review L3)" {
      Invoke-Run | Should -Be 0
      $script:S.Machine["RecoveryKeyKeptBy"] | Should -Match "the box owner"
    }
    It "leaves BitLocker alone for a rehearsal and says what that means" {
      $SkipBitLocker = $true
      Set-DrivesOff
      Invoke-Run | Should -Be 0
      $script:S.BLCalls.Count | Should -Be 0
      $script:S.Machine.ContainsKey("BitlockerUnlock") | Should -BeFalse
      ($script:S.Said -join "`n") | Should -Match "BitLocker was left as it is"
    }
    It "carries the unlock setting across the restart" {
      $script:S.Features = @{ "VirtualMachinePlatform" = $false; "Microsoft-Windows-Subsystem-Linux" = $false }
      $script:S.WslInstalled = $false
      Invoke-Run | Should -Be 3010
      $script:S.ResumeMore | Should -Match "-BitLockerUnlock tpm$"
    }
  }
}

Describe "Windows Update and the shutdown right (NEW-WIN-5, D-606)" {
  BeforeEach {
    New-Scenario | Out-Null
    $script:S.Machine = @{}
    Mock Set-TbMachineSetting { $script:S.Machine[$Name] = $Value }
    Mock Write-TbLog { }
    Mock Get-TbUpdatePolicy {
      $p = @{ Ours = [string]$script:S.Machine["update_window"] }
      foreach ($n in @("NoAutoUpdate", "AUOptions", "ScheduledInstallDay", "ScheduledInstallTime", "SetActiveHours", "ActiveHoursStart",
          "ActiveHoursEnd", "ExcludeWUDriversInQualityUpdate", "NoAutoRebootWithLoggedOnUsers", "AlwaysAutoRebootAtScheduledTime",
          "SetComplianceDeadline", "ConfigureDeadlineForQualityUpdates", "ConfigureDeadlineForFeatureUpdates", "Mdm")) { $p[$n] = $script:S.Upd[$n] }
      return $p
    }
    Mock Write-TbUpdateValue {
      if ($script:S.UpdFailAt -gt 0 -and $script:S.UpdWrites.Count -ge $script:S.UpdFailAt) { throw "Requested registry access is not allowed" }
      $script:S.Upd[$Name] = $Value; [void]$script:S.UpdWrites.Add("$Sub|$Name=$Value")
    }
    Mock Get-TbShutdownRight { return @{ Sids = @($script:S.Shut.Sids); AtSignIn = [bool]$script:S.Shut.AtSignIn } }
    Mock Write-TbShutdownRight { $script:S.ShutWrites++; if ($script:S.ShutSticks) { $script:S.Shut = @{ Sids = @($Sid); AtSignIn = $false } } }
  }
  It "sets the window on a PC with no policy: installs at its first hour, restarts only inside it, no drivers" {
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $u = $script:S.Upd
    $u.NoAutoUpdate | Should -Be 0
    $u.AUOptions | Should -Be 4                    # install at the scheduled time
    $u.ScheduledInstallDay | Should -Be 0          # every day
    $u.ScheduledInstallTime | Should -Be 19
    $u.SetActiveHours | Should -Be 1
    $u.ActiveHoursStart | Should -Be 1             # the window ends at 01:00: no restart from then ...
    $u.ActiveHoursEnd | Should -Be 19              # ... until the window opens again
    $u.ExcludeWUDriversInQualityUpdate | Should -Be 1
    $script:S.Machine["update_window"] | Should -Be "19+6"
    ($script:S.UpdWrites -join " ") | Should -Match "\\AU\|AUOptions=4"   # the AU values under the AU key
    ($script:S.UpdWrites -join " ") | Should -Match "(^| )\|SetActiveHours=1"
  }
  It "never protects more than 18 hours from restarts, whatever window is asked (Windows' own limit)" {
    foreach ($start in 0..23) {
      foreach ($hours in @(6, 9, 23)) {
        $script:S.Upd = @{}; $script:S.Machine = @{}
        Set-TbUpdateWindow $start $hours | Should -Be "written"
        $active = ($script:S.Upd.ActiveHoursEnd - $script:S.Upd.ActiveHoursStart + 24) % 24
        $active | Should -Be (24 - $hours)
        $active | Should -BeLessOrEqual 18
      }
    }
  }
  It "refuses a window shorter than six hours at the command line" {
    $cmd = Get-Command $script:Ps1
    $range = $cmd.Parameters["UpdateWindowHours"].Attributes | Where-Object { $_ -is [System.Management.Automation.ValidateRangeAttribute] }
    $range.MinRange | Should -Be 6
    $range.MaxRange | Should -Be 23
  }
  It "writes nothing on a second run" {
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $script:S.UpdWrites.Clear()
    Set-TbUpdateWindow 19 6 | Should -Be "same"
    $script:S.UpdWrites.Count | Should -Be 0
  }
  It "moves its own window when the owner names another" {
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    Set-TbUpdateWindow 12 8 | Should -Be "written"
    $script:S.Upd.ScheduledInstallTime | Should -Be 12
    $script:S.Upd.ActiveHoursStart | Should -Be 20
    $script:S.Machine["update_window"] | Should -Be "12+8"
  }
  It "puts its window back when a value was changed by hand" {
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $script:S.Upd.AUOptions = 3
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $script:S.Upd.AUOptions | Should -Be 4
  }
  It "keeps a policy the site's IT set, and still excludes drivers" {
    $script:S.Upd = @{ NoAutoUpdate = 0; AUOptions = 3 }       # IT: download and notify
    Set-TbUpdateWindow 19 6 | Should -Be "kept"
    $script:S.Upd.AUOptions | Should -Be 3
    $script:S.Upd.ContainsKey("ScheduledInstallTime") | Should -BeFalse
    $script:S.Upd.ContainsKey("SetActiveHours") | Should -BeFalse
    $script:S.Upd.ExcludeWUDriversInQualityUpdate | Should -Be 1
    $script:S.Machine.ContainsKey("update_window") | Should -BeFalse
    ($script:S.UpdWrites -join " ") | Should -Be "|ExcludeWUDriversInQualityUpdate=1"
  }
  It "keeps IT's active hours too (a policy with only active hours set)" {
    $script:S.Upd = @{ SetActiveHours = 1; ActiveHoursStart = 6; ActiveHoursEnd = 23; ExcludeWUDriversInQualityUpdate = 1 }
    Set-TbUpdateWindow 19 6 | Should -Be "kept"
    $script:S.UpdWrites.Count | Should -Be 0
  }
  It "takes values half written by a failed run as its own and writes them whole at the next start (review H1)" {
    $script:S.UpdFailAt = 4                       # the driver exclusion and three values go in, then Windows refuses
    { Set-TbUpdateWindow 19 6 } | Should -Throw
    $script:S.Upd.AUOptions | Should -Be 4
    $script:S.Upd.ContainsKey("SetActiveHours") | Should -BeFalse
    $script:S.Machine["update_window"] | Should -Be "19+6"     # the note went in first
    $script:S.UpdFailAt = 0
    Set-TbUpdateWindow 19 6 | Should -Be "written"             # not "kept", not "IT's policy"
    $script:S.Upd.SetActiveHours | Should -Be 1
    $script:S.Upd.ActiveHoursStart | Should -Be 1
  }
  It "keeps its hands off when a value of IT's would defeat the window: <name>" -ForEach @(
    @{ name = "NoAutoRebootWithLoggedOnUsers" }, @{ name = "AlwaysAutoRebootAtScheduledTime" }, @{ name = "SetComplianceDeadline" },
    @{ name = "ConfigureDeadlineForQualityUpdates" }, @{ name = "ConfigureDeadlineForFeatureUpdates" }, @{ name = "Mdm" }
  ) {
    $script:S.Upd = @{ $name = 1 }
    Set-TbUpdateWindow 19 6 | Should -Be "kept"
    $script:S.Upd.ContainsKey("AUOptions") | Should -BeFalse
    $script:S.Machine.ContainsKey("update_window") | Should -BeFalse
  }
  It "keeps a policy of IT's that sets only an install time" {
    $script:S.Upd = @{ ScheduledInstallTime = 4; ScheduledInstallDay = 1 }
    Set-TbUpdateWindow 19 6 | Should -Be "kept"
    $script:S.Upd.ScheduledInstallTime | Should -Be 4
  }
  It "knows its own window again when its note was deleted, and still moves it (review L1)" {
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $script:S.Machine.Remove("update_window")
    Set-TbUpdateWindow 12 8 | Should -Be "written"
    $script:S.Upd.ScheduledInstallTime | Should -Be 12
    $script:S.Machine["update_window"] | Should -Be "12+8"
  }
  It "writes over a value of its own that is not a number instead of failing at every start (review L2)" {
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $script:S.Upd.AUOptions = "abc"
    Set-TbUpdateWindow 19 6 | Should -Be "written"
    $script:S.Upd.AUOptions | Should -Be 4
  }
  It "does not say the shutdown right is set when it did not take (review L7)" {
    $script:S.ShutSticks = $false                 # a domain policy sets it back
    { Set-TbShutdownRight } | Should -Throw "*may set it back*"
  }
  It "leaves the right to shut down to administrators only, and takes it off the sign-in screen" {
    Set-TbShutdownRight | Should -Be "written"
    $script:S.Shut.Sids | Should -Be @("S-1-5-32-544")
    $script:S.Shut.AtSignIn | Should -BeFalse
    Set-TbShutdownRight | Should -Be "kept"
    $script:S.ShutWrites | Should -Be 1
  }
  It "sets the right again when only the sign-in screen still offers shutting down" {
    $script:S.Shut = @{ Sids = @("S-1-5-32-544"); AtSignIn = $true }
    Set-TbShutdownRight | Should -Be "written"
  }
}

Describe "the seam that gives a program the window (not replaced here)" {
  It "gives the Linux installer the window itself: its output is not collected, only its exit code comes back" {
    $r = Invoke-TbNativeConsole "/bin/sh" @("-c", "echo the-first-run-code; exit 3")
    $r | Should -BeOfType [int]
    @($r).Count | Should -Be 1
    $r | Should -Be 3
  }
  It "keeps an argument with a space as one argument" {
    $f = Join-Path $TestDrive "arg out.txt"
    Invoke-TbNativeConsole "/bin/sh" @("-c", 'printf %s "$1" > "$2"', "sh", "a b", $f) | Should -Be 0
    Get-Content -LiteralPath $f -Raw | Should -Be "a b"
  }
}
