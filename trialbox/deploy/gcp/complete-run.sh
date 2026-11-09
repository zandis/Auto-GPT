#!/usr/bin/env bash
# TrialBox complete-platform run on the RTX PRO 6000 (TB-PLAN-04 step 9, D-139). Owner's OK first: it starts a paid
# VM (tb-gpu-sim, g4-standard-48 spot, about US$2.74 an hour; D-139 has the estimate).
#
#   export CLOUDSDK_CONFIG=$(mktemp -d)          # a private gcloud config, never the default one
#   gcloud auth activate-service-account --key-file <the key file, in place> && gcloud config set project trialbox-demo
#   deploy/gcp/complete-run.sh [--dry-run] [--patients 50000] [VM] [ZONE]
#
# 1. Puts deploy/gcp/gpu-pro6000-run.sh on the VM as its startup script, with tools/serving_config.py and a fresh
#    random API key (made here into a 0600 file, given to the VM as metadata "tb-key", never printed).
# 2. Starts the VM and waits for PRO6000-RUN-READY on the serial port (judge Gemma 4 26B-A4B NVFP4 and verifier
#    Qwen3.5-9B AWQ resident, 32k, 0.40 + 0.20 of the card; D-124).
# 3. Fetches the live serving record and checks `serving_config.py measured rtxpro6000` on it.
# 4. Runs tools/complete_run.py from this checkout with --model pair against http://<vm>/judge/v1 and /verifier/v1:
#    install check, the 50,000-patient hospital in ja and zh-TW, the public site in ja and zh-TW, the walk, backup,
#    update, the cascade at scale. Report: <dir>/report/report.md and report.json, screenshots in report/shots/.
# 5. Always, also on failure or Ctrl-C: stops the VM, waits until it shows TERMINATED, and puts the usual startup
#    script (gpu-sim-startup.sh) back.
set -euo pipefail
DRY=0; PATIENTS=50000
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --patients) PATIENTS="$2"; shift 2 ;;
    -h|--help) sed -n 2,19p "$0"; exit 0 ;;
    *) break ;;
  esac
done
VM="${1:-tb-gpu-sim}"; ZONE="${2:-asia-east1-a}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${TB_COMPLETE_DIR:-/tmp/tb-complete-gpu}"
PY="${PY:-$ROOT/.venv/bin/python}"

run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }

if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG (export CLOUDSDK_CONFIG=\$(mktemp -d)) and activate the service account in it}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"*) echo "CLOUDSDK_CONFIG must be private, not $CLOUDSDK_CONFIG" >&2; exit 2 ;; esac
fi
unset CLOUDSDK_AUTH_ACCESS_TOKEN
umask 077
mkdir -p "$OUT"
KEYF="$OUT/tb-key"
"$PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$KEYF"

STARTED=0
finish() {
  rc=$?
  if [ "$STARTED" = 1 ]; then
    echo "stopping $VM"
    run gcloud compute instances stop "$VM" --zone "$ZONE" || true
    if [ "$DRY" = 0 ]; then
      for _ in $(seq 1 60); do
        S="$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(status)' || echo unknown)"
        [ "$S" = TERMINATED ] && break
        sleep 10
      done
      echo "VM $VM status: $S"
      [ "$S" = TERMINATED ] || { echo "WARNING: $VM is not TERMINATED: stop it by hand" >&2; rc=3; }
    fi
    run gcloud compute instances add-metadata "$VM" --zone "$ZONE" \
      --metadata-from-file startup-script="$ROOT/deploy/gcp/gpu-sim-startup.sh" || true
  fi
  rm -f "$KEYF"
  exit "$rc"
}
trap finish EXIT INT TERM

run gcloud compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
  "startup-script=$ROOT/deploy/gcp/gpu-pro6000-run.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-key=$KEYF"
STARTED=1
T0=$(date +%s)
run gcloud compute instances start "$VM" --zone "$ZONE"

if [ "$DRY" = 1 ]; then
  IP="<vm-ip>"
else
  IP="$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)')"
  echo "waiting for PRO6000-RUN-READY on $VM ($IP); about 15 minutes"
  for i in $(seq 1 90); do
    gcloud compute instances get-serial-port-output "$VM" --zone "$ZONE" 2>/dev/null | grep -q PRO6000-RUN-READY && break
    [ "$i" = 90 ] && { echo "the pair did not come up in 45 minutes" >&2; exit 4; }
    sleep 30
  done
fi
echo "ready after $(( $(date +%s) - T0 )) s"

REC="$OUT/serving_config.rtxpro6000.live.json"
run curl -fsS --retry 20 --retry-delay 15 --retry-all-errors -o "$REC" "http://$IP/record/serving_config.json"
run "$PY" "$ROOT/tools/serving_config.py" measured rtxpro6000 "$REC"

cd "$ROOT"
RC=0
if [ "$DRY" = 1 ]; then
  echo "+ TB_GPU_KEY=<from $KEYF> $PY -m tools.complete_run --dir $OUT --model pair --patients $PATIENTS" \
       "--judge-url http://$IP/judge/v1 --verifier-url http://$IP/verifier/v1 --live-record $REC"
else
  TB_GPU_KEY="$(cat "$KEYF")" TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" \
    --model pair --patients "$PATIENTS" --judge-url "http://$IP/judge/v1" --verifier-url "http://$IP/verifier/v1" \
    --live-record "$REC" || RC=$?
fi
run curl -fsS -o "$OUT/report/gpu_peak.json" "http://$IP/record/gpu_peak.json" || true
echo "VM time so far: $(( ($(date +%s) - T0) / 60 )) min; report: $OUT/report/report.md"
exit "$RC"
