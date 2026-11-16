# NEW-WIN-15 (D-618; NEW-WIN-8 part 2, D-603): deploy/windows/site-key.ps1 holds the site keys' KEK on the Windows
# side and hands it into WSL2's memory at every start of Windows, so the box returns with nobody there.
# What this proves: the KEK only ever travels on standard input as 64 hex figures, never in an argument, a log or the
# screen; what is stored where; the check after storing; the copy inside WSL2 removed only after the check. What it
# cannot prove: DPAPI or a file's permissions under the boot task's S4U sign-in (P-0 line 36a decides the store).

BeforeAll {
  $script:Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
  . (Join-Path $script:Root "deploy/windows/site-key.ps1") -LoadOnly
}

Describe "site-key.ps1" {
  BeforeEach {
    $script:Dir = Join-Path $TestDrive ([guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $script:Dir | Out-Null
    $script:Kek = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
    $script:W = @{ Handout = $script:Kek; Sent = New-Object System.Collections.ArrayList; Shredded = 0; Cmds = New-Object System.Collections.ArrayList; HandExit = 0 }
    Mock Read-TbWslHandout { [void]$script:W.Cmds.Add("read"); return [string]$script:W.Handout }
    Mock Get-TbWslHandoutSha { return (Get-TbHexSha ([string]$script:W.Handout)) }
    Mock Remove-TbWslHandout { $script:W.Shredded++ }
    Mock Send-TbWslKek { [void]$script:W.Sent.Add($Hex); return [int]$script:W.HandExit }
    Mock Protect-TbUserBytes { param([byte[]]$Bytes) return ([byte[]](@(0xAA) + $Bytes)) }      # a stand-in for DPAPI
    Mock Unprotect-TbUserBytes { param([byte[]]$Bytes) return ([byte[]]($Bytes[1..($Bytes.Length - 1)])) }
  }

  It "takes the KEK from WSL2 once, stores it in the closed folder, checks it, and only then removes WSL2's copy" {
    $r = Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox"
    $r | Should -Be "stored"
    (Read-TbSiteKey -Dir $script:Dir -Store "acl_file") | Should -Be $script:Kek
    $script:W.Shredded | Should -Be 1
    Test-Path -LiteralPath (Join-Path $script:Dir "site-key.bin") | Should -BeTrue
  }

  It "stores it in this account's protected store (DPAPI) when that is the store chosen" {
    Save-TbSiteKey -Dir $script:Dir -Store "dpapi_user" -Distro "TrialBox" | Should -Be "stored"
    Test-Path -LiteralPath (Join-Path $script:Dir "site-key.dpapi") | Should -BeTrue
    Test-Path -LiteralPath (Join-Path $script:Dir "site-key.bin") | Should -BeFalse
    (Read-TbSiteKey -Dir $script:Dir -Store "dpapi_user") | Should -Be $script:Kek
  }

  It "keeps WSL2's copy and stores nothing when the read-back does not match (review: never lose the only copy)" {
    Mock Get-TbWslHandoutSha { return "0000" }
    Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox" | Should -Be "mismatch"
    $script:W.Shredded | Should -Be 0
    Test-Path -LiteralPath (Join-Path $script:Dir "site-key.bin") | Should -BeFalse
  }

  It "refuses a hand-out that is not 64 hex figures, and one that is not there" {
    $script:W.Handout = "not a key"
    Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox" | Should -Be "bad_handout"
    $script:W.Handout = ""
    Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox" | Should -Be "no_handout"
    $script:W.Shredded | Should -Be 0
  }

  It "never writes over a stored KEK (a second install keeps the first: the site keys are wrapped under it)" {
    Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox" | Should -Be "stored"
    $script:W.Handout = "ffeeddccbbaa99887766554433221100ffeeddccbbaa99887766554433221100"
    Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox" | Should -Be "exists"
    (Read-TbSiteKey -Dir $script:Dir -Store "acl_file") | Should -Be $script:Kek
  }

  It "hands the stored KEK into WSL2 at a start, on standard input only" {
    Save-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox" | Out-Null
    (Send-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox") | Should -Be "handed"
    $script:W.Sent | Should -Be @($script:Kek)
    (Send-TbSiteKey -Dir (Join-Path $TestDrive "none") -Store "acl_file" -Distro "TrialBox") | Should -Be "no_key"
    $script:W.HandExit = 1
    (Send-TbSiteKey -Dir $script:Dir -Store "acl_file" -Distro "TrialBox") | Should -Be "refused"
  }

  It "never puts the KEK in a command line, a log line or the screen" {
    $text = Get-Content -LiteralPath (Join-Path $script:Root "deploy/windows/site-key.ps1") -Raw
    # the seams that reach WSL2 take the KEK on standard input (a pipe into wsl.exe), never as an argument
    $text | Should -Match '\$Hex \| & wsl\.exe'
    foreach ($line in ($text -split "`n" | Where-Object { $_ -match '\$(Hex|hex|kek)\b' })) {
      $line | Should -Not -Match "Write-Output|Write-Host|Add-Content|Out-File|-Argument" -Because $line
    }
  }
}
