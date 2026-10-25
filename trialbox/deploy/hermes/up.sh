#!/usr/bin/env bash
# Hermes on the POC in one command (spec v4 §9; S1-11): `make poc` first, then
#
#   deploy/hermes/up.sh            # certificates, relay key, directory, DEV/TEST profile, then hermes + frontdoor-mcp +
#                                  # channel-relay layered on the running POC (same TB_LLM_MODE as deploy/poc.sh)
#   deploy/hermes/up.sh status     # container states
#   deploy/hermes/up.sh down       # stop and remove the three Hermes-side services (the POC keeps running)
#
# Then talk to it as the POC administrator: python3 tools/relay_send.py --body "How many patients for GZQO over the
# last 3 years?" (replies in MailHog, http://127.0.0.1:8025); `OK` on the reply starts the job (deterministic intake).
# Knobs: TB_LLM_MODE (stub|openrouter|gpu), TB_POC_ADMIN_EMAIL, TB_HERMES_PROFILE (tb-staff), TB_HERMES_DEV_MODEL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ACTION="${1:-up}"
MODE="${TB_LLM_MODE:-stub}"
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
export TB_POC_ADMIN_EMAIL="${TB_POC_ADMIN_EMAIL:-admin@hospa.test}"
export TB_SETTINGS_FILE="./poc/settings.yaml" TB_DATA_CLASS=D0
export TB_HOST_MAILHOG_PORT="${TB_HOST_MAILHOG_PORT:-8025}" TB_HOST_CONSOLE_PORT="${TB_HOST_CONSOLE_PORT:-8090}"
export TB_CONSOLE_WEBMAIL_URL="http://127.0.0.1:$TB_HOST_MAILHOG_PORT"
export TB_HERMES_CONFIG="./secrets/hermes/hermes-config.yaml"
case "$MODE" in
  stub) export TB_ENV=TEST TB_GATEWAY_MODEL="" TB_SITE_DIR="./poc/site"; MODEL="${TB_HERMES_DEV_MODEL:-f-frontdesk}"
        PROFILES=(--profile stub) ;;
  openrouter) export TB_ENV=DEV TB_GATEWAY_MODEL=j-workhorse TB_SITE_DIR="./poc/site"
        MODEL="${TB_HERMES_DEV_MODEL:-j-workhorse}"; PROFILES=(--profile stub) ;;
  gpu) export TB_ENV=TEST TB_GATEWAY_MODEL=j-workhorse TB_SITE_DIR="${TB_SITE_DIR:-./site}"
        MODEL="${TB_HERMES_DEV_MODEL:-j-workhorse}"; PROFILES=(--profile gpu) ;;
  *) echo "up.sh: TB_LLM_MODE must be stub, openrouter or gpu" >&2; exit 2 ;;
esac
COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml
  -f deploy/docker-compose.poc.yml -f deploy/hermes/docker-compose.hermes.yml -f deploy/hermes/docker-compose.hermes.test.yml
  "${PROFILES[@]}" --profile test --profile hermes)
if [ "$MODE" = gpu ] && { [ "$(uname -m)" = aarch64 ] || [ "$(uname -m)" = arm64 ]; }; then  # DGX Spark / GB10
  COMPOSE+=(-f deploy/docker-compose.gb10.yml)
fi
HERMES_SIDE=(hermes channel-relay frontdoor-mcp)

case "$ACTION" in
  status) "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}' "${HERMES_SIDE[@]}"; exit 0 ;;
  down) "${COMPOSE[@]}" rm -sf "${HERMES_SIDE[@]}"; exit 0 ;;
  up) ;;
  *) echo "usage: deploy/hermes/up.sh [up|status|down]" >&2; exit 2 ;;
esac

[ -f deploy/poc/settings.yaml ] || { echo "up.sh: run the POC first (make poc)" >&2; exit 1; }
echo "==> deploy-time material (deploy/secrets/hermes; never committed)"
docker run --rm --user 0 -v "$ROOT:/src" -w /src -e TB_ENV -e TB_POC_ADMIN_EMAIL "$IMAGE_PY" \
  python deploy/hermes/prepare.py --env "$TB_ENV" --model "$MODEL" --profile "${TB_HERMES_PROFILE:-tb-staff}"
echo "==> hermes, frontdoor-mcp, channel-relay ($MODE model via tb-gateway)"
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" up -d --wait --wait-timeout "${TB_POC_UP_TIMEOUT:-600}" gateway "${HERMES_SIDE[@]}"
cat <<EOF

  Hermes is serving through channel-relay -> tb_relay_adapter -> frontdoor-mcp (mTLS, per-call assertion).
  Send:   python3 tools/relay_send.py --body "How many patients could we find for GZQO over the last 3 years?"
  Reply:  web mail http://127.0.0.1:$TB_HOST_MAILHOG_PORT   (then: tools/relay_send.py --body OK --in-reply-to '<id>')
  Test:   make test-hermes-e2e        Stop:  deploy/hermes/up.sh down
EOF
