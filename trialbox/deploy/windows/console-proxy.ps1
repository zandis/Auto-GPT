# TrialBox: keep the console's forwarding rule pointed at WSL2 on Windows 10 (NEW-WIN-10, D-613; owner ruling D-503).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File console-proxy.ps1 [-Distro TrialBox] [-Port 443]
#   powershell -NoProfile -ExecutionPolicy Bypass -File console-proxy.ps1 -Register -User <account> [-EveryMinutes 5]
#
# Windows 10 has no mirrored networking for WSL2: WSL2 sits behind an address of its own, which changes at every
# start of WSL2. One rule of Windows' port proxy (netsh interface portproxy) passes the console's port, and only it,
# from this PC to WSL2's address. box-install.ps1 copies this script beside its state (a folder only administrators
# write to) and registers a task that runs it at startup and every few minutes, signed in or not (S4U, as the boot
# task). It changes the rule only when WSL2's address has changed, and writes one line to its log each time it does.
# Windows Firewall, not this rule, decides who may reach the port (box-install.ps1, Set-TbHostFirewall).
# Every Windows command is behind a function below, so the logic is tested with Pester on PowerShell 7
# (tests/windows/console-proxy.Tests.ps1). Keep this file ASCII and in Windows PowerShell 5.1 syntax.
[CmdletBinding()]
param(
  [ValidatePattern("^[A-Za-z0-9._-]+$")][string]$Distro = "TrialBox",
  [ValidateRange(1, 65535)][int]$Port = 443,
  [string]$LogPath = "",
  [switch]$Register,
  [string]$User = "",
  [ValidateRange(1, 60)][int]$EveryMinutes = 5,
  [string]$TaskName = "TrialBox-Console-Proxy",
  [switch]$LoadOnly
)

# ---- seams: the only places that touch Windows
function Get-TbWslAddressText([string]$Name) {
  # WSL2's addresses as Linux reports them, one line, separated by spaces
  return [string](& wsl.exe -d $Name -u root --exec hostname -I 2>$null)
}
function Get-TbProxyTable { return @(& netsh.exe interface portproxy show v4tov4 2>$null) }
function Invoke-TbNetsh([string[]]$Arguments) {
  & netsh.exe @Arguments | Out-Null
  return $LASTEXITCODE
}

# ---- logic
function Select-TbWslAddress([string]$Text) {
  # the first IPv4 address that is not a loopback or a link-local one
  foreach ($word in ($Text -split "\s+")) {
    if ($word -notmatch "^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$") { continue }
    $parts = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], [int]$Matches[4])
    if (@($parts | Where-Object { $_ -gt 255 }).Count -gt 0) { continue }
    if ($parts[0] -eq 127 -or ($parts[0] -eq 169 -and $parts[1] -eq 254) -or $parts[0] -eq 0) { continue }
    return $word
  }
  return ""
}
function Get-TbProxyTarget([string[]]$Lines, [int]$ListenPort) {
  # netsh's table in any display language: the headings differ, the rows are four figures
  foreach ($line in $Lines) {
    if ([string]$line -match "^\s*(\S+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$") {
      if ($Matches[1] -eq "0.0.0.0" -and [int]$Matches[2] -eq $ListenPort) { return $Matches[3] }
    }
  }
  return ""
}
function Update-TbConsoleProxy([string]$Distro, [int]$Port) {
  # Returns @{ Status = added | changed | kept | no_address | refused; Address = WSL2's address or "" }
  $address = Select-TbWslAddress (Get-TbWslAddressText $Distro)
  if (-not $address) { return @{ Status = "no_address"; Address = "" } }
  $now = Get-TbProxyTarget (Get-TbProxyTable) $Port
  if ($now -eq $address) { return @{ Status = "kept"; Address = $address } }
  $verb = "add"; $status = "added"
  if ($now) { $verb = "set"; $status = "changed" }
  $rc = Invoke-TbNetsh @("interface", "portproxy", $verb, "v4tov4", ("listenport={0}" -f $Port), "listenaddress=0.0.0.0",
    ("connectport={0}" -f $Port), ("connectaddress={0}" -f $address))
  if ($rc -ne 0) { return @{ Status = "refused"; Address = $address } }
  return @{ Status = $status; Address = $address }
}
function Write-TbProxyLog([string]$Path, [string]$Text) {
  if (-not $Path) { return }
  $line = "{0} {1}" -f [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"), $Text
  $old = @()
  if (Test-Path -LiteralPath $Path) { $old = @(Get-Content -LiteralPath $Path) }
  # the last 200 lines: a few weeks of address changes, never a growing file
  $keep = @($old + $line | Select-Object -Last 200)
  Set-Content -LiteralPath $Path -Value $keep -Encoding ASCII
}

function Register-TbConsoleProxyTask([string]$Account, [string]$Name, [int]$Minutes) {
  # at startup and every few minutes after, signed in or not (S4U: no password is stored), with administrator rights
  # (only an administrator changes the port proxy); the task runs this very file
  $self = $PSCommandPath
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"{0}`" -Distro {1} -Port {2}" -f $self, $Distro, $Port)
  $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
  $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType S4U -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger @((New-ScheduledTaskTrigger -AtStartup), $repeat) -Principal $principal `
    -Settings $settings -Description "TrialBox: keep the console's forwarding pointed at WSL2 (NEW-WIN-10)" -Force | Out-Null
}

if ($LoadOnly) { return }
if ($Register) {
  if (-not $User) { Write-Output "console-proxy: -Register needs -User <the box owner's account>"; exit 2 }
  Register-TbConsoleProxyTask $User $TaskName $EveryMinutes
  Write-Output ("registered {0}: at startup and every {1} minutes, signed in or not" -f $TaskName, $EveryMinutes)
  exit 0
}
if (-not $LogPath) { $LogPath = Join-Path $PSScriptRoot "console-proxy.log" }
$result = Update-TbConsoleProxy -Distro $Distro -Port $Port
if ($result.Status -ne "kept") {
  Write-TbProxyLog $LogPath ("console forwarding: {0}, port {1} to WSL2 at {2}" -f $result.Status, $Port, $result.Address)
}
Write-Output ("status={0} address={1}" -f $result.Status, $result.Address)
if ($result.Status -eq "no_address" -or $result.Status -eq "refused") { exit 1 }
exit 0
