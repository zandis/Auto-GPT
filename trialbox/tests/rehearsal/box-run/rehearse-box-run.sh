#!/usr/bin/env bash
# The local rehearsal of the product-on-GPU run's VM script (gap X-10; plan v7 section 7.1, tests G-2, G-9, G-10).
#
#   tests/rehearsal/box-run/rehearse-box-run.sh [CASE ...]     # every case, about 2 minutes, US$0
#
# It runs the REAL deploy/gcp/box-install-run.sh, unchanged, as the startup script of a "VM" that is a process group on
# this machine, with its disk in a folder. No container, no root, no network, no cloud call. What is replaced:
#   * on the "VM" (shims/): the GCE metadata server (curl), systemd (systemd-run, `systemctl poweroff`), gcloud (Secret
#     Manager and the bucket are folders; any other gcloud call fails and is logged), docker (inspect, restart),
#     nvidia-smi;
#   * lane D's pieces, which land 2026-12-04 (standins/): the installer and its first-run wizard (box-install.sh), the
#     box's tools: pin, qualify, promote, the serving capture, the screen job, doctor, the canary (tool.py);
#   * the bundle: a small synthetic tar with a manifest of the real shape (path, kind, sha256, size);
#   * the driver: this script. It reads the door (TLS, the pinned certificate, the key) and, when the VM asks for the
#     power cycle, "stops and starts" it (standins/reboot.sh: every process killed at once, a new boot id).
# The VM script's limits run on a short clock (TB_BOXRUN_MINUTE_S=1: a "minute" is a second), so the cap and the
# watchdog are the script's own code paths in seconds.
# The cases:
#   happy         all sixteen steps; the power cycle is asked for and done; results over the door; power-off once
#                 collected
#   step-fails    the qualification fails: the run stops there with the step's record (reason, log tail); a later boot
#                 hands the same results over and runs nothing again
#   reboot        the VM is cut off in the middle of the qualification: the next boot keeps the finished steps (the
#                 installer and the wizard run once) and runs the cut step again
#   cap           the cost cap fires during a long step: power-off with a results.tgz; the next boot ends at once with
#                 TB-CAP-REACHED (the cap counts every boot of the run)
#   bad-hash      a file of the bundle differs from its manifest: refused, the installer never runs
#   bad-tar-hash  the bundle is not the one the driver declared: refused, never unpacked
#   paid-twice    a box that repeats more calls than were in flight: the G-9 parts say "pass": false, the run goes on
# Every case is checked by check.py; the evidence stays in $TB_BOXRUN_REHEARSAL_DIR/<case>/ (default
# /tmp/tb-boxrun-rehearsal). Needs: bash, python3, curl, openssl, tar, setsid.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REH="${TB_BOXRUN_REHEARSAL_DIR:-/tmp/tb-boxrun-rehearsal}"
# shellcheck disable=SC2206  # CASES=happy,cap: split on commas and spaces
CASES=(${*//,/ }); [ "${#CASES[@]}" -gt 0 ] || CASES=(happy step-fails reboot cap bad-hash bad-tar-hash paid-twice)
# the harness's own ceiling for one wait (a declared setting): a whole case takes 10 to 30 seconds on the short clock,
# so 120 seconds without the awaited event means the case is broken, not slow
WAIT_S="${TB_BOXRUN_REHEARSAL_WAIT_S:-120}"
log() { echo "$(date -u +%T) rehearse-box-run: $*"; }
S=""
vm_kill() { [ -z "$S" ] || [ ! -f "$S/vm.pgid" ] || kill -KILL -- "-$(cat "$S/vm.pgid")" 2>/dev/null || true; }
trap vm_kill EXIT
die() { log "FAIL: $*"; [ -z "$S" ] || tail -n 25 "$S"/boot-*.out 2>/dev/null || true; exit 1; }
wait_for() {  # wait_for <what> <command...>
  local what=$1 t0=$SECONDS; shift
  until "$@" >/dev/null 2>&1; do
    [ $((SECONDS - t0)) -lt "$WAIT_S" ] || die "waited $WAIT_S s for: $what"
    sleep 0.2
  done
}
door() {  # door <curl args> <path>: as the driver reaches the VM: TLS, the pinned certificate, the key
  /usr/bin/curl -fsS --noproxy '*' --max-time 10 --cacert "$S/driver/door.crt" --resolve "tb-door:$PORT:127.0.0.1" \
    -H @"$S/driver/hdr" "${@:1:$#-1}" "https://tb-door:$PORT${!#}"
}
asks_power() { door /tb/progress | grep -q '^POWER-CYCLE-REQUESTED$'; }
is_done() { grep -q '^BOX-RUN-DONE$' "$S/boot-$(cat "$S/boots").out"; }   # this boot's own console, not an older marker
is_off() { [ "$(cat "$S/status")" = TERMINATED ]; }
collect() {  # the results over the door, unpacked into the evidence; a call without the key is refused
  mkdir -p "$S/evidence/results"
  door -o "$S/evidence/results.tgz" /tb/results.tgz
  tar -xzf "$S/evidence/results.tgz" -C "$S/evidence/results"
  code=$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 10 --cacert "$S/driver/door.crt" \
    --resolve "tb-door:$PORT:127.0.0.1" "https://tb-door:$PORT/tb/results.tgz")
  echo "$code" > "$S/evidence/no-key-http-code"
}

setup() {  # setup <case> [knob ...]: a fresh "VM": metadata, the door's secret, the answers, the bundle, the box root
  local k
  S="$REH/$1"; rm -rf "$S"
  mkdir -p "$S"/{metadata,knobs,secrets/door,secrets/answers,driver,evidence,boxroot/deploy,boxroot/tools,models/judge,models/verifier,disk}
  for k in "${@:2}"; do touch "$S/knobs/$k"; done
  PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$S/driver/door.key" -out "$S/driver/door.crt" -days 2 \
    -subj /CN=tb-door -addext subjectAltName=DNS:tb-door >/dev/null 2>&1
  (umask 077
   python3 - "$S" <<'PY'
import hashlib, io, json, os, secrets, sys, tarfile
s = sys.argv[1]
key = secrets.token_hex(24)   # a random key of this rehearsal only, never printed
json.dump({"key": key, "tls_key": open(f"{s}/driver/door.key").read()}, open(f"{s}/secrets/door/1", "w"))
open(f"{s}/driver/hdr", "w").write(f"Authorization: Bearer {key}\n")
# the wizard's answers: a synthetic site (no real name, address or passphrase)
open(f"{s}/secrets/answers/1", "w").write("site_id: REHEARSAL-BOXRUN\nsite_name: synthetic hospital\ntz: Asia/Taipei\n")
# the bundle: synthetic payloads, a manifest of the real shape (tools/sign_bundle.py: path, kind, sha256, size)
payloads = {"trialbox-host.tar": ("host", b"synthetic host tree\n" * 64), "images/app.tar": ("image", os.urandom(4096)),
            "rulesets/rules.json": ("ruleset", b'{"synthetic": true}\n')}
files = [{"path": p, "kind": k, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for p, (k, b) in payloads.items()]
if os.path.exists(f"{s}/knobs/bad-hash"):   # one payload is not what the manifest says (same size)
    payloads["images/app.tar"] = ("image", os.urandom(4096))
manifest = json.dumps({"release": "0.0.0-rehearsal", "files": files}).encode()
with tarfile.open(f"{s}/disk/bundle.tar", "w") as tar:
    for name, data in [("manifest.json", manifest)] + [(p, b) for p, (_, b) in payloads.items()]:
        info = tarfile.TarInfo(name); info.size = len(data); tar.addfile(info, io.BytesIO(data))
PY
  )
  cp "$HERE/standins/box-install.sh" "$S/boxroot/deploy/box-install.sh"
  : > "$S/boxroot/tools/__init__.py"
  for t in pin_model qualify serving_config screen_job trialbox canary; do cp "$HERE/standins/tool.py" "$S/boxroot/tools/$t.py"; done
  echo "standin/model-server:new" > "$S/knobs/vllm-image"
  echo "snapshot-rehearsal-1" > "$S/disk/CURRENT"
  m() { printf '%s' "$2" > "$S/metadata/$1"; }
  m tb-run-id "rehearsal-$1"; m tb-door-secret door; m tb-door-version 1; m tb-door-port "$PORT"
  cp "$S/driver/door.crt" "$S/metadata/tb-door-cert"
  m tb-bundle "$S/disk/bundle.tar"; m tb-bundle-sha256 "$(sha256sum "$S/disk/bundle.tar" | cut -d' ' -f1)"
  m tb-box-root "$S/boxroot"; m tb-answers-secret answers; m tb-answers-version 1
  m tb-models-root "$S/models"; m tb-current-file "$S/disk/CURRENT"; m tb-g10-vllm-image "standin/model-server:new"
  m tb-patients 500; m tb-done-grace 3
  : > "$S/calls.log"; : > "$S/vm-gcloud.log"
}
boot() { "$HERE/standins/boot.sh" "$S"; }
power_cycle() { wait_for "the VM to ask for the power cycle" asks_power; "$HERE/standins/reboot.sh" "$S"; }
to_the_end() {  # done, the results collected over the door, the VM told so, power-off
  wait_for "the done marker" is_done
  collect; door -o /dev/null -X POST /tb/collected
  wait_for "the power-off once collected" is_off
}

for case in "${CASES[@]}"; do
  log "case $case"
  case "$case" in
    happy)
      setup "$case"; boot; power_cycle; to_the_end ;;
    paid-twice)
      setup "$case" repeat-many; boot; power_cycle; to_the_end ;;
    step-fails)
      setup "$case"; touch "$S/knobs/fail-qualify"; boot
      wait_for "the done marker" is_done
      wait_for "the power-off after the grace (nobody collected)" is_off
      boot; to_the_end ;;                      # the driver starts it again for the results: nothing runs again
    reboot)
      setup "$case"; echo 3 > "$S/knobs/qualify-seconds"; boot
      wait_for "the qualification to be running" grep -q '^qualify$' "$S/calls.log"
      "$HERE/standins/reboot.sh" "$S"          # a cut in the middle of step 05, not asked for
      power_cycle; to_the_end ;;
    cap)
      setup "$case"; echo 60 > "$S/knobs/qualify-seconds"; printf 4 > "$S/metadata/tb-max-minutes"; boot
      wait_for "the power-off by the cap" is_off
      cp "$S/vm/tb/out/results.tgz" "$S/evidence/results-at-cap.tgz"
      boot; to_the_end ;;
    bad-hash)
      setup "$case" bad-hash; boot; to_the_end ;;
    bad-tar-hash)
      setup "$case"; printf '%064d' 0 > "$S/metadata/tb-bundle-sha256"; boot; to_the_end ;;
    *) die "no such case: $case" ;;
  esac
  python3 "$HERE/check.py" "$case" "$S" || die "case $case: the checks above"
  vm_kill
  log "case $case passed"
done
log "all cases passed: ${CASES[*]}"
