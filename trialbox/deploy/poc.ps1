# TrialBox proof of concept in one command on Windows (Docker Desktop). Same steps as deploy/poc.sh.
#
#   powershell -ExecutionPolicy Bypass -File deploy\poc.ps1                    # stub model (no GPU, no key)
#   $env:TB_LLM_MODE="openrouter"; powershell -ExecutionPolicy Bypass -File deploy\poc.ps1
#        key from $env:OPENROUTER_API_KEY or deploy\poc\secrets\openrouter_api_key (never stored in the repository)
#   powershell -File deploy\poc.ps1 down | reset | status
#
# GPU mode is for Linux hosts (DGX Spark, NVIDIA servers): use deploy/poc.sh there. WSL2 users can also run
# deploy/poc.sh from their Ubuntu shell with Docker Desktop's WSL integration.
param([string]$Action = "up")
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Mode = if ($env:TB_LLM_MODE) { $env:TB_LLM_MODE } else { "stub" }
$Poc = Join-Path $Root "deploy\poc"
$AdminEmail = if ($env:TB_POC_ADMIN_EMAIL) { $env:TB_POC_ADMIN_EMAIL } else { "admin@hospa.test" }
$ImagePy = if ($env:TB_IMAGE) { $env:TB_IMAGE } else { "trialbox-py:1.0.0" }
$ImageJvm = if ($env:TB_JVM_IMAGE) { $env:TB_JVM_IMAGE } else { "trialbox-jvm:1.0.0" }
$OpenRouterModel = if ($env:TB_OPENROUTER_MODEL) { $env:TB_OPENROUTER_MODEL } else { "nvidia/nemotron-3-nano-30b-a3b" }

function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "poc: $m" -ForegroundColor Red; exit 1 }
function Rand([int]$n = 32) {
  $chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".ToCharArray()
  $bytes = New-Object byte[] $n
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}
function Run([string[]]$cmd) {
  & $cmd[0] $cmd[1..($cmd.Length - 1)]
  if ($LASTEXITCODE -ne 0) { Die "failed: $($cmd -join ' ')" }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "Docker Desktop is not installed" }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Die "Docker Desktop is not running" }

$env:TB_SETTINGS_FILE = "./poc/settings.yaml"
$env:TB_POC_ADMIN_EMAIL = $AdminEmail
$env:TB_DATA_CLASS = "D0"
if (-not $env:TB_HOST_MAILHOG_PORT) { $env:TB_HOST_MAILHOG_PORT = "8025" }
if (-not $env:TB_HOST_CONSOLE_PORT) { $env:TB_HOST_CONSOLE_PORT = "8090" }
$env:TB_CONSOLE_WEBMAIL_URL = "http://127.0.0.1:$($env:TB_HOST_MAILHOG_PORT)"
$Compose = @("docker", "compose", "--project-directory", "deploy", "-f", "deploy/docker-compose.yml",
  "-f", "deploy/docker-compose.test.yml", "-f", "deploy/docker-compose.poc.yml", "--profile", "stub", "--profile", "test")
switch ($Mode) {
  "stub" { $env:TB_ENV = "TEST"; $env:TB_GATEWAY_MODEL = ""; $env:TB_SITE_DIR = "./poc/site" }
  "openrouter" { $env:TB_ENV = "DEV"; $env:TB_GATEWAY_MODEL = "j-workhorse"; $env:TB_SITE_DIR = "./poc/site" }
  default { Die "TB_LLM_MODE must be stub or openrouter on Windows (gpu: use deploy/poc.sh on the GPU host)" }
}

function Show-Urls {
  $bind = if ($env:TB_POC_BIND) { $env:TB_POC_BIND } else { "127.0.0.1" }
  Write-Host ""
  Write-Host "  TrialBox POC ($Mode model)"
  Write-Host "  Console (sign in as admin):   http://$($bind):$($env:TB_HOST_CONSOLE_PORT)"
  Write-Host "  Web mail (box's outgoing):    http://127.0.0.1:$($env:TB_HOST_MAILHOG_PORT)"
  Write-Host "  Send mail to the box:         the console's Test mailbox page, or SMTP 127.0.0.1:3025 From $AdminEmail"
  Write-Host "  Stop: deploy\poc.ps1 down     Reset everything: deploy\poc.ps1 reset"
}

switch ($Action) {
  "down" { Run ($Compose + @("down")); exit 0 }
  "reset" { Run ($Compose + @("down", "-v")); exit 0 }
  "status" { Run ($Compose + @("ps")); Show-Urls; exit 0 }
  "up" { }
  default { Die "usage: deploy\poc.ps1 [up|down|reset|status]" }
}

# ---------------------------------------------------------------- secrets
New-Item -ItemType Directory -Force -Path (Join-Path $Poc "secrets"), (Join-Path $Poc "site") | Out-Null
$EnvFile = Join-Path $Root "deploy\.env"
if (-not (Test-Path $EnvFile)) {
  Say "creating deploy\.env with random service passwords"
  (Get-Content (Join-Path $Root ".env.example")) `
    -replace '^MINIO_SECRET_KEY=.*', "MINIO_SECRET_KEY=$(Rand 32)" `
    -replace '^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$(Rand 32)" `
    -replace '^POSTGRES_WF_PASSWORD=.*', "POSTGRES_WF_PASSWORD=$(Rand 32)" |
    Set-Content -Encoding ascii $EnvFile
}
$KeyDir = Join-Path $Root ".cache\test-secrets"
if (-not (Test-Path (Join-Path $KeyDir "site_hmac.key"))) {
  New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null
  [System.IO.File]::WriteAllText((Join-Path $KeyDir "site_hmac.key"), (Rand 48))
}
if ($Mode -eq "openrouter") {
  $keyFile = Join-Path $Poc "secrets\openrouter_api_key"
  if (-not $env:OPENROUTER_API_KEY -and (Test-Path $keyFile)) { $env:OPENROUTER_API_KEY = (Get-Content $keyFile -Raw).Trim() }
  if (-not $env:OPENROUTER_API_KEY) { Die "openrouter mode: set OPENROUTER_API_KEY or put the key in deploy\poc\secrets\openrouter_api_key" }
}

# ---------------------------------------------------------------- images
docker image inspect $ImagePy $ImageJvm *> $null
if ($env:TB_POC_BUILD -eq "1" -or $LASTEXITCODE -ne 0) {
  Say "building images in a builder container (first run: ~15-25 min)"
  $builder = if ($env:TB_BUILDER_IMAGE) { $env:TB_BUILDER_IMAGE } else { "maven:3.9.9-eclipse-temurin-17" }
  Run @("docker", "run", "--rm", "-v", "$($Root):/src", "-w", "/src", $builder, "bash", "-c",
    "apt-get update -qq && apt-get install -y -qq python3 curl >/dev/null && PY=python3 bash tools/fetch_jvm_deps.sh && python3 tools/fetch_fonts.py")
  Run @("docker", "build", "-f", "deploy/docker/python.Dockerfile", "-t", "trialbox-py:1.0.0", ".")
  Run @("docker", "build", "-f", "deploy/docker/jvm.Dockerfile", "-t", "trialbox-jvm:1.0.0", ".")
} else { Say "using images $ImagePy and $ImageJvm (set TB_POC_BUILD=1 to rebuild)" }

# ---------------------------------------------------------------- settings, model pin
Say "POC settings for administrator mailbox $AdminEmail"
Run @("docker", "run", "--rm", "-v", "$($Poc):/out", $ImagePy, "python", "-m", "console.cli", "poc-settings",
  "--in", "/app/deploy/settings.example.yaml", "--out", "/out/settings.yaml", "--admin-email", $AdminEmail)
if ($Mode -eq "openrouter") {
  Say "pinning j-workhorse to OpenRouter model $OpenRouterModel (DEV, D0 only)"
  Run @("docker", "run", "--rm", "-v", "$(Join-Path $Poc 'site'):/out", $ImagePy, "python", "-m", "console.cli",
    "poc-openrouter-pin", "--model", $OpenRouterModel, "--out", "/out/registry.site.yaml")
}

# ---------------------------------------------------------------- up
Say "starting the stack ($Mode model); the first start pulls images and takes a few minutes"
& $Compose[0] $Compose[1..($Compose.Length - 1)] rm -sf gateway *> $null
Run ($Compose + @("up", "-d", "--wait", "--wait-timeout", "900"))
Say "console administrator"
Run ($Compose + @("exec", "-T", "console", "python", "-m", "console.cli", "bootstrap-admin", "--username", "admin", "--mailbox", $AdminEmail))
if ($env:TB_POC_SKIP_INGEST -ne "1") {
  Say "ingesting synthetic site A (600 patients)"
  & $Compose[0] $Compose[1..($Compose.Length - 1)] exec -T console python -m console.cli ingest
  if ($LASTEXITCODE -ne 0) { Write-Host "poc: ingest did not pass; retry from the console Overview page" }
}
Show-Urls
