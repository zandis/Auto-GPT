#!/usr/bin/env bash
# FR-MOD-10 (D-111): capture the serving-configuration record of the judge and verifier running on the GPU VM.
# Copies tools/serving_config.py to the VM, runs `capture` there (docker inspect, nvidia-smi, vllm version, sha256 of
# every model file under /models) and fetches the JSON into eval/parity/.
#
# It never creates or starts a VM: the VM must already be RUNNING with both vLLM containers up (see
# docs/SERVING_CONFIG.md for how it is started and what it costs). Hashing ~25 GB of weights takes a few minutes.
#
#   deploy/gcp/capture-serving-config.sh [VM] [ZONE]      # defaults: tb-gpu-sim asia-east1-a
set -euo pipefail
VM="${1:-tb-gpu-sim}"
ZONE="${2:-asia-east1-a}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAMP="$(date -u +%Y-%m-%d)"
OUT="$ROOT/eval/parity/serving_config_${STAMP}_${VM}.json"
STATUS="$(gcloud compute instances describe "$VM" --zone "$ZONE" --format='value(status)')"
if [ "$STATUS" != "RUNNING" ]; then
  echo "VM $VM is $STATUS, not RUNNING. This script does not start VMs; start it on purpose first." >&2
  exit 2
fi
gcloud compute scp --zone "$ZONE" "$ROOT/tools/serving_config.py" "$VM:/tmp/serving_config.py"
gcloud compute ssh "$VM" --zone "$ZONE" --command \
  "sudo python3 /tmp/serving_config.py capture --container judge=judge --container verifier=verifier \
   --models-dir /models --capped-to '${TB_CAPPED_TO:-RTX 5090 (32 GB)}' --notes '${TB_CAPTURE_NOTES:-}' \
   --out /tmp/serving_config.json; sudo chmod 644 /tmp/serving_config.json" || true
gcloud compute scp --zone "$ZONE" "$VM:/tmp/serving_config.json" "$OUT"
"${PY:-python3}" "$ROOT/tools/serving_config.py" validate "$OUT"
echo "record: $OUT"
