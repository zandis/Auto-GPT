#!/usr/bin/env bash
# TrialBox proof of concept in one command (docs/RUNBOOK.md §9, README "Try the POC in 10 minutes").
#
#   deploy/poc.sh                          # stub model (no GPU, no key): any Docker host
#   OpenRouter (D0 synthetic data only). Run in your own Bash shell:
#   read -rs OPENROUTER_API_KEY; export OPENROUTER_API_KEY
#   sudo --preserve-env=OPENROUTER_API_KEY TB_LLM_MODE=openrouter deploy/poc.sh
#   unset OPENROUTER_API_KEY
#   sudo VAR=value command shows the value in the process list.
#   TB_LLM_MODE=gpu deploy/poc.sh          # the real pair on a plain GPU VM (D-839): rtxpro6000 or gb10 (deploy/
#                                          #   gpu_profile.sh, or TB_GPU_PROFILE); the weights in deploy/models (the
#                                          #   pinned builds of models/registry.yaml); checks, pins, starts, canary
#   TB_POC_EMBED=model deploy/poc.sh       # the stub (or OpenRouter) judge with the REAL embedder (e-embed-1) on the
#                                          #   CPU, from the pinned weights in deploy/models/embedder (card 24-7,
#                                          #   RUNBOOK §28 and §29); kept in deploy/.env for later starts
#   deploy/poc.sh down                     # stop (volumes kept);  deploy/poc.sh reset  # stop and delete volumes
#   deploy/poc.sh status                   # URLs and container states
#   deploy/poc.sh report                   # what to send back: states, memory, the embedder's mode and pin (no
#                                          #   address, password, folder or host name)
#
# Steps: Docker check -> deploy/.env with random secrets (first run only) -> images (built when missing, or always with
# TB_POC_BUILD=1) -> POC settings with the administrator's mailbox -> compose up (box + GreenMail + MailHog + console)
# -> console administrator (random password printed once) -> ingest synthetic site A -> URLs.
# Knobs: TB_POC_ADMIN_EMAIL (admin@hospa.test), TB_POC_BIND (127.0.0.1), TB_HOST_CONSOLE_PORT (8090),
# TB_HOST_MAILHOG_PORT (8025), TB_POC_MAIL=real (your own mailbox from deploy/.env, RUNBOOK §9), TB_OPENROUTER_MODEL, TB_POC_UP_TIMEOUT (s, 900), TB_POC_SKIP_INGEST=1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# H-132 (LR-2): on a host where a box is installed (the update path's record) every action of this script would act on
# that box's compose project (reset: down -v, its volumes). Refused before anything is made, run or removed
if [ -e deploy/updates/installed.json ] || { [ -d deploy/updates ] && ! [ -x deploy/updates ]; }; then  # OCR 1481-5
  printf 'poc: this host has an installed box (deploy/updates/installed.json): "deploy/poc.sh %s" would act on' \
    "${1:-up}" >&2
  printf ' its compose project and data. Nothing was done; the box is run by its own commands (RUNBOOK §5).\n' >&2
  exit 1
fi
export TB_HOST_OBJECTS_DIR="${TB_HOST_OBJECTS_DIR:-$ROOT/deploy/.objects}"; mkdir -p "$TB_HOST_OBJECTS_DIR"  # test-stack object store (D-121)
MODE="${TB_LLM_MODE:-stub}"
ACTION="${1:-up}"
POC="$ROOT/deploy/poc"
ADMIN_EMAIL="${TB_POC_ADMIN_EMAIL:-admin@hospa.test}"
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
IMAGE_JVM="${TB_JVM_IMAGE:-trialbox-jvm:1.0.0}"
IMAGE_DB=trialbox-postgres:16-1  # deploy/build_db_image.sh builds it; compose's db service runs it (card 24-2)
# H-75: the 48 GB host run's own tag (deploy/build_db_image.sh takes the same) and its compose project (compose's
# -p, COMPOSE_PROJECT_NAME), which names the volume checked below; unset, the box's
[ -z "${TRIALBOX_IMAGE_TAG:-}" ] || IMAGE_DB="trialbox-postgres:$TRIALBOX_IMAGE_TAG"
PROJECT="${COMPOSE_PROJECT_NAME:-trialbox}"
OPENROUTER_MODEL="${TB_OPENROUTER_MODEL:-nvidia/nemotron-3-nano-30b-a3b}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'poc: %s\n' "$*" >&2; exit 1; }
# D-839: tr is stopped by the closed pipe once head has its characters; under pipefail that made `X="$(rand)"` end
# the script (exit 141) on a first run
rand() { { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; } || true; }
envfile_get() { [ -f deploy/.env ] && sed -n "s/^$1=//p" deploy/.env | tail -1 | tr -d "\"'" || true; }
envfile_set() {  # one VAR= line in deploy/.env, replacing any before it
  sed -i.bak "/^$1=/d" deploy/.env && rm -f deploy/.env.bak
  printf '%s=%s\n' "$1" "$2" >> deploy/.env
}
# D-896 (F15/W6): the models folder. TB_MODELS_DIR as typed (relative to here), else the one kept in deploy/.env
# (relative to deploy/, as compose reads it), else deploy/models; always made absolute, so compose, the pin, the
# doctor and check_weights.sh all read the same folder
models_dir() {
  local m="${TB_MODELS_DIR:-}"
  if [ -n "$m" ]; then case "$m" in /*) ;; *) m="$ROOT/${m#./}" ;; esac
  else m="$(envfile_get TB_MODELS_DIR)"; m="${m:-./models}"; case "$m" in /*) ;; *) m="$ROOT/deploy/${m#./}" ;; esac
  fi
  printf '%s' "${m%/}"
}

command -v docker >/dev/null || die "Docker is not installed (Docker Desktop, or Docker Engine 27+ with compose)"
docker info >/dev/null 2>&1 || die "Docker is not running (start Docker Desktop, or: sudo systemctl start docker)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is missing"

# D-839: a long step prints a line a minute (a watchdog sees life); started with alive_start, ended with alive_stop
ALIVE_PID=""
alive_start() {
  local what="$1" me=$$
  ( s=""; self=$BASHPID; trap 'kill "$s" 2>/dev/null; exit 0' TERM; n=0
    # OCR 1455-4: alive while the script is this ticker's parent. kill -0 is not enough: a script a signal ended is a
    # zombie that kill -0 still finds until its caller reaps it, and a caller that reads the output first never does
    up() { if [ -r "/proc/$self/stat" ]; then read -r _ _ _ pp _ < "/proc/$self/stat" && [ "$pp" = "$me" ]; else kill -0 "$me" 2>/dev/null; fi; }
    while up; do
      # H-110: the sleep holds none of the caller's pipes: one a stop orphans (its TERM before s=$!) never keeps a
      # caller that reads this output waiting
      # one-second sleeps, each followed by a look at the script: a signal that ends it frees the caller in a second
      i=0; while [ "$i" -lt "${TB_POC_ALIVE_S:-60}" ] && up; do
        sleep 1 >/dev/null 2>&1 & s=$!; wait "$s"; i=$((i + 1)); done; n=$((n + 1))
      up && echo "    ... still $what ($n)" >&2
    done ) 9>&- 6>&- & ALIVE_PID=$!  # 1452-12: the ticker and its sleep hold no lock fd of the caller (9, 6)
}
alive_stop() { [ -n "$ALIVE_PID" ] || return 0; kill "$ALIVE_PID" 2>/dev/null || true; wait "$ALIVE_PID" 2>/dev/null || true; ALIVE_PID=""; }
ok() { printf '    ok    %s\n' "$*"; }
compose_default() { sed -n "s/.*\${$1:-\([^}]*\)}.*/\1/p" "$2" | head -1; }

# GPU PREFLIGHT (D-839): everything the real pair needs, checked before anything is written or started
GPU=""
if [ "$MODE" = gpu ]; then
  say "GPU host check (nothing is changed yet)"
  command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 \
    || die "gpu mode: nvidia-smi finds no GPU (install the NVIDIA driver)"
  ok "GPU: $(nvidia-smi -L 2>/dev/null | head -1)"
  docker info 2>/dev/null | grep -qi nvidia || die "gpu mode: Docker lists no nvidia runtime (install nvidia-container-toolkit, then nvidia-ctk runtime configure --runtime=docker and restart Docker)"
  ok "Docker's nvidia runtime"
  GPU="${TB_GPU_PROFILE:-$(sh deploy/gpu_profile.sh)}"
  # card 10E-5 (D-1335): gb10 is the 128 GB Spark; under 96 GiB of memory it is gb10-64 however it was named.
  # TB_TEST_MEM_KIB stands in for /proc/meminfo's MemTotal in the tests only
  [ "$GPU" != gb10 ] || GPU="$(sh deploy/gpu_profile.sh memory-class "${TB_TEST_MEM_KIB:-}")"
  case "$GPU" in
    rtxpro6000|gb10) ok "GPU profile $GPU" ;;
    gb10-64) die "gpu mode: this DGX Spark has under 96 GiB of memory (the 64 GB class): the PoC does not serve the model pair on it. The gb10 profile is sized for 128 GB and no profile of the 64 GB class is measured (card 10E-5, D-1335); run the PoC without TB_LLM_MODE=gpu (the stub model), or use a 128 GB Spark" ;;
    dgpu48) die "gpu mode: dgpu48 is a DRAFT, UNMEASURED 48 GB profile: the PoC never starts it, whatever is set; its one use is the measuring run (TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure, RUNBOOK §29)" ;;
    *) die "gpu mode: GPU profile '$GPU': the one-command PoC serves the pair on rtxpro6000 or gb10 (TB_GPU_PROFILE); others: deploy/install.sh" ;;
  esac
  OVR="deploy/docker-compose.$GPU.yml"
  MODELS="$(models_dir)"
  # D-896 (F15/W6): a mount made by hand on the models folder is gone after a reboot, and llm-service comes back on an
  # empty folder; said here, with the setting that lasts
  if command -v mountpoint >/dev/null && mountpoint -q "$MODELS" 2>/dev/null \
     && ! findmnt --fstab --target "$MODELS" >/dev/null 2>&1 \
     && ! { command -v systemd-escape >/dev/null && systemctl cat "$(systemd-escape -p --suffix=mount "$MODELS")" >/dev/null 2>&1; }; then
    echo "poc: warning: $MODELS is a mount made by hand (no fstab line or mount unit): it is lost at the next reboot and the models then start on an empty folder. Point TB_MODELS_DIR=<the weights folder> at the weights instead (kept in deploy/.env), or add the mount to /etc/fstab" >&2
  fi
  for v in JUDGE_MODEL_DIR VERIFIER_MODEL_DIR; do
    d="${!v:-$(compose_default "$v" "$OVR")}"
    [ -f "$MODELS/$d/config.json" ] || die "gpu mode: no model in $MODELS/$d (no config.json): put the weights of the pinned build there (models/registry.yaml, profile $GPU; RUNBOOK §8) or set $v"
    ok "model folder $MODELS/$d"
  done
  tpl="${JUDGE_CHAT_TEMPLATE:-$(compose_default JUDGE_CHAT_TEMPLATE "$OVR")}"
  [ -z "$tpl" ] || [ -f "$MODELS/$tpl" ] || die "gpu mode: no chat template $MODELS/$tpl (the pinned file of models/registry.yaml, D-567)"
  [ -z "$tpl" ] || ok "chat template $MODELS/$tpl"
  need="${TB_POC_MIN_FREE_GB:-30}"
  droot="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
  for d in "$droot" "$MODELS"; do
    free="$(df -Pk "$d" 2>/dev/null | awk 'NR==2 {print int($4/1048576)}')"
    [ -z "$free" ] || [ "$free" -ge "$need" ] || die "gpu mode: $free GB free under $d, $need GB needed (TB_POC_MIN_FREE_GB)"
    [ -z "$free" ] || ok "$free GB free under $d"
  done
fi
# ---- end of GPU PREFLIGHT

# EMBEDDER PREFLIGHT (card 24-7, root review 24): TB_POC_EMBED=model serves the real embedder (e-embed-1, on the CPU)
# in place of the hash embedder the PoC overlay gives a synthetic stack. Kept in deploy/.env (TB_POC_EMBED) so a
# later plain start does not fall back to the hash embedder over a lake embedded by the model, and checked before
# anything is written: the folder, its weights' kind, and that the lake was not embedded by the other one.
EMBED_BUILD=e-embed-1
EMBED="${TB_POC_EMBED:-$(envfile_get TB_POC_EMBED)}"
EMBED="${EMBED:-hash}"
EMBED_DIR=""
case "$EMBED" in
  hash|model) ;;
  *) die "TB_POC_EMBED must be hash or model (got $EMBED)" ;;
esac
if [ "$EMBED" = model ] && [ "$ACTION" = up ]; then
  say "embedder check: the real embedder $EMBED_BUILD on the CPU (nothing is changed yet)"
  [ "$MODE" != gpu ] || die "TB_POC_EMBED=model is for the stub and openrouter modes; gpu mode is not prepared for it (card 24-7)"
  EMBED_MODELS="$(models_dir)"
  EMBED_DIR="$EMBED_MODELS/${EMBED_MODEL_DIR:-embedder}"
  [ -d "$EMBED_DIR" ] || die "TB_POC_EMBED=model: no embedder weights in $EMBED_DIR: fetch the pinned build $EMBED_BUILD there first (RUNBOOK §28, \"The real embedder\"), or start without TB_POC_EMBED"
  [ -f "$EMBED_DIR/config.json" ] && [ -f "$EMBED_DIR/model.safetensors" ] \
    || die "TB_POC_EMBED=model: $EMBED_DIR is not the pinned build $EMBED_BUILD (no config.json or no model.safetensors): fetch it again (RUNBOOK §28)"
  # the embed service's own refused suffixes (services/embed_service/embedder.py REFUSED_SUFFIXES); hidden files skipped
  pickles="$(find "$EMBED_DIR" -type f -not -path '*/.*' \( -iname '*.bin' -o -iname '*.pt' -o -iname '*.pth' -o -iname '*.pkl' -o -iname '*.pickle' -o -iname '*.ckpt' -o -iname '*.py' -o -iname '*.pyc' \) 2>/dev/null | head -3)"
  [ -z "$pickles" ] || die "TB_POC_EMBED=model: $EMBED_DIR holds pickle or code files ($(echo "$pickles" | tr '\n' ' ')): the pinned build $EMBED_BUILD is the folder without them (D-429); remove them"
  ok "embedder folder $EMBED_DIR (its manifest is checked against the release when it is pinned)"
fi
if [ "$ACTION" = up ] && docker volume inspect "${PROJECT}_lake-data" >/dev/null 2>&1; then
  kept="$(envfile_get TB_POC_EMBED)"
  [ "${kept:-hash}" = "$EMBED" ] || die "the synthetic lake was embedded with the ${kept:-hash} embedder, not the $EMBED one: its sentence vectors would not match. Start again from nothing (deploy/poc.sh reset deletes all PoC data), then run this again"
fi
# ---- end of EMBEDDER PREFLIGHT

export TB_SETTINGS_FILE="./poc/settings.yaml"
export TB_POC_ADMIN_EMAIL="$ADMIN_EMAIL"
export TB_DATA_CLASS=D0
export TB_HOST_MAILHOG_PORT="${TB_HOST_MAILHOG_PORT:-$(envfile_get TB_HOST_MAILHOG_PORT)}"
export TB_HOST_MAILHOG_PORT="${TB_HOST_MAILHOG_PORT:-8025}"
export TB_HOST_CONSOLE_PORT="${TB_HOST_CONSOLE_PORT:-$(envfile_get TB_HOST_CONSOLE_PORT)}"
export TB_HOST_CONSOLE_PORT="${TB_HOST_CONSOLE_PORT:-8090}"
export TB_CONSOLE_WEBMAIL_URL="http://127.0.0.1:$TB_HOST_MAILHOG_PORT"

if [ "$EMBED" = model ]; then  # card 24-7: the embed service's image and mode (docker-compose.poc.yml reads both)
  export TB_EMBED_IMAGE="${TB_EMBED_IMAGE:-trialbox-embed:1.0.0}" TB_EMBED_MODE=model
  [ -z "$EMBED_DIR" ] || export TB_MODELS_DIR="${EMBED_DIR%/*}"
fi
COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml)
MAILPROF=(--profile test)
if [ "${TB_POC_MAIL:-test}" = real ]; then  # your own mailbox (IMAP_*/SMTP_* in deploy/.env): no GreenMail/MailHog
  MAILPROF=(); export TB_CONSOLE_TEST_SMTP="" TB_CONSOLE_WEBMAIL_URL="${TB_POC_WEBMAIL_URL:-}"
fi
case "$MODE" in
  stub)
    COMPOSE+=(-f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile stub ${MAILPROF[@]+"${MAILPROF[@]}"})
    # the second-model checks go to the stub under its second served name (a real pair: v-verifier on the Spark)
    export TB_ENV=TEST TB_GATEWAY_MODEL="" TB_GATEWAY_VERIFIER_MODEL=stub-verifier TB_SITE_DIR="./poc/site" ;;
  openrouter)
    COMPOSE+=(-f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile stub ${MAILPROF[@]+"${MAILPROF[@]}"})
    export TB_ENV=DEV TB_GATEWAY_MODEL=j-workhorse TB_SITE_DIR="./poc/site" ;;
  gpu)
    COMPOSE+=(-f "deploy/docker-compose.$GPU.yml")  # D-839: the profile's shipped serving settings
    COMPOSE+=(-f deploy/docker-compose.test.yml -f deploy/docker-compose.poc.yml --profile gpu ${MAILPROF[@]+"${MAILPROF[@]}"})
    export TB_ENV=TEST TB_GATEWAY_MODEL=j-workhorse TB_SITE_DIR="${TB_SITE_DIR:-./site}" ;;
  *) die "TB_LLM_MODE must be stub, openrouter or gpu (got $MODE)" ;;
esac

urls() {
  local bind="${TB_POC_BIND:-127.0.0.1}"
  cat <<EOF

  TrialBox POC ($MODE model, $EMBED embedder)
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
  # card 24-7 (review of #1100): what to send back after the real-embedder start, and nothing else: no address, no
  # password, no folder name, no host name. The services' states and memory, the embedder's mode and its pin.
  report)
    echo "TrialBox PoC report ($(date -u +%Y-%m-%dT%H:%MZ)): $MODE model, $EMBED embedder choice"
    echo "embed-service TB_EMBED_MODE: $("${COMPOSE[@]}" exec -T embed-service printenv TB_EMBED_MODE 2>/dev/null || echo '?')"
    pinned="$(python3 -c "import sys, yaml; d = yaml.safe_load(open(sys.argv[1])) or {}; print(((d.get('builds') or {}).get('e-embed-1') or {}).get('sha256') or 'none')" "deploy/${TB_SITE_DIR#./}/registry.site.yaml" 2>/dev/null || echo none)"
    echo "e-embed-1 pin: ${pinned:0:12}"
    "${COMPOSE[@]}" ps --format '{{.Service}} {{.Status}}'
    ids="$("${COMPOSE[@]}" ps -q)"
    # shellcheck disable=SC2086 # one word per container id
    [ -z "$ids" ] || docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' $ids
    exit 0 ;;
  up) ;;
  *) die "usage: deploy/poc.sh [up|down|reset|status|report]" ;;
esac

# ------------------------------------------------------------------------------------------------ secrets
mkdir -p "$POC/secrets" "$POC/site"
chmod 700 "$POC/secrets"
if [ ! -f deploy/.env ]; then
  say "creating deploy/.env with random service passwords"
  WF_PW="$(rand 32)"
  sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(rand 32)/" \
      -e "s/^POSTGRES_WF_PASSWORD=.*/POSTGRES_WF_PASSWORD=$WF_PW/" \
      -e "s/^TB_DB_PW_FHIR_STORE=.*/TB_DB_PW_FHIR_STORE=$(rand 32)/" \
      -e "s|^TB_DB_URL=.*|TB_DB_URL=postgresql://trialbox:$WF_PW@db:5432/trialbox_wf|" \
      -e "s/^TB_SERVICE_TOKEN=.*/TB_SERVICE_TOKEN=$(rand 32)/" .env.example > deploy/.env
  chmod 600 deploy/.env
elif grep -q 'change-me' deploy/.env; then
  echo "poc: note: deploy/.env still has change-me passwords (kept: existing volumes were created with them)" >&2
fi
# D-896 (F15/W6): a models folder of its own is kept for every later start (compose, a restart, the doctor)
if [ "$MODE" = gpu ]; then
  export TB_MODELS_DIR="$MODELS"
  if [ "$MODELS" != "$ROOT/deploy/models" ] && [ "$(envfile_get TB_MODELS_DIR)" != "$MODELS" ]; then
    envfile_set TB_MODELS_DIR "$MODELS"
    ok "the models folder $MODELS is kept in deploy/.env (TB_MODELS_DIR)"
  fi
fi
# D-114: the orchestrator refuses changing calls without the box's service token (no volume depends on it)
if ! grep -q '^TB_SERVICE_TOKEN=' deploy/.env || grep -q '^TB_SERVICE_TOKEN=change-me' deploy/.env; then
  sed -i.bak '/^TB_SERVICE_TOKEN=/d' deploy/.env && rm -f deploy/.env.bak
  printf 'TB_SERVICE_TOKEN=%s\n' "$(rand 32)" >> deploy/.env
fi
if [ ! -s .cache/test-secrets/site_hmac.key ]; then  # pseudonymisation key of the synthetic site (test overlay mount)
  install -d -m 0777 .cache/test-secrets
  rand 48 > .cache/test-secrets/site_hmac.key && chmod 0644 .cache/test-secrets/site_hmac.key
fi
if [ "$MODE" = openrouter ]; then
  if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -s "$POC/secrets/openrouter_api_key" ]; then
    OPENROUTER_API_KEY="$(tr -d '\r\n' < "$POC/secrets/openrouter_api_key")"
  fi
  [ -n "${OPENROUTER_API_KEY:-}" ] || die "openrouter mode: enter the gateway key as shown in RUNBOOK §9"
  export OPENROUTER_API_KEY
fi

# ------------------------------------------------------------------------------------------------ images
build_images() {
  # the font step needs fontTools: prefer the project venv, else a host python3 that has it
  local py=""
  for cand in "$ROOT/.venv/bin/python" "$(command -v python3 || true)"; do
    if [ -x "$cand" ] && "$cand" -c 'import fontTools' 2>/dev/null; then py="$cand"; break; fi
  done
  # H-75: images of other names (TB_IMAGE, TB_JVM_IMAGE) never go through `make images`, whose tags are the box's
  # own: the build inputs are fetched here and the images built under the given names, on that base (BASE_IMAGE)
  local base=() own=0
  [ "$IMAGE_PY" = trialbox-py:1.0.0 ] && [ "$IMAGE_JVM" = trialbox-jvm:1.0.0 ] || own=1
  [ "$IMAGE_PY" = trialbox-py:1.0.0 ] || base=(--build-arg "BASE_IMAGE=$IMAGE_PY")
  if [ "$own" = 0 ] && command -v mvn >/dev/null && [ -n "$py" ] && command -v curl >/dev/null; then
    make images PY="$py"; DB_BUILT=1  # its last build is the database image's (deploy/build_db_image.sh)
  else  # no build tools on the host: fetch the build inputs in a throwaway builder container
    if [ "$own" = 1 ] && command -v mvn >/dev/null && [ -n "$py" ] && command -v curl >/dev/null; then
      say "fetching fonts and JVM build inputs (tools/fetch_jvm_deps.sh, tools/fetch_fonts.py)"
      PY="$py" bash tools/fetch_jvm_deps.sh && "$py" tools/fetch_fonts.py || die "the build inputs did not come"
    else
      say "fetching fonts and JVM build inputs in a builder container"
      docker run --rm -v "$ROOT:/src" -w /src "${TB_BUILDER_IMAGE:-maven:3.9.9-eclipse-temurin-17}" bash -c \
        'apt-get update -qq && apt-get install -y -qq python3 python3-fonttools curl >/dev/null && PY=python3 bash tools/fetch_jvm_deps.sh && python3 tools/fetch_fonts.py'
    fi
    docker build -f deploy/docker/python.Dockerfile -t "$IMAGE_PY" .
    docker build -f deploy/docker/jvm.Dockerfile ${base[@]+"${base[@]}"} -t "$IMAGE_JVM" .
    # card 24-7: the real embedder's image (trialbox-py plus its CPU library), only when it is asked for
    local emb=trialbox-embed:1.0.0; [ "$own" = 0 ] || emb="${TB_EMBED_IMAGE:-$emb}"
    [ "$EMBED" != model ] || docker build -f deploy/docker/embed.Dockerfile ${base[@]+"${base[@]}"} -t "$emb" .
  fi
}
# card 24-2 (root review 24): the database image has no build: entry in compose and is on no registry, so a host
# without it stopped at compose up. Built by the one command `make images` also runs, when missing or TB_POC_BUILD=1
# (`make images` above already built it); only the box's own image: a POSTGRES_IMAGE of the site's is left alone
build_db_image() {
  say "building the database image $IMAGE_DB (deploy/docker/db.Dockerfile, pinned base and packages; ~5-15 min)"
  deploy/build_db_image.sh || die "the database image $IMAGE_DB did not build (the lines above say why; most often a \
download that failed). Check that this machine reaches the internet (deb.debian.org, apt.postgresql.org, \
packages.groonga.org), then run deploy/poc.sh again: it starts nothing until the image is built"
}
DB_BUILT=0
if [ "${TB_POC_BUILD:-0}" = 1 ] || ! docker image inspect "$IMAGE_PY" "$IMAGE_JVM" >/dev/null 2>&1; then
  say "building images (first run: ~10-20 min)"
  build_images
else
  say "using images $IMAGE_PY and $IMAGE_JVM (TB_POC_BUILD=1 rebuilds)"
fi
DB_WANTED="${POSTGRES_IMAGE:-$(envfile_get POSTGRES_IMAGE)}"
if [ "$DB_BUILT" = 0 ] && [ "${DB_WANTED:-$IMAGE_DB}" = "$IMAGE_DB" ] \
   && { [ "${TB_POC_BUILD:-0}" = 1 ] || ! docker image inspect "$IMAGE_DB" >/dev/null 2>&1; }; then
  build_db_image
fi
EMBED_BASE=(); [ "$IMAGE_PY" = trialbox-py:1.0.0 ] || EMBED_BASE=(--build-arg "BASE_IMAGE=$IMAGE_PY")  # H-75: on the run's own base
if [ "$EMBED" = model ] && ! docker image inspect "$TB_EMBED_IMAGE" >/dev/null 2>&1; then
  say "building the embedder image $TB_EMBED_IMAGE (card 24-7; a few minutes)"
  docker build -f deploy/docker/embed.Dockerfile ${EMBED_BASE[@]+"${EMBED_BASE[@]}"} -t "$TB_EMBED_IMAGE" .
fi

# ------------------------------------------------------------------------------------------------ settings, model pin
say "POC settings for administrator mailbox $ADMIN_EMAIL"
docker run --rm -v "$POC:/out" --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m console.cli poc-settings \
  --in /app/deploy/settings.example.yaml --out /out/settings.yaml --admin-email "$ADMIN_EMAIL"
if [ "$MODE" = openrouter ]; then
  say "pinning j-workhorse to OpenRouter model $OPENROUTER_MODEL (DEV, D0 only)"
  ca=()  # a hospital TLS-inspection CA (TB_EXTRA_CA) must also reach this one-off call to OpenRouter
  [ -n "${TB_EXTRA_CA:-}" ] && ca=(-v "$TB_EXTRA_CA:/run/tb-extra-ca.pem:ro")
  docker run --rm -v "$POC/site:/out" "${ca[@]}" --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m console.cli \
    poc-openrouter-pin --model "$OPENROUTER_MODEL" --out /out/registry.site.yaml
elif [ "$MODE" = gpu ]; then
  # D-839: the pair pinned from the weights in deploy/models (as install.sh does), then what each role routes to
  SITE="deploy/${TB_SITE_DIR#./}"; mkdir -p "$SITE"
  say "pinning the $GPU pair from $MODELS (tools/pin_model.py --install; hashing the weights takes minutes)"
  alive_start "hashing the model weights"
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d" -v "$(cd "$MODELS" && pwd):/m:ro" \
    -e JUDGE_MODEL_DIR -e JUDGE_MODEL -e JUDGE_CHAT_TEMPLATE -e VERIFIER_MODEL_DIR -e VERIFIER_MODEL "$IMAGE_PY" \
    python -m tools.pin_model --install "$GPU" --models-root /m --out "/d/${SITE#deploy/}/registry.site.yaml" \
    || { alive_stop; die "gpu mode: the pair could not be pinned (above)"; }
  alive_stop
  docker run --rm -v "$ROOT/deploy:/d:ro" "$IMAGE_PY" \
    python -m tools.pin_model --resolve --out "/d/${SITE#deploy/}/registry.site.yaml" 2>&1 | sed 's/^/    /' || true
fi
if [ "$EMBED" = model ]; then
  # card 24-7: e-embed-1 pinned alone from its folder (the embedder-only pin of a box without a GPU, D-1066): a folder
  # whose manifest is not the release's is refused here, and an existing pin is checked against the folder again
  SITE_E="deploy/${TB_SITE_DIR#./}"; mkdir -p "$SITE_E"
  say "pinning the embedder $EMBED_BUILD from $EMBED_DIR (tools/pin_model.py --install-embedder; hashing 2.3 GB)"
  alive_start "hashing the embedder's weights"
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d" -v "${EMBED_DIR%/*}:/m:ro" -e EMBED_MODEL_DIR \
    "$IMAGE_PY" python -m tools.pin_model --install-embedder --models-root /m --out "/d/${SITE_E#deploy/}/registry.site.yaml" \
    || { alive_stop; die "TB_POC_EMBED=model: the embedder could not be pinned (above): $EMBED_DIR is not the pinned build $EMBED_BUILD"; }
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d:ro" -v "${EMBED_DIR%/*}:/m:ro" "$IMAGE_PY" \
    python -m tools.pin_model --verify --build "$EMBED_BUILD" --model-dir "/m/${EMBED_DIR##*/}" --out "/d/${SITE_E#deploy/}/registry.site.yaml" \
    || { alive_stop; die "TB_POC_EMBED=model: $EMBED_DIR differs from its pin (above): put the pinned build back, or delete deploy/${SITE_E#deploy/}/registry.site.yaml and pin again"; }
  alive_stop
fi
# card 24-7: the embedder choice is kept for every later start (a lake embedded by the model is never read with the
# hash embedder), and only once the pin above passed; hash is the default and is written only once model was kept
if [ "$EMBED" = model ] || [ -n "$(envfile_get TB_POC_EMBED)" ]; then
  [ "$(envfile_get TB_POC_EMBED)" = "$EMBED" ] || { envfile_set TB_POC_EMBED "$EMBED"; ok "the embedder choice ($EMBED) is kept in deploy/.env (TB_POC_EMBED)"; }
fi

# ------------------------------------------------------------------------------------------------ up
say "starting the stack ($MODE model); first start pulls images and takes a few minutes"
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" rm -sf gateway >/dev/null 2>&1 || true   # the gateway reads model pins at start
alive_start "starting the stack (the model servers load their weights)"
"${COMPOSE[@]}" up -d --wait --wait-timeout "${TB_POC_UP_TIMEOUT:-900}" \
  || { alive_stop; "${COMPOSE[@]}" ps; die "the stack did not become healthy (deploy/poc.sh status; docker compose logs)"; }
alive_stop

say "console administrator"
"${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin --mailbox "$ADMIN_EMAIL"

if [ "$MODE" = gpu ]; then
  # D-839: the 54-case pair canary through the box's gateway, inside the orchestrator (no model port is published)
  say "the pair canary (54 cases, each model and the pair; tools/canary.py)"
  alive_start "the pair canary"
  "${COMPOSE[@]}" exec -T orchestrator python -m tools.canary \
    || { alive_stop; die "gpu mode: the pair canary did not pass (above): check the card, the driver and the model servers' logs"; }
  alive_stop
  echo "    G-1 (the served chat template against the weights folder's): python -m tools.complete_run --only chat-template --judge-url <judge /v1> from a checkout with the model server's image (tools/chat_template_check.py)"
fi

if [ "${TB_POC_SKIP_INGEST:-0}" != 1 ]; then
  say "ingesting synthetic site A (600 patients)"
  "${COMPOSE[@]}" exec -T console python -m console.cli ingest || echo "poc: ingest did not pass; retry from the console Overview page" >&2
fi
urls
