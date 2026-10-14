<#
.SYNOPSIS
  Install and start local TrialGPT on Windows with an NVIDIA GPU (e.g. RTX 3080).

.DESCRIPTION
  Installs what is missing (git, Ollama, uv) with winget, picks a Gemma 4 size from the GPU memory, pulls it,
  clones the code, creates a Python 3.12 environment and starts the interface on http://127.0.0.1:8090.
  Run it again any time: finished steps are skipped and the code is updated.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -Model gemma4:12b
#>
param(
    [string]$Model = "",                                # default: chosen from GPU memory
    [string]$Dir = "$HOME\TrialGPT",
    [string]$Branch = "claude/trialgpt-local-lcvm9p",
    [int]$NumCtx = 16384,
    [switch]$NoStart
)
$ErrorActionPreference = "Stop"

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Need([string]$cmd, [string]$wingetId) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) { return }
    Write-Host "Installing $wingetId ..." -ForegroundColor Cyan
    winget install --id $wingetId -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "$cmd is still not on PATH: open a new PowerShell window and run this script again."
    }
}

Need git Git.Git
Need ollama Ollama.Ollama
Need uv astral-sh.uv

# 1. Model: largest Gemma 4 that leaves room for a 16k context on this GPU
if (-not $Model) {
    $mib = 0
    try { $mib = [int](& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    if ($mib -ge 16000) { $Model = "gemma4:12b" } elseif ($mib -ge 6000) { $Model = "gemma4:e4b" } else { $Model = "gemma4:e2b" }
    Write-Host "GPU memory: $mib MiB -> $Model (override with -Model)" -ForegroundColor Cyan
}

# 2. Ollama server (the Windows app normally runs it in the background)
function Ollama-Up { try { Invoke-RestMethod -TimeoutSec 2 http://127.0.0.1:11434/api/version | Out-Null; $true } catch { $false } }
if (-not (Ollama-Up)) {
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30 -and -not (Ollama-Up); $i++) { Start-Sleep 1 }
    if (-not (Ollama-Up)) { throw "Ollama did not start: launch the Ollama app, then run this script again." }
}
Write-Host "Pulling $Model ..." -ForegroundColor Cyan
ollama pull $Model

# 3. Code
if (Test-Path "$Dir\.git") {
    git -C $Dir fetch origin $Branch
    git -C $Dir checkout $Branch
    git -C $Dir pull --ff-only origin $Branch
} else {
    git clone --branch $Branch --depth 1 https://github.com/zandis/Auto-GPT.git $Dir
}
$app = Join-Path $Dir "trialgpt"
Set-Location $app

# 4. Python environment (CPU torch is enough: only the small MedCPT retrievers use it)
$py = Join-Path $app ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { uv venv -p 3.12 .venv }
uv pip install --python $py -e .
& $py -c "import nltk; nltk.download('punkt_tab', quiet=True); nltk.download('punkt', quiet=True)"

# 5. Launcher
$start = Join-Path $app "start-trialgpt.ps1"
@"
`$env:TG_LLM_MODEL = "$Model"
`$env:TG_LLM_NUM_CTX = "$NumCtx"
`$env:TG_LLM_THINK = "false"
Set-Location "$app"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-Command", "Start-Sleep 6; Start-Process http://127.0.0.1:8090"
& "$py" -m trialgpt_local.app
"@ | Set-Content -Encoding UTF8 $start
Write-Host "Installed. Start it any time with: powershell -ExecutionPolicy Bypass -File `"$start`"" -ForegroundColor Green

if (-not $NoStart) { & $start }
