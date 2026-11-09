#!/usr/bin/env bash
# TrialBox complete-platform run on the RTX PRO 6000 (TB-PLAN-04 step 9, D-139, D-141). Owner's OK first: it starts
# a paid VM (tb-gpu-sim, g4-standard-48 spot, about US$2.74 an hour).
#
#   export CLOUDSDK_CONFIG=<a private folder>              # never the default one
#   export TB_SA_KEY_FILE=<the service account key file>   # gcloud re-activates from it on an auth error
#   gcloud auth activate-service-account --key-file "$TB_SA_KEY_FILE" && gcloud config set project trialbox-demo
#   deploy/gcp/complete-run.sh --estimate [--patients 50000]           # hours and US$, nothing started
#   deploy/gcp/complete-run.sh --dry-run [--patients 50000] [VM] [ZONE] # every command, nothing run
#   deploy/gcp/complete-run.sh [--patients 50000] [--hours N] [--no-wait] [VM] [ZONE]
#   deploy/gcp/complete-run.sh --collect <run id> [VM] [ZONE]          # later: results, then the stub parts, report
#   deploy/gcp/complete-run.sh --stop [VM] [ZONE]                       # stop it by hand
#
# Fail-safe (D-141; the 2026-11-09 incident: a dead driver left the VM running for 61 minutes):
#   1. Cloud-side hard cap, set before the start: max-run-duration of the estimate x 1.3 rounded up (--hours to
#      change it), termination action STOP. Compute Engine stops the VM at the cap whatever else happens.
#   2. The VM stops itself (deploy/gcp/complete-run-vm.sh): a systemd hard cap, and a watchdog that powers off when
#      the heartbeat is not touched for 20 minutes or the done marker appears (after the driver collects, or 30
#      minutes later).
#   3. The workload runs on the VM (48 vCPU): the driver uploads the code (git archive of HEAD), polls, downloads the
#      results and runs the stub parts (walk, backup, update, scale) here once the VM has stopped. The driver can die
#      at any moment; `--collect <run id>` picks the run up again.
#   4. Every gcloud call goes through `gc` (deploy/gcp/gcloud-auth.sh): an auth error re-activates the service
#      account from TB_SA_KEY_FILE and retries once; a probe before the start fails fast.
#   5. Every part is resumable: a restarted VM runs complete_run --resume (parts with a passed result are kept).
# Optional TB_BUCKET=gs://<bucket>: code and results go through the bucket (the VM's service account needs
# storage access); without it they go over HTTP to the VM, the key in the Authorization header.
set -euo pipefail
DRY=0; STOP=0; ESTIMATE=0; WAIT=1; PATIENTS=50000; HOURS=""; COLLECT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --stop) STOP=1; shift ;;
    --estimate) ESTIMATE=1; shift ;;
    --no-wait) WAIT=0; shift ;;
    --patients) PATIENTS="$2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    --collect) COLLECT="$2"; shift 2 ;;
    -h|--help) sed -n 2,33p "$0"; exit 0 ;;
    *) break ;;
  esac
done
VM="${1:-tb-gpu-sim}"; ZONE="${2:-asia-east1-a}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
BUCKET="${TB_BUCKET:-}"
export GC_DRY="$DRY"
# shellcheck source=deploy/gcp/gcloud-auth.sh
. "$ROOT/deploy/gcp/gcloud-auth.sh"
cd "$ROOT"

if [ "$ESTIMATE" = 1 ]; then
  exec env PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --estimate --patients "$PATIENTS" \
    ${TB_ESTIMATE_FROM:+--estimate-from "$TB_ESTIMATE_FROM"}
fi
if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG and activate the service account in it}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"*) echo "CLOUDSDK_CONFIG must be private" >&2; exit 2 ;; esac
fi
unset CLOUDSDK_AUTH_ACCESS_TOKEN

status() { if [ "$DRY" = 1 ]; then echo TERMINATED; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(status)' || echo unknown; fi; }
stop_vm() {
  gc compute instances stop "$VM" --zone "$ZONE" || true
  local s; s="$(status)"
  echo "VM $VM status: $s"
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file startup-script="$ROOT/deploy/gcp/gpu-sim-startup.sh" || true
}
if [ "$STOP" = 1 ]; then stop_vm; exit 0; fi

RUN_ID="${COLLECT:-${TB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)}}"
OUT="${TB_COMPLETE_DIR:-$ROOT/.cache/complete-run/$RUN_ID}"
mkdir -p "$OUT"
umask 077
KEYF="$OUT/tb-key"

ip() { if [ "$DRY" = 1 ]; then echo "<vm-ip>"; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)'; fi; }
door() {  # METHOD PATH [curl args...]: the VM's door, the key in a header read from the key file (never argv)
  local m=$1 p=$2; shift 2
  if [ "$DRY" = 1 ]; then echo "+ curl -X $m http://<vm-ip>/tb/$p (Authorization from $KEYF)"; return 0; fi
  curl -fsS --max-time 600 -X "$m" -H @<(printf 'Authorization: Bearer %s\n' "$(cat "$KEYF")") "http://$IP/tb/$p" "$@"
}

if [ -z "$COLLECT" ]; then
  # -------------------------------------------------------------- the estimate and the cap
  EST="$(PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --estimate --json --patients "$PATIENTS" \
    ${TB_ESTIMATE_FROM:+--estimate-from "$TB_ESTIMATE_FROM"})"
  read -r EST_H CAP_H EST_USD < <(printf '%s' "$EST" | "$PY" -c 'import json,sys; e=json.load(sys.stdin); print(e["hours"], e["cap_hours"], e["usd"])')
  CAP_H="${HOURS:-$CAP_H}"
  echo "run $RUN_ID: $PATIENTS patients; estimate ${EST_H} h (US\$${EST_USD}); hard cap ${CAP_H} h (STOP), at most US\$$("$PY" -c "print(round($CAP_H*2.74, 2))")"
  [ -n "$(git status --porcelain)" ] && echo "note: local changes are NOT in the run; it runs HEAD $(git rev-parse --short HEAD)" >&2
  gc_probe
  s="$(status)"
  [ "$s" = TERMINATED ] || { echo "$VM is $s, not TERMINATED: stop it first (--stop) or collect its run" >&2; exit 3; }

  # -------------------------------------------------------------- 1. the cloud-side hard cap, before the start
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${CAP_H}h" --instance-termination-action=STOP
  [ "$DRY" = 1 ] || gc compute instances describe "$VM" --zone "$ZONE" \
    --format='value(scheduling.maxRunDuration.seconds,scheduling.instanceTerminationAction)'

  # -------------------------------------------------------------- the code, the key, the metadata, the start
  if [ "$DRY" = 1 ]; then
    echo "+ git archive --format=tar.gz -o $OUT/src.tgz HEAD trialbox; a random key into $KEYF (0600)"
  else
    git -C "$ROOT/.." archive --format=tar.gz -o "$OUT/src.tgz" HEAD trialbox
    "$PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$KEYF"
  fi
  [ -n "$BUCKET" ] && gc storage cp "$OUT/src.tgz" "$BUCKET/runs/$RUN_ID/src.tgz"
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
    "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-key=$KEYF" \
    --metadata "tb-run-id=$RUN_ID,tb-patients=$PATIENTS,tb-max-minutes=$((CAP_H * 60 - 5)),tb-idle-minutes=20,tb-done-grace=30${BUCKET:+,tb-bucket=$BUCKET}"
  gc compute instances start "$VM" --zone "$ZONE"
  echo "started $VM; it stops itself (cap ${CAP_H} h, watchdog 20 min idle). Pick the run up again with: $0 --collect $RUN_ID"
  IP="$(ip)"
  if [ -z "$BUCKET" ]; then  # 3. the code over HTTP once the door is up (the VM waits 30 minutes for it)
    for _ in $(seq 1 90); do door POST heartbeat >/dev/null 2>&1 && break; [ "$DRY" = 1 ] && break; sleep 20; done
    door PUT upload --data-binary @"$OUT/src.tgz" -H 'Content-Type: application/gzip'
  fi
  [ "$WAIT" = 1 ] || exit 0
else
  [ -f "$KEYF" ] || { echo "no key for run $RUN_ID in $OUT" >&2; exit 2; }
  IP="$(ip)"
fi

# ---------------------------------------------------------------- poll: short calls only, nothing held open
while :; do
  s="$(status)"
  echo "$(date -u +%H:%M) $VM $s"
  [ "$s" = RUNNING ] || break
  door POST heartbeat >/dev/null 2>&1 || true
  p="$(door GET progress 2>/dev/null || true)"
  printf '%s\n' "$p" | tail -n 3
  printf '%s' "$p" | grep -q '^DONE' && break
  [ "$DRY" = 1 ] && break
  sleep 60
done

# ---------------------------------------------------------------- the results, then the stub parts here
if [ -n "$BUCKET" ]; then gc storage cp "$BUCKET/runs/$RUN_ID/results.tgz" "$OUT/results.tgz" || true
else door GET results.tgz -o "$OUT/results.tgz" || echo "results not reachable: the VM has stopped; start it to resume, or --collect later" >&2
fi
door POST collected >/dev/null 2>&1 || true   # the VM powers off now
if [ "$DRY" = 1 ]; then
  echo "+ tar -xzf $OUT/results.tgz -C $OUT"
  echo "+ $PY -m tools.complete_run --dir $OUT --resume --only walk backup update scale"
  echo "+ $PY -m tools.complete_run --dir $OUT --report-only --model pair --patients $PATIENTS"
  exit 0
fi
[ -f "$OUT/results.tgz" ] || exit 4
tar -xzf "$OUT/results.tgz" -C "$OUT"
rm -f "$KEYF"
env TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" --resume --only walk backup update scale || true
env TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" --report-only --model pair \
  --patients "$PATIENTS" --live-record "$OUT/serving_config.rtxpro6000.live.json"
echo "report: $OUT/report/report.md; VM status: $(status)"
