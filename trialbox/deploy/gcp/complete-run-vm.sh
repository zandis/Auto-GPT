#!/bin/bash
# TrialBox complete run ON the RTX PRO 6000 VM (TB-PLAN-04 step 9, D-141). The VM's startup script for the run (the
# usual one is gpu-sim-startup.sh). deploy/gcp/complete-run.sh puts it there with this metadata:
#
#   tb-key          random API key of the two model servers (made by the driver, never printed)
#   tb-run-id       the run's id; tb-patients the bulk size; tb-bucket an optional gs:// bucket for code and results
#   tb-only         the parts of this VM (complete_run --only tags; a shard of a parallel run, D-148); empty: all
#   tb-max-minutes  hard cap of this boot (the driver sets the cloud cap too: max-run-duration, action STOP)
#   tb-idle-minutes the watchdog's idle limit (default 20)
#   tb-serving-config tools/serving_config.py (the serving record, D-111)
#
# The VM stops itself, whatever happens to the driver:
#   1. a hard cap (systemd timer, tb-max-minutes after boot) and the cloud's max-run-duration (set by the driver);
#   2. a watchdog: poweroff when the heartbeat file is not touched for tb-idle-minutes (the run touches it on progress,
#      the driver over HTTP), when setup takes more than 60 minutes, or when the done marker has been there for
#      tb-done-grace minutes (default 30; at once once the driver says it collected the results);
#   3. the run itself ends with the done marker.
# The workload runs here, not on the driver: the code comes from the bucket or an HTTP upload by the driver, the
# model parts run with --resume (a restart of the VM continues where it stopped), and the results wait in the bucket
# or at http://<vm>/tb/results.tgz (key needed) for the driver. Nothing ever prints the key: no `set -x` (A-12).
exec > >(tee -a /var/log/tb-complete.log /dev/ttyS0) 2>&1
set -u
md() { curl -sf -H Metadata-Flavor:Google "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
TB=/var/lib/tb
RUN="$TB/run"
HB="$TB/heartbeat"
DONE="$TB/DONE"
PHASE="$TB/phase"
mkdir -p "$RUN" "$TB/incoming" "$TB/out"
echo setup > "$PHASE"
touch "$HB"
rm -f "$DONE" "$TB/collected"

# ------------------------------------------------------------------ 1-2. the VM stops itself (first, before anything)
MAXM=$(md tb-max-minutes || echo 300)
IDLEM=$(md tb-idle-minutes || echo 20)
GRACE=$(md tb-done-grace || echo 30)
systemd-run --unit tb-hard-cap --on-active="${MAXM}min" --description "TrialBox hard cap" \
  /bin/sh -c 'echo "TB-WATCHDOG hard cap reached, powering off" >/dev/ttyS0; systemctl poweroff'
cat >/usr/local/sbin/tb-watchdog <<'EOS'
#!/bin/sh
# poweroff on: no heartbeat for $1 minutes while running; setup longer than 60 minutes; the done marker older than
# $2 minutes (or collected). Checked every minute.
idle=$1; grace=$2; tb=/var/lib/tb; boot=$(date +%s)
while :; do
  sleep 60
  now=$(date +%s); phase=$(cat $tb/phase 2>/dev/null || echo setup)
  hb=$(stat -c %Y $tb/heartbeat 2>/dev/null || echo 0)
  if [ -f $tb/DONE ]; then
    d=$(stat -c %Y $tb/DONE)
    if [ -f $tb/collected ] || [ $((now - d)) -ge $((grace * 60)) ]; then
      echo "TB-WATCHDOG done, results collected or grace over: powering off" >/dev/ttyS0; systemctl poweroff; fi
  elif [ "$phase" = setup ] && [ $((now - boot)) -ge 3600 ]; then
    echo "TB-WATCHDOG setup over 60 minutes: powering off" >/dev/ttyS0; systemctl poweroff
  elif [ "$phase" != setup ] && [ $((now - hb)) -ge $((idle * 60)) ]; then
    echo "TB-WATCHDOG no heartbeat for $idle minutes: powering off" >/dev/ttyS0; systemctl poweroff
  fi
done
EOS
chmod 0755 /usr/local/sbin/tb-watchdog
systemd-run --unit tb-watchdog --description "TrialBox watchdog" /usr/local/sbin/tb-watchdog "$IDLEM" "$GRACE"

KEY=$(md tb-key)
RUN_ID=$(md tb-run-id || echo run)
PATIENTS=$(md tb-patients || echo 50000)
ONLY=$(md tb-only || true)
BUCKET=$(md tb-bucket || true)

# ------------------------------------------------------------------ the driver's door: heartbeat, upload, progress
# a tiny server on the docker bridge gateway (port 8081) behind nginx: POST /tb/heartbeat, POST /tb/collected,
# PUT /tb/upload (the code tarball), GET /tb/progress (the run log's tail), GET /tb/results.tgz. nginx runs in a
# container and reaches the host as host.docker.internal (= the docker0 gateway), so the door cannot listen on
# 127.0.0.1 (the first cloud run got 502 there). It listens on the gateway only, never on the public address, and it
# checks the key itself as well as nginx does.
install -d -m 700 /var/lib/tb
umask 077; printf '%s' "$KEY" > /var/lib/tb/door-key; umask 022
DOOR_HOST=$(ip -4 -o addr show docker0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
DOOR_HOST=${DOOR_HOST:-172.17.0.1}
cat >/usr/local/sbin/tb-door.py <<'PY'
import hmac, http.server, os, pathlib, subprocess, sys
TB = pathlib.Path("/var/lib/tb")
KEY = (TB / "door-key").read_text().strip()
class H(http.server.BaseHTTPRequestHandler):
    def parse_request(self):
        if not super().parse_request(): return False
        if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {KEY}"):
            self.send_error(401); return False
        return True
    def _ok(self, body=b"ok\n", ctype="text/plain"):
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path == "/heartbeat": (TB / "heartbeat").touch(); return self._ok()
        if self.path == "/collected": (TB / "collected").touch(); return self._ok()
        self.send_error(404)
    def do_PUT(self):
        if self.path != "/upload": return self.send_error(404)
        n = int(self.headers.get("Content-Length", "0"))
        tmp = TB / "incoming" / "src.tgz.part"
        with open(tmp, "wb") as fh:
            while n > 0:
                b = self.rfile.read(min(n, 1 << 20)); fh.write(b); n -= len(b)
        tmp.replace(TB / "incoming" / "src.tgz"); return self._ok()
    def do_GET(self):
        if self.path == "/progress":
            phase = (TB / "phase").read_text() if (TB / "phase").exists() else "?"
            tail = subprocess.run(["tail", "-n", "15", "/var/log/tb-complete-run.log"], capture_output=True).stdout
            return self._ok(f"phase {phase}".encode() + b"\n" + tail + (b"DONE\n" if (TB / "DONE").exists() else b""))
        if self.path == "/results.tgz" and (TB / "out" / "results.tgz").exists():
            return self._ok((TB / "out" / "results.tgz").read_bytes(), "application/gzip")
        self.send_error(404)
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer((sys.argv[1], 8081), H).serve_forever()
PY
systemd-run --unit tb-door --description "TrialBox driver door" python3 /usr/local/sbin/tb-door.py "$DOOR_HOST"

# ------------------------------------------------------------------ serving: judge and verifier resident (D-124)
VLLM=vllm/vllm-openai:v0.32.0
J=nvidia/Gemma-4-26B-A4B-NVFP4
V=cyankiwi/Qwen3.5-9B-AWQ-4bit
REC=/root/record
mkdir -p $REC /models
chmod 755 $REC
docker rm -f judge verifier front 2>/dev/null
docker network create tb 2>/dev/null
# :80 for the driver (the key is checked here for /tb/; vLLM checks it for /judge/ and /verifier/); 127.0.0.1:8080
# for the run on this VM: the gateway reaches the two servers there, and nginx adds the key (the routing file is
# the installed box's, unchanged)
umask 077
cat > /root/nginx.conf <<NG
events {}
http { resolver 127.0.0.11 valid=5s ipv6=off; client_max_body_size 200m; proxy_read_timeout 900s;
  server { listen 80;
    location /judge/    { set \$up judge;    rewrite ^/judge/(.*)\$ /\$1 break;    proxy_pass http://\$up:8000; }
    location /verifier/ { set \$up verifier; rewrite ^/verifier/(.*)\$ /\$1 break; proxy_pass http://\$up:8000; }
    location /record/   { alias /srv/record/; default_type application/json; }
    location /tb/ { if (\$http_authorization != "Bearer ${KEY}") { return 401; }
                    rewrite ^/tb/(.*)\$ /\$1 break; proxy_set_header Authorization "Bearer ${KEY}"; proxy_pass http://host.docker.internal:8081; } }
  server { listen 8080;
    location /judge/    { set \$up judge;    rewrite ^/judge/(.*)\$ /\$1 break; proxy_set_header Authorization "Bearer ${KEY}"; proxy_pass http://\$up:8000; }
    location /verifier/ { set \$up verifier; rewrite ^/verifier/(.*)\$ /\$1 break; proxy_set_header Authorization "Bearer ${KEY}"; proxy_pass http://\$up:8000; } } }
NG
umask 022
docker run -d --name front --network tb -p 80:80 -p 127.0.0.1:8080:8080 --add-host host.docker.internal:host-gateway \
  -v /root/nginx.conf:/etc/nginx/nginx.conf:ro -v $REC:/srv/record:ro nginx:1.27-alpine >/dev/null
python3 - <<'PY' &
import json, subprocess, time
peak, out = 0, "/root/record/gpu_peak.json"  # the card's peak memory every 2 s, both models resident
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
    --restart unless-stopped $VLLM --model "$model" --served-model-name "$served" --max-model-len 32768 \
    --max-num-seqs 16 --enforce-eager --gpu-memory-utilization "$util" --api-key "$KEY" "$@" >/dev/null
}
healthy() { docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null; }
start judge $J local/gemma-4-26b-a4b-nvfp4 0.40 --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
for _ in $(seq 1 240); do healthy judge && break; touch "$HB"; sleep 5; done
start verifier $V local/qwen3.5-9b-awq 0.20 --limit-mm-per-prompt '{"image":0,"video":0}' \
  --default-chat-template-kwargs '{"enable_thinking": false}'
for _ in $(seq 1 240); do healthy verifier && break; touch "$HB"; sleep 5; done
SC=$(md tb-serving-config || true)
if [ -n "$SC" ]; then
  printf '%s\n' "$SC" > /root/serving_config.py
  python3 /root/serving_config.py capture --container judge=judge --container verifier=verifier --models-dir /models \
    --notes "rtxpro6000 profile (D-124): complete run ${RUN_ID}" --out $REC/serving_config.json || true
  chmod 644 $REC/serving_config.json 2>/dev/null || true
fi
echo PRO6000-RUN-READY

# ------------------------------------------------------------------ the code and the tools
SRC=$TB/src
if [ -n "$BUCKET" ]; then
  gcloud storage cp "$BUCKET/runs/$RUN_ID/src.tgz" "$TB/incoming/src.tgz" || true
  gcloud storage rsync -r "$BUCKET/runs/$RUN_ID/parts" "$RUN/parts" 2>/dev/null || true   # resume
fi
echo "TB-WAITING-FOR-CODE"
for _ in $(seq 1 120); do [ -f "$TB/incoming/src.tgz" ] && break; sleep 15; done
[ -f "$TB/incoming/src.tgz" ] || { echo "TB-NO-CODE: nothing uploaded in 30 minutes"; touch "$DONE"; exit 1; }
rm -rf "$SRC" && mkdir -p "$SRC" && tar -xzf "$TB/incoming/src.tgz" -C "$SRC"
cd "$SRC/trialbox" || { touch "$DONE"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
LOG=/var/log/tb-complete-run.log
setup_failed() {  # the setup log comes back with the results, so a failed setup is never silent (first cloud run)
  echo "TB-SETUP-FAILED: $1" | tee -a "$LOG"; echo setup-failed > "$PHASE"
  tar -czf "$TB/out/results.tgz" -C /var/log tb-complete-run.log 2>/dev/null
  touch "$DONE"; exit 1
}
echo "== setup $(date -u +%FT%TZ)" >>"$LOG"
apt-get update -qq >>"$LOG" 2>&1
apt-get install -y -qq postgresql tesseract-ocr tesseract-ocr-jpn tesseract-ocr-chi-tra tesseract-ocr-eng \
  python3-venv python3-pip curl xz-utils maven >>"$LOG" 2>&1 || setup_failed "apt-get install"
touch "$HB"
# Ubuntu 24.04 refuses a system-wide pip install (PEP 668), so uv comes from a venv of its own, else its installer
if ! command -v uv >/dev/null; then
  { python3 -m venv /opt/uv && /opt/uv/bin/pip install -q uv && ln -sf /opt/uv/bin/uv /usr/local/bin/uv; } >>"$LOG" 2>&1 \
    || { curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh; } >>"$LOG" 2>&1
fi
command -v uv >/dev/null || setup_failed "uv"
{ uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"; } >>"$LOG" 2>&1 \
  || setup_failed "python environment"
[ -x .venv/bin/python ] || setup_failed "no .venv/bin/python"
# Ubuntu's own Node.js is too old for Playwright (the third cloud run stopped on it): the pinned LTS from nodejs.org
NODE_V=v22.23.4
{ curl -fsSL "https://nodejs.org/dist/$NODE_V/node-$NODE_V-linux-x64.tar.xz" | tar -xJ -C /opt \
  && ln -sf /opt/node-$NODE_V-linux-x64/bin/node /opt/node-$NODE_V-linux-x64/bin/npm /opt/node-$NODE_V-linux-x64/bin/npx /usr/local/bin/; } \
  >>"$LOG" 2>&1 || setup_failed "node $NODE_V"
mkdir -p /opt/node-tools && (cd /opt/node-tools && npm i -s playwright@1.63.0 axe-core && npx playwright install --with-deps chromium) \
  >>"$LOG" 2>&1 || setup_failed "playwright"
.venv/bin/python tools/fetch_fonts.py >>"$LOG" 2>&1 || true
# the in-process box reads FHIRHelpers from the cql-translator jars (.cache/jvm, maven): without them every protocol
# paste fails in compiling (the first cloud run's hospital parts: "FHIRHelpers-4.0.1.cql not found")
PY=.venv/bin/python bash tools/fetch_jvm_deps.sh >>"$LOG" 2>&1 || setup_failed "JVM dependencies (tools/fetch_jvm_deps.sh)"
echo "== setup done $(date -u +%FT%TZ)" >>"$LOG"
touch "$HB"

# the embedding bench (tools/bench_embed.py) runs in the vLLM image: its torch and transformers already run on this card
cat >/usr/local/sbin/tb-embed-py <<EOS
#!/bin/sh
exec docker run --rm --gpus all --ipc host -v /models:/root/.cache/huggingface -v $TB:$TB -w "\$PWD" \
  --entrypoint python3 $VLLM "\$@"
EOS
chmod 0755 /usr/local/sbin/tb-embed-py

# ------------------------------------------------------------------ the run: model parts here, resumable
echo run > "$PHASE"
( while [ ! -f "$TB/run-ended" ]; do  # progress keeps the VM alive: the log grew in the last minute
    s1=$(stat -c %s $LOG 2>/dev/null || echo 0); sleep 60; s2=$(stat -c %s $LOG 2>/dev/null || echo 0)
    [ "$s2" != "$s1" ] && touch "$HB"
    [ -n "$BUCKET" ] && gcloud storage rsync -r "$RUN/parts" "$BUCKET/runs/$RUN_ID/parts" >/dev/null 2>&1
  done ) &
# shellcheck disable=SC2086  # ONLY is a list of tags
NODE_PATH=/opt/node-tools/node_modules TB_GPU_KEY="$KEY" TB_ENV=DEV PYTHONPATH=libs:services:. \
  TB_BENCH_EMBED_CMD=/usr/local/sbin/tb-embed-py \
  .venv/bin/python -m tools.complete_run --dir "$RUN" --model pair --patients "$PATIENTS" --ocr tesseract \
  --judge-url http://127.0.0.1:8080/judge/v1 --verifier-url http://127.0.0.1:8080/verifier/v1 \
  --live-record $REC/serving_config.json --skip walk backup update scale --resume --heartbeat "$HB" \
  ${ONLY:+--only $ONLY} >>"$LOG" 2>&1
echo "TB-RUN-EXIT $?"
touch "$TB/run-ended"
cp $REC/gpu_peak.json "$RUN/" 2>/dev/null || curl -fsS -o "$RUN/gpu_peak.json" http://127.0.0.1/record/gpu_peak.json || true
cp $REC/serving_config.json "$RUN/serving_config.rtxpro6000.live.json" 2>/dev/null || true
cp "$LOG" "$RUN/vm.log" 2>/dev/null || true
tar -czf "$TB/out/results.tgz" -C "$RUN" vm.log parts report gpu_peak.json serving_config.rtxpro6000.live.json \
  bench-embed/result.json bench-embed/set.json bench-profile/result.json 2>/dev/null
[ -n "$BUCKET" ] && gcloud storage cp "$TB/out/results.tgz" "$BUCKET/runs/$RUN_ID/results.tgz"
printf "done\n" > "$PHASE"
touch "$DONE"
echo COMPLETE-RUN-DONE
