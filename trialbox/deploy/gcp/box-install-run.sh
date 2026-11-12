#!/bin/bash
# TrialBox product-on-GPU run ON the cloud GPU VM (plan v7 section 7.1, tests G-2, G-9, G-10; gap X-10 of the GCP test
# plan): install a box from the real offline bundle with the installer only, qualify and promote the model pair, then
# the restart and outage test and the canary on the new model-server image. It is the VM's startup script for this run
# (as complete-run-vm.sh is for the complete run), and it is fail-safe in the same three ways: a cost cap, a watchdog
# and a door for the driver. GCE runs a startup script at every boot, so a power cycle resumes here by itself.
#
# The steps, in order. Each is timed and written as a part result (parts/NN-<step>.json) and kept in state.json: a step
# that finished is never run again, in this boot or after a restart.
#   01-bundle            fetch the bundle, check the whole file's sha256, unpack it, check every file of its manifest
#   02-install           the installer, non-interactive, up to the first-run wizard
#   03-wizard            the first-run wizard, fed an answers file only
#   04-pin               pin the pair from the real model folders
#   05-qualify           the full qualification (its record comes back)
#   06/07-promote-<role> promote the judge build, then the verifier build, from that record
#   08-resolve           PRODUCTION resolves judge and verifier to the promoted builds
#   09-serving           the serving record, and the model servers' resident memory on the host (vLLM host RSS)
#   10-g9-screen         G-9: a screen with tb-llm-concurrency calls in flight, started as a job of the box
#   11..-g9-restart-<c>  G-9: `docker restart` of each container of tb-g9-containers, one at a time, with the calls in
#                        flight: seconds to healthy, the job's state, calls repeated
#   14-g9-power          G-9: a power cycle. This script cannot stop and start its own VM, so it asks: it writes the
#                        marker POWER-CYCLE-REQUEST (also a line of /tb/progress); the driver stops and starts the VM;
#                        the next boot finds the request in state.json, sees a new boot id and goes on from there
#   15-g9-result         G-9: the job's final state, calls repeated in all, whether CURRENT moved
#   16-g10-canary        G-10: the 54-case pair canary on the model-server image named by tb-g10-vllm-image
# A step cut by a restart of the VM is run again by the next boot (its part result counts the attempts and the boots).
# G-2's pass rule is "no step needed a shell beyond the installer". So nothing here repairs or works around a step: a
# step of the box that fails, or whose command is not there, is written down as a STOP (what was run, its exit code,
# the last lines of its log) and the run ends with that record. A test rule that is not met (a call paid twice, a job
# that did not resume) is not a stop: it is recorded as "pass": false and the run goes on, so one paid session measures
# all it can.
#
# Lane D's installer, wizard and qualification path are not final (they land 2026-12-04). Every call into them is one
# function below (d_install, d_wizard, d_pin, d_qualify, d_promote, d_resolve, d_capture, d_screen_start,
# d_screen_status, d_healthy, d_canary): when the real interface lands, only those bodies change.
#
# Metadata (set by the driver). "(setting)" marks a declared limit with its reason (OD-10: no other fixed limit here;
# everything else is bounded by the watchdog, which follows real progress):
#   tb-door-secret, tb-door-version  the Secret Manager secret and version of the door: {"key": ..., "tls_key": ...}
#   tb-door-cert        the door's self-signed certificate (public; the driver pins it)
#   tb-door-port        the door's port (setting, default 8443: 443 and 80 belong to the installed box)
#   tb-run-id           the run's id: the run directory is /var/lib/tb/boxruns/<id>
#   tb-bundle           the offline bundle: gs://... or a path on this disk; tb-bundle-sha256 its sha256 (required)
#   tb-box-root         where the box's host tree is (default /opt/trialbox); tb-installer (default
#                       <box root>/deploy/box-install.sh)
#   tb-answers-secret, tb-answers-version  the first-run wizard's answers file (synthetic site; it may hold the
#                       owner's passphrase, so it is a secret, never metadata, never printed)
#   tb-profile          the GPU profile (default rtxpro6000); tb-models-root the real model folders (default /models)
#   tb-judge-container, tb-verifier-container  the model servers' container names (defaults judge, verifier)
#   tb-g9-containers    the containers restarted in G-9 (default "orchestrator adapter judge")
#   tb-patients         the G-9 screen's size (default 50000, G-6's size); tb-llm-concurrency calls in flight (default
#                       16, G-9's definition)
#   tb-current-file     the CURRENT pointer G-9 watches (default <box root>/deploy/data/lake/CURRENT)
#   tb-g10-vllm-image   the model-server image G-10 is run on (required: no default, the move is a decision)
#   tb-bucket           an optional gs:// bucket for results.tgz and the power-cycle marker
#   tb-max-minutes      the cost cap (setting, default 240: twice the 2.0 hours the GCP test plan gives the box
#                       install, L6). It counts every boot of this run id: a power cycle does not start it again
#   tb-idle-minutes     the watchdog's idle limit (setting, default 20: the longest silence known is a model load, and
#                       complete-run-vm.sh allows it 20 minutes). A step's output or a job's progress is the heartbeat
#   tb-done-grace       minutes a finished VM waits for the driver (setting, default 30, as complete-run-vm.sh)
#   tb-healthy-minutes  how long the box may take to be healthy after a restart (setting, default 20: a model load)
#   tb-power-wait-minutes  how long to wait for the driver's stop (setting, default 15: the driver polls every minute
#                       and a GCE stop takes a few)
#
# The VM stops itself, whatever happens to the driver: the cap (a systemd timer for what is left of tb-max-minutes),
# the watchdog (no heartbeat for tb-idle-minutes; done and collected, or done for tb-done-grace), and every stop ends
# with the done marker and a results.tgz that says why. Nothing prints a key: no `set -x`.
# Knobs for the rehearsal only (tests/rehearsal/box-run; never set on the VM): TB_BOXRUN_ROOT, TB_BOXRUN_LOGDIR,
# TB_BOXRUN_SBIN, TB_BOXRUN_TLS, TB_BOXRUN_SERIAL, TB_BOXRUN_BOOT_ID, TB_BOXRUN_PY, TB_BOXRUN_MINUTE_S (how many
# seconds a minute of the limits lasts), TB_BOXRUN_POLL_S (the polling period, default 5 seconds), TB_BOXRUN_DOOR_HOST.
TB=${TB_BOXRUN_ROOT:-/var/lib/tb}
LOGDIR=${TB_BOXRUN_LOGDIR:-/var/log}
SBIN=${TB_BOXRUN_SBIN:-/usr/local/sbin}
TLS=${TB_BOXRUN_TLS:-/root/tls}
SERIAL=${TB_BOXRUN_SERIAL:-/dev/ttyS0}
MIN_S=${TB_BOXRUN_MINUTE_S:-60}
POLL=${TB_BOXRUN_POLL_S:-5}
PY=${TB_BOXRUN_PY:-python3}
CON=$LOGDIR/tb-boxrun.log          # this boot's console
LOG=$LOGDIR/tb-boxrun-run.log      # the run's log, every boot appended: /tb/progress tails it, it comes back as vm.log
mkdir -p "$TB/out" "$TB/boxruns" "$LOGDIR" "$SBIN"
[ -f "$CON" ] && mv -f "$CON" "$CON.prev"
exec > >(tee -a "$CON" "$SERIAL") 2>&1
set -u
export PATH="$PATH:/snap/bin"
md() { curl -sf -H Metadata-Flavor:Google "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
HB="$TB/heartbeat"
DONE="$TB/DONE"
PHASE="$TB/phase"
phase() { printf '%s\n' "$1" > "$PHASE"; echo "TB-PHASE $1 $(date -u +%FT%TZ)"; }
BOOT_T0=$(date +%s)
BOOT_ID=${TB_BOXRUN_BOOT_ID:-$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo "boot-$BOOT_T0")}
phase boot
touch "$HB"
rm -f "$DONE" "$TB/collected"

RUN_ID=$(md tb-run-id || echo boxrun)
RUN_ID=$(printf '%s' "$RUN_ID" | tr -c 'A-Za-z0-9._-' '_')
RUN="$TB/boxruns/$RUN_ID"
BUCKET=$(md tb-bucket || true)
mkdir -p "$RUN/parts" "$RUN/logs" "$RUN/records"
printf '%s' "$RUN" > "$TB/current-run"; printf '%s' "$BUCKET" > "$TB/current-bucket"
echo "== boot $(date -u +%FT%TZ) run $RUN_ID boot ${BOOT_ID:0:8}" >> "$LOG"

# results.tgz of the run so far: written to a temporary name and renamed, so the door never serves half an archive
cat > "$SBIN/tb-boxrun-pack" <<EOS
#!/bin/sh
# tb-boxrun-pack <run dir> [bucket]: the run log, state.json, parts/, records/, the steps' logs -> out/results.tgz
run=\$1; bucket=\${2:-}; out=$TB/out/results.tgz
cp "$LOG" "\$run/vm.log" 2>/dev/null
cd "\$run" || exit 1
set --
for m in vm.log state.json parts records logs; do [ -e "\$m" ] && set -- "\$@" "\$m"; done
tar -czf "\$out.tmp" "\$@" 2>/dev/null && mv -f "\$out.tmp" "\$out"
if [ -n "\$bucket" ]; then
  gcloud storage cp "\$out" "\$bucket/boxruns/\$(basename "\$run")/results.tgz" >/dev/null 2>&1 \\
    || echo "TB-UPLOAD-FAILED: results.tgz to \$bucket" | tee -a "$LOG" >"$SERIAL"
fi
EOS
chmod 0755 "$SBIN/tb-boxrun-pack"
pack() { "$SBIN/tb-boxrun-pack" "$RUN" "$BUCKET"; }

# ------------------------------------------------------------------ the VM stops itself (first, before anything)
MAXM=$(md tb-max-minutes || echo 240)
IDLEM=$(md tb-idle-minutes || echo 20)
GRACE=$(md tb-done-grace || echo 30)
HEALTHM=$(md tb-healthy-minutes || echo 20)
POWERM=$(md tb-power-wait-minutes || echo 15)
# the cap counts the seconds of every boot of this run: the watchdog writes them down each tick
CAP_USED=$(cat "$RUN/cap-used-s" 2>/dev/null || echo 0)
CAP_LEFT=$((MAXM * MIN_S - CAP_USED))
cat > "$SBIN/tb-boxrun-off" <<EOS
#!/bin/sh
# tb-boxrun-off <why>: say why (console, run log), pack what there is, power off. A stopped VM always has a results.tgz
# (the pack is a tar of logs, seconds of work: 120 s only keeps a hung bucket upload from holding the power-off)
echo "TB-WATCHDOG \$1: powering off" >"$SERIAL"
echo "TB-WATCHDOG \$1: powering off" >> "$LOG"
# the cap's own power-off closes the account: a later boot of this run ends at once (TB-CAP-REACHED) and only hands over
[ "\${2:-}" = cap ] && echo $((MAXM * MIN_S)) > "$RUN/cap-used-s"
[ -f "$TB/current-run" ] && timeout 120 "$SBIN/tb-boxrun-pack" "\$(cat "$TB/current-run")" "\$(cat "$TB/current-bucket" 2>/dev/null)"
systemctl poweroff
EOS
cat > "$SBIN/tb-boxrun-watchdog" <<EOS
#!/bin/sh
# poweroff, checked every "minute": done and collected, or done for \$2 minutes; no heartbeat for \$1 minutes. It also
# keeps the cap's account: \$3 seconds used by earlier boots plus this boot's, in \$4.
idle=\$1; grace=\$2; used0=\$3; account=\$4; t0=\$(date +%s)
while :; do
  sleep $MIN_S
  now=\$(date +%s)
  used=\$((used0 + now - t0))   # only ever up: the cap's power-off may have closed the account already
  [ "\$used" -le "\$(cat "\$account" 2>/dev/null || echo 0)" ] || { echo "\$used" > "\$account.tmp" && mv -f "\$account.tmp" "\$account"; }
  if [ -f "$DONE" ]; then
    [ -f "$TB/collected" ] && exec "$SBIN/tb-boxrun-off" "done, results collected"
    [ \$((now - \$(stat -c %Y "$DONE"))) -ge \$((grace * $MIN_S)) ] && exec "$SBIN/tb-boxrun-off" "done, grace of \$grace minutes over"
  else
    hb=\$(stat -c %Y "$HB" 2>/dev/null || echo 0)
    [ \$((now - hb)) -ge \$((idle * $MIN_S)) ] && exec "$SBIN/tb-boxrun-off" "no heartbeat for \$idle minutes (phase \$(cat "$PHASE" 2>/dev/null))"
  fi
done
EOS
chmod 0755 "$SBIN/tb-boxrun-off" "$SBIN/tb-boxrun-watchdog"
if [ "$CAP_LEFT" -gt 0 ]; then
  systemd-run --unit tb-boxrun-cap --on-active="${CAP_LEFT}s" --description "TrialBox box run: cost cap" \
    "$SBIN/tb-boxrun-off" "cost cap of $MAXM minutes reached" cap
fi
systemd-run --unit tb-boxrun-watchdog --description "TrialBox box run: watchdog" \
  "$SBIN/tb-boxrun-watchdog" "$IDLEM" "$GRACE" "$CAP_USED" "$RUN/cap-used-s"

# ------------------------------------------------------------------ the state: steps, parts, never a step twice
cat > "$SBIN/tb-boxrun-state.py" <<'PY'
"""state.json and the part results of a box run. A step is: absent, started, done or stop. Written by rename."""
import json, os, sys, time
run, cmd, step = sys.argv[1], sys.argv[2], sys.argv[3]
path = os.path.join(run, "state.json")
def load():
    try:
        return json.load(open(path))
    except FileNotFoundError:
        return {"steps": {}, "order": []}
def save(obj, to=path):
    with open(to + ".tmp", "w") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True); fh.write("\n"); fh.flush(); os.fsync(fh.fileno())
    os.replace(to + ".tmp", to)
st = load()
if cmd == "get":
    print(st["steps"].get(step, {}).get("status", "") if step != "_ended" else st.get("ended", ""))
elif cmd == "begin":   # argv[4] the boot id
    s = st["steps"].setdefault(step, {"first_started": time.time(), "attempts": 0, "boots": []})
    s["status"] = "started"; s["attempts"] += 1
    if sys.argv[4] not in s["boots"]: s["boots"].append(sys.argv[4])
    if step not in st["order"]: st["order"].append(step)
    save(st)
elif cmd == "set":     # a value of the run kept across boots: argv[4] key, argv[5] value
    st.setdefault("kv", {})[sys.argv[4]] = sys.argv[5]; st["kv_step"] = step; save(st)
elif cmd == "kv":
    print(st.get("kv", {}).get(sys.argv[4], ""))
elif cmd == "ended":   # the run's last marker
    st["ended"] = sys.argv[4]; save(st)
elif cmd == "end":     # argv[4] done|stop, argv[5] the notes file (key<TAB>value), argv[6] the stop's reason, argv[7] its log
    s = st["steps"][step]; now = time.time()
    detail = {}
    if os.path.exists(sys.argv[5]):
        for line in open(sys.argv[5]):
            k, _, v = line.rstrip("\n").partition("\t")
            try: detail[k] = json.loads(v)
            except ValueError: detail[k] = v
    part = {"step": step, "ok": sys.argv[4] == "done", "status": sys.argv[4],
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s["first_started"])),
            "ended": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "seconds": round(now - s["first_started"], 3), "minutes": round((now - s["first_started"]) / 60, 2),
            "attempts": s["attempts"], "boots": s["boots"], "detail": detail}
    if "pass" in detail: part["pass"] = bool(detail.pop("pass"))
    if sys.argv[4] == "stop":
        tail = []
        if os.path.exists(sys.argv[7]):
            tail = open(sys.argv[7], errors="replace").read().splitlines()[-20:]
        part["stop"] = {"reason": sys.argv[6], "log_tail": tail}
    save(part, os.path.join(run, "parts", step + ".json"))
    s["status"] = sys.argv[4]; s["seconds"] = part["seconds"]; save(st)
PY
st() { local c=$1 s=$2; shift 2; "$PY" "$SBIN/tb-boxrun-state.py" "$RUN" "$c" "$s" "$@"; }
finish() {  # $1 marker line, $2 phase: say why, keep it in the state, pack, DONE; the watchdog does the rest
  echo "$1" | tee -a "$LOG"; phase "$2"
  st ended _ "$1"
  pack
  touch "$DONE"; echo BOX-RUN-DONE; exit "${3:-1}"
}

# ------------------------------------------------------------------ the door (TLS, the driver's pinned certificate)
# The box owns 443 and 80, so the door is its own small TLS server on tb-door-port: POST /tb/heartbeat, POST
# /tb/collected, GET /tb/progress (phase, the run log's tail, POWER-CYCLE-REQUESTED, DONE), GET /tb/results.tgz. The
# key and the TLS key come from Secret Manager with the VM's own service account, into root-only files.
DOORP=$(md tb-door-port || echo 8443)
install -d -m 700 "$TLS"
DSEC=$(md tb-door-secret || true); DVER=$(md tb-door-version || true)
rm -f "$TB/door-key" "$TLS/door.key"
if [ -n "$DSEC" ] && [ -n "$DVER" ]; then
  (umask 077; gcloud secrets versions access "$DVER" --secret="$DSEC" 2>/dev/null | "$PY" -c '
import json, sys
d = json.load(sys.stdin)
open(sys.argv[1], "w").write(d["key"].strip()); open(sys.argv[2], "w").write(d["tls_key"])' "$TB/door-key" "$TLS/door.key")
  (umask 022; md tb-door-cert > "$TLS/door.crt") || rm -f "$TLS/door.crt"
fi
[ -s "$TB/door-key" ] && [ -s "$TLS/door.key" ] && [ -s "$TLS/door.crt" ] \
  || { echo "TB-NO-KEY: no door from Secret Manager (tb-door-secret, tb-door-version, tb-door-cert); powering off"
       systemctl poweroff; exit 1; }
(umask 077; printf 'Authorization: Bearer %s\n' "$(cat "$TB/door-key")" > "$TB/door-hdr")
cat > "$SBIN/tb-boxrun-door.py" <<'PY'
import hmac, http.server, pathlib, ssl, subprocess, sys
TB, LOG = pathlib.Path(sys.argv[1]), sys.argv[2]
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
        if self.path == "/tb/heartbeat": (TB / "heartbeat").touch(); return self._ok()
        if self.path == "/tb/collected": (TB / "collected").touch(); return self._ok()
        self.send_error(404)
    def do_GET(self):
        if self.path == "/tb/progress":
            phase = (TB / "phase").read_text() if (TB / "phase").exists() else "?\n"
            tail = subprocess.run(["tail", "-n", "15", LOG], capture_output=True).stdout
            flags = (b"POWER-CYCLE-REQUESTED\n" if (TB / "POWER-CYCLE-REQUEST").exists() else b"") \
                + (b"DONE\n" if (TB / "DONE").exists() else b"")
            return self._ok(f"phase {phase}".encode() + tail + flags)
        if self.path == "/tb/results.tgz" and (TB / "out" / "results.tgz").exists():
            return self._ok((TB / "out" / "results.tgz").read_bytes(), "application/gzip")
        self.send_error(404)
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer((sys.argv[3], int(sys.argv[4])), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.minimum_version = ssl.TLSVersion.TLSv1_2
ctx.load_cert_chain(sys.argv[5], sys.argv[6])
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
PY
DOOR_HOST=${TB_BOXRUN_DOOR_HOST:-0.0.0.0}
systemd-run --unit tb-boxrun-door --property=Restart=on-failure --description "TrialBox box run: the driver's door" \
  "$PY" "$SBIN/tb-boxrun-door.py" "$TB" "$LOG" "$DOOR_HOST" "$DOORP" "$TLS/door.crt" "$TLS/door.key"
DOOR_TLS=(--noproxy "*" --cacert "$TLS/door.crt" --resolve "tb-door:$DOORP:127.0.0.1")
door_up() { curl -fsS -o /dev/null --max-time 5 "${DOOR_TLS[@]}" -H @"$TB/door-hdr" "https://tb-door:$DOORP/tb/progress"; }
# a door that never answers means a paid VM nobody can drive: 30 tries 2 seconds apart (the server only has to bind,
# as complete-run-vm.sh waits for its own), then off
for _ in $(seq 1 30); do door_up 2>/dev/null && break; sleep 2; done
door_up || { echo "TB-DOOR-FAILED: /tb/progress does not answer on port $DOORP (TLS): powering off"; systemctl poweroff; exit 1; }
echo "TB-DOOR-UP on port $DOORP (TLS, the key checked)"
pack   # a results.tgz from the first minute on

# ------------------------------------------------------------------ the settings, and what an earlier boot left
BUNDLE_SRC=$(md tb-bundle || true)
BUNDLE_SHA=$(md tb-bundle-sha256 || true)
BOXROOT=$(md tb-box-root || echo /opt/trialbox)
INSTALLER=$(md tb-installer || echo "$BOXROOT/deploy/box-install.sh")
ASEC=$(md tb-answers-secret || true); AVER=$(md tb-answers-version || true)
PROFILE=$(md tb-profile || echo rtxpro6000)
MODELS=$(md tb-models-root || echo /models)
JUDGE_C=$(md tb-judge-container || echo judge)
VERIFIER_C=$(md tb-verifier-container || echo verifier)
G9_CONTAINERS=$(md tb-g9-containers || echo "orchestrator adapter judge")
PATIENTS=$(md tb-patients || echo 50000)
LLMC=$(md tb-llm-concurrency || echo 16)
CURRENT_FILE=$(md tb-current-file || echo "$BOXROOT/deploy/data/lake/CURRENT")
G10_IMAGE=$(md tb-g10-vllm-image || true)
BUNDLE="$TB/bundle/$RUN_ID.tar"
UNPACKED="$RUN/bundle"
ANSWERS="$TB/wizard-answers"
REC="$RUN/records"

ENDED=$(st get _ended)
if [ -n "$ENDED" ]; then  # this run already ended (a stop, or all steps): hand over its results, repeat nothing
  echo "TB-RUN-ENDED-BEFORE: $ENDED" | tee -a "$LOG"; phase ended
  pack; touch "$DONE"; echo BOX-RUN-DONE; exit 0
fi
[ "$CAP_LEFT" -gt 0 ] || finish "TB-CAP-REACHED: the $MAXM minutes of this run are used ($CAP_USED s over its boots)" cap-reached

pf=""
for c in docker nvidia-smi "$PY" curl tar sha256sum; do command -v "$c" >/dev/null || pf="$pf; no $c"; done
[ -n "$BUNDLE_SRC" ] || pf="$pf; no tb-bundle"
[ -n "$BUNDLE_SHA" ] || pf="$pf; no tb-bundle-sha256 (a bundle is never installed unchecked)"
[ -n "$G10_IMAGE" ] || pf="$pf; no tb-g10-vllm-image (G-10 names its image)"
[ -n "$ASEC" ] && [ -n "$AVER" ] || pf="$pf; no tb-answers-secret / tb-answers-version (the wizard's answers file)"
[ -d "$MODELS" ] || pf="$pf; no model folders at $MODELS"
[ -z "$pf" ] || finish "TB-PREFLIGHT-FAILED${pf}" preflight-failed
echo "TB-PREFLIGHT ok"

# ------------------------------------------------------------------ the step runner
STEP=""; STEP_LOG=/dev/null; NOTES=/dev/null; STOP=""
note() { printf '%s\t%s\n' "$1" "$2" >> "$NOTES"; }          # a value of the step's part result (JSON, or plain text)
watched() {  # run a command of the step, its output to the step's log; the log growing is the heartbeat
  echo "+ $(basename "$1") (${#} words) $(date -u +%T)" >> "$STEP_LOG"
  "$@" >> "$STEP_LOG" 2>&1 < /dev/null &
  local pid=$! size=-1 now
  while kill -0 "$pid" 2>/dev/null; do
    now=$(stat -c %s "$STEP_LOG" 2>/dev/null || echo 0)
    [ "$now" = "$size" ] || { touch "$HB"; size=$now; }
    sleep "$POLL"
  done
  wait "$pid"
}
need() {  # need <what it is> <command...>: run it watched; a failure is the step's STOP, never repaired here
  local what=$1 rc; shift
  watched "$@"; rc=$?
  [ "$rc" = 0 ] && return 0
  case "$rc" in
    126|127) STOP="$what: the command is not there or does not run (exit $rc): a person would need a shell" ;;
    *) STOP="$what: exit $rc" ;;
  esac
  return 1
}
run_step() {  # run_step <NN-name> <function> [args]: once per run, timed, a part result, a STOP ends the run
  local name=$1 fn=$2 rc; shift 2
  case "$(st get "$name")" in
    done) echo "TB-STEP $name kept (finished before; not run again)" | tee -a "$LOG"; return 0 ;;
    stop) finish "TB-STOP $name (recorded before; not run again)" stopped ;;
  esac
  STEP=$name; STEP_LOG="$RUN/logs/$name.log"; NOTES="$RUN/logs/$name.notes"; STOP=""
  phase "$name"; touch "$HB"
  st begin "$name" "$BOOT_ID"
  echo "TB-STEP $name start $(date -u +%FT%TZ)" | tee -a "$LOG"
  "$fn" "$@"; rc=$?
  if [ "$rc" = 0 ] && [ -z "$STOP" ]; then
    st end "$name" done "$NOTES" "" "$STEP_LOG"
    echo "TB-STEP $name done" | tee -a "$LOG"; pack; return 0
  fi
  st end "$name" stop "$NOTES" "${STOP:-exit $rc}" "$STEP_LOG"
  finish "TB-STOP $name: ${STOP:-exit $rc}" stopped
}

# ------------------------------------------------------------------ lane D's interface: one function per call
# ASSUMED until lane D's installer, wizard and qualification path land (2026-12-04). Change these bodies only.
box_tool() { (cd "$BOXROOT" && PYTHONPATH="$BOXROOT/libs:$BOXROOT" exec "$PY" -m "tools.$1" "${@:2}"); }
d_install()  { "$INSTALLER" "$1" --prepare --yes; }                       # the bundle -> an installed box, wizard pending
d_wizard()   { "$INSTALLER" --firstrun --answers "$1"; }                  # the wizard takes a file, no browser, no code
d_pin()      { box_tool pin_model --install "$PROFILE" --models-root "$MODELS"; }
d_qualify()  { box_tool qualify --profile "$PROFILE" --out "$1"; }        # full: no --items cap
d_promote()  { box_tool pin_model --promote "$1" --record "$2" --environment PRODUCTION; }
d_resolve()  { box_tool pin_model --resolve --environment PRODUCTION; }   # stdout: {"judge": {"build":, "promoted":}, "verifier": ...}
d_capture()  { box_tool serving_config capture --container "judge=$JUDGE_C" --container "verifier=$VERIFIER_C" \
                 --models-dir "$MODELS" --notes "$PROFILE profile: box run $RUN_ID" --out "$1"; }
d_screen_start()  { box_tool screen_job start --patients "$PATIENTS" --llm-concurrency "$LLMC"; }   # stdout: the job id
d_screen_status() { box_tool screen_job status --job "$1"; }   # stdout: {"state":, "in_flight":, "calls_total":, "calls_repeated":}
d_healthy()  { box_tool trialbox doctor; }                                # exit 0: the whole stack is healthy
d_canary()   { box_tool canary --out "$1"; }                              # the 54-case pair canary; exit 0: passed
jget() { "$PY" -c 'import json,sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$1" "$2" 2>/dev/null; }

# ------------------------------------------------------------------ the bundle
step_bundle() {
  mkdir -p "$TB/bundle"
  case "$BUNDLE_SRC" in
    gs://*) need "fetching the bundle from the bucket" gcloud storage cp "$BUNDLE_SRC" "$BUNDLE" || return 1 ;;
    *) [ -f "$BUNDLE_SRC" ] || { STOP="no bundle at $BUNDLE_SRC"; return 1; }
       BUNDLE=$BUNDLE_SRC ;;
  esac
  local size free got
  size=$(stat -c %s "$BUNDLE"); note bundle_bytes "$size"
  got=$(sha256sum "$BUNDLE" | cut -d' ' -f1)
  [ "$got" = "$BUNDLE_SHA" ] || { STOP="TB-BUNDLE-REFUSED: sha256 ${got:0:16}... is not the declared ${BUNDLE_SHA:0:16}..."; return 1; }
  touch "$HB"
  # room to unpack: the bundle's own size (a tar's members add up to it), from the data, not a fixed floor
  free=$(df -B1 --output=avail "$RUN" | tail -n 1 | tr -dc 0-9)
  [ "${free:-0}" -gt "$size" ] || { STOP="${free:-0} bytes free under $RUN, the bundle needs $size to unpack"; return 1; }
  rm -rf "$UNPACKED"; mkdir -p "$UNPACKED"
  # every file the manifest lists: there, its size, its sha256; nothing unpacked that the manifest does not list
  # (the signature over the manifest is the installer's own check, tools/apply_update.sh)
  cat > "$SBIN/tb-boxrun-manifest.py" <<'PY'
import hashlib, json, os, sys, tarfile
bundle, out, notes, hb = sys.argv[1:5]
bad = []
with tarfile.open(bundle) as tar:
    names = {m.name.removeprefix("./"): m for m in tar.getmembers()}
    if "manifest.json" not in names:
        sys.exit("no manifest.json in the bundle")
    manifest = json.load(tar.extractfile(names["manifest.json"]))
    listed = {f["path"]: f for f in manifest["files"]}
    for name, m in names.items():
        if m.isdir() or name.startswith("manifest."):
            continue
        if name not in listed or not m.isfile() or name.startswith("/") or ".." in name.split("/"):
            bad.append(f"{name}: not a plain file the manifest lists")
    for path, f in listed.items():
        m = names.get(path)
        if m is None:
            bad.append(f"{path}: listed, not in the bundle"); continue
        if not m.isfile() or path.startswith("/") or ".." in path.split("/"):
            continue   # refused above
        if m.size != f["size"]:
            bad.append(f"{path}: {m.size} bytes, the manifest says {f['size']}"); continue
        h, src = hashlib.sha256(), tar.extractfile(m)
        dst = os.path.join(out, path); os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            while chunk := src.read(1 << 20):
                h.update(chunk); fh.write(chunk)
        os.utime(hb)   # a large payload is progress
        if h.hexdigest() != f["sha256"]:
            bad.append(f"{path}: sha256 {h.hexdigest()[:16]}... is not the manifest's {f['sha256'][:16]}...")
            os.remove(dst)
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh)
with open(notes, "a") as fh:
    fh.write("manifest_files\t%d\n" % len(listed))
    fh.write("manifest_release\t%s\n" % json.dumps(manifest.get("release", manifest.get("version", ""))))
    fh.write("refused\t%s\n" % json.dumps(bad))
for b in bad:
    print("TB-BUNDLE-REFUSED:", b)
sys.exit(1 if bad else 0)
PY
  need "TB-BUNDLE-REFUSED: the bundle's manifest" "$PY" "$SBIN/tb-boxrun-manifest.py" "$BUNDLE" "$UNPACKED" "$NOTES" "$HB" \
    || return 1
  st set "$STEP" bundle "$BUNDLE"
}

# ------------------------------------------------------------------ the installer, the wizard
step_install() {
  local b; b=$(st kv _ bundle)
  [ -x "$INSTALLER" ] || { STOP="no installer at $INSTALLER (tb-installer): a person would need a shell"; return 1; }
  note installer "$INSTALLER"
  need "the installer" d_install "$b"
}
step_wizard() {
  (umask 077; gcloud secrets versions access "$AVER" --secret="$ASEC" > "$ANSWERS" 2>/dev/null) && [ -s "$ANSWERS" ] \
    || { STOP="no wizard answers in Secret Manager (tb-answers-secret, tb-answers-version)"; return 1; }
  need "the first-run wizard with an answers file only" d_wizard "$ANSWERS"; local rc=$?
  rm -f "$ANSWERS"
  return $rc
}

# ------------------------------------------------------------------ pin, qualify, promote, resolve
QREC="$REC/qualification.json"
step_pin() { need "pinning the $PROFILE pair from $MODELS" d_pin; }
step_qualify() {
  need "the full qualification" d_qualify "$QREC" || return 1
  [ -s "$QREC" ] || { STOP="the qualification wrote no record"; return 1; }
}
step_promote() {  # step_promote <role>
  local build; build=$(jget "$QREC" "builds.$1")
  [ -n "$build" ] || { STOP="the qualification record names no $1 build (builds.$1)"; return 1; }
  note build "\"$build\""
  need "promoting the $1 build" d_promote "$build" "$QREC"
}
step_resolve() {
  local res="$REC/production-resolves.json" role build
  d_resolve > "$res" 2>> "$STEP_LOG" || { STOP="PRODUCTION does not resolve (exit $?)"; return 1; }
  for role in judge verifier; do
    build=$(jget "$QREC" "builds.$role")
    [ "$(jget "$res" "$role.build")" = "$build" ] && [ "$(jget "$res" "$role.promoted")" = True ] \
      || { STOP="PRODUCTION resolves $role to '$(jget "$res" "$role.build")' (promoted: $(jget "$res" "$role.promoted")), not to the promoted build"; return 1; }
    note "$role" "\"$build\""
  done
  note production_resolves_promoted true
}

# ------------------------------------------------------------------ the serving record and vLLM host RSS
step_serving() {
  local c pid
  need "the serving capture" d_capture "$REC/serving_config.json" || return 1
  for c in "$JUDGE_C" "$VERIFIER_C"; do
    pid=$(docker inspect --format '{{.State.Pid}}' "$c" 2>> "$STEP_LOG")
    [ -n "$pid" ] && [ "$pid" != 0 ] || { STOP="no running container '$c' (tb-judge-container, tb-verifier-container)"; return 1; }
    # the resident memory of the container's whole process tree, read on the host
    note "host_rss_kib_$c" "$("$PY" - "$pid" <<'PY'
import os, sys
kids = {}
for p in filter(str.isdigit, os.listdir("/proc")):
    try: ppid = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()[1]
    except OSError: continue
    kids.setdefault(ppid, []).append(p)
todo, total = [sys.argv[1]], 0
while todo:
    p = todo.pop(); todo += kids.get(p, [])
    try: total += next(int(line.split()[1]) for line in open(f"/proc/{p}/status") if line.startswith("VmRSS:"))
    except (OSError, StopIteration): pass
print(total)
PY
)"
  done
  note gpu_memory_used_total_mib "\"$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null)\""
}

# ------------------------------------------------------------------ G-9: restarts and a power cycle in a screen
job_status() { d_screen_status "$(st kv _ g9_job)" > "$RUN/logs/job-status.json" 2>> "$STEP_LOG"; }
job() { jget "$RUN/logs/job-status.json" "$1"; }
current() { cat "$CURRENT_FILE" 2>/dev/null || echo "(no file)"; }
wait_in_flight() {  # until the job has LLMC calls in flight; the job's own progress is the heartbeat (a stuck job: the watchdog)
  local last=-1
  while :; do
    job_status || { STOP="the screen's status cannot be read"; return 1; }
    case "$(job state)" in
      running) ;;
      *) STOP="the screen is '$(job state)' before the interruption: it must be running (a larger tb-patients)"; return 1 ;;
    esac
    [ "$(job calls_total)" = "$last" ] || { touch "$HB"; last=$(job calls_total); }
    [ "$(job in_flight)" = "$LLMC" ] && return 0
    sleep "$POLL"
  done
}
wait_healthy() {  # seconds from $1 (epoch) until the stack is healthy, at most tb-healthy-minutes
  local t0=$1 limit=$((HEALTHM * MIN_S))
  until d_healthy >> "$STEP_LOG" 2>&1; do
    touch "$HB"
    [ $(($(date +%s) - t0)) -lt "$limit" ] || { STOP="not healthy $HEALTHM minutes after the interruption"; return 1; }
    sleep "$POLL"
  done
  note seconds_to_healthy $(($(date +%s) - t0))
}
after_interruption() {  # the job after an interruption: its state, the calls repeated by it, the rule
  local before=$1 rep ok=true
  job_status || { STOP="the screen's status cannot be read"; return 1; }
  rep=$(($(job calls_repeated) - before))
  note job_state "\"$(job state)\""; note calls_repeated "$rep"; note calls_in_flight "$LLMC"
  case "$(job state)" in running|done) ;; *) ok=false ;; esac
  [ "$rep" -le "$LLMC" ] || ok=false       # no call is paid twice beyond the ones in flight
  note pass "$ok"
}
step_g9_screen() {
  local id
  note current_before "\"$(current)\""; st set "$STEP" g9_current "$(current)"
  id=$(d_screen_start 2>> "$STEP_LOG") && [ -n "$id" ] || { STOP="the screen did not start as a job of the box"; return 1; }
  st set "$STEP" g9_job "$id"; note job "\"$id\""; note patients "$PATIENTS"
  wait_in_flight
}
step_g9_restart() {
  local c=$1 before t0
  wait_in_flight || return 1
  before=$(job calls_repeated); t0=$(date +%s)
  need "docker restart $c" docker restart "$c" || return 1
  wait_healthy "$t0" || return 1
  after_interruption "$before"
}
step_g9_power() {
  local t0 before
  if [ "$(st kv _ g9_power_boot)" = "" ]; then   # first pass: ask for the power cycle and wait to be stopped
    wait_in_flight || return 1
    st set "$STEP" g9_power_repeated "$(job calls_repeated)"
    st set "$STEP" g9_power_boot "$BOOT_ID"
    printf '{"run": "%s", "requested": "%s", "boot": "%s"}\n' "$RUN_ID" "$(date -u +%FT%TZ)" "$BOOT_ID" > "$TB/POWER-CYCLE-REQUEST"
    [ -z "$BUCKET" ] || gcloud storage cp "$TB/POWER-CYCLE-REQUEST" "$BUCKET/boxruns/$RUN_ID/POWER-CYCLE-REQUEST" >/dev/null 2>&1
    echo "TB-POWER-CYCLE-REQUESTED (the driver stops and starts this VM)" | tee -a "$LOG"; pack
    t0=$(date +%s)
    while [ $(($(date +%s) - t0)) -lt $((POWERM * MIN_S)) ]; do touch "$HB"; sleep "$POLL"; done
    rm -f "$TB/POWER-CYCLE-REQUEST"
    STOP="the driver did not power-cycle the VM in $POWERM minutes"; return 1
  fi
  rm -f "$TB/POWER-CYCLE-REQUEST"
  [ "$(st kv _ g9_power_boot)" != "$BOOT_ID" ] \
    || { STOP="the power cycle was requested and this is still the same boot: the script was restarted, not the VM"; return 1; }
  echo "TB-POWER-CYCLE-DONE (boot ${BOOT_ID:0:8})" | tee -a "$LOG"
  note boot_before "$(st kv _ g9_power_boot)"; note boot_after "$BOOT_ID"
  wait_healthy "$BOOT_T0" || return 1                  # from this boot's start: nobody signs in, nobody starts a thing
  before=$(st kv _ g9_power_repeated)
  after_interruption "$before"
}
step_g9_result() {
  local last=-1 ok=true n=0 c
  for c in $G9_CONTAINERS; do n=$((n + 1)); done; n=$((n + 1))   # the interruptions: each restart and the power cycle
  while :; do
    job_status || { STOP="the screen's status cannot be read"; return 1; }
    case "$(job state)" in running) ;; *) break ;; esac
    [ "$(job calls_total)" = "$last" ] || { touch "$HB"; last=$(job calls_total); }
    sleep "$POLL"
  done
  cp "$RUN/logs/job-status.json" "$REC/g9-job-final.json"
  note final_job_state "\"$(job state)\""; note calls_total "$(job calls_total)"; note calls_repeated "$(job calls_repeated)"
  note interruptions "$n"
  note current_before "\"$(st kv _ g9_current)\""; note current_after "\"$(current)\""
  note current_moved "$([ "$(current)" = "$(st kv _ g9_current)" ] && echo false || echo true)"
  [ "$(job state)" = done ] || ok=false                                   # the job resumed and ended
  [ "$(job calls_repeated)" -le $((n * LLMC)) ] || ok=false               # nothing paid twice beyond the calls in flight
  note pass "$ok"
}

# ------------------------------------------------------------------ G-10: the canary on the declared image
step_g10() {
  local c img out="$REC/canary-g10.json" ok=true
  for c in "$JUDGE_C" "$VERIFIER_C"; do
    img=$(docker inspect --format '{{.Config.Image}}' "$c" 2>> "$STEP_LOG")
    note "image_$c" "\"$img\""
    [ "$img" = "$G10_IMAGE" ] \
      || { STOP="'$c' runs on '$img', G-10 is declared for '$G10_IMAGE' (tb-g10-vllm-image): the image move is the bundle's, not this script's"; return 1; }
  done
  watched d_canary "$out"; note canary_exit $?
  [ -s "$out" ] || { STOP="the canary wrote no result"; return 1; }
  note cases "$(jget "$out" total)"; note passed "$(jget "$out" passed)"
  note schema_failures "$(jget "$out" schema_failures)"; note calls_per_s "$(jget "$out" calls_per_s)"
  # 54 of 54: the canary's own size (tools/canary.py), not a limit of this script
  [ "$(jget "$out" total)" = 54 ] && [ "$(jget "$out" passed)" = 54 ] || ok=false
  note pass "$ok"
}

# ------------------------------------------------------------------ the run
N=0
step() { N=$((N + 1)); run_step "$(printf '%02d' "$N")-$1" "${@:2}"; }   # numbered in the order they run
step bundle step_bundle
step install step_install
step wizard step_wizard
step pin step_pin
step qualify step_qualify
step promote-judge step_promote judge
step promote-verifier step_promote verifier
step resolve step_resolve
step serving step_serving
step g9-screen step_g9_screen
for c in $G9_CONTAINERS; do step "g9-restart-$c" step_g9_restart "$c"; done
step g9-power step_g9_power
step g9-result step_g9_result
step g10-canary step_g10
finish "TB-BOX-RUN-COMPLETE: every step ran; the parts say which test rules passed" complete 0
