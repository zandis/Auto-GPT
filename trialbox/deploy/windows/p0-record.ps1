# TrialBox: write down what the P-0 sheet asks for, so the owner only starts P-0 (NEW-WIN-12, D-615; ruling D-510).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File p0-record.ps1 -When after-run [-CopyTo <usb>\P0-RECORD]
#   powershell -NoProfile -ExecutionPolicy Bypass -File p0-record.ps1 -Register -User <account>
#
# Read only: it changes nothing on the PC but its own record folder (beside the installer's state, administrators
# only) and, with -Register, its own task, which records each start of Windows six minutes in, signed in or not
# (S4U, as the boot task). One record is one text file. A section that fails writes its error and the others go on.
# Nothing shaped like a BitLocker recovery key or a first-run code is ever written. It never starts WSL2: what it
# reads inside WSL2 it reads only when WSL2 already runs, so the record says whether the boot task started it.
# Every Windows command is behind a function below (tests/windows/p0-record.Tests.ps1, Pester on PowerShell 7).
# Keep this file ASCII and in Windows PowerShell 5.1 syntax.
[CmdletBinding()]
param(
  [ValidateSet("after-run", "at-boot", "by-hand")][string]$When = "by-hand",
  [string]$StateDir = "",
  [string]$Out = "",
  [string]$CopyTo = "",
  [ValidatePattern("^[A-Za-z0-9._-]+$")][string]$Distro = "TrialBox",
  [string]$WslConfig = "",
  [switch]$Register,
  [string]$User = "",
  [string]$TaskName = "TrialBox-P0-Record",
  [switch]$LoadOnly
)

$script:TbRecTasks = @("TrialBox-WSL2", "TrialBox-Console-Proxy", "TrialBox-Install-Resume", "TrialBox-P0-Record")

# ---- seams: the only places that touch Windows (each returns lines of text)
function Invoke-TbRecWsl([string]$Name, [string[]]$Command) {
  $env:WSL_UTF8 = "1"   # wsl.exe's own messages in UTF-8, not UTF-16
  return @(& wsl.exe -d $Name -u root --exec @Command 2>&1 | ForEach-Object { [string]$_ })
}
function Test-TbRecWslRunning([string]$Name) {
  $env:WSL_UTF8 = "1"
  return (@(& wsl.exe --list --running --quiet 2>$null | ForEach-Object { ([string]$_).Trim() }) -contains $Name)
}
function Get-TbRecWindows {
  $cv = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
  $os = Get-CimInstance Win32_OperatingSystem
  return @(("build {0}.{1} ({2})" -f $cv.CurrentBuildNumber, $cv.UBR, $cv.DisplayVersion), ("edition {0}" -f $cv.EditionID),
    ("last start of Windows {0:u}" -f $os.LastBootUpTime.ToUniversalTime()))
}
function Get-TbRecWsl {
  $env:WSL_UTF8 = "1"
  return @(@(& wsl.exe --version 2>&1) + @(& wsl.exe --list --verbose 2>&1) | ForEach-Object { [string]$_ })
}
function Get-TbRecNetwork {
  $lines = @("-- port proxy (netsh interface portproxy show v4tov4)") + @(& netsh.exe interface portproxy show v4tov4 2>&1)
  $rule = Get-NetFirewallRule -Name "TrialBox-Console" -ErrorAction SilentlyContinue
  if ($rule) {
    $pf = $rule | Get-NetFirewallPortFilter; $af = $rule | Get-NetFirewallAddressFilter
    $lines += ("-- Windows Firewall rule TrialBox-Console: enabled {0}, {1} {2}, {3} {4}, from {5}, networks {6}" -f $rule.Enabled,
      $rule.Direction, $rule.Action, $pf.Protocol, $pf.LocalPort, (@($af.RemoteAddress) -join ","), $rule.Profile)
  } else { $lines += "-- Windows Firewall rule TrialBox-Console: none" }
  foreach ($p in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) { $lines += ("-- network '{0}': {1}" -f $p.InterfaceAlias, $p.NetworkCategory) }
  $svc = Get-Service -Name "iphlpsvc" -ErrorAction SilentlyContinue
  if ($svc) { $lines += ("-- IP Helper (iphlpsvc): {0}, {1}" -f $svc.Status, $svc.StartType) } else { $lines += "-- IP Helper (iphlpsvc): missing" }
  $lines += "-- listening on port 443 (netstat -ano -p tcp)"
  $lines += @(& netstat.exe -ano -p tcp 2>$null | Where-Object { $_ -match ":443\s" -and $_ -match "LISTEN" })
  foreach ($a in @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" })) {
    $lines += ("-- {0}: {1}/{2}" -f $a.InterfaceAlias, $a.IPAddress, $a.PrefixLength)
  }
  return @($lines | ForEach-Object { [string]$_ })
}
function Get-TbRecTasks {
  $lines = @()
  foreach ($n in $script:TbRecTasks) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($null -eq $t) { $lines += ("{0}: none" -f $n); continue }
    $i = Get-ScheduledTaskInfo -TaskName $n -ErrorAction SilentlyContinue
    $lines += ("{0}: {1}; sign-in {2}, rights {3}; last run {4:u}, result {5}; run limit {6}" -f $n, $t.State, $t.Principal.LogonType,
      $t.Principal.RunLevel, $i.LastRunTime, $i.LastTaskResult, $t.Settings.ExecutionTimeLimit)
    foreach ($tr in @($t.Triggers)) {
      $lines += ("  trigger {0}: delay {1}, repeat every {2} for {3}" -f $tr.CimClass.CimClassName, $tr.Delay, $tr.Repetition.Interval, $tr.Repetition.Duration)
    }
  }
  return $lines
}
function Get-TbRecBitLocker {
  # the state and the kinds of protector only: a key protector's own value is never read
  return @(@(Get-BitLockerVolume -ErrorAction Stop) | ForEach-Object {
      "{0} {1}, protection {2}, {3} percent, protectors {4}" -f $_.MountPoint, $_.VolumeStatus, $_.ProtectionStatus,
      $_.EncryptionPercentage, ((@($_.KeyProtector) | ForEach-Object { [string]$_.KeyProtectorType }) -join ",")
    })
}
function Get-TbRecTimes([string]$Name) {
  # the last start of Windows, the start of WSL2's first process (only when WSL2 already runs: reading it would
  # start it), and the first sign-in after the start (Winlogon's event 7001)
  $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
  $t = @{ Boot = $boot; WslStart = $null; FirstSignIn = $null; WslNotRunning = $false }
  if (Test-TbRecWslRunning $Name) {
    $epoch = [string](@(Invoke-TbRecWsl $Name @("stat", "-c", "%Y", "/proc/1")) | Select-Object -First 1)
    if ($epoch -match "^\d+$") { $t.WslStart = ([datetime]"1970-01-01T00:00:00Z").ToUniversalTime().AddSeconds([double]$epoch) }
  } else { $t.WslNotRunning = $true }
  $ev = @(Get-WinEvent -FilterHashtable @{ LogName = "System"; ProviderName = "Microsoft-Windows-Winlogon"; Id = 7001; StartTime = $boot.ToLocalTime() } -ErrorAction SilentlyContinue |
      Sort-Object TimeCreated | Select-Object -First 1)
  if ($ev.Count -gt 0) { $t.FirstSignIn = $ev[0].TimeCreated.ToUniversalTime() }
  return $t
}
function Get-TbRecInside([string]$Name) {
  if (-not (Test-TbRecWslRunning $Name)) { return @("WSL2 is not running: nothing read inside it (reading would start it)") }
  $sh = "cd /opt/trialbox 2>/dev/null || exit 0; ip -4 -o addr show dev eth0; grep -E '^TB_(ENV|REHEARSAL)=' deploy/.env 2>/dev/null; " +
  "ls deploy/site/rehearsal.json 2>/dev/null; systemctl is-active docker 2>/dev/null; docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null; " +
  "[ -f deploy/.env ] && python3 -m tools.trialbox doctor --env-file deploy/.env 2>&1 | tail -n 80"
  return @(Invoke-TbRecWsl $Name @("bash", "-c", $sh))
}

function Get-TbRecKeyProbe([string]$Dir) {
  # line 36a: the key probe's own lines (key-probe.ps1 -Collect), when the installer armed it; dummy values only
  $probe = Join-Path $Dir "key-probe.ps1"
  if (-not (Test-Path -LiteralPath (Join-Path $env:ProgramData "TrialBox\key-probe"))) { return @("not armed") }
  return @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe -Collect 2>&1 | ForEach-Object { [string]$_ })
}

# ---- logic
function Protect-TbRecText([string[]]$Lines) {
  # a BitLocker recovery key is eight groups of six figures; a first-run code follows "One-time code"
  return @($Lines | ForEach-Object {
      $l = [regex]::Replace([string]$_, "\d{6}(-\d{6}){7}", "[a recovery key: not written]")
      if ($l -match "(?i)one-time code") { $l = "[a first-run code: not written]" }
      $l
    })
}
function Format-TbTimeline($Times) {
  # line 26a: did WSL2 (the box) start before anyone signed in?
  $b = $Times.Boot; $w = $Times.WslStart; $s = $Times.FirstSignIn
  if ($null -ne $b -and $Times.WslNotRunning) {
    if ($null -eq $s) { return "wsl2_started_before_sign_in: no (WSL2 was not running when this was recorded; nobody signed in since)" }
    return ("wsl2_started_before_sign_in: no (WSL2 was not running when this was recorded; first sign-in {0} s after boot)" -f [int]($s - $b).TotalSeconds)
  }
  if ($null -eq $b -or $null -eq $w) { return "wsl2_started_before_sign_in: unknown (no start time read)" }
  $ws = [int]($w - $b).TotalSeconds
  if ($null -eq $s) { return ("wsl2_started_before_sign_in: yes ({0} s after boot; nobody signed in since)" -f $ws) }
  $ss = [int]($s - $b).TotalSeconds
  $answer = "no"; if ($w -lt $s) { $answer = "yes" }
  return ("wsl2_started_before_sign_in: {0} ({1} s after boot; first sign-in {2} s after boot)" -f $answer, $ws, $ss)
}
function Write-TbRecord([string]$Out, [string]$When, [string]$StateDir, [string]$Distro, [string]$WslConfig) {
  if (-not (Test-Path -LiteralPath $Out)) { New-Item -ItemType Directory -Force -Path $Out | Out-Null }
  $file = Join-Path $Out ("{0}-{1}.txt" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"), $When)
  $text = @(("TrialBox P-0 record, {0}, written {1:u}" -f $When, [DateTime]::UtcNow))
  $sections = [ordered]@{
    "windows" = { Get-TbRecWindows }
    "wsl" = { Get-TbRecWsl }
    "wslconfig" = { if ($WslConfig -and (Test-Path -LiteralPath $WslConfig)) { @(Get-Content -LiteralPath $WslConfig) } else { @("no .wslconfig read") } }
    "network" = { Get-TbRecNetwork }
    "tasks" = { Get-TbRecTasks }
    "bitlocker" = { Get-TbRecBitLocker }
    "times" = { $t = Get-TbRecTimes $Distro; @(("boot {0:u}; WSL2 started {1:u}; first sign-in {2:u}" -f $t.Boot, $t.WslStart, $t.FirstSignIn), (Format-TbTimeline $t)) }
    "key probe" = { Get-TbRecKeyProbe $StateDir }
    "inside WSL2" = { Get-TbRecInside $Distro }
    "installer log" = { $p = Join-Path $StateDir "box-install.log"; if (Test-Path -LiteralPath $p) { @(Get-Content -LiteralPath $p) } else { @("none") } }
    "console forwarding log" = { $p = Join-Path $StateDir "console-proxy.log"; if (Test-Path -LiteralPath $p) { @(Get-Content -LiteralPath $p) } else { @("none") } }
  }
  foreach ($name in $sections.Keys) {
    $text += ""
    try { $text += ("== {0}" -f $name); $text += @(& $sections[$name]) }
    catch { $text[-1] = ("== {0}`r`nerror: {1}" -f $name, $_.Exception.Message) }
  }
  Set-Content -LiteralPath $file -Value (Protect-TbRecText $text) -Encoding ASCII
  return $file
}
function Copy-TbRecords([string]$From, [string]$To) {
  # to the USB disk, when it is there (at a start of Windows it often is not; the next run after the installer copies)
  try {
    if (-not (Test-Path -LiteralPath (Split-Path -Parent $To))) { return }
    if (-not (Test-Path -LiteralPath $To)) { New-Item -ItemType Directory -Force -Path $To | Out-Null }
    Copy-Item -Path (Join-Path $From "*.txt") -Destination $To -Force
  } catch { Write-Output ("p0-record: the records were not copied to {0}: {1}" -f $To, $_.Exception.Message) }
}
function Register-TbRecordTask([string]$Account, [string]$Name, [string]$Self, [string]$Dir, [string]$Config) {
  # each start of Windows, six minutes in, signed in or not: what an unattended start does (sheet lines 26a, 79)
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $trigger.Delay = "PT6M"
  $arg = "-NoProfile -ExecutionPolicy Bypass -File `"{0}`" -When at-boot -StateDir `"{1}`" -Distro {2}" -f $Self, $Dir, $Distro
  if ($Config) { $arg += (" -WslConfig `"{0}`"" -f $Config) }
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
  $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType S4U -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "TrialBox P-0: write down what a start of Windows did (NEW-WIN-12); removed with the P-0 box" -Force | Out-Null
}

if ($LoadOnly) { return }
if (-not $StateDir) { $StateDir = Join-Path $env:ProgramData "TrialBox\box-install" }
if (-not $Out) { $Out = Join-Path $StateDir "P0-RECORD" }
if ($Register) {
  if (-not $User) { Write-Output "p0-record: -Register needs -User <the box owner's account>"; exit 2 }
  Register-TbRecordTask $User $TaskName $PSCommandPath $StateDir $WslConfig
  Write-Output ("registered {0}: each start of Windows, six minutes in" -f $TaskName)
  exit 0
}
$file = Write-TbRecord -Out $Out -When $When -StateDir $StateDir -Distro $Distro -WslConfig $WslConfig
if ($CopyTo) { Copy-TbRecords -From $Out -To $CopyTo }
Write-Output ("record={0}" -f $file)
exit 0
