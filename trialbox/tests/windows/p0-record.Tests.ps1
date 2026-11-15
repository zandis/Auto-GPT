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
    Mock Get-TbRecTimes { return @{ Boot = [datetime]"2026-11-15T01:00:00Z"; WslStart = [datetime]"2026-11-15T01:01:10Z"; FirstSignIn = [datetime]"2026-11-15T01:09:00Z" } }
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
    $text | Should -Match "dpapi_machine mode=at_startup result=ok"
  }

  It "answers line 26a from the times: WSL2 started before anyone signed in" {
    $text = Get-Content -LiteralPath (Write-TbRecord -Out $script:Out -When "at-boot" -StateDir $script:State -Distro "TrialBox" -WslConfig "") -Raw
    $text | Should -Match "wsl2_started_before_sign_in: yes \(70 s after boot; first sign-in 540 s after boot\)"
    Format-TbTimeline @{ Boot = [datetime]"2026-11-15T01:00:00Z"; WslStart = [datetime]"2026-11-15T01:10:00Z"; FirstSignIn = [datetime]"2026-11-15T01:09:00Z" } |
      Should -Match "wsl2_started_before_sign_in: no"
    Format-TbTimeline @{ Boot = [datetime]"2026-11-15T01:00:00Z"; WslStart = [datetime]"2026-11-15T01:01:00Z"; FirstSignIn = $null } |
      Should -Match "wsl2_started_before_sign_in: yes \(60 s after boot; nobody signed in since\)"
    Format-TbTimeline @{ Boot = $null; WslStart = $null; FirstSignIn = $null } | Should -Match "wsl2_started_before_sign_in: unknown"
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
