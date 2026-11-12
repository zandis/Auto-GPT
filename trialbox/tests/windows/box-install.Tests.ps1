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
      "windows/box-install.ps1", "windows/box-install.messages.json", "windows/wsl-setup.sh",
      "windows/wsl/wsl.2.4.13.0.x64.msi", "windows/wsl/ubuntu-24.04-wsl-amd64.tar.gz",
      "linux/debs/docker-ce_27.deb", "linux/trialbox-host.tar", "linux/trialbox-1.0.0.tar", "linux/vendor_ed25519.pub"
    )
    $sums = @()
    foreach ($f in $files) {
      $p = Join-Path $media $f
      $src = Join-Path $script:Root ("deploy/windows/" + (Split-Path -Leaf $f))
      if ($f -like "windows/box-install.*" -or $f -like "windows/wsl-setup.sh") { Copy-Item -LiteralPath $src -Destination $p }
      else { Set-Content -LiteralPath $p -Value ("content of " + $f) -NoNewline }
      $sums += ("{0}  {1}" -f (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower(), $f)
    }
    Set-Content -LiteralPath (Join-Path $media "SHA256SUMS") -Value $sums
    $s = @{
      Base = $base; Media = $media; StateDir = (Join-Path $base "state"); Data = (Join-Path $base "data")
      Edition = "ProfessionalWorkstation"; Build = 26100; VirtFirmware = $true; Hypervisor = $false
      Account = "BOX\owner"; IsAdmin = $true; FreeGB = 3000
      Features = @{ "VirtualMachinePlatform" = $false; "Microsoft-Windows-Subsystem-Linux" = $false }
      FeatureRestart = $true; WslInstalled = $false; Distros = @(); WinGpu = $true
      Pid1 = "systemd"; SetupFail = @{}; InstallExit = 0; StateLine = "installed=1"
      Calls = New-Object System.Collections.ArrayList; Console = New-Object System.Collections.ArrayList
      Restarted = 0; ResumeTask = $false; FoundMedia = ""; ImportDies = $false; Said = New-Object System.Collections.ArrayList
    }
    New-Item -ItemType Directory -Force -Path $s.Data | Out-Null
    $script:S = $s
    return $s
  }

  function Invoke-Run([switch]$Resume) {
    $s = $script:S
    $p = @{ MediaRoot = $s.Media; DataDrive = $s.Data; StateDir = $s.StateDir; Lang = "en"; Yes = $true }
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
    Mock Get-TbDriveFacts { return @{ FreeGB = $script:S.FreeGB; Fixed = $true; FileSystem = "NTFS" } }
    Mock Get-TbDataDriveCandidates { return @() }
    Mock Protect-TbDirectory { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
    Mock Get-TbFeatureEnabled { return [bool]$script:S.Features[$Name] }
    Mock Enable-TbFeature { $script:S.Features[$Name] = $true; return [bool]$script:S.FeatureRestart }
    Mock Register-TbResumeTask { $script:S.ResumeTask = $true; $script:S.ResumeMore = $More; $script:S.ResumeScript = $ScriptPath }
    Mock Unregister-TbResumeTask { $script:S.ResumeTask = $false }
    Mock Restart-TbComputer { $script:S.Restarted++ }
    Mock Find-TbMedia { return [string]$script:S.FoundMedia }
    Mock Start-TbSleep { }
    Mock Read-TbLine { return "" }
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
    It "refuses a build before Windows 11" {
      $script:S.Build = 19045
      Invoke-Run | Should -Be 1
      Get-Log | Should -Match "STOP step 2/\d+ windows"
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
      $script:S.ResumeScript | Should -Be (Join-Path $script:S.StateDir "scripts/box-install.ps1")
    }
    It "hands this run's settings to the run after the restart, and no path or secret beyond them" {
      $MinFreeGB = 200; $script:S.FreeGB = 250
      Invoke-Run | Should -Be 3010
      $script:S.ResumeMore | Should -Be "-MinFreeGB 200 -MinWindowsBuild 22000 -StartWaitSeconds 120 -Distro TrialBox -Lang en"
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
      Get-SetupSteps | Should -Be @("wslconf", "pid1", "no-linux-driver", "packages", "no-linux-driver", "gpu", "host-tree", "state")
      $script:S.Console.Count | Should -Be 1
      $script:S.Console[0] | Should -Match "wsl\.exe -d TrialBox -u root .*wsl-setup\.sh install \S+/linux/trialbox-1\.0\.0\.tar"
      $state = Get-Content -LiteralPath (Join-Path $script:S.StateDir "state.json") -Raw | ConvertFrom-Json
      $state.finished | Should -BeTrue
    }
    It "writes .wslconfig with swap off before WSL2 first starts, and no memory figure of its own" {
      Invoke-Run | Should -Be 0
      $cfg = Get-Content -LiteralPath (Join-Path $script:S.Base "profile/.wslconfig") -Raw
      $cfg | Should -Match "(?m)^swap=0"
      $cfg | Should -Not -Match "memory="
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
    It "does nothing on a second run of a finished install" {
      Invoke-Run | Should -Be 0
      $n = $script:S.Calls.Count
      Invoke-Run | Should -Be 0
      $script:S.Calls.Count | Should -Be $n
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
      Get-Log | Should -Match "STOP step 12/\d+ linux-install"
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
          "packages", "gpu-container", "host-tree", "linux-install")) { $log | Should -Match ("step \d+/12 " + $name + ": ok") }
      Should -Invoke Invoke-TbNative -Times 0 -ParameterFilter { ($Arguments -join " ") -match "wsl-setup\.sh install" }
    }
  }

  Context "small pieces" {
    It "turns a Windows path into the path WSL2 mounts it at" {
      ConvertTo-TbWslPath "D:\TrialBox\install\wsl-setup.sh" | Should -Be "/mnt/d/TrialBox/install/wsl-setup.sh"
      ConvertTo-TbWslPath "e:\TRIALBOX-1.0\linux\x.tar" | Should -Be "/mnt/e/TRIALBOX-1.0/linux/x.tar"
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
