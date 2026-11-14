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
  # eth0's IPv4 line as Linux reports it: the address the Windows side reaches WSL2 at. Not `hostname -I`, which
  # also lists docker's bridges and WSL's DNS-tunnel address on lo, in no set order
  return [string](@(& wsl.exe -d $Name -u root --exec ip -4 -o addr show dev eth0 2>$null) -join " ")
}
function Get-TbProxyTable { return @(& netsh.exe interface portproxy show v4tov4 2>$null) }
function Invoke-TbNetsh([string[]]$Arguments) {
  & netsh.exe @Arguments | Out-Null
  return $LASTEXITCODE
}

# ---- logic
function Select-TbWslAddress([string]$Text) {
  # the first "inet a.b.c.d/n" of ip's line that is not a loopback, link-local or WSL's DNS-tunnel address
  foreach ($m in [regex]::Matches($Text, "inet (\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/\d{1,2}")) {
    $parts = @([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value, [int]$m.Groups[4].Value)
    if (@($parts | Where-Object { $_ -gt 255 }).Count -gt 0) { continue }
    $word = $parts -join "."
    if ($parts[0] -eq 127 -or ($parts[0] -eq 169 -and $parts[1] -eq 254) -or $parts[0] -eq 0) { continue }
    if ($word -eq "10.255.255.254") { continue }  # WSL 2.x's DNS tunnel, on lo; Windows cannot reach it
    return $word
  }
  return ""
}
function Get-TbProxyRows([string[]]$Lines) {
  # netsh's table in any display language: the headings differ, the rows are four figures
  $rows = @()
  foreach ($line in $Lines) {
    if ([string]$line -match "^\s*(\S+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$") {
      $rows += @{ ListenAddress = $Matches[1]; ListenPort = [int]$Matches[2]; ConnectAddress = $Matches[3]; ConnectPort = [int]$Matches[4] }
    }
  }
  return $rows
}
function Update-TbConsoleProxy([string]$Distro, [int]$Port) {
  # Returns @{ Status = added | changed | kept | no_address | conflict | refused; Address = WSL2's address or "" }
  $address = Select-TbWslAddress (Get-TbWslAddressText $Distro)
  if (-not $address) { return @{ Status = "no_address"; Address = "" } }
  $rows = @(Get-TbProxyRows (Get-TbProxyTable) | Where-Object { $_.ListenPort -eq $Port })
  # a rule someone made for one address on this port: a second listener would be ambiguous, so it is left to them
  if (@($rows | Where-Object { $_.ListenAddress -ne "0.0.0.0" }).Count -gt 0) { return @{ Status = "conflict"; Address = $address } }
  $now = @($rows | Where-Object { $_.ListenAddress -eq "0.0.0.0" }) | Select-Object -First 1
  if ($null -ne $now -and $now.ConnectAddress -eq $address -and $now.ConnectPort -eq $Port) { return @{ Status = "kept"; Address = $address } }
  $verb = "add"; $status = "added"
  if ($null -ne $now) { $verb = "set"; $status = "changed" }
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
  # the repetition's length is set, not left to the Windows version's default (ten years: as long as the box)
  $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Minutes) -RepetitionDuration (New-TimeSpan -Days 3650)
  $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType S4U -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)  # a hung wsl.exe must not hold off the next runs for days
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
if ($result.Status -eq "no_address" -or $result.Status -eq "refused" -or $result.Status -eq "conflict") { exit 1 }
exit 0
