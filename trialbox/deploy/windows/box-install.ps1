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
#    2 windows        administrator; Windows 11 Pro, Pro for Workstations, Enterprise or Education; virtualisation
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
#                     (register_keepalive.ps1) starts the distribution at boot, signed in or not
#   13 linux-install  deploy/box-install.sh inside WSL2, in this window: it shows the first-run code and waits for
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
  # the first build of Windows 11 (WSL2 with systemd and GPU support in its supported form)
  [int]$MinWindowsBuild = 22000,
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
$script:TbSteps = @("media", "windows", "gpu-driver", "drive", "wsl-enable", "wslconfig", "import", "systemd",
  "packages", "gpu-container", "host-tree", "boot-task", "linux-install")
$script:TbEditions = @("Professional", "ProfessionalWorkstation", "Enterprise", "EnterpriseS", "Education",
  "ProfessionalEducation")
$script:TbFeatures = @("VirtualMachinePlatform", "Microsoft-Windows-Subsystem-Linux")
$script:TbResumeTask = "TrialBox-Install-Resume"
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
function Get-TbWslConfigText([int]$MemoryGB, [int]$Processors, [int]$SharePercent, [long]$DiskBytes) {
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
    desktop_share_pct = -1; recovery_confirmed = ""; bitlocker_unlock = ""; bitlocker_turned_on = ""
    restart_pending = $false; finished = $false }
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
  if ($script:TbEditions -notcontains $f.EditionId -or $f.Build -lt $MinWindowsBuild) { Stop-TbStep "edition" @($f.EditionId, $f.Build) }
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
    foreach ($n in @("box-install.ps1", "box-install.messages.json", "register_keepalive.ps1")) {
      $from = Join-Path $PSScriptRoot $n; $to = Join-Path $copy $n
      if ($from -ne $to) { Copy-Item -LiteralPath $from -Destination $to -Force }  # the copy itself asked again
    }
    # the run after the restart gets this run's settings (all checked: figures, a language of the list, a name)
    $more = "-MinFreeGB {0} -MinWindowsBuild {1} -StartWaitSeconds {2} -DesktopSharePercent {3} -Distro {4} -Lang {5} -BitLockerUnlock {6}" -f $MinFreeGB,
      $MinWindowsBuild, $StartWaitSeconds, $script:TbShare, $script:TbState.distro, $script:TbLang, $script:TbUnlock
    if ($SkipBitLocker) { $more += " -SkipBitLocker" }
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
        if ($text -notmatch "(?im)^\s*swap\s*=\s*0\s*$") { Say "wslconfig_kept_no_swap0" @($path) } else { Say "wslconfig_kept" @($path) }
        return "kept"
      }
      $old = $text
    }
  }
  $hw = Get-TbHardware
  $new = Get-TbWslConfigText $hw.MemoryGB $hw.Processors $script:TbShare $script:TbDataDriveBytes
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
}
function Step-LinuxInstall {
  Say "linux_install" @()
  $a = @("-d", $script:TbState.distro, "-u", "root", "--cd", "/", "--exec", "bash", $script:TbSetupWsl, "install",
    (ConvertTo-TbWslPath $script:TbFiles.Bundle))
  if ($Yes) { $a += "--yes" }
  $code = Invoke-TbNativeConsole "wsl.exe" $a
  Write-TbLog ("    the Linux installer ended with exit " + $code)
  $r = Invoke-TbSetup "state" @()
  $line = [string](@($r.Output) | Select-Object -Last 1)
  if ($line -ne "installed=1") { Stop-TbStep "linux_install_stopped" @($code) }
  [void](Assert-TbSetup "boot-check" @())  # Docker and the stack start with the distribution, with nobody there
  if ($code -ne 0) { Say "host_check_fails" @() }
  $script:TbState.finished = $true
}

# ------------------------------------------------------------------------------------------------ the run
function Invoke-TbInstall {
  param([string]$MediaRoot, [string]$DataDrive, [string]$Distro = "TrialBox", [string]$Lang, [string]$StateDir,
    [switch]$Resume, [switch]$Yes)
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
  # the resume task has done its work once this run started; step 5 registers it again if Windows wants a restart
  try { Unregister-TbResumeTask } catch { Write-TbLog ("    the resume task could not be removed: " + [string]$_.Exception.Message) }
  if ($script:TbShareGiven -or [int]$script:TbState.desktop_share_pct -lt 0) { $script:TbState.desktop_share_pct = $script:TbShareDefault }
  $script:TbShare = [int]$script:TbState.desktop_share_pct
  if ($script:TbUnlockGiven -or -not $script:TbState.bitlocker_unlock) { $script:TbState.bitlocker_unlock = $script:TbUnlockDefault }
  $script:TbUnlock = [string]$script:TbState.bitlocker_unlock
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
    # and the start-at-boot task, when it was deleted or disabled by hand (D-602)
    try { if ((Set-TbBootTask) -ne "kept") { Say "boot_task_restored" @($script:TbBootTask) } }
    catch { Say "boot_task_failed" @([string]$_.Exception.Message) }
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
    -Resume:$Resume -Yes:$Yes
  exit $code
}
