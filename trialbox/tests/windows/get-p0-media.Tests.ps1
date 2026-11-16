# NEW-WIN-13 (D-616; owner ruling D-510, D-504): deploy/windows/get-p0-media.ps1 fetches the P-0 media from a GitHub
# release (parts under GitHub's 2 GiB asset limit), checks every part and unpacks the media onto the USB disk.
# What this proves: which disk is taken, that a part is checked and fetched again once, that nothing is overwritten,
# that a part already fetched and right is not fetched again. What it cannot prove: BITS, tar.exe, a real disk (P-0).

BeforeAll {
  $script:Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
  . (Join-Path $script:Root "deploy/windows/get-p0-media.ps1") -LoadOnly
}

Describe "get-p0-media.ps1" {
  BeforeEach {
    $script:Work = Join-Path $TestDrive ([guid]::NewGuid().ToString("N"))
    $script:Usb = Join-Path $TestDrive ([guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $script:Work, $script:Usb | Out-Null
    $script:Blobs = @{ "TRIALBOX-p0a.tar.part-001" = "first part"; "TRIALBOX-p0a.tar.part-002" = "second" }
    $script:Fetched = New-Object System.Collections.ArrayList
    $script:Corrupt = @{}
    $parts = @()
    foreach ($n in @($script:Blobs.Keys | Sort-Object)) {
      $parts += @{ name = $n; size = $script:Blobs[$n].Length; sha256 = (Get-TbTextSha $script:Blobs[$n]) }
    }
    $script:Manifest = @{ media = "TRIALBOX-p0a"; sha256 = "x"; parts = $parts } | ConvertTo-Json -Depth 4
    $script:Untarred = New-Object System.Collections.ArrayList
    Mock Invoke-TbFetch {
      $name = Split-Path -Leaf $Path
      [void]$script:Fetched.Add($name)
      if ($name -like "*.manifest.json") { Set-Content -LiteralPath $Path -Value $script:Manifest -NoNewline; return }
      $text = $script:Blobs[$name]
      if ($script:Corrupt[$name] -gt 0) { $script:Corrupt[$name]--; $text = "damaged" }
      Set-Content -LiteralPath $Path -Value $text -NoNewline
    }
    Mock Get-TbUsbVolumes { return @(@{ Root = $script:Usb; FreeBytes = 64GB; FileSystem = "exFAT"; Label = "USB" }) }
    $script:UntarExit = 0
    Mock Invoke-TbUntar {
      [void]$script:Untarred.Add(($Parts | ForEach-Object { Split-Path -Leaf $_ }) -join ",")
      # as tar.exe with Get-TbTarArgs: the media's own folder only, unpacked under its .partial name
      $d = Join-Path $Dest ($Media + ".partial")
      New-Item -ItemType Directory -Force -Path $d | Out-Null
      Set-Content -LiteralPath (Join-Path $d "SHA256SUMS") -Value "x"
      return $script:UntarExit
    }
    Mock Get-TbFreeBytes { return 500GB }
    $script:ManifestSha = ""
  }

  It "gives tar.exe the media's folder only, unpacked under a .partial name, and no path to change to (review 1, 8)" {
    $a = Get-TbTarArgs "TRIALBOX-p0a"
    $a | Should -Be @("-x", "-f", "-", "-s", ",^TRIALBOX-p0a/,TRIALBOX-p0a.partial/,", "TRIALBOX-p0a")
    ($a -join " ") | Should -Not -Match "-C"
    (Get-Content -LiteralPath (Join-Path $script:Root "deploy/windows/get-p0-media.ps1") -Raw) | Should -Match 'WorkingDirectory = \$Dest'
  }

  It "removes what a failed unpack left, so the next start can try again (review 4)" {
    $script:UntarExit = 1
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work
    $r.Status | Should -Be "unpack_failed"
    Test-Path -LiteralPath (Join-Path $script:Usb "TRIALBOX-p0a.partial") | Should -BeFalse
    Test-Path -LiteralPath (Join-Path $script:Usb "TRIALBOX-p0a") | Should -BeFalse
    $script:UntarExit = 0
    (Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work).Status | Should -Be "ready"
  }

  It "checks the manifest against the sha256 the launcher carries (review 8)" {
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work -ManifestSha "0000"
    $r.Status | Should -Be "bad_manifest"
    $script:Untarred.Count | Should -Be 0
    $good = Get-TbTextSha $script:Manifest
    (Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work -ManifestSha $good).Status | Should -Be "ready"
  }

  It "stops before fetching when this PC has no room for the parts (review 5)" {
    Mock Get-TbFreeBytes { return 5 }
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work
    $r.Status | Should -Be "no_room"
    @($script:Fetched | Where-Object { $_ -like "*.part-*" }).Count | Should -Be 0
  }

  It "speaks TLS 1.2 to GitHub on Windows PowerShell 5.1, in the launcher and the script (review 3)" {
    foreach ($f in @("Get-TrialBox-P0.cmd", "get-p0-media.ps1")) {
      (Get-Content -LiteralPath (Join-Path $script:Root ("deploy/windows/" + $f)) -Raw) | Should -Match "SecurityProtocol.*3072" -Because $f
    }
  }

  It "fetches every part, checks it, unpacks the media onto the USB disk and removes the parts" {
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work
    $r.Status | Should -Be "ready"
    $r.Media | Should -Be (Join-Path $script:Usb "TRIALBOX-p0a")
    $script:Untarred | Should -Be @("TRIALBOX-p0a.tar.part-001,TRIALBOX-p0a.tar.part-002")
    @(Get-ChildItem -LiteralPath $script:Work -Filter "*.part-*").Count | Should -Be 0
  }

  It "fetches a damaged part once more, and stops when it is damaged again" {
    $script:Corrupt["TRIALBOX-p0a.tar.part-002"] = 1
    (Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work).Status | Should -Be "ready"
    @($script:Fetched | Where-Object { $_ -eq "TRIALBOX-p0a.tar.part-002" }).Count | Should -Be 2
    Remove-Item -LiteralPath (Join-Path $script:Usb "TRIALBOX-p0a") -Recurse
    $script:Fetched.Clear(); $script:Untarred.Clear()
    $script:Corrupt["TRIALBOX-p0a.tar.part-001"] = 2
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work
    $r.Status | Should -Be "damaged"
    $script:Untarred.Count | Should -Be 0
    Test-Path -LiteralPath (Join-Path $script:Work "TRIALBOX-p0a.tar.part-001") | Should -BeFalse
  }

  It "does not fetch again a part that is already there and right (a second start after a cut connection)" {
    Set-Content -LiteralPath (Join-Path $script:Work "TRIALBOX-p0a.tar.part-001") -Value "first part" -NoNewline
    Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work | Out-Null
    $script:Fetched | Should -Not -Contain "TRIALBOX-p0a.tar.part-001"
  }

  It "takes the USB disk with room, never a FAT32 one (a media file can pass 4 GB), and the roomiest of several" {
    Mock Get-TbUsbVolumes { return @(@{ Root = "F:\"; FreeBytes = 8GB; FileSystem = "FAT32" }, @{ Root = "G:\"; FreeBytes = 1KB; FileSystem = "exFAT" },
        @{ Root = "H:\"; FreeBytes = 30GB; FileSystem = "NTFS" }, @{ Root = "I:\"; FreeBytes = 60GB; FileSystem = "exFAT" }) }
    (Select-TbUsb 10GB).Root | Should -Be "I:\"
    Mock Get-TbUsbVolumes { return @(@{ Root = "F:\"; FreeBytes = 64GB; FileSystem = "FAT32" }) }
    Select-TbUsb 10GB | Should -BeNullOrEmpty
  }

  It "stops, fetching nothing, when no USB disk has the room" {
    Mock Get-TbUsbVolumes { return @() }
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work
    $r.Status | Should -Be "no_disk"
    @($script:Fetched | Where-Object { $_ -like "*.part-*" }).Count | Should -Be 0
  }

  It "never writes over a media folder already on the disk" {
    New-Item -ItemType Directory -Force -Path (Join-Path $script:Usb "TRIALBOX-p0a") | Out-Null
    Set-Content -LiteralPath (Join-Path (Join-Path $script:Usb "TRIALBOX-p0a") "keep.txt") -Value "mine"
    $r = Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work
    $r.Status | Should -Be "exists"
    $script:Untarred.Count | Should -Be 0
    Get-Content -LiteralPath (Join-Path (Join-Path $script:Usb "TRIALBOX-p0a") "keep.txt") | Should -Be "mine"
  }

  It "refuses a manifest whose part names could leave the work folder" {
    $script:Manifest = @{ media = "TRIALBOX-p0a"; parts = @(@{ name = "..\evil.exe"; size = 1; sha256 = "a" }) } | ConvertTo-Json -Depth 4
    (Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work).Status | Should -Be "bad_manifest"
    $script:Manifest = @{ media = "..\x"; parts = @() } | ConvertTo-Json -Depth 4
    (Get-TbP0Media -Base "https://example.invalid/r" -Manifest "TRIALBOX-p0a.manifest.json" -Work $script:Work).Status | Should -Be "bad_manifest"
  }

  It "the launcher fetches this script, checks its sha256 before running it, and names the release it was made for" {
    $cmd = Get-Content -LiteralPath (Join-Path $script:Root "deploy/windows/Get-TrialBox-P0.cmd") -Raw
    foreach ($k in @("@RELEASE_BASE@", "@MANIFEST@", "@SCRIPT_SHA256@", "@MANIFEST_SHA256@")) { $cmd | Should -Match ([regex]::Escape($k)) }
    $cmd | Should -Match "Get-FileHash"
    $cmd.IndexOf("Get-FileHash") | Should -BeLessThan $cmd.IndexOf("-File ")
  }
}
