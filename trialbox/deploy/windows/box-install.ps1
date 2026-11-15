# TrialBox: the installer for a Windows workstation (NEW-WIN-1, D-600; plan v7.2 section 2.3; D-494).
#
#   Double-click Install-TrialBox.cmd on the offline media (docs/handover/OFFLINE-MEDIA.md), or, as administrator:
#   powershell -NoProfile -ExecutionPolicy Bypass -File windows\box-install.ps1 [-DataDrive D:] [-Lang en|ja|zh-TW] [-Yes]
#
# Run it signed in as the box owner's Windows administrator account: WSL2's distribution belongs to the account
# that imports it. What it does, in order; each step checks the machine first, so a second run goes on where the
# first one stopped, and it stops at the first failure with one message and one line in the log:
#    1 media          the files it needs are on the media and match SHA256SUMS (a damaged copy; the bundle's
#                     signature is checked later, inside WSL2, by deploy/install.sh); the WSL package is signed by Microsoft
#    2 windows        administrator; Windows 10 22H2 or Windows 11, Pro, Pro for Workstations, Enterprise or
#                     Education (NEW-WIN-10, D-613; owner ruling D-503); virtualisation
#    3 gpu-driver     the NVIDIA driver for Windows answers (WSL2 uses it; no driver is ever installed in Linux)
#    4 drive          the data drive (the only other fixed drive, or the one the owner names) has room; the folder
#                     <drive>\TrialBox is made for administrators and this account only. BitLocker (NEW-WIN-8, D-603):
#                     on the system drive and the data drive, opened by the TPM; each drive's recovery key is shown
#                     (and printed when the owner says so), confirmed by its last six digits, and stored nowhere
#    5 wsl-enable     the two Windows features and the WSL package from the media; when Windows needs a restart, a
#                     task at this account's next sign-in runs this script again (-Resume), then the restart
#    6 wslconfig      %USERPROFILE%\.wslconfig before WSL2 first starts (NEW-WIN-3, D-601): memory and processors
#                     from the installed hardware less the desktop's share, swap=0, the virtual disk's size limit
#                     at the data drive's size. A file TrialBox did not write is kept as it is
#    7 import         wsl --import <Distro> <drive>\TrialBox\wsl <the Ubuntu 24.04 image> --version 2
#    8 systemd        /etc/wsl.conf [boot] systemd=true, the distribution stopped and started, PID 1 is systemd
#    9 packages       no Linux NVIDIA driver, before and after; Docker Engine and the NVIDIA Container Toolkit from
#                     the media's linux/debs
#   10 gpu-container  a container started with --gpus all sees the card
#   11 host-tree      the release's host tree unpacked to /opt/trialbox (never over an existing one)
#   12 boot-task      start without a person (NEW-WIN-2, D-602): hibernation and sleep off; the task TrialBox-WSL2
#                     (register_keepalive.ps1) starts the distribution at boot, signed in or not. Windows Update
#                     (NEW-WIN-5, D-606): installs and restarts only in the declared update window, never takes a
#                     driver (the NVIDIA driver stays the measured one); only administrators may shut the PC down.
#                     A Windows Update policy the site's IT already set is kept as it is
#   13 network        the console on the site's network (NEW-WIN-4, D-604): WSL2 runs with mirrored networking, and
#                     one firewall rule admits the console's port from the site's own network, nothing else. Where
#                     Windows has no mirrored networking (Windows 10; D-613), one port-proxy rule passes the console's
#                     port to WSL2's own address, kept pointed by a task (console-proxy.ps1), and one Windows Firewall
#                     rule admits that port from the site's own network on a private or domain network only
#   14 linux-install  deploy/box-install.sh inside WSL2, in this window: it shows the first-run code and waits for
#                     the owner. Its window is never written to the log. Then: Docker and the stack are enabled
#                     to start with the distribution
# It never removes a distribution, a virtual disk or a file it did not write: a distribution of the same name that
# this install did not import, or a virtual disk already in the data folder, stops it (D-600).
# The log, in English, for the install record: %ProgramData%\TrialBox\box-install\box-install.log. No secret is
# written to it. Every Windows command is behind one function (the "seams" below) so the logic is tested with
# Pester on PowerShell 7 (tests/windows); what only a real Windows machine can show is the P-0 rehearsal
# (docs/handover/P-0-windows-rehearsal.md). Keep this file ASCII and in Windows PowerShell 5.1 syntax.
[CmdletBinding()]
param(
  [string]$MediaRoot = "",
  [string]$DataDrive = "",
  [ValidatePattern("^[A-Za-z0-9._-]+$")][string]$Distro = "TrialBox",
  [ValidateSet("", "en", "ja", "zh-TW")][string]$Lang = "",
  [string]$StateDir = "",
  # room the data drive must have: the figure preflight.ps1 and preflight.sh already declare (D-125: images and
  # models about 40 GB; the lake, the databases and the local backup copies are the rest)
  [int]$MinFreeGB = 500,
  # Windows 10 22H2, the build the sites' workstations run (owner ruling D-503; NEW-WIN-10, D-613); WSL2 with
  # systemd, GPU support and the WSL package from the media all run on it. Windows 11 22H2 (build 22621) and later
  # serve the console with mirrored networking; earlier builds through the port proxy (step 13)
  [int]$MinWindowsBuild = 19045,
  # how often the console's forwarding is checked on a PC without mirrored networking: after WSL2 restarts, the
  # console answers again within this many minutes
  [ValidateRange(1, 60)][int]$ProxyEveryMinutes = 5,
  # how long a stopped distribution may take to start again with systemd as PID 1
  [int]$StartWaitSeconds = 120,
  # percent of the installed memory and processors kept for Windows and the desktop user; WSL2 gets the rest.
  # The declared setting TB_WSL_DESKTOP_SHARE_PCT (libs/tb_common/config.py; the same default, held by a test)
  [ValidateRange(0, 99)][int]$DesktopSharePercent = 25,
  # disk unlock (NEW-WIN-8, D-603; D-494 point 6): "tpm" the workstation returns after a restart with nobody
  # there; "tpm_pin" a person types a PIN at every restart (the site sets the PIN protector up with its IT first)
  [ValidateSet("tpm", "tpm_pin")][string]$BitLockerUnlock = "tpm",
  # a rehearsal on a PC that must stay unencrypted: BitLocker is left as it is, and the host check then fails
  [switch]$SkipBitLocker,
  # a rehearsal box (NEW-WIN-11, D-614): handed to the Linux installer as --rehearsal (lane D's D-726: the box is
  # TEST and says "rehearsal box", runs stand-in model servers, takes a bundle built with make_bundle.sh
  # --rehearsal; a site box refuses such a bundle). Kept in state.json: the install stays one to its end
  [switch]$Rehearsal,
  # the update window (NEW-WIN-5, D-606): the hour of the day, this PC's clock, at which Windows Update may install
  # and restart, and how many hours the window lasts. The declared settings TB_WIN_UPDATE_WINDOW_START and
  # TB_WIN_UPDATE_WINDOW_HOURS (libs/tb_common/config.py gives the reasons; the same defaults, held by a test).
  # At least 6 hours: Windows protects at most 18 hours of a day from restarts ("active hours")
  [ValidateRange(0, 23)][int]$UpdateWindowStart = 19,
  [ValidateRange(6, 23)][int]$UpdateWindowHours = 6,
  # an outside (USB) drive that backups may go to (NEW-WIN-7, D-608): the installer checks with Windows that it is
  # one and marks the drive. Start the installer with it once the drive is plugged in, also on a finished install
  [ValidatePattern("^$|^[A-Za-z]:?$")][string]$BackupDrive = "",
  [switch]$Resume,
  [switch]$Yes,
  [switch]$LoadOnly
)

# the desktop's share: the one given on this command line; else the one this install already used (state.json);
# else the declared default above
$script:TbShareDefault = $DesktopSharePercent
$script:TbShareGiven = $PSBoundParameters.ContainsKey("DesktopSharePercent")
# the disk unlock the same way: tpm_pin chosen once is never turned into tpm by a later start without the parameter
$script:TbUnlockDefault = $BitLockerUnlock
$script:TbUnlockGiven = $PSBoundParameters.ContainsKey("BitLockerUnlock")
# the update window the same way
$script:TbUpdateDefault = @($UpdateWindowStart, $UpdateWindowHours)
$script:TbUpdateGiven = @($PSBoundParameters.ContainsKey("UpdateWindowStart"), $PSBoundParameters.ContainsKey("UpdateWindowHours"))
# values of the site's IT that take restarts out of the window's hands (Microsoft: with either of the first two the
# active hours have no effect; a compliance deadline restarts whatever the hour); and a policy held by MDM
$script:TbUpdateForeign = @("NoAutoRebootWithLoggedOnUsers", "AlwaysAutoRebootAtScheduledTime", "SetComplianceDeadline",
  "ConfigureDeadlineForQualityUpdates", "ConfigureDeadlineForFeatureUpdates", "Mdm")
$script:TbAdminsSid = "S-1-5-32-544"  # the built-in Administrators group, the same on every Windows
$script:TbSteps = @("media", "windows", "gpu-driver", "drive", "wsl-enable", "wslconfig", "import", "systemd",
  "packages", "gpu-container", "host-tree", "boot-task", "network", "linux-install")
$script:TbEditions = @("Professional", "ProfessionalWorkstation", "Enterprise", "EnterpriseS", "Education",
  "ProfessionalEducation")
$script:TbFeatures = @("VirtualMachinePlatform", "Microsoft-Windows-Subsystem-Linux")
$script:TbResumeTask = "TrialBox-Install-Resume"
$script:TbMirroredBuild = 22621  # Windows 11 22H2: the first build with WSL2's mirrored networking (Microsoft Learn,
                                  # "Accessing network applications with WSL"); earlier builds take the port proxy
$script:TbProxyTask = "TrialBox-Console-Proxy"
# where this run finds its own files: the media's folder, or after a restart the copy in the state (the task runs it)
$script:TbHere = $PSScriptRoot
$script:TbConsolePort = 443  # the one port the stack publishes (deploy/docker-compose.identity.yml; a test holds the two together)
$script:TbFirewallRule = "TrialBox-Console"
$script:TbBootTask = "TrialBox-WSL2"  # the name host_facts.ps1 and wsl2_policy.py look for (D-421)
$script:TbRestartExit = 3010  # the exit code Windows installers use for "restart needed"

# ------------------------------------------------------------------------------------------------ seams (Windows)
function Get-TbWindowsFacts {
  $cv = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $cs = Get-CimInstance Win32_ComputerSystem
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $admin = ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  return @{
    EditionId = [string]$cv.EditionID; Build = [int]$cv.CurrentBuildNumber
    VirtualizationFirmware = [bool]$cpu.VirtualizationFirmwareEnabled; HypervisorPresent = [bool]$cs.HypervisorPresent
    Account = [string]$id.Name; IsAdmin = [bool]$admin; UiCulture = [string](Get-UICulture).Name
    SystemDrive = [string]$env:SystemDrive; UserProfile = [string]$env:USERPROFILE
  }
}
function Get-TbDriveFacts([string]$Drive) {
  $ld = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $Drive.Substring(0, 2))
  if ($null -eq $ld) { return $null }
  return @{ FreeGB = [math]::Floor($ld.FreeSpace / 1GB); Fixed = ($ld.DriveType -eq 3); FileSystem = [string]$ld.FileSystem
    SizeBytes = [long]$ld.Size }
}
function Get-TbHardware {
  # the installed memory (the modules' own sizes; what Windows can use when the firmware does not list modules)
  # and the logical processors, read on the Windows side: inside WSL2 one sees only WSL2's share
  $modules = @(Get-CimInstance Win32_PhysicalMemory)
  $bytes = [long](($modules | Measure-Object -Property Capacity -Sum).Sum)
  $cs = Get-CimInstance Win32_ComputerSystem
  # never more than Windows can use (to the nearest GB: Windows reports a little less than the modules hold)
  $usable = [long]([math]::Round([long]$cs.TotalPhysicalMemory / 1GB)) * 1GB
  if ($bytes -le 0 -or $bytes -gt $usable) { $bytes = $usable }
  return @{ MemoryGB = [int][math]::Floor($bytes / 1GB); Processors = [int]$cs.NumberOfLogicalProcessors }
}
function Get-TbDataDriveCandidates([string[]]$Not) {
  $out = @()
  foreach ($ld in @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3")) {
    if ($ld.FileSystem -eq "NTFS" -and ($Not -notcontains [string]$ld.DeviceID)) { $out += [string]$ld.DeviceID }
  }
  return $out
}
function Protect-TbDirectory([string]$Path, [string]$Account) {
  # A folder for SYSTEM, the administrators and the installing account only, with nothing inherited: a standard
  # desktop account can neither read the virtual disk nor plant a script that this installer would run.
  $sids = @(
    (New-Object Security.Principal.SecurityIdentifier "S-1-5-18"),
    (New-Object Security.Principal.SecurityIdentifier "S-1-5-32-544"),
    (New-Object Security.Principal.NTAccount $Account).Translate([Security.Principal.SecurityIdentifier])
  )
  if (Test-Path -LiteralPath $Path) {
    $owner = (Get-Acl -LiteralPath $Path).GetOwner([Security.Principal.SecurityIdentifier])
    if (@($sids | Where-Object { $_.Value -eq $owner.Value }).Count -eq 0) {
      throw ("TBOWNER " + $owner.Value)
    }
    # a folder that was open to other accounts may hold their files (a planted script): only an empty one is taken
    $old = Get-Acl -LiteralPath $Path
    $allowed = @($sids | ForEach-Object { $_.Value })
    $open = (-not $old.AreAccessRulesProtected) -or (@($old.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) |
        Where-Object { $_.AccessControlType -eq "Allow" -and ($allowed -notcontains $_.IdentityReference.Value) }).Count -gt 0)
    if ($open -and @(Get-ChildItem -LiteralPath $Path -Force).Count -gt 0) { throw "TBOWNER open-and-not-empty" }
  }
  $acl = New-Object Security.AccessControl.DirectorySecurity
  $acl.SetAccessRuleProtection($true, $false)
  $acl.SetOwner($sids[1])
  $inherit = [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
  foreach ($sid in $sids) {
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, "FullControl", $inherit, "None", "Allow")))
  }
  if (-not (Test-Path -LiteralPath $Path)) { [void][IO.Directory]::CreateDirectory($Path, $acl) }
  else { Set-Acl -LiteralPath $Path -AclObject $acl }
}
function Get-TbFeatureEnabled([string]$Name) {
  return ((Get-WindowsOptionalFeature -Online -FeatureName $Name).State -eq "Enabled")
}
function Enable-TbFeature([string]$Name) {
  $r = Enable-WindowsOptionalFeature -Online -FeatureName $Name -All -NoRestart
  return [bool]$r.RestartNeeded
}
function Test-TbMsiSignature([string]$Path) {
  $sig = Get-AuthenticodeSignature -LiteralPath $Path
  return ($sig.Status -eq "Valid" -and [string]$sig.SignerCertificate.Subject -match "O=Microsoft Corporation")
}
function Register-TbResumeTask([string]$ScriptPath, [string]$Account, [string]$StateDir, [string]$More) {
  $arguments = '-NoProfile -ExecutionPolicy Bypass -NoExit -File "{0}" -Resume -StateDir "{1}" {2}' -f $ScriptPath, $StateDir, $More
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $Account
  $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Highest
  Register-ScheduledTask -TaskName $script:TbResumeTask -Action $action -Trigger $trigger -Principal $principal `
    -Description "TrialBox: go on with the install after the restart (NEW-WIN-1)" -Force | Out-Null
}
function Unregister-TbResumeTask {
  if (Get-ScheduledTask -TaskName $script:TbResumeTask -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $script:TbResumeTask -Confirm:$false
  }
}
function Register-TbBootTask([string]$Account, [string]$Distro, [string]$TaskName) {
  # one definition of the task for the installer and for a person at a terminal: register_keepalive.ps1
  & (Join-Path $PSScriptRoot "register_keepalive.ps1") -User $Account -Distro $Distro -TaskName $TaskName | Out-Null
}
function Find-TbMedia {
  # a TrialBox media at the root of a drive, or one folder below it (TRIALBOX-<version>)
  foreach ($d in @(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
    $roots = @($d.Root) + @(Get-ChildItem -LiteralPath $d.Root -Directory -Filter "TRIALBOX-*" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    foreach ($r in $roots) {
      if ((Test-Path -LiteralPath (Join-Path $r "SHA256SUMS")) -and (Test-Path -LiteralPath (Join-Path $r "windows\wsl-setup.sh"))) { return $r }
    }
  }
  return ""
}
function Get-TbBootTaskInfo([string]$TaskName) {
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($null -eq $task) { return $null }
  $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
  return @{ State = [string]$task.State; LastResult = [string]$info.LastTaskResult
    Action = ((@($task.Actions) | ForEach-Object { "{0} {1}" -f $_.Execute, $_.Arguments }) -join " ; ") + " " }
}
function Get-TbTpm {
  $t = Get-Tpm
  return @{ Present = [bool]$t.TpmPresent; Ready = [bool]$t.TpmReady }
}
function Get-TbBitLocker([string]$Drive) {
  $v = Get-BitLockerVolume -MountPoint $Drive
  return @{ Status = [string]$v.VolumeStatus; Protection = [string]$v.ProtectionStatus; AutoUnlock = [bool]$v.AutoUnlockEnabled
    Protectors = @(@($v.KeyProtector) | ForEach-Object { [string]$_.KeyProtectorType }) }
}
function Get-TbRecoveryPassword([string]$Drive) {
  # the drive's first recovery password and its protector's id (the id is not a secret: it names which key)
  $p = @((Get-BitLockerVolume -MountPoint $Drive).KeyProtector | Where-Object { [string]$_.KeyProtectorType -eq "RecoveryPassword" }) | Select-Object -First 1
  return @{ Id = [string]$p.KeyProtectorId; Password = [string]$p.RecoveryPassword }
}
function Add-TbRecoveryPassword([string]$Drive) {
  # on a drive that is not encrypted yet too: the key exists, and is in the owner's hands, before encryption starts
  Add-BitLockerKeyProtector -MountPoint $Drive -RecoveryPasswordProtector -WarningAction SilentlyContinue | Out-Null
  return (Get-TbRecoveryPassword $Drive)
}
function Enable-TbBitLockerSystem([string]$Drive) {
  # the system drive, opened by the TPM; only the space in use is encrypted first (a new machine), the rest as it fills
  Enable-BitLocker -MountPoint $Drive -TpmProtector -UsedSpaceOnly -SkipHardwareTest -WarningAction SilentlyContinue | Out-Null
}
function Enable-TbBitLockerData([string]$Drive) {
  # A data drive. Its recovery key was made and confirmed before this call. Enable-BitLocker wants a protector of
  # its own to start: it adds a second recovery password, which nobody is shown (either key opens the drive; the
  # owner holds the first). The drive is then opened with the system drive (automatic unlock).
  Enable-BitLocker -MountPoint $Drive -RecoveryPasswordProtector -UsedSpaceOnly -SkipHardwareTest -WarningAction SilentlyContinue | Out-Null
}
function Enable-TbAutoUnlock([string]$Drive) { Enable-BitLockerAutoUnlock -MountPoint $Drive | Out-Null }
function Set-TbMachineSetting([string]$Name, [string]$Value) {
  # HKLM: only an administrator writes it; deploy/windows/host_facts.ps1 reads it for the host check
  $key = "HKLM:\SOFTWARE\TrialBox"
  if (-not (Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }
  Set-ItemProperty -LiteralPath $key -Name $Name -Value $Value
}
function Send-TbToPrinter([string[]]$Lines) { $Lines | Out-Printer }
function Get-TbDefaultPrinter {
  $p = Get-CimInstance Win32_Printer -Filter "Default=TRUE" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $p) { return "" }
  return [string]$p.Name
}
function Test-TbTranscription {
  # a site policy that records every PowerShell window to a file would record a recovery key shown in this one
  $k = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription"
  $v = Get-ItemProperty -LiteralPath $k -Name EnableTranscripting -ErrorAction SilentlyContinue
  return ($null -ne $v -and [int]$v.EnableTranscripting -eq 1)
}
function Clear-TbScreen { Clear-Host }
# WSL2 with mirrored networking sits behind Windows' Hyper-V firewall. Four small seams around its cmdlets; what the
# installer does with them is Set-TbConsoleFirewall, below.
$script:TbWslVmId = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"   # the id Windows gives WSL's virtual machines (Microsoft Learn)
function Get-TbWslInboundDefault {
  $vm = Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore -Name $script:TbWslVmId -ErrorAction SilentlyContinue
  if ($null -eq $vm) { return "" }
  return [string]$vm.DefaultInboundAction
}
function Set-TbWslInboundBlock { Set-NetFirewallHyperVVMSetting -Name $script:TbWslVmId -DefaultInboundAction Block }
function Get-TbConsoleFirewallRule([string]$RuleName) {
  $r = Get-NetFirewallHyperVRule -Name $RuleName -ErrorAction SilentlyContinue
  if ($null -eq $r) { return $null }
  return @{ Enabled = [string]$r.Enabled; Direction = [string]$r.Direction; Action = [string]$r.Action; Protocol = [string]$r.Protocol
    LocalPorts = (@($r.LocalPorts) -join ","); RemoteAddresses = (@($r.RemoteAddresses) -join ","); VMCreatorId = [string]$r.VMCreatorId }
}
function Write-TbConsoleFirewallRule([string]$RuleName, [int]$Port, [bool]$Exists) {
  $p = @{ Direction = "Inbound"; VMCreatorId = $script:TbWslVmId; Protocol = "TCP"; LocalPorts = $Port; RemoteAddresses = "LocalSubnet"
    Action = "Allow"; Enabled = "True" }
  if ($Exists) { Set-NetFirewallHyperVRule -Name $RuleName @p | Out-Null }
  else { New-NetFirewallHyperVRule -Name $RuleName -DisplayName "TrialBox console (HTTPS) from the site's own network" @p | Out-Null }
}
function Set-TbConsoleFirewall([string]$RuleName, [int]$Port) {
  # Inbound to WSL stays closed by default; one rule lets the console's port in from the workstation's own subnet.
  # A rule of that name is ours: one that is wider, for another port or switched off is put right, not kept.
  # Returns "kept", "added" or "corrected".
  $before = Get-TbWslInboundDefault
  if ($before -ne "Block") {
    # machine-wide: it closes inbound traffic to every account's WSL distributions, not only the box's
    Write-TbLog ("    WSL's default for inbound traffic was '{0}': set to Block (all WSL distributions on this PC)" -f $before)
    Set-TbWslInboundBlock
    Say "wsl_inbound_blocked" @($before)
  }
  $rule = Get-TbConsoleFirewallRule $RuleName
  if ($null -eq $rule) { Write-TbConsoleFirewallRule $RuleName $Port $false; return "added" }
  $right = ($rule.Enabled -eq "True" -and $rule.Direction -eq "Inbound" -and $rule.Action -eq "Allow" -and $rule.Protocol -eq "TCP" -and
    $rule.LocalPorts -eq [string]$Port -and $rule.RemoteAddresses -eq "LocalSubnet" -and $rule.VMCreatorId -eq $script:TbWslVmId)
  if ($right) { return "kept" }
  Write-TbLog ("    rule {0} was: enabled {1}, {2} {3}, {4} ports {5}, from {6}" -f $RuleName, $rule.Enabled, $rule.Direction, $rule.Action,
    $rule.Protocol, $rule.LocalPorts, $rule.RemoteAddresses)
  Write-TbConsoleFirewallRule $RuleName $Port $true
  return "corrected"
}
# ---- Windows Update and the right to shut down (NEW-WIN-5, D-606): registry policy values and secedit, as seams
function Get-TbUpdatePolicy {
  # the Windows Update policy as it stands: values a group policy, the site's IT or an earlier run of this script wrote
  $wu = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"; $au = $wu + "\AU"
  $p = @{}
  foreach ($n in @("NoAutoUpdate", "AUOptions", "ScheduledInstallDay", "ScheduledInstallTime", "NoAutoRebootWithLoggedOnUsers",
      "AlwaysAutoRebootAtScheduledTime")) {
    try { $p[$n] = (Get-ItemProperty -LiteralPath $au -Name $n -ErrorAction Stop).$n } catch { $p[$n] = $null }
  }
  foreach ($n in @("SetActiveHours", "ActiveHoursStart", "ActiveHoursEnd", "ExcludeWUDriversInQualityUpdate", "SetComplianceDeadline",
      "ConfigureDeadlineForQualityUpdates", "ConfigureDeadlineForFeatureUpdates")) {
    try { $p[$n] = (Get-ItemProperty -LiteralPath $wu -Name $n -ErrorAction Stop).$n } catch { $p[$n] = $null }
  }
  try { $p["Ours"] = [string](Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\TrialBox" -Name "update_window" -ErrorAction Stop).update_window }
  catch { $p["Ours"] = "" }
  # a device managed by MDM (Intune) holds its Windows Update policy here, not under Policies
  try { $p["Mdm"] = (Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\PolicyManager\current\device\Update" -Name "AllowAutoUpdate" -ErrorAction Stop).AllowAutoUpdate }
  catch { $p["Mdm"] = $null }
  return $p
}
function Write-TbUpdateValue([string]$Sub, [string]$Name, [int]$Value) {
  $key = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate" + $Sub
  if (-not (Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }
  Set-ItemProperty -LiteralPath $key -Name $Name -Value $Value -Type DWord
}
function Get-TbShutdownRight {
  # who may shut this PC down: the SIDs of the user right "Shut down the system" (secedit's export), and whether
  # the sign-in screen offers shutting down to somebody who has not signed in. secedit works on files: they are
  # kept in the install's own folder (administrators only) under fixed names, and hold no secret
  $f = Join-Path $script:TbStateDir "rights-now.inf"
  $sids = @()
  & secedit.exe /export /cfg $f /areas USER_RIGHTS | Out-Null
  if ($LASTEXITCODE -ne 0) { throw ("secedit /export ended with code " + $LASTEXITCODE) }
  $line = Get-Content -LiteralPath $f | Where-Object { $_ -match "^SeShutdownPrivilege\s*=" } | Select-Object -First 1
  if ($line) { $sids = @(($line -split "=", 2)[1].Split(",") | ForEach-Object { $_.Trim().TrimStart("*") } | Where-Object { $_ }) }
  $at = 1
  try { $at = [int](Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "ShutdownWithoutLogon" -ErrorAction Stop).ShutdownWithoutLogon }
  catch { $at = 1 }
  return @{ Sids = $sids; AtSignIn = ($at -ne 0) }
}
function Write-TbShutdownRight([string]$Sid) {
  $inf = Join-Path $script:TbStateDir "rights-set.inf"
  $lines = @("[Unicode]", "Unicode=yes", "[Version]", 'signature="$CHICAGO$"', "Revision=1", "[Privilege Rights]", ("SeShutdownPrivilege = *" + $Sid))
  Set-Content -LiteralPath $inf -Value $lines -Encoding Unicode
  & secedit.exe /configure /db (Join-Path $script:TbStateDir "rights-set.sdb") /cfg $inf /areas USER_RIGHTS | Out-Null
  if ($LASTEXITCODE -ne 0) { throw ("secedit /configure ended with code " + $LASTEXITCODE) }
  Set-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "ShutdownWithoutLogon" -Value 0 -Type DWord
}
function Get-TbOwnDrives {
  # NEW-WIN-7 (D-608): the letters of this PC's own drives: every fixed drive Windows lists, less those on a disk
  # attached by USB. A letter Windows cannot place on a disk is the PC's own (the strict side). An error is the
  # caller's: nothing is recorded then.
  $usb = @()
  foreach ($d in @(Get-Disk | Where-Object { $_.BusType -eq "USB" })) {
    foreach ($p in @(Get-Partition -DiskNumber $d.Number | Where-Object { $_.DriveLetter })) { $usb += ([string]$p.DriveLetter).ToUpper() }
  }
  $out = @()
  foreach ($ld in @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3")) {
    $l = ([string]$ld.DeviceID).Substring(0, 1).ToUpper()
    if ($usb -notcontains $l) { $out += $l }
  }
  return $out
}
function Get-TbDriveBus([string]$Letter) { return [string]((Get-Partition -DriveLetter $Letter | Get-Disk).BusType) }
function Write-TbOutsideMark([string]$Letter, [string[]]$Lines) {
  # one small file at the root of the outside drive: the backup check inside WSL2 looks for it (D-608)
  Set-Content -LiteralPath ($Letter + ":\.trialbox-outside-drive") -Value $Lines -Encoding ASCII
}
# ---- the console on Windows 10 (NEW-WIN-10, D-613): a Windows Firewall rule, the forwarding task and its script
function Get-TbHostFirewallRule([string]$RuleName) {
  $r = Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
  if ($null -eq $r) { return $null }
  $port = $r | Get-NetFirewallPortFilter; $addr = $r | Get-NetFirewallAddressFilter
  return @{ Enabled = [string]$r.Enabled; Direction = [string]$r.Direction; Action = [string]$r.Action; Profile = [string]$r.Profile
    Protocol = [string]$port.Protocol; LocalPort = (@($port.LocalPort) -join ","); RemoteAddress = (@($addr.RemoteAddress) -join ",") }
}
function Write-TbHostFirewallRule([string]$RuleName, [int]$Port, [bool]$Exists) {
  $p = @{ Direction = "Inbound"; Protocol = "TCP"; LocalPort = $Port; RemoteAddress = "LocalSubnet"; Profile = @("Domain", "Private")
    Action = "Allow"; Enabled = "True" }
  if ($Exists) { Set-NetFirewallRule -Name $RuleName @p | Out-Null }
  else { New-NetFirewallRule -Name $RuleName -DisplayName "TrialBox console (HTTPS) from the site's own network" @p | Out-Null }
}
function Get-TbProxyTaskInfo([string]$TaskName) {
  $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($null -eq $t) { return $null }
  return @{ State = [string]$t.State; Action = ((@($t.Actions) | ForEach-Object { "{0} {1}" -f $_.Execute, $_.Arguments }) -join " ; ") }
}
function Register-TbProxyTask([string]$Account, [string]$Script, [string]$Distro, [int]$Port, [int]$EveryMinutes, [string]$TaskName) {
  # the forwarding script registers its own task (one definition, as register_keepalive.ps1 for the boot task)
  & $Script -Register -User $Account -Distro $Distro -Port $Port -EveryMinutes $EveryMinutes -TaskName $TaskName | Out-Null
}
function Get-TbIpHelper {
  # Windows' IP Helper service serves the port proxy: without it a rule is written and nothing listens
  $svc = Get-Service -Name "iphlpsvc" -ErrorAction SilentlyContinue
  if ($null -eq $svc) { return $null }
  return @{ Status = [string]$svc.Status; StartType = [string]$svc.StartType }
}
function Set-TbIpHelperOn {
  Set-Service -Name "iphlpsvc" -StartupType Automatic
  Start-Service -Name "iphlpsvc"
}
function Get-TbProxyRowTarget([int]$Port) {
  # the port proxy's row for 0.0.0.0:<port>, read only (console-proxy.ps1 reads the same table)
  foreach ($line in @(& netsh.exe interface portproxy show v4tov4 2>$null)) {
    if ([string]$line -match "^\s*0\.0\.0\.0\s+(\d+)\s+(\S+)\s+\d+\s*$" -and [int]$Matches[1] -eq $Port) { return $Matches[2] }
  }
  return ""
}
function Remove-TbProxyRow([int]$Port) {
  & netsh.exe interface portproxy delete v4tov4 ("listenport={0}" -f $Port) "listenaddress=0.0.0.0" | Out-Null
}
function Unregister-TbProxyTask([string]$TaskName) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
function Remove-TbHostFirewallRule([string]$RuleName) { Remove-NetFirewallRule -Name $RuleName }
function Invoke-TbConsoleProxy([string]$Script, [string]$Distro, [int]$Port) {
  # the forwarding script run once, now; its own output says what it did
  $out = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -Distro $Distro -Port $Port 2>&1)
  $line = [string]($out | Where-Object { $_ -like "status=*" } | Select-Object -Last 1)
  if ($line -match "^status=(\S+) address=(\S*)") { return @{ Status = $Matches[1]; Address = $Matches[2] } }
  return @{ Status = "refused"; Address = "" }
}
function Restart-TbComputer { Restart-Computer -Force }
function Start-TbSleep([int]$Seconds) { Start-Sleep -Seconds $Seconds }
function Read-TbLine([string]$Prompt) { return (Read-Host $Prompt) }
function Write-TbScreen([string]$Text) { Write-Host $Text }
function Invoke-TbNative([string]$Exe, [string[]]$Arguments) {
  # a program's exit code and its output as lines; wsl.exe prints UTF-16 unless WSL_UTF8 is set
  $ErrorActionPreference = "Continue"
  $old = $env:WSL_UTF8; $env:WSL_UTF8 = "1"
  try {
    $out = @(& $Exe @Arguments 2>&1 | ForEach-Object { ([string]$_) -replace "`0", "" })
    $code = $LASTEXITCODE
  } catch [System.Management.Automation.CommandNotFoundException] {
    $out = @(); $code = -1
  } finally { $env:WSL_UTF8 = $old }
  return @{ ExitCode = [int]$code; Output = $out }
}
function Invoke-TbNativeConsole([string]$Exe, [string[]]$Arguments) {
  # A program that owns this window (the Linux installer: its questions and the first-run code). The process gets
  # the console itself: PowerShell never reads its output, so nothing is captured, held back or logged (a plain
  # "& program" inside a function would collect the output as the function's result).
  $quoted = @($Arguments | ForEach-Object {
      if ($_ -ne "" -and $_ -notmatch '[\s"]') { $_ }
      else { '"' + (($_ -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' }
    })
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $Exe
  $psi.Arguments = ($quoted -join " ")
  $psi.UseShellExecute = $false
  $p = [System.Diagnostics.Process]::Start($psi)
  $p.WaitForExit()
  return [int]$p.ExitCode
}

# ------------------------------------------------------------------------------------------------ small pieces
function ConvertTo-TbWslPath([string]$Path) {
  $p = $Path -replace "\\", "/"
  if ($p -match "^([A-Za-z]):(/.*)?$") { return ("/mnt/" + $Matches[1].ToLower() + $Matches[2]) }
  return $p
}
function Get-TbLang([string]$Asked, [string]$UiCulture) {
  if ($Asked) { return $Asked }
  if ($UiCulture -like "ja*") { return "ja" }
  if ($UiCulture -like "zh-TW*" -or $UiCulture -like "zh-Hant*" -or $UiCulture -like "zh-HK*" -or $UiCulture -like "zh-MO*") { return "zh-TW" }
  return "en"
}
function Get-TbWslConfigText([int]$MemoryGB, [int]$Processors, [int]$SharePercent, [long]$DiskBytes, [bool]$Mirrored = $true) {
  # .wslconfig from the hardware (D-601): WSL2 gets what the desktop's share leaves, rounded down to whole units.
  # Nothing here is a constant of ours: two readings of the machine and one declared setting.
  $mem = [int][math]::Floor($MemoryGB * (100 - $SharePercent) / 100)
  $cpu = [int][math]::Floor($Processors * (100 - $SharePercent) / 100)
  if ($mem -lt 1 -or $cpu -lt 1) { return $null }
  $lines = @(
    "# TrialBox: written by box-install.ps1 from this machine's hardware (NEW-WIN-3, D-601). Run the installer",
    ("# again after a hardware change. Installed: {0} GB, {1} logical processors; {2} percent kept for the desktop." -f $MemoryGB, $Processors, $SharePercent),
    "[wsl2]", ("memory={0}GB" -f $mem), ("processors={0}" -f $cpu),
    "# no swap: patient data never pages to a disk file (D-421)", "swap=0")
  if ($Mirrored) { $lines += @("# the workstation's own network address is WSL2's (NEW-WIN-4, D-604)", "networkingMode=mirrored") }
  else {
    # Windows 10 has no mirrored networking: the console's port is forwarded by the port proxy, which also answers
    # on this PC's own name; WSL2's own forwarding of localhost would take the same port first (NEW-WIN-10, D-613)
    $lines += @("# the console is forwarded to WSL2 by the port proxy (NEW-WIN-10, D-613)", "localhostForwarding=false")
  }
  if ($DiskBytes -gt 0) { $lines += @("# the virtual disk may grow to the data drive's size", ("defaultVhdSize={0}" -f $DiskBytes)) }
  $lines += @("[experimental]", "# the disk file gives back freed space (D-421)", "sparseVhd=true", "")
  return ($lines -join "`r`n")
}
function Get-TbText([string]$Key, [object[]]$Values, [string]$Language) {
  $entry = $script:TbMessages.$Key
  if ($null -eq $entry) { return ("{0} {1}" -f $Key, ($Values -join " ")) }
  $fmt = [string]$entry.$Language
  if (-not $fmt) { $fmt = [string]$entry.en }
  return ($fmt -f (@($Values) + @("", "", "")))  # a value that is missing prints as nothing, never as an error
}
function Write-TbLog([string]$Text) {
  $line = "{0} {1}" -f ([DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")), $Text
  [IO.File]::AppendAllText($script:TbLogPath, $line + "`r`n", (New-Object Text.UTF8Encoding $false))
}
function Say([string]$Key, [object[]]$Values) {
  Write-TbScreen (Get-TbText $Key $Values $script:TbLang)
  Write-TbLog ("say: " + (Get-TbText $Key $Values "en"))
}
function Stop-TbStep([string]$Key, [object[]]$Values) {
  $script:TbStop = @{ Key = $Key; Values = $Values }
  throw ("TBSTOP " + $Key)
}
function Save-TbState {
  $json = $script:TbState | ConvertTo-Json
  [IO.File]::WriteAllText($script:TbStatePath, $json, (New-Object Text.UTF8Encoding $false))
}
function Read-TbState {
  $s = @{ version = 1; account = ""; media_root = ""; data_drive = ""; distro = ""; imported = $false; import_started = $false
    desktop_share_pct = -1; update_window = ""; update_window_told = ""; drives_told = ""; recovery_confirmed = ""; bitlocker_unlock = ""; bitlocker_turned_on = ""
    restart_pending = $false; finished = $false; rehearsal = $false }
  if (Test-Path -LiteralPath $script:TbStatePath) {
    $j = Get-Content -LiteralPath $script:TbStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($k in @($s.Keys)) { if ($null -ne $j.$k) { $s[$k] = $j.$k } }
  }
  return $s
}
function Find-TbOne([string]$Dir, [string]$Filter, [string]$Not) {
  $found = @(Get-ChildItem -LiteralPath $Dir -Filter $Filter -File -ErrorAction SilentlyContinue |
      Where-Object { -not $Not -or $_.Name -ne $Not })
  if ($found.Count -ne 1) { Stop-TbStep "media_file" @((Join-Path $Dir $Filter), $found.Count) }
  return $found[0].FullName
}
function Invoke-TbSetup([string]$Step, [string[]]$More) {
  # one step of wsl-setup.sh as root inside the distribution; its output goes to the log
  $a = @("-d", $script:TbState.distro, "-u", "root", "--cd", "/", "--exec", "bash", $script:TbSetupWsl, $Step) + @($More)
  $r = Invoke-TbNative "wsl.exe" $a
  foreach ($ln in $r.Output) { Write-TbLog ("    " + $ln) }
  return $r
}
function Assert-TbSetup([string]$Step, [string[]]$More) {
  $r = Invoke-TbSetup $Step $More
  if ($r.ExitCode -ne 0) { Stop-TbStep "linux_step" @($Step, (@($r.Output) | Select-Object -Last 1)) }
  return $r
}

# ------------------------------------------------------------------------------------------------ the steps
function Step-Media {
  $m = $script:TbState.media_root
  if (-not (Test-Path -LiteralPath (Join-Path $m "SHA256SUMS"))) { Stop-TbStep "media_missing" @($m) }
  $win = Join-Path $m "windows"; $lin = Join-Path $m "linux"
  $script:TbFiles = @{
    Msi = Find-TbOne (Join-Path $win "wsl") "wsl.*.msi" ""
    RootFs = Find-TbOne (Join-Path $win "wsl") "ubuntu-24.04*.tar.gz" ""
    Setup = Find-TbOne $win "wsl-setup.sh" ""
    HostTar = Find-TbOne $lin "trialbox-host.tar" ""
    Bundle = Find-TbOne $lin "trialbox-*.tar" "trialbox-host.tar"
    PubKey = Find-TbOne $lin "vendor_ed25519.pub" ""
    Debs = Join-Path $lin "debs"
  }
  if (@(Get-ChildItem -LiteralPath $script:TbFiles.Debs -Filter *.deb -File -ErrorAction SilentlyContinue).Count -eq 0) {
    Stop-TbStep "media_file" @((Join-Path $script:TbFiles.Debs "*.deb"), 0)
  }
  Say "media_checking" @($m)
  $sums = @{}
  foreach ($ln in Get-Content -LiteralPath (Join-Path $m "SHA256SUMS") -Encoding UTF8) {
    if ($ln -match "^([0-9a-fA-F]{64})\s+\*?(.+)$") { $sums[($Matches[2].Trim() -replace "\\", "/")] = $Matches[1].ToLower() }
  }
  $check = @($script:TbFiles.Msi, $script:TbFiles.RootFs, $script:TbFiles.Setup, $script:TbFiles.HostTar,
    $script:TbFiles.Bundle, $script:TbFiles.PubKey, (Find-TbOne $win "register_keepalive.ps1" ""))
  $check += @(Get-ChildItem -LiteralPath $script:TbFiles.Debs -Filter *.deb -File | ForEach-Object { $_.FullName })
  if (-not (Test-TbMsiSignature $script:TbFiles.Msi)) { Stop-TbStep "msi_unsigned" @($script:TbFiles.Msi) }
  $rootLen = $m.TrimEnd("\", "/").Length + 1
  foreach ($f in $check) {
    $rel = $f.Substring($rootLen) -replace "\\", "/"
    if (-not $sums.ContainsKey($rel)) { Stop-TbStep "media_unlisted" @($rel) }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $f).Hash.ToLower() -ne $sums[$rel]) { Stop-TbStep "media_damaged" @($rel) }
  }
}
function Step-Windows {
  $f = $script:TbFacts
  if (-not $f.IsAdmin) { Stop-TbStep "not_admin" @() }
  if ($script:TbState.account -and $script:TbState.account -ne $f.Account) { Stop-TbStep "other_account" @($script:TbState.account, $f.Account) }
  if ($script:TbEditions -notcontains $f.EditionId) { Stop-TbStep "edition" @($f.EditionId, $f.Build) }
  if ($f.Build -lt $MinWindowsBuild) { Stop-TbStep "windows_too_old" @($f.Build, $MinWindowsBuild) }
  if (-not ($f.VirtualizationFirmware -or $f.HypervisorPresent)) { Stop-TbStep "virtualisation" @() }
  $script:TbState.account = $f.Account
}
function Step-GpuDriver {
  $r = Invoke-TbNative "nvidia-smi.exe" @("--query-gpu=name,driver_version,memory.total", "--format=csv,noheader")
  $card = @($r.Output) | Select-Object -First 1
  if ($r.ExitCode -ne 0 -or -not $card) { Stop-TbStep "no_windows_driver" @() }
  Say "card" @($card)
}
function Step-Drive {
  $d = $script:TbState.data_drive
  if (-not $d) {
    $mediaDrive = ""; if ($script:TbState.media_root -match "^([A-Za-z]:)") { $mediaDrive = $Matches[1].ToUpper() }
    $cands = @(Get-TbDataDriveCandidates @($script:TbFacts.SystemDrive.ToUpper(), $mediaDrive))
    if ($cands.Count -eq 1) { $d = $cands[0] }
    elseif ($Yes) { Stop-TbStep "drive_unclear" @(($cands -join ", ")) }
    else {
      Say "drive_ask" @(($cands -join ", "), $script:TbFacts.SystemDrive)
      $d = ([string](Read-TbLine ">")).Trim().TrimEnd("\")
      if ($d -match "^[A-Za-z]$") { $d = $d + ":" }
      if ($d -notmatch "^[A-Za-z]:$") { Stop-TbStep "drive_bad" @($d) }
    }
    if ($d -match "^[A-Za-z]:$") { $d = $d.ToUpper() }
  }
  $facts = Get-TbDriveFacts $d
  if ($null -eq $facts -or -not $facts.Fixed -or $facts.FileSystem -ne "NTFS") { Stop-TbStep "drive_bad" @($d) }
  if ($facts.FreeGB -lt $MinFreeGB -and -not $script:TbState.imported) { Stop-TbStep "drive_small" @($d, $facts.FreeGB, $MinFreeGB) }
  $script:TbState.data_drive = $d
  $script:TbDataDriveBytes = [long]$facts.SizeBytes
  $base = $d; if ($base -match "^[A-Za-z]:$") { $base = $base + "\" }
  $script:TbDataRoot = Join-Path $base "TrialBox"
  try { Protect-TbDirectory $script:TbDataRoot $script:TbFacts.Account }
  catch { if ([string]$_.Exception.Message -like "TBOWNER*") { Stop-TbStep "folder_not_ours" @($script:TbDataRoot) } else { throw } }
  Say "drive" @($script:TbDataRoot, $facts.FreeGB)
  Set-TbBitLocker   # before any data is put on the drive
}
function Confirm-TbRecoveryKey([string]$Drive, [string]$secret) {
  # The recovery key goes to the window, and to the printer when the owner says so. It is never written to the
  # log, the state or any file. The owner types its last six digits back, then the window is cleared.
  if ($secret -notmatch "^(\d{6}-){7}\d{6}$") { Stop-TbStep "recovery_unreadable" @($Drive) }
  if (Test-TbTranscription) { Stop-TbStep "transcription_on" @($Drive) }
  Write-TbScreen (Get-TbText "recovery_show" @($Drive) $script:TbLang)
  Write-TbScreen ("        " + $secret)
  $printer = Get-TbDefaultPrinter
  if ($printer -and ([string](Read-TbLine (Get-TbText "recovery_print_ask" @($printer) $script:TbLang))).Trim() -match "^(y|yes)$") {
    try {
      Send-TbToPrinter @((Get-TbText "recovery_show" @($Drive) $script:TbLang), "", ("    " + $secret))
      Say "recovery_printed" @($printer)
    } catch { Say "recovery_print_failed" @([string]$_.Exception.Message) }
  }
  $want = ($secret -replace "[^0-9]", "")
  $want = $want.Substring($want.Length - 6)
  while ($true) {
    $typed = ([string](Read-TbLine (Get-TbText "recovery_confirm" @() $script:TbLang))) -replace "[^0-9]", ""
    if ($typed -eq "") { Stop-TbStep "recovery_needs_person" @($Drive) }
    if ($typed -eq $want) { break }
    Write-TbScreen (Get-TbText "recovery_wrong" @() $script:TbLang)
  }
  Clear-TbScreen   # the key does not stay in a window on a desktop that staff share
  Write-TbLog ("    recovery key of {0}: shown, confirmed by the owner (its last six digits typed back), the window cleared" -f $Drive)
}
function Set-TbBitLocker {
  # NEW-WIN-8 (D-603): BitLocker on the system drive and the data drive, opened by the TPM. The order per drive is
  # the one Windows' own wizard keeps: the recovery key exists and is in the owner's hands BEFORE the drive is
  # encrypted. A drive that is already encrypted is kept as it is; nothing is ever decrypted or weakened.
  if ($SkipBitLocker) { Say "bitlocker_skipped" @(); return }
  $unlock = $script:TbUnlock
  $sys = $script:TbFacts.SystemDrive.ToUpper()
  $data = [string]$script:TbState.data_drive
  if ($data -match "^([A-Za-z]:)") { $data = $Matches[1].ToUpper() }
  $drives = @($sys); if ($data -ne $sys) { $drives += $data }
  $tpm = Get-TbTpm
  if (-not ($tpm.Present -and $tpm.Ready)) { Stop-TbStep "no_tpm" @() }
  foreach ($drv in $drives) {
    $b = Get-TbBitLocker $drv
    # being decrypted, paused, or encrypted with its protection suspended: not ours to change
    if ($b.Status -like "Decryption*" -or $b.Status -like "*Suspended" -or $b.Status -like "*Paused" -or
      ($b.Status -like "FullyEncrypted*" -and $b.Protection -ne "On")) { Stop-TbStep "bitlocker_suspended" @($drv, $b.Status) }
    $off = ($b.Status -eq "FullyDecrypted")
    if ($off -and $Yes) { Stop-TbStep "recovery_needs_person" @($drv) }   # a new key needs a person to receive it
    # 1. the recovery key: made when there is none, and confirmed unless this very key was confirmed before
    $rp = $null
    if ($b.Protectors -notcontains "RecoveryPassword") {
      if ($Yes) { Stop-TbStep "recovery_needs_person" @($drv) }
      $rp = Add-TbRecoveryPassword $drv
    }
    if ($Yes) { Say "recovery_unconfirmed" @($drv) }
    else {
      if ($null -eq $rp) { $rp = Get-TbRecoveryPassword $drv }
      $known = @(([string]$script:TbState.recovery_confirmed) -split "," | Where-Object { $_ })
      $mark = $drv + "=" + $rp.Id
      if ($known -notcontains $mark) {
        Confirm-TbRecoveryKey $drv $rp.Password
        $script:TbState.recovery_confirmed = ((@($known | Where-Object { $_ -notlike ($drv + "=*") }) + $mark) -join ",")
        Save-TbState
      }
    }
    $rp = $null
    # 2. only now the encryption
    if ($off) {
      Write-TbLog ("    turning BitLocker on for " + $drv)
      $script:TbState.bitlocker_turned_on = ((@(([string]$script:TbState.bitlocker_turned_on) -split "," | Where-Object { $_ -and $_ -ne $drv }) + $drv) -join ",")
      Save-TbState
      if ($drv -eq $sys) { Enable-TbBitLockerSystem $drv } else { Enable-TbBitLockerData $drv }
      $b = Get-TbBitLocker $drv
    }
    # 3. how it opens
    if ($drv -eq $sys) {
      $alone = @($b.Protectors | Where-Object { $_ -eq "Tpm" -or $_ -eq "TpmNetworkKey" }).Count -gt 0
      $pin = @($b.Protectors | Where-Object { $_ -like "TpmPin*" }).Count -gt 0
      if ($unlock -eq "tpm" -and -not $alone) { Stop-TbStep "no_tpm_protector" @($drv, ($b.Protectors -join ",")) }
      if ($unlock -eq "tpm_pin" -and -not $pin) { Stop-TbStep "tpm_pin_missing" @($drv) }
    } elseif (-not $b.AutoUnlock) {
      Write-TbLog ("    automatic unlock for " + $drv)
      try { Enable-TbAutoUnlock $drv }
      catch { Stop-TbStep "autounlock_failed" @($drv, [string]$_.Exception.Message) }
    }
    Say "bitlocker_on" @($drv)
  }
  Set-TbMachineSetting "BitlockerUnlock" $unlock
  Set-TbMachineSetting "RecoveryKeyKeptBy" "the box owner (each key shown and confirmed at the install)"
  Say "bitlocker_unlock" @($unlock)
}
function Step-WslEnable {
  $restart = $false
  foreach ($name in $script:TbFeatures) {
    if (-not (Get-TbFeatureEnabled $name)) {
      Write-TbLog ("    enabling Windows feature " + $name)
      if (Enable-TbFeature $name) { $restart = $true }
    }
  }
  if ((Invoke-TbNative "wsl.exe" @("--version")).ExitCode -ne 0) {
    $r = Invoke-TbNative "msiexec.exe" @("/i", $script:TbFiles.Msi, "/qn", "/norestart")
    Write-TbLog ("    msiexec exit " + $r.ExitCode)
    if ($r.ExitCode -eq $script:TbRestartExit) { $restart = $true }
    elseif ($r.ExitCode -ne 0) { Stop-TbStep "msi_failed" @($r.ExitCode) }
  }
  if ($restart) {
    # the copy the task runs must not depend on the media's drive letter after the restart
    $copy = Join-Path $script:TbStateDir "scripts"
    Protect-TbDirectory $copy $script:TbFacts.Account
    foreach ($n in @("box-install.ps1", "box-install.messages.json", "register_keepalive.ps1", "console-proxy.ps1")) {
      $from = Join-Path $script:TbHere $n; $to = Join-Path $copy $n
      if ($from -ne $to) { Copy-Item -LiteralPath $from -Destination $to -Force }  # the copy itself asked again
    }
    # the run after the restart gets this run's settings (all checked: figures, a language of the list, a name)
    $more = "-MinFreeGB {0} -MinWindowsBuild {1} -ProxyEveryMinutes {9} -StartWaitSeconds {2} -DesktopSharePercent {3} -UpdateWindowStart {7} -UpdateWindowHours {8} -Distro {4} -Lang {5} -BitLockerUnlock {6}" -f $MinFreeGB,
      $MinWindowsBuild, $StartWaitSeconds, $script:TbShare, $script:TbState.distro, $script:TbLang, $script:TbUnlock, $script:TbUpdate[0], $script:TbUpdate[1], $ProxyEveryMinutes
    if ($SkipBitLocker) { $more += " -SkipBitLocker" }
    if ($script:TbState.rehearsal) { $more += " -Rehearsal" }  # D-614: the run after the restart is asked for it again
    Register-TbResumeTask (Join-Path $copy "box-install.ps1") $script:TbFacts.Account $script:TbStateDir $more
    $script:TbState.restart_pending = $true
    Save-TbState
    Say "restart" @($script:TbFacts.Account)
    if (-not $Yes) { [void](Read-TbLine (Get-TbText "press_enter" @() $script:TbLang)) }
    Write-TbLog "restarting Windows"
    Restart-TbComputer
    return "restart"
  }
  if ((Invoke-TbNative "wsl.exe" @("--version")).ExitCode -ne 0) { Stop-TbStep "wsl_not_ready" @() }
  Unregister-TbResumeTask
  $script:TbState.restart_pending = $false
  [void](Invoke-TbNative "wsl.exe" @("--set-default-version", "2"))
}
function Step-WslConfig {
  # Returns "kept" (the account's own file), "same" (ours, nothing to change) or "written".
  $path = Join-Path $script:TbFacts.UserProfile ".wslconfig"
  $old = ""
  if (Test-Path -LiteralPath $path) {
    $bytes = [IO.File]::ReadAllBytes($path)
    $text = [Text.Encoding]::ASCII.GetString($bytes)
    if ($text.Trim().Length -gt 0) {   # an empty file is nobody's settings: it is written like a missing one
      # ours is plain ASCII and starts with "# TrialBox"; a file in another encoding, or with another start, is
      # the account's own and is kept as it is
      $plain = @($bytes | Where-Object { $_ -eq 0 -or $_ -gt 127 }).Count -eq 0
      if (-not ($plain -and $text.StartsWith("# TrialBox"))) {
        $swap0 = $text -match "(?im)^\s*swap\s*=\s*0\s*$"
        if ((Get-TbNetForm) -eq "proxy") {
          # Windows 10 (D-613): WSL2's own localhost forwarding would take port 443 before the port proxy
          if ($swap0 -and $text -match "(?im)^\s*localhostForwarding\s*=\s*false\s*$") { Say "wslconfig_kept_proxy" @($path) }
          else { Say "wslconfig_kept_proxy_missing" @($path) }
        } elseif (-not $swap0) { Say "wslconfig_kept_no_swap0" @($path) } else { Say "wslconfig_kept" @($path) }
        return "kept"
      }
      $old = $text
    }
  }
  $hw = Get-TbHardware
  $new = Get-TbWslConfigText $hw.MemoryGB $hw.Processors $script:TbShare $script:TbDataDriveBytes ((Get-TbNetForm) -eq "mirrored")
  if ($null -eq $new) { Stop-TbStep "wslconfig_too_small" @($hw.MemoryGB, $hw.Processors, $script:TbShare) }
  if ($old -eq $new) { Write-TbLog ("    " + $path + " is as computed: not written"); return "same" }
  $backup = ""
  if ($old) {  # also a file somebody tuned by hand under our first line: a copy stays beside it
    $backup = $path + ".before-trialbox-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    Copy-Item -LiteralPath $path -Destination $backup
  }
  if (-not (Test-Path -LiteralPath $script:TbFacts.UserProfile)) { [void](New-Item -ItemType Directory -Force -Path $script:TbFacts.UserProfile) }
  [IO.File]::WriteAllText($path, $new, (New-Object Text.ASCIIEncoding))
  $m = [regex]::Match($new, "memory=(\d+)GB"); $c = [regex]::Match($new, "processors=(\d+)")
  Say "wslconfig_written" @($m.Groups[1].Value, $c.Groups[1].Value, $script:TbShare)
  if ($backup) { Say "wslconfig_replaced" @($backup) }
  return "written"
}
function Step-Import {
  $name = $script:TbState.distro
  $dir = Join-Path $script:TbDataRoot "wsl"
  $r = Invoke-TbNative "wsl.exe" @("--list", "--quiet")
  $have = @($r.Output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ -eq $name }).Count -gt 0
  # import_started is saved before the import, when neither the name nor a virtual disk was there: what is found
  # after that is this install's own, also when the window was closed while the import ran
  if ($have) {
    if (-not ($script:TbState.imported -or $script:TbState.import_started)) { Stop-TbStep "distro_exists" @($name) }
    Write-TbLog ("    " + $name + " was imported by this install: kept")
    $script:TbState.imported = $true
    return
  }
  if (Test-Path -LiteralPath (Join-Path $dir "ext4.vhdx")) {
    if ($script:TbState.import_started) { Stop-TbStep "import_interrupted" @((Join-Path $dir "ext4.vhdx")) }
    Stop-TbStep "vhdx_exists" @((Join-Path $dir "ext4.vhdx"))
  }
  Protect-TbDirectory $dir $script:TbFacts.Account
  $script:TbState.import_started = $true
  Save-TbState
  Say "importing" @($name, $dir)
  $r = Invoke-TbNative "wsl.exe" @("--import", $name, $dir, $script:TbFiles.RootFs, "--version", "2")
  foreach ($ln in $r.Output) { Write-TbLog ("    " + $ln) }
  if ($r.ExitCode -ne 0) { Stop-TbStep "import_failed" @($r.ExitCode, (@($r.Output) | Select-Object -Last 1)) }
  $script:TbState.imported = $true
  Save-TbState
}
function Copy-TbStaging {
  # the scripts and small files WSL2 reads, on the data drive (a fixed drive is always mounted in WSL2; the media
  # may be a USB disk that is not). The shell script is written with Unix line ends whatever the media's copy has.
  $stage = Join-Path $script:TbDataRoot "install"
  Protect-TbDirectory $stage $script:TbFacts.Account
  $text = [IO.File]::ReadAllText($script:TbFiles.Setup) -replace "`r`n", "`n"
  [IO.File]::WriteAllText((Join-Path $stage "wsl-setup.sh"), $text, (New-Object Text.UTF8Encoding $false))
  $debs = Join-Path $stage "debs"
  Protect-TbDirectory $debs $script:TbFacts.Account
  foreach ($f in Get-ChildItem -LiteralPath $script:TbFiles.Debs -Filter *.deb -File) { Copy-Item -LiteralPath $f.FullName -Destination $debs -Force }
  Copy-Item -LiteralPath $script:TbFiles.HostTar -Destination $stage -Force
  Copy-Item -LiteralPath $script:TbFiles.PubKey -Destination $stage -Force
  $script:TbStage = $stage
  $script:TbSetupWsl = ConvertTo-TbWslPath (Join-Path $stage "wsl-setup.sh")
}
function Step-Systemd {
  Copy-TbStaging
  $r = Assert-TbSetup "wslconf" @()
  if (@($r.Output) -contains "changed") {
    [void](Invoke-TbNative "wsl.exe" @("--terminate", $script:TbState.distro))
  }
  $waited = 0; $pause = 5  # how often to look, not a limit: the limit is -StartWaitSeconds
  while ($true) {
    $r = Invoke-TbSetup "pid1" @()
    if ($r.ExitCode -eq 0 -and (@($r.Output) | Select-Object -Last 1) -eq "systemd") { return }
    if ($waited -ge $StartWaitSeconds) { Stop-TbStep "no_systemd" @((@($r.Output) | Select-Object -Last 1)) }
    Start-TbSleep $pause; $waited += $pause
  }
}
function Step-Packages {
  [void](Assert-TbSetup "no-linux-driver" @())
  Say "packages" @()
  [void](Assert-TbSetup "packages" @((ConvertTo-TbWslPath (Join-Path $script:TbStage "debs"))))
  [void](Assert-TbSetup "no-linux-driver" @())
}
function Step-GpuContainer {
  $r = Assert-TbSetup "gpu" @()
  Say "gpu_container" @((@($r.Output) | Select-Object -Last 1))
}
function Step-HostTree {
  $r = Assert-TbSetup "host-tree" @((ConvertTo-TbWslPath (Join-Path $script:TbStage "trialbox-host.tar")),
    (ConvertTo-TbWslPath (Join-Path $script:TbStage "vendor_ed25519.pub")))
  foreach ($ln in @($r.Output | Where-Object { $_ -like "vendor key*" })) { Say "vendor_key" @($ln) }
}
function Set-TbBootTask {
  # The task is registered once. One that is there and starts this distribution is kept as it is: registering it
  # again would start it again beside a live keep-alive. Returns "kept", "registered" or "restored".
  $info = Get-TbBootTaskInfo $script:TbBootTask
  $wanted = "-d " + $script:TbState.distro + " "
  if ($null -ne $info -and $info.State -ne "Disabled" -and ([string]$info.Action).Contains($wanted)) { return "kept" }
  Register-TbBootTask $script:TbFacts.Account $script:TbState.distro $script:TbBootTask
  if ($null -eq $info) { return "registered" } else { return "restored" }
}
function Set-TbUpdateWindow([int]$Start, [int]$Hours) {
  # Windows Update installs at the window's first hour, and restarts by itself only inside the window: the hours
  # outside it are Windows' "active hours". Drivers are never taken from Windows Update: the NVIDIA driver is the
  # one the serving record was measured with. A policy that is there and that this script did not write is the
  # site's IT's: it is kept, and the host check judges it. Returns "kept", "same" or "written".
  $p = Get-TbUpdatePolicy
  $end = ($Start + $Hours) % 24
  if ([string]$p.ExcludeWUDriversInQualityUpdate -ne "1") {
    Write-TbUpdateValue "" "ExcludeWUDriversInQualityUpdate" 1
    Write-TbLog "    Windows Update: drivers excluded (ExcludeWUDriversInQualityUpdate=1)"
  }
  $names = @("NoAutoUpdate", "AUOptions", "ScheduledInstallDay", "ScheduledInstallTime", "SetActiveHours", "ActiveHoursStart", "ActiveHoursEnd")
  $ours = [bool]$p.Ours
  if (-not $ours) {
    # values that are exactly a window as this script writes one are ours, also when its own note was deleted
    $ours = ([string]$p.AUOptions -eq "4" -and [string]$p.NoAutoUpdate -eq "0" -and [string]$p.ScheduledInstallDay -eq "0" -and
      [string]$p.SetActiveHours -eq "1" -and [string]$p.ScheduledInstallTime -match "^\d+$" -and [string]$p.ActiveHoursStart -match "^\d+$" -and
      [string]$p.ScheduledInstallTime -eq [string]$p.ActiveHoursEnd)
  }
  $foreign = @($script:TbUpdateForeign | Where-Object { $null -ne $p[$_] })
  $set = @($names | Where-Object { $null -ne $p[$_] })
  if ($foreign.Count -gt 0 -or (-not $ours -and $set.Count -gt 0)) {
    Write-TbLog ("    Windows Update: a policy is already set ({0}): kept" -f ((@($set) + @($foreign) | ForEach-Object { "{0}={1}" -f $_, $p[$_] }) -join ", "))
    return "kept"
  }
  $want = @(@("\AU", "NoAutoUpdate", 0), @("\AU", "AUOptions", 4), @("\AU", "ScheduledInstallDay", 0), @("\AU", "ScheduledInstallTime", $Start),
    @("", "SetActiveHours", 1), @("", "ActiveHoursStart", $end), @("", "ActiveHoursEnd", $Start))
  $note = "{0}+{1}" -f $Start, $Hours
  $differs = @($want | Where-Object { [string]$p[$_[1]] -ne [string]$_[2] })
  if ($differs.Count -eq 0 -and $p.Ours -eq $note) { return "same" }
  # the note first: values half written by a run that failed are then ours, and the next start writes them whole
  Set-TbMachineSetting "update_window" $note
  foreach ($w in $want) { Write-TbUpdateValue $w[0] $w[1] $w[2] }
  Write-TbLog ("    Windows Update: installs daily at {0}:00; restarts by itself only from {0}:00 to {1}:00 (active hours {1} to {0})" -f $Start, $end)
  return "written"
}
function Test-TbShutdownRight($Now) { return (@($Now.Sids).Count -eq 1 -and $Now.Sids[0] -eq $script:TbAdminsSid -and -not $Now.AtSignIn) }
function Set-TbShutdownRight {
  # Only administrators may shut the PC down, and the sign-in screen offers it to nobody: a desktop user who turns
  # the PC off in the evening stops the night. Returns "kept" or "written"; what was written is read back.
  $now = Get-TbShutdownRight
  if (Test-TbShutdownRight $now) { return "kept" }
  Write-TbLog ("    shutdown right was: {0}; offered at the sign-in screen: {1}" -f (@($now.Sids) -join ","), [bool]$now.AtSignIn)
  Write-TbShutdownRight $script:TbAdminsSid
  $after = Get-TbShutdownRight
  if (-not (Test-TbShutdownRight $after)) {
    throw ("after setting it the right is held by {0} (a policy of the domain may set it back)" -f (@($after.Sids) -join ","))
  }
  return "written"
}
function Set-TbOwnDrives {
  # The backup check inside WSL2 counts a Windows drive as off-box only when it is none of this PC's own: the box
  # is told the letters of its own drives (the system drive and the data drive always; every other disk that is
  # not on USB), once, and again when they change. A failure is logged and stops nothing: without the record no
  # Windows drive counts as off-box, which is the safe side.
  try {
    $own = @(Get-TbOwnDrives)
    foreach ($x in @([string]$script:TbFacts.SystemDrive, [string]$script:TbState.data_drive)) {
      if ($x -match "^([A-Za-z]):") { $own += $Matches[1].ToUpper() }
    }
    $tell = (@($own | Where-Object { $_ -match "^[A-Z]$" } | Sort-Object -Unique) -join ",")
    if ($tell -and $script:TbSetupWsl -and [string]$script:TbState.drives_told -ne $tell) {
      if ((Invoke-TbSetup "windows-drives" @($tell)).ExitCode -eq 0) { $script:TbState.drives_told = $tell }
    }
  } catch { Write-TbLog ("    this PC's own drives could not be recorded for the backup check: " + [string]$_.Exception.Message) }
}
function Set-TbBackupDrive([string]$Drive) {
  # -BackupDrive E: marks an outside drive as a place for backups. Windows is asked what the drive is: only a disk
  # attached by USB that is none of this PC's own drives is marked. The mark is a file on the drive itself, so it
  # goes where the disk goes; a letter that later names another volume has none. Nothing here stops the install.
  $l = $Drive.Substring(0, 1).ToUpper()
  try {
    $own = @(Get-TbOwnDrives)
    foreach ($x in @([string]$script:TbFacts.SystemDrive, [string]$script:TbState.data_drive)) {
      if ($x -match "^([A-Za-z]):") { $own += $Matches[1].ToUpper() }
    }
    if ($own -contains $l) { Say "backup_drive_own" @($l); return }
    $bus = Get-TbDriveBus $l
    if ($bus -ne "USB") { Say "backup_drive_not_usb" @($l, $bus); return }
    Write-TbOutsideMark $l @("TrialBox: an outside drive for backups. Written by box-install.ps1 -BackupDrive on " + (Get-Date).ToString("yyyy-MM-dd") + ".")
    Write-TbLog ("    drive {0}: marked as an outside drive for backups (bus {1})" -f $l, $bus)
    Say "backup_drive_marked" @($l, ("/mnt/" + $l.ToLower()))
  } catch { Say "backup_drive_unknown" @($l, [string]$_.Exception.Message) }
}
function Set-TbUnattended([bool]$Quiet) {
  # Neither part stops the install: a PC whose policy cannot be written still runs TrialBox, and the host check
  # (deploy/windows/wsl2_policy.py) fails it by name. $Quiet: a finished install says only what changed.
  $start = [int]$script:TbUpdate[0]; $hours = [int]$script:TbUpdate[1]
  try {
    $did = Set-TbUpdateWindow $start $hours
    if ($did -eq "kept") { if (-not $Quiet) { Say "updates_kept" @() } }
    elseif ($did -eq "written" -or -not $Quiet) { Say "updates" @($start, (($start + $hours) % 24)) }
    # trialbox doctor judges the window against the night: it is told which window Windows holds, or that the
    # site's IT holds the policy. Told once; again when it changes
    $tell = "kept"; if ($did -ne "kept") { $tell = "{0}+{1}" -f $start, $hours }
    if ($script:TbSetupWsl -and [string]$script:TbState.update_window_told -ne $tell) {
      if ((Invoke-TbSetup "update-window" @($tell)).ExitCode -eq 0) { $script:TbState.update_window_told = $tell }
    }
  } catch { Say "updates_failed" @([string]$_.Exception.Message) }
  try { if ((Set-TbShutdownRight) -eq "written" -or -not $Quiet) { Say "shutdown_right" @() } }
  catch { Say "shutdown_right_failed" @([string]$_.Exception.Message) }
}
function Step-BootTask {
  # A workstation that sleeps or hibernates serves nobody, and hiberfil.sys would hold WSL2's memory (D-421).
  # What is set: hibernation off, and the idle timers of the current power plan to never, on mains and on battery.
  # A power setting Windows refuses (a machine with no hibernation support) is told and does not stop the install:
  # hibernation is judged again by the host check.
  foreach ($a in @(@("/hibernate", "off"), @("/change", "standby-timeout-ac", "0"), @("/change", "hibernate-timeout-ac", "0"),
      @("/change", "standby-timeout-dc", "0"), @("/change", "hibernate-timeout-dc", "0"))) {
    $r = Invoke-TbNative "powercfg.exe" $a
    if ($r.ExitCode -ne 0) { Say "power_failed" @(($a -join " "), $r.ExitCode) }
  }
  try { $did = Set-TbBootTask }
  catch { Stop-TbStep "boot_task_failed" @([string]$_.Exception.Message) }
  $info = Get-TbBootTaskInfo $script:TbBootTask
  Write-TbLog ("    task {0}: {1}; state {2}; last result {3}" -f $script:TbBootTask, $did, $info.State, $info.LastResult)
  Say "boot_task" @($script:TbBootTask)
  Set-TbUnattended $false
  Set-TbOwnDrives
  if ($BackupDrive) { Set-TbBackupDrive $BackupDrive }
}
function Get-TbNetForm {
  # "mirrored" where Windows has WSL2's mirrored networking, else "proxy" (Windows 10; NEW-WIN-10, D-613)
  if ([int]$script:TbFacts.Build -ge $script:TbMirroredBuild) { return "mirrored" }
  return "proxy"
}
function Set-TbHostFirewall([string]$RuleName, [int]$Port) {
  # Windows Firewall, on a PC without mirrored networking: the console's port from the workstation's own subnet, on a
  # private or domain network only. A rule of that name is ours: one that is wider is put right. "kept", "added" or
  # "corrected".
  $rule = Get-TbHostFirewallRule $RuleName
  if ($null -eq $rule) { Write-TbHostFirewallRule $RuleName $Port $false; return "added" }
  $profiles = @(([string]$rule.Profile) -split "\s*,\s*" | Where-Object { $_ }) | Sort-Object
  $right = ($rule.Enabled -eq "True" -and $rule.Direction -eq "Inbound" -and $rule.Action -eq "Allow" -and $rule.Protocol -eq "TCP" -and
    $rule.LocalPort -eq [string]$Port -and $rule.RemoteAddress -eq "LocalSubnet" -and ($profiles -join ",") -eq "Domain,Private")
  if ($right) { return "kept" }
  Write-TbLog ("    rule {0} was: enabled {1}, {2} {3}, {4} ports {5}, from {6}, networks {7}" -f $RuleName, $rule.Enabled, $rule.Direction,
    $rule.Action, $rule.Protocol, $rule.LocalPort, $rule.RemoteAddress, $rule.Profile)
  Write-TbHostFirewallRule $RuleName $Port $true
  return "corrected"
}
function Set-TbConsoleProxy([bool]$Quiet) {
  # The forwarding script beside the state (administrators only), its task, and one run now. Returns the run's
  # @{ Status; Address }. A task that is there and runs this script is kept as it is.
  $script = Join-Path $script:TbStateDir "console-proxy.ps1"
  $from = Join-Path $script:TbHere "console-proxy.ps1"
  if ($from -ne $script) { Copy-Item -LiteralPath $from -Destination $script -Force }
  $info = Get-TbProxyTaskInfo $script:TbProxyTask
  if ($null -eq $info -or $info.State -eq "Disabled" -or -not ([string]$info.Action).Contains($script)) {
    Register-TbProxyTask $script:TbFacts.Account $script $script:TbState.distro $script:TbConsolePort $ProxyEveryMinutes $script:TbProxyTask
    Write-TbLog ("    task {0}: registered, every {1} minutes and at startup" -f $script:TbProxyTask, $ProxyEveryMinutes)
  }
  $r = Invoke-TbConsoleProxy $script $script:TbState.distro $script:TbConsolePort
  Write-TbLog ("    console forwarding: {0}, port {1} to WSL2 at {2}" -f $r.Status, $script:TbConsolePort, $r.Address)
  return $r
}
function Set-TbIpHelper {
  # Returns "ok", "started" (it was only stopped or on demand) or "off" (switched off by the site, or missing: the
  # site's IT decides; nothing is changed)
  $ih = Get-TbIpHelper
  if ($null -eq $ih -or $ih.StartType -eq "Disabled") { return "off" }
  if ($ih.Status -eq "Running" -and $ih.StartType -eq "Automatic") { return "ok" }
  Set-TbIpHelperOn
  Write-TbLog ("    IP Helper (iphlpsvc): was {0}, {1}; now running, automatic" -f $ih.Status, $ih.StartType)
  return "started"
}
function Remove-TbWin10Forwarding {
  # a PC upgraded from Windows 10 to a Windows 11 with mirrored networking: the forwarding task, its row and the
  # Windows Firewall rule would hold port 443 on the PC against WSL2's own (review finding 5)
  $gone = @()
  if ($null -ne (Get-TbProxyTaskInfo $script:TbProxyTask)) { Unregister-TbProxyTask $script:TbProxyTask; $gone += "task" }
  if (Get-TbProxyRowTarget $script:TbConsolePort) { Remove-TbProxyRow $script:TbConsolePort; $gone += "row" }
  if ($null -ne (Get-TbHostFirewallRule $script:TbFirewallRule)) { Remove-TbHostFirewallRule $script:TbFirewallRule; $gone += "firewall" }
  if ($gone.Count -gt 0) { Write-TbLog ("    Windows 10 forwarding removed: {0}" -f ($gone -join ", ")) }
}
function Step-Network {
  if ((Get-TbNetForm) -eq "proxy") {
    # Windows 10 (NEW-WIN-10, D-613): WSL2 behind its own address; the port proxy passes the console's port to it
    try { $ih = Set-TbIpHelper } catch { Stop-TbStep "proxy_failed" @([string]$_.Exception.Message) }
    if ($ih -eq "off") { Stop-TbStep "iphelper_off" @() }
    try { $did = Set-TbHostFirewall $script:TbFirewallRule $script:TbConsolePort }
    catch { Stop-TbStep "firewall_failed" @([string]$_.Exception.Message) }
    Write-TbLog ("    firewall rule {0}: {1}" -f $script:TbFirewallRule, $did)
    if ($did -eq "corrected") { Say "firewall_corrected" @($script:TbFirewallRule) }
    try { $r = Set-TbConsoleProxy $false }
    catch { Stop-TbStep "proxy_failed" @([string]$_.Exception.Message) }
    if ($r.Status -eq "no_address") { Stop-TbStep "proxy_failed" @("WSL2 gave no address") }
    if ($r.Status -eq "refused") { Stop-TbStep "proxy_failed" @("netsh refused the rule") }
    if ($r.Status -eq "conflict") {
      Stop-TbStep "proxy_failed" @("another port-proxy rule takes port $($script:TbConsolePort) on one address: netsh interface portproxy show v4tov4")
    }
    Say "network_proxy" @($script:TbConsolePort)
    return
  }
  # the form is mirrored networking (.wslconfig, step 6): the workstation's own address is WSL2's, so the box sees
  # the site's real network and the console answers on the workstation's name
  $r = Invoke-TbSetup "network-mode" @()
  $mode = [string](@($r.Output) | Select-Object -Last 1)
  if ($r.ExitCode -ne 0 -or $mode -ne "mirrored") { Stop-TbStep "not_mirrored" @($mode) }
  try { Remove-TbWin10Forwarding } catch { Stop-TbStep "firewall_failed" @([string]$_.Exception.Message) }
  try { $did = Set-TbConsoleFirewall $script:TbFirewallRule $script:TbConsolePort }
  catch { Stop-TbStep "firewall_failed" @([string]$_.Exception.Message) }
  Write-TbLog ("    firewall rule {0}: {1}" -f $script:TbFirewallRule, $did)
  if ($did -eq "corrected") { Say "firewall_corrected" @($script:TbFirewallRule) }
  Say "network" @($script:TbConsolePort)
}
function Test-TbNetworkAfterInstall {
  # with the stack up: the egress table must be seen to stop a container (not only to be loaded), and the box's own
  # firewall must be open to the network this PC is really on
  $r = Invoke-TbSetup "egress-proof" @()
  $verdict = [string](@($r.Output | Where-Object { $_ -like "verdict=*" }) | Select-Object -Last 1)
  if ($verdict -eq "verdict=OUT") { Stop-TbStep "egress_open" @() }
  if ($verdict -ne "verdict=held") { Say "egress_unproven" @($verdict) }
  $r = Invoke-TbSetup "lan-check" @()
  $lan = [string](@($r.Output) | Select-Object -Last 1)
  if ($r.ExitCode -ne 0) { Say "lan_mismatch" @($lan) }
}
function Step-LinuxInstall {
  Say "linux_install" @()
  $a = @("-d", $script:TbState.distro, "-u", "root", "--cd", "/", "--exec", "bash", $script:TbSetupWsl, "install",
    (ConvertTo-TbWslPath $script:TbFiles.Bundle))
  if ($Yes) { $a += "--yes" }
  if ($script:TbState.rehearsal) { $a += "--rehearsal" }
  $code = Invoke-TbNativeConsole "wsl.exe" $a
  Write-TbLog ("    the Linux installer ended with exit " + $code)
  $r = Invoke-TbSetup "state" @()
  $line = [string](@($r.Output) | Select-Object -Last 1)
  if ($line -ne "installed=1") { Stop-TbStep "linux_install_stopped" @($code) }
  [void](Assert-TbSetup "boot-check" @())  # Docker and the stack start with the distribution, with nobody there
  [void](Assert-TbSetup "egress-check" @())  # the egress table of D-377 is loaded under this networking form
  Test-TbNetworkAfterInstall
  if ($code -ne 0) { Say "host_check_fails" @() }
  $script:TbState.finished = $true
}

# ------------------------------------------------------------------------------------------------ the run
function Invoke-TbInstall {
  param([string]$MediaRoot, [string]$DataDrive, [string]$Distro = "TrialBox", [string]$Lang, [string]$StateDir,
    [switch]$Resume, [switch]$Yes, [switch]$Rehearsal)
  # a cmdlet that reports an error stops its step: nothing goes on after a failed copy, permission change or task
  # registration (Invoke-TbNative sets its own preference for a program's error text)
  $ErrorActionPreference = "Stop"
  $script:TbFacts = Get-TbWindowsFacts
  $script:TbLang = Get-TbLang $Lang $script:TbFacts.UiCulture
  $script:TbMessages = Get-Content -LiteralPath (Join-Path $PSScriptRoot "box-install.messages.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $script:TbFacts.IsAdmin) { Write-TbScreen (Get-TbText "not_admin" @() $script:TbLang); return 1 }
  $closing = $StateDir
  try {
    if (-not $StateDir) {
      # standard accounts may make folders under ProgramData: the parent is closed first, so nobody else owns the
      # path of the script the resume task runs elevated
      $closing = Join-Path $env:ProgramData "TrialBox"
      Protect-TbDirectory $closing $script:TbFacts.Account
      $StateDir = Join-Path $closing "box-install"
      $closing = $StateDir
    }
    Protect-TbDirectory $StateDir $script:TbFacts.Account
  } catch { Write-TbScreen (Get-TbText "folder_not_ours" @($closing) $script:TbLang); return 1 }
  $script:TbStateDir = $StateDir
  $script:TbStatePath = Join-Path $StateDir "state.json"
  $script:TbLogPath = Join-Path $StateDir "box-install.log"
  $script:TbState = Read-TbState
  $script:TbStop = $null
  Write-TbLog ("box-install.ps1 started by {0}; resume={1}; Windows {2} build {3}; language {4}" -f $script:TbFacts.Account,
    [bool]$Resume, $script:TbFacts.EditionId, $script:TbFacts.Build, $script:TbLang)
  # a rehearsal (D-614) goes on only when asked for again: a run without -Rehearsal on an unfinished rehearsal stops
  # here, before anything changes. Its box may have been emptied since (RUNBOOK section 16), and the Linux installer
  # would then take a site's media as a rehearsal unasked (review finding 3). The resume task names the switch
  if ($script:TbState.rehearsal -and -not $script:TbState.finished -and -not $Rehearsal) {
    Write-TbLog "    unfinished rehearsal started without -Rehearsal: stopped, nothing changed"
    Write-TbScreen (Get-TbText "rehearsal_unasked" @($script:TbStatePath) $script:TbLang)
    return 1
  }
  # the resume task has done its work once this run started; step 5 registers it again if Windows wants a restart
  try { Unregister-TbResumeTask } catch { Write-TbLog ("    the resume task could not be removed: " + [string]$_.Exception.Message) }
  if ($script:TbShareGiven -or [int]$script:TbState.desktop_share_pct -lt 0) { $script:TbState.desktop_share_pct = $script:TbShareDefault }
  $script:TbShare = [int]$script:TbState.desktop_share_pct
  if ($script:TbUnlockGiven -or -not $script:TbState.bitlocker_unlock) { $script:TbState.bitlocker_unlock = $script:TbUnlockDefault }
  $script:TbUnlock = [string]$script:TbState.bitlocker_unlock
  # each figure: the one given on this command line; else the one this install already used; else the default
  $script:TbUpdate = @([int]$script:TbUpdateDefault[0], [int]$script:TbUpdateDefault[1])
  if ([string]$script:TbState.update_window -match "^(\d+)\+(\d+)$") {
    if (-not $script:TbUpdateGiven[0]) { $script:TbUpdate[0] = [int]$Matches[1] }
    if (-not $script:TbUpdateGiven[1]) { $script:TbUpdate[1] = [int]$Matches[2] }
  }
  $script:TbState.update_window = "{0}+{1}" -f $script:TbUpdate[0], $script:TbUpdate[1]
  # a rehearsal is decided at the start and kept: never turned off by a run without the switch (a site's box is a
  # new install, RUNBOOK section 16); the Linux installer refuses to make a box holding a site's install a rehearsal
  if ($Rehearsal -and $script:TbState.finished -and -not $script:TbState.rehearsal) {
    Write-TbLog "    -Rehearsal ignored: this install is finished and is not a rehearsal"
    Say "rehearsal_ignored" @()
  } elseif ($Rehearsal) { $script:TbState.rehearsal = $true }
  if ($script:TbState.rehearsal -and -not $script:TbState.finished) {
    Write-TbLog "    rehearsal: yes (the box will be TEST and say so; D-726)"
    Say "rehearsal_on" @()
  }
  if ($script:TbState.finished) {
    # A finished install is left alone, but for .wslconfig: it follows the hardware (memory was added, the share
    # was changed), so "start the installer again after a hardware change" is true on a finished box too.
    try {
      $script:TbDataDriveBytes = 0
      if ($script:TbState.data_drive) { $df = Get-TbDriveFacts $script:TbState.data_drive; if ($df) { $script:TbDataDriveBytes = [long]$df.SizeBytes } }
      [void](Step-WslConfig)
    } catch {
      if ([string]$_.Exception.Message -like "TBSTOP*" -and $null -ne $script:TbStop) { Say $script:TbStop.Key $script:TbStop.Values }
      else { Say "unexpected" @([string]$_.Exception.Message) }
    }
    # the console's firewall rule (D-604): only once WSL2 really runs with mirrored networking. An install made
    # before NEW-WIN-4 gets the new .wslconfig above and needs one restart of Windows first
    try {
      $root = [string]$script:TbState.data_drive; if ($root -match "^[A-Za-z]:$") { $root = $root + "\" }
      $script:TbSetupWsl = ConvertTo-TbWslPath (Join-Path (Join-Path (Join-Path $root "TrialBox") "install") "wsl-setup.sh")
      if ((Get-TbNetForm) -eq "proxy") {
        if ((Set-TbIpHelper) -eq "off") { Say "iphelper_off" @() }
        else {
          $did = Set-TbHostFirewall $script:TbFirewallRule $script:TbConsolePort
          if ($did -ne "kept") { Write-TbLog ("    firewall rule {0}: {1}" -f $script:TbFirewallRule, $did) }
          $r = Set-TbConsoleProxy $true
          if (@("no_address", "refused", "conflict") -contains $r.Status) { Say "proxy_failed" @($r.Status) }
        }
      } elseif (([string](@((Invoke-TbSetup "network-mode" @()).Output) | Select-Object -Last 1)) -eq "mirrored") {
        Remove-TbWin10Forwarding
        $did = Set-TbConsoleFirewall $script:TbFirewallRule $script:TbConsolePort
        if ($did -ne "kept") { Write-TbLog ("    firewall rule {0}: {1}" -f $script:TbFirewallRule, $did); Say "network" @($script:TbConsolePort) }
      } else { Say "network_pending" @("not mirrored") }
    } catch { Say "firewall_failed" @([string]$_.Exception.Message) }
    # and the start-at-boot task, when it was deleted or disabled by hand (D-602)
    try { if ((Set-TbBootTask) -ne "kept") { Say "boot_task_restored" @($script:TbBootTask) } }
    catch { Say "boot_task_failed" @([string]$_.Exception.Message) }
    # and the update window and the shutdown right (D-606): an install made before NEW-WIN-5 gets them here
    Set-TbUnattended $true
    Set-TbOwnDrives
    if ($BackupDrive) { Set-TbBackupDrive $BackupDrive }
    Save-TbState
    Say "already_installed" @($script:TbLogPath)
    return 0
  }
  # the media: the one named; else the one this script was started from; else the one of the last run; else a
  # media found on a drive (its letter may have changed over the restart)
  $here = Split-Path -Parent $PSScriptRoot
  if ($MediaRoot) { $script:TbState.media_root = $MediaRoot }
  elseif (Test-Path -LiteralPath (Join-Path $here "SHA256SUMS")) { $script:TbState.media_root = $here }
  elseif (-not $script:TbState.media_root -or -not (Test-Path -LiteralPath (Join-Path $script:TbState.media_root "SHA256SUMS"))) {
    $found = Find-TbMedia
    if ($found) { $script:TbState.media_root = $found } elseif (-not $script:TbState.media_root) { $script:TbState.media_root = $here }
  }
  if (-not $script:TbState.data_drive -and $DataDrive) { $script:TbState.data_drive = $DataDrive }
  if (-not $script:TbState.distro) { $script:TbState.distro = $Distro }
  $n = 0
  foreach ($step in $script:TbSteps) {
    $n++
    $label = "step {0}/{1} {2}" -f $n, $script:TbSteps.Count, $step
    Write-TbLog ($label + ": start")
    try {
      $fn = "Step-" + (($step -split "-" | ForEach-Object { $_.Substring(0, 1).ToUpper() + $_.Substring(1) }) -join "")
      $result = & $fn
    } catch {
      $text = [string]$_.Exception.Message
      if ($text -like "TBSTOP*" -and $null -ne $script:TbStop) {
        Write-TbLog ("STOP {0}: {1}" -f $label, (Get-TbText $script:TbStop.Key $script:TbStop.Values "en"))
        Write-TbScreen (Get-TbText $script:TbStop.Key $script:TbStop.Values $script:TbLang)
      } else {
        Write-TbLog ("STOP {0}: unexpected: {1}" -f $label, $text)
        Write-TbScreen (Get-TbText "unexpected" @($text) $script:TbLang)
      }
      Save-TbState
      # what an unfinished install has already changed for good is said, not left to be found
      if ($script:TbState.bitlocker_turned_on) { Say "bitlocker_stays" @([string]$script:TbState.bitlocker_turned_on) }
      Write-TbScreen (Get-TbText "stopped" @($n, $script:TbSteps.Count, $script:TbLogPath) $script:TbLang)
      return 1
    }
    Save-TbState
    if ($result -eq "restart") { Write-TbLog ($label + ": restart"); return $script:TbRestartExit }
    Write-TbLog ($label + ": ok")
  }
  Say "done" @($script:TbLogPath)
  return 0
}

if (-not $LoadOnly) {
  $code = Invoke-TbInstall -MediaRoot $MediaRoot -DataDrive $DataDrive -Distro $Distro -Lang $Lang -StateDir $StateDir `
    -Resume:$Resume -Yes:$Yes -Rehearsal:$Rehearsal
  exit $code
}
