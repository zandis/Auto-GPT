#!/bin/bash
# TrialBox one-5090 sleep-swap run on tb-gpu-sim (TB-PLAN-03 step 1, D-116): the RTX PRO 6000 (96 GB) capped to
# the 5090's 32 GB as the compose profile runs it (deploy/docker-compose.rtx5090.yml): both vLLM servers with
# --enable-sleep-mode, each at 0.27 of 96 GB (= 0.81 of a 32 GB card), 8k context, 4 sequences, one awake at a time.
# Used as the VM's startup script for one boot (the usual one is gpu-sim-startup.sh).
#
# Order, so that answers before any sleep can be compared with answers after a wake (tools/wake_check.py):
#   1. the judge starts and serves, never slept;
#   2. this script waits until a caller puts the judge to sleep (POST /judge/sleep?level=1), then starts the
#      verifier, which finds the card free;
#   3. from then on the caller swaps them (/judge/wake_up, /verifier/sleep ...), as the gateway would.
# nginx 127.0.0.1:80 (an ssh tunnel, T-119): /judge/ and /verifier/ (whole servers: /v1, /health, /sleep, /wake_up, /is_sleeping), /record/ (this
# script's measurements: gpu_peak.json, a 2-second sample of the card's used memory, and serving_config.json).
# The API key is made on the VM (/root/tb-key, T-119); it is never written to the record.
exec > >(tee -a /var/log/tb-swap.log /dev/ttyS0) 2>&1
# the API key (T-119, CR-048): made here at the first boot, root-only in /root/tb-key, never in the metadata. Port 80
# is on loopback only: reach it with `gcloud compute ssh <vm> --zone <zone> -- -N -L 8080:127.0.0.1:80` and read the
# key over the same ssh (`sudo cat /root/tb-key`); nothing crosses the internet in plain HTTP.
[ -s /root/tb-key ] || (umask 077; head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 43 > /root/tb-key)
KEY=$(cat /root/tb-key)
# no `set -x`: the API key is on the docker command lines
VLLM=vllm/vllm-openai:v0.32.0
J=nvidia/Gemma-4-26B-A4B-NVFP4
V=cyankiwi/Qwen3.5-9B-AWQ-4bit
UTIL=${TB_SWAP_UTIL:-0.27}
REC=/root/record
mkdir -p $REC /models
chmod 755 $REC
nvidia-smi
docker rm -f judge verifier front 2>/dev/null
docker network create tb 2>/dev/null

# the verifier container does not exist yet when nginx starts, so upstreams are resolved per request through
# docker's DNS (a plain proxy_pass to http://verifier:8000 makes nginx refuse to start: host not found)
cat > /root/nginx.conf <<'NG'
events {}
http { resolver 127.0.0.11 valid=5s ipv6=off;
  server { listen 80; client_max_body_size 10m; proxy_read_timeout 900s;
  location /judge/    { set $up judge;    rewrite ^/judge/(.*)$ /$1 break;    proxy_pass http://$up:8000; }
  location /verifier/ { set $up verifier; rewrite ^/verifier/(.*)$ /$1 break; proxy_pass http://$up:8000; }
  location /record/   { alias /srv/record/; default_type application/json; } } }
NG
docker run -d --name front --network tb -p 127.0.0.1:80:80 -v /root/nginx.conf:/etc/nginx/nginx.conf:ro \
  -v $REC:/srv/record:ro nginx:1.27-alpine

# card memory every 2 s: the current and the peak, with the phase the caller is in (who is awake)
python3 - <<'PY' &
import json, subprocess, time, urllib.request
peak, out = 0, "/root/record/gpu_peak.json"
def awake(name):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1/{name}/is_sleeping", timeout=2) as r:
            return not json.load(r).get("is_sleeping")
    except Exception:  # noqa: BLE001  (not started yet, or loading)
        return None
while True:
    try:
        used = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]).split()[0])
        total = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]).split()[0])
    except Exception:  # noqa: BLE001
        time.sleep(2); continue
    peak = max(peak, used)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "used_mib": used, "peak_mib": peak,
           "total_mib": total, "judge_awake": awake("judge"), "verifier_awake": awake("verifier")}
    json.dump(rec, open(out + ".tmp", "w")); subprocess.run(["mv", out + ".tmp", out])
    with open("/root/record/gpu_samples.jsonl", "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    time.sleep(2)
PY

start() {  # name model served [extra...]
  local name=$1 model=$2 served=$3; shift 3
  docker run -d --name "$name" --network tb --gpus all --ipc host -e VLLM_SERVER_DEV_MODE=1 \
    -v /models:/root/.cache/huggingface $VLLM --model "$model" --served-model-name "$served" \
    --max-model-len 8192 --max-num-seqs 4 --enforce-eager --gpu-memory-utilization "$UTIL" --enable-sleep-mode \
    --api-key "$KEY" "$@"
}
healthy() { docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null; }
sleeping() { docker exec "$1" python3 -c "import json,urllib.request,sys;sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8000/is_sleeping',timeout=3)).get('is_sleeping') else 1)" 2>/dev/null; }

start judge $J local/gemma-4-26b-a4b-nvfp4 --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
for i in $(seq 1 240); do healthy judge && break; sleep 5; done
echo JUDGE-UP
for i in $(seq 1 2160); do sleeping judge && break; sleep 5; done   # up to 3 h for the caller's resident pass
echo JUDGE-ASLEEP
start verifier $V local/qwen3.5-9b-awq --limit-mm-per-prompt '{"image":0,"video":0}' \
  --default-chat-template-kwargs '{"enable_thinking": false}'
for i in $(seq 1 240); do healthy verifier && break; sleep 5; done
echo VERIFIER-UP

# FR-MOD-10 (D-111): the serving record (sha256 of every model file, flags, card), as gpu-sim-startup.sh does
SC=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-serving-config || true)
if [ -n "$SC" ]; then
  printf '%s\n' "$SC" > /root/serving_config.py
  python3 /root/serving_config.py capture --container judge=judge --container verifier=verifier --models-dir /models \
    --capped-to "RTX 5090 (32 GB), by --gpu-memory-utilization $UTIL of 96 GB with --enable-sleep-mode (one awake)" \
    --notes "one-5090 sleep swap (D-116): both servers with --enable-sleep-mode, one awake at a time" \
    --out $REC/serving_config.json || true
  chmod 644 $REC/serving_config.json 2>/dev/null || true
fi
echo SWAP-RUN-READY
