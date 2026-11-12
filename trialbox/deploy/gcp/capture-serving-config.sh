#!/usr/bin/env bash
# FR-MOD-10 (D-111): the serving-configuration record of the judge and verifier on the GPU VM (tb-gpu-sim).
#
#   deploy/gcp/capture-serving-config.sh prepare [VM] [ZONE]   # VM stopped or running: attach the capture code
#   (start the VM on purpose: docs/RUNBOOK.md §11; the startup script captures once both servers answer)
#   deploy/gcp/capture-serving-config.sh fetch   [VM] [ZONE]   # VM running: download and check the record
#
# The VM's startup script (gpu-sim-startup.sh) runs tools/serving_config.py capture on the box (docker inspect,
# nvidia-smi, vllm version, sha256 of every model file under /models) into /root/record/serving_config.json; fetch
# reads it over `gcloud compute ssh` (T-119: the VM's port 80 is on loopback only, nothing over plain HTTP). This
# script never creates, starts or stops a VM. Hashing ~25 GB of weights adds a few minutes after the servers are up.
set -euo pipefail
CMD="${1:-}"; VM="${2:-tb-gpu-sim}"; ZONE="${3:-asia-east1-a}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
case "$CMD" in
  prepare)
    gcloud compute instances add-metadata "$VM" --zone "$ZONE" \
      --metadata-from-file tb-serving-config="$ROOT/tools/serving_config.py"
    echo "attached; the next boot of $VM records the serving configuration" ;;
  fetch)
    STATUS="$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(status)')"
    if [ "$STATUS" != "RUNNING" ]; then
      echo "VM $VM is $STATUS, not RUNNING. This script does not start VMs." >&2
      exit 2
    fi
    OUT="$ROOT/eval/parity/serving_config_$(date -u +%Y-%m-%d)_${VM}.json"
    for _ in $(seq 1 20); do
      gcloud compute ssh "$VM" --zone "$ZONE" --command 'sudo cat /root/record/serving_config.json' > "$OUT.part" \
        2>/dev/null && [ -s "$OUT.part" ] && break
      sleep 30
    done
    [ -s "$OUT.part" ] || { rm -f "$OUT.part"; echo "no record on $VM yet (/root/record/serving_config.json)" >&2; exit 3; }
    mv -f "$OUT.part" "$OUT"
    "${PY:-python3}" "$ROOT/tools/serving_config.py" validate "$OUT"
    echo "record: $OUT" ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
