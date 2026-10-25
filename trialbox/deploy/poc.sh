#!/usr/bin/env bash
# TrialBox proof of concept in one command (docs/RUNBOOK.md §9, README "Try the POC in 10 minutes").
#
#   deploy/poc.sh                          # stub model (no GPU, no key): any Docker host
#   TB_LLM_MODE=openrouter deploy/poc.sh   # OpenRouter (D0 synthetic data only); key from OPENROUTER_API_KEY or
#                                          #   deploy/poc/secrets/openrouter_api_key (never stored in the repository)
#   TB_LLM_MODE=gpu deploy/poc.sh          # local GPU (vLLM; DGX Spark / GB10 adds docker-compose.gb10.yml); needs a
#                                          #   pinned model in deploy/site (make spark-e2e or tools/pin_model.py)
#   deploy/poc.sh down                     # stop (volumes kept);  deploy/poc.sh reset  # stop and delete volumes
#   deploy/poc.sh status                   # URLs and container states
#
# Steps: Docker check -> deploy/.env with random secrets (first run only) -> images (built when missing, or always with
# TB_POC_BUILD=1) -> POC settings with the administrator's mailbox -> compose up (box + GreenMail + MailHog + console)
# -> console administrator (random password printed once) -> ingest synthetic site A -> URLs.
# Knobs: TB_POC_ADMIN_EMAIL (admin@hospa.test), TB_POC_BIND (127.0.0.1), TB_HOST_CONSOLE_PORT (8090),
# TB_HOST_MAILHOG_PORT (8025), TB_POC_MAIL=real (your own mailbox from deploy/.env, RUNBOOK §9), TB_OPENROUTER_MODEL, TB_POC_UP_TIMEOUT (s, 900), TB_POC_SKIP_INGEST=1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE="${TB_LLM_MODE:-stub}"
ACTION="${1:-up}"
POC="$ROOT/deploy/poc"
ADMIN_EMAIL="${TB_POC_ADMIN_EMAIL:-admin@hospa.test}"
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
IMAGE_JVM="${TB_JVM_IMAGE:-trialbox-jvm:1.0.0}"
OPENROUTER_MODEL="${TB_OPENROUTER_MODEL:-nvidia/nemotron-3-nano-30b-a3b}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'poc: %s\n' "$*" >&2; exit 1; }
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
envfile_get() { [ -f deploy/.env ] && sed -n "s/^$1=//p" deploy/.env | tail -1 | tr -d "\"'" || true; }

command -v docker >/dev/null || die "Docker is not installed (Docker Desktop, or Docker Engine 27+ with compose)"
docker info >/dev/null 2>&1 || die "Docker is not running (start Docker Desktop, or: sudo systemctl start docker)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is missing"

export TB_SETTINGS_FILE="./poc/settings.yaml"
export TB_POC_ADMIN_EMAIL="$ADMIN_EMAIL"
export TB_DATA_CLASS=D0
export TB_HOST_MAILHOG_PORT="${TB_HOST_MAILHOG_PORT:-$(envfile_get TB_HOST_MAILHOG_PORT)}"
export TB_HOST_MAILHOG_PORT="${TB_HOST_MAILHOG_PORT:-8025}"
export TB_HOST_CONSOLE_PORT="${TB_HOST_CONSOLE_PORT:-$(envfile_get TB_HOST_CONSOLE_PORT)}"
export TB_HOST_CONSOLE_PORT="${TB_HOST_CONSOLE_PORT:-8090}"
export TB_CONSOLE_WEBMAIL_URL="http://127.0.0.1:$TB_HOST_MAILHOG_PORT"

COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml)
MAILPROF=(--profile test)
if [ "${TB_POC_MAIL:-test}" = real ]; then  # your own mailbox (IMAP_*/SMTP_* in deploy/.env): no GreenMail/MailHog
  MAILPROF=(); export TB_CONSOLE_TEST_SMTP="" TB_CONSOLE_WEBMAIL_URL="${TB_POC_WEBMAIL_URL:-}"
fi
case "$MODE" in
  stub)
    COMPOSE+=(-f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile stub ${MAILPROF[@]+"${MAILPROF[@]}"})
    export TB_ENV=TEST TB_GATEWAY_MODEL="" TB_SITE_DIR="./poc/site" ;;
  openrouter)
    COMPOSE+=(-f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile stub ${MAILPROF[@]+"${MAILPROF[@]}"})
    export TB_ENV=DEV TB_GATEWAY_MODEL=j-workhorse TB_SITE_DIR="./poc/site" ;;
  gpu)
    if [ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "arm64" ]; then COMPOSE+=(-f deploy/docker-compose.gb10.yml); fi
    COMPOSE+=(-f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile gpu ${MAILPROF[@]+"${MAILPROF[@]}"})
    export TB_ENV=TEST TB_GATEWAY_MODEL=j-workhorse TB_SITE_DIR="${TB_SITE_DIR:-./site}" ;;
  *) die "TB_LLM_MODE must be stub, openrouter or gpu (got $MODE)" ;;
esac

urls() {
  local bind="${TB_POC_BIND:-127.0.0.1}"
  cat <<EOF

  TrialBox POC ($MODE model)
  Console (sign in as admin):   http://$bind:$TB_HOST_CONSOLE_PORT
  Web mail (box's outgoing):    http://127.0.0.1:$TB_HOST_MAILHOG_PORT
  Send mail to the box:         SMTP 127.0.0.1:${TB_HOST_SMTP_PORT:-3025}, To: $(envfile_get MAIL_INTAKE_ADDR), From: $ADMIN_EMAIL
                                (or the console's "Test mailbox" page; tools/send_test_mail.py "FEAS GZQO" --sender $ADMIN_EMAIL)
  Stop: deploy/poc.sh down      Reset everything: deploy/poc.sh reset
EOF
}

case "$ACTION" in
  down) "${COMPOSE[@]}" down; exit 0 ;;
  reset) "${COMPOSE[@]}" down -v; exit 0 ;;
  status) "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'; urls; exit 0 ;;
  up) ;;
  *) die "usage: deploy/poc.sh [up|down|reset|status]" ;;
esac

# ------------------------------------------------------------------------------------------------ secrets
mkdir -p "$POC/secrets" "$POC/site"
chmod 700 "$POC/secrets"
if [ ! -f deploy/.env ]; then
  say "creating deploy/.env with random service passwords"
  sed -e "s/^MINIO_SECRET_KEY=.*/MINIO_SECRET_KEY=$(rand 32)/" \
      -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(rand 32)/" \
      -e "s/^POSTGRES_WF_PASSWORD=.*/POSTGRES_WF_PASSWORD=$(rand 32)/" .env.example > deploy/.env
  chmod 600 deploy/.env
elif grep -q 'change-me' deploy/.env; then
  echo "poc: note: deploy/.env still has change-me passwords (kept: existing volumes were created with them)" >&2
fi
if [ ! -s .cache/test-secrets/site_hmac.key ]; then  # pseudonymisation key of the synthetic site (test overlay mount)
  install -d -m 0777 .cache/test-secrets
  rand 48 > .cache/test-secrets/site_hmac.key && chmod 0644 .cache/test-secrets/site_hmac.key
fi
if [ "$MODE" = openrouter ]; then
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -s "$POC/secrets/openrouter_api_key" ]; then
    OPENROUTER_API_KEY="$(tr -d '\r\n' < "$POC/secrets/openrouter_api_key")"
  fi
  [ -n "${OPENROUTER_API_KEY:-}" ] || die "openrouter mode: set OPENROUTER_API_KEY or put the key in deploy/poc/secrets/openrouter_api_key"
  export OPENROUTER_API_KEY
fi

# ------------------------------------------------------------------------------------------------ images
build_images() {
  # the font step needs fontTools: prefer the project venv, else a host python3 that has it
  local py=""
  for cand in "$ROOT/.venv/bin/python" "$(command -v python3 || true)"; do
    if [ -x "$cand" ] && "$cand" -c 'import fontTools' 2>/dev/null; then py="$cand"; break; fi
  done
  if command -v mvn >/dev/null && [ -n "$py" ] && command -v curl >/dev/null; then
    make images PY="$py"
  else  # no build tools on the host: fetch the build inputs in a throwaway builder container
    say "fetching fonts and JVM build inputs in a builder container"
    docker run --rm -v "$ROOT:/src" -w /src "${TB_BUILDER_IMAGE:-maven:3.9.9-eclipse-temurin-17}" bash -c \
      'apt-get update -qq && apt-get install -y -qq python3 python3-fonttools curl >/dev/null && PY=python3 bash tools/fetch_jvm_deps.sh && python3 tools/fetch_fonts.py'
    docker build -f deploy/docker/python.Dockerfile -t trialbox-py:1.0.0 .
    docker build -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .
  fi
}
if [ "${TB_POC_BUILD:-0}" = 1 ] || ! docker image inspect "$IMAGE_PY" "$IMAGE_JVM" >/dev/null 2>&1; then
  say "building images (first run: ~10-20 min)"
  build_images
else
  say "using images $IMAGE_PY and $IMAGE_JVM (TB_POC_BUILD=1 rebuilds)"
fi

# ------------------------------------------------------------------------------------------------ settings, model pin
say "POC settings for administrator mailbox $ADMIN_EMAIL"
docker run --rm -v "$POC:/out" --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m console.cli poc-settings \
  --in /app/deploy/settings.example.yaml --out /out/settings.yaml --admin-email "$ADMIN_EMAIL"
if [ "$MODE" = openrouter ]; then
  say "pinning j-workhorse to OpenRouter model $OPENROUTER_MODEL (DEV, D0 only)"
  docker run --rm -v "$POC/site:/out" --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m console.cli \
    poc-openrouter-pin --model "$OPENROUTER_MODEL" --out /out/registry.site.yaml
elif [ "$MODE" = gpu ]; then
  [ -s "deploy/${TB_SITE_DIR#./}/registry.site.yaml" ] \
    || die "gpu mode: no pinned model in deploy/${TB_SITE_DIR#./}/registry.site.yaml (run make spark-e2e once, or tools/pin_model.py; RUNBOOK §8)"
fi

# ------------------------------------------------------------------------------------------------ up
say "starting the stack ($MODE model); first start pulls images and takes a few minutes"
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" rm -sf gateway >/dev/null 2>&1 || true   # the gateway reads model pins at start
"${COMPOSE[@]}" up -d --wait --wait-timeout "${TB_POC_UP_TIMEOUT:-900}" \
  || { "${COMPOSE[@]}" ps; die "the stack did not become healthy (deploy/poc.sh status; docker compose logs)"; }

say "console administrator"
"${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin --mailbox "$ADMIN_EMAIL"

if [ "${TB_POC_SKIP_INGEST:-0}" != 1 ]; then
  say "ingesting synthetic site A (600 patients)"
  "${COMPOSE[@]}" exec -T console python -m console.cli ingest || echo "poc: ingest did not pass; retry from the console Overview page" >&2
fi
urls
