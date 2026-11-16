# NEW-WIN-12 (D-615; owner ruling D-510): deploy/windows/p0-record.ps1 writes down what the P-0 sheet's lines ask
# for, so the owner only starts P-0 and hands the USB disk back.
# What this proves: which sections are written, that a failing section never stops the others, that no recovery key
# is ever written, how line 26a's answer is worked out from the times. What it cannot prove: what Windows answers (P-0).

BeforeAll {
  $script:Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
  . (Join-Path $script:Root "deploy/windows/p0-record.ps1") -LoadOnly
}

Describe "p0-record.ps1" {
  BeforeEach {
    $script:Out = Join-Path $TestDrive ([guid]::NewGuid().ToString("N"))
    $script:State = Join-Path $TestDrive ([guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $script:State | Out-Null
    Set-Content -LiteralPath (Join-Path $script:State "box-install.log") -Value @("step 1/14 media: ok", "step 14/14 install: ok")
    Mock Get-TbRecWindows { return @("build 19045", "edition Professional") }
    Mock Get-TbRecWsl { return @("WSL version: 2.6.1.0") }
    Mock Get-TbRecNetwork { return @("0.0.0.0         443         172.28.14.5     443") }
    Mock Get-TbRecTasks { return @("TrialBox-WSL2 Ready S4U") }
    Mock Get-TbRecBitLocker { return @("G: FullyEncrypted On protectors RecoveryPassword") }
    Mock Get-TbRecInside { return @("TB_ENV=TEST") }
    Mock Get-TbRecKeyProbe { return @("dpapi_user mode=at_startup result=fail", "dpapi_machine mode=at_startup result=ok") }
    Mock Get-TbRecTimes { return @{ Boot = [datetime]"2026-11-15T01:00:00Z"; WslStart = [datetime]"2026-11-15T01:01:10Z"; FirstSignIn = [datetime]"2026-11-15T01:09:00Z"
        BootTaskState = "Running"; BootTaskLastRun = [datetime]"2026-11-15T01:00:50Z"; BootTaskResult = "267009" } }
    Mock Test-TbRecProbeReady { return $true }
    Mock Find-TbRecMedia { return "" }
  }

  It "writes one record with every section the sheet asks for, named by the time and the occasion" {
    $file = Write-TbRecord -Out $script:Out -When "after-run" -StateDir $script:State -Distro "TrialBox" -WslConfig ""
    Split-Path -Leaf $file | Should -Match "^\d{8}T\d{6}Z-after-run\.txt$"
    $text = Get-Content -LiteralPath $file -Raw
    foreach ($s in @("windows", "wsl", "wslconfig", "network", "tasks", "bitlocker", "times", "key probe", "inside WSL2", "installer log")) {
      $text | Should -Match ("(?m)^== {0}$" -f [regex]::Escape($s))
    }
    $text | Should -Match "build 19045"
    $text | Should -Match "step 14/14 install: ok"
    $boot = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "at-boot" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    $boot | Should -Match "dpapi_machine mode=at_startup result=ok"      # the probe is collected at a start of Windows
  }

  It "answers line 26a from the boot task itself: running since before anyone signed in (review 3, 4)" {
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "at-boot" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    $text | Should -Match "wsl2_started_before_sign_in: yes \(the boot task TrialBox-WSL2 runs since 50 s after boot; first sign-in 540 s after boot\)"
    $b = [datetime]"2026-11-15T01:00:00Z"
    # the task started after the sign-in: the sign-in, not the task, may have brought WSL2 up
    Format-TbTimeline @{ Boot = $b; FirstSignIn = $b.AddSeconds(60); BootTaskState = "Running"; BootTaskLastRun = $b.AddSeconds(90) } |
      Should -Match "wsl2_started_before_sign_in: no \(the boot task started 90 s after boot, after the first sign-in at 60 s\)"
    Format-TbTimeline @{ Boot = $b; FirstSignIn = $null; BootTaskState = "Running"; BootTaskLastRun = $b.AddSeconds(40) } |
      Should -Match "wsl2_started_before_sign_in: yes \(the boot task TrialBox-WSL2 runs since 40 s after boot; nobody signed in since\)"
    # WSL2 up but the boot task not running: something else holds it (the key probe, a person): not the boot task's doing
    Format-TbTimeline @{ Boot = $b; FirstSignIn = $null; BootTaskState = "Ready"; BootTaskResult = "1"; BootTaskLastRun = $b.AddSeconds(40) } |
      Should -Match "wsl2_started_before_sign_in: no \(the boot task TrialBox-WSL2 is Ready, last result 1; nobody signed in since\)"
    Format-TbTimeline @{ Boot = $b; FirstSignIn = $null; BootTaskState = ""; WslNotRunning = $true } |
      Should -Match "wsl2_started_before_sign_in: no \(WSL2 was not running when this was recorded"
    Format-TbTimeline @{ Boot = $null } | Should -Match "wsl2_started_before_sign_in: unknown"
  }

  It "collects the key probe only at a start of Windows, and only once it wrote its result (review 1)" {
    Mock Get-TbRecKeyProbe { return @("dpapi_machine mode=at_startup result=ok") }
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "after-run" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    Should -Invoke Get-TbRecKeyProbe -Times 0
    $text | Should -Match "(?m)^== key probe\s+not collected after a run"
    Mock Test-TbRecProbeReady { return $false }
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "at-boot" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    Should -Invoke Get-TbRecKeyProbe -Times 0
    $text | Should -Match "no result from the probe yet"
  }

  It "copies a record of a start of Windows to the media it finds, with no path given (review 2)" {
    $media = Join-Path $TestDrive "TRIALBOX-p0a"
    Mock Find-TbRecMedia { return $media }
    Resolve-TbRecCopyTo -When "at-boot" -CopyTo "" | Should -Be (Join-Path $media "P0-RECORD")
    Resolve-TbRecCopyTo -When "after-run" -CopyTo "X:\given" | Should -Be "X:\given"
    Mock Find-TbRecMedia { return "" }
    Resolve-TbRecCopyTo -When "at-boot" -CopyTo "" | Should -BeNullOrEmpty
  }

  It "reads wsl.exe's list whether it came as UTF-8 or as UTF-16 with NULs (review 7)" {
    ConvertFrom-TbWslList @("T`0r`0i`0a`0l`0B`0o`0x`0", " Ubuntu ") | Should -Be @("TrialBox", "Ubuntu")
  }

  It "writes down a section that fails and goes on with the others" {
    Mock Get-TbRecNetwork { throw "netsh is not there" }
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "after-run" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    $text | Should -Match "(?m)^== network\s+error: netsh is not there"
    $text | Should -Match "(?m)^== tasks$"
  }

  It "never writes a recovery key, whatever a section returns" {
    Mock Get-TbRecBitLocker { return @("RecoveryPassword 111111-222222-333333-444444-555555-666666-777777-123456") }
    Set-Content -LiteralPath (Join-Path $script:State "box-install.log") -Value "printed 888888-999999-000000-111111-222222-333333-444444-654321"
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "after-run" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    $text | Should -Not -Match "\d{6}-\d{6}-\d{6}"
    $text | Should -Match "\[a recovery key: not written\]"
    Mock Get-TbRecInside { return @("  One-time code:    ABCD-EFGH") }
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "after-run" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    $text | Should -Not -Match "ABCD-EFGH"
    $text | Should -Match "\[a first-run code: not written\]"
  }

  It "copies its records to a second folder (the USB disk) when one is given and reachable" {
    $usb = Join-Path $TestDrive "usb"
    New-Item -ItemType Directory -Force -Path $usb | Out-Null
    $f1 = Write-TbRecord -Out $script:Out -When "at-boot" -StateDir $script:State -Distro "TrialBox" -WslConfig ""
    Copy-TbRecords -From $script:Out -To (Join-Path $usb "P0-RECORD")
    Test-Path -LiteralPath (Join-Path (Join-Path $usb "P0-RECORD") (Split-Path -Leaf $f1)) | Should -BeTrue
    { Copy-TbRecords -From $script:Out -To (Join-Path $TestDrive "no-such-drive/P0-RECORD") } | Should -Not -Throw
  }
}
