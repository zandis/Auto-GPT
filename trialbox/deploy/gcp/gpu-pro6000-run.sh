#!/bin/bash
# TrialBox RTX PRO 6000 profile run on tb-gpu-sim (TB-PLAN-04 step 1, D-124): the card uncapped, judge and verifier
# both resident with the flags of deploy/docker-compose.rtxpro6000.yml (32k context, 16 sequences, 0.40 and 0.20 of
# the card, no sleep mode). Used as the VM's startup script for one boot (the usual one is gpu-sim-startup.sh):
#
#   gcloud compute instances add-metadata tb-gpu-sim --zone asia-east1-a \
#     --metadata-from-file startup-script=deploy/gcp/gpu-pro6000-run.sh,tb-serving-config=tools/serving_config.py
#   (start the VM only with the owner's OK: about US$2.74 an hour; docs/SERVING_CONFIG.md)
#
# nginx :80: /judge/ and /verifier/ (whole servers), /record/ (serving_config.json, written with no capped_to so
# that `tools/serving_config.py measured rtxpro6000` accepts it, and gpu_peak.json). The API key comes from the
# instance metadata "tb-key" and is never written to the record.
exec > >(tee -a /var/log/tb-pro6000.log /dev/ttyS0) 2>&1
KEY=$(curl -s -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-key)
# no `set -x`: the API key is on the docker command lines
VLLM=vllm/vllm-openai:v0.32.0
J=nvidia/Gemma-4-26B-A4B-NVFP4
V=cyankiwi/Qwen3.5-9B-AWQ-4bit
LEN=${TB_PRO_LEN:-32768}
SEQS=${TB_PRO_SEQS:-16}
REC=/root/record
mkdir -p $REC /models
chmod 755 $REC
nvidia-smi
docker rm -f judge verifier front 2>/dev/null
docker network create tb 2>/dev/null

cat > /root/nginx.conf <<'NG'
events {}
http { resolver 127.0.0.11 valid=5s ipv6=off;
  server { listen 80; client_max_body_size 10m; proxy_read_timeout 900s;
  location /judge/    { set $up judge;    rewrite ^/judge/(.*)$ /$1 break;    proxy_pass http://$up:8000; }
  location /verifier/ { set $up verifier; rewrite ^/verifier/(.*)$ /$1 break; proxy_pass http://$up:8000; }
  location /record/   { alias /srv/record/; default_type application/json; } } }
NG
docker run -d --name front --network tb -p 80:80 -v /root/nginx.conf:/etc/nginx/nginx.conf:ro \
  -v $REC:/srv/record:ro nginx:1.27-alpine

# peak card memory every 2 s (both resident: the peak is the profile's footprint under load)
python3 - <<'PY' &
import json, subprocess, time
peak, out = 0, "/root/record/gpu_peak.json"
while True:
    try:
        q = ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]
        used, total = (int(x) for x in subprocess.check_output(q).decode().split(","))
    except Exception:  # noqa: BLE001
        time.sleep(2); continue
    peak = max(peak, used)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "used_mib": used, "peak_mib": peak, "total_mib": total}
    json.dump(rec, open(out + ".tmp", "w")); subprocess.run(["mv", out + ".tmp", out])
    time.sleep(2)
PY

start() {  # name model served util [extra...]
  local name=$1 model=$2 served=$3 util=$4; shift 4
  docker run -d --name "$name" --network tb --gpus all --ipc host -v /models:/root/.cache/huggingface \
    --restart unless-stopped $VLLM --model "$model" --served-model-name "$served" \
    --max-model-len "$LEN" --max-num-seqs "$SEQS" --enforce-eager --gpu-memory-utilization "$util" \
    --api-key "$KEY" "$@"
}
healthy() { docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null; }

start judge $J local/gemma-4-26b-a4b-nvfp4 0.40 --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
for i in $(seq 1 240); do healthy judge && break; sleep 5; done
docker logs judge 2>&1 | grep -aE 'Error|KV cache|Started' | tail -6 | sed 's/^/TBJ /'
echo JUDGE-UP
start verifier $V local/qwen3.5-9b-awq 0.20 --limit-mm-per-prompt '{"image":0,"video":0}' \
  --default-chat-template-kwargs '{"enable_thinking": false}'
for i in $(seq 1 240); do healthy verifier && break; sleep 5; done
docker logs verifier 2>&1 | grep -aE 'Error|KV cache|Started' | tail -6 | sed 's/^/TBV /'
echo VERIFIER-UP
nvidia-smi --query-gpu=memory.used,memory.total --format=csv

# FR-MOD-10 (D-111): the serving record of the uncapped card (no --capped-to), with the sha256 of every model file
SC=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-serving-config || true)
if [ -n "$SC" ]; then
  printf '%s\n' "$SC" > /root/serving_config.py
  python3 /root/serving_config.py capture --container judge=judge --container verifier=verifier --models-dir /models \
    --notes "rtxpro6000 profile (D-124): both resident, ${LEN} context, ${SEQS} sequences, 0.40 + 0.20 of the card" \
    --out $REC/serving_config.json || true
  chmod 644 $REC/serving_config.json 2>/dev/null || true
fi
echo PRO6000-RUN-READY
