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
