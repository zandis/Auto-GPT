#!/usr/bin/env bash
# TrialBox one-file installer for a hospital workstation or server (clinical review 2026-11, section 6; RUNBOOK §1).
#
#   sudo deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--gpu gb10|rtx5090|rtx4090] [--yes]
#   sudo deploy/install.sh --check            # host checks only (deploy/check_host.sh)
#
# What it does, in order, and stops at the first failure:
#   1. host:      Docker Engine + compose plugin present and running; GPU driver when --mode gpu (auto when nvidia-smi
#                 works); vendor public key installed (deploy/keys/vendor_ed25519.pub)
#   2. bundle:    verify the Ed25519 signature and every payload hash, then load images, models and rulesets
#                 (tools/apply_update.sh; a tampered bundle changes nothing)
#   3. settings:  deploy/settings.yaml + deploy/.env from the settings wizard (questions, or --answers), random
#                 service passwords, mode 0600; an existing settings.yaml is kept and re-validated
#   4. start:     docker compose up --wait with the chosen model profile; egress rules (deploy/network.sh apply)
#   5. accounts:  first console administrator (password printed once); users page for the rest
#   6. check:     deploy/check_host.sh; the console URL and the intake address
# Re-running is safe: every step is idempotent. Nothing leaves the host: no registry, no download, no telemetry.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUNDLE=""; ANSWERS=""; MODE="${TB_LLM_MODE:-auto}"; GPU="${TB_GPU_PROFILE:-auto}"; YES=0; CHECK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --answers) ANSWERS="$2"; shift ;;
    --mode) MODE="$2"; shift ;;
    --gpu) GPU="$2"; shift ;;
    --yes) YES=1 ;;
    --check) CHECK=1 ;;
    -h|--help) sed -n 2,18p "$0"; exit 0 ;;
    -*) echo "install: unknown option $1" >&2; exit 2 ;;
    *) BUNDLE="$1" ;;
  esac
  shift
done
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
PUBKEY="${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}"

if [ "$CHECK" = 1 ]; then exec sh "$ROOT/deploy/check_host.sh" "$@"; fi
[ -n "$BUNDLE" ] || die "usage: deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--yes]"
[ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"

# ------------------------------------------------------------------------------------------------ 1. host
say "host"
command -v docker >/dev/null || die "Docker is not installed (Docker Engine 27+ with the compose plugin; docs/HARDENING.md)"
docker info >/dev/null 2>&1 || die "Docker is not running (sudo systemctl start docker)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is missing"
if [ "$MODE" = auto ]; then
  if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then MODE=gpu; else MODE=stub; fi
fi
case "$MODE" in
  gpu) command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 || die "--mode gpu but nvidia-smi finds no GPU (driver + container toolkit; docs/HARDENING.md)"
       docker info 2>/dev/null | grep -qi nvidia || echo "install: warning: Docker lists no nvidia runtime; the model service may not start" >&2 ;;
  stub) echo "    no GPU: structured criteria only (FEAS, NAV, COHORT); note criteria wait for a GPU or a pinned cloud model" ;;
  *) die "--mode must be gpu or stub" ;;
esac
# GPU profile (D-95): gb10 = DGX Spark pair; rtx5090 = Gemma 4 4-bit + Qwen3.5-9B 4-bit on one 32 GB card, both must
# agree to exclude; rtx4090 = the judge alone on a 24 GB card, note answers never exclude; default = base llm-service
if [ "$MODE" = gpu ] && [ "$GPU" = auto ]; then
  name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
  case "$(uname -m):$name" in
    aarch64:*|arm64:*) GPU=gb10 ;;
    *5090*|*"RTX PRO 4500"*) GPU=rtx5090 ;;
    *4090*|*3090*) GPU=rtx4090 ;;
    *) GPU=default ;;
  esac
fi
case "$GPU" in auto|default|gb10|rtx5090|rtx4090) ;; *) die "--gpu must be gb10, rtx5090, rtx4090 or default" ;; esac
[ -f "$PUBKEY" ] || die "vendor public key missing: copy vendor_ed25519.pub (from the vendor, out of band) to $PUBKEY"
if [ -f "$BUNDLE.sha256" ]; then
  (cd "$(dirname "$BUNDLE")" && sha256sum -c "$(basename "$BUNDLE").sha256" >/dev/null) || die "bundle checksum mismatch"
fi
echo "    docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), model profile: $MODE, gpu: $GPU, vendor key: $PUBKEY"

# ------------------------------------------------------------------------------------------------ 2. bundle
say "bundle: verify and load (images, models, rulesets)"
sh "$ROOT/tools/apply_update.sh" "$BUNDLE" --dry-run >/dev/null || die "the bundle is not a valid signed TrialBox release; nothing was changed"
TB_SKIP_AUDIT=1 sh "$ROOT/tools/apply_update.sh" "$BUNDLE" 2>&1 | sed 's/^/    /' || die "loading the bundle failed"
docker image inspect "$IMAGE_PY" >/dev/null 2>&1 || die "the bundle carried no $IMAGE_PY image"

# ------------------------------------------------------------------------------------------------ 3. settings
say "settings"
mkdir -p deploy/keys deploy/secrets
if [ ! -f deploy/settings.yaml ]; then
  if [ -n "$ANSWERS" ]; then
    [ -f "$ANSWERS" ] || die "no such answers file: $ANSWERS"
    docker run --rm -v "$ROOT/deploy:/out" -v "$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS"):/in/answers.yaml:ro" \
      --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.settings_wizard --answers /in/answers.yaml --out /out/settings.yaml --env-out /out/.env
  else
    [ -t 0 ] || die "no deploy/settings.yaml and no terminal for the questions: pass --answers site.yaml (RUNBOOK §1 step 3)"
    docker run --rm -it -v "$ROOT/deploy:/out" --user "$(id -u):$(id -g)" "$IMAGE_PY" \
      python -m tools.settings_wizard --out /out/settings.yaml --env-out /out/.env
  fi
else
  echo "    keeping deploy/settings.yaml (re-validating)"
  docker run --rm -v "$ROOT/deploy/settings.yaml:/in/settings.yaml:ro" "$IMAGE_PY" python -m tools.settings_wizard --check /in/settings.yaml
fi
[ -f deploy/.env ] || cp .env.example deploy/.env
# random service passwords where the example ones are still in place
for k in MINIO_SECRET_KEY POSTGRES_PASSWORD POSTGRES_WF_PASSWORD; do
  if grep -q "^$k=change-me" deploy/.env || ! grep -q "^$k=" deploy/.env; then
    sed -i.bak "/^$k=/d" deploy/.env && printf '%s=%s\n' "$k" "$(rand 32)" >> deploy/.env
  fi
done
rm -f deploy/.env.bak
grep -q '^TB_LLM_MODE=' deploy/.env && sed -i "s/^TB_LLM_MODE=.*/TB_LLM_MODE=$MODE/" deploy/.env || echo "TB_LLM_MODE=$MODE" >> deploy/.env
NOTE_BLOCK=both_agree; [ "$GPU" = rtx4090 ] && NOTE_BLOCK=never
grep -q '^TB_NOTE_BLOCK=' deploy/.env && sed -i "s/^TB_NOTE_BLOCK=.*/TB_NOTE_BLOCK=$NOTE_BLOCK/" deploy/.env || echo "TB_NOTE_BLOCK=$NOTE_BLOCK" >> deploy/.env
grep -q '^COMPOSE_PROFILES=' deploy/.env && sed -i "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=$MODE/" deploy/.env || echo "COMPOSE_PROFILES=$MODE" >> deploy/.env
chmod 600 deploy/.env deploy/settings.yaml
export TB_SETTINGS_FILE="./settings.yaml"
if [ "$MODE" = gpu ]; then
  ls deploy/site/registry.site.yaml >/dev/null 2>&1 || echo "install: note: no model pinned yet (deploy/site/registry.site.yaml): run tools/pin_model.py or make spark-e2e after install (RUNBOOK §8)" >&2
fi

# ------------------------------------------------------------------------------------------------ 4. start
COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml)
case "$MODE:$GPU" in
  gpu:gb10) COMPOSE+=(-f deploy/docker-compose.gb10.yml) ;;
  gpu:rtx5090|gpu:rtx4090) COMPOSE+=(-f deploy/docker-compose.rtx5090.yml) ;;
esac
COMPOSE+=(--profile "$MODE")
UP_EXTRA=(); [ "$MODE:$GPU" = gpu:rtx4090 ] && UP_EXTRA=(--scale llm-verifier=0)
if [ "$YES" != 1 ] && [ -t 0 ]; then
  printf 'Start the stack now with profile %s? [Y/n] ' "$MODE"; read -r ans; case "$ans" in n|N) die "stopped before start; re-run with --yes to skip the question" ;; esac
fi
say "starting the stack (profile $MODE)"
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" up -d "${UP_EXTRA[@]}" --wait --wait-timeout "${TB_INSTALL_UP_TIMEOUT:-900}" \
  || { "${COMPOSE[@]}" ps; die "the stack did not become healthy (docker compose logs)"; }
if [ "$(id -u)" = 0 ] && [ -x deploy/network.sh ]; then
  say "egress rules"; deploy/network.sh apply || echo "install: warning: egress rules not applied (deploy/network.sh apply)" >&2
fi

for f in deploy/updates/pending_audit/*.json; do  # the bundle's update.applied event, deferred until now
  [ -f "$f" ] || continue
  "${COMPOSE[@]}" exec -T orchestrator python -c '
import json, sys
from tb_common.audit import AuditLog
s = json.load(sys.stdin)
AuditLog("/data/audit").append("update.applied", actor="deploy/install.sh", input_sha=s["manifest_sha256"],
    detail={"bundle_id": s["bundle_id"], "signer": s["signer"], "files": s["files"]})
' < "$f" && rm -f "$f" && echo "    audited bundle $(basename "$f" .json)"
done

# ------------------------------------------------------------------------------------------------ 5. accounts
say "first console administrator"
ADMIN_MAIL="$(sed -n 's/^MAIL_ADMIN_ADDR=//p' deploy/.env | head -1)"
ADMIN_MAIL="${ADMIN_MAIL:-${TB_ADMIN_EMAIL:-}}"
if [ -n "$ADMIN_MAIL" ]; then
  "${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin --mailbox "$ADMIN_MAIL"
else
  "${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin
fi
echo "    add coordinators and viewers on the console's Users page, or: docker compose exec console python -m console.cli add-user"

# ------------------------------------------------------------------------------------------------ 6. check
say "host check"
sh "$ROOT/deploy/check_host.sh" $( [ "$(uname -m)" = aarch64 ] && echo --gb10 ) || echo "install: host check reported FAIL lines above: fix them before go-live (docs/HARDENING.md)" >&2
PORT="$(sed -n 's/^TB_HOST_CONSOLE_PORT=//p' deploy/.env | head -1)"
cat <<EOT

  TrialBox is running.
  Console:            http://127.0.0.1:${PORT:-8090}   (sign in as admin with the password printed above)
  Intake mailbox:     $(sed -n 's/^MAIL_INTAKE_ADDR=//p' deploy/.env | head -1)
  First ingest:       docker compose --project-directory deploy exec adapter python -m adapter.cli run   (or 02:00 nightly)
  Acceptance:         docs/RUNBOOK.md §6 before go-live;  updates: tools/apply_update.sh <bundle>
EOT
