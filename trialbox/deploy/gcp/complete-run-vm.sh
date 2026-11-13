#!/bin/bash
# TrialBox complete run ON the RTX PRO 6000 VM (TB-PLAN-04 step 9, D-141, D-150). The VM's startup script for the run
# (the usual one is gpu-sim-startup.sh). deploy/gcp/complete-run.sh puts it there with this metadata:
#
#   tb-door-secret, tb-door-version  the Secret Manager secret and version (T-119, CR-048) that hold the door: the
#                     random API key of the two model servers and the door, and the TLS key of nginx :443 (made by
#                     the driver, read here with the VM's own service account, never in the metadata, never printed)
#   tb-door-cert      the door's self-signed certificate (public; the driver pins its key). No port 80.
#   tb-run-id         the run's id: the run directory is /var/lib/tb/runs/<id> (a new id never sees an older run's
#                     parts, D-150 / review H-01); tb-patients the bulk size; tb-bucket an optional gs:// bucket
#   tb-only           the parts of this VM (complete_run --only tags; a shard of a parallel run, D-148); empty: all
#   tb-llm-concurrency  the model calls in flight (TB_SCREEN_LLM_CONCURRENCY): one value for every part, or several
#                     ("1 4 16 48": the hospital part once per value, review test G-3); empty: the record's max_num_seqs
#   tb-src-sha256     the sha256 of the code the driver uploads: anything else is refused before it is unpacked
#   tb-max-minutes    hard cap of this boot (the driver sets the cloud cap too: max-run-duration, action STOP)
#   tb-idle-minutes   the watchdog's idle limit in the run phase (default 20); tb-done-grace (default 30);
#                     tb-fail-grace (default 5): the grace after a failure marker (finish), when nothing ran worth a wait
#   tb-code-wait-minutes how long to wait for the upload (default 30)
#   tb-collect-only   1: a results-only boot of a stopped VM (no models, no run): serve the last results.tgz to the
#                     driver and power off once it has them (complete-run.sh --collect, review H-04)
#   tb-serving-config tools/serving_config.py (the serving record, D-111)
#   tb-min-free-gb    the pre-flight's free-disk floor (default 50); tb-selftest-seconds (the rehearsal's silent parts)
#
# The VM stops itself, whatever happens to the driver:
#   1. a hard cap (systemd timer, tb-max-minutes after boot) and the cloud's max-run-duration (set by the driver);
#   2. a watchdog, per phase: serving the sum of its own waits (SERVING_LIMIT_S below, derived), waiting for the code
#      35 min, setup 45 min; in the run, no heartbeat for tb-idle-minutes (only the run touches it, while a part works:
#      its processes' CPU, a part's container's CPU or the card busy; D-150 / review H-03). The driver's poll touches
#      driver-alive, never the heartbeat: a driver that follows a stuck part must not keep it alive to the cap. The
#      done marker older than tb-done-grace (tb-fail-grace after a failure marker; at once once the driver says it
#      collected the results);
#   3. every failure ends with the done marker and a results.tgz that says why (TB-PREFLIGHT-FAILED,
#      TB-SERVING-FAILED, TB-NO-CODE, TB-UPLOAD-REJECTED, TB-SETUP-FAILED), so a failed boot costs minutes, not hours
#      (TB-NO-CODE powers off at once, without the grace: no code, nothing for a driver to wait for; A6).
# The workload runs here, not on the driver: the code comes from the bucket or an HTTP upload by the driver, the model
# parts run with --resume inside this run's own directory (a restart of the same run id continues where it stopped),
# results.tgz is re-packed after every part, and waits in the bucket or at https://<vm>/tb/results.tgz (key needed).
# Nothing ever prints the key: no `set -x` (A-12). tests/rehearsal runs this script unchanged before any paid launch.
TB=/var/lib/tb
CON=/var/log/tb-complete.log      # this boot's console
LOG=/var/log/tb-complete-run.log  # the run's log: /tb/progress tails it, it comes back as vm.log
mkdir -p "$TB/incoming" "$TB/out" "$TB/runs" "$TB/cache"
[ -f "$CON" ] && mv -f "$CON" "$CON.prev"   # a fresh console per boot (review M-01); the last one kept once
exec > >(tee -a "$CON" /dev/ttyS0) 2>&1
set -u
export PATH="$PATH:/snap/bin"   # gcloud on the GCE images (Secret Manager, the bucket)
md() { curl -sf -H Metadata-Flavor:Google "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
HB="$TB/heartbeat"
DONE="$TB/DONE"
PHASE="$TB/phase"
phase() { printf '%s\n' "$1" > "$PHASE"; echo "TB-PHASE $1 $(date -u +%FT%TZ)"; }
COLLECT_ONLY=$(md tb-collect-only || true)
phase "$([ "$COLLECT_ONLY" = 1 ] && echo collect || echo serving)"
touch "$HB"
rm -f "$DONE" "$TB/collected" "$TB/run-ended" "$TB/grace"

# ------------------------------------------------------------------ 1-2. the VM stops itself (first, before anything)
# The waits of the serving phase (OD-10: each a setting with its reason; the phase's watchdog limit is their sum, so
# the watchdog never cuts a boot that is still inside one of its own waits):
DOCKER_WAIT_S=120      # docker may start after this script (M-05): 60 tries of 2 s
DOOR_WAIT_S=210        # nginx's door through TLS: 30 tries of up to 5 s + 2 s
HEALTH_WAIT_S=1200     # each model server healthy: 240 tries of 5 s (the bound the script already had)
CHECK_WAIT_S=360       # per server: /v1/models 30 s, one chat call 300 s, the no-key refusal 30 s
CAPTURE_WAIT_S=300     # the serving record (docker inspect, the weight files' sha256): unmeasured, a setting set high
SERVING_LIMIT_S=$((DOCKER_WAIT_S + DOOR_WAIT_S + 2 * HEALTH_WAIT_S + 2 * CHECK_WAIT_S + CAPTURE_WAIT_S))
MAXM=$(md tb-max-minutes || echo 300)
IDLEM=$(md tb-idle-minutes || echo 20)
GRACE=$(md tb-done-grace || echo 30)
FAILGRACE=$(md tb-fail-grace || echo 5)   # a failure marker: no run, a driver polling every minute collects in 1-2
systemd-run --unit tb-hard-cap --on-active="${MAXM}min" --description "TrialBox hard cap" \
  /bin/sh -c 'echo "TB-WATCHDOG hard cap reached, powering off" >/dev/ttyS0; systemctl poweroff'
cat >/usr/local/sbin/tb-watchdog <<'EOS'
#!/bin/sh
# poweroff, checked every minute: the done marker older than $2 minutes ($tb/grace instead after a failure marker; at
# once when collected); in the run phase no heartbeat for $1 minutes (the driver's poll touches driver-alive, which
# never counts in the run); serving longer than $3 seconds; any other phase longer than its limit (the phase's age).
idle=$1; grace=$2; serving=$3; tb=/var/lib/tb
off() {  # say why, in the run log too, and pack what there is: a stopped VM always has a results.tgz to collect
  echo "TB-WATCHDOG $1: powering off" >/dev/ttyS0
  if [ -f $tb/current-run ] && [ ! -f $tb/DONE ]; then
    echo "TB-WATCHDOG $1: powering off" >> /var/log/tb-complete-run.log
    timeout 120 /usr/local/sbin/tb-pack "$(cat $tb/current-run)" "$(cat $tb/current-bucket 2>/dev/null)"
  fi
  systemctl poweroff; exit 0
}
while :; do
  sleep 60
  now=$(date +%s); phase=$(cat $tb/phase 2>/dev/null || echo serving)
  since=$((now - $(stat -c %Y $tb/phase 2>/dev/null || echo "$now")))
  hb=$(stat -c %Y $tb/heartbeat 2>/dev/null || echo 0)
  if [ -f $tb/DONE ]; then
    d=$(stat -c %Y $tb/DONE); g=$grace
    [ -s $tb/grace ] && g=$(cat $tb/grace)
    [ -f $tb/collected ] && off "done, results collected"
    [ $((now - d)) -ge $((g * 60)) ] && off "done, grace of $g minutes over"
  else
    case "$phase" in
      run) [ $((now - hb)) -ge $((idle * 60)) ] && off "no heartbeat for $idle minutes in the run (a stuck part)" ;;
      serving) [ "$since" -ge "$serving" ] && off "phase serving over $((serving / 60)) minutes (the sum of its waits)" ;;
      setup) [ "$since" -ge 2700 ] && off "phase $phase over 45 minutes" ;;
      code) [ "$since" -ge 2100 ] && off "phase code over 35 minutes" ;;
      *) [ "$since" -ge 3600 ] && off "phase $phase over 60 minutes" ;;
    esac
  fi
done
EOS
chmod 0755 /usr/local/sbin/tb-watchdog
systemd-run --unit tb-watchdog --description "TrialBox watchdog" /usr/local/sbin/tb-watchdog "$IDLEM" "$GRACE" "$SERVING_LIMIT_S"

# the door from Secret Manager (T-119): the key and the TLS key into root-only files, the certificate from metadata
TLS=/root/tls
install -d -m 700 "$TLS" "$TB"
DSEC=$(md tb-door-secret || true); DVER=$(md tb-door-version || true)
rm -f "$TB/door-key" "$TLS/door.key"
if [ -n "$DSEC" ] && [ -n "$DVER" ]; then
  (umask 077; gcloud secrets versions access "$DVER" --secret="$DSEC" 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
open(sys.argv[1], "w").write(d["key"].strip()); open(sys.argv[2], "w").write(d["tls_key"])' "$TB/door-key" "$TLS/door.key")
  (umask 022; md tb-door-cert > "$TLS/door.crt") || rm -f "$TLS/door.crt"
fi
KEY=$(cat "$TB/door-key" 2>/dev/null || true)
[ -n "$KEY" ] && [ -s "$TLS/door.key" ] && [ -s "$TLS/door.crt" ] \
  || { echo "TB-NO-KEY: no door from Secret Manager (tb-door-secret, tb-door-version, tb-door-cert); powering off"
       systemctl poweroff; exit 1; }
DOOR_TLS=(--noproxy "*" --cacert "$TLS/door.crt" --resolve tb-door:443:127.0.0.1)   # its own door, as the driver checks it
RUN_ID=$(md tb-run-id || echo run)
RUN_ID=$(printf '%s' "$RUN_ID" | tr -c 'A-Za-z0-9._-' '_')
RUN="$TB/runs/$RUN_ID"
PATIENTS=$(md tb-patients || echo 50000)
ONLY=$(md tb-only || true)
LLMC=$(md tb-llm-concurrency || true)
BUCKET=$(md tb-bucket || true)
SRC_SHA=$(md tb-src-sha256 || true)
REC=/root/record
VLLM=vllm/vllm-openai:v0.32.0
NGINX=nginx:1.27-alpine
mkdir -p $REC /models
chmod 755 $REC
umask 077; printf 'Authorization: Bearer %s\n' "$KEY" > "$TB/door-hdr"; umask 022

# results.tgz of the run so far: written to a temporary name and renamed, so the door never serves half an archive
cat >/usr/local/sbin/tb-pack <<'EOS'
#!/bin/sh
# tb-pack <run dir> [bucket]: the run log, parts/, the report, the records, the serving logs -> out/results.tgz
run=$1; bucket=${2:-}; out=/var/lib/tb/out/results.tgz
mkdir -p "$run"
cp /var/log/tb-complete-run.log "$run/vm.log" 2>/dev/null
cp /root/record/gpu_peak.json "$run/" 2>/dev/null
cp /root/record/serving_config.json "$run/serving_config.rtxpro6000.live.json" 2>/dev/null
cd "$run" || exit 1
set --
for m in vm.log parts report gpu_peak.json serving_config.rtxpro6000.live.json serving-logs bench-embed/result.json \
  bench-embed/set.json bench-profile/result.json gw-audit-* chat-template; do [ -e "$m" ] && set -- "$@" "$m"; done
# gw-audit-<part>: the gateway's audit of each model part (every call, every refusal: the report's per-call figures
# and refusal counts are recomputed from it); chat-template: G-1's template texts and the tokenizer side's output
tar -czf "$out.tmp" "$@" && mv -f "$out.tmp" "$out"
if [ -n "$bucket" ]; then  # 3 tries (30 s, 60 s apart): a failed upload leaves the marker; the disk keeps the archive
  dst="$bucket/runs/$(basename "$run")/results.tgz"
  for wait in 30 60 0; do
    if gcloud storage cp "$out" "$dst" >/dev/null 2>&1; then rm -f /var/lib/tb/out/upload-failed; exit 0; fi
    [ "$wait" = 0 ] || sleep "$wait"
  done
  echo "$dst" > /var/lib/tb/out/upload-failed
  echo "TB-UPLOAD-FAILED: results.tgz to $dst (3 tries); it stays on this disk: a results-only collect fetches it" \
    | tee -a /var/log/tb-complete-run.log >/dev/ttyS0
fi
EOS
chmod 0755 /usr/local/sbin/tb-pack
finish() {  # $1 marker line, $2 phase: say why (run log, console), pack what there is, DONE; the watchdog does the rest
  # after a failure the grace is tb-fail-grace (5 min), not tb-done-grace: nothing ran, a driver collects at its next poll
  echo "$1" | tee -a "$LOG"; phase "$2"
  /usr/local/sbin/tb-pack "$RUN" "$BUCKET"
  [ "$FAILGRACE" -lt "$GRACE" ] && echo "$FAILGRACE" > "$TB/grace"
  touch "$DONE"; echo COMPLETE-RUN-DONE; exit 1
}

if [ "$COLLECT_ONLY" != 1 ]; then
  # a new run never sees another run's state (review H-01, M-01): its own directory, a fresh log, no old archive
  for d in "$TB"/runs/*; do [ "$d" != "$RUN" ] && [ -d "$d" ] && rm -rf "$d"; done
  rm -rf "$TB/run" "$TB/out/results.tgz" "$TB/out/results.tgz.tmp" "$TB"/incoming/src.tgz*
  [ -f "$LOG" ] && mv -f "$LOG" "$LOG.prev"
  : > "$LOG"
  mkdir -p "$RUN"
  echo "== boot $(date -u +%FT%TZ) run $RUN_ID" >> "$LOG"
  printf '%s' "$RUN" > "$TB/current-run"; printf '%s' "$BUCKET" > "$TB/current-bucket"   # for the watchdog's pack
  /usr/local/sbin/tb-pack "$RUN" ""   # a results.tgz from the first minute on (the log so far)
fi

# ------------------------------------------------------------------ the driver's door: heartbeat, upload, progress
# a tiny server on the docker bridge gateway (port 8081) behind nginx: POST /tb/heartbeat, POST /tb/collected,
# PUT /tb/upload (the code tarball), GET /tb/progress (the run log's tail), GET /tb/results.tgz, on 443 only (TLS,
# the driver's pinned certificate; T-119: no port 80, the key never crosses plain HTTP). nginx runs in a
# container and reaches the host as host.docker.internal (= the docker0 gateway), so the door cannot listen on
# 127.0.0.1 (the first cloud run got 502 there). It listens on the gateway only, never on the public address, and it
# checks the key itself as well as nginx does.
for _ in $(seq 1 $((DOCKER_WAIT_S / 2))); do docker info >/dev/null 2>&1 && break; sleep 2; done   # docker may start after us (M-05)
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
        # the driver's poll: driver-alive, never the run's heartbeat (a driver following a stuck part must not keep it
        # alive to the cap; the watchdog's idle limit in the run is the part's own work only)
        if self.path == "/heartbeat": (TB / "driver-alive").touch(); return self._ok()
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
systemd-run --unit tb-door --property=Restart=on-failure --description "TrialBox driver door" \
  python3 /usr/local/sbin/tb-door.py "$DOOR_HOST"

J=nvidia/Gemma-4-26B-A4B-NVFP4
V=cyankiwi/Qwen3.5-9B-AWQ-4bit
JS=local/gemma-4-26b-a4b-nvfp4   # the served names: tools/pin_model.py JUDGE_SERVED, VERIFIER_SERVED (D-124)
VS=local/qwen3.5-9b-awq
docker rm -f judge verifier front 2>/dev/null
docker network create tb 2>/dev/null
# :443 (TLS) for the driver (the key is checked here for /tb/; vLLM checks it for /judge/ and /verifier/); 127.0.0.1:8080
# for the run on this VM: the gateway reaches the two servers there, and nginx adds the key (the routing file is
# the installed box's, unchanged)
umask 077
cat > /root/nginx.conf <<NG
events {}
http { resolver 127.0.0.11 valid=5s ipv6=off; client_max_body_size 200m; proxy_read_timeout 900s;
  server { listen 443 ssl; ssl_certificate $TLS/door.crt; ssl_certificate_key $TLS/door.key; ssl_protocols TLSv1.2 TLSv1.3;
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
docker run -d --name front --network tb -p 443:443 -p 127.0.0.1:8080:8080 --add-host host.docker.internal:host-gateway \
  -v /root/nginx.conf:/etc/nginx/nginx.conf:ro -v $REC:/srv/record:ro -v "$TLS:$TLS:ro" "$NGINX" >/dev/null \
  || { echo "TB-FRONT-FAILED: the nginx container did not start; the driver cannot reach this VM: powering off"; systemctl poweroff; exit 1; }
# the door through nginx with the key, as the driver will use it (M-05): unreachable means a paid VM nobody can drive
for _ in $(seq 1 30); do curl -fsS -o /dev/null --max-time 5 "${DOOR_TLS[@]}" -H @"$TB/door-hdr" https://tb-door/tb/progress && break; sleep 2; done
curl -fsS -o /dev/null --max-time 5 "${DOOR_TLS[@]}" -H @"$TB/door-hdr" https://tb-door/tb/progress \
  || { echo "TB-DOOR-FAILED: /tb/progress does not answer through nginx (TLS): powering off"; systemctl poweroff; exit 1; }
echo "TB-DOOR-UP on $DOOR_HOST:8081 behind nginx :443 (TLS, no port 80)"

# the images on this disk, every boot (the driver's --preflight reads the last boot's line from the serial console):
# a missing one would be pulled inside the serving limit, or not at all without a network
imgs=""; for im in "$VLLM" "$NGINX"; do
  if docker image inspect "$im" >/dev/null 2>&1; then imgs="$imgs $im=present"; else imgs="$imgs $im=missing"; fi
done
echo "TB-IMAGES$imgs"

if [ "$COLLECT_ONLY" = 1 ]; then  # a stopped VM started to hand over its results (review H-04): no models, no run
  if [ -f "$TB/out/results.tgz" ]; then echo "TB-COLLECT-ONLY: results.tgz ($(stat -c %s "$TB/out/results.tgz") bytes) at /tb/results.tgz"
    if [ -n "$BUCKET" ]; then  # the run's upload may have failed (TB-UPLOAD-FAILED): once more, to the bucket too
      gcloud storage cp "$TB/out/results.tgz" "$BUCKET/runs/$RUN_ID/results.tgz" >/dev/null 2>&1 \
        && echo "TB-COLLECT-ONLY: results.tgz uploaded to $BUCKET/runs/$RUN_ID/" \
        || echo "TB-COLLECT-ONLY: the upload to $BUCKET failed again; the driver fetches it through the door"
    fi
  else echo "TB-COLLECT-ONLY: no results.tgz on this disk"; fi
  touch "$DONE"; echo COMPLETE-RUN-DONE; exit 0   # the watchdog powers off once collected, or after the grace
fi

# ------------------------------------------------------------------ pre-flight: what this script needs and installs not
# (review M-08: a re-created VM or a new disk lacks them, and the run would die later and silently)
MINFREE=$(md tb-min-free-gb || echo 50)
pf=""
for c in docker nvidia-smi python3 curl tar ip; do command -v "$c" >/dev/null || pf="$pf; no $c"; done
docker info 2>/dev/null | grep -qi nvidia || pf="$pf; docker has no NVIDIA runtime (gpu-sim-startup.sh installs it)"
for w in models--nvidia--Gemma-4-26B-A4B-NVFP4 models--cyankiwi--Qwen3.5-9B-AWQ-4bit; do
  [ -d "/models/hub/$w" ] || pf="$pf; no weights /models/hub/$w (a download would not fit the serving limit)"
done
free=$(df -BG --output=avail "$TB" | tail -n 1 | tr -dc 0-9)
[ "${free:-0}" -ge "$MINFREE" ] || pf="$pf; ${free:-0} GB free on $TB, at least $MINFREE needed"
[ -z "$pf" ] || finish "TB-PREFLIGHT-FAILED${pf}" preflight-failed
echo "TB-PREFLIGHT ok (${free} GB free)"

# ------------------------------------------------------------------ serving: judge and verifier resident (D-124)
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
  # HF_HUB_OFFLINE: the weights are on this disk (the pre-flight checked); a server must never reach for the Hub
  docker run -d --name "$name" --network tb --gpus all --ipc host -v /models:/root/.cache/huggingface \
    -e HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
    --restart unless-stopped $VLLM --model "$model" --served-model-name "$served" --max-model-len 32768 \
    --max-num-seqs 16 --enforce-eager --gpu-memory-utilization "$util" --api-key "$KEY" "$@" >/dev/null
}
healthy() { docker exec "$1" python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null; }
exited() { docker ps -a --filter "name=^$1\$" --format '{{.Status}}' 2>/dev/null | grep -q Exited; }
serving_failed() {  # the servers' own logs come back with the results (review H-02)
  mkdir -p "$RUN/serving-logs"
  for n in judge verifier; do docker logs --tail 300 "$n" > "$RUN/serving-logs/$n.log" 2>&1; done
  finish "TB-SERVING-FAILED: $1" serving-failed
}
start judge $J $JS 0.40 --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}' || serving_failed "docker run judge"
for _ in $(seq 1 $((HEALTH_WAIT_S / 5))); do healthy judge && break; exited judge && break; touch "$HB"; sleep 5; done
healthy judge || serving_failed "judge not healthy (20 minutes, or its container exited)"
start verifier $V $VS 0.20 --limit-mm-per-prompt '{"image":0,"video":0}' \
  --default-chat-template-kwargs '{"enable_thinking": false}' || serving_failed "docker run verifier"
for _ in $(seq 1 $((HEALTH_WAIT_S / 5))); do healthy verifier && break; exited verifier && break; touch "$HB"; sleep 5; done
healthy verifier || serving_failed "verifier not healthy (20 minutes, or its container exited)"
# the run's own path (127.0.0.1:8080, nginx adds the key): each server lists exactly its served name, answers one chat
# call, and refuses a call without the key. A name drift (run 4's 404) stops the boot here, not after hours.
for pair in "judge $JS" "verifier $VS"; do
  set -- $pair
  ids=$(curl -fsS --max-time 30 "http://127.0.0.1:8080/$1/v1/models" \
    | python3 -c 'import json,sys; print(" ".join(m["id"] for m in json.load(sys.stdin)["data"]))' 2>/dev/null) \
    || serving_failed "$1: GET /v1/models through nginx failed"
  [ "$ids" = "$2" ] || serving_failed "$1 serves '$ids', the run asks for '$2'"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 300 -H 'Content-Type: application/json' \
    -d "{\"model\": \"$2\", \"messages\": [{\"role\": \"user\", \"content\": \"Answer OK.\"}], \"max_tokens\": 4}" \
    "http://127.0.0.1:8080/$1/v1/chat/completions")
  [ "$code" = 200 ] || serving_failed "$1: one chat call as '$2' answered HTTP $code"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "${DOOR_TLS[@]}" "https://tb-door/$1/v1/models")
  [ "$code" = 401 ] || serving_failed "$1: a call without the key answered HTTP $code, not 401"
  echo "TB-SERVING ok: $1 serves $2, one chat call answered, no key refused"
done
SC=$(md tb-serving-config || true)
if [ -n "$SC" ]; then
  printf '%s\n' "$SC" > /root/serving_config.py
  python3 /root/serving_config.py capture --container judge=judge --container verifier=verifier --models-dir /models \
    --notes "rtxpro6000 profile (D-124): complete run ${RUN_ID}" --out $REC/serving_config.json || true
  chmod 644 $REC/serving_config.json 2>/dev/null || true
fi
echo PRO6000-RUN-READY | tee -a "$LOG"

# ------------------------------------------------------------------ the code: checked, then unpacked without owners
phase code
SRC=$TB/src
if [ -n "$BUCKET" ]; then
  gcloud storage cp "$BUCKET/runs/$RUN_ID/src.tgz" "$TB/incoming/src.tgz" \
    || echo "TB-BUCKET: no $BUCKET/runs/$RUN_ID/src.tgz; waiting for an HTTP upload" | tee -a "$LOG"
fi
WAITM=$(md tb-code-wait-minutes || echo 30)
echo "TB-WAITING-FOR-CODE (${WAITM} minutes)" | tee -a "$LOG"
for _ in $(seq 1 $((WAITM * 4))); do [ -f "$TB/incoming/src.tgz" ] && break; sleep 15; done
if [ ! -f "$TB/incoming/src.tgz" ]; then
  # A6 (2026-11-12: the driver could not reach the door, the VM idled out its grace too, about US$3.50): no code means
  # no run and no results worth a driver's wait; the log is packed (and in the bucket with TB_BUCKET), then power off
  # now, not after tb-done-grace. The wait itself is tb-code-wait-minutes (default 30; the driver uploads as soon as
  # the door answers, minutes after the boot, before this wait begins).
  echo "TB-NO-CODE: nothing uploaded in ${WAITM} minutes" | tee -a "$LOG"; phase no-code
  /usr/local/sbin/tb-pack "$RUN" "$BUCKET"
  touch "$DONE"
  echo "TB-NO-CODE: no code, so no run: powering off now (results.tgz holds this log)"
  systemctl poweroff; exit 1
fi
mv -f "$TB/incoming/src.tgz" "$TB/src.tgz"   # the next boot waits for its own upload, never this one
if [ -n "$SRC_SHA" ]; then
  got=$(sha256sum "$TB/src.tgz" | cut -d' ' -f1)
  [ "$got" = "$SRC_SHA" ] || finish "TB-UPLOAD-REJECTED: sha256 ${got:0:16}... is not the driver's ${SRC_SHA:0:16}..." upload-rejected
fi
rm -rf "$SRC" && mkdir -p "$SRC" && tar --no-same-owner --no-same-permissions -xzf "$TB/src.tgz" -C "$SRC" \
  || finish "TB-UPLOAD-REJECTED: the archive does not unpack" upload-rejected
cd "$SRC/trialbox" || finish "TB-UPLOAD-REJECTED: no trialbox/ in the archive" upload-rejected
echo "TB-CODE $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head"][:12])' "$SRC/TB_HEAD.json" 2>/dev/null || echo '(no TB_HEAD.json)')" | tee -a "$LOG"

# ------------------------------------------------------------------ setup
phase setup
export DEBIAN_FRONTEND=noninteractive
setup_failed() { finish "TB-SETUP-FAILED: $1" setup-failed; }
echo "== setup $(date -u +%FT%TZ)" >>"$LOG"
# DPkg::Lock::Timeout: the image's own unattended-upgrades may hold the lock at boot; wait for it (10 min) not fail
APT=(apt-get -o DPkg::Lock::Timeout=600)
# The same wait for every other apt on this VM: `playwright install --with-deps` calls apt-get itself, without the
# option above, and run 20261113T072836Z ended at TB-SETUP-FAILED: playwright on unattended-upgrades' lock.
echo 'DPkg::Lock::Timeout "600";' >/etc/apt/apt.conf.d/99tb-lock-timeout
"${APT[@]}" update -qq >>"$LOG" 2>&1
"${APT[@]}" install -y -qq postgresql tesseract-ocr tesseract-ocr-jpn tesseract-ocr-chi-tra tesseract-ocr-eng \
  python3-venv python3-pip curl xz-utils git >>"$LOG" 2>&1 || setup_failed "apt-get install"
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
if [ ! -x /opt/node-$NODE_V-linux-x64/bin/node ]; then
  { curl -fsSL "https://nodejs.org/dist/$NODE_V/node-$NODE_V-linux-x64.tar.xz" | tar -xJ -C /opt; } >>"$LOG" 2>&1 \
    || setup_failed "node $NODE_V"
fi
ln -sf /opt/node-$NODE_V-linux-x64/bin/node /opt/node-$NODE_V-linux-x64/bin/npm /opt/node-$NODE_V-linux-x64/bin/npx /usr/local/bin/
mkdir -p /opt/node-tools && (cd /opt/node-tools && npm i -s playwright@1.63.0 && npx playwright install --with-deps chromium) \
  >>"$LOG" 2>&1 || setup_failed "playwright"
# a half-installed Chromium would show only as every screenshot missing (review L-05): launch it once
(cd /opt/node-tools && node -e "require('playwright').chromium.launch().then(b => b.close())") >>"$LOG" 2>&1 \
  || setup_failed "Chromium does not launch"
.venv/bin/python tools/fetch_fonts.py >>"$LOG" 2>&1 || true
touch "$HB"
# the data git does not carry (review C-02, C-03): the CQL translator's quick jar (FHIRHelpers), MedTxt, TREC CT, only
# what this VM's parts need, kept on this disk between runs. A dataset that cannot be fetched is named here and in the
# results; the parts that need it fail at once with "data missing" and take no card time.
# shellcheck disable=SC2086  # ONLY is a list of tags
.venv/bin/python -m tools.fetch_run_data --cache "$TB/cache" ${ONLY:+--only $ONLY} >>"$LOG" 2>&1
grep -a '^TB-DATA' "$LOG" | tail -n 3
echo "== setup done $(date -u +%FT%TZ)" >>"$LOG"
touch "$HB"

# the embedding bench (tools/bench_embed.py) runs in the vLLM image: its torch and transformers already run on this card
cat >/usr/local/sbin/tb-embed-py <<EOS
#!/bin/sh
exec docker run --rm --label tb-part=1 --gpus all --ipc host -v /models:/root/.cache/huggingface -v $TB:$TB -w "\$PWD" \
  --entrypoint python3 $VLLM "\$@"
EOS
chmod 0755 /usr/local/sbin/tb-embed-py

# ------------------------------------------------------------------ the run: model parts here, resumable, packed per part
phase run
touch "$HB"
/usr/local/sbin/tb-pack "$RUN" "$BUCKET"   # the setup's log is in the results even if the first part never ends
SELFTEST_S=$(md tb-selftest-seconds || true)
[ -z "$SELFTEST_S" ] || export TB_SELFTEST_SECONDS="$SELFTEST_S"   # the rehearsal's silent parts only
# shellcheck disable=SC2086  # ONLY is a list of tags
NODE_PATH=/opt/node-tools/node_modules TB_GPU_KEY="$KEY" TB_ENV=DEV PYTHONPATH=libs:services:. \
  TB_BENCH_EMBED_CMD=/usr/local/sbin/tb-embed-py \
  .venv/bin/python -m tools.complete_run --dir "$RUN" --run-id "$RUN_ID" --model pair --patients "$PATIENTS" \
  --ocr tesseract --judge-url http://127.0.0.1:8080/judge/v1 --verifier-url http://127.0.0.1:8080/verifier/v1 \
  --live-record $REC/serving_config.json --skip walk backup update scale --resume --heartbeat "$HB" \
  --after-part "/usr/local/sbin/tb-pack $RUN $BUCKET" ${LLMC:+--llm-concurrency "$LLMC"} ${ONLY:+--only $ONLY} >>"$LOG" 2>&1
echo "TB-RUN-EXIT $?" | tee -a "$LOG"
touch "$TB/run-ended"
/usr/local/sbin/tb-pack "$RUN" "$BUCKET"
phase "done"
touch "$DONE"
echo COMPLETE-RUN-DONE