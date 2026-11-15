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

$script:TbRecTasks = @("TrialBox-WSL2", "TrialBox-Console-Proxy", "TrialBox-Install-Resume", "TrialBox-P0-Record", "TrialBox-Key-Probe")

# ---- seams: the only places that touch Windows (each returns lines of text)
function Invoke-TbRecWsl([string]$Name, [string[]]$Command) {
  $env:WSL_UTF8 = "1"   # wsl.exe's own messages in UTF-8, not UTF-16
  return @(& wsl.exe -d $Name -u root --exec @Command 2>&1 | ForEach-Object { [string]$_ })
}
function Test-TbRecWslRunning([string]$Name) {
  $env:WSL_UTF8 = "1"
  return ((ConvertFrom-TbWslList @(& wsl.exe --list --running --quiet 2>$null)) -contains $Name)
}
function Find-TbRecMedia {
  # the P-0 media on any drive: its checksum list, its choices and its launcher (at a start of Windows nobody
  # passes its path, and its letter may have changed)
  foreach ($d in @(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
    foreach ($dir in @(Get-ChildItem -LiteralPath $d.Root -Directory -Filter "TRIALBOX-*" -ErrorAction SilentlyContinue)) {
      if ((Test-Path -LiteralPath (Join-Path $dir.FullName "SHA256SUMS")) -and (Test-Path -LiteralPath (Join-Path $dir.FullName "windows\p0.json")) -and
        (Test-Path -LiteralPath (Join-Path $dir.FullName "Install-TrialBox-P0.cmd"))) { return $dir.FullName }
    }
  }
  return ""
}
function Test-TbRecProbeReady {
  # the key probe's task wrote its result at this start of Windows (key-probe.ps1: result-at_startup.txt)
  $f = Join-Path $env:ProgramData "TrialBox\key-probe\result-at_startup.txt"
  return ((Test-Path -LiteralPath $f) -and (Get-Item -LiteralPath $f).Length -gt 0)
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
  # the last start of Windows; the boot task (is it running, since when); WSL2's first process's start (only when
  # WSL2 already runs: reading it would start it; from /proc/1/stat and the kernel's boot time, not a file's time);
  # the first sign-in after the start (Winlogon's event 7001)
  $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
  $t = @{ Boot = $boot; WslStart = $null; FirstSignIn = $null; WslNotRunning = $false; BootTaskState = ""; BootTaskLastRun = $null; BootTaskResult = "" }
  $bt = Get-ScheduledTask -TaskName "TrialBox-WSL2" -ErrorAction SilentlyContinue
  if ($bt) {
    $bi = Get-ScheduledTaskInfo -TaskName "TrialBox-WSL2" -ErrorAction SilentlyContinue
    $t.BootTaskState = [string]$bt.State; $t.BootTaskResult = [string]$bi.LastTaskResult
    if ($bi.LastRunTime -and $bi.LastRunTime.Year -gt 2000) { $t.BootTaskLastRun = $bi.LastRunTime.ToUniversalTime() }
  }
  if (Test-TbRecWslRunning $Name) {
    $sh = 'b=$(awk ''/^btime/{print $2}'' /proc/stat); s=$(cut -d" " -f22 /proc/1/stat); echo $((b + s / $(getconf CLK_TCK)))'
    $epoch = [string](@(Invoke-TbRecWsl $Name @("sh", "-c", $sh)) | Select-Object -First 1)
    if ($epoch -match "^\d+$") { $t.WslStart = ([datetime]"1970-01-01T00:00:00Z").ToUniversalTime().AddSeconds([double]$epoch) }
  } else { $t.WslNotRunning = $true }
  $ev = @(Get-WinEvent -FilterHashtable @{ LogName = "System"; ProviderName = "Microsoft-Windows-Winlogon"; Id = 7001; StartTime = $boot.ToLocalTime() } -ErrorAction SilentlyContinue |
      Sort-Object TimeCreated | Select-Object -First 1)
  if ($ev.Count -gt 0) { $t.FirstSignIn = $ev[0].TimeCreated.ToUniversalTime() }
  return $t
}
function Get-TbRecKeyProbe([string]$Dir) {
  # line 36a: the key probe's own lines (key-probe.ps1 -Collect, which also removes its task); dummy values only
  return @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "key-probe.ps1") -Collect 2>&1 | ForEach-Object { [string]$_ })
}
function Get-TbRecInside([string]$Name) {
  if (-not (Test-TbRecWslRunning $Name)) { return @("WSL2 is not running: nothing read inside it (reading would start it)") }
  $sh = "cd /opt/trialbox 2>/dev/null || exit 0; ip -4 -o addr show dev eth0; grep -E '^TB_(ENV|REHEARSAL)=' deploy/.env 2>/dev/null; " +
  "ls deploy/site/rehearsal.json 2>/dev/null; systemctl is-active docker 2>/dev/null; docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null; " +
  "[ -f deploy/.env ] && python3 -m tools.trialbox doctor --env-file deploy/.env 2>&1 | tail -n 80 | " +
  "PYTHONPATH=libs:. python3 -c 'import sys; from tools.support_bundle import redact_secrets; from tb_common.logging import redact; sys.stdout.write(redact(redact_secrets(sys.stdin.read())[0]))'"
  return @(Invoke-TbRecWsl $Name @("bash", "-c", $sh))
}

# ---- logic
function ConvertFrom-TbWslList([string[]]$Lines) {
  # wsl.exe answers in UTF-16 when WSL_UTF8 is not honoured: its NULs are dropped, as key-probe.ps1 does
  return @($Lines | ForEach-Object { ([string]$_ -replace "`0", "").Trim() } | Where-Object { $_ })
}
function Resolve-TbRecCopyTo([string]$When, [string]$CopyTo) {
  if ($CopyTo) { return $CopyTo }
  if ($When -ne "at-boot") { return "" }
  $m = Find-TbRecMedia
  if ($m) { return (Join-Path $m "P0-RECORD") }
  return ""
}
function Protect-TbRecText([string[]]$Lines) {
  # a BitLocker recovery key is eight groups of six figures; a first-run code follows "One-time code"
  return @($Lines | ForEach-Object {
      $l = [regex]::Replace([string]$_, "\d{6}(-\d{6}){7}", "[a recovery key: not written]")
      if ($l -match "(?i)one-time code") { $l = "[a first-run code: not written]" }
      $l
    })
}
function Format-TbTimeline($Times) {
  # line 26a: does the boot task start WSL2 (and hold it) with nobody signed in? Decided by the task itself: whoever
  # else may have started WSL2 first (the key probe, a person), the box returns only if the boot task runs
  $b = $Times.Boot; $s = $Times.FirstSignIn; $r = $Times.BootTaskLastRun
  if ($null -eq $b) { return "wsl2_started_before_sign_in: unknown (no start of Windows read)" }
  $signin = "nobody signed in since"; if ($null -ne $s) { $signin = "first sign-in {0} s after boot" -f [int]($s - $b).TotalSeconds }
  if ($Times.WslNotRunning) { return ("wsl2_started_before_sign_in: no (WSL2 was not running when this was recorded; {0})" -f $signin) }
  if ($Times.BootTaskState -ne "Running") {
    return ("wsl2_started_before_sign_in: no (the boot task TrialBox-WSL2 is {0}, last result {1}; {2})" -f $Times.BootTaskState, $Times.BootTaskResult, $signin)
  }
  if ($null -eq $r) { return ("wsl2_started_before_sign_in: unknown (the boot task runs, its start time was not read; {0})" -f $signin) }
  $rs = [int]($r - $b).TotalSeconds
  if ($null -ne $s -and $r -ge $s) {
    return ("wsl2_started_before_sign_in: no (the boot task started {0} s after boot, after the first sign-in at {1} s)" -f $rs, [int]($s - $b).TotalSeconds)
  }
  return ("wsl2_started_before_sign_in: yes (the boot task TrialBox-WSL2 runs since {0} s after boot; {1})" -f $rs, $signin)
}
function Write-TbRecord([string]$Out, [string]$When, [string]$StateDir, [string]$Distro, [string]$WslConfig) {
  if (-not (Test-Path -LiteralPath $Out)) { New-Item -ItemType Directory -Force -Path $Out | Out-Null }
  $file = Join-Path $Out ("{0}-{1}.txt" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"), $When)
  $sections = [ordered]@{
    "windows" = { Get-TbRecWindows }
    "wsl" = { Get-TbRecWsl }
    "wslconfig" = { if ($WslConfig -and (Test-Path -LiteralPath $WslConfig)) { @(Get-Content -LiteralPath $WslConfig) } else { @("no .wslconfig read") } }
    "network" = { Get-TbRecNetwork }
    "tasks" = { Get-TbRecTasks }
    "bitlocker" = { Get-TbRecBitLocker }
    "times" = {
      $t = Get-TbRecTimes $Distro
      @(("boot {0:u}; boot task {1}, started {2:u}, last result {3}; WSL2's first process {4:u}; first sign-in {5:u}" -f $t.Boot,
          $t.BootTaskState, $t.BootTaskLastRun, $t.BootTaskResult, $t.WslStart, $t.FirstSignIn), (Format-TbTimeline $t))
    }
    "key probe" = {
      # collected at a start of Windows only, once the probe wrote its result: -Collect removes the probe's task
      if ($When -ne "at-boot") { @("not collected after a run (collected at the next start of Windows)") }
      elseif (-not (Test-TbRecProbeReady)) { @("no result from the probe yet (not armed, or its task has not run at this start)") }
      else { Get-TbRecKeyProbe $StateDir }
    }
    "inside WSL2" = { Get-TbRecInside $Distro }
    "installer log" = { $p = Join-Path $StateDir "box-install.log"; if (Test-Path -LiteralPath $p) { @(Get-Content -LiteralPath $p) } else { @("none") } }
    "console forwarding log" = { $p = Join-Path $StateDir "console-proxy.log"; if (Test-Path -LiteralPath $p) { @(Get-Content -LiteralPath $p) } else { @("none") } }
  }
  # written section by section: a run the task's time limit ends keeps what it had read
  Set-Content -LiteralPath $file -Value ("TrialBox P-0 record, {0}, written {1:u}" -f $When, [DateTime]::UtcNow) -Encoding ASCII
  foreach ($name in $sections.Keys) {
    $lines = @("", ("== {0}" -f $name))
    try { $lines += @(& $sections[$name]) } catch { $lines += ("error: {0}" -f $_.Exception.Message) }
    Add-Content -LiteralPath $file -Value (Protect-TbRecText $lines) -Encoding ASCII
  }
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
$CopyTo = Resolve-TbRecCopyTo $When $CopyTo
if ($CopyTo) { Copy-TbRecords -From $Out -To $CopyTo }
Write-Output ("record={0}" -f $file)
exit 0
