# M9: the 96 GB profile proof on a Windows 10 or 11 PC with WSL2 (written for the integrator's PC; not run here).
#
#   powershell -ExecutionPolicy Bypass -File tools\prove_profile_96gb.ps1 -Distro Ubuntu -Deploy /home/u/box/deploy `
#       -Out /home/u/m9-proof -Night '<cmd>' -Screen '<cmd>' -Backup '<cmd>' -Restore '<cmd>' [-Gpu 0] [-ExpectUsedMib 3072]
#
# It checks the Windows side first and stops with one line before anything is started: WSL2 present and the distro
# in version 2; the Windows driver sees a card of at least the class's memory (a smaller card cannot be held to the
# class: the profile needs its 97,887 MiB); .wslconfig gives WSL2 at least the two model servers' host caps (the
# record's 48 GiB each; doctor's wsl2_memory judges the whole box once installed). Then it runs
# tools/prove_profile_96gb.sh inside the distro (the same proof as a Linux host: ballast down to the class, utilisations
# scaled, servers pinned to the card, the four steps, rows in -Out/rows.tsv). -ExpectUsedMib is the card memory the
# desktop itself holds (default 3072): above it the card is taken to be in use by something else, and refused.
# The Docker Engine is the one in WSL or Docker Desktop's through its WSL link; the tested range covers both.
# Synthetic data only. Changes nothing on Windows.
param(
  [string]$Distro = "Ubuntu", [int]$Gpu = 0, [int]$ExpectUsedMib = 3072,
  [Parameter(Mandatory)][string]$Deploy, [Parameter(Mandatory)][string]$Out,
  [Parameter(Mandatory)][string]$Night, [Parameter(Mandatory)][string]$Screen,
  [Parameter(Mandatory)][string]$Backup, [Parameter(Mandatory)][string]$Restore
)
$ErrorActionPreference = "Stop"
function Stop-Proof($why) { Write-Host "refused: $why"; exit 2 }
$ClassMib = 97887; $ServerCapsGiB = 96   # deploy/measured/profile_record.rtxpro6000.json: 48 + 48
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Stop-Proof "wsl.exe is not installed (WSL2 is needed)" }
$distros = (& wsl.exe -l -v) -replace "`0", "" | Where-Object { $_ -match "\s$Distro\s" }
if (-not $distros -or $distros -notmatch "\s2\s*$") { Stop-Proof "distro '$Distro' is missing or not WSL version 2 (wsl -l -v)" }

$smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if (-not $smi) { Stop-Proof "nvidia-smi.exe not found: the NVIDIA driver for Windows is not installed" }
$total = [int](& nvidia-smi.exe -i $Gpu --query-gpu=memory.total --format=csv,noheader,nounits | Select-Object -First 1)
if ($total + 512 -lt $ClassMib) { Stop-Proof "card $Gpu has $total MiB; the class needs $ClassMib MiB (a smaller card cannot be held to it)" }

$cfg = Join-Path $env:USERPROFILE ".wslconfig"
$mem = if (Test-Path $cfg) { (Select-String -Path $cfg -Pattern '^\s*memory\s*=\s*(\d+)\s*GB' -CaseSensitive:$false | Select-Object -First 1) } else { $null }
if (-not $mem) { Stop-Proof ".wslconfig has no memory=<n>GB line: WSL2 would take its default, not the class's caps" }
if ([int]$mem.Matches[0].Groups[1].Value -lt $ServerCapsGiB) { Stop-Proof ".wslconfig gives WSL2 $($mem.Matches[0].Groups[1].Value) GB, less than the model servers' caps ($ServerCapsGiB GB)" }

# the arguments go through a file, never through the command line's quoting
$repoWsl = (& wsl.exe -d $Distro -- wslpath -a ($Repo.Path -replace '\\', '/')).Trim()
function Q($s) { "'" + ($s -replace "'", "'\''") + "'" }
$run = "#!/usr/bin/env bash`ncd $(Q $repoWsl) && exec tools/prove_profile_96gb.sh --gpu $Gpu --expect-used $ExpectUsedMib " +
  "--deploy $(Q $Deploy) --out $(Q $Out) --night $(Q $Night) --screen $(Q $Screen) --backup $(Q $Backup) --restore $(Q $Restore)`n"
$tmp = Join-Path $env:TEMP "tb-m9-run.sh"
[IO.File]::WriteAllText($tmp, $run, (New-Object Text.UTF8Encoding($false)))
$tmpWsl = (& wsl.exe -d $Distro -- wslpath -a ($tmp -replace '\\', '/')).Trim()
& wsl.exe -d $Distro -u root -- bash $tmpWsl
$rc = $LASTEXITCODE
Remove-Item $tmp -ErrorAction SilentlyContinue
Write-Host "rows: $Out/rows.tsv (inside $Distro); exit $rc"
exit $rc
