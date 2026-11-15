#!/bin/bash
# TrialBox box run ON the cloud GPU VM (plan v7 section 7.1; R2 of lane G; tests G-2, G-6, G-9, G-10; gap X-10 of the
# GCP test plan). The VM's startup script for the run (as complete-run-vm.sh is for the complete run). The driver is
# deploy/gcp/box-run.sh; nobody runs this by hand. GCE runs a startup script at every boot, so a power cycle or a
# pre-emption resumes here by itself. Fail-safe in the same three ways as the complete run: a cost cap, a watchdog,
# and results that leave the VM after every step (the bucket, and the door when there is no bucket).
#
# Groups of steps, chosen by the metadata tb-steps (one or more of: build start g6 g9 g10 acc, in this order). Each step
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
#   acc    the public accuracy run on the installed box (public-accuracy-run-plan.md, Run A by default; the sets of
#          tb-acc-sets, "name:size" each), lane G's tools from tb-acc-tools (a git archive at the driver's commit):
#     50-acc-tools     the tools unpacked on the VM (never into the box)
#     51-acc-settings  the site settings the run needs, each recorded before and after: the declared
#                      TB_JOBS_PER_SENDER_PER_DAY=0 (D-775) and TB_MAIL_PER_RECIPIENT_PER_DAY=0 (the answers' env_extra
#                      sets both; a box without them gets them here), TB_MAIL_AUTHSERV_ID only when the box has none
#                      (the answers' mta_authserv_id writes it, D-825); the
#                      tripwire: tb-acc-tripwire-setting NAME=VALUE only when NAME is a declared setting of this
#                      tree, else it stays on and the record says so. Then the stack recreated on them
#     52-acc-routes    would the box route the compile's and the screen's calls in its environment (the gateway's own
#                      policy and registry), which prompt versions it serves there, which embedder SCREEN ranks with,
#                      the serving record again: a box that routes neither stops HERE (no hours spent on refusals)
#     53-acc-data      tools.public_accuracy fetch (the pins) and build --for-box --ref <the box's day> per set, with
#                      the VM's python3 (standard library; JMED's parquet in the box's image, offline), outside the
#                      box; the gold stays out
#     54-acc-ingest    the sets' hospital CSVs merged into the box's feed folder (acc/), the box's ingest, the publish
#     60.. acc-<set>   per set, box_vm.py acc-set: FEAS by mail with the protocol, the review workbook, APPROVE by the
#                      box's named reviewer, SCREEN pract=<the trial's investigator>, the lists, the pseudonym map;
#                      then the set (gold, answers, per-protocol record, the gateway's audit summary) uploaded to
#                      tb-bucket boxruns/<run>/acc/<set>.tgz at once: a pre-emption loses at most the set in hand,
#                      and that set resumes protocol by protocol. Scored outside the box (box-run.sh --collect)
#     79-acc-result    the sets' counts; protocols refused by the PHI tripwire are a product defect count
# Modes (tb-mode): production (the default: the vendor key, box-install.sh and the first-run wizard, PRODUCTION) or
# validation (the owner's ruling of 2026-11-15, a proof of concept): b05 signs with a THROWAWAY Ed25519 key made in
# tmpfs on this VM by tools/sign_bundle.py keygen (never the vendor key; its public half goes beside the bundle; the
# bundle is NOT a release and records/bundle.json says so); the start installs with deploy/install.sh --answers (a
# synthetic site whose env_extra makes the box TB_ENV=VALIDATION; the installer's own path for an operator's TB_ENV,
# D-127), 03 checks the box says VALIDATION, and qualify/promote/resolve are for VALIDATION. install.sh seals the
# site keys on a VALIDATION box under its default KEK back end (tpm: the VM needs a vTPM; no hardening.conf is
# written, so the input firewall and SSH are left as the VM has them and doctor FAILs the host baseline).
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
#   acc: tb-acc-tools (gs:// of the tools tarball), tb-acc-sets ("name:size ..."), tb-acc-job-minutes (setting, 60: the
#        longest single job the plan's high bound gives is a TCGA screen of about 4 minutes; ten times more means a
#        stuck job, not a slow one), tb-acc-authserv (default mx.acc.invalid), tb-acc-tripwire-setting (NAME=VALUE)
#   tb-mode (production | validation); validation: tb-site-answers (the settings wizard's answers of the synthetic
#          site, deploy/gcp/validation-site-answers.yaml; no secret in it) in place of tb-answers-secret
#   tb-max-minutes (setting, 240: the driver sets it from its estimate), tb-idle-minutes (setting, 20: the longest
#   silence known is a model load), tb-done-grace (setting, 30), tb-healthy-minutes (setting, 20: a model load),
#   tb-power-wait-minutes (setting, 15: the driver polls every minute and a GCE stop takes a few)
# Nothing prints a key: no `set -x`. Knobs for the rehearsal only (tests/rehearsal/box-run; never set on the VM):
# TB_BOXRUN_ROOT, TB_BOXRUN_LOGDIR, TB_BOXRUN_SBIN, TB_BOXRUN_TLS, TB_BOXRUN_SERIAL, TB_BOXRUN_BOOT_ID, TB_BOXRUN_PY,
# TB_BOXRUN_MINUTE_S, TB_BOXRUN_POLL_S, TB_BOXRUN_DOOR_HOST, TB_BOXRUN_SHM (the tmpfs of the key), TB_BOXRUN_CGROUP
# (the cgroup root), TB_ISSUE_DIR (deploy/box-install.sh's own knob: where the box's screen text goes),
# TB_BOXRUN_INSTALL (the validation install command), TB_BOXRUN_MOUNT (the bind mount of the weights), TB_BOXRUN_TODAY,
# TB_BOXRUN_ACC_PY (the python that runs lane G's accuracy tools on the VM), TB_BOXRUN_SYS and TB_BOXRUN_ROOT_MAJMIN (a
# stand-in sysfs and root device for grow_root).
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
# A retry (box-run.sh --resume after a fix of this script, tb-retry a new value): the run's end and each step that
# STOPPED are cleared, so that step runs again with the fixed script; every finished step is kept. The stopped
# step's part is kept beside the logs (logs/<step>.stop-<retry>.json): the first-contact failure stays on record.
# The cost cap starts again (the driver set the cloud's own cap for this launch).
RETRY=$(md tb-retry || true)
if [ -n "$RETRY" ] && [ "$RETRY" != "$(cat "$RUN/retry-seen" 2>/dev/null)" ]; then
  "$PY" - "$RUN" "$RETRY" <<'PY'
import json, os, sys
run, retry = sys.argv[1], sys.argv[2]
p = os.path.join(run, "state.json")
if os.path.exists(p):
    st = json.load(open(p))
    st.pop("ended", None)
    for name, s in list(st.get("steps", {}).items()):
        if s.get("status") == "stop":
            part = os.path.join(run, "parts", name + ".json")
            if os.path.exists(part):
                os.replace(part, os.path.join(run, "logs", f"{name}.stop-{retry}.json"))
            del st["steps"][name]
            print(f"TB-RETRY {retry}: step {name} cleared (it stopped before; it runs again)")
    if "50-acc-tools" in st.get("steps", {}):  # lane G's tools are fetched again: a fix may be in them
        del st["steps"]["50-acc-tools"]
        print(f"TB-RETRY {retry}: 50-acc-tools cleared (the tools are fetched again)")
    with open(p + ".tmp", "w") as fh:
        json.dump(st, fh, indent=1, sort_keys=True); fh.write("\n")
    os.replace(p + ".tmp", p)
PY
  rm -f "$RUN/cap-used-s"
  printf '%s' "$RETRY" > "$RUN/retry-seen"
fi

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
  # the box's facts on any way out of a start once an install was tried (a stop is when they matter most)
  if has start && [ -d "${BOXROOT:-/nonexistent}/deploy" ] && [ ! -s "$REC/facts-box.txt" ]; then
    NOTES=/dev/null; step_facts_box >/dev/null 2>&1 || true
  fi
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
# ------------------------------------------------------------------ the root disk grown to the disk (idempotent)
# The disk was enlarged online (2026-11-15, 200 -> 400 GB); the root partition and file system follow only when
# something grows them. Every boot, before any step: when the disk is more than 1 GiB larger than the root partition,
# growpart and the file system's own grow tool; before and after sizes in records/disk.json. A missing tool is said
# loudly (the run goes on, on the space it has; the free-space checks of b05 and 01 still guard it).
SYSFS=${TB_BOXRUN_SYS:-/sys}
grow_root() {
  local mm part disk pn disk_b part_b fs before after out=""
  mm=${TB_BOXRUN_ROOT_MAJMIN:-$(mountpoint -d /)}
  part=$(basename "$(readlink -f "$SYSFS/dev/block/$mm")")
  pn=$(cat "$SYSFS/class/block/$part/partition" 2>/dev/null)
  disk=$(basename "$(dirname "$(readlink -f "$SYSFS/class/block/$part")")")
  disk_b=$(( $(cat "$SYSFS/class/block/$disk/size" 2>/dev/null || echo 0) * 512 ))
  part_b=$(( $(cat "$SYSFS/class/block/$part/size" 2>/dev/null || echo 0) * 512 ))
  fs=$(findmnt -n -o FSTYPE /)
  before=$(df -B1 --output=size / | tail -n 1 | tr -d ' ')
  if [ -z "$pn" ] || [ "$disk_b" -le $((part_b + (1 << 30))) ]; then
    out="nothing to grow (disk $disk_b B, root partition $part_b B)"
  else
    for t in growpart "$( [ "$fs" = xfs ] && echo xfs_growfs || echo resize2fs )"; do
      command -v "$t" >/dev/null || { echo "TB-GROW-FAILED: no $t on this VM: the root stays at $before B" | tee -a "$LOG"; out="no $t"; }
    done
    if [ -z "$out" ]; then
      growpart "/dev/$disk" "$pn" >> "$LOG" 2>&1
      if [ "$fs" = xfs ]; then xfs_growfs / >> "$LOG" 2>&1; else resize2fs "/dev/$part" >> "$LOG" 2>&1; fi
      out="grown: growpart /dev/$disk $pn, then the $fs file system"
    fi
  fi
  after=$(df -B1 --output=size / | tail -n 1 | tr -d ' ')
  # the record of the boot that grew it (or the first boot's) is kept; a later boot with nothing to grow adds none
  case "$out" in "nothing to grow"*) [ -s "$RUN/records/disk.json" ] && { echo "TB-DISK root $after B ($out)" | tee -a "$LOG"; return 0; } ;; esac
  printf '{"disk": "%s", "partition": "%s", "fs": "%s", "disk_bytes": %s, "partition_bytes_before": %s, "root_fs_bytes_before": %s, "root_fs_bytes_after": %s, "what": "%s"}\n' \
    "$disk" "$part" "$fs" "$disk_b" "$part_b" "${before:-0}" "${after:-0}" "$out" > "$RUN/records/disk.json"
  echo "TB-DISK root $before -> $after B ($out)" | tee -a "$LOG"
}
grow_root || echo "TB-GROW-FAILED: the root could not be grown (see the log)" | tee -a "$LOG"

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
export TB_SETTINGS_FILE=./settings.yaml   # every compose call of this run (selftest, doctor, Box.call): F16
ASEC=$(md tb-answers-secret || true); AVER=$(md tb-answers-version || true)
SITE_ANSWERS=$(md tb-site-answers | head -c 1 || true)   # validation: the synthetic site's answers in the metadata
CONNECT=$(md tb-console-connect || echo 127.0.0.1:443)
CACERT=$(md tb-console-cacert || echo "$BOXROOT/deploy/secrets/tls/caddy-root.crt")
PROFILE=$(md tb-profile || echo rtxpro6000)
MODELS=$(md tb-models-root || echo /models)
JUDGE_S=$(md tb-judge-service || echo llm-service)
VERIFIER_S=$(md tb-verifier-service || echo llm-verifier)
DOCTOR_EXPECTED=$(md tb-doctor-expected || true)
QEVIDENCE=$(md tb-qualify-evidence || true)
QARGS=$(md tb-qualify-args || true)   # qualify's own size options (--items N --repeat-items M), recorded in its notes
BOXPY=$(md tb-box-python || echo python3)
# validation: where the box's model folders come from (models/registry.yaml's rtxpro6000 rows: the VM's model cache
# holds the publisher's snapshots; the template and the embedder's subset come from their public repositories)
MODEL_LINKS=$(md tb-model-links || echo "gemma-4-26b-a4b-it-4bit=hub/models--nvidia--Gemma-4-26B-A4B-NVFP4/snapshots/a19cfe00be84568a6867111c9a68c9c44fdcffe6 qwen3.5-9b-4bit=hub/models--cyankiwi--Qwen3.5-9B-AWQ-4bit/snapshots/e4d2d39cede8c5d1716d824cd843e2889c648083")
MODEL_TEMPLATE=$(md tb-model-template || echo "chat-templates/gemma-4-26b-a4b-it/chat_template.jinja=https://huggingface.co/google/gemma-4-26B-A4B-it/resolve/4d7ae4984b7db7de8f8457170b3f1a419ee76d52/chat_template.jinja=ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4")
EMBED_LIST_SRC=$(md tb-embed-list || true)   # gs:// of the embedder's "sha256  path" list (e-embed-1)
EMBED_URL=$(md tb-embed-url || echo "https://huggingface.co/BAAI/bge-m3/resolve/7b44caba5c06fd6f1ef1d2786261e636c38e4295/{path}")
# g6, g9, g10
STUDY=$(md tb-study || true)
G6N=$(md tb-g6-patients || echo 50000)
G6PROFILE=$(md tb-g6-profile || echo dense)
G9_SERVICES=$(md tb-g9-services || echo "orchestrator gateway")
OUTAGE_S=$(md tb-outage-seconds || echo 120)
REQUESTER=$(md tb-screen-requester || true)
G10_IMAGE=$(md tb-g10-vllm-image || true)
G10_BUNDLE=$(md tb-g10-bundle || true); G10_SHA=$(md tb-g10-bundle-sha256 || true)
MODE=$(md tb-mode || echo production)
case "$MODE" in validation) ENVNAME=VALIDATION ;; *) MODE=production; ENVNAME=PRODUCTION ;; esac
# acc
ACC_TOOLS=$(md tb-acc-tools || true)
ACC_SETS=$(md tb-acc-sets || true)
ACC_JOB_MIN=$(md tb-acc-job-minutes || echo 60)
ACC_AUTHSERV=$(md tb-acc-authserv || echo mx.acc.invalid)
ACC_TRIPWIRE=$(md tb-acc-tripwire-setting || true)
ACC_PLAN=$(md tb-acc-plan || true)
ACC_MIN_DL=$(md tb-acc-min-deadline || echo 600)   # (setting) the shortest time budget of a set, seconds
PROG_S=$(md tb-progress-seconds || echo 60)        # (setting) seconds between checkpoints of a long step (the owner's 60)
QTIMEBOX=$(md tb-qualify-timebox || true)          # the owner's probe: qualify ended after so many seconds
ACC_DEADLINE=$(md tb-acc-deadline || true)         # the owner's probe: each set's time budget, seconds (else the plan's)   # "set:size:high_seconds ..." from the plan (tools/box_run.py metadata)
PROBE=$(md tb-probe || true)
DIRECT=$(md tb-direct || true)   # 1: 02 brings the installed tree's stack up with the product's own tools, no install.sh   # 1: read the VM's and the box's facts (00-facts; after the install 04p-facts) and stop
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
for s in $STEPS; do case "$s" in build|start|g6|g9|g10|acc|probe|dev) ;; *) pf="$pf; unknown group '$s' in tb-steps" ;; esac; done
[ -s "$HELPER" ] || pf="$pf; no tb-helper (deploy/gcp/box_vm.py)"
for c in "$PY" curl tar sha256sum; do command -v "$c" >/dev/null || pf="$pf; no $c"; done
if has build || has dev; then
  for c in git make docker; do command -v "$c" >/dev/null || pf="$pf; no $c (build)"; done
  if ! has build; then bv="SRC COMMIT"   # dev: images and the tree only
  elif [ "$MODE" = validation ]; then bv="SRC COMMIT RID SEQ OUTP"; else bv="SRC COMMIT RID SEQ KSEC KVER VPUB_SRC OUTP"; fi
  for v in $bv; do [ -n "${!v}" ] || pf="$pf; no ${v} (build metadata)"; done
fi
if has start || has dev || has g6 || has g9 || has g10 || has acc; then
  for c in docker nvidia-smi; do command -v "$c" >/dev/null || pf="$pf; no $c"; done
  [ -d "$MODELS" ] || pf="$pf; no model folders at $MODELS"
fi
if has start; then
  if [ "$MODE" = validation ]; then   # install.sh seals a VALIDATION box's site keys (KEK_BACKEND tpm, seal_keys.sh)
    [ -n "${TB_BOXRUN_ROOT:-}" ] || [ -e /dev/tpmrm0 ] || [ -e /dev/tpm0 ] \
      || pf="$pf; no TPM 2.0 device: install.sh seals a VALIDATION box's site keys with KEK_BACKEND=tpm (turn the VM's vTPM on)"
    command -v systemd-creds >/dev/null || [ -n "${TB_BOXRUN_ROOT:-}" ] || pf="$pf; no systemd-creds (seal_keys.sh, KEK_BACKEND=tpm)"
  fi
  [ -n "$BUNDLE_SRC" ] || pf="$pf; no tb-bundle"
  [ -n "$BUNDLE_SHA" ] || pf="$pf; no tb-bundle-sha256 (a bundle is never installed unchecked)"
  [ -n "$VPUB_SRC" ] || pf="$pf; no tb-vendor-pub (the installer refuses a bundle without the vendor's public key)"
  { [ -n "$ASEC" ] && [ -n "$AVER" ]; } || { [ "$MODE" = validation ] && [ -n "$SITE_ANSWERS" ]; } \
    || pf="$pf; no tb-answers-secret / tb-answers-version (the wizard's answers; validation: or tb-site-answers)"
fi
[ "$(echo $G9_SERVICES | wc -w)" -le 5 ] || pf="$pf; at most five tb-g9-services (steps 32 to 36)"
{ has g6 || has g9; } && [ -z "$STUDY" ] && pf="$pf; no tb-study (the approved study G-6 and G-9 screen)"
has g10 && [ -z "$G10_IMAGE" ] && pf="$pf; no tb-g10-vllm-image (G-10 names its image)"
has acc && [ -z "$ACC_TOOLS" ] && pf="$pf; no tb-acc-tools (lane G's accuracy tools, a tarball in the bucket)"
has acc && [ -z "$ACC_SETS" ] && pf="$pf; no tb-acc-sets"
[ -z "$pf" ] || finish "TB-PREFLIGHT-FAILED${pf}" preflight-failed
echo "TB-PREFLIGHT ok: groups$STEPS"

# ------------------------------------------------------------------ the step runner
STEP=""; STEP_LOG=/dev/null; NOTES=/dev/null; STOP=""
note() { printf '%s\t%s\n' "$1" "$2" >> "$NOTES"; }          # a value of the step's part result (JSON, or plain text)
watched() {  # run a command of the step, its output to the step's log; the log growing is the heartbeat
  echo "+ $(basename "$1") (${#} words) $(date -u +%T)" >> "$STEP_LOG"
  "$@" >> "$STEP_LOG" 2>&1 < /dev/null &
  local pid=$! size=-1 now io=-1 ion gpu last_prog=$SECONDS line t0=$SECONDS e0 st adir
  e0=$(date +%s)
  adir=$(docker volume inspect -f '{{.Mountpoint}}' trialbox_audit-data 2>/dev/null)
  while kill -0 "$pid" 2>/dev/null; do
    now=$(stat -c %s "$STEP_LOG" 2>/dev/null || echo 0)
    [ "$now" = "$size" ] || { touch "$HB"; size=$now; }
    if [ -n "${WATCH_IO:-}" ]; then   # a step whose product command is silent for long (install.sh's bundle checks):
      ion=$(awk '{s += $6 + $10} END {print s + 0}' /proc/diskstats 2>/dev/null)   # the disks reading or writing
      [ "$ion" = "$io" ] || { touch "$HB"; io=$ion; }                                # is progress; a hang does neither
    fi
    if [ -n "${WATCH_GPU:-}" ]; then  # a step whose model calls run long between lines (qualify's pair gate): the card
      gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -dc 0-9)
      [ "${gpu:-0}" -gt 0 ] 2>/dev/null && touch "$HB"                              # working is progress
    fi
    # a checkpoint every PROG_S seconds (60, the owner's order) on the console, in the step's log and in the bucket:
    # what the step is doing now (PROG_FN), its time, the gateway's audited calls since it began (rate, latency, the
    # queue, calls over a minute, refusals, how long since the last finished call) and the card's use. A stop, a
    # pre-emption or the watchdog leaves the last checkpoint and every finished item in the bucket.
    if [ -n "${PROG_FN:-}" ] && [ $((SECONDS - last_prog)) -ge "${PROG_S:-60}" ]; then
      last_prog=$SECONDS
      gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -dc 0-9)
      st=$(vm audit-stats --dir "${adir:-/nonexistent}" --since "$e0" 2>/dev/null || echo '{}')
      printf '{"t": "%s", "elapsed_s": %s, "gpu": "%s", "now": "%s", "audit": %s}\n' "$(date -u +%FT%TZ)" \
        $((SECONDS - t0)) "${gpu:-?}" "$("$PROG_FN" 2>/dev/null | tr -d '"\\')" "$st" >> "$RUN/logs/$STEP.checkpoints.jsonl"
      line=$("$PY" -c 'import json,sys
d = json.loads(sys.argv[1] or "{}"); l = d.get("latency_s") or {}; q = d.get("queue_s") or {}
print("calls %s (%s/min, %s in the last minute); latency med %s p95 %s max %s s; queue max %s s; over 60 s %s; refusals %s; last finished call %s s ago" % (
  d.get("calls"), d.get("calls_per_min"), d.get("calls_last_window"), l.get("median"), l.get("p95"), l.get("max"),
  q.get("max"), d.get("calls_over_60s"), d.get("refusals") or {}, d.get("seconds_since_last_call")))' "$st" 2>/dev/null)
      echo "TB-PROGRESS $(date -u +%T) $STEP +$((SECONDS - t0))s: $("$PROG_FN" 2>/dev/null) $line; GPU ${gpu:-?} %" \
        | tee -a "$STEP_LOG" "$LOG" > "$SERIAL" 2>/dev/null
      pack
    fi
    # a time box (the owner's probes): the step's command is ended at TIMEBOX_S, cleanly, by TIMEBOX_KILL
    if [ -n "${TIMEBOX_S:-}" ] && [ $((SECONDS - t0)) -ge "$TIMEBOX_S" ]; then
      echo "TB-TIMEBOX $STEP: ended after ${TIMEBOX_S} s (the probe's time box)" | tee -a "$STEP_LOG" "$LOG" > "$SERIAL" 2>/dev/null
      [ -z "${TIMEBOX_KILL:-}" ] || $TIMEBOX_KILL >> "$STEP_LOG" 2>&1
      kill "$pid" 2>/dev/null; TIMEBOXED=1
      break
    fi
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
# COMPOSE_FILE/PROFILES: install.sh's .env. TB_SETTINGS_FILE as install.sh exports it (install.sh:459): it is not in
# deploy/.env, and without it compose mounts settings.example.yaml into every service (F16, a product gap)
dc() { TB_SETTINGS_FILE=./settings.yaml docker compose --project-directory "$BOXROOT/deploy" "$@"; }
box_tool() { (cd "$BOXROOT" && PYTHONPATH="$BOXROOT/libs:$BOXROOT" exec "$BOXPY" -m "tools.$1" "${@:2}"); }
in_svc() { dc exec -T "$1" python -; }   # a snippet on stdin in a service's container (as make rehearse-box does)
d_install()  { "$INSTALLER" "$1" --prepare --yes; }
d_firstrun() { "$INSTALLER" --firstrun; }                                     # waits for the owner's answers
# A box tool that needs the product's code (services/: the gateway, the registry, the orchestrator) runs in the box's
# own python image, as install.sh runs pin_model: the host tree of the bundle carries no services/ (tools/host_tree.py).
# img_tool [-v SRC:DST[:ro] | -e NAME[=VALUE] ...] <tool> [args]; IMG_NET names the network (default none).
img_tool() {
  local o=()
  while [ $# -gt 1 ]; do case "$1" in -v|-e|--env-file|--name) o+=("$1" "$2"); shift 2 ;; *) break ;; esac; done
  # OPS-004 (D-570): after a bundle install the shipped files under deploy/ are links into ../current; the release
  # tree goes beside /d at /current, as install.sh's tree_args does
  [ -d "$BOXROOT/current" ] && o+=(-v "$(readlink -f "$BOXROOT/current"):/current:ro")
  docker run --rm --user 0 --network "${IMG_NET:-none}" -v "$BOXROOT/deploy:/d" ${o[@]+"${o[@]}"} "$(img_py)" \
    python -m "tools.$1" "${@:2}"
}
SITE_PINS=/d/site/registry.site.yaml   # the site pins install.sh writes (pin_model --install ... --out)
d_pin()      { [ -s "$BOXROOT/deploy/site/registry.site.yaml" ]; }   # install.sh pinned the pair (its own step)
d_weights()  { img_tool pin_model --verify-all /d/models --out "$SITE_PINS"; }
# trialbox eval qualify --box (BOX-QUALIFY, D-737) in the box's image (its code needs services/), with what --box
# needs to ask the running box: the host's docker CLI, its compose plugin and socket, and the host paths it finds
# (the weight folders under the box root, the servers' json-file logs, the audit volume) at the same paths. The
# gateway at its compose name on trialbox-net, with the operator's token (tools/trialbox/svc_secrets.py: the
# administrator's token on the host); the qualify cache (medtxt) in $TB/qualify-cache. $1 the record, rest evidence.
d_qualify() {
  local out=$1 tok=() m=() p; shift
  for p in /var/run/docker.sock /var/lib/docker/containers /var/lib/docker/volumes "$BOXROOT" "$MODELS"; do
    [ -e "$p" ] && m+=(-v "$p:$p")
  done
  p=$(command -v docker); [ -n "$p" ] && m+=(-v "$p:/usr/local/bin/docker:ro")
  for p in /usr/libexec/docker/cli-plugins /usr/lib/docker/cli-plugins /usr/local/lib/docker/cli-plugins; do
    [ -d "$p" ] && m+=(-v "$p:$p:ro")
  done
  if [ -s "$BOXROOT/deploy/secrets/services/operator.token" ]; then
    tok=(-v "$BOXROOT/deploy/secrets/services/operator.token:/run/tb-operator.token:ro" -e TB_SERVICE_TOKEN_FILE=/run/tb-operator.token)
  fi
  # qualify reads files of the repository the box image does not carry (tests/fixtures/llm, docs/licences,
  # eval/qualification, deploy/images.lock: F13, a product gap): the same commit's files, read-only at /app/...
  if [ -d "$TB/qsrc/trialbox" ]; then
    for p in tests docs eval; do m+=(-v "$TB/qsrc/trialbox/$p:/app/$p:ro"); done
    m+=(-v "$TB/qsrc/trialbox/deploy/images.lock:/app/deploy/images.lock:ro")
  fi
  rm -rf "$TB/qualify-out"; mkdir -p "$TB/qualify-cache" "$TB/qualify-out"
  docker rm -f tb-qualify >/dev/null 2>&1
  IMG_NET=trialbox-net img_tool --name tb-qualify ${m[@]+"${m[@]}"} ${tok[@]+"${tok[@]}"} -v "$TB/qualify-cache:/app/.cache" -v "$TB/qualify-out:/q" \
    -e "TB_COMPOSE=docker compose --project-directory $BOXROOT/deploy" -e TB_DOCKER=docker \
    -e "TB_ENV=$(envget TB_ENV)" \
    trialbox eval qualify --box --profile "$PROFILE" --gateway-url http://gateway:8020/v1 --operator lane-g-box-run \
    --out /q "$@"
  local rc=$? rec
  # --out is the records' folder (qualify writes <profile>-<build>-<time>.json in it): the newest one is this run's
  rec=$(ls -t "$TB/qualify-out"/*.json 2>/dev/null | head -n 1)
  [ -n "$rec" ] && [ -s "$rec" ] && cp "$rec" "$out"
  return $rc
}
d_medtxt()   { IMG_NET=bridge img_tool -v "$TB/qualify-cache:/app/.cache" medtxt_eval fetch; }   # qualify's medtxt items
d_cmd()      { docker inspect --format '{{json .Config.Cmd}}' "$1"; }
d_sha_in()   { dc exec -T "$1" sha256sum "$2"; }                              # a file inside a service's container
d_digests()  { docker image inspect --format '{{json .RepoDigests}}' "$1"; }
d_identity() { in_svc orchestrator <<EOF
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
          for e in default_registry().served_set("$ENVNAME")]
print(json.dumps({"builds": builds, "served_prompts": served}))
EOF
}
d_promote()  { img_tool -v "$(dirname "$2"):/q:ro" pin_model --promote "$1" --record "/q/$(basename "$2")" \
                 --environment "$ENVNAME" --out "$SITE_PINS"; }
d_resolve()  { img_tool pin_model --resolve --env-file /d/.env --out "$SITE_PINS"; }   # one line a role and class (D-738)
d_gw_restart() { dc up -d --force-recreate --wait gateway; }   # the gateway reads the site pins at start
# G-1's token half (chat_template_check, D-739): the prompts, the ids the judge's server gives through model-guard's
# keyed /tokenize (asked from the gateway's container: the only one with the key and on model-net), and the ids of
# the weights folder's own tokenizer, in the model server's image (it carries transformers), offline
d_g1_prompts() { docker run --rm --network none "$(img_py)" python -c \
  'import json; from tools.chat_template_check import prompts; print(json.dumps(prompts(), ensure_ascii=False))'; }
# d_g1_server <the prompts file> <the judge's served name>
d_g1_server() { in_svc gateway <<EOF
# tb-boxrun: g1-tokens
import base64, json, os, urllib.request
msgs = json.loads(base64.b64decode("$(base64 -w0 < "$1")").decode("utf-8"))
url = (os.environ.get("TB_EP_SERVING_URL") or "http://llm-service:8000/v1").rstrip("/")
root = url[:-3] if url.endswith("/v1") else url
kf = os.environ.get("TB_LLM_API_KEY_FILE", "")
key = open(kf).read().strip() if kf and os.path.exists(kf) else os.environ.get("TB_LLM_API_KEY", "")
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ids, errors = [], []
for m in msgs:
    body = json.dumps({"model": "$2", "messages": m, "add_generation_prompt": True}).encode()
    req = urllib.request.Request(root + "/tokenize", data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with op.open(req, timeout=60) as r:
            ids.append([int(x) for x in json.loads(r.read())["tokens"]])
    except Exception as exc:
        ids.append(None); errors.append(str(exc)[:200])
print(json.dumps({"ids": ids, "errors": errors, "url": root + "/tokenize", "keyed": bool(key)}))
EOF
}
d_g1_hf() {  # $1 the vLLM image, $2 the host folder at /models, $3 the model path, $4 the work folder, [$5 template]
  local t=(); [ -z "${5:-}" ] || t=(--template "$5")
  docker run --rm --network none --user 0 --entrypoint python3 -e HF_HUB_OFFLINE=1 -e PYTHONPATH=/tbt \
    -v "$2:/models:ro" -v "$BOXROOT/tools:/tbt/tools:ro" -v "$4:/w" "$1" \
    -m tools.chat_template_check hf --model "$3" --prompts /w/prompts.json --out /w/hf.json ${t[@]+"${t[@]}"}
}
# validation mode: deploy/install.sh with a synthetic site's answers (env_extra TB_ENV: VALIDATION); its log redacted
# (it prints the first administrator's password and enrolment code once, and this log goes to the bucket)
d_install_v() {  # as box-install.sh judges it: a FAIL list at the end (no backup target yet) leaves the stack running
  local rc
  # shellcheck disable=SC2086 # TB_BOXRUN_INSTALL is a command line on purpose (the rehearsal)
  # line-buffered: install.sh pipes its long steps through sed, which holds a pipe's output until it ends (stdbuf's
  # setting reaches every child), so the step's log grows while the bundle is verified and loaded
  # the owner's ruling (2026-11-15): a short-lived public-data PoC box needs no sealed site keys; install.sh's own
  # setting defers the seal (TB_BOX_DEFER_SEAL=1, install.sh:580), so nothing of the TPM is needed. Said in the notes.
  TB_BOX_DEFER_SEAL=1 PYTHONUNBUFFERED=1 stdbuf -oL -eL ${TB_BOXRUN_INSTALL:-bash $BOXROOT/deploy/install.sh} "$1" --answers "$2" --gpu "$PROFILE" --mode gpu --yes 2>&1 \
    | "$PY" "$HELPER" redact | tee "$TB/install-v.log"
  rc=${PIPESTATUS[0]}
  [ "$rc" = 0 ] || grep -q "TrialBox is running" "$TB/install-v.log" || return "$rc"
  echo "install.sh exit $rc (a FAIL list at the end; the stack runs)"
}
# What install.sh runs with the host's python3 needs PyYAML (tools/trialbox/anchors.py, and pre-start through
# doctor.py) and, for its own verifier, cryptography; egress wants nft, the retention and backup schedules cron. The
# product's own rehearsal host has exactly these (tools/rehearse_box/host.Dockerfile); a GCE image may not.
d_host_prereq() {
  local miss=()
  python3 -c 'import yaml' 2>/dev/null || miss+=(python3-yaml)
  python3 -c 'import cryptography' 2>/dev/null || miss+=(python3-cryptography)
  command -v nft >/dev/null || miss+=(nftables)
  [ -d /etc/cron.d ] || miss+=(cron)
  # F9 (2026-11-15): systemd-creds reached the vTPM only through the TSS2 libraries it loads at run time; without them
  # "Failed to create TPM2 context: Operation not supported" in seal_keys.sh. tpm2-tools brings them
  [ -n "${TB_BOXRUN_ROOT:-}" ] || systemd-creds has-tpm2 2>/dev/null | head -n 1 | grep -qx yes || miss+=(tpm2-tools)
  note host_packages_added "\"${miss[*]-}\""
  [ -z "${TB_BOXRUN_ROOT:-}" ] || return 0   # the rehearsal installs nothing on its host
  if [ ${#miss[@]} -gt 0 ]; then
    DEBIAN_FRONTEND=noninteractive apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${miss[@]}" \
      || return 1
  fi
  # the seal needs the TPM through systemd-creds: proved here, in the first minutes, not 20 minutes into the install:
  # every part of has-tpm2, and a round trip of a throwaway value through the TPM (nothing of the box's)
  note has_tpm2 "\"$(systemd-creds has-tpm2 2>&1 | tr '\n' ' ')\""
  systemd-creds has-tpm2 2>&1 | tee -a "$STEP_LOG" | head -n 1 | grep -qx yes \
    || { echo "TB-TPM: systemd-creds has-tpm2 is not 'yes': the seal would fail" >&2; return 1; }
  [ "$(printf tb-tpm-roundtrip | systemd-creds encrypt --with-key=tpm2 --name=tb-roundtrip - - 2>>"$STEP_LOG" \
        | systemd-creds decrypt --name=tb-roundtrip - - 2>>"$STEP_LOG")" = tb-tpm-roundtrip ] \
    || { echo "TB-TPM: a throwaway value does not go through systemd-creds encrypt/decrypt with the TPM" >&2; return 1; }
  note tpm_roundtrip true
}
# A VALIDATION install that stopped half way leaves the site keys wrapped under a KEK that sat only in /run (tmpfs:
# gone at the next boot) and its record in the secrets volume; install.sh run again would wrap under a KEK nobody has.
# Before an install, a box whose earlier install never reached "TrialBox is running" (its log, $TB/install-v.log)
# is taken down with its volumes and the KEK's leftovers removed: a fresh VALIDATION box on public data, nothing of
# value in it. Said in the step's notes.
d_half_install() {
  grep -q "TrialBox is running" "$TB/install-v.log" 2>/dev/null && return 0
  docker volume ls -q 2>/dev/null | grep -q '^trialbox_' || return 0
  dc down -v --remove-orphans >/dev/null 2>&1
  docker volume ls -q | grep '^trialbox_' | xargs -r docker volume rm >/dev/null 2>&1
  rm -rf /run/trialbox /etc/credstore.encrypted/trialbox-kek
  note half_install_removed true
}
d_old_servers() {  # judge, verifier, front of deploy/gcp/gpu-sim-startup.sh (--restart unless-stopped): removed, said
  local c
  for c in judge verifier front; do
    docker inspect "$c" >/dev/null 2>&1 && docker rm -f "$c" >/dev/null 2>&1 && note "removed_old_$c" true
  done
  return 0
}
d_models_place() {  # the site's weights in deploy/models, where install.sh pins them from (the VM's /models, bound)
  local l=() x
  # the box's flat folders (compose's JUDGE_MODEL_DIR, VERIFIER_MODEL_DIR defaults, the registry's template file,
  # the embedder's folder) from the VM's model cache and the registry's public sources (box_vm.py models-place)
  for x in $MODEL_LINKS; do l+=(--link "$x"); done
  [ -z "$EMBED_LIST_SRC" ] || fetch "$EMBED_LIST_SRC" "$TB/embed.sha256" || return 1
  vm models-place --root "$MODELS" ${l[@]+"${l[@]}"} --template "$MODEL_TEMPLATE" \
    ${EMBED_LIST_SRC:+--embed-list "$TB/embed.sha256"} --embed-url "$EMBED_URL" --notes "$NOTES" || return 1
  mkdir -p "$BOXROOT/deploy/models"
  if [ -n "${TB_BOXRUN_MOUNT:-}" ]; then $TB_BOXRUN_MOUNT "$MODELS" "$BOXROOT/deploy/models"
  else mountpoint -q "$BOXROOT/deploy/models" || mount --bind "$MODELS" "$BOXROOT/deploy/models"; fi
}
# lane G's accuracy tools OUTSIDE the box: the VM's own python3 (they need the standard library only, and the
# network for the pinned files and the live records); JMED-Personas' parquet needs pyarrow: the box's python image,
# offline (its files are fetched before)
d_acc_py() { (cd "$ACCT" && PYTHONPATH="$ACCT" ${TB_BOXRUN_ACC_PY:-python3} -m tools.public_accuracy "$@"); }
d_acc_img() { docker run --rm --network none --user 0 -v "$ACCT:/acc" -w /acc -e PYTHONPATH=/acc "$@"; }
d_recreate() { dc up -d --force-recreate --wait "$@"; }
d_capture()  { box_tool serving_config capture --container "judge=$(cid "$JUDGE_S")" --container "verifier=$(cid "$VERIFIER_S")" \
                 --models-dir "$MODELS" --notes "$PROFILE profile: box run $RUN_ID" --out "$1"; }   # $1 the record
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
# the build's own tools the release commit's targets call on the host: `make images` runs tools/fetch_jvm_deps.sh,
# which needs Maven and the JDK of .java-version (CI: actions/setup-java); installed only when missing
d_build_prereq() {
  local jv; jv=$(tr -dc 0-9 < "$CK/.java-version" 2>/dev/null); jv=${jv:-21}
  DEBIAN_FRONTEND=noninteractive apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    "openjdk-$jv-jdk-headless" maven
}
# The classic image store for the build: with Docker's containerd image store a pulled image's local Id is its index
# digest, while the release gates record a registry image by its config digest, and the bundle check matches by the
# local Id alone (tools/supply_chain/__main__.py:113): every third-party image is then "not a passing image". CI's
# runners use the classic store. Set once, before any image is built or pulled (b02), never on the box.
d_docker_classic() {
  docker info -f '{{json .DriverStatus}}' 2>/dev/null | grep -q 'containerd.snapshotter' || return 0
  "$PY" - <<'PYC' || return 1
import json, os
p = "/etc/docker/daemon.json"
d = json.load(open(p)) if os.path.exists(p) else {}
d.setdefault("features", {})["containerd-snapshotter"] = False
json.dump(d, open(p, "w"), indent=1)
PYC
  systemctl restart docker && sleep 5 && ! docker info -f '{{json .DriverStatus}}' | grep -q 'containerd.snapshotter'
}
# The probe of 2026-11-15 (F7): 44 GB free of 193 GB; /var/lib/containerd held 47 GB, the images of Docker's containerd
# store from before the switch to the classic store (d_docker_classic), which nothing uses any more. Removed through
# containerd itself (its own garbage collection drops the unreferenced snapshots); free space noted before and after.
d_old_store() {
  local imgs
  command -v ctr >/dev/null || return 0
  note free_before_old_store "\"$(df -h --output=avail / | tail -n 1 | tr -d ' ')\""
  imgs=$(ctr -n moby images ls -q 2>/dev/null)
  # shellcheck disable=SC2086  # one image reference per word
  [ -z "$imgs" ] || ctr -n moby images rm $imgs >/dev/null 2>&1
  ctr -n moby content ls -q 2>/dev/null | xargs -r ctr -n moby content rm >/dev/null 2>&1
  sleep 5
  note free_after_old_store "\"$(df -h --output=avail / | tail -n 1 | tr -d ' ')\""
  return 0
}
b_prereq() {  # before b02 and b03 (a boot that kept b02 still needs them for the images)
  need "the classic image store for the build (the gates and the bundle check name an image alike)" d_docker_classic || return 1
  d_old_store
  if ! command -v mvn >/dev/null || ! command -v java >/dev/null; then
    need "installing the build's host tools (Maven, the JDK of .java-version)" d_build_prereq || return 1
  fi
  note java "\"$(java -version 2>&1 | head -n 1)\""
}
step_b_venv() { b_prereq && step_b_make venv scanners; }
# make images, then the demo image the release gates also scan (SC_OWN_IMAGES), as CI's images job builds it
step_b_images() { b_prereq && step_b_make images && need "the demo image (demo/Dockerfile)" d_demo_image; }
d_demo_image() { (cd "$CK" && docker build -f demo/Dockerfile -t trialbox-demo:step5 .); }
step_b_gates() {
  local args=""
  need "make trivy-db" make -C "$CK" trivy-db || return 1
  # the demo image the gates scan, when a resumed build kept a b03 that did not build it
  docker image inspect trialbox-demo:step5 >/dev/null 2>&1 || need "the demo image (demo/Dockerfile)" d_demo_image || return 1
  # production: enforcing (no --vuln-mode report): a FAIL here stops the build, and the vendor key is never read.
  # validation (a proof of concept, never a release): the gates' own report mode, as CI's images job runs them. It
  # defers only the fixable findings of the two test-only mail servers no bundle carries (tools/supply_chain/
  # release.py VULN_REPORT_ONLY); every image a bundle carries still blocks. Recorded in records/bundle.json.
  if [ "$MODE" = validation ]; then args="--vuln-mode report"; note gates_vuln_mode '"report (test-only mail images deferred)"'; fi
  if ! watched make -C "$CK" release-gates ${args:+RELEASE_GATES_ARGS="$args"}; then
    STOP="TB-GATES-FAILED: make release-gates did not pass (enforcing): $(grep -a '^FAIL' "$STEP_LOG" | head -3 | tr '\n' ' ')"
    return 1
  fi
  note gates "\"build/supply-chain/gates.json\""
  cp "$CK/build/supply-chain/gates.json" "$REC/gates.json" 2>/dev/null
  st set "$STEP" gates_mode "${args:-block}"
}
d_sign() {  # the key lives only inside this function's process: tmpfs, 0600, shredded on every way out
  local k
  k=$(mktemp -d "$SHM/tbk.XXXXXX") || return 1
  chmod 700 "$k"
  trap 'shred -u "$k/vendor.key" 2>/dev/null; rm -rf "$k"' EXIT INT TERM
  ( umask 077; gcloud secrets versions access "$KVER" --secret="$KSEC" --out-file="$k/vendor.key" >/dev/null 2>&1 ) \
    || { echo "TB-NO-VENDOR-KEY: secret $KSEC version $KVER is not readable by this VM's service account"; return 3; }
  chmod 600 "$k/vendor.key"
  (cd "$CK" && mkdir -p "$BUILD/tmp" && TMPDIR="$BUILD/tmp" TB_TZ="${TB_TZ:-UTC}" tools/make_bundle.sh --key "$k/vendor.key" --id "$RID" --release-seq "$SEQ" \
     --out "$BUILD/out/trialbox-$RID.tar" --gates build/supply-chain/gates.json --sbom-dir dist/sbom)
}
# TB_TZ for make_bundle.sh: its compose call that lists the images renders the compose file with a staged .env that
# names no TB_TZ, and the compose file requires one (T-656, ${TB_TZ:?}); it only lists images (tools/make_bundle.sh:104)
d_sign_throwaway() {  # validation: a key made here, never the vendor key; only its public half leaves the VM
  local k
  k=$(mktemp -d "$SHM/tbk.XXXXXX") || return 1
  chmod 700 "$k"
  trap 'shred -u "$k/vendor_ed25519.key" 2>/dev/null; rm -rf "$k"' EXIT INT TERM
  "$CK/.venv/bin/python" "$CK/tools/sign_bundle.py" keygen --out "$k" >/dev/null || return 3
  chmod 600 "$k/vendor_ed25519.key"
  cp "$k/vendor_ed25519.pub" "$BUILD/throwaway-signing-key.pub"
  echo "TB-THROWAWAY-KEY: made on this VM for a validation bundle; the bundle is NOT a release"
  (cd "$CK" && mkdir -p "$BUILD/tmp" && TMPDIR="$BUILD/tmp" TB_TZ="${TB_TZ:-UTC}" tools/make_bundle.sh --key "$k/vendor_ed25519.key" --id "$RID" --release-seq "$SEQ" \
     --out "$BUILD/out/trialbox-$RID.tar" --gates build/supply-chain/gates.json --sbom-dir dist/sbom)
}
# the room make_bundle.sh needs: it stages every image (docker save, ~25 GB with vLLM) and then writes the bundle; its
# staging goes under the build root (TMPDIR), not /tmp, and the build cache of b03 is dropped first (images are kept)
b_room() {
  docker builder prune -af >/dev/null 2>&1 || true
  d_old_store
  note free_before_sign "\"$(df -h --output=avail,target "$BUILD" / 2>/dev/null | tail -n +2 | tr -s ' ' | tr '\n' ';')\""
}
step_b_sign() {
  b_room
  mkdir -p "$BUILD/out"
  if [ "$MODE" = validation ]; then
    need "signing the bundle (tools/make_bundle.sh with a throwaway key made on this VM: not a release)" d_sign_throwaway
  else
    need "signing the bundle (tools/make_bundle.sh with the vendor key)" d_sign
  fi
  local rc=$?
  note mode "\"$MODE\""; [ "$MODE" = validation ] && note not_a_release true
  rm -rf "$SHM"/tbk.* 2>/dev/null
  note key_left_on_tmpfs "$(ls -d "$SHM"/tbk.* >/dev/null 2>&1 && echo true || echo false)"
  return $rc
}
step_b_verify() {
  local b="$BUILD/out/trialbox-$RID.tar"
  note mode "\"$MODE\""
  if [ "$MODE" = validation ]; then
    cp "$BUILD/throwaway-signing-key.pub" "$BUILD/vendor.pub" || { STOP="no throwaway public key from b05"; return 1; }
    note not_a_release true
  else
    need "fetching the vendor public key" fetch "$VPUB_SRC" "$BUILD/vendor.pub" || return 1
  fi
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
  if [ "$MODE" = validation ]; then
    need "uploading the throwaway key's public half" gcloud storage cp "$BUILD/throwaway-signing-key.pub" "$OUTP/throwaway-signing-key.pub" || return 1
  fi
  printf '{"release_id": "%s", "release_seq": %s, "commit": "%s", "sha256": "%s", "bytes": %s, "object": "%s", "mode": "%s", "not_a_release": %s, "signed_with": "%s"}\n' \
    "$RID" "$SEQ" "$COMMIT" "$sha" "$(stat -c %s "$b")" "$OUTP/trialbox-$RID.tar" "$MODE" \
    "$([ "$MODE" = validation ] && echo true || echo false)" \
    "$([ "$MODE" = validation ] && echo "a throwaway key made on the runner VM (not the vendor key)" || echo "the vendor key (Secret Manager)")" > "$REC/bundle.json"
  "$PY" - "$REC/bundle.json" "$(st kv _ gates_mode)" <<'PY'
import json, sys
p, mode = sys.argv[1], sys.argv[2] or "block"
d = json.load(open(p))
d["release_gates_vuln_mode"] = mode.replace("--vuln-mode ", "")
d["release_gates"] = ("green: every image blocks" if d["release_gates_vuln_mode"] == "block" else
                      "NOT all green: report mode, the test-only mail images' findings deferred (records/gates.json)")
json.dump(d, open(p, "w"))
PY
  note sha256 "\"$sha\""; note object "\"$OUTP/trialbox-$RID.tar\""
  # the bundle is in the bucket now (its sha256 beside it): the local copy goes, or the start on this same disk
  # holds it four times (this copy, 01's fetch, install.sh's dry-run stage and its real stage)
  rm -f "$b"; note local_copy_removed true
  note disk_after "\"$(df -B1 --output=used,avail / | tail -n 1 | tr -s ' ')\""
}

# ================================================================== start (G-2)
step_bundle() {
  local size free got
  mkdir -p "$TB/bundle"
  # a start on the VM that built the bundle: the build's tree and Docker's build cache are not needed any more
  if [ -d "$BUILD" ] && ! has build; then
    rm -rf "${BUILD:?}/out" "${BUILD:?}/verify-stage" "${BUILD:?}/tb"; note build_tree_removed "\"$BUILD\""
    docker builder prune -af >> "$STEP_LOG" 2>&1 || true
  fi
  [ "$(docker info -f '{{.Driver}}' 2>/dev/null)" = overlay2 ] && d_old_store
  need "fetching the bundle" fetch "$BUNDLE_SRC" "$BUNDLE" || return 1
  size=$(stat -c %s "$BUNDLE"); note bundle_bytes "$size"
  got=$(sha256sum "$BUNDLE" | cut -d' ' -f1)
  [ "$got" = "$BUNDLE_SHA" ] || { STOP="TB-BUNDLE-REFUSED: sha256 ${got:0:16}... is not the declared ${BUNDLE_SHA:0:16}..."; return 1; }
  touch "$HB"
  [ ! -e "$BOXROOT/deploy/updates/installed.json" ] \
    || { STOP="an installed box is already at $BOXROOT: a production start needs a fresh root (tb-box-root)"; return 1; }
  note disk "\"$(df -B1 --output=used,avail / | tail -n 1 | tr -s ' ')\""
  note models_bytes "$(du -sxb "$MODELS" 2>/dev/null | cut -f1 | grep . || echo null)"
  # the installer's room: tools/apply_update.sh stages a full copy of the bundle under ${TMPDIR:-/tmp} (once for
  # install.sh's --dry-run, once for the load; verify_update.py wants 1.05 x the payloads), beside this copy
  free=$(df -B1 --output=avail "${TMPDIR:-/tmp}" | tail -n 1 | tr -dc 0-9)
  note free_bytes "${free:-0}"
  [ "${free:-0}" -gt $((size * 11 / 10)) ] || { STOP="${free:-0} bytes free under ${TMPDIR:-/tmp}, the install stages the bundle's $size there (x1.05)"; return 1; }
  need "TB-BUNDLE-REFUSED: the bundle against its manifest and as a PRODUCTION box reads it" \
    vm bundle-check "$BUNDLE" --production ${COMMIT:+--commit "$COMMIT"} --release-out "$REC/release.json" \
      --host-out "$TB/bundle/host.tar" --notes "$NOTES" --beat "$HB" || return 1
  mkdir -p "$BOXROOT"
  need "unpacking the signed host tree as the installer's bootstrap" tar -xf "$TB/bundle/host.tar" -C "$BOXROOT" || return 1
  rm -f "$TB/bundle/host.tar"
  mkdir -p "$BOXROOT/deploy/keys"
  need "fetching the vendor public key" fetch "$VPUB_SRC" "$BOXROOT/deploy/keys/vendor_ed25519.pub" || return 1
  note vendor_pub_sha256 "\"$(sha256sum "$BOXROOT/deploy/keys/vendor_ed25519.pub" | cut -d' ' -f1)\""
  note mode "\"$MODE\""; [ "$MODE" = validation ] && note not_a_release true
  return 0
}


# ------------------------------------------------------------------ dev: the commit's own tree as the box's release
# The images were built from the commit's checkout (b03, same tags as a bundle's). Its host tree (what a bundle's
# trialbox-host.tar carries: tools/host_tree.py's TOP_DIRS and TOP_FILES) is copied to releases/dev-<commit12> and
# `current` points at it; deploy/'s links into ../current follow. The site's own files (deploy/.env, settings.yaml,
# secrets, site) stay as the settings wizard and the first start left them. No bundle, no signature: said in the notes.
step_dev_tree() {
  local rel="$BOXROOT/releases/dev-${COMMIT:0:12}" x f
  [ -d "$BOXROOT/deploy" ] && [ -s "$BOXROOT/deploy/.env" ] \
    || { STOP="no box at $BOXROOT with the wizard's deploy/.env (the first start's): dev reuses its site files"; return 1; }
  rm -rf "$rel"; mkdir -p "$rel"
  for x in deploy tools libs schemas pyproject.toml .env.example NOTICE CHANGELOG.md; do
    [ -e "$CK/$x" ] && cp -a "$CK/$x" "$rel/"
  done
  rm -f "$rel/deploy/.env"
  ln -sfn "releases/dev-${COMMIT:0:12}" "$BOXROOT/current.new" && mv -Tf "$BOXROOT/current.new" "$BOXROOT/current"
  for f in "$rel"/deploy/*; do   # a shipped file new in this commit gets its link too; the site's own files stay
    x="$BOXROOT/deploy/$(basename "$f")"
    [ -e "$x" ] || [ -L "$x" ] || ln -s "../current/deploy/$(basename "$f")" "$x"
  done
  note release "\"dev-${COMMIT:0:12} (the commit's checkout; images built on this VM, b03; no bundle, no signature)\""
  note commit "\"$COMMIT\""
}
# ------------------------------------------------------------------ the direct route (the lead's order, 2026-11-15)
# The owner's goal for PoC-1 is the main system on the GPU VM, not the delivery path. When install.sh cannot run again
# (it refuses a repeat of the release it already applied), 02 brings up the tree the signed bundle put at $BOXROOT
# (current -> releases/<id>, deploy/.env and settings.yaml from the settings wizard, deploy/secrets) with the product's
# own commands, in install.sh's order: service tokens (secrets init), the pair and embedder pinned (pin_model
# --install, as root: install.sh's own call runs as the image user and cannot write deploy/site, F10), the site keys
# (adapter keys-init; not sealed: the owner's ruling), the database and its release steps (db-up), the whole stack
# (compose up --wait), and the model servers checked as install.sh checks them (doctor --serving on model-net).
envexp() { local v; for v in "$@"; do printf -- '-e\n%s=%s\n' "$v" "$(envget "$v")"; done; }
d_direct_secrets() { box_tool trialbox secrets init --deploy "$BOXROOT/deploy"; }
d_direct_pin() {
  local e=(); mapfile -t e < <(envexp JUDGE_MODEL_DIR JUDGE_MODEL JUDGE_CHAT_TEMPLATE VERIFIER_MODEL_DIR VERIFIER_MODEL)
  mkdir -p "$BOXROOT/deploy/site"
  img_tool "${e[@]}" pin_model --install "$PROFILE" --models-root /d/models --out "$SITE_PINS"
}
d_direct_keys() { dc run --rm --no-deps -T adapter python -m adapter.cli keys-init; }
d_direct_db()   { dc up -d --pull never --wait db; }
d_direct_dbup() { box_tool trialbox db-up --deploy "$BOXROOT/deploy"; }
# after a reboot the bind of the VM's /models into deploy/models is gone, and the model servers and the embedder that
# Docker restarted on the empty folder are unhealthy (F15): the bind again, those three restarted, then the wait
d_models_bind() {
  if [ -n "${TB_BOXRUN_MOUNT:-}" ]; then $TB_BOXRUN_MOUNT "$MODELS" "$BOXROOT/deploy/models"; return 0; fi
  mountpoint -q "$BOXROOT/deploy/models" && return 0
  mount --bind "$MODELS" "$BOXROOT/deploy/models" && dc restart llm-service llm-verifier embed-service
}
d_direct_up()   { d_models_bind && dc up -d --pull never --wait --wait-timeout 900; }
d_direct_serving() {  # as install.sh:616-617: on model-net, the box's .env, deploy/ at /app/deploy, the model key file
  IMG_NET=trialbox-model-net img_tool --env-file "$BOXROOT/deploy/.env" -v "$BOXROOT/deploy:/app/deploy:ro" \
    -v "$(readlink -f "$BOXROOT/current"):/app/current:ro" -e TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key \
    trialbox doctor --serving
}
step_direct_up() {
  [ -d "$BOXROOT/current" ] && [ -s "$BOXROOT/deploy/.env" ] \
    || { STOP="no installed tree at $BOXROOT (the signed bundle's host tree and the wizard's .env): the direct route needs the first install's tree"; return 1; }
  note route '"direct: the signed bundle'"'"'s installed tree, brought up with the product'"'"'s own commands (no install.sh)"'
  note release "\"$(basename "$(readlink -f "$BOXROOT/current")")\""
  need "the installer's host packages" d_host_prereq || return 1
  need "placing the site's weights in deploy/models" d_models_place || return 1
  d_old_servers
  need "service tokens (tools.trialbox secrets init)" d_direct_secrets || return 1
  need "the pair and the embedder pinned (pin_model --install, as root)" d_direct_pin || return 1
  # the pins must be there (install.sh only warned when its own call could not write them, F11): the judge's, the
  # verifier's and the embedder's builds, each with its weights' sha256; readable by the services' user
  chmod -R a+rX "$BOXROOT/deploy/site"
  local b
  for b in gemma-4-26b-a4b-it-rtxpro6000 qwen3.5-9b-rtxpro6000 e-embed-1; do
    "$PY" - "$BOXROOT/deploy/site/registry.site.yaml" "$b" <<'PYP' >> "$STEP_LOG" 2>&1 \
      || { STOP="the site pins name no $b with its weights' sha256 (pin_model --install)"; return 1; }
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
i = text.find(sys.argv[2] + ":")
assert i >= 0 and re.search(r"sha256: *['\"]?[0-9a-f]{64}", text[i:i + 4000]), sys.argv[2]
print("pinned", sys.argv[2])
PYP
  done
  note pins '"judge, verifier and embedder pinned with their sha256 (deploy/site/registry.site.yaml)"'
  need "the site keys (adapter keys-init; not sealed: a public-data PoC box)" d_direct_keys || return 1
  note site_keys '"not sealed (a public-data PoC box, the owner'"'"'s ruling)"'
  need "the database" d_direct_db || return 1
  need "the release's database steps (tools.trialbox db-up)" d_direct_dbup || return 1
  WATCH_IO=1 PROG_FN=prog_line need "the whole stack up (compose up --wait)" d_direct_up || return 1
  watched d_direct_serving; note serving_check_exit $?
  dc ps --format '{{.Service}} {{.State}} {{.Health}}' > "$REC/stack.txt" 2>> "$STEP_LOG"
  note services_up "$(grep -c ' running' "$REC/stack.txt")"
}
step_install() {
  if [ "$MODE" = validation ]; then
    [ -f "$BOXROOT/deploy/install.sh" ] || { STOP="no deploy/install.sh in the bundle's host tree"; return 1; }
    if [ -n "$SITE_ANSWERS" ]; then   # the committed synthetic site (deploy/gcp/validation-site-answers.yaml)
      (umask 077; md tb-site-answers > "$ANSWERS.yaml") && [ -s "$ANSWERS.yaml" ] || { STOP="tb-site-answers is empty"; return 1; }
      note answers "\"tb-site-answers (deploy/gcp/validation-site-answers.yaml)\""
    else
      (umask 077; gcloud secrets versions access "$AVER" --secret="$ASEC" > "$ANSWERS.yaml" 2>/dev/null) && [ -s "$ANSWERS.yaml" ] \
        || { STOP="no site answers in Secret Manager (tb-answers-secret, tb-answers-version)"; return 1; }
    fi
    watched d_host_prereq; note host_prereq_exit $?   # the TPM's proof is a fact here, not a stop: the seal is deferred
    note site_keys '"not sealed: TB_BOX_DEFER_SEAL=1 (a public-data PoC box, the owner'"'"'s ruling)"'
    need "placing the site's weights in deploy/models" d_models_place || return 1
    d_old_servers   # lane G's earlier private model servers on this VM (gpu-sim-startup.sh) would hold the card
    d_half_install
    WATCH_IO=1 need "the installer (install.sh --answers: a VALIDATION box)" d_install_v "$BUNDLE" "$ANSWERS.yaml"; local rc=$?
    rm -f "$ANSWERS.yaml"
    return $rc
  fi
  [ -x "$INSTALLER" ] || { STOP="no installer at $INSTALLER in the bundle's host tree: a person would need a shell"; return 1; }
  need "the installer" d_install "$BUNDLE"
}
step_venv_env() {  # validation: the box's environment as deploy/.env names it (install.sh: PRODUCTION when unset)
  local e; e=$(envget TB_ENV | tr -d "\"' \r" | tr '[:lower:]' '[:upper:]')
  note environment "\"${e:-PRODUCTION (unset)}\""
  [ "$e" = VALIDATION ] || { STOP="the box is ${e:-PRODUCTION (TB_ENV unset)}, not VALIDATION: the answers' env_extra did not reach deploy/.env"; return 1; }
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
step_pin() {  # install.sh pinned the pair (pin_model --install, its own step): the site pins are there
  need "the site pins install.sh wrote (deploy/site/registry.site.yaml)" d_pin || return 1
  note site_pins_sha256 "\"$(sha256sum "$BOXROOT/deploy/site/registry.site.yaml" | cut -d' ' -f1)\""
}
step_g1() {
  local jc tpl sha s img wrc served model src g1w hrc
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
  # the token half (D-739): the judge server's own ids through model-guard's keyed /tokenize against the weights
  # folder's tokenizer, with the folder's template and with the passed one. A part that cannot run is said, not
  # guessed: the identity half stands on its own and the record names what did not run.
  g1w="$TB/g1-tokens"; rm -rf "$g1w"; mkdir -p "$g1w"
  served=$(vm cmd-arg "$(d_cmd "$jc" 2>> "$STEP_LOG")" --flag=--served-model-name)
  model=$(vm cmd-arg "$(d_cmd "$jc" 2>> "$STEP_LOG")" --flag=--model)
  src=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/models"}}{{.Source}}{{end}}{{end}}' "$jc" 2>> "$STEP_LOG")
  img=$(docker inspect --format '{{.Config.Image}}' "$jc" 2>> "$STEP_LOG")
  note judge_served_name "\"$served\""
  if d_g1_prompts > "$g1w/prompts.json" 2>> "$STEP_LOG" && [ -s "$g1w/prompts.json" ]; then
    d_g1_server "$g1w/prompts.json" "$served" > "$g1w/server.json" 2>> "$STEP_LOG" || note tokens_server_exit $?
    hrc=0
    if [ -n "$src" ] && [ -n "$model" ] && [ -n "$img" ]; then
      watched d_g1_hf "$img" "$src" "$model" "$g1w" "$tpl"; hrc=$?
    else hrc=99; fi
    note tokens_hf_exit "$hrc"
  else
    note tokens_prompts "\"not made (the box's image cannot run tools.chat_template_check prompts)\""
  fi
  cp "$g1w/chat_template.folder.jinja" "$REC/chat_template.folder.jinja" 2>/dev/null
  vm g1-tokens --server "$g1w/server.json" --hf "$g1w/hf.json" --notes "$NOTES" > "$REC/g1-tokens.json" 2>> "$STEP_LOG"
  vm identity --box "$REC/identity-box.json" --lock "$BOXROOT/deploy/images.lock" --template-sha "$sha" \
    --images "$RUN/logs/images.json" --weights-exit "$wrc" --tokens "$REC/g1-tokens.json" --notes "$NOTES" > "$REC/identity.json"
}
step_canary() { watched d_canary; local rc=$?; note canary_exit "$rc"; [ "$rc" = 0 ] && note pass true || note pass false; }
# qualify, promote, resolve. In production a qualification that does not pass stops the run (G-2's rule). In
# validation (the owner's ruling D-511: a failed gate is a RESULT): the record and each step's verdict are kept, the
# pair is promoted only from a passing record, and the run goes on: a VALIDATION box routes a candidate pair (D-823);
# whether it really routes the run's calls is asked of the box's own gateway at 52-acc-routes.
QSTEPS="pin serving_record licence schema longest_prompt log_marker canary pair_gate determinism throughput injection n12 public_e2e goldens planted_defect"
prog_qualify() {  # the gate qualify is in now: the one after the last it reported (tools/qualify.py STEPS order)
  local last next n
  last=$(grep -oE '^qualify: [a-z_0-9]+:' "$STEP_LOG" 2>/dev/null | tail -n 1 | cut -d' ' -f2 | tr -d :)
  n=$(grep -cE '^qualify: [a-z_0-9]+: ' "$STEP_LOG" 2>/dev/null)
  next=$(printf '%s\n' $QSTEPS | grep -A1 -x "${last:-none}" | sed -n 2p); [ -n "$last" ] || next=pin
  echo "qualify gate ${next:-?} ($n of 15 reported);"
}
prog_line() { echo "now: $(grep -v '^TB-PROGRESS' "$STEP_LOG" 2>/dev/null | tail -n 1 | cut -c1-80);"; }
step_qualify() {
  local args=() e rc
  for e in $QEVIDENCE; do   # step=gs://...: the evidence results qualify reads (fetched, named in the part)
    mkdir -p "$TB/evidence"
    need "fetching qualify evidence ${e%%=*}" fetch "${e#*=}" "$TB/evidence/${e%%=*}.json" || return 1
    args+=(--evidence "${e%%=*}=$TB/evidence/${e%%=*}.json")
  done
  note evidence "\"${QEVIDENCE:-none}\""
  # a boot after the start's (a resume): the stack restarts by itself, the model servers load for minutes; qualify
  # starts only once compose says every service, both model servers too, is healthy (F14: model_unavailable)
  if [ -n "$DIRECT" ]; then WATCH_IO=1 need "the stack healthy before qualify (compose up --wait)" d_direct_up || return 1; fi
  watched d_medtxt; note medtxt_fetch_exit $?
  # the box's own commit, for the files qualify reads that the image lacks (F13): the source bundle beside the bundle
  if has dev && [ -d "$CK" ] && [ ! -d "$TB/qsrc/trialbox" ]; then ln -sfn "${CK%/trialbox}" "$TB/qsrc"; fi
  if [ -n "$COMMIT" ] && [ ! -d "$TB/qsrc/trialbox" ]; then
    rm -rf "$TB/qsrc"
    { fetch "${BUNDLE_SRC%/*}/src.bundle" "$TB/qsrc.bundle" && git clone -q "$TB/qsrc.bundle" "$TB/qsrc" \
        && git -C "$TB/qsrc" checkout -q --detach "$COMMIT"; } >> "$STEP_LOG" 2>&1 \
      && note qualify_files "\"tests docs eval deploy/images.lock of $COMMIT, read-only\"" \
      || { rm -rf "$TB/qsrc"; note qualify_files '"not there: the commit'"'"'s source bundle could not be read"'; }
    rm -f "$TB/qsrc.bundle"
  fi
  if [ "$MODE" = validation ]; then
    note qualify_args "\"${QARGS:-none (every item)}\""
    # shellcheck disable=SC2086  # QARGS is qualify's options, one per word
    TIMEBOXED=""
    TIMEBOX_S=$QTIMEBOX TIMEBOX_KILL="docker kill tb-qualify" WATCH_GPU=1 PROG_FN=prog_qualify \
      watched d_qualify "$QREC" ${args[@]+"${args[@]}"} $QARGS; rc=$?
    note qualify_exit "$rc"
    if [ -n "$TIMEBOXED" ]; then   # a probe: what it reached is the result, there is no record
      note timeboxed_s "$QTIMEBOX"; note gates_reported "\"$(grep -oE '^qualify: [a-z_0-9]+: [a-z]+' "$STEP_LOG" | cut -d' ' -f2,3 | tr '\n' ' ')\""
      note pass false; return 0
    fi
    [ -s "$QREC" ] || { STOP="the qualification wrote no record (exit $rc)"; return 1; }
    note verdict "$(vm qualify-verdict "$QREC")"
    [ "$rc" = 0 ] && note pass true || note pass false
    return 0
  fi
  need "the full qualification" d_qualify "$QREC" ${args[@]+"${args[@]}"} || return 1
  [ -s "$QREC" ] || { STOP="the qualification wrote no record"; return 1; }
}
step_promote() {
  local build
  if [ "$MODE" = validation ] && [ ! -s "$QREC" ]; then   # qualify left no record (its time box): nothing to promote
    note promoted false; note why '"no qualification record (qualify was time-boxed): not promoted; VALIDATION routes the candidate"'
    return 0
  fi
  build=$(jget "$QREC" "builds.$1.build_id")
  [ -n "$build" ] || build=$(jget "$QREC" "builds.$1")   # an older record form: the build id itself
  [ -n "$build" ] || { STOP="the qualification record names no $1 build (builds.$1)"; return 1; }
  note build "\"$build\""
  if [ "$MODE" = validation ] && [ "$(jget "$QREC" status)" != passed ] && [ "$(jget "$QREC" passed)" != True ]; then
    note promoted false; note why "\"the record did not pass ($(jget "$QREC" status)): not promoted; VALIDATION routes it as $(jget "$QREC" "builds.$1.registry_status")\""
    return 0
  fi
  need "promoting the $1 build" d_promote "$build" "$QREC" || return 1
  note promoted true
  st set "$STEP" promoted_any 1
}
step_resolve() {
  local res="$REC/production-resolves.txt" role build line
  [ -z "$(st kv _ promoted_any)" ] || need "the gateway restarted on the new pins" d_gw_restart || return 1
  d_resolve > "$res" 2>> "$STEP_LOG"; note resolve_exit $?
  [ -s "$res" ] || { STOP="pin_model --resolve printed nothing"; return 1; }
  for role in judge:judge second_opinion:verifier; do   # the routing role and the record's role (D-738)
    build=$(jget "$QREC" "builds.${role#*:}.build_id")
    line=$(grep -E "^${role%%:*} D3 -> " "$res" | head -n 1)
    note "${role%%:*}_d3" "$(printf '%s' "$line" | "$PY" -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    if [ "$MODE" != validation ]; then
      case "$line" in "${role%%:*} D3 -> $build "*) ;; *) STOP="PRODUCTION resolves ${role%%:*} to '${line:-nothing}', not to the promoted build $build"; return 1 ;; esac
    fi
  done
  [ "$MODE" = validation ] || note production_resolves_promoted true
}
cid() { dc ps -q "$1" 2>/dev/null | head -n 1; }
wsl_kernel_into() {  # $1 a serving record (tb-serving-config/1) this script wrote; [$2 /proc/version, $3 the release]
  # The record's wsl_kernel (the owner's ask of 2026-11-13, for another lane's version check): the kernel release
  # (uname -r) when /proc/version or the release says WSL2 ("microsoft" or "WSL2"), else null. The schema's validate
  # allows a field it does not name; nothing else of the record changes. A record that is not there is left alone.
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
  need "the serving capture" d_capture "$REC/serving_config.json" || return 1
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
  if [ ! -s "$REC/doctor.json" ]; then   # validation: said, not a stop (the run's evidence is the accuracy group)
    [ "$MODE" = validation ] && { note pass false; note why "\"trialbox doctor --json wrote nothing\""; return 0; }
    STOP="trialbox doctor --json wrote nothing"; return 1
  fi
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
  note qualify_exit "$rc"; note status "\"$(jget "$REC/qualification-g10.json" status)\""
  [ "$rc" = 0 ] && [ "$(jget "$REC/qualification-g10.json" status)" = passed ] && note pass true || note pass false
}

# ================================================================== acc (the public accuracy run on the installed box)
ACC="$TB/acc"; ACCT="$TB/acc-tools"
ONBOX="$ACCT/tools/public_accuracy/onbox.py"
DCCMD="docker compose --project-directory $BOXROOT/deploy"
acc_call() {  # acc_call <service> <onbox command> [JSON argument]
  local arg=${3:-}; [ -n "$arg" ] || arg='{}'
  vm acc-call --dc "$DCCMD" --onbox "$ONBOX" --log "$STEP_LOG" --beat "$HB" --svc "$1" --cmd "$2" --arg "$arg"
}
envset_box() { sed -i "/^$1=/d" "$BOXROOT/deploy/.env" && printf '%s=%s\n' "$1" "$2" >> "$BOXROOT/deploy/.env"; }
acc_compile_only() { case "$1" in tfda|jrct|chia) return 0 ;; *) return 1 ;; esac; }   # as plan.RUN_A's screen=False
acc_fetch_set() { case "$1" in trec2023) echo trec ;; *) echo "$1" ;; esac; }          # as plan.RUN_A's fetch
step_acc_tools() {
  # a launch after the start's: the direct route installs no systemd unit, so the stack is brought up here (a no-op
  # when it runs)
  [ -z "$DIRECT" ] || { WATCH_IO=1 watched d_direct_up; note stack_up_exit $?; }
  rm -rf "${ACCT:?}"; mkdir -p "$ACCT" "$ACC"
  need "fetching lane G's accuracy tools (tb-acc-tools)" fetch "$ACC_TOOLS" "$TB/acc-tools.tgz" || return 1
  need "unpacking them (on the VM, never into the box)" tar -xzf "$TB/acc-tools.tgz" -C "$ACCT" || return 1
  [ -f "$ONBOX" ] || { STOP="the tools tarball has no tools/public_accuracy/onbox.py"; return 1; }
  note sha256 "\"$(sha256sum "$TB/acc-tools.tgz" | cut -d' ' -f1)\""; note sets "\"$ACC_SETS\""
}
first_of() { "$PY" -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]) or []; print(v[0] if v else "")' "$1" "$2"; }
step_acc_settings() {
  local name
  acc_call mail-gateway env > "$REC/acc-settings-before.json" || { STOP="the box's settings cannot be read (onbox env)"; return 1; }
  # the product's own declared settings for the run's limits (D-775, and the mail one): the answers' env_extra sets
  # both at install; a box without them gets them here. Recorded before and after.
  [ "$(envget TB_JOBS_PER_SENDER_PER_DAY)" = 0 ] || envset_box TB_JOBS_PER_SENDER_PER_DAY 0
  [ "$(envget TB_MAIL_PER_RECIPIENT_PER_DAY)" = 0 ] || envset_box TB_MAIL_PER_RECIPIENT_PER_DAY 0
  # the hospital MTA's id: the answers' mta_authserv_id (D-825) writes it; only a box with none gets the run's
  if [ -n "$(envget TB_MAIL_AUTHSERV_ID)" ]; then note authserv '"the box'"'"'s own (answers: mta_authserv_id)"'
  else envset_box TB_MAIL_AUTHSERV_ID "$ACC_AUTHSERV"; note authserv "\"set by the run: $ACC_AUTHSERV\""; fi
  if [ -n "$ACC_TRIPWIRE" ]; then   # only a setting this tree declares (tb_common.config.DECLARED), never a code change
    name=${ACC_TRIPWIRE%%=*}
    if "$PY" -c 'import json,sys; sys.exit(0 if sys.argv[2] in (json.load(open(sys.argv[1])).get("tripwire_settings") or {}) else 1)' \
         "$REC/acc-settings-before.json" "$name"; then
      envset_box "$name" "${ACC_TRIPWIRE#*=}"; note tripwire "\"set by the declared setting $ACC_TRIPWIRE\""
      note tripwire_env "\"$name=$(envget "$name")\""
    else
      note tripwire "\"on: $name is not a declared setting of this tree (asked: $ACC_TRIPWIRE)\""
    fi
  else
    note tripwire "\"on: no setting used (gateway step 4 runs on every call of class D0 to D2)\""
  fi
  # every service that reads deploy/.env, not the two model servers (their settings did not change; a reload of both
  # is minutes of the card for nothing)
  local svcs=(); mapfile -t svcs < <(dc config --services | grep -v '^llm-')
  need "the stack recreated on the new settings (not the model servers)" d_recreate "${svcs[@]}" || return 1
  acc_call mail-gateway env > "$REC/acc-settings-after.json" || { STOP="the box's settings cannot be read after the change"; return 1; }
  st set "$STEP" acc_sender "$(first_of "$REC/acc-settings-after.json" senders)"
  st set "$STEP" acc_reviewer "$(first_of "$REC/acc-settings-after.json" reviewers)"
  { [ -n "$(st kv _ acc_sender)" ] && [ -n "$(st kv _ acc_reviewer)" ]; } || { STOP="the box's settings name no sender or no reviewer"; return 1; }
  note limits "$("$PY" -c 'import json,sys
b, a = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
k = ("rate_limit_per_sender_per_day", "rate_limits_per_day", "jobs_per_sender_per_day", "mail_per_recipient_per_day", "authserv")
print(json.dumps({"before": {x: b.get(x) for x in k}, "after": {x: a.get(x) for x in k}, "environment": a.get("environment")}))' \
    "$REC/acc-settings-before.json" "$REC/acc-settings-after.json")"
}
step_acc_routes() {
  local dcls jcls ccls
  dcls=$(envget TB_DATA_CLASS); jcls=${dcls:-D3}; ccls=${dcls:-D1}   # a phi prompt is D3, the others D1 (tb_llm v1_labels)
  acc_call gateway routes "{\"calls\": [[\"judge\", \"$jcls\"], [\"extract_criteria\", \"$ccls\"], [\"concept_select\", \"$ccls\"]]}" \
    > "$RUN/logs/acc-routes-gw.json" || { STOP="the gateway's routes cannot be read (onbox routes)"; return 1; }
  acc_call orchestrator embedder > "$RUN/logs/acc-embedder.json" || echo '{}' > "$RUN/logs/acc-embedder.json"
  [ -s "$REC/serving_config.json" ] || d_capture "$REC/serving_config.json" >> "$STEP_LOG" 2>&1
  vm acc-routes "$RUN/logs/acc-routes-gw.json" "$RUN/logs/acc-embedder.json" --notes "$NOTES" > "$REC/acc-routes.json" \
    || { STOP="TB-ACC-BLOCKED: the box would refuse the run's calls in $(jget "$REC/acc-routes.json" environment): $(jget "$REC/acc-routes.json" blocked) (a product defect, not worked around)"; return 1; }
}
acc_today() {  # the box's day for the built sites (kept in the state: a resumed run builds on the same day)
  local d; d=$(st kv _ acc_ref)
  [ -n "$d" ] || { d=${TB_BOXRUN_TODAY:-$(TZ="$(envget TB_TZ | grep . || echo UTC)" date +%F)}; st set "$STEP" acc_ref "$d"; }
  echo "$d"
}
step_acc_data() {
  local ref item name size img
  ref=$(acc_today); img=$(img_py); note ref "\"$ref\""
  for item in $ACC_SETS; do
    name=${item%%:*}; size=${item#*:}
    [ -f "$ACC/$name/built/gold/ids.json" ] && { echo "set $name: built before (kept)" >> "$STEP_LOG"; continue; }
    rm -rf "${ACC:?}/${name:?}/built"; mkdir -p "$ACC/$name"
    watched d_acc_py fetch --only "$(acc_fetch_set "$name")" || note "fetch_failed_$name" true
    # a set that cannot be fetched or built (a public source down) is left out of this run, said; the others go on
    if [ "$name" = jmed ]; then   # pyarrow: the box's python image, no network (the file is fetched above)
      watched d_acc_img -v "$ACC/$name:/work" "$img" python -m tools.public_accuracy build --set "$name" --size "$size" \
          --out /work --ref "$ref" --for-box
    else
      watched d_acc_py build --set "$name" --size "$size" --out "$ACC/$name" --ref "$ref" --for-box
    fi
    if [ ! -f "$ACC/$name/built/gold/ids.json" ]; then
      note "skipped_$name" "\"not built: $(grep -E 'Error|error' "$STEP_LOG" | tail -n 1 | cut -c1-160 | tr -d '"\\')\""
      rm -rf "${ACC:?}/${name:?}/built"
    fi
  done
}
# the site's own setting for the tables a public-data site does not have (settings.yaml feed_completeness.optional_tables,
# deploy/settings.example.yaml:44): every table of the mapping (data_source.mapping, in the box's image) that the
# merged feed holds no row of. Without it the first night is held ("table missing and no earlier good night had it",
# F17). And the site's threshold for the FHIR validator's sample (thresholds.validation_error_max_pct, 0.5 by default)
# at 10 %: the public sets' patients carry no birth date where the source has none (TCGA reports), and 4 of 108
# sampled Patients failed the minimum profile on the first full night (F20); the threshold only gates loading, it
# changes no screening answer. Written in the box's image, checked by the settings wizard, recorded before and after.
ACC_OPTIONAL='
import csv, json, pathlib, sys, yaml
p, feed = "/d/settings.yaml", pathlib.Path("/feed")
text = open(p, encoding="utf-8").read()
head = "".join(x for x in text.splitlines(True) if x.startswith("#"))
doc = yaml.safe_load(text) or {}
rel = (doc.get("data_source") or {}).get("mapping") or "mapping/tw_core/demo_his.yaml"
m = next((q for q in (pathlib.Path("/d/site") / rel, pathlib.Path("/app/services/adapter") / rel) if q.is_file()), None)
tables = list((yaml.safe_load(open(m, encoding="utf-8")) or {}).get("tables") or {}) if m else []
def rows(t):
    f = feed / (t + ".csv")
    if not f.is_file():
        return 0
    with open(f, encoding="utf-8-sig", newline="") as fh:
        return max(0, sum(1 for _ in csv.reader(fh)) - 1)
before = dict(doc.get("feed_completeness") or {})
opt = sorted(set(before.get("optional_tables") or []) | {t for t in tables if t != "patient" and rows(t) == 0})
doc["feed_completeness"] = {**before, "optional_tables": opt}
th = dict(doc.get("thresholds") or {})
vbefore = th.get("validation_error_max_pct")
th["validation_error_max_pct"] = max(float(vbefore or 0), 10.0)
doc["thresholds"] = th
open(p, "w", encoding="utf-8").write(head + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
print(json.dumps({"mapping": str(m), "before": before, "after": doc["feed_completeness"],
                  "validation_error_max_pct": {"before": vbefore, "after": th["validation_error_max_pct"]}}))
'
d_optional_tables() {  # $1 the merged feed folder on the host
  docker run --rm --network none --user 0 -v "$BOXROOT/deploy:/d" -v "$1:/feed:ro" "$(img_py)" sh -c \
    "python -c '$ACC_OPTIONAL' && python -m tools.settings_wizard --check /d/settings.yaml"
}
step_acc_ingest() {
  local feed mount sites=() item ref snap before t0
  feed=$(envget TB_SOURCE_DIR); mount=$(envget TB_SOURCE_MOUNT)
  { [ -n "$feed" ] && [ -n "$mount" ]; } || { STOP="no feed folder (TB_SOURCE_DIR, TB_SOURCE_MOUNT in deploy/.env)"; return 1; }
  case "$feed" in /*) ;; *) feed="$BOXROOT/deploy/$feed" ;; esac
  for item in $ACC_SETS; do   # the sets 53 built (a set left out there has no site)
    [ -d "$ACC/${item%%:*}/built/site/hospital" ] && sites+=("$ACC/${item%%:*}/built/site/hospital")
  done
  [ ${#sites[@]} -gt 0 ] || { STOP="no accuracy set was built (53)"; return 1; }
  need "the sets' hospital feeds as one feed in the box's feed folder (acc/)" vm acc-merge-feed --into "$feed/acc" "${sites[@]}" || return 1
  need "the site's optional tables for a public-data feed (settings.yaml feed_completeness)" d_optional_tables "$feed/acc" || return 1
  ref=$(acc_today); snap=$(date -d "$ref -1 day" +%F); note snapshot "\"$snap\""
  before=$(d_current 2>/dev/null)
  need "the box's ingest of the feed" d_ingest "$mount/acc" "$snap" || return 1
  t0=$(date +%s)
  while [ "$(d_current 2>/dev/null)" = "$before" ]; do
    touch "$HB"
    [ $(($(date +%s) - t0)) -lt $((ACC_JOB_MIN * MIN_S)) ] || { STOP="the lake did not publish the ingest in $ACC_JOB_MIN minutes"; return 1; }
    sleep "$POLL"
  done
  note current "\"$(d_current 2>/dev/null)\""
}
# the set in flight, for its progress line and its partial upload (PROG_FN of watched)
ACC_CUR=""
prog_acc() {
  local p
  p=$(vm acc-progress --work "$ACC/$ACC_CUR/work" --built "$ACC/$ACC_CUR/built")
  acc_pack "$ACC_CUR" partial
  "$PY" -c 'import json,sys; d=json.loads(sys.argv[1]); print("set %s: protocols %s/%s, patients answered %s, set clock %s of %s s;" % (sys.argv[2], d["protocols_done"], d["protocols"], d["patients_answered"], d["used_s"], d["deadline_s"]))' "$p" "$ACC_CUR"
}
ACC_UP=false
acc_pack() {  # acc_pack <set> [partial]: the set's gold, provenance and work so far to the bucket (ACC_UP: uploaded)
  local name=$1 where=acc
  [ "${2:-}" = partial ] && where=acc-partial
  mkdir -p "$ACC/$name/built/site-provenance"; cp "$ACC/$name/built/site/PROVENANCE.md" "$ACC/$name/built/site-provenance/" 2>/dev/null
  tar -czf "$ACC/$name.$where.tgz" -C "$ACC/$name" built/gold built/site-provenance work 2>> "$STEP_LOG" || return 1
  ACC_UP=false
  if [ -n "$BUCKET" ] && gcloud storage cp "$ACC/$name.$where.tgz" "$BUCKET/boxruns/$RUN_ID/$where/$name.tgz" >/dev/null 2>&1; then ACC_UP=true; fi
  return 0
}
# each set's own time budget (the lead's order of 2026-11-15): 1.5 x its plan high bound (tb-acc-plan, from
# tools/public_accuracy/plan.py) x the box's measured slowdown r (the first set finished: its seconds / its plan high);
# before r is known, 4 x (a first set must be able to measure it). At least ten minutes.
acc_deadline() {
  local name=$1 high r
  [ -z "$ACC_DEADLINE" ] || { echo "$ACC_DEADLINE"; return 0; }
  high=$(printf '%s\n' $ACC_PLAN | sed -n "s/^$name:[0-9]*://p" | head -n 1)
  r=$(st kv _ acc_rate); [ -n "$r" ] || r=4
  "$PY" -c 'import sys; h, r, m = float(sys.argv[1] or 0), float(sys.argv[2]), float(sys.argv[3]); print(int(max(m, 1.5 * h * r)) if h else 0)' "${high:-0}" "$r" "$ACC_MIN_DL"
}
step_acc_set() {
  local name=$1 co=() up=false t0 dl high sec r
  if [ ! -f "$ACC/$name/built/gold/ids.json" ]; then   # left out at 53 (its source could not be fetched or built)
    note skipped "\"not built at 53-acc-data (see its notes)\""; note pass false; return 0
  fi
  acc_compile_only "$name" && co=(--compile-only)
  t0=$(st kv _ "acc_t0_$name"); [ -n "$t0" ] || { t0=$(date -u +%FT%T); st set "$STEP" "acc_t0_$name" "$t0"; }
  dl=$(acc_deadline "$name"); note deadline_s "${dl:-0}"; note rate_used "\"$(st kv _ acc_rate | grep . || echo 'not measured yet: 4')\""
  # the sender and the reviewer as the box's settings name them NOW (a 51 kept from an earlier boot may have read
  # other settings: F16 left the example's in place then, F18)
  if acc_call mail-gateway env > "$RUN/logs/acc-env-$name.json" 2>> "$STEP_LOG"; then
    st set "$STEP" acc_sender "$(first_of "$RUN/logs/acc-env-$name.json" senders)"
    st set "$STEP" acc_reviewer "$(first_of "$RUN/logs/acc-env-$name.json" reviewers)"
  fi
  note sender "\"$(st kv _ acc_sender)\""; note reviewer "\"$(st kv _ acc_reviewer)\""
  ACC_CUR=$name
  WATCH_GPU=1 PROG_FN=prog_acc need "the set $name through the box (FEAS, APPROVE, SCREEN by mail; box_vm.py acc-set)" \
    vm acc-set --set "$name" --built "$ACC/$name/built" --work "$ACC/$name/work" --onbox "$ONBOX" --dc "$DCCMD" \
      --sender "$(st kv _ acc_sender)" --reviewer "$(st kv _ acc_reviewer)" --run-id "$RUN_ID" ${co[@]+"${co[@]}"} \
      --job-minutes "$ACC_JOB_MIN" --poll "$POLL" --notes "$NOTES" --beat "$HB" --deadline-s "${dl:-0}" || return 1
  # the box's measured slowdown, from the first set that finished: its seconds over its plan high bound
  if [ -z "$(st kv _ acc_rate)" ]; then
    high=$(printf '%s\n' $ACC_PLAN | sed -n "s/^$name:[0-9]*://p" | head -n 1)
    sec=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("used_s") or 0)' "$ACC/$name/work/set-clock.json" 2>/dev/null)
    r=$("$PY" -c 'import sys; s, h = float(sys.argv[1] or 0), float(sys.argv[2] or 0); print(round(max(0.05, s / h), 3) if h > 0 and s > 0 else "")' "${sec:-0}" "${high:-0}")
    if [ -n "$r" ]; then st set "$STEP" acc_rate "$r"; note rate_measured "$r"; fi
  fi
  acc_call gateway audit "{\"since\": \"$t0\"}" > "$ACC/$name/work/gateway-audit.json" 2>> "$STEP_LOG" || rm -f "$ACC/$name/work/gateway-audit.json"
  # the raw answers (both models' outputs per call, as the box's trace store keeps them): with the set's results in
  # the bucket and the operator's run folder, never committed
  acc_call gateway traces "{\"since\": \"$t0\"}" > "$ACC/$name/work/raw-traces.json" 2>> "$STEP_LOG" \
    && note raw_traces "$(jget "$ACC/$name/work/raw-traces.json" calls)" || { rm -f "$ACC/$name/work/raw-traces.json"; note raw_traces '"not read"'; }
  acc_pack "$name" || { STOP="the set $name could not be packed"; return 1; }
  up=$ACC_UP
  mkdir -p "$RUN/acc/$name"; cp "$ACC/$name/work/answers.json" "$RUN/acc/$name/" 2>/dev/null
  note uploaded "$up"
}
step_acc_result() {
  local sets ok
  sets=$("$PY" - "$RUN/parts" <<'PY'
import json, sys
from pathlib import Path
rows = {}
for p in sorted(Path(sys.argv[1]).glob("6*-acc-*.json")):
    d = json.loads(p.read_text())
    rows[p.stem[7:]] = {"status": d.get("status"), "pass": d.get("pass"), "counts": (d.get("detail") or {}).get("counts")}
print(json.dumps(rows))
PY
)
  note sets "$sets"
  ok=$("$PY" -c 'import json,sys; r=json.loads(sys.argv[1]); print("true" if r and all(v["pass"] for v in r.values()) else "false")' "$sets")
  note pass "$ok"
}


# ================================================================== the probe (facts a review cannot know without the VM)
# Read-only: what is on the VM and, after the install, on the box. Names, sizes, versions and exit codes only: no
# key, token or password is read or printed (secret FILES are listed by name and mode, never opened).
probe_cmd() { printf '\n$ %s\n' "$*"; timeout 120 "$@" 2>&1 | head -n 200; printf '[exit %s]\n' "${PIPESTATUS[0]}"; }
step_facts() {
  local f="$REC/facts-vm.txt"
  {
    probe_cmd df -h
    probe_cmd findmnt -no TARGET,FSTYPE,SIZE,AVAIL /tmp
    probe_cmd du -sh /var/lib/docker /var/lib/containerd /models /models/hub /srv/tb-build "$TB" "$BOXROOT"
    probe_cmd ls -la /models /models/hub
    probe_cmd docker info -f '{{.ServerVersion}} {{.Driver}} {{json .DriverStatus}}'
    probe_cmd docker compose version
    probe_cmd docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}'
    probe_cmd docker system df
    probe_cmd cat /etc/docker/daemon.json
    probe_cmd python3 --version
    probe_cmd python3 -c 'import yaml, sys; print("yaml", yaml.__version__)'
    probe_cmd python3 -c 'import cryptography; print("cryptography", cryptography.__version__)'
    probe_cmd systemctl --version
    probe_cmd sh -c 'command -v systemd-creds; ls -l /dev/tpm0 /dev/tpmrm0'
    probe_cmd nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
    probe_cmd sh -c 'ss -ltnp | head -40'
    probe_cmd sh -c 'command -v uv mvn java curl git make nft gcloud'
    probe_cmd cat /etc/os-release
    probe_cmd docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}'
    probe_cmd sh -c 'ls -ld /etc/cron.d; command -v nft cron crontab'
    probe_cmd sh -c 'ls -d /models/hub/models--*/snapshots/* 2>/dev/null'
    probe_cmd sh -c 'du -sh /models/hub/models--* 2>/dev/null'
    probe_cmd sh -c 'ls -la /models/embedder /models/chat-templates 2>&1 | head -40'
    probe_cmd sh -c 'f=$(find /models/hub -name "*.safetensors" -size +1G 2>/dev/null | head -n 1); [ -n "$f" ] && sync && echo 3 > /proc/sys/vm/drop_caches && dd if="$f" of=/dev/null bs=16M count=128 2>&1 | tail -n 1'
  } > "$f"
  note facts_vm "\"records/facts-vm.txt\""
}
step_facts_box() {
  local f="$REC/facts-box.txt" g
  {
    probe_cmd ls -la "$BOXROOT" "$BOXROOT/deploy" "$BOXROOT/deploy/site" "$BOXROOT/deploy/secrets" "$BOXROOT/deploy/secrets/services" "$BOXROOT/deploy/models"
    probe_cmd readlink -f "$BOXROOT/current"
    probe_cmd sh -c "sed 's/=.*//' '$BOXROOT/deploy/.env' | sort"   # names only
    probe_cmd sh -c "grep -E '^(TB_ENV|TB_TOPOLOGY|TB_PROFILE|COMPOSE_FILE|COMPOSE_PROFILES|TB_SOURCE_DIR|TB_SOURCE_MOUNT|TB_TZ|TB_JOBS_PER_SENDER_PER_DAY|TB_MAIL_PER_RECIPIENT_PER_DAY|TB_MAIL_AUTHSERV_ID|TB_GATEWAY_PHI_TRIPWIRE|TB_BACKUP_ALERT_ROUTE|JUDGE_MODEL_DIR|VERIFIER_MODEL_DIR|TB_IMAGE|TB_DATA_CLASS)=' '$BOXROOT/deploy/.env'"
    probe_cmd docker compose --project-directory "$BOXROOT/deploy" ps --format '{{.Service}} {{.State}} {{.Health}} {{.Image}}'
    probe_cmd sh -c "ls -la '$BOXROOT/deploy/site/registry.site.yaml' && grep -E 'build|sha256|status|served' '$BOXROOT/deploy/site/registry.site.yaml' | head -40"
    for g in gateway orchestrator mail-gateway llm-service llm-verifier model-guard embed-service; do
      probe_cmd docker inspect -f '{{.Name}} {{range $k, $v := .NetworkSettings.Networks}}{{$k}}={{$v.IPAddress}} {{end}} {{json .Config.Cmd}} {{json .Mounts}}' "$(cid "$g")"
    done
    probe_cmd docker network ls
    probe_cmd docker run --rm --network none "$(img_py)" python -c 'import os; print(os.getcwd(), sorted(os.listdir("/app")))'
    probe_cmd sh -c "docker compose --project-directory '$BOXROOT/deploy' exec -T orchestrator python -c 'import urllib.request as u; print(u.urlopen(\"http://gateway:8020/healthz\", timeout=10).status)'"
    probe_cmd sh -c "docker compose --project-directory '$BOXROOT/deploy' exec -T gateway python -c 'import os; print(sorted(k for k in os.environ if k.startswith((\"TB_EP_\",\"TB_LLM_\",\"TB_GATEWAY_\",\"TB_ENV\",\"TB_TRACESTORE\"))))'"
    probe_cmd sh -c "docker compose --project-directory '$BOXROOT/deploy' exec -T orchestrator python -c 'from tb_llm.prompt_registry import default_registry as d; print([(e.id, e.version) for e in d().served_set(\"VALIDATION\")])'"
    probe_cmd sh -c "tail -n 60 '$TB/install-v.log'"
  } > "$f"
  note facts_box "\"records/facts-box.txt\""
}
# ------------------------------------------------------------------ the run
# a later boot of a direct-route box (a resume, or an acc launch): the stack as this tree starts it (the weights' bind,
# the site's settings.yaml, every service healthy) before any step, since no systemd unit does it on this route (F15,
# F16). Said in the log; a stack that cannot come up is the next step's stop, with its own log.
st02=$(st get 02-install)
if [ -n "$DIRECT" ] && [ -s "$BOXROOT/deploy/.env" ] \
   && { [ "$st02" = "done" ] || { has acc && ! has dev && ! has start; }; }; then
  echo "TB-STACK $(date -u +%T): bringing the box's stack up on this boot (compose up --wait)" | tee -a "$LOG"
  d_direct_up >> "$LOG" 2>&1 && echo "TB-STACK up" | tee -a "$LOG" || echo "TB-STACK not healthy (see the log)" | tee -a "$LOG"
fi
[ -z "$PROBE" ] || run_step 00-facts step_facts
if has probe; then   # a facts-only launch: the VM's facts, then the run ends (no build, no install)
  run_step 00-facts step_facts
  finish "TB-PROBE-DONE: the VM's facts are in records/facts-vm.txt; nothing was built or installed" probe-done 0
fi
if has build; then
  run_step b01-source step_b_source
  run_step b02-venv step_b_venv
  run_step b03-images step_b_images
  run_step b04-gates step_b_gates
  run_step b05-sign step_b_sign
  run_step b06-verify step_b_verify
  run_step b07-upload step_b_upload
fi
if has dev; then   # the lead's order (2026-11-15): the latest commit's images built here, its tree, the direct route
  run_step b01-source step_b_source
  run_step b02-venv step_b_venv
  run_step b03-images step_b_images
  run_step d04-tree step_dev_tree
  DIRECT=1
fi
if has start || has dev; then
  has dev || run_step 01-bundle step_bundle
  if [ -n "$DIRECT" ]; then run_step 02-install step_direct_up; else run_step 02-install step_install; fi
  if [ "$MODE" = validation ]; then run_step 03-wizard step_venv_env; else run_step 03-wizard step_wizard; fi
  if [ -n "$PROBE" ]; then
    run_step 04p-facts step_facts_box
    finish "TB-PROBE-DONE: the VM's and the box's facts are in records/facts-*.txt; the run stops here" probe-done 0
  fi
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
if has acc; then
  run_step 50-acc-tools step_acc_tools
  run_step 51-acc-settings step_acc_settings
  run_step 52-acc-routes step_acc_routes
  run_step 53-acc-data step_acc_data
  run_step 54-acc-ingest step_acc_ingest
  n=59; for item in $ACC_SETS; do n=$((n + 1)); run_step "$n-acc-${item%%:*}" step_acc_set "${item%%:*}"; done
  run_step 79-acc-result step_acc_result
fi
finish "TB-BOX-RUN-COMPLETE: every step ran; the parts say which test rules passed" complete 0
