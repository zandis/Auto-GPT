#!/usr/bin/env bash
# FR-MOD-10 (D-111): the serving-configuration record of the judge and verifier on the GPU VM (tb-gpu-sim).
#
#   deploy/gcp/capture-serving-config.sh prepare [VM] [ZONE]   # VM stopped or running: attach the capture code
#   (start the VM on purpose: docs/SERVING_CONFIG.md; the startup script captures once both servers answer)
#   deploy/gcp/capture-serving-config.sh fetch   [VM] [ZONE]   # VM running: download and check the record
#
# The VM's startup script (gpu-sim-startup.sh) runs tools/serving_config.py capture on the box (docker inspect,
# nvidia-smi, vllm version, sha256 of every model file under /models) and serves the JSON on :80 at
# /record/serving_config.json; this container reaches the VM over HTTP only. This script never creates, starts or
# stops a VM. Hashing ~25 GB of weights adds a few minutes after the servers are up.
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
    IP="$(gcloud compute instances describe "$VM" --zone "$ZONE" \
      --format='value(networkInterfaces[0].accessConfigs[0].natIP)')"
    OUT="$ROOT/eval/parity/serving_config_$(date -u +%Y-%m-%d)_${VM}.json"
    curl -fsS --retry 20 --retry-delay 30 --retry-all-errors -o "$OUT" "http://$IP/record/serving_config.json"
    "${PY:-python3}" "$ROOT/tools/serving_config.py" validate "$OUT"
    echo "record: $OUT" ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
