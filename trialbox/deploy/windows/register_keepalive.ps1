# TrialBox: register the start-at-boot task that keeps WSL2 and the stack running (T-210a, D-421; OPS-061).
#
#   powershell -ExecutionPolicy Bypass -File register_keepalive.ps1 -User <windows-account> [-Distro Ubuntu-24.04]
#
# Without it WSL2 stops when nobody is signed in and does not come back after a Windows Update restart. The task
# starts at boot, runs whether or not anyone is signed in (S4U: no password is stored), keeps one wsl.exe open and
# restarts it within a minute when it ends. deploy/windows/box-install.ps1 runs it at step boot-task (NEW-WIN-2,
# D-602); by hand: as administrator, once. check_host.sh --wsl2 checks it. systemd inside the distribution then
# starts Docker and the stack (docker.service, trialbox.service).
param(
  [Parameter(Mandatory = $true)][string]$User,
  [string]$Distro = "Ubuntu-24.04",
  [string]$TaskName = "TrialBox-WSL2"
)
$ErrorActionPreference = "Stop"
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument ("-d {0} --exec /bin/sh -c 'exec sleep infinity'" -f $Distro)
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan) -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Description "TrialBox: keep WSL2 running (T-210a)" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output ("registered and started {0}: wsl.exe -d {1} at startup, signed in or not" -f $TaskName, $Distro)
