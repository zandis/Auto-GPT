# TrialBox: which Windows key store can the start-at-boot task open? (NEW-WIN-8, D-603; a probe for the P-0 rehearsal)
#
#   As administrator, signed in as the box owner, after the installer finished:
#   powershell -NoProfile -ExecutionPolicy Bypass -File windows\key-probe.ps1 [-Distro TrialBox]
#
# The site keys must be handed to WSL2 after a restart with nobody signed in. The start-at-boot task runs with the
# sign-in type S4U (no stored password), and such a sign-in may not be allowed to open every key store. This probe
# does not guess: it stores a DUMMY value (random bytes made here, worth nothing) in three ways, then runs a
# one-time task with the same sign-in type as the boot task and lets it try to read each one back and to hand the
# value to WSL2. It prints one line per way. Send those lines back with the P-0 sheet; the mechanism of the key
# back end is chosen from them. No TrialBox key or other secret is read, written or printed by this script.
#   dpapi_user     Windows' protected store of this account (DPAPI, CurrentUser)
#   dpapi_machine  the machine's protected store (DPAPI, LocalMachine; any account on the machine can open it)
#   acl_file       a file only SYSTEM, the administrators and this account may read, on the BitLocker system drive
#   wsl_handover   the value written into the distribution's /run (memory) by the task
# Keep this file ASCII and in Windows PowerShell 5.1 syntax.
param(
  [string]$Distro = "TrialBox",
  [string]$TaskName = "TrialBox-Key-Probe",
  [string]$ProbeDir = "",
  # how long the one-time task may take (it starts WSL2 when it is not running)
  [int]$WaitSeconds = 180,
  [switch]$Inner
)
$ErrorActionPreference = "Stop"
if (-not $ProbeDir) { $ProbeDir = Join-Path $env:ProgramData "TrialBox\key-probe" }
Add-Type -AssemblyName System.Security
function Get-Hash([byte[]]$Bytes) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace "-", "").ToLower() } finally { $sha.Dispose() }
}
function Test-Way([string]$Name, [scriptblock]$Read, [string]$Want) {
  try {
    $got = & $Read
    if ((Get-Hash $got) -eq $Want) { return ("{0}=ok" -f $Name) }
    return ("{0}=fail: read back another value" -f $Name)
  } catch { return ("{0}=fail: {1}" -f $Name, (([string]$_.Exception.Message) -replace "[`r`n]+", " ")) }
}

if ($Inner) {
  # under the task's own sign-in: read each form back; the results go to a file the outer run prints
  $want = (Get-Content -LiteralPath (Join-Path $ProbeDir "want.sha256") -Raw).Trim()
  $user = [Security.Cryptography.DataProtectionScope]::CurrentUser
  $machine = [Security.Cryptography.DataProtectionScope]::LocalMachine
  $lines = @(
    ("ran_as={0}" -f [Security.Principal.WindowsIdentity]::GetCurrent().Name),
    (Test-Way "dpapi_user" { [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $ProbeDir "user.blob")), $null, $user) } $want),
    (Test-Way "dpapi_machine" { [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $ProbeDir "machine.blob")), $null, $machine) } $want),
    (Test-Way "acl_file" { [IO.File]::ReadAllBytes((Join-Path $ProbeDir "plain.bin")) } $want)
  )
  try {
    # the value goes in on standard input, never as an argument; WSL2 answers with its own hash of what arrived
    $hex = ([BitConverter]::ToString([IO.File]::ReadAllBytes((Join-Path $ProbeDir "plain.bin"))) -replace "-", "").ToLower()
    $out = $hex | & wsl.exe -d $Distro -u root -- sh -c "umask 077; cat > /run/trialbox-key-probe; tr -d '\r\n' < /run/trialbox-key-probe | xxd -r -p | sha256sum | cut -d' ' -f1; rm -f /run/trialbox-key-probe"
    $got = (([string]($out | Select-Object -Last 1)) -replace "`0", "").Trim()
    if ($got -eq $want) { $lines += "wsl_handover=ok" } else { $lines += ("wsl_handover=fail: WSL2 answered '{0}' (exit {1})" -f $got, $LASTEXITCODE) }
  } catch { $lines += ("wsl_handover=fail: {0}" -f (([string]$_.Exception.Message) -replace "[`r`n]+", " ")) }
  [IO.File]::WriteAllLines((Join-Path $ProbeDir "result.txt"), $lines)
  exit 0
}

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Output "key-probe: run it as administrator, signed in as the box owner"; exit 1
}
if (-not (Test-Path -LiteralPath (Split-Path -Parent $ProbeDir))) {
  Write-Output ("key-probe: {0} is not there: run the installer first (it makes that folder for administrators only)" -f (Split-Path -Parent $ProbeDir)); exit 1
}
if (-not (Test-Path -LiteralPath $ProbeDir)) { New-Item -ItemType Directory -Path $ProbeDir | Out-Null }
$dummy = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($dummy) } finally { $rng.Dispose() }
[IO.File]::WriteAllText((Join-Path $ProbeDir "want.sha256"), (Get-Hash $dummy))
[IO.File]::WriteAllBytes((Join-Path $ProbeDir "user.blob"), [Security.Cryptography.ProtectedData]::Protect($dummy, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser))
[IO.File]::WriteAllBytes((Join-Path $ProbeDir "machine.blob"), [Security.Cryptography.ProtectedData]::Protect($dummy, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine))
[IO.File]::WriteAllBytes((Join-Path $ProbeDir "plain.bin"), $dummy)
$result = Join-Path $ProbeDir "result.txt"
if (Test-Path -LiteralPath $result) { [IO.File]::WriteAllText($result, "") }

# the same sign-in type as the boot task (register_keepalive.ps1): S4U, no stored password, highest run level
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Inner -Distro {1} -ProbeDir "{2}"' -f $PSCommandPath, $Distro, $ProbeDir
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$principal = New-ScheduledTaskPrincipal -UserId $id.Name -LogonType S4U -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Description "TrialBox: key store probe (NEW-WIN-8), a dummy value only" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
$waited = 0
while ($waited -lt $WaitSeconds -and ((Get-ScheduledTask -TaskName $TaskName).State -eq "Running" -or -not (Test-Path -LiteralPath $result) -or (Get-Item -LiteralPath $result).Length -eq 0)) {
  Start-Sleep -Seconds 2; $waited += 2
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output ("key-probe: task under S4U for {0}; last result {1}; waited {2} s" -f $id.Name, $info.LastTaskResult, $waited)
if ((Test-Path -LiteralPath $result) -and (Get-Item -LiteralPath $result).Length -gt 0) { Get-Content -LiteralPath $result | ForEach-Object { Write-Output $_ } }
else { Write-Output "task_ran=fail: the task wrote no result (it did not start, or could not write to the probe folder)" }
Write-Output "key-probe: these lines hold no secret; send them back with the P-0 sheet"
exit 0
