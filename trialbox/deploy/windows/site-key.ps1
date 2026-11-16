# TrialBox: the site keys' KEK held by Windows and handed into WSL2 at every start (NEW-WIN-15, D-618; NEW-WIN-8
# part 2, D-603). WSL2 has no security chip, so without this the site keys wait for a passphrase after each restart.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File site-key.ps1 -Take [-Store acl_file|dpapi_user]   (the installer)
#   powershell -NoProfile -ExecutionPolicy Bypass -File site-key.ps1 -Hand [-Store ...]                    (its task, at start)
#   powershell -NoProfile -ExecutionPolicy Bypass -File site-key.ps1 -Register -User <account> [-Store ...]
#
# The hand-over with the Linux side (KEK_BACKEND=windows, deploy/hardening/seal_keys.sh; lane D's half):
#   at install  the Linux side leaves the new KEK in /var/lib/trialbox/kek.for-windows (on WSL2's disk, root only,
#               32 bytes): a restart before Windows took it must not lose the only copy.
#               -Take reads it once as 64 hex figures, stores it, reads the store back and compares it with the
#               file's own hash inside WSL2, and only then shreds the file there. A stored KEK is never written over.
#   at start    -Hand reads the store and writes the 64 hex figures, on standard input, to
#               /run/trialbox/kek.from-windows (tmpfs, root only), which the Linux side's unseal unit takes.
# The KEK travels on standard input only: never in a command line, a log, the screen or the task's arguments.
# The store (P-0 line 36a decides it; D-603 point 8): acl_file, a file in the installer's closed folder (SYSTEM, the
# administrators and the box owner; the folder sits on the BitLocker system drive), the default because a task
# signed in by S4U is expected to read it; or dpapi_user, this account's protected store (DPAPI), stronger, if the
# probe shows the boot task's sign-in can open it with nobody signed in.
# Every Windows command is behind a function below (tests/windows/site-key.Tests.ps1). ASCII, Windows PowerShell 5.1.
[CmdletBinding()]
param(
  [switch]$Take,
  [switch]$Hand,
  [switch]$Register,
  [string]$User = "",
  [ValidateSet("acl_file", "dpapi_user")][string]$Store = "acl_file",
  [string]$Dir = "",
  [ValidatePattern("^[A-Za-z0-9._-]+$")][string]$Distro = "TrialBox",
  [string]$TaskName = "TrialBox-Site-Key",
  [switch]$LoadOnly
)

# on WSL2's disk, not in memory: a restart before Windows took it must not lose the only copy of the KEK
$script:TbHandout = "/var/lib/trialbox/kek.for-windows"
$script:TbHandIn = "/run/trialbox/kek.from-windows"

# ---- seams: the only places that touch Windows or WSL2
function Read-TbWslHandout([string]$Distro) {
  $sh = "[ -f {0} ] && od -An -tx1 -v {0} | tr -d ' \n'" -f $script:TbHandout
  return ([string](@(& wsl.exe -d $Distro -u root --exec sh -c $sh 2>$null) -join "") -replace "`0", "").Trim()
}
function Get-TbWslHandoutSha([string]$Distro) {
  $sh = "od -An -tx1 -v {0} | tr -d ' \n' | sha256sum | cut -d' ' -f1" -f $script:TbHandout
  return ([string](@(& wsl.exe -d $Distro -u root --exec sh -c $sh 2>$null) -join "") -replace "`0", "").Trim()
}
function Remove-TbWslHandout([string]$Distro) {
  & wsl.exe -d $Distro -u root --exec sh -c ("shred -u {0} 2>/dev/null || rm -f {0}" -f $script:TbHandout) | Out-Null
}
function Send-TbWslKek([string]$Distro, [string]$Hex) {
  # exit 3: WSL2 holds the KEK already (unsealed, or handed and not yet taken): nothing is written. The 64 figures go
  # to wsl.exe's standard input exactly, with no line end (a pipe from PowerShell 5.1 would add CR LF, review 3)
  $sh = "[ -e /run/trialbox/kek ] && exit 3; [ -e {0} ] && exit 3; umask 077; mkdir -p /run/trialbox; cat > {0}.part && mv -f {0}.part {0}" -f $script:TbHandIn
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = "wsl.exe"
  $psi.Arguments = ("-d {0} -u root --exec sh -c `"{1}`"" -f $Distro, $sh)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardInput = $true
  $psi.RedirectStandardOutput = $true
  $proc = [Diagnostics.Process]::Start($psi)
  try { $proc.StandardInput.Write($Hex) } finally { $proc.StandardInput.Close() }
  [void]$proc.StandardOutput.ReadToEnd()
  $proc.WaitForExit()
  return $proc.ExitCode
}
function Start-TbSleep([int]$Seconds) { Start-Sleep -Seconds $Seconds }
function Protect-TbUserBytes([byte[]]$Bytes) {
  Add-Type -AssemblyName System.Security
  return [Security.Cryptography.ProtectedData]::Protect($Bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
}
function Unprotect-TbUserBytes([byte[]]$Bytes) {
  Add-Type -AssemblyName System.Security
  return [Security.Cryptography.ProtectedData]::Unprotect($Bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
}

# ---- logic
function Get-TbHexSha([string]$Text) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($Text))) -replace "-", "").ToLower() } finally { $sha.Dispose() }
}
function ConvertTo-TbBytes([string]$Hex) {
  $b = New-Object byte[] ($Hex.Length / 2)
  for ($i = 0; $i -lt $b.Length; $i++) { $b[$i] = [Convert]::ToByte($Hex.Substring($i * 2, 2), 16) }
  return , $b
}
function ConvertTo-TbHex([byte[]]$Bytes) { return (([BitConverter]::ToString($Bytes)) -replace "-", "").ToLower() }
function Get-TbStorePath([string]$Dir, [string]$Store) {
  if ($Store -eq "dpapi_user") { return (Join-Path $Dir "site-key.dpapi") }
  return (Join-Path $Dir "site-key.bin")
}
function Read-TbSiteKey([string]$Dir, [string]$Store) {
  # "" when there is no store; throws when there is one that cannot be read (DPAPI under another sign-in)
  $p = Get-TbStorePath $Dir $Store
  if (-not (Test-Path -LiteralPath $p)) { return "" }
  $bytes = [IO.File]::ReadAllBytes($p)
  if ($Store -eq "dpapi_user") { $bytes = Unprotect-TbUserBytes $bytes }
  if ($null -eq $bytes) { throw "the store gave nothing back" }
  return (ConvertTo-TbHex $bytes)
}
function Write-TbStore([string]$Dir, [string]$Store, [string]$Hex) {
  $bytes = ConvertTo-TbBytes $Hex
  if ($Store -eq "dpapi_user") { $bytes = Protect-TbUserBytes $bytes }
  $path = Get-TbStorePath $Dir $Store
  try {
    [IO.File]::WriteAllBytes($path + ".part", $bytes)
    Move-Item -LiteralPath ($path + ".part") -Destination $path -Force
  } finally { Remove-Item -LiteralPath ($path + ".part") -Force -ErrorAction SilentlyContinue }   # never a stray copy
}
function Save-TbSiteKey([string]$Dir, [string]$Store, [string]$Distro) {
  # Returns stored | replaced | exists | no_handout | bad_handout | mismatch
  $have = ""
  foreach ($s in @("acl_file", "dpapi_user")) { if (Test-Path -LiteralPath (Get-TbStorePath $Dir $s)) { $have = $s } }
  $hex = Read-TbWslHandout $Distro
  if ($have -and -not $hex) { return "exists" }
  if (-not $hex) { return "no_handout" }
  if ($hex -notmatch "^[0-9a-f]{64}$") { return "bad_handout" }
  if ($have) {
    # a take cut between store and shred left the same KEK on both sides: only the hand-out goes
    if ((Read-TbSiteKey $Dir $have) -eq $hex) { Remove-TbWslHandout $Distro; return "exists" }
    # another KEK: the Linux side makes one only when it has none (seal_keys.sh), and wraps the keys under it, so
    # the stored one wraps nothing any more (the distribution was installed again); it is replaced below, after the
    # same check, and kept when the check fails (review 1)
  }
  $old = $null
  if ($have) { $old = [IO.File]::ReadAllBytes((Get-TbStorePath $Dir $have)) }
  Write-TbStore $Dir $Store $hex
  if ($have -and $have -ne $Store) { Remove-Item -LiteralPath (Get-TbStorePath $Dir $have) -Force }
  # the store read back must be the file inside WSL2, by its own hash there, before that file is removed: the KEK
  # has one copy until then, and the site keys are wrapped under it
  $back = ""; try { $back = Read-TbSiteKey $Dir $Store } catch { $back = "" }
  if ($back -ne $hex -or (Get-TbHexSha $back) -ne (Get-TbWslHandoutSha $Distro)) {
    Remove-Item -LiteralPath (Get-TbStorePath $Dir $Store) -Force -ErrorAction SilentlyContinue
    if ($null -ne $old) { [IO.File]::WriteAllBytes((Get-TbStorePath $Dir $have), $old) }   # the old store as it was
    return "mismatch"
  }
  Remove-TbWslHandout $Distro
  if ($have) { return "replaced" }
  return "stored"
}
function Send-TbSiteKey([string]$Dir, [string]$Store, [string]$Distro, [int]$Tries = 10, [int]$WaitSeconds = 15) {
  # Returns handed | held | no_key | unreadable | refused. WSL2 may still be starting at a start of Windows: tried
  # again, the task itself does not restart an action that ended (review 2)
  try { $hex = Read-TbSiteKey $Dir $Store } catch { return "unreadable" }
  if (-not $hex) { return "no_key" }
  if ($hex -notmatch "^[0-9a-f]{64}$") { return "unreadable" }
  for ($i = 1; $i -le $Tries; $i++) {
    $rc = Send-TbWslKek $Distro $hex
    if ($rc -eq 0) { return "handed" }
    if ($rc -eq 3) { return "held" }
    if ($i -lt $Tries) { Start-TbSleep $WaitSeconds }
  }
  return "refused"
}
function Register-TbSiteKeyTask([string]$Account, [string]$Name, [string]$Self, [string]$Folder, [string]$Kind) {
  # at each start and every few minutes after, signed in or not (S4U, as the boot task): a WSL2 started again
  # without a start of Windows (wsl --shutdown, an update) gets the KEK again; one that holds it is left alone
  $arg = "-NoProfile -ExecutionPolicy Bypass -File `"{0}`" -Hand -Store {1} -Dir `"{2}`" -Distro {3}" -f $Self, $Kind, $Folder, $Distro
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
  $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType S4U -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
  $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger @((New-ScheduledTaskTrigger -AtStartup), $repeat) -Principal $principal `
    -Settings $settings -Description "TrialBox: hand the site keys' KEK into WSL2 at start (NEW-WIN-15)" -Force | Out-Null
}

if ($LoadOnly) { return }
if (-not $Dir) { $Dir = Join-Path $env:ProgramData "TrialBox\box-install" }
if ($Register) {
  if (-not $User) { Write-Output "site-key: -Register needs -User <the box owner's account>"; exit 2 }
  Register-TbSiteKeyTask $User $TaskName $PSCommandPath $Dir $Store
  Write-Output ("registered {0}: at each start, store {1}" -f $TaskName, $Store)
  exit 0
}
if ($Take) { $r = Save-TbSiteKey -Dir $Dir -Store $Store -Distro $Distro }
elseif ($Hand) { $r = Send-TbSiteKey -Dir $Dir -Store $Store -Distro $Distro }
else { Write-Output "site-key: -Take, -Hand or -Register"; exit 2 }
Write-Output ("status={0}" -f $r)
if (@("stored", "replaced", "exists", "handed", "held") -contains $r) { exit 0 }
exit 1
