#!/bin/sh
# D-991 (TERM-VOL; TERM-1 D-858, TERM-2 D-1113 to D-1116): load a code system onto the box. The one writer of the
# terminology volume: `python -m tools.terminology_install` in the box's Python image (the loader needs its pyarrow),
# with the volume read-write at TB_TERMINOLOGY_DIR (/data/terminology), the site's staging folder deploy/site/terminology
# read-only at /stage, and no network. criteria-compiler, orchestrator and console mount the same volume read-only and
# read what is loaded there (docs/handover/OFFLINE-MEDIA.md "Code systems at install").
#
#   deploy/terminology.sh site-list /stage/icd_local.csv --name icd_local --system icd10cm
#   deploy/terminology.sh status
#
# A file is named by its path under /stage (copy it to deploy/site/terminology first). The box must have been started
# once (`docker compose up` creates the volume). Exit code: the loader's.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env"
val() {  # the last VAR= line of deploy/.env, quotes removed (as compose reads it)
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | sed "s/^[\"']//; s/[\"']\$//"
}
[ $# -ge 1 ] || { echo "usage: deploy/terminology.sh <tools.terminology_install subcommand> [args; files as /stage/<name>]" >&2; exit 2; }
PROJECT="${COMPOSE_PROJECT_NAME:-$(val COMPOSE_PROJECT_NAME)}"; PROJECT="${PROJECT:-trialbox}"
IMAGE="${TB_IMAGE:-$(val TB_IMAGE)}"; IMAGE="${IMAGE:-trialbox-py:1.0.0}"
VOLUME="${PROJECT}_tb-terminology"
if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "terminology: no volume $VOLUME: start the box once (docker compose up creates it), then load" >&2
  exit 2
fi
mkdir -p "$ROOT/deploy/site/terminology"
exec docker run --rm --network none --user 0:0 -e TB_TERMINOLOGY_DIR=/data/terminology \
  -v "${PROJECT}_tb-terminology:/data/terminology" -v "$ROOT/deploy/site/terminology:/stage:ro" \
  "$IMAGE" python -m tools.terminology_install "$@"
