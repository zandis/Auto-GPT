#!/bin/sh
# T-677 (D-393; deep review LLM-008): `trialbox doctor --weights` in the box's Python image, with the site's models
# folder and site pins mounted. Every pinned build's weights must still hash to their pin; a difference writes
# deploy/site/weights_changed.json and the gateway refuses every model call until a later run passes (it removes the
# flag). Run by trialbox-weights.timer before the night's scheduled runs; an update runs the same check after its
# restart (tools/trialbox/update.py). Exit 1 on a mismatch. Usage: deploy/check_weights.sh [TRIALBOX_ROOT]
set -eu
ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="$ROOT/deploy/.env"
val() {  # the last VAR= line of deploy/.env, quotes removed (as compose reads it)
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | sed "s/^[\"']//; s/[\"']\$//"
}
abs() { case "$1" in /*) echo "$1" ;; *) echo "$ROOT/deploy/${1#./}" ;; esac; }
IMAGE="$(val TB_IMAGE)"
MODELS="$(val TB_MODELS_DIR)"
SITE="$(val TB_SITE_DIR)"
ENV_ARGS=""
[ -f "$ENV_FILE" ] && ENV_ARGS="--env-file $ENV_FILE"
# shellcheck disable=SC2086
exec docker run --rm --network none $ENV_ARGS \
  -e TB_MODELS_DIR=/app/deploy/models -e TB_REGISTRY_OVERRIDE=/app/deploy/site/registry.site.yaml -e TB_WEIGHTS_FLAG= \
  -v "$ROOT/deploy:/app/deploy" -v "$(abs "${MODELS:-./models}"):/app/deploy/models:ro" \
  -v "$(abs "${SITE:-./site}"):/app/deploy/site" \
  "${IMAGE:-trialbox-py:1.0.0}" python -m tools.trialbox doctor --weights
