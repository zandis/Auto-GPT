# TrialBox: which Windows key store can the start-at-boot task open? (NEW-WIN-8, D-603; a probe for the P-0 rehearsal)
#
#   As administrator, signed in as the box owner, after the installer finished. Two runs:
#   1. powershell -NoProfile -ExecutionPolicy Bypass -File windows\key-probe.ps1 -AtStartup
#      then restart Windows, do NOT sign in for five minutes, sign in, and:
#      powershell -NoProfile -ExecutionPolicy Bypass -File windows\key-probe.ps1 -Collect
#   2. powershell -NoProfile -ExecutionPolicy Bypass -File windows\key-probe.ps1          (on demand, for comparison)
#
# The site keys must be handed to WSL2 after a restart with nobody signed in. The start-at-boot task runs with the
# sign-in type S4U (no stored password), and such a sign-in may not be allowed to open every key store. This probe
# does not guess: it stores a DUMMY value (random bytes made here, worth nothing) in three ways, then lets a task
# with the boot task's own sign-in type try to read each one back and hand the value to WSL2.
# Run 1 is the one that decides: the task runs at startup, before anyone has signed in, exactly as the boot task
# will. Run 2 runs the same task while the owner is signed in; a store that answers ok in run 2 and fail in run 1
# opens only because the owner's session had it open, and is of no use to a box that must return by itself.
# It prints one line per way. Send those lines back with the P-0 sheet. No TrialBox key or other secret is read,
# written or printed by this script.
#   dpapi_user     Windows' protected store of this account (DPAPI, CurrentUser)
#   dpapi_machine  the machine's protected store (DPAPI, LocalMachine; any account on the machine can open it)
#   acl_file       a file in the installer's closed folder (SYSTEM, the administrators and this account)
#   wsl_handover   the value written into the distribution's /run (memory) by the task, on standard input
# Run it from a local drive or the USB media, not from a network share (the task cannot read one).
# Keep this file ASCII and in Windows PowerShell 5.1 syntax.
param(
  [string]$Distro = "TrialBox",
  [string]$TaskName = "TrialBox-Key-Probe",
  # how long the on-demand task may take (it starts WSL2 when it is not running)
  [int]$WaitSeconds = 180,
  [switch]$AtStartup,
  [switch]$Collect,
  [string]$Inner = ""
)
$ErrorActionPreference = "Stop"
# the installer's folder: made for SYSTEM, the administrators and the owner only (box-install.ps1, D-600 point 4)
$ProbeDir = Join-Path $env:ProgramData "TrialBox\key-probe"
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
function Show-Result([string]$Mode) {
  $result = Join-Path $ProbeDir ("result-{0}.txt" -f $Mode)
  if ((Test-Path -LiteralPath $result) -and (Get-Item -LiteralPath $result).Length -gt 0) { Get-Content -LiteralPath $result | ForEach-Object { Write-Output $_ } }
  else { Write-Output ("mode={0}" -f $Mode); Write-Output "task_ran=fail: the task wrote no result (it did not start, or could not read this script or write to the probe folder)" }
  Write-Output "key-probe: these lines hold no secret; send them back with the P-0 sheet"
}

if ($Inner) {
  # under the task's own sign-in: read each form back; the results go to a file the outer run prints
  $want = (Get-Content -LiteralPath (Join-Path $ProbeDir "want.sha256") -Raw).Trim()
  $user = [Security.Cryptography.DataProtectionScope]::CurrentUser
  $machine = [Security.Cryptography.DataProtectionScope]::LocalMachine
  $lines = @(
    ("mode={0}" -f $Inner),
    ("ran_at={0}" -f [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")),
    ("ran_as={0}" -f [Security.Principal.WindowsIdentity]::GetCurrent().Name),
    # was anybody signed in when it ran? a desktop shell is the sign
    ("desktop_shells_running={0}" -f @(Get-Process -Name explorer -ErrorAction SilentlyContinue).Count),
    (Test-Way "dpapi_user" { [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $ProbeDir "user.blob")), $null, $user) } $want),
    (Test-Way "dpapi_machine" { [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $ProbeDir "machine.blob")), $null, $machine) } $want),
    (Test-Way "acl_file" { [IO.File]::ReadAllBytes((Join-Path $ProbeDir "plain.bin")) } $want)
  )
  try {
    # the value goes in on standard input as hex text, never as an argument; WSL2 answers with the hash of the
    # text that arrived, and this side compares it with the hash of the text it sent
    $hex = ([BitConverter]::ToString([IO.File]::ReadAllBytes((Join-Path $ProbeDir "plain.bin"))) -replace "-", "").ToLower()
    $sent = Get-Hash ([Text.Encoding]::ASCII.GetBytes($hex))
    $out = $hex | & wsl.exe -d $Distro -u root -- sh -c "umask 077; cat > /run/trialbox-key-probe; tr -d '\r\n' < /run/trialbox-key-probe | sha256sum | cut -d' ' -f1; rm -f /run/trialbox-key-probe"
    $got = (([string]($out | Select-Object -Last 1)) -replace "`0", "").Trim()
    if ($got -eq $sent) { $lines += "wsl_handover=ok" } else { $lines += ("wsl_handover=fail: WSL2 answered '{0}' (exit {1})" -f $got, $LASTEXITCODE) }
  } catch { $lines += ("wsl_handover=fail: {0}" -f (([string]$_.Exception.Message) -replace "[`r`n]+", " ")) }
  [IO.File]::WriteAllLines((Join-Path $ProbeDir ("result-{0}.txt" -f $Inner)), $lines)
  exit 0
}

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Output "key-probe: run it as administrator, signed in as the box owner"; exit 1
}
if (-not (Test-Path -LiteralPath (Split-Path -Parent $ProbeDir))) {
  Write-Output ("key-probe: {0} is not there: run the installer first (it makes that folder for administrators only)" -f (Split-Path -Parent $ProbeDir)); exit 1
}

if ($Collect) {
  # after the restart: what the task found at startup, then the task is removed
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($null -ne $task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Output ("key-probe: startup task last ran {0}; last result {1}" -f $info.LastRunTime, $info.LastTaskResult)
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  } else { Write-Output "key-probe: no startup task is registered (run -AtStartup first, then restart)" }
  Write-Output ("key-probe: you signed in at about {0} (now); compare with ran_at below" -f [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"))
  Show-Result "at_startup"
  exit 0
}

if (-not (Test-Path -LiteralPath $ProbeDir)) { New-Item -ItemType Directory -Path $ProbeDir | Out-Null }
$dummy = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($dummy) } finally { $rng.Dispose() }
[IO.File]::WriteAllText((Join-Path $ProbeDir "want.sha256"), (Get-Hash $dummy))
[IO.File]::WriteAllBytes((Join-Path $ProbeDir "user.blob"), [Security.Cryptography.ProtectedData]::Protect($dummy, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser))
[IO.File]::WriteAllBytes((Join-Path $ProbeDir "machine.blob"), [Security.Cryptography.ProtectedData]::Protect($dummy, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine))
[IO.File]::WriteAllBytes((Join-Path $ProbeDir "plain.bin"), $dummy)
$mode = "on_demand"; if ($AtStartup) { $mode = "at_startup" }
$result = Join-Path $ProbeDir ("result-{0}.txt" -f $mode)
[IO.File]::WriteAllText($result, "")

# the same sign-in type as the boot task (register_keepalive.ps1): S4U, no stored password, highest run level.
# The task runs a copy of this script in the closed folder, so it does not depend on the media being there
$copy = Join-Path $ProbeDir "key-probe.ps1"
Copy-Item -LiteralPath $PSCommandPath -Destination $copy -Force
$arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Inner {1} -Distro {2}' -f $copy, $mode, $Distro
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$principal = New-ScheduledTaskPrincipal -UserId $id.Name -LogonType S4U -RunLevel Highest
if ($AtStartup) {
  $trigger = New-ScheduledTaskTrigger -AtStartup
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Description "TrialBox: key store probe at startup (NEW-WIN-8), a dummy value only" -Force | Out-Null
  Write-Output "key-probe: registered. Now restart Windows, wait five minutes WITHOUT signing in, sign in, and run this script with -Collect."
  exit 0
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Description "TrialBox: key store probe (NEW-WIN-8), a dummy value only" -Force | Out-Null
try {
  Start-ScheduledTask -TaskName $TaskName
  $waited = 0
  while ($waited -lt $WaitSeconds -and ((Get-ScheduledTask -TaskName $TaskName).State -eq "Running" -or (Get-Item -LiteralPath $result).Length -eq 0)) {
    Start-Sleep -Seconds 2; $waited += 2
  }
  $info = Get-ScheduledTaskInfo -TaskName $TaskName
  Write-Output ("key-probe: task under S4U for {0}; last result {1}; waited {2} s" -f $id.Name, $info.LastTaskResult, $waited)
} finally {
  # the task never outlives this run, also when the run dies
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}
Show-Result "on_demand"
exit 0
