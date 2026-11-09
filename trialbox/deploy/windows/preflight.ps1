# TrialBox pre-flight check on the Windows workstation (D-125, D-138). Groundwork for the offline installer, which is
# built after the platform; run it before an install and keep the output with the install record.
#
#   powershell -ExecutionPolicy Bypass -File preflight.ps1 [-DataDrive D:] [-MinFreeGB 500] [-MinRamGB 64]
#
# Prints one PASS or FAIL line per check and exits 1 when any check fails. Reads only; changes nothing; needs no
# network. Then run deploy/windows/preflight.sh inside the WSL2 Ubuntu (the same checks from the Linux side).
param(
  [string]$DataDrive = $env:SystemDrive,
  [int]$MinFreeGB = 500,
  [int]$MinRamGB = 64
)
$ErrorActionPreference = "Continue"
$script:Failed = 0
function Line([bool]$ok, [string]$what, [string]$detail) {
  if ($ok) { Write-Output ("PASS  {0}: {1}" -f $what, $detail) }
  else { Write-Output ("FAIL  {0}: {1}" -f $what, $detail); $script:Failed++ }
}

# 1. Windows build and edition: Windows 11 Pro / Enterprise (build 22000 or later) or Windows Server 2022+ (20348+)
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$caption = [string]$os.Caption
$server = $os.ProductType -ne 1
$edition_ok = $server -or $caption -match "Pro|Enterprise|Education"
$build_ok = if ($server) { $build -ge 20348 } else { $build -ge 22000 }
Line ($build_ok -and $edition_ok) "Windows build" ("{0}, build {1} (need Windows 11 Pro/Enterprise 22000+ or Server 2022 20348+)" -f $caption, $build)

# 2. CPU virtualisation: on in the firmware, or a hypervisor already running (WSL2 needs it)
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs = Get-CimInstance Win32_ComputerSystem
$virt = [bool]$cpu.VirtualizationFirmwareEnabled -or [bool]$cs.HypervisorPresent
Line $virt "CPU virtualisation" ("firmware {0}, hypervisor {1}" -f $cpu.VirtualizationFirmwareEnabled, $cs.HypervisorPresent)

# 3. WSL2: installed, default version 2, a distribution on version 2
$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if ($null -eq $wsl) {
  Line $false "WSL2" "wsl.exe not found: install WSL from the offline media (OFFLINE-MEDIA.md, windows/)"
} else {
  $list = (& wsl.exe --list --verbose 2>$null | Out-String) -replace "`0", ""
  $v2 = $list -match "\s2\s*(\r?\n|$)"
  $status = (& wsl.exe --status 2>$null | Out-String) -replace "`0", ""
  $default2 = $status -match "(Default Version|既定のバージョン|預設版本)\s*:\s*2"
  Line ($v2) "WSL2" ("distribution on version 2: {0}; default version 2: {1}" -f $v2, $default2)
}

# 4. GPU driver: an NVIDIA card and the Windows driver (WSL2 uses the Windows driver; never install one in Linux)
$smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if ($null -eq $smi) {
  Line $false "GPU driver" "nvidia-smi.exe not found: install the NVIDIA driver for Windows from the offline media"
} else {
  $q = (& nvidia-smi.exe --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null | Select-Object -First 1)
  Line ([bool]$q) "GPU driver" ("{0}" -f $q)
}

# 5. Disk space on the data drive (images and models about 30 GB; the box's data and backups the rest)
$drive = Get-PSDrive -Name $DataDrive.TrimEnd(":", "\") -ErrorAction SilentlyContinue
$free = if ($drive) { [math]::Floor($drive.Free / 1GB) } else { 0 }
Line ($free -ge $MinFreeGB) "Disk space" ("{0} GB free on {1} (need {2} GB)" -f $free, $DataDrive, $MinFreeGB)

# 6. Memory (WSL2 gets half of it by default; .wslconfig raises that)
$ram = [math]::Floor($cs.TotalPhysicalMemory / 1GB)
Line ($ram -ge $MinRamGB) "Memory" ("{0} GB (need {1} GB)" -f $ram, $MinRamGB)

if ($script:Failed -gt 0) { Write-Output ("{0} check(s) FAILED: fix them before installing (WINDOWS-INSTALL-CHECKLIST.md)" -f $script:Failed); exit 1 }
Write-Output "all checks passed"
exit 0
