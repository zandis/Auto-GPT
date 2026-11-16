# TrialBox: read the Windows facts that the WSL2 hardening checks judge (T-210a, D-421; CR-041, OPS-061).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File host_facts.ps1 [-Distro Ubuntu-24.04] [-WslConfig <path>]
#              [-TaskName TrialBox-WSL2] [-RecoveryKeyEscrow "<who keeps the BitLocker recovery password>"]
#
# Prints key=value lines and nothing else. Values are enum names and numbers, never localised text, so a Japanese or
# Chinese Windows gives the same lines. Reads only: no setting is changed, no network. deploy/windows/wsl2_policy.py
# judges the lines (preflight.ps1 on Windows, check_host.sh --wsl2 in WSL2). Run it as administrator: BitLocker's key
# protectors need it (without it only the Explorer state of BitLocker is read).
param(
  [string]$Distro = "",
  [string]$WslConfig = "",
  [string]$TaskName = "TrialBox-WSL2",
  [string]$RecoveryKeyEscrow = ""
)
$ErrorActionPreference = "SilentlyContinue"
function Fact([string]$Key, $Value) { Write-Output ("{0}={1}" -f $Key, (([string]$Value) -replace "[`r`n]", " ")) }
function RegValue([string]$Path, [string]$Name) {
  $item = Get-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction SilentlyContinue
  if ($null -eq $item) { return "" }
  return [string]$item.$Name
}
function Epoch { return [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }

Fact "facts_version" 1
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$admin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Fact "is_admin" ([int]$admin)
$sys = $env:SystemDrive
Fact "system_drive" $sys

# the distribution's disk file (HKCU Lxss: the default distribution unless -Distro names one)
$lxss = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss"
$defaultId = RegValue $lxss "DefaultDistribution"
$vhdx = ""
foreach ($k in @(Get-ChildItem -LiteralPath $lxss -ErrorAction SilentlyContinue)) {
  $p = Get-ItemProperty -LiteralPath $k.PSPath
  $match = if ($Distro) { [string]$p.DistributionName -eq $Distro } else { $k.PSChildName -eq $defaultId }
  if ($match) {
    $base = ([string]$p.BasePath) -replace "^\\\\\?\\", ""
    $file = if ($p.VhdFileName) { [string]$p.VhdFileName } else { "ext4.vhdx" }
    $vhdx = Join-Path $base $file
    Fact "distro" $p.DistributionName
  }
}
$drives = @($sys)
if ($vhdx -and (Test-Path -LiteralPath $vhdx)) {
  $vd = Split-Path -Qualifier $vhdx
  Fact "vhdx_path" $vhdx
  Fact "vhdx_drive" $vd
  Fact "vhdx_gb" ([math]::Round((Get-Item -LiteralPath $vhdx -Force).Length / 1GB))
  $ld = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $vd)
  if ($ld) {
    Fact "vhdx_drive_size_gb" ([math]::Floor($ld.Size / 1GB))
    Fact "vhdx_drive_free_gb" ([math]::Floor($ld.FreeSpace / 1GB))
  }
  if ($drives -notcontains $vd) { $drives += $vd }
} else {
  Fact "vhdx_path" ""
}

# BitLocker on the system drive and the drive of the disk file; the page file's drives too
try {
  $pf = @(Get-CimInstance Win32_PageFileUsage -ErrorAction Stop)
  $pfDrives = @($pf | ForEach-Object { ([string]$_.Name).Substring(0, 1).ToUpper() } | Sort-Object -Unique)
  Fact "pagefile_known" 1
  Fact "pagefile_drives" ($pfDrives -join ",")
  foreach ($l in $pfDrives) { if ($drives -notcontains "${l}:") { $drives += "${l}:" } }
} catch {
  Fact "pagefile_known" 0
}
$shell = New-Object -ComObject Shell.Application -ErrorAction SilentlyContinue
foreach ($d in $drives) {
  $tag = $d.TrimEnd(":").ToUpper()
  if ($shell) {  # 1 on, 2 off, 3 encrypting, 4 decrypting, 5 suspended, 6 on and locked; readable without admin
    Fact "bitlocker_${tag}_shell" ($shell.NameSpace("${tag}:\").Self.ExtendedProperty("System.Volume.BitLockerProtection"))
  }
  $bl = Get-BitLockerVolume -MountPoint "${tag}:" -ErrorAction SilentlyContinue
  if ($null -eq $bl) { Fact "bitlocker_${tag}_status" "unknown"; continue }
  Fact "bitlocker_${tag}_status" $bl.VolumeStatus
  Fact "bitlocker_${tag}_protection" $bl.ProtectionStatus
  Fact "bitlocker_${tag}_method" $bl.EncryptionMethod
  Fact "bitlocker_${tag}_protectors" ((@($bl.KeyProtector) | ForEach-Object { [string]$_.KeyProtectorType }) -join ",")
  Fact "bitlocker_${tag}_autounlock" ([bool]$bl.AutoUnlockEnabled)
}
# who keeps the recovery keys: as stated at this check, else as recorded by box-install.ps1 when the owner
# confirmed each key at the install (NEW-WIN-8, D-603)
if (-not $RecoveryKeyEscrow) { $RecoveryKeyEscrow = RegValue "HKLM:\SOFTWARE\TrialBox" "RecoveryKeyKeptBy" }
Fact "recovery_escrow" $RecoveryKeyEscrow
# the box's disk unlock setting, recorded by box-install.ps1 (NEW-WIN-8, D-603): tpm or tpm_pin; empty when not set
Fact "bitlocker_unlock" (RegValue "HKLM:\SOFTWARE\TrialBox" "BitlockerUnlock")

# the installed memory and the logical processors (NEW-WIN-3, D-601): .wslconfig is computed from them; inside
# WSL2 one sees only WSL2's share
$mods = @(Get-CimInstance Win32_PhysicalMemory)
$memBytes = [long](($mods | Measure-Object -Property Capacity -Sum).Sum)
$csys = Get-CimInstance Win32_ComputerSystem
if ($memBytes -le 0) { $memBytes = [long]$csys.TotalPhysicalMemory }
Fact "installed_memory_gb" ([math]::Floor($memBytes / 1GB))
Fact "logical_processors" $csys.NumberOfLogicalProcessors

# hibernation and Fast Startup (both write memory to C:\hiberfil.sys)
Fact "hibernate_enabled" (RegValue "HKLM:\SYSTEM\CurrentControlSet\Control\Power" "HibernateEnabled")
Fact "fast_startup" (RegValue "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" "HiberbootEnabled")
Fact "hiberfil_present" ([int](Test-Path -LiteralPath (Join-Path "$sys\" "hiberfil.sys")))

# .wslconfig of the user who runs WSL2, as it is (wsl2_policy.py reads swap and sparseVhd)
if (-not $WslConfig) { $WslConfig = Join-Path $env:USERPROFILE ".wslconfig" }
Fact "wslconfig_path" $WslConfig
if (Test-Path -LiteralPath $WslConfig) {
  Fact "wslconfig_found" 1
  Fact "wslconfig_b64" ([Convert]::ToBase64String([IO.File]::ReadAllBytes($WslConfig)))
} else {
  Fact "wslconfig_found" 0
}

# Remote Desktop
Fact "rdp_deny_connections" (RegValue "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" "fDenyTSConnections")

# Windows Update restarts: group policy, MDM policy, a restart already pending
$au = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
Fact "wu_no_auto_update" (RegValue $au "NoAutoUpdate")
Fact "wu_au_options" (RegValue $au "AUOptions")
Fact "wu_scheduled_install_day" (RegValue $au "ScheduledInstallDay")
Fact "wu_scheduled_install_time" (RegValue $au "ScheduledInstallTime")
Fact "wu_mdm_allow_auto_update" (RegValue "HKLM:\SOFTWARE\Microsoft\PolicyManager\current\device\Update" "AllowAutoUpdate")
# NEW-WIN-5 (D-606): the update window the installer set, Windows' active hours, drivers from Windows Update
$wu = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
Fact "update_window" (RegValue "HKLM:\SOFTWARE\TrialBox" "update_window")
Fact "wu_set_active_hours" (RegValue $wu "SetActiveHours")
Fact "wu_active_hours_start" (RegValue $wu "ActiveHoursStart")
Fact "wu_active_hours_end" (RegValue $wu "ActiveHoursEnd")
Fact "wu_exclude_drivers" (RegValue $wu "ExcludeWUDriversInQualityUpdate")
# values that take restarts out of the active hours' hands (Microsoft, "Manage device restarts after updates")
Fact "wu_no_auto_reboot_logged_on" (RegValue $au "NoAutoRebootWithLoggedOnUsers")
Fact "wu_always_reboot_at_scheduled" (RegValue $au "AlwaysAutoRebootAtScheduledTime")
Fact "wu_compliance_deadline" (RegValue $wu "SetComplianceDeadline")
Fact "wu_deadline_quality" (RegValue $wu "ConfigureDeadlineForQualityUpdates")
Fact "wu_deadline_feature" (RegValue $wu "ConfigureDeadlineForFeatureUpdates")
# whether the sign-in screen offers shutting down. The user right "Shut down the system" itself is not read here
# (Windows gives it only through secedit's export to a file, and this script writes nothing): the installer sets
# and logs it, and puts it right at every start
Fact "shutdown_at_sign_in" (RegValue "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" "ShutdownWithoutLogon")
Fact "wu_reboot_pending" ([int](Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"))

# NEW-WIN-6 (D-607): the card shared with the desktop. The card's memory by program, from Windows' own counters
# (a CIM class, the same name in every display language); WSL2's virtual machine is the process vmmem or vmmemWSL
$gp = @(Get-CimInstance -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory)
if ($gp.Count -eq 0) {
  Fact "gpu_programs_known" 0
} else {
  Fact "gpu_programs_known" 1
  $by = @{}
  foreach ($r in $gp) {
    if ([string]$r.Name -match "^pid_(\d+)_") { $id = [int]$Matches[1]; $by[$id] = [long]$by[$id] + [long]$r.DedicatedUsage }
  }
  $wslBytes = [long]0; $other = @{}
  foreach ($id in @($by.Keys)) {
    $n = [string](Get-Process -Id $id).ProcessName
    if (-not $n) { $n = "unknown" }
    if ($n -like "vmmem*") { $wslBytes += $by[$id] } else { $other[$n] = [long]$other[$n] + $by[$id] }
  }
  $sum = [long]0; foreach ($v in $other.Values) { $sum += $v }
  Fact "gpu_wsl_mib" ([long]($wslBytes / 1MB))
  Fact "gpu_outside_mib" ([long]($sum / 1MB))
  Fact "gpu_outside_top" ((@($other.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 5 |
        ForEach-Object { "{0}:{1}" -f ($_.Key -replace "[,:=]", "_"), [long]($_.Value / 1MB) }) -join ","))
}
# who is an administrator of this workstation: a number, no names. The built-in account counts when it is enabled
$adminCount = ""
$members = @(Get-LocalGroupMember -SID "S-1-5-32-544" | Where-Object { $_.ObjectClass -eq "User" })
if ($members.Count -gt 0) {
  $adminCount = 0
  foreach ($m in $members) {
    if ([string]$m.PrincipalSource -eq "Local") { if ((Get-LocalUser -SID $m.SID).Enabled) { $adminCount++ } } else { $adminCount++ }
  }
}
Fact "admin_accounts" $adminCount

# NEW-WIN-10 (D-613): the Windows build, and on a build without WSL2's mirrored networking the console's forwarding:
# the port-proxy row for 0.0.0.0:443 (netsh's rows are figures in every display language) and the task that keeps it
Fact "windows_build" ((Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").CurrentBuildNumber)
$proxyTo = ""
foreach ($row in @(& netsh.exe interface portproxy show v4tov4 2>$null)) {
  if ([string]$row -match "^\s*0\.0\.0\.0\s+443\s+(\S+)\s+443\s*$") { $proxyTo = $Matches[1] }
}
Fact "console_proxy_to" $proxyTo
$proxyTask = Get-ScheduledTask -TaskName "TrialBox-Console-Proxy" -ErrorAction SilentlyContinue
if ($null -eq $proxyTask) { Fact "console_proxy_task" "missing" } else { Fact "console_proxy_task" $proxyTask.State }
# Windows' IP Helper service serves the port proxy: with it off a row is there and nothing listens (status/start type)
$ipHelper = Get-Service -Name "iphlpsvc" -ErrorAction SilentlyContinue
if ($null -eq $ipHelper) { Fact "ip_helper" "missing" } else { Fact "ip_helper" ("{0}/{1}" -f $ipHelper.Status, $ipHelper.StartType) }

# NEW-WIN-15 (D-618): where Windows keeps the site keys' KEK (the file's name only, never its content) and the task
# that hands it into WSL2 at each start
$keyDir = Join-Path $env:ProgramData "TrialBox\box-install"
# the folder the task hands from (-Dir in its arguments): an install with its own -StateDir keeps the KEK there
$keyTask = Get-ScheduledTask -TaskName "TrialBox-Site-Key" -ErrorAction SilentlyContinue
if ($null -ne $keyTask -and ((@($keyTask.Actions) | ForEach-Object { $_.Arguments }) -join " ") -match '-Dir "([^"]+)"') { $keyDir = $Matches[1] }
if (Test-Path -LiteralPath (Join-Path $keyDir "site-key.dpapi")) { Fact "site_key_store" "dpapi_user" }
elseif (Test-Path -LiteralPath (Join-Path $keyDir "site-key.bin")) { Fact "site_key_store" "acl_file" }
else { Fact "site_key_store" "none" }
if ($null -eq $keyTask) { Fact "site_key_task" "missing" } else { Fact "site_key_task" $keyTask.State }

# the start-at-boot task that keeps WSL2 running whether or not anyone is signed in (register_keepalive.ps1)
Fact "keepalive_task_name" $TaskName
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
  Fact "keepalive_task_found" 0
} else {
  Fact "keepalive_task_found" 1
  Fact "keepalive_task_state" $task.State
  Fact "keepalive_task_logon_type" $task.Principal.LogonType
  Fact "keepalive_task_triggers" ((@($task.Triggers) | ForEach-Object { $_.CimClass.CimClassName }) -join ",")
  Fact "keepalive_task_action" ((@($task.Actions) | ForEach-Object { "{0} {1}" -f $_.Execute, $_.Arguments }) -join " ; ")
}

# the clock (the WSL2 side is read by the caller around this script)
Fact "w32time_status" ((Get-Service -Name W32Time -ErrorAction SilentlyContinue).Status)
$now = Epoch
Fact "clock_windows_lo" $now
Fact "clock_windows_hi" $now
exit 0
