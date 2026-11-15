# TrialBox: fetch the P-0 media from its GitHub release onto the USB disk (NEW-WIN-13, D-616; rulings D-510, D-504).
#
#   Started by Get-TrialBox-P0.cmd (the one file the owner downloads), which checks this script's sha256 first.
#   powershell -NoProfile -ExecutionPolicy Bypass -File get-p0-media.ps1 -Base <release download URL> -Manifest <name>
#
# A GitHub release carries files of at most 2 GiB, so the media is one tar cut into parts with a manifest (the name,
# size and sha256 of each part; tools/windows_media.py parts). This script fetches every part into a work folder on
# this PC, checks each against the manifest (a damaged part is fetched once more, then it stops), and unpacks the
# media onto the USB disk: one that is exFAT or NTFS (a media file can pass FAT32's 4 GB) and has the room; of
# several, the roomiest. It never writes over a media folder already on the disk. The parts are removed afterwards.
# A second start after a cut connection fetches only the parts not yet there and right.
# Every Windows command is behind a function below (tests/windows/get-p0-media.Tests.ps1, Pester on PowerShell 7).
# Keep this file ASCII and in Windows PowerShell 5.1 syntax.
[CmdletBinding()]
param(
  [string]$Base = "",
  [string]$Manifest = "",
  [string]$Work = "",
  [switch]$LoadOnly
)

# ---- seams: the only places that touch Windows or the network
function Invoke-TbFetch([string]$Url, [string]$Path) {
  # BITS resumes a transfer the network cut; plain HTTPS when BITS is not there
  try { Start-BitsTransfer -Source $Url -Destination $Path -ErrorAction Stop }
  catch { Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing }
}
function Get-TbUsbVolumes {
  return @(Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveType -eq "Removable" -and $_.DriveLetter } | ForEach-Object {
      @{ Root = ("{0}:\" -f $_.DriveLetter); FreeBytes = [long]$_.SizeRemaining; FileSystem = [string]$_.FileSystemType; Label = [string]$_.FileSystemLabel }
    })
}
function Invoke-TbUntar([string[]]$Parts, [string]$Dest) {
  # the parts, in order, into tar.exe's standard input: the joined tar is never written, so the disk needs room for
  # the media only (tar.exe is part of Windows 10 1803 and later)
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = Join-Path $env:SystemRoot "System32\tar.exe"
  $psi.Arguments = ('-xf - -C "{0}"' -f $Dest)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardInput = $true
  $proc = [Diagnostics.Process]::Start($psi)
  try {
    foreach ($p in $Parts) {
      $fs = [IO.File]::OpenRead($p)
      try { $fs.CopyTo($proc.StandardInput.BaseStream) } finally { $fs.Dispose() }
    }
  } finally { $proc.StandardInput.Close() }
  $proc.WaitForExit()
  return $proc.ExitCode
}

# ---- logic
function Get-TbFileSha([string]$Path) { return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower() }
function Get-TbTextSha([string]$Text) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($Text))) -replace "-", "").ToLower() } finally { $sha.Dispose() }
}
function Select-TbUsb([long]$Need) {
  $ok = @(Get-TbUsbVolumes | Where-Object { @("exFAT", "NTFS") -contains $_.FileSystem -and [long]$_.FreeBytes -ge $Need })
  if ($ok.Count -eq 0) { return $null }
  return ($ok | Sort-Object { [long]$_.FreeBytes } -Descending | Select-Object -First 1)
}
function Test-TbPart([string]$Path, $Part) {
  return ((Test-Path -LiteralPath $Path) -and (Get-Item -LiteralPath $Path).Length -eq [long]$Part.size -and (Get-TbFileSha $Path) -eq [string]$Part.sha256)
}
function Get-TbP0Media([string]$Base, [string]$Manifest, [string]$Work) {
  # Returns @{ Status = ready | no_disk | exists | damaged | bad_manifest | unpack_failed; Media; Detail }
  if (-not (Test-Path -LiteralPath $Work)) { New-Item -ItemType Directory -Force -Path $Work | Out-Null }
  $mf = Join-Path $Work $Manifest
  Invoke-TbFetch ("{0}/{1}" -f $Base, $Manifest) $mf
  try { $m = Get-Content -LiteralPath $mf -Raw | ConvertFrom-Json } catch { return @{ Status = "bad_manifest"; Detail = "not JSON" } }
  # names only, never a path: nothing fetched may land outside the work folder or the disk's own media folder
  if ([string]$m.media -notmatch "^TRIALBOX-[A-Za-z0-9._-]+$") { return @{ Status = "bad_manifest"; Detail = [string]$m.media } }
  foreach ($p in @($m.parts)) { if ([string]$p.name -notmatch "^[A-Za-z0-9._-]+$") { return @{ Status = "bad_manifest"; Detail = [string]$p.name } } }
  $need = [long](@($m.parts) | Measure-Object -Property size -Sum).Sum
  $usb = Select-TbUsb ([long]($need * 1.02))   # 2 percent for the file system's own space per file
  if ($null -eq $usb) { return @{ Status = "no_disk"; Detail = ("{0:N1} GB" -f ($need / 1GB)) } }
  $media = Join-Path $usb.Root ([string]$m.media)
  if ((Test-Path -LiteralPath $media) -and @(Get-ChildItem -LiteralPath $media -Force).Count -gt 0) { return @{ Status = "exists"; Media = $media } }
  $local = @()
  foreach ($p in @($m.parts)) {
    $path = Join-Path $Work ([string]$p.name)
    $tries = 0
    while (-not (Test-TbPart $path $p)) {
      if ($tries -ge 2) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue; return @{ Status = "damaged"; Detail = [string]$p.name } }
      Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
      Invoke-TbFetch ("{0}/{1}" -f $Base, [string]$p.name) $path
      $tries++
    }
    $local += $path
  }
  $rc = Invoke-TbUntar $local $usb.Root
  if ($rc -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $media "SHA256SUMS"))) { return @{ Status = "unpack_failed"; Media = $media; Detail = ("tar exit {0}" -f $rc) } }
  foreach ($p in $local) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
  return @{ Status = "ready"; Media = $media }
}

if ($LoadOnly) { return }
if (-not $Work) { $Work = Join-Path $env:TEMP "TrialBox-P0" }
$r = Get-TbP0Media -Base $Base -Manifest $Manifest -Work $Work
switch ($r.Status) {
  "ready" { Write-Output ("The P-0 media is on the USB disk: {0}. Plug that disk into the PC for P-0 and double-click Install-TrialBox-P0.cmd in that folder." -f $r.Media); exit 0 }
  "no_disk" { Write-Output ("No USB disk with {0} free, formatted exFAT or NTFS, is plugged in. Plug one in and start this again." -f $r.Detail) }
  "exists" { Write-Output ("{0} is already on the USB disk; nothing was changed. If it is a complete media, use it as it is." -f $r.Media) }
  "damaged" { Write-Output ("The part {0} came damaged twice; nothing was put on the disk. Start this again later." -f $r.Detail) }
  default { Write-Output ("The media could not be fetched ({0}: {1}); nothing complete was put on the disk." -f $r.Status, $r.Detail) }
}
exit 1
