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
    Mock Invoke-TbUntar { [void]$script:Untarred.Add(($Parts | ForEach-Object { Split-Path -Leaf $_ }) -join ","); New-Item -ItemType Directory -Force -Path (Join-Path $Dest "TRIALBOX-p0a") | Out-Null; Set-Content -LiteralPath (Join-Path (Join-Path $Dest "TRIALBOX-p0a") "SHA256SUMS") -Value "x"; return 0 }
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
    foreach ($k in @("@RELEASE_BASE@", "@MANIFEST@", "@SCRIPT_SHA256@")) { $cmd | Should -Match ([regex]::Escape($k)) }
    $cmd | Should -Match "Get-FileHash"
    $cmd.IndexOf("Get-FileHash") | Should -BeLessThan $cmd.IndexOf("-File ")
  }
}
