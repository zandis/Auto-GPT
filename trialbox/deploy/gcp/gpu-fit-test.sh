#!/bin/bash
# TrialBox 32 GB fit test on tb-gpu-sim (one RTX PRO 6000, 96 GB, capped by --gpu-memory-utilization to RTX 5090
# sizes). Used as the VM's startup script for one boot (the usual one is gpu-sim-startup.sh); the driver reaches
# it over an ssh tunnel, so every result is written to /root/record/fit.json and served at 127.0.0.1:80/record/ (an ssh tunnel).
#
# Cases (same vLLM image and model files as the 6 Nov pair):
#   judge-alone / verifier-alone   one model at 0.30 of 96 GB (= 28.8 GB, 0.90 of a 32 GB card), 8k context, 4 seqs
#   pair-tight                     both resident at 4k context, 2 seqs, 0.20 + 0.093 (the compose's 32 GB caps)
#   sleep-swap                     time-shared: both started with --enable-sleep-mode, one asleep (level 1, weights
#                                  to CPU) while the other serves; swap time and peak GiB measured
# For each: did it start, seconds to ready, nvidia-smi memory.used at rest and after one judge request, a one-line
# answer check. Nothing else on the card while it runs.
exec > >(tee -a /var/log/tb-fit.log /dev/ttyS0) 2>&1
# no `set -x` (review A-12): the API key is on the docker command lines and would go to the serial log
# the API key (T-119, CR-048): made here at the first boot, root-only in /root/tb-key, never in the metadata. Port 80
# is on loopback only: reach it with `gcloud compute ssh <vm> --zone <zone> -- -N -L 8080:127.0.0.1:80` and read the
# key over the same ssh (`sudo cat /root/tb-key`); nothing crosses the internet in plain HTTP.
[ -s /root/tb-key ] || (umask 077; head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 43 > /root/tb-key)
KEY=$(cat /root/tb-key)
VLLM=vllm/vllm-openai:v0.32.0
J=nvidia/Gemma-4-26B-A4B-NVFP4
V=cyankiwi/Qwen3.5-9B-AWQ-4bit
REC=/root/record
mkdir -p $REC /models
echo '{"status": "running", "cases": []}' > $REC/fit.json
chmod 644 $REC/fit.json
docker rm -f judge verifier front 2>/dev/null
docker network create tb 2>/dev/null
cat > /root/nginx-fit.conf <<'NG'
events {}
http { server { listen 80; location /record/ { alias /srv/record/; default_type application/json; } } }
NG
docker run -d --name front -p 127.0.0.1:80:80 -v /root/nginx-fit.conf:/etc/nginx/nginx.conf:ro -v $REC:/srv/record:ro nginx:1.27-alpine

used() { local u; u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1); echo "${u:-null}"; }
add() {  # add one case result (a JSON object) to fit.json
  python3 - "$1" <<'PY'
import json, sys
p = "/root/record/fit.json"
d = json.load(open(p))
try:
    case = json.loads(sys.argv[1])
except ValueError:
    case = {"unparsed": sys.argv[1][:4000]}  # keep the measurement even if one field broke the JSON
d["cases"].append(case); json.dump(d, open(p, "w"), indent=1)
PY
}
start() {  # name model served util len seqs [extra...]
  local name=$1 model=$2 served=$3 util=$4 len=$5 seqs=$6; shift 6
  docker run -d --name "$name" --network tb --gpus all --ipc host -e VLLM_SERVER_DEV_MODE=1 \
    -v /models:/root/.cache/huggingface $VLLM --model "$model" --served-model-name "$served" \
    --max-model-len "$len" --max-num-seqs "$seqs" --enforce-eager --gpu-memory-utilization "$util" --api-key "$KEY" "$@"
}
ready() {  # name timeout_s -> prints seconds to ready or -1
  local t0=$(date +%s)
  for i in $(seq 1 $(( $2 / 5 ))); do
    docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null && { echo $(( $(date +%s) - t0 )); return; }
    docker ps -a --filter name="^$1\$" --format '{{.Status}}' | grep -q Exited && break
    sleep 5
  done
  echo -1
}
ask() {  # name served -> prints the answer's first 80 chars as a JSON string (or "ERROR ...")
  # -i: the script comes on stdin (without it python3 read nothing and printed nothing, so 8 Nov's fit.json had
  # empty answer fields and every case was stored unparsed)
  local out
  out=$(docker exec -i "$1" python3 - "$2" "$KEY" <<'PY' 2>/dev/null | tail -1
import json, sys, urllib.request
body = {"model": sys.argv[1], "max_tokens": 40, "temperature": 0,
        "messages": [{"role": "user", "content": "Patient note: 'A 64-year-old man with lung adenocarcinoma, ECOG 1.' "
                      "Does the note state ECOG 0 or 1? Answer yes or no and quote the note."}]}
req = urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions", json.dumps(body).encode(),
                             {"Content-Type": "application/json", "Authorization": "Bearer " + sys.argv[2]})
try:
    out = json.load(urllib.request.urlopen(req, timeout=300))
    print(json.dumps(out["choices"][0]["message"]["content"][:80]))
except Exception as e:  # noqa: BLE001
    print(json.dumps("ERROR " + str(e)[:70]))
PY
)
  case "$out" in \"*) echo "$out" ;; *) echo '"ERROR no answer"' ;; esac
}
jstr() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }  # any text as a JSON string
post() {  # name path -> seconds the POST took
  local t0=$(date +%s.%N)
  docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000$2',data=b'',method='POST',headers={'Authorization':'Bearer $KEY'}),timeout=600)" 2>&1 | tail -1
  python3 -c "import time;print(round(time.time()-$t0,1))"
}
logs() {  # the last memory/error lines of a server, as a JSON string (quotes, backslashes and control bytes escaped)
  jstr "$(docker logs "$1" 2>&1 | grep -aE 'Error|out of memory|KV cache|Available|Loading weights took|Model loading took' | tail -4 | tr '\n' ' ' | cut -c1-600)"
}
clear_card() { docker rm -f judge verifier >/dev/null 2>&1; sleep 10; }
nvidia-smi
BASE=$(used)

# ---- 1-2: each model alone at 0.90 of a 32 GB card, 8k context, 4 sequences
for spec in "judge $J local/gemma-4-26b-a4b-nvfp4" "verifier $V local/qwen3.5-9b-awq"; do
  set -- $spec
  extra=(--limit-mm-per-prompt '{"image":0,"audio":0,"video":0}')
  [ "$1" = verifier ] && extra=(--limit-mm-per-prompt '{"image":0,"video":0}' --default-chat-template-kwargs '{"enable_thinking": false}')
  start "$1" "$2" "$3" 0.30 8192 4 "${extra[@]}"
  s=$(ready "$1" 1200); u0=$(used); a=$(ask "$1" "$3"); u1=$(used)
  add "{\"case\": \"$1-alone\", \"util\": 0.30, \"max_model_len\": 8192, \"max_num_seqs\": 4, \"started\": $([ "$s" -ge 0 ] && echo true || echo false), \"seconds_to_ready\": $s, \"base_mib\": $BASE, \"used_mib_ready\": $u0, \"used_mib_after_request\": $u1, \"answer\": $a, \"log\": $(logs "$1")}"
  clear_card
done

# ---- 3: both resident, tight caps (4k context, 2 sequences, the compose's 0.60 / 0.28 of 32 GB)
start judge $J local/gemma-4-26b-a4b-nvfp4 0.20 4096 2 --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
sj=$(ready judge 1200)
start verifier $V local/qwen3.5-9b-awq 0.093 4096 2 --limit-mm-per-prompt '{"image":0,"video":0}' --default-chat-template-kwargs '{"enable_thinking": false}'
sv=$(ready verifier 1200); u0=$(used)
aj=$(ask judge local/gemma-4-26b-a4b-nvfp4); av=$(ask verifier local/qwen3.5-9b-awq); u1=$(used)
add "{\"case\": \"pair-tight\", \"util\": [0.20, 0.093], \"max_model_len\": 4096, \"max_num_seqs\": 2, \"judge_seconds\": $sj, \"verifier_seconds\": $sv, \"base_mib\": $BASE, \"used_mib_ready\": $u0, \"used_mib_after_request\": $u1, \"answer_judge\": $aj, \"answer_verifier\": $av, \"log_judge\": $(logs judge), \"log_verifier\": $(logs verifier)}"
clear_card

# ---- 4: time-shared with sleep mode, 8k context, 4 sequences, each 0.27 of 96 GB (25.9 GB) when awake
start judge $J local/gemma-4-26b-a4b-nvfp4 0.27 8192 4 --enable-sleep-mode --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
sj=$(ready judge 1200); uj=$(used); aj1=$(ask judge local/gemma-4-26b-a4b-nvfp4)
tsj=$(post judge /sleep?level=1 | tail -1); ujs=$(used)
start verifier $V local/qwen3.5-9b-awq 0.27 8192 4 --enable-sleep-mode --limit-mm-per-prompt '{"image":0,"video":0}' --default-chat-template-kwargs '{"enable_thinking": false}'
sv=$(ready verifier 1200); uv=$(used); av=$(ask verifier local/qwen3.5-9b-awq); uva=$(used)
tsv=$(post verifier /sleep?level=1 | tail -1); uvs=$(used)
twj=$(post judge /wake_up | tail -1); ujw=$(used); aj2=$(ask judge local/gemma-4-26b-a4b-nvfp4); ujwa=$(used)
tsj2=$(post judge /sleep?level=1 | tail -1); twv=$(post verifier /wake_up | tail -1); uvw=$(used); av2=$(ask verifier local/qwen3.5-9b-awq)
add "{\"case\": \"sleep-swap\", \"util\": 0.27, \"max_model_len\": 8192, \"max_num_seqs\": 4, \"judge_seconds\": $sj, \"verifier_seconds\": $sv, \"base_mib\": $BASE, \"used_mib_judge_awake\": $uj, \"used_mib_judge_asleep\": $ujs, \"used_mib_verifier_awake_judge_asleep\": $uv, \"used_mib_after_verifier_request\": $uva, \"used_mib_both_asleep\": $uvs, \"used_mib_judge_rewoken\": $ujw, \"used_mib_after_judge_request\": $ujwa, \"used_mib_verifier_rewoken\": $uvw, \"seconds_sleep_judge\": $tsj, \"seconds_sleep_verifier\": $tsv, \"seconds_wake_judge\": $twj, \"seconds_sleep_judge_2\": $tsj2, \"seconds_wake_verifier\": $twv, \"answer_judge_first\": $aj1, \"answer_judge_after_wake\": $aj2, \"answer_verifier\": $av, \"answer_verifier_after_wake\": $av2, \"log_judge\": $(logs judge), \"log_verifier\": $(logs verifier)}"
clear_card
python3 - <<'PY'
import json
p = "/root/record/fit.json"; d = json.load(open(p)); d["status"] = "fit-done"; json.dump(d, open(p, "w"), indent=1)
PY

# ---- 5: the Gemma QAT build (AWQ INT4) as the judge, paired with the same verifier, the 6 Nov caps; left serving
# behind nginx (/v1/ and /judge/ -> QAT, /verifier/ -> Qwen) for the SIGIR and canary runs from outside
Q=cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4
start judge $Q local/gemma-4-26b-a4b-qat-awq 0.22 8192 4 --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
sq=$(ready judge 2400); uq=$(used); aq=$(ask judge local/gemma-4-26b-a4b-qat-awq)
start verifier $V local/qwen3.5-9b-awq 0.105 8192 4 --limit-mm-per-prompt '{"image":0,"video":0}' --default-chat-template-kwargs '{"enable_thinking": false}'
sv=$(ready verifier 1200); up=$(used)
add "{\"case\": \"qat-pair\", \"util\": [0.22, 0.105], \"max_model_len\": 8192, \"max_num_seqs\": 4, \"judge_seconds\": $sq, \"verifier_seconds\": $sv, \"base_mib\": $BASE, \"used_mib_qat_alone\": $uq, \"used_mib_pair\": $up, \"answer_qat\": $aq, \"log_qat\": $(logs judge)}"
cat > /root/nginx.conf <<'NG'
events {}
http { server { listen 80; client_max_body_size 10m; proxy_read_timeout 600s;
  location /v1/       { proxy_pass http://judge:8000/v1/; }
  location /judge/    { proxy_pass http://judge:8000/; }
  location /verifier/ { proxy_pass http://verifier:8000/; }
  location /record/   { alias /srv/record/; default_type application/json; } } }
NG
docker rm -f front
docker run -d --name front --network tb -p 127.0.0.1:80:80 -v /root/nginx.conf:/etc/nginx/nginx.conf:ro -v $REC:/srv/record:ro nginx:1.27-alpine
python3 - <<'PY'
import json
p = "/root/record/fit.json"; d = json.load(open(p)); d["status"] = "done"; json.dump(d, open(p, "w"), indent=1)
PY
echo FIT-DONE
