#!/bin/bash
# TrialBox box run ON the cloud GPU VM (plan v7 section 7.1; R2 of lane G; tests G-2, G-6, G-9, G-10; gap X-10 of the
# GCP test plan). The VM's startup script for the run (as complete-run-vm.sh is for the complete run). The driver is
# deploy/gcp/box-run.sh; nobody runs this by hand. GCE runs a startup script at every boot, so a power cycle or a
# pre-emption resumes here by itself. Fail-safe in the same three ways as the complete run: a cost cap, a watchdog,
# and results that leave the VM after every step (the bucket, and the door when there is no bucket).
#
# Groups of steps, chosen by the metadata tb-steps (one or more of: build start g6 g9 g10, in this order). Each step
# is timed and written as a part result (parts/<step>.json) and kept in state.json: a step that finished is never run
# again, in this boot or after a restart. A step cut by a restart (a pre-emption, a power cut) runs again.
#   build  R2's bundle, on the runner VM, as the service account that may read the vendor key (r2-bundle-plan.md):
#     b01-source    the release commit from the git bundle in the bucket (tb-src), checked out, HEAD = tb-commit
#     b02-venv      make venv scanners
#     b03-images    make images
#     b04-gates     make trivy-db release-gates, enforcing: a gate that fails stops the build before the key is read
#     b05-sign      the vendor key from Secret Manager BY NAME (tb-vendor-key-secret, tb-vendor-key-version) into a
#                   tmpfs file of mode 600, tools/make_bundle.sh, the file shredded (a trap, and again after the step)
#     b06-verify    tools/verify_update.py with the vendor PUBLIC key (tb-vendor-pub), then the release record as a
#                   PRODUCTION box reads it: no rehearsal mark (D-726), not dirty, the declared commit (D-633)
#     b07-upload    the bundle and its .sha256 to tb-out; records/bundle.json (id, seq, commit, sha256, bytes)
#   start  G-2, the production start from the uploaded bundle with the real installer:
#     01-bundle     fetch, the whole file's sha256, every payload and meta file against the manifest (streamed, never
#                   unpacked), the release record as PRODUCTION reads it; the host tree from the signed bundle
#                   unpacked as the installer's bootstrap, the vendor PUBLIC key placed at deploy/keys (P8)
#     02-install    deploy/box-install.sh <bundle> --prepare --yes (non-interactive, up to the first-run wizard)
#     03-wizard     deploy/box-install.sh --firstrun, and the wizard answered as its owner does in a browser: the
#                   one-time code off the box's screen, the console's first-run page over HTTPS (box_vm.py wizard),
#                   the answers from Secret Manager (tb-answers-secret); then the installer applies them itself
#     04-pin        pin_model --install: the pair from the real model folders (the installer's own pins kept)
#     05-serving    the serving record of the running pair, the model servers' host memory
#     06-g1         G-1 on the SHIPPED serving: the template the judge server was started with (its sha256 read in
#                   its container) against models/registry.yaml; each model server's image digest against
#                   deploy/images.lock; the weights against their pins (pin_model --verify-all); the prompt versions
#                   the box serves in PRODUCTION. Written as records/identity.json, which every result names
#     07-canary     the pair canary (trialbox selftest)
#     08-qualify    trialbox eval qualify on the real weights, with the evidence files of tb-qualify-evidence
#     09/10-promote-<role>, 11-resolve   promoted from that record; PRODUCTION resolves to the promoted builds
#     12-doctor     trialbox doctor --live --json: no FAIL beyond tb-doctor-expected, no rehearsal mark (G-2's rule)
#   The models are started only by the installed box's own compose (the installer): no vLLM start of this script.
#   g6     G-6, the night of tb-g6-patients dense synthetic patients under the production caps ("the 50k night
#          profiling"): g6-study, g6-feed, then ingest, rebuild, screen, backup, each with its wall time and each
#          container's peak memory (cgroup v2), and g6-result (the three largest costs). T-692 (the ingest needs 16 to
#          17 GB against a 6 to 8 GB cap) is recorded as what happens: an OOM kill is a fact of the part, not hidden
#   g9     G-9, interruptions in the middle of a screen with the box's own calls in flight (TB_SCREEN_LLM_CONCURRENCY:
#          16 on the rtxpro6000 profile): g9-baseline (G-6's screen when it ran, else an undisturbed one), g9-screen,
#          g9-restart-<service> per tb-g9-services, g9-outage (the judge's server stopped for tb-outage-seconds),
#          g9-power (a power cycle: the driver stops and starts the VM), g9-result: pass = the job ended done and its
#          candidate list equals the undisturbed one
#   g10    G-10, the model-server image named by tb-g10-vllm-image: g10-update (an update bundle that carries it,
#          tb-g10-bundle, through tools/apply_update.sh; skipped when none is named), g10-image (both model servers
#          run that image, else a stop), g10-canary (trialbox selftest), g10-qualify
# G-2's pass rule is "no step needed a shell beyond the installer". So nothing here repairs or works around a step: a
# box command that fails, or is not there, is a STOP (what was run, its exit code, the last lines of its log) and the
# run ends with that record. A test rule not met (a list that differs, an OOM kill) is not a stop: the part says
# "pass": false and the run goes on, so one paid session measures all it can.
#
# Every call into the box is one function d_* below. They are today's commands (train 17), not yet run on a real
# box: the run's first paid steps will show any that differ, as a stop with its log. Lane D's open items are listed
# in docs/runbook/11-cloud-runs.md (section "Box run").
#
# Metadata (set by the driver). "(setting)" marks a declared limit with its reason (OD-10):
#   tb-run-id, tb-steps, tb-bucket (gs://...; results.tgz after every step, the power-cycle marker)
#   tb-helper           deploy/gcp/box_vm.py (the helper; standard library only)
#   tb-door-secret, tb-door-version, tb-door-cert, tb-door-port   the door (optional with a bucket; port default 8443,
#                       a setting: 443 and 80 belong to the installed box)
#   build: tb-src, tb-commit, tb-release-id, tb-release-seq, tb-vendor-key-secret (the NAME of the secret),
#          tb-vendor-key-version, tb-vendor-pub (gs:// of the public key), tb-out (gs:// prefix), tb-build-root
#   start: tb-bundle, tb-bundle-sha256, tb-commit (optional), tb-vendor-pub, tb-box-root (default /opt/trialbox),
#          tb-answers-secret, tb-answers-version (JSON of the wizard's form fields: a synthetic site; it holds the
#          owner's password, so a secret, never printed), tb-console-connect (default 127.0.0.1:443), tb-console-cacert
#          (default <box>/deploy/secrets/tls/caddy-root.crt), tb-profile (rtxpro6000), tb-models-root (/models),
#          tb-judge-service (llm-service), tb-verifier-service (llm-verifier), tb-doctor-expected (doctor checks
#          expected to FAIL on a fresh cloud box: lane D names them; empty: none), tb-box-python (python3)
#          tb-qualify-evidence (space-separated step=gs://... result files for qualify's evidence steps)
#   g6/g9: tb-study (the approved study the screens run), tb-g6-patients (50000), tb-g6-profile (dense),
#          tb-g9-services ("orchestrator gateway"), tb-outage-seconds (setting, default 120: longer than the gateway's
#          own retry, so the outage reaches the job), tb-screen-requester (the mailbox the screen is requested as)
#   g10: tb-g10-vllm-image (required), tb-g10-bundle, tb-g10-bundle-sha256 (optional)
#   tb-max-minutes (setting, 240: the driver sets it from its estimate), tb-idle-minutes (setting, 20: the longest
#   silence known is a model load), tb-done-grace (setting, 30), tb-healthy-minutes (setting, 20: a model load),
#   tb-power-wait-minutes (setting, 15: the driver polls every minute and a GCE stop takes a few)
# Nothing prints a key: no `set -x`. Knobs for the rehearsal only (tests/rehearsal/box-run; never set on the VM):
# TB_BOXRUN_ROOT, TB_BOXRUN_LOGDIR, TB_BOXRUN_SBIN, TB_BOXRUN_TLS, TB_BOXRUN_SERIAL, TB_BOXRUN_BOOT_ID, TB_BOXRUN_PY,
# TB_BOXRUN_MINUTE_S, TB_BOXRUN_POLL_S, TB_BOXRUN_DOOR_HOST, TB_BOXRUN_SHM (the tmpfs of the key), TB_BOXRUN_CGROUP
# (the cgroup root), TB_ISSUE_DIR (deploy/box-install.sh's own knob: where the box's screen text goes).
TB=${TB_BOXRUN_ROOT:-/var/lib/tb}
LOGDIR=${TB_BOXRUN_LOGDIR:-/var/log}
SBIN=${TB_BOXRUN_SBIN:-/usr/local/sbin}
TLS=${TB_BOXRUN_TLS:-/root/tls}
SERIAL=${TB_BOXRUN_SERIAL:-/dev/ttyS0}
MIN_S=${TB_BOXRUN_MINUTE_S:-60}
POLL=${TB_BOXRUN_POLL_S:-5}
PY=${TB_BOXRUN_PY:-python3}
SHM=${TB_BOXRUN_SHM:-/dev/shm}
CGROOT=${TB_BOXRUN_CGROUP:-/sys/fs/cgroup}
CON=$LOGDIR/tb-boxrun.log
LOG=$LOGDIR/tb-boxrun-run.log
mkdir -p "$TB/out" "$TB/boxruns" "$LOGDIR" "$SBIN"
[ -f "$CON" ] && mv -f "$CON" "$CON.prev"
exec > >(tee -a "$CON" "$SERIAL") 2>&1
set -u
export PATH="$PATH:/snap/bin"
md() { curl -sf -H Metadata-Flavor:Google "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
HB="$TB/heartbeat"; DONE="$TB/DONE"; PHASE="$TB/phase"
phase() { printf '%s\n' "$1" > "$PHASE"; echo "TB-PHASE $1 $(date -u +%FT%TZ)"; }
BOOT_T0=$(date +%s)
BOOT_ID=${TB_BOXRUN_BOOT_ID:-$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo "boot-$BOOT_T0")}
phase boot
touch "$HB"
rm -f "$DONE" "$TB/collected" "$TB/uploaded"
rm -rf "$SHM"/tbk.* 2>/dev/null   # a key left by a step this boot never finished (a reboot clears tmpfs anyway)

RUN_ID=$(md tb-run-id || echo boxrun)
RUN_ID=$(printf '%s' "$RUN_ID" | tr -c 'A-Za-z0-9._-' '_')
RUN="$TB/boxruns/$RUN_ID"
BUCKET=$(md tb-bucket || true)
mkdir -p "$RUN/parts" "$RUN/logs" "$RUN/records"
printf '%s' "$RUN" > "$TB/current-run"; printf '%s' "$BUCKET" > "$TB/current-bucket"
echo "== boot $(date -u +%FT%TZ) run $RUN_ID boot ${BOOT_ID:0:8}" >> "$LOG"

# results.tgz of the run so far, renamed into place; with a bucket also uploaded, and $TB/uploaded says it went
cat > "$SBIN/tb-boxrun-pack" <<EOS
#!/bin/sh
run=\$1; bucket=\${2:-}; out=$TB/out/results.tgz
cp "$LOG" "\$run/vm.log" 2>/dev/null
cd "\$run" || exit 1
set --
for m in vm.log state.json parts records logs; do [ -e "\$m" ] && set -- "\$@" "\$m"; done
tar -czf "\$out.tmp" "\$@" 2>/dev/null && mv -f "\$out.tmp" "\$out"
if [ -n "\$bucket" ]; then
  if gcloud storage cp "\$out" "\$bucket/boxruns/\$(basename "\$run")/results.tgz" >/dev/null 2>&1; then
    touch "$TB/uploaded"
  else
    rm -f "$TB/uploaded"; echo "TB-UPLOAD-FAILED: results.tgz to \$bucket" | tee -a "$LOG" >"$SERIAL"
  fi
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
CAP_USED=$(cat "$RUN/cap-used-s" 2>/dev/null || echo 0)
CAP_LEFT=$((MAXM * MIN_S - CAP_USED))
cat > "$SBIN/tb-boxrun-off" <<EOS
#!/bin/sh
echo "TB-WATCHDOG \$1: powering off" >"$SERIAL"
echo "TB-WATCHDOG \$1: powering off" >> "$LOG"
[ "\${2:-}" = cap ] && echo $((MAXM * MIN_S)) > "$RUN/cap-used-s"
rm -rf "$SHM"/tbk.* 2>/dev/null
[ -f "$TB/current-run" ] && timeout 120 "$SBIN/tb-boxrun-pack" "\$(cat "$TB/current-run")" "\$(cat "$TB/current-bucket" 2>/dev/null)"
systemctl poweroff
EOS
cat > "$SBIN/tb-boxrun-watchdog" <<EOS
#!/bin/sh
# every "minute": done and collected (the door), done and uploaded (the bucket: nothing is left on the VM to fetch),
# or done for \$2 minutes; no heartbeat for \$1 minutes. It keeps the cap's account across boots in \$4.
idle=\$1; grace=\$2; used0=\$3; account=\$4; t0=\$(date +%s)
while :; do
  sleep $MIN_S
  now=\$(date +%s)
  used=\$((used0 + now - t0))
  [ "\$used" -le "\$(cat "\$account" 2>/dev/null || echo 0)" ] || { echo "\$used" > "\$account.tmp" && mv -f "\$account.tmp" "\$account"; }
  if [ -f "$DONE" ]; then
    [ -f "$TB/collected" ] && exec "$SBIN/tb-boxrun-off" "done, results collected"
    [ -f "$TB/uploaded" ] && exec "$SBIN/tb-boxrun-off" "done, results in the bucket"
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
elif cmd == "begin":
    s = st["steps"].setdefault(step, {"first_started": time.time(), "attempts": 0, "boots": []})
    s["status"] = "started"; s["attempts"] += 1
    if sys.argv[4] not in s["boots"]: s["boots"].append(sys.argv[4])
    if step not in st["order"]: st["order"].append(step)
    save(st)
elif cmd == "set":
    st.setdefault("kv", {})[sys.argv[4]] = sys.argv[5]; save(st)
elif cmd == "kv":
    print(st.get("kv", {}).get(sys.argv[4], ""))
elif cmd == "ended":
    st["ended"] = sys.argv[4]; save(st)
elif cmd == "end":
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

# ------------------------------------------------------------------ the door (TLS); optional when a bucket is named
# GET /tb/progress, GET /tb/results.tgz, POST /tb/heartbeat, POST /tb/collected. The key and the TLS key come from
# Secret Manager with the VM's own service account, into root-only files. With tb-bucket the results and the
# power-cycle request go through the bucket and the driver needs no door (no firewall rule for it).
DOORP=$(md tb-door-port || echo 8443)
DSEC=$(md tb-door-secret || true); DVER=$(md tb-door-version || true)
rm -f "$TB/door-key" "$TLS/door.key"
if [ -n "$DSEC" ] && [ -n "$DVER" ]; then
  install -d -m 700 "$TLS"
  (umask 077; gcloud secrets versions access "$DVER" --secret="$DSEC" 2>/dev/null | "$PY" -c '
import json, sys
d = json.load(sys.stdin)
open(sys.argv[1], "w").write(d["key"].strip()); open(sys.argv[2], "w").write(d["tls_key"])' "$TB/door-key" "$TLS/door.key")
  (umask 022; md tb-door-cert > "$TLS/door.crt") || rm -f "$TLS/door.crt"
fi
if [ -s "$TB/door-key" ] && [ -s "$TLS/door.key" ] && [ -s "$TLS/door.crt" ]; then
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
  for _ in $(seq 1 30); do door_up 2>/dev/null && break; sleep 2; done
  door_up || { echo "TB-DOOR-FAILED: /tb/progress does not answer on port $DOORP (TLS): powering off"; systemctl poweroff; exit 1; }
  echo "TB-DOOR-UP on port $DOORP (TLS, the key checked)"
elif [ -n "$BUCKET" ]; then
  echo "TB-DOOR-OFF: results and the power-cycle request go through $BUCKET"
else
  echo "TB-NO-KEY: no bucket and no door from Secret Manager (tb-door-secret, tb-door-version, tb-door-cert); powering off"
  systemctl poweroff; exit 1
fi
pack   # a results.tgz from the first minute on

# ------------------------------------------------------------------ the settings, and what an earlier boot left
STEPS=" $( (md tb-steps || echo start) | tr ',' ' ') "
HELPER="$SBIN/tb-box-vm.py"
md tb-helper > "$HELPER.tmp" 2>/dev/null && [ -s "$HELPER.tmp" ] && mv -f "$HELPER.tmp" "$HELPER" || rm -f "$HELPER.tmp"
vm() { "$PY" "$HELPER" "$@"; }
COMMIT=$(md tb-commit || true)
VPUB_SRC=$(md tb-vendor-pub || true)
# build
SRC=$(md tb-src || true); RID=$(md tb-release-id || true); SEQ=$(md tb-release-seq || true)
KSEC=$(md tb-vendor-key-secret || true); KVER=$(md tb-vendor-key-version || true); OUTP=$(md tb-out || true)
BUILD=$(md tb-build-root || echo /srv/tb-build)
# start
BUNDLE_SRC=$(md tb-bundle || true); BUNDLE_SHA=$(md tb-bundle-sha256 || true)
BOXROOT=$(md tb-box-root || echo /opt/trialbox)
INSTALLER="$BOXROOT/deploy/box-install.sh"
ASEC=$(md tb-answers-secret || true); AVER=$(md tb-answers-version || true)
CONNECT=$(md tb-console-connect || echo 127.0.0.1:443)
CACERT=$(md tb-console-cacert || echo "$BOXROOT/deploy/secrets/tls/caddy-root.crt")
PROFILE=$(md tb-profile || echo rtxpro6000)
MODELS=$(md tb-models-root || echo /models)
JUDGE_S=$(md tb-judge-service || echo llm-service)
VERIFIER_S=$(md tb-verifier-service || echo llm-verifier)
DOCTOR_EXPECTED=$(md tb-doctor-expected || true)
QEVIDENCE=$(md tb-qualify-evidence || true)
BOXPY=$(md tb-box-python || echo python3)
# g6, g9, g10
STUDY=$(md tb-study || true)
G6N=$(md tb-g6-patients || echo 50000)
G6PROFILE=$(md tb-g6-profile || echo dense)
G9_SERVICES=$(md tb-g9-services || echo "orchestrator gateway")
OUTAGE_S=$(md tb-outage-seconds || echo 120)
REQUESTER=$(md tb-screen-requester || true)
G10_IMAGE=$(md tb-g10-vllm-image || true)
G10_BUNDLE=$(md tb-g10-bundle || true); G10_SHA=$(md tb-g10-bundle-sha256 || true)
ISSUE="${TB_ISSUE_DIR:-/etc/issue.d}/trialbox-firstrun.issue"
BUNDLE="$TB/bundle/$RUN_ID.tar"
ANSWERS="$TB/wizard-answers"
REC="$RUN/records"

ENDED=$(st get _ended)
if [ -n "$ENDED" ]; then  # this run already ended (a stop, or all steps): hand over its results, repeat nothing
  echo "TB-RUN-ENDED-BEFORE: $ENDED" | tee -a "$LOG"; phase ended
  pack; touch "$DONE"; echo BOX-RUN-DONE; exit 0
fi
[ "$CAP_LEFT" -gt 0 ] || finish "TB-CAP-REACHED: the $MAXM minutes of this run are used ($CAP_USED s over its boots)" cap-reached

has() { case "$STEPS" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
pf=""
for s in $STEPS; do case "$s" in build|start|g6|g9|g10) ;; *) pf="$pf; unknown group '$s' in tb-steps" ;; esac; done
[ -s "$HELPER" ] || pf="$pf; no tb-helper (deploy/gcp/box_vm.py)"
for c in "$PY" curl tar sha256sum; do command -v "$c" >/dev/null || pf="$pf; no $c"; done
if has build; then
  for c in git make docker; do command -v "$c" >/dev/null || pf="$pf; no $c (build)"; done
  for v in SRC COMMIT RID SEQ KSEC KVER VPUB_SRC OUTP; do [ -n "${!v}" ] || pf="$pf; no ${v} (build metadata)"; done
fi
if has start || has g6 || has g9 || has g10; then
  for c in docker nvidia-smi; do command -v "$c" >/dev/null || pf="$pf; no $c"; done
  [ -d "$MODELS" ] || pf="$pf; no model folders at $MODELS"
fi
if has start; then
  [ -n "$BUNDLE_SRC" ] || pf="$pf; no tb-bundle"
  [ -n "$BUNDLE_SHA" ] || pf="$pf; no tb-bundle-sha256 (a bundle is never installed unchecked)"
  [ -n "$VPUB_SRC" ] || pf="$pf; no tb-vendor-pub (the installer refuses a bundle without the vendor's public key)"
  { [ -n "$ASEC" ] && [ -n "$AVER" ]; } || pf="$pf; no tb-answers-secret / tb-answers-version (the wizard's answers)"
fi
[ "$(echo $G9_SERVICES | wc -w)" -le 5 ] || pf="$pf; at most five tb-g9-services (steps 32 to 36)"
{ has g6 || has g9; } && [ -z "$STUDY" ] && pf="$pf; no tb-study (the approved study G-6 and G-9 screen)"
has g10 && [ -z "$G10_IMAGE" ] && pf="$pf; no tb-g10-vllm-image (G-10 names its image)"
[ -z "$pf" ] || finish "TB-PREFLIGHT-FAILED${pf}" preflight-failed
echo "TB-PREFLIGHT ok: groups$STEPS"

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
run_step() {  # run_step <name> <function> [args]: once per run, timed, a part result, a STOP ends the run
  local name=$1 fn=$2 rc; shift 2
  case "$(st get "$name")" in
    done) echo "TB-STEP $name kept (finished before; not run again)" | tee -a "$LOG"; return 0 ;;
    stop) finish "TB-STOP $name (recorded before; not run again)" stopped ;;
  esac
  STEP=$name; STEP_LOG="$RUN/logs/$name.log"; NOTES="$RUN/logs/$name.notes"; STOP=""
  : > "$NOTES"
  phase "$name"; touch "$HB"
  st begin "$name" "$BOOT_ID"
  echo "TB-STEP $name start $(date -u +%FT%TZ)" | tee -a "$LOG"
  "$fn" "$@"; rc=$?
  if [ "$rc" = 0 ] && [ -z "$STOP" ]; then
    st end "$name" "done" "$NOTES" "" "$STEP_LOG"
    echo "TB-STEP $name done" | tee -a "$LOG"; pack; return 0
  fi
  st end "$name" stop "$NOTES" "${STOP:-exit $rc}" "$STEP_LOG"
  finish "TB-STOP $name: ${STOP:-exit $rc}" stopped
}
jget() { "$PY" -c 'import json,sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$1" "$2" 2>/dev/null; }
fetch() {  # fetch <gs:// or path> <dest>
  case "$1" in gs://*) gcloud storage cp "$1" "$2" ;; *) cp "$1" "$2" ;; esac
}

# ------------------------------------------------------------------ the box: one function per call (train 17)
dc() { docker compose --project-directory "$BOXROOT/deploy" "$@"; }   # COMPOSE_FILE/PROFILES: install.sh's .env
box_tool() { (cd "$BOXROOT" && PYTHONPATH="$BOXROOT/libs:$BOXROOT" exec "$BOXPY" -m "tools.$1" "${@:2}"); }
in_svc() { dc exec -T "$1" python -; }   # a snippet on stdin in a service's container (as make rehearse-box does)
d_install()  { "$INSTALLER" "$1" --prepare --yes; }
d_firstrun() { "$INSTALLER" --firstrun; }                                     # waits for the owner's answers
d_pin()      { box_tool pin_model --install "$PROFILE" --models-root "$MODELS"; }
d_qualify()  { box_tool trialbox eval qualify --profile "$PROFILE" --out "$@"; }   # [--evidence step=file ...]
d_weights()  { box_tool pin_model --verify-all "$MODELS"; }
d_cmd()      { docker inspect --format '{{json .Config.Cmd}}' "$1"; }
d_sha_in()   { dc exec -T "$1" sha256sum "$2"; }                              # a file inside a service's container
d_digests()  { docker image inspect --format '{{json .RepoDigests}}' "$1"; }
d_identity() { in_svc orchestrator <<'EOF'
# tb-boxrun: identity
import json, yaml
from tb_llm.prompt_registry import default_registry
reg = yaml.safe_load(open("/app/models/registry.yaml", encoding="utf-8"))
builds = [{"build_id": b.get("build_id"), "alias": b.get("alias"), "status": b.get("status"),
           "manifest_sha256": (b.get("expected") or {}).get("manifest_sha256"),
           "revision": (b.get("expected") or {}).get("revision"),
           "chat_template_sha256": (b.get("chat_template") or {}).get("sha256")}
          for b in reg.get("builds") or [] if str(b.get("build_id", "")).endswith("-rtxpro6000")]
served = [{"id": e.id, "version": e.version, "sha256": getattr(e, "sha256", None)}
          for e in default_registry().served_set("PRODUCTION")]
print(json.dumps({"builds": builds, "served_prompts": served}))
EOF
}
d_promote()  { box_tool pin_model --promote "$1" --record "$2" --environment PRODUCTION; }
d_resolve()  { box_tool pin_model --resolve --environment PRODUCTION; }       # {"judge": {"build", "promoted"}, ...}
d_capture()  { box_tool serving_config capture --container "judge=$1" --container "verifier=$2" \
                 --models-dir "$MODELS" --notes "$PROFILE profile: box run $RUN_ID" --out "$3"; }
d_doctor()   { box_tool trialbox doctor --live --json --env-file "$BOXROOT/deploy/.env"; }
d_healthy()  { dc ps --format '{{.Service}} {{.State}} {{.Health}}' | awk '$2 != "running" || ($3 != "" && $3 != "healthy") {bad=1} END {exit bad}'; }
d_canary()   { box_tool trialbox selftest --deploy "$BOXROOT/deploy"; }
d_update()   { (cd "$BOXROOT" && tools/apply_update.sh "$1"); }
d_backup()   { box_tool trialbox backup-nightly --deploy "$BOXROOT/deploy"; }
d_feed()     { docker run --rm --network none -v "$1:/out" "$(img_py)" python -c "$GEN_FEED" "$G6N" /out/site 2026-10-04 "$G6PROFILE"; }
d_ingest()   { dc exec -T adapter python -m adapter.cli run --source csv --path "$1" --snapshot "$2"; }
d_current()  { dc exec -T lake cat /data/lake/CURRENT; }
d_study_ready() { in_svc console <<EOF
# tb-boxrun: study-ready
import httpx, sys
from tb_common.service_auth import auth_headers
r = httpx.get("http://orchestrator:8010/rulesets/$1", headers=auth_headers(), timeout=60)
print(r.status_code, r.text[:300]); sys.exit(0 if r.status_code == 200 else 1)
EOF
}
d_screen_start() { in_svc mail-gateway <<EOF
# tb-boxrun: screen-start
import time, httpx
from tb_common.service_auth import auth_headers
body = {"type": "SCREEN", "ruleset": "$1", "comment": "box run $RUN_ID $2", "requested_by": "$REQUESTER",
        "message_id": "<boxrun-$RUN_ID-$2-%d@trialbox.invalid>" % time.time()}
r = httpx.post("http://orchestrator:8010/jobs", json=body, headers=auth_headers(), timeout=60)
assert r.status_code == 200, f"POST /jobs: {r.status_code} {r.text[:300]}"
print(r.json()["job_id"])
EOF
}
d_screen_status() { in_svc mail-gateway <<EOF
# tb-boxrun: screen-status $1
import json, httpx
from tb_common.service_auth import auth_headers
j = httpx.get("http://orchestrator:8010/jobs/$1", headers=auth_headers(), timeout=60).json()
print(json.dumps({"state": j.get("state"), "error": j.get("error"), "metrics": {k: v for k, v in (j.get("metrics") or {}).items() if not isinstance(v, (dict, list))}}))
EOF
}
d_candidates() { in_svc orchestrator <<EOF
# tb-boxrun: candidates $1
import json
from orchestrator.app import orch
o = orch(); job = o.db.get("$1")
rows = []
for f in job.outputs or []:
    if f.filename.startswith("candidate_list_") and f.filename.endswith(".json"):
        rows += [{"pid": r.get("pid"), "tier": r.get("tier")} for r in json.loads(o.store.get(f.minio_key)).get("rows") or []]
print(json.dumps({"job": "$1", "rows": rows}))
EOF
}
# the scale gate's generator (tools/scale_gate.py CHILD_GENERATE): the synthetic hospital, thickened when dense
GEN_FEED='
import json, sys
from datetime import date
from pathlib import Path
from tools.make_fixtures import write_site
from tools.synth.generator import generate
n, out, ref, profile = int(sys.argv[1]), Path(sys.argv[2]), date.fromisoformat(sys.argv[3]), sys.argv[4]
if profile == "dense":
    from tb_testkit.scale import densify
    thin = out.with_name(out.name + "-thin")
    write_site(generate(42, "DEMO-A", ref, n, "1"), thin)
    print(json.dumps(densify(thin, out)))
else:
    write_site(generate(42, "DEMO-A", ref, n, "1"), out)
'
img_py() { sed -n 's/^TB_IMAGE=//p' "$BOXROOT/deploy/.env" 2>/dev/null | tail -1 | grep . || echo trialbox-py:1.0.0; }
envget() { sed -n "s/^$1=//p" "$BOXROOT/deploy/.env" 2>/dev/null | tail -1; }

# ================================================================== build (R2, the runner VM)
CK="$BUILD/tb/trialbox"
step_b_source() {
  mkdir -p "$BUILD"; rm -rf "$BUILD/tb"
  need "fetching the release commit's git bundle" fetch "$SRC" "$BUILD/src.bundle" || return 1
  need "cloning it" git clone -q "$BUILD/src.bundle" "$BUILD/tb" || return 1
  need "checking out $COMMIT" git -C "$BUILD/tb" checkout -q --detach "$COMMIT" || return 1
  [ "$(git -C "$BUILD/tb" rev-parse HEAD)" = "$COMMIT" ] || { STOP="HEAD is not $COMMIT"; return 1; }
  note commit "\"$COMMIT\""
}
step_b_make() { need "make $*" make -C "$CK" "$@"; }
step_b_gates() {
  need "make trivy-db" make -C "$CK" trivy-db || return 1
  # enforcing (no --vuln-mode report): a FAIL here stops the build, and the vendor key is never read
  if ! watched make -C "$CK" release-gates; then
    STOP="TB-GATES-FAILED: make release-gates did not pass (enforcing): $(grep -a '^FAIL' "$STEP_LOG" | head -3 | tr '\n' ' ')"
    return 1
  fi
  note gates "\"build/supply-chain/gates.json\""
}
d_sign() {  # the key lives only inside this function's process: tmpfs, 0600, shredded on every way out
  local k
  k=$(mktemp -d "$SHM/tbk.XXXXXX") || return 1
  chmod 700 "$k"
  trap 'shred -u "$k/vendor.key" 2>/dev/null; rm -rf "$k"' EXIT INT TERM
  ( umask 077; gcloud secrets versions access "$KVER" --secret="$KSEC" --out-file="$k/vendor.key" >/dev/null 2>&1 ) \
    || { echo "TB-NO-VENDOR-KEY: secret $KSEC version $KVER is not readable by this VM's service account"; return 3; }
  chmod 600 "$k/vendor.key"
  (cd "$CK" && tools/make_bundle.sh --key "$k/vendor.key" --id "$RID" --release-seq "$SEQ" \
     --out "$BUILD/out/trialbox-$RID.tar" --gates build/supply-chain/gates.json --sbom-dir dist/sbom)
}
step_b_sign() {
  mkdir -p "$BUILD/out"
  need "signing the bundle (tools/make_bundle.sh with the vendor key)" d_sign; local rc=$?
  rm -rf "$SHM"/tbk.* 2>/dev/null
  note key_left_on_tmpfs "$(ls -d "$SHM"/tbk.* >/dev/null 2>&1 && echo true || echo false)"
  return $rc
}
step_b_verify() {
  local b="$BUILD/out/trialbox-$RID.tar"
  need "fetching the vendor public key" fetch "$VPUB_SRC" "$BUILD/vendor.pub" || return 1
  rm -rf "$BUILD/verify-stage"
  need "tools/verify_update.py (the Ed25519 signature with the vendor public key)" \
    "$CK/.venv/bin/python" "$CK/tools/verify_update.py" "$b" --pubkey "$BUILD/vendor.pub" --stage "$BUILD/verify-stage" || return 1
  rm -rf "$BUILD/verify-stage"
  need "TB-BUNDLE-REFUSED: the release record as a PRODUCTION box reads it" \
    vm bundle-check "$b" --production --commit "$COMMIT" --notes "$NOTES" --beat "$HB" || return 1
}
step_b_upload() {
  local b="$BUILD/out/trialbox-$RID.tar" sha
  sha=$(sha256sum "$b" | cut -d' ' -f1); printf '%s  %s\n' "$sha" "trialbox-$RID.tar" > "$b.sha256"
  need "uploading the bundle" gcloud storage cp "$b" "$OUTP/trialbox-$RID.tar" || return 1
  need "uploading its sha256" gcloud storage cp "$b.sha256" "$OUTP/trialbox-$RID.tar.sha256" || return 1
  printf '{"release_id": "%s", "release_seq": %s, "commit": "%s", "sha256": "%s", "bytes": %s, "object": "%s"}\n' \
    "$RID" "$SEQ" "$COMMIT" "$sha" "$(stat -c %s "$b")" "$OUTP/trialbox-$RID.tar" > "$REC/bundle.json"
  note sha256 "\"$sha\""; note object "\"$OUTP/trialbox-$RID.tar\""
}

# ================================================================== start (G-2)
step_bundle() {
  local size free got
  mkdir -p "$TB/bundle"
  need "fetching the bundle" fetch "$BUNDLE_SRC" "$BUNDLE" || return 1
  size=$(stat -c %s "$BUNDLE"); note bundle_bytes "$size"
  got=$(sha256sum "$BUNDLE" | cut -d' ' -f1)
  [ "$got" = "$BUNDLE_SHA" ] || { STOP="TB-BUNDLE-REFUSED: sha256 ${got:0:16}... is not the declared ${BUNDLE_SHA:0:16}..."; return 1; }
  touch "$HB"
  [ ! -e "$BOXROOT/deploy/updates/installed.json" ] \
    || { STOP="an installed box is already at $BOXROOT: a production start needs a fresh root (tb-box-root)"; return 1; }
  # the installer's room: the bundle again (its image tars are loaded from it) and the host tree, from the data
  free=$(df -B1 --output=avail "$TB" | tail -n 1 | tr -dc 0-9)
  note free_bytes "${free:-0}"
  [ "${free:-0}" -gt "$size" ] || { STOP="${free:-0} bytes free under $TB, the install needs at least the bundle's $size"; return 1; }
  need "TB-BUNDLE-REFUSED: the bundle against its manifest and as a PRODUCTION box reads it" \
    vm bundle-check "$BUNDLE" --production ${COMMIT:+--commit "$COMMIT"} --release-out "$REC/release.json" \
      --host-out "$TB/bundle/host.tar" --notes "$NOTES" --beat "$HB" || return 1
  mkdir -p "$BOXROOT"
  need "unpacking the signed host tree as the installer's bootstrap" tar -xf "$TB/bundle/host.tar" -C "$BOXROOT" || return 1
  rm -f "$TB/bundle/host.tar"
  mkdir -p "$BOXROOT/deploy/keys"
  need "fetching the vendor public key" fetch "$VPUB_SRC" "$BOXROOT/deploy/keys/vendor_ed25519.pub" || return 1
  note vendor_pub_sha256 "\"$(sha256sum "$BOXROOT/deploy/keys/vendor_ed25519.pub" | cut -d' ' -f1)\""
}
step_install() {
  [ -x "$INSTALLER" ] || { STOP="no installer at $INSTALLER in the bundle's host tree: a person would need a shell"; return 1; }
  need "the installer" d_install "$BUNDLE"
}
step_wizard() {
  local pid rc
  (umask 077; gcloud secrets versions access "$AVER" --secret="$ASEC" > "$ANSWERS" 2>/dev/null) && [ -s "$ANSWERS" ] \
    || { STOP="no wizard answers in Secret Manager (tb-answers-secret, tb-answers-version)"; return 1; }
  systemctl stop trialbox-firstrun.service >/dev/null 2>&1   # a boot's own first run (enabled by --prepare): one at a time
  rm -f "$ISSUE"
  echo "+ box-install.sh --firstrun (background) $(date -u +%T)" >> "$STEP_LOG"
  d_firstrun >> "$RUN/logs/firstrun.log" 2>&1 < /dev/null &
  pid=$!
  # the code is on the box's screen once the installer shows it; a box whose answers were applied before shows none
  watched vm wizard --issue "$ISSUE" --answers "$ANSWERS" --connect "$CONNECT" --cacert "$CACERT" \
    --wait $((HEALTHM * MIN_S)) --notes "$NOTES" &
  local wpid=$! wrc=""
  while kill -0 "$pid" 2>/dev/null; do
    if [ -z "$wrc" ] && ! kill -0 "$wpid" 2>/dev/null; then
      wait "$wpid"; wrc=$?
      if [ "$wrc" != 0 ]; then   # the installer would wait for answers that will never come
        kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; rm -f "$ANSWERS"
        cat "$RUN/logs/firstrun.log" >> "$STEP_LOG"
        STOP="the wizard's answers were not taken (box_vm.py wizard exit $wrc; the log says which fields)"; return 1
      fi
    fi
    touch "$HB"; sleep "$POLL"
  done
  wait "$pid"; rc=$?
  [ -n "$wrc" ] || { kill "$wpid" 2>/dev/null; wait "$wpid" 2>/dev/null; }
  rm -f "$ANSWERS"
  cat "$RUN/logs/firstrun.log" >> "$STEP_LOG"
  note installer_exit "$rc"
  grep -q "TrialBox is ready" "$RUN/logs/firstrun.log" \
    || { STOP="the first run did not finish (box-install.sh --firstrun exit $rc)"; return 1; }
  note host_check_exit "$rc"   # the installer's last line is the host check: judged by 10-doctor, not here
}
QREC="$REC/qualification.json"
step_pin() { need "pinning the $PROFILE pair from $MODELS" d_pin; }
step_g1() {
  local jc tpl sha s img wrc
  jc=$(cid "$JUDGE_S")
  tpl=$(vm cmd-arg "$(d_cmd "$jc" 2>> "$STEP_LOG")" --flag=--chat-template)
  note judge_chat_template "\"$tpl\""
  sha=""
  [ -z "$tpl" ] || sha=$(d_sha_in "$JUDGE_S" "$tpl" 2>> "$STEP_LOG" | cut -d' ' -f1)
  d_identity > "$REC/identity-box.json" 2>> "$STEP_LOG" || { STOP="the box's registry and served prompts cannot be read"; return 1; }
  printf '{' > "$RUN/logs/images.json"
  for s in "$JUDGE_S" "$VERIFIER_S"; do
    img=$(docker inspect --format '{{.Config.Image}}' "$(cid "$s")" 2>> "$STEP_LOG")
    printf '"%s": {"ref": "%s", "repo_digests": %s},' "$s" "$img" "$(d_digests "$img" 2>> "$STEP_LOG" || echo '[]')" >> "$RUN/logs/images.json"
  done
  sed -i 's/,$/}/' "$RUN/logs/images.json"
  watched d_weights; wrc=$?
  vm identity --box "$REC/identity-box.json" --lock "$BOXROOT/deploy/images.lock" --template-sha "$sha" \
    --images "$RUN/logs/images.json" --weights-exit "$wrc" --notes "$NOTES" > "$REC/identity.json"
}
step_canary() { watched d_canary; local rc=$?; note canary_exit "$rc"; [ "$rc" = 0 ] && note pass true || note pass false; }
step_qualify() {
  local args=() e
  for e in $QEVIDENCE; do   # step=gs://...: the evidence results qualify reads (fetched, named in the part)
    mkdir -p "$TB/evidence"
    need "fetching qualify evidence ${e%%=*}" fetch "${e#*=}" "$TB/evidence/${e%%=*}.json" || return 1
    args+=(--evidence "${e%%=*}=$TB/evidence/${e%%=*}.json")
  done
  note evidence "\"${QEVIDENCE:-none}\""
  need "the full qualification" d_qualify "$QREC" "${args[@]}" || return 1
  [ -s "$QREC" ] || { STOP="the qualification wrote no record"; return 1; }
}
step_promote() {
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
cid() { dc ps -q "$1" 2>/dev/null | head -n 1; }
wsl_kernel_into() {  # $1 a serving record; [$2 /proc/version, $3 the release]: wsl_kernel, the kernel when WSL2, else null
  "${PY:-python3}" - "$1" "${2:-/proc/version}" "${3:-$(uname -r)}" <<'WSLPY'
import json, os, re, sys
rec_path, version_file, release = sys.argv[1], sys.argv[2], sys.argv[3].strip()
if os.path.isfile(rec_path):
    try:
        text = open(version_file, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    rec = json.load(open(rec_path, encoding="utf-8"))
    rec["wsl_kernel"] = release if re.search(r"microsoft|wsl2", f"{text} {release}", re.I) else None
    with open(rec_path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1)
    os.replace(rec_path + ".tmp", rec_path)
WSLPY
}
step_serving() {
  local s c pid
  need "the serving capture" d_capture "$(cid "$JUDGE_S")" "$(cid "$VERIFIER_S")" "$REC/serving_config.json" || return 1
  wsl_kernel_into "$REC/serving_config.json" >> "$STEP_LOG" 2>&1 || true
  for s in "$JUDGE_S" "$VERIFIER_S"; do
    c=$(cid "$s")
    pid=$(docker inspect --format '{{.State.Pid}}' "$c" 2>> "$STEP_LOG")
    [ -n "$pid" ] && [ "$pid" != 0 ] || { STOP="no running container of service '$s'"; return 1; }
    note "host_rss_kib_$s" "$("$PY" - "$pid" <<'PY'
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
step_doctor() {
  d_doctor > "$REC/doctor.json" 2>> "$STEP_LOG"; note doctor_exit $?
  [ -s "$REC/doctor.json" ] || { STOP="trialbox doctor --json wrote nothing"; return 1; }
  vm doctor-verdict "$REC/doctor.json" --expected "$(echo $DOCTOR_EXPECTED | tr ' ' ,)" --notes "$NOTES" >> "$STEP_LOG" 2>&1 \
    && note pass true || note pass false
}

# ================================================================== the screens (G-6, G-9)
job_status() { d_screen_status "$1" > "$RUN/logs/job-status.json" 2>> "$STEP_LOG"; }
job_state() { jget "$RUN/logs/job-status.json" state; }
wait_job() {  # wait_job <id> running|ended: the job's own progress is the heartbeat (a stuck one: the watchdog)
  local id=$1 want=$2 last=""
  while :; do
    job_status "$id" || { STOP="the screen's status cannot be read"; return 1; }
    [ "$(cat "$RUN/logs/job-status.json")" = "$last" ] || { touch "$HB"; last=$(cat "$RUN/logs/job-status.json"); }
    case "$want:$(job_state)" in
      running:running|ended:done|ended:failed|ended:cancelled|ended:rejected) return 0 ;;
      running:done|running:failed|running:cancelled|running:rejected)
        STOP="the screen is '$(job_state)' before the interruption: it must be running (a larger study pool)"; return 1 ;;
    esac
    sleep "$POLL"
  done
}
screen_to_end() {  # screen_to_end <tag> <candidates file>: start, wait, keep the list; the job's state is noted
  local id
  id=$(d_screen_start "$STUDY" "$1" 2>> "$STEP_LOG" | tail -n 1) && [ -n "$id" ] || { STOP="the screen did not start as a job of the box"; return 1; }
  note job "\"$id\""; st set "$STEP" "job_$1" "$id"
  wait_job "$id" ended || return 1
  note job_state "\"$(job_state)\""
  d_candidates "$id" > "$2" 2>> "$STEP_LOG" || { STOP="the candidate list of job $id cannot be read"; return 1; }
  note candidates "$("$PY" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["rows"]))' "$2")"
}
profiled() {  # profiled <services> <command...>: the command watched, the services' memory sampled; rc is noted
  local svcs=$1 s rc; shift
  : > "$RUN/logs/$STEP.ids"
  for s in $svcs; do printf '%s\t%s\n' "$s" "$(cid "$s")" >> "$RUN/logs/$STEP.ids"; done
  rm -f "$RUN/logs/$STEP.stop" "$RUN/logs/$STEP.mem"
  vm sample --names "$(echo $svcs | tr ' ' ,)" --ids "$RUN/logs/$STEP.ids" --out "$RUN/logs/$STEP.mem" \
    --stop "$RUN/logs/$STEP.stop" --interval 1 --cgroup-root "$CGROOT" &
  local spid=$!
  "$@"; rc=$?
  touch "$RUN/logs/$STEP.stop"; wait "$spid"
  note memory "$(vm stage-memory "$RUN/logs/$STEP.mem")"
  note exit "$rc"
  return "$rc"
}
G6_SNAP=2026-10-04
step_g6_study() { need "the approved study $STUDY on this box (D-640: a PRODUCTION box starts with none)" d_study_ready "$STUDY"; }
step_g6_feed() {
  local feed; feed=$(envget TB_SOURCE_DIR)
  [ -n "$feed" ] || { STOP="no feed folder (TB_SOURCE_DIR in deploy/.env)"; return 1; }
  case "$feed" in /*) ;; *) feed="$BOXROOT/deploy/$feed" ;; esac
  note feed "\"$feed\""; note patients "$G6N"; note profile "\"$G6PROFILE\""
  need "generating the synthetic feed (the scale gate's generator, in the box's image)" d_feed "$feed"
}
g6_stage() {  # g6_stage <services> <command...>: a stage of the night; its failure is a fact (pass false), not a stop
  if profiled "$@"; then note pass true; else note pass false; fi
  local ooms; ooms=$("$PY" -c 'import json,sys
m = json.loads(sys.argv[1]); print(sum(c.get("oom_kills") or 0 for c in m["containers"].values()))' "$(sed -n 's/^memory\t//p' "$NOTES")" 2>/dev/null)
  note oom_kills "${ooms:-null}"
  return 0
}
step_g6_ingest() {
  st set "$STEP" g6_current "$(d_current 2>/dev/null)"
  g6_stage "adapter lake" d_ingest "$(envget TB_SOURCE_MOUNT | grep . || echo /data/source/site-a)/site" "$G6_SNAP"
}
rebuilt() {  # until the lake's CURRENT moves from what it was before the ingest (the publish), heartbeats meanwhile
  local before; before=$(st kv _ g6_current)
  while [ "$(d_current 2>/dev/null)" = "$before" ]; do touch "$HB"; sleep "$POLL"; done
  echo "CURRENT now $(d_current 2>/dev/null)"
}
step_g6_rebuild() {
  # after an ingest that did not end (T-692's OOM kill), no publish is coming: the stage is recorded as blocked
  if [ "$(jget "$RUN/parts/22-g6-ingest.json" pass)" != True ]; then
    note blocked_by "\"22-g6-ingest did not end: no new snapshot to rebuild\""; note pass false; return 0
  fi
  g6_stage "lake orchestrator" rebuilt
}
step_g6_screen() { g6_stage "orchestrator gateway lake $JUDGE_S $VERIFIER_S" screen_to_end g6 "$REC/g6-candidates.json"; }
step_g6_backup() { g6_stage "db" d_backup; }
step_g6_result() {
  vm top-costs "$RUN/parts" > "$REC/g6-top-costs.json" 2>> "$STEP_LOG"
  note top_costs "$(cat "$REC/g6-top-costs.json")"
  local ok=true p
  for p in "$RUN"/parts/*-g6-ingest.json "$RUN"/parts/*-g6-rebuild.json "$RUN"/parts/*-g6-screen.json "$RUN"/parts/*-g6-backup.json; do
    [ "$(jget "$p" pass)" = True ] || ok=false
  done
  note t692 "\"T-692: the ingest needs 16 to 17 GB (scale review) against the adapter's cap; see g6-ingest's memory and oom_kills\""
  note pass "$ok"
}
step_g9_baseline() {
  if [ -s "$REC/g6-candidates.json" ]; then
    cp "$REC/g6-candidates.json" "$REC/g9-baseline.json"; note baseline "\"G-6's screen\""; return 0
  fi
  screen_to_end baseline "$REC/g9-baseline.json"
}
step_g9_screen() {
  local id
  id=$(d_screen_start "$STUDY" g9 2>> "$STEP_LOG" | tail -n 1) && [ -n "$id" ] || { STOP="the screen did not start as a job of the box"; return 1; }
  st set "$STEP" g9_job "$id"; note job "\"$id\""
  wait_job "$id" running
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
after() { job_status "$(st kv _ g9_job)" || { STOP="the screen's status cannot be read"; return 1; }; note job_state "\"$(job_state)\""; }
step_g9_restart() {
  local t0; wait_job "$(st kv _ g9_job)" running || return 1
  t0=$(date +%s)
  need "docker compose restart $1" dc restart "$1" || return 1
  wait_healthy "$t0" && after
}
step_g9_outage() {
  local t0; wait_job "$(st kv _ g9_job)" running || return 1
  t0=$(date +%s)
  need "stopping the judge's model server ($JUDGE_S)" dc stop "$JUDGE_S" || return 1
  local end=$((t0 + OUTAGE_S)); while [ "$(date +%s)" -lt "$end" ]; do touch "$HB"; sleep "$POLL"; done
  note outage_seconds "$OUTAGE_S"
  need "starting it again" dc start "$JUDGE_S" || return 1
  wait_healthy "$t0" && after
}
step_g9_power() {
  local t0
  if [ "$(st kv _ g9_power_boot)" = "" ]; then   # first pass: ask for the power cycle and wait to be stopped
    wait_job "$(st kv _ g9_job)" running || return 1
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
  note boot_before "\"$(st kv _ g9_power_boot)\""; note boot_after "\"$BOOT_ID\""
  wait_healthy "$BOOT_T0" && after                # from this boot's start: nobody signs in, nobody starts a thing
}
step_g9_result() {
  local id; id=$(st kv _ g9_job)
  wait_job "$id" ended || return 1
  cp "$RUN/logs/job-status.json" "$REC/g9-job-final.json"
  note final_job_state "\"$(job_state)\""
  d_candidates "$id" > "$REC/g9-candidates.json" 2>> "$STEP_LOG" || { STOP="the candidate list of job $id cannot be read"; return 1; }
  vm compare-lists "$REC/g9-baseline.json" "$REC/g9-candidates.json" > "$REC/g9-compare.json"
  note compare "$(cat "$REC/g9-compare.json")"
  [ "$(job_state)" = "done" ] && [ "$(jget "$REC/g9-compare.json" equal)" = True ] && note pass true || note pass false
}

# ================================================================== G-10
step_g10_update() {
  local b="$TB/bundle/g10.tar" got
  need "fetching the update bundle" fetch "$G10_BUNDLE" "$b" || return 1
  got=$(sha256sum "$b" | cut -d' ' -f1)
  [ "$got" = "$G10_SHA" ] || { STOP="TB-BUNDLE-REFUSED: the update bundle's sha256 is not the declared one"; return 1; }
  need "TB-BUNDLE-REFUSED: the update bundle as a PRODUCTION box reads it" vm bundle-check "$b" --production --notes "$NOTES" --beat "$HB" || return 1
  need "tools/apply_update.sh (the box's update path)" d_update "$b"
}
step_g10_image() {
  local s img
  for s in "$JUDGE_S" "$VERIFIER_S"; do
    img=$(docker inspect --format '{{.Config.Image}}' "$(cid "$s")" 2>> "$STEP_LOG")
    note "image_$s" "\"$img\""
    [ "$img" = "$G10_IMAGE" ] \
      || { STOP="'$s' runs on '$img', G-10 is declared for '$G10_IMAGE' (tb-g10-vllm-image): the image comes by a bundle (tb-g10-bundle), never by hand"; return 1; }
  done
}
step_g10_canary() { watched d_canary; local rc=$?; note canary_exit "$rc"; [ "$rc" = 0 ] && note pass true || note pass false; }
step_g10_qualify() {
  watched d_qualify "$REC/qualification-g10.json"; local rc=$?
  note qualify_exit "$rc"; note passed "\"$(jget "$REC/qualification-g10.json" passed)\""
  [ "$rc" = 0 ] && [ "$(jget "$REC/qualification-g10.json" passed)" = True ] && note pass true || note pass false
}

# ------------------------------------------------------------------ the run
if has build; then
  run_step b01-source step_b_source
  run_step b02-venv step_b_make venv scanners
  run_step b03-images step_b_make images
  run_step b04-gates step_b_gates
  run_step b05-sign step_b_sign
  run_step b06-verify step_b_verify
  run_step b07-upload step_b_upload
fi
if has start; then
  run_step 01-bundle step_bundle
  run_step 02-install step_install
  run_step 03-wizard step_wizard
  run_step 04-pin step_pin
  run_step 05-serving step_serving
  run_step 06-g1 step_g1
  run_step 07-canary step_canary
  run_step 08-qualify step_qualify
  run_step 09-promote-judge step_promote judge
  run_step 10-promote-verifier step_promote verifier
  run_step 11-resolve step_resolve
  run_step 12-doctor step_doctor
fi
if has g6; then
  run_step 20-g6-study step_g6_study
  run_step 21-g6-feed step_g6_feed
  run_step 22-g6-ingest step_g6_ingest
  run_step 23-g6-rebuild step_g6_rebuild
  run_step 24-g6-screen step_g6_screen
  run_step 25-g6-backup step_g6_backup
  run_step 26-g6-result step_g6_result
fi
if has g9; then
  has g6 || run_step 20-g6-study step_g6_study
  run_step 30-g9-baseline step_g9_baseline
  run_step 31-g9-screen step_g9_screen
  n=31; for s in $G9_SERVICES; do n=$((n + 1)); run_step "$n-g9-restart-$s" step_g9_restart "$s"; done
  run_step 37-g9-outage step_g9_outage
  run_step 38-g9-power step_g9_power
  run_step 39-g9-result step_g9_result
fi
if has g10; then
  [ -z "$G10_BUNDLE" ] || run_step 40-g10-update step_g10_update
  run_step 41-g10-image step_g10_image
  run_step 42-g10-canary step_g10_canary
  run_step 43-g10-qualify step_g10_qualify
fi
finish "TB-BOX-RUN-COMPLETE: every step ran; the parts say which test rules passed" complete 0
