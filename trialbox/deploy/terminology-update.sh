#!/usr/bin/env bash
# V-18 (D-1182; DB-C1): the one code-system step, at install and as the manual update (one command for the admin).
#   1. The hospital's folder (TB_LICENSED_DIR, default deploy/site/terminology; its layout in
#      docs/handover/terminology-folder.md) into the terminology volume: deploy/terminology.sh folder /stage, with no
#      network. Each licensed copy needs the named person of the folder's acceptance.json (D-1114).
#   2. The vocabulary (omop.concept) and the FHIR store from the volume's one manifest and the shipped tables, in one
#      run (python -m tools.terminology_load load), its report in deploy/site/terminology-load.json.
# Never a stop (exit 0): each system not loaded is a line of deploy/site/needed.jsonl (the "information still needed"
# page, U-5) and, on the installer's run, of poc-stops.jsonl; running this again loads it, with no reinstall. The
# hospital's files stay where they are: only the tables built from them go into the volume.
#
#   deploy/terminology-update.sh                      # after the files changed, or a system was added to the folder
#   deploy/terminology-update.sh --rollback BUNDLE    # the tables an update's code systems replaced, put back
#   deploy/terminology-update.sh --scheduled          # M2 (V-19): a signed pack from TB_TERMINOLOGY_UPDATE_DIR or a stick
#   deploy/terminology-update.sh --readers-only       # step 2 only (deploy/terminology.sh, after it loaded a system)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
if [ "${1:-}" = "--rollback" ]; then  # V-18: the tables kept aside by update BUNDLE (tools/trialbox/update.py)
  KEEP="deploy/terminology/previous/${2:?usage: deploy/terminology-update.sh --rollback BUNDLE}"
  [ -f "$KEEP/saved.json" ] || { echo "terminology-update: nothing kept for ${2} ($KEEP/saved.json)" >&2; exit 2; }
  PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' deploy/.env 2>/dev/null | tail -1)"; PROJECT="${PROJECT:-trialbox}"
  IMAGE="$(sed -n 's/^TB_IMAGE=//p' deploy/.env 2>/dev/null | tail -1)"; IMAGE="${IMAGE:-trialbox-py:1.0.0}"
  docker run --rm --network none --user 0:0 -e TB_TERMINOLOGY_DIR=/data/terminology \
    -v "${PROJECT}_tb-terminology:/data/terminology" -v "$ROOT/$KEEP:/keep:ro" "$IMAGE" python -c \
    "from pathlib import Path; from criteria_compiler.terminology import installed as i; print(i.restore_tables(Path('/data/terminology'), Path('/keep')))" \
    || { echo "terminology-update: the kept tables were not put back (above); nothing changed" >&2; exit 2; }
  shift 2
  set -- "$@"
fi
if [ "${1:-}" = "--scheduled" ]; then  # M2 (V-19): run by trialbox-terminology.timer, before the night
  STICKS=(); IFS=: read -ra FOLDERS <<< "${TB_TERMINOLOGY_STICK:-}"  # ":" between folders, as terminology_pack.py reads it
  for s in "${FOLDERS[@]}"; do if [ -n "$s" ]; then STICKS+=(--stick "$s"); fi; done
  PACK="$(PYTHONPATH=. python3 -m tools.terminology_pack find --update-dir "${TB_TERMINOLOGY_UPDATE_DIR:-}" "${STICKS[@]}")"
  [ -n "$PACK" ] || { echo "terminology-update: no pack waiting"; exit 0; }
  PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' deploy/.env 2>/dev/null | tail -1)"; PROJECT="${PROJECT:-trialbox}"
  mkdir -p deploy/terminology/previous
  # exit: 0 applied or waits, 3 refused (by name, nothing changed), 4 a reader failed (the old release is back)
  exec docker compose --project-directory deploy run --rm --no-deps -T -v "$PACK:/pack:ro"     -v "$ROOT/deploy/terminology/previous:/keep" -v "$ROOT/deploy/keys:/keys:ro"     -v "${PROJECT}_audit-data:/data/audit" -e TB_VENDOR_KEYS=/keys -e TB_AUDIT_DIR=/data/audit     criteria-compiler python -m tools.terminology_pack run --pack /pack --keep /keep
fi
READERS_ONLY=0
[ "${1:-}" != "--readers-only" ] || READERS_ONLY=1
SITE="deploy/site"
REPORT="$SITE/terminology-load.json"
LOG="$(mktemp)"
trap 'rm -f "$LOG" "$REPORT.new"' EXIT
mkdir -p "$SITE"
FOLDER_LOG=()
if [ "$READERS_ONLY" = 0 ]; then
  echo "code systems: the hospital's folder into the terminology volume"
  if ! TB_TERMINOLOGY_READERS=0 deploy/terminology.sh folder /stage >"$LOG" 2>&1; then
    echo "terminology-update: warning: the hospital's folder was not read (deploy/terminology.sh, below)" >&2
  fi
  sed 's/^/    /' "$LOG"
  FOLDER_LOG=(--folder-log "$LOG")
fi
echo "code systems: one manifest into the vocabulary and the FHIR store"
docker rm -f tb-terminology-load >/dev/null 2>&1 || true
COMPOSE=(docker compose --project-directory deploy)  # the files and profile of deploy/.env (COMPOSE_FILE), as installed
if "${COMPOSE[@]}" run --rm --no-deps -T --name tb-terminology-load criteria-compiler \
    python -m tools.terminology_load load --report - >"$REPORT.new"; then
  # review 1439-4: the systems an earlier load changed and no restart served stay pending in the new report
  PYTHONPATH=. python3 -m tools.terminology_load carry --old "$REPORT" --new "$REPORT.new" || true
  mv -f "$REPORT.new" "$REPORT"
  # V-18b (D-1183, V18-01): the store keeps its $lookup and $validate-code answers for minutes and no operation of
  # it clears them, so after a load that changed a system it is restarted, and waited for until it is healthy
  if PYTHONPATH=. python3 -m tools.terminology_load changed --report "$REPORT" >/dev/null; then
    echo "code systems: restarting the FHIR store, so it answers from the new versions at once"
    start=$(date +%s)
    answered=no
    if "${COMPOSE[@]}" restart fhir-store >/dev/null 2>&1; then
      for _ in $(seq "${TB_FHIR_RESTART_TRIES:-60}"); do  # 15 s apart: the store's own start period is 90 s
        cid="$("${COMPOSE[@]}" ps -q fhir-store 2>/dev/null)"
        if [ -n "$cid" ] && [ "$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null)" = healthy ]; then
          answered=yes
          break
        fi
        sleep "${TB_FHIR_RESTART_STEP:-15}"
      done
    fi
    PYTHONPATH=. python3 -m tools.terminology_load restarted --report "$REPORT" --answered "$answered" \
      --seconds "$(( $(date +%s) - start ))"
    [ "$answered" = yes ] || echo "terminology-update: warning: the FHIR store did not answer after its restart" >&2
  fi
else
  echo "terminology-update: warning: the vocabulary and the FHIR store were not loaded (above); run this again" >&2
  rm -f "$REPORT"
fi
# what is still needed: the folder's systems not loaded and the readers' (standard library only, on the host)
PYTHONPATH=. python3 -m tools.terminology_load skipped --report "$REPORT" "${FOLDER_LOG[@]}" --site "$SITE" \
  | while IFS="$(printf '\t')" read -r key why; do
      [ -z "$key" ] || echo "terminology-update: still needed: $key: $why" >&2
    done
exit 0
