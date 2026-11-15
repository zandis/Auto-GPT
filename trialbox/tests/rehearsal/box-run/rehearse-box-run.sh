#!/usr/bin/env bash
# The local rehearsal of the box run's VM script (deploy/gcp/box-install-run.sh: R2's bundle build, G-2, G-6, G-9,
# G-10) and of the helper the VM runs (deploy/gcp/box_vm.py). US$0, no network, no container, no root.
#
#   tests/rehearsal/box-run/rehearse-box-run.sh [CASE ...]     # every case, a few minutes
#
# The VM script runs unchanged as the startup script of a "VM" that is a process group on this machine, with its disk
# in a folder; a "minute" of its limits is a second (TB_BOXRUN_MINUTE_S=1). What is REAL here:
#   * deploy/gcp/box-install-run.sh and deploy/gcp/box_vm.py (the code under test);
#   * the bundle format and its signature: tools/sign_bundle.py signs, tools/verify_update.py checks (b06), over the
#     real host tree of this checkout (tools/host_tree.py pack), so 01-bundle unpacks the real deploy/box-install.sh;
#   * deploy/box-install.sh itself (prepare, the one-time code on the box's screen, the wait, the apply with
#     tools.box in the repo's venv) and the console's first-run pages (console.app with console.firstrun, over TLS),
#     answered by box_vm.py wizard as a browser would;
#   * models/registry.yaml, deploy/images.lock and the prompt registry the identity record (06-g1) reads.
# What is a STAND-IN, and what the paid run puts in its place:
#   * shims/: the GCE metadata server, systemd, gcloud (Secret Manager and the bucket are folders), docker, nvidia-smi
#     -> the VM's own;
#   * standins/install-inner.sh, compose-up.sh, host-check.sh (box-install.sh's own knobs TB_BOX_INSTALL,
#     TB_BOX_COMPOSE, TB_BOX_HOST_CHECK) -> deploy/install.sh, docker compose and deploy/check_host.sh of the bundle;
#   * standins/box.py: the installed box's containers and tools (pin, qualify, doctor, selftest, the screen job, the
#     ingest, the backup, memory in cgroup files) -> the box the real installer starts, with the real models;
#   * standins/console_standin.py: the console's container and Caddy -> the box's console behind Caddy on 443;
#   * the build's `make venv scanners images trivy-db release-gates` and tools/make_bundle.sh (a Makefile and a
#     script in a small git repository made here; the script signs with the real signer, as above) -> the release
#     commit's own targets and make_bundle.sh (docker save of ~12 GB of images);
#   * the vendor key: a throwaway Ed25519 key made here -> the owner's key in Secret Manager.
# The cases:
#   build              R2's build: source, gates, the key fetched by name to tmpfs (0600) and shredded, signed,
#                      verified with the public key, uploaded with its sha256
#   build-gate-fails   a release gate fails: the build stops at b04 and the key is never read
#   build-refused      the bundle comes out a rehearsal bundle (--rehearsal): b06 refuses it (D-726), nothing uploaded
#   build-preempt      a pre-emption in the middle of b03: the next boot keeps b01 and b02, runs b03 again, finishes
#   happy              start (G-2) + g6 + g9 + g10 from the signed bundle; the power cycle; results through the bucket
#                      (and the door)
#   step-fails         the qualification fails: the run stops there with the step's record
#   reboot             a cut in the middle of the qualification: the next boot keeps the finished steps
#   cap                the cost cap fires during a long step; the next boot ends at once (TB-CAP-REACHED)
#   bad-hash           a payload differs from its signed manifest: refused, the installer never runs
#   bad-tar-hash       the bundle is not the declared one: refused
#   refused-rehearsal  a --rehearsal bundle given to a production start: refused before the installer (D-726)
#   wizard-refused     the answers break the console's password rule: the wizard step stops, the installer is ended
#   oom                T-692: the ingest is killed at the adapter's cap: recorded (pass false, oom_kills 1), run goes on
#   list-differs       the disturbed screen lists other patients: G-9's result is pass false
#   identity-differs   the judge's served template and image are not the pinned ones, and the server's token ids and
#                      the weights folder's template differ from the folder tokenizer's: 06-g1 says so (pass false)
#   build-validation   validation mode's build: a THROWAWAY key made on the VM (the real sign_bundle.py keygen), the
#                      vendor key never read, verified with the throwaway public key, uploaded beside the bundle,
#                      records/bundle.json says "not a release"
#   acc                validation mode: install.sh --answers makes the box VALIDATION (its printed admin password
#                      redacted), then the accuracy group on three tiny synthetic sets built by the REAL item builder
#                      (two screened, one compile-only): the limits set and recorded, the routes probed, the feeds
#                      merged and ingested, FEAS/APPROVE/SCREEN by mail per protocol, the first protocol of each set
#                      refused by the PHI tripwire and counted as such, each set uploaded as it finished; then scored
#                      outside the box (tools/box_run.py acc-score) through the pseudonym map
#   acc-preempt        as acc, cut by a pre-emption in the middle of the first set: the next boot keeps the finished
#                      steps and protocols, waits for the jobs already started, never mails a protocol twice
#   acc-blocked        the box's gateway would refuse the screen's judge call (today's VALIDATION ceiling): the run
#                      stops at 52-acc-routes with the reason, before any data is fetched
#   resume-after-stop  the qualification fails (a stop), then the driver's --resume after a fix: a new tb-retry clears
#                      the run's end and the stopped step (its part kept in logs/), the next boot runs it again and
#                      keeps every finished step
#   acc-qualify-fails  validation mode: the qualification fails a gate; that is a result (the record's failed step and
#                      its figure), the pair is not promoted, resolve says what PRODUCTION routes, the run goes on
# Needs: bash, python3 (with PyYAML), the repo's venv (.venv: cryptography, the console), curl, openssl, git, make,
# tar, setsid. Evidence stays in $TB_BOXRUN_REHEARSAL_DIR/<case>/ (default /tmp/tb-boxrun-rehearsal).
# Ports: one free local port per case for the door and one for the console (asked of the kernel), never a fixed
# one: it may run beside `make rehearse`.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
VPY="${TB_BOXRUN_VENV_PY:-$ROOT/.venv/bin/python}"
REH="${TB_BOXRUN_REHEARSAL_DIR:-/tmp/tb-boxrun-rehearsal}"
ALL=(build build-gate-fails build-refused build-preempt happy step-fails reboot cap bad-hash bad-tar-hash
     refused-rehearsal wizard-refused oom list-differs identity-differs build-validation acc acc-preempt acc-blocked
     resume-after-stop acc-qualify-fails)
# shellcheck disable=SC2206  # CASES=happy,cap: split on commas and spaces
CASES=(${*//,/ }); [ "${#CASES[@]}" -gt 0 ] || CASES=("${ALL[@]}")
# the harness's own ceiling for one wait (a declared setting): a case takes 5 to 40 seconds on the short clock, so
# 180 seconds without the awaited event means the case is broken, not slow
WAIT_S="${TB_BOXRUN_REHEARSAL_WAIT_S:-180}"
log() { echo "$(date -u +%T) rehearse-box-run: $*"; }
S=""; CONSOLE_PID=""
vm_kill() {
  [ -z "$S" ] || [ ! -f "$S/vm.pgid" ] || kill -KILL -- "-$(cat "$S/vm.pgid")" 2>/dev/null || true
  [ -z "$CONSOLE_PID" ] || { kill "$CONSOLE_PID" 2>/dev/null || true; wait "$CONSOLE_PID" 2>/dev/null || true; CONSOLE_PID=""; }
  # the console's throwaway PostgreSQL goes with it (also when the console was killed before its own clean-up)
  [ -z "$S" ] || [ ! -s "$S/console/pg-root" ] || (cd "$ROOT" && "$VPY" -c 'import sys; from pathlib import Path; from tools import pglocal
pglocal.remove(Path(sys.argv[1]))' "$(cat "$S/console/pg-root")") || true
}
trap vm_kill EXIT
die() { log "FAIL: $*"; [ -z "$S" ] || tail -n 30 "$S"/boot-*.out 2>/dev/null || true; exit 1; }
wait_for() {  # wait_for <what> <command...>
  local what=$1 t0=$SECONDS; shift
  until "$@" >/dev/null 2>&1; do
    [ $((SECONDS - t0)) -lt "$WAIT_S" ] || die "waited $WAIT_S s for: $what"
    sleep 0.2
  done
}
free_port() { python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
[ -x "$VPY" ] || die "no venv python at $VPY (TB_BOXRUN_VENV_PY)"

# ---------------------------------------------------------------- the vendor's side, once: key, host tree, bundles
V="$REH/vendor"
vendor() {
  [ -s "$V/good.tar" ] && return 0
  rm -rf "$V"; mkdir -p "$V"
  "$VPY" "$ROOT/tools/sign_bundle.py" keygen --out "$V/keys" >/dev/null
  "$VPY" -m tools.host_tree pack --root "$ROOT" --out "$V/trialbox-host.tar" >/dev/null
  COMMIT=$(git -C "$ROOT" rev-parse HEAD)
  local b=("$VPY" "$HERE/standins/mkbundle.py" --key "$V/keys/vendor_ed25519.key" --id 2026.11-r --seq 3
           --host "$V/trialbox-host.tar" --commit "$COMMIT")
  "${b[@]}" --out "$V/good.tar" >/dev/null
  "${b[@]}" --out "$V/rehearsal.tar" --rehearsal >/dev/null
  "${b[@]}" --out "$V/tampered.tar" --tamper >/dev/null
  echo "$COMMIT" > "$V/commit"
}

# ---------------------------------------------------------------- one "VM"
m() { printf '%s' "$2" > "$S/metadata/$1"; }
setup() {  # setup <case> <steps> [knob ...]: a fresh "VM": metadata, secrets, the bucket, the helper
  local k
  S="$REH/$1"; vm_kill; rm -rf "$S"
  mkdir -p "$S"/{metadata,knobs,secrets/door,secrets/answers,secrets/vendor-key,driver,evidence,models/judge,models/verifier,box-root}
  for k in "${@:3}"; do touch "$S/knobs/$k"; done
  : > "$S/calls.log"; : > "$S/vm-gcloud.log"
  BKT="$S/bucket/tb-runs"; mkdir -p "$BKT/r2/keys"
  cp "$V/keys/vendor_ed25519.pub" "$BKT/r2/keys/vendor_ed25519.pub"
  cp "$V/keys/vendor_ed25519.key" "$S/secrets/vendor-key/1"   # the owner's step: the key into Secret Manager
  m tb-run-id "rehearsal-$1"; m tb-steps "$2"; m tb-bucket gs://tb-runs; m tb-done-grace 3
  cp "$ROOT/deploy/gcp/box_vm.py" "$S/metadata/tb-helper"
  m tb-vendor-pub gs://tb-runs/r2/keys/vendor_ed25519.pub
  m tb-box-root "$S/box-root"; m tb-models-root "$S/models"; m tb-box-python "$HERE/standins/boxpy"
  echo "standin/model-server:new" > "$S/knobs/vllm-image"
}
door_setup() {  # the door too (the driver's optional channel): its key and TLS key in "Secret Manager"
  PORT=$(free_port)
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$S/driver/door.key" -out "$S/driver/door.crt" -days 2 \
    -subj /CN=tb-door -addext subjectAltName=DNS:tb-door >/dev/null 2>&1
  (umask 077; python3 - "$S" <<'PY'
import json, secrets, sys
s = sys.argv[1]
key = secrets.token_hex(24)   # a random key of this rehearsal only, never printed
json.dump({"key": key, "tls_key": open(f"{s}/driver/door.key").read()}, open(f"{s}/secrets/door/1", "w"))
open(f"{s}/driver/hdr", "w").write(f"Authorization: Bearer {key}\n")
PY
  )
  m tb-door-secret door; m tb-door-version 1; m tb-door-port "$PORT"; cp "$S/driver/door.crt" "$S/metadata/tb-door-cert"
}
start_setup() {  # start (G-2): the bundle in the bucket, the wizard's answers, the console, the box's hardware
  local which=${1:-good} cport
  cp "$V/$which.tar" "$BKT/r2/trialbox.tar"
  m tb-bundle gs://tb-runs/r2/trialbox.tar; m tb-bundle-sha256 "$(sha256sum "$BKT/r2/trialbox.tar" | cut -d' ' -f1)"
  m tb-commit "$(cat "$V/commit")"; m tb-answers-secret answers; m tb-answers-version 1
  m tb-doctor-expected backup; m tb-g10-vllm-image "standin/model-server:new"; m tb-study GZQO
  m tb-g6-patients 500; m tb-screen-requester crc1@hospa.test; m tb-outage-seconds 1
  python3 - "$S" "$([ -f "$S/knobs/weak-password" ] && echo short || echo ok)" <<'PY'
import json, sys
s, pw = sys.argv[1], ("short" if sys.argv[2] == "short" else "owner-password-0001")
# a synthetic site: no real name, address or passphrase
json.dump({"site_name": "Synthetic Hospital (rehearsal)", "tz": "Asia/Tokyo", "language": "en",
           "owner_full_name": "Rehearsal Owner", "owner_username": "owner", "owner_email": "owner@hospa.test",
           "password": pw, "box_name": "trialbox", "backup_kind": "second_disk", "backup_disk": "/dev/sdb",
           "source": "spreadsheet"}, open(f"{s}/secrets/answers/1", "w"))
json.dump({"arch": "x86_64", "cpu_count": 48, "ram_gib": 188, "disk_free_gib": 400, "tpm": True,
           "disks": [{"path": "/dev/sdb", "size_gib": 500.0, "transport": "scsi", "mounted": ""}],
           "lan": "10.140.0.0/20", "hostname": "box1", "host_tz": "Asia/Tokyo",
           "gpu_name": "NVIDIA RTX PRO 6000 Blackwell Server Edition", "gpu_mem_gib": 96.0},
          open(f"{s}/hardware.json", "w"))
PY
  # the console of the box, over TLS for the box's provisional name (box1.local), on its own free port
  cport=$(free_port)
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$S/driver/console.key" -out "$S/driver/console.crt" -days 2 \
    -subj /CN=box1.local -addext subjectAltName=DNS:box1.local >/dev/null 2>&1
  mkdir -p "$S/vm/firstrun" "$S/console"
  "$VPY" "$HERE/standins/console_standin.py" "$S/vm/firstrun" "$S/console" "$cport" "$S/driver/console.crt" "$S/driver/console.key" \
    > "$S/console.log" 2>&1 &
  CONSOLE_PID=$!
  m tb-console-connect "127.0.0.1:$cport"; m tb-console-cacert "$S/driver/console.crt"
  wait_for "the console to answer" /usr/bin/curl -s --noproxy '*' -o /dev/null --cacert "$S/driver/console.crt" \
    --resolve "box1.local:$cport:127.0.0.1" "https://box1.local:$cport/healthz"
}
build_setup() {  # build: a small git repository as the release commit, its git bundle in the bucket
  local r="$S/srcrepo"
  mkdir -p "$r/trialbox/tools"
  cp "$ROOT/tools/verify_update.py" "$ROOT/tools/update_status.py" "$ROOT/tools/host_tree.py" "$ROOT/tools/sign_bundle.py" \
    "$r/trialbox/tools/"
  : > "$r/trialbox/tools/__init__.py"
  cp "$V/trialbox-host.tar" "$S/host-for-build.tar"
  # the stand-in targets (a recipe line starts with a tab)
  printf '%s\n' \
    'venv:' $'\tmkdir -p .venv/bin && ln -sf "$(TB_BOX_PY)" .venv/bin/python && echo venv >> "$(BR_S)/calls.log"' \
    'scanners:' $'\techo scanners >> "$(BR_S)/calls.log"' \
    'images:' $'\techo images >> "$(BR_S)/calls.log"; n=$$(cat "$(BR_S)/knobs/images-seconds" 2>/dev/null || echo 0); i=0; while [ $$i -lt $$n ]; do echo building; sleep 1; i=$$((i+1)); done' \
    'trivy-db:' $'\techo trivy-db >> "$(BR_S)/calls.log"' \
    'release-gates:' $'\techo release-gates >> "$(BR_S)/calls.log"; if [ -f "$(BR_S)/knobs/gate-fails" ]; then echo "FAIL vllm/vllm-openai CVE-2026-128089 (stand-in)"; exit 1; fi; mkdir -p build/supply-chain dist/sbom && echo "{}" > build/supply-chain/gates.json' \
    > "$r/trialbox/Makefile"
  cat > "$r/trialbox/tools/make_bundle.sh" <<'EOS'
#!/bin/bash
# Stand-in for tools/make_bundle.sh in the box-run rehearsal: no image to export; it checks the key file as the
# real one does, then signs with the REAL signer over the real host tree (standins/mkbundle.py).
set -eu
while [ $# -gt 0 ]; do case "$1" in --key) K=$2; shift ;; --id) I=$2; shift ;; --release-seq) Q=$2; shift ;;
  --out) O=$2; shift ;; --gates) G=$2; shift ;; --sbom-dir) shift ;; *) echo "make_bundle: unknown option $1" >&2; exit 2 ;; esac; shift; done
[ -f "$K" ] && [ -f "$G" ] || { echo "make_bundle: no key or no gates" >&2; exit 2; }
[ "$(stat -c %a "$K")" = 600 ] || { echo "make_bundle: the key is not 0600" >&2; exit 2; }
echo "make-bundle key-ok" >> "$BR_S/calls.log"
x=(); [ -f "$BR_S/knobs/build-rehearsal" ] && x=(--rehearsal)
"$TB_BOX_PY" "$BR_HERE/standins/mkbundle.py" --key "$K" --id "$I" --seq "$Q" --host "$BR_S/host-for-build.tar" \
  --commit "$(git rev-parse HEAD)" --out "$O" ${x[@]+"${x[@]}"}
EOS
  chmod +x "$r/trialbox/tools/make_bundle.sh"
  git -C "$r" init -q && git -C "$r" add -A && git -C "$r" -c user.email=r@x.invalid -c user.name=rehearsal commit -qm r2
  git -C "$r" bundle create -q "$BKT/r2/src.bundle" HEAD 2>/dev/null || git -C "$r" bundle create "$BKT/r2/src.bundle" HEAD >/dev/null 2>&1
  m tb-src gs://tb-runs/r2/src.bundle; m tb-commit "$(git -C "$r" rev-parse HEAD)"
  m tb-release-id 2026.11-r; m tb-release-seq 3; m tb-vendor-key-secret vendor-key; m tb-vendor-key-version 1
  m tb-out gs://tb-runs/r2/out; m tb-build-root "$S/vm/build"
}
acc_setup() {  # validation mode and the acc group: the synthetic site's answers (YAML), lane G's tools in the bucket
  m tb-mode validation; m tb-acc-sets "jmed:3 sigir:3 tfda:2"; m tb-acc-job-minutes 2
  # the committed synthetic site's answers, as the driver hands them over (no Secret Manager in validation mode)
  cp "$ROOT/deploy/gcp/validation-site-answers.yaml" "$S/metadata/tb-site-answers"
  rm -f "$S/metadata/tb-answers-secret" "$S/metadata/tb-answers-version"
  mkdir -p "$BKT/boxruns/rehearsal-$CASE"
  (cd "$ROOT" && tar -czf "$BKT/boxruns/rehearsal-$CASE/acc-tools.tgz" tools/__init__.py tools/public_accuracy \
     tools/public_site.py tools/fetch_pinned.py eval/criterion_ml)
  m tb-acc-tools "gs://tb-runs/boxruns/rehearsal-$CASE/acc-tools.tgz"
}
acc_collect() {  # as the driver's --collect: each set's upload fetched, unpacked and scored outside the box
  local f
  mkdir -p "$S/evidence/collected/acc"
  for f in "$BKT/boxruns/rehearsal-$CASE/acc/"*.tgz; do
    [ -f "$f" ] || continue
    mkdir -p "$S/evidence/collected/acc/$(basename "$f" .tgz)"
    tar -xzf "$f" -C "$S/evidence/collected/acc/$(basename "$f" .tgz)"
  done
  (cd "$ROOT" && env PYTHONPATH=libs:services:. TB_ENV=DEV "$VPY" -m tools.box_run acc-score "$S/evidence/collected") \
    > "$S/evidence/acc-score.json"
}
boot() { "$HERE/standins/boot.sh" "$S"; }
RES() { echo "$BKT/boxruns/rehearsal-$CASE/results.tgz"; }
is_done() { grep -q '^BOX-RUN-DONE$' "$S/boot-$(cat "$S/boots").out"; }
is_off() { [ "$(cat "$S/status")" = TERMINATED ]; }
asks_power() { [ -f "$BKT/boxruns/rehearsal-$CASE/POWER-CYCLE-REQUEST" ]; }
power_cycle() {  # as the driver does: it sees the request in the bucket, removes it, stops and starts the VM
  wait_for "the VM to ask for the power cycle" asks_power
  rm -f "$BKT/boxruns/rehearsal-$CASE/POWER-CYCLE-REQUEST"
  "$HERE/standins/reboot.sh" "$S"
}
collect() {  # the results from the bucket, unpacked into the evidence
  mkdir -p "$S/evidence/results"
  tar -xzf "$(RES)" -C "$S/evidence/results"
}
door_probe() {  # the door, with and without the key, while the VM's run is known to be up: it waits for its power
  # cycle, which only this harness gives. Never after the done marker: the VM powers itself off tb-done-grace
  # seconds later, and a probe then races the power-off (it read 000 instead of 401 on 2026-11-15).
  local code key
  for code in no-key with-key; do
    key=(); [ "$code" = no-key ] || key=(-H @"$S/driver/hdr")
    /usr/bin/curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 5 --cacert "$S/driver/door.crt" \
      --resolve "tb-door:$PORT:127.0.0.1" ${key[@]+"${key[@]}"} "https://tb-door:$PORT/tb/progress" \
      > "$S/evidence/$code-http-code" || true
  done
}
to_the_end() { wait_for "the done marker" is_done; collect; wait_for "the power-off (done, results in the bucket)" is_off; }

vendor
for CASE in "${CASES[@]}"; do
  log "case $CASE"
  case "$CASE" in
    build) setup "$CASE" build; build_setup; boot; to_the_end ;;
    build-gate-fails) setup "$CASE" build gate-fails; build_setup; boot; to_the_end ;;
    build-refused) setup "$CASE" build build-rehearsal; build_setup; boot; to_the_end ;;
    build-preempt)
      setup "$CASE" build; echo 4 > "$S/knobs/images-seconds"; build_setup; boot
      wait_for "b03-images to be running" grep -q '^images$' "$S/calls.log"
      "$HERE/standins/reboot.sh" "$S"            # a pre-emption: the spot VM is stopped, the driver starts it again
      to_the_end ;;
    happy)
      setup "$CASE" "start g6 g9 g10"; door_setup; start_setup; boot
      wait_for "the door" grep -q 'TB-DOOR-UP' "$S/vm/serial.log"
      wait_for "the VM to ask for the power cycle" asks_power   # from here the run waits for us: the door is up
      door_probe
      power_cycle; to_the_end ;;
    step-fails) setup "$CASE" start fail-qualify; start_setup; boot; to_the_end ;;
    reboot)
      setup "$CASE" start; echo 3 > "$S/knobs/qualify-seconds"; start_setup; boot
      wait_for "the qualification to be running" grep -q '^qualify$' "$S/calls.log"
      "$HERE/standins/reboot.sh" "$S"
      to_the_end ;;
    cap)
      # 30 "minutes" (seconds here): the install, the wizard and the steps before 08 take 5 to 15 s on this host
      setup "$CASE" start; echo 120 > "$S/knobs/qualify-seconds"; start_setup; m tb-max-minutes 30; boot
      wait_for "the power-off by the cap" is_off
      cp "$(RES)" "$S/evidence/results-at-cap.tgz"
      boot; to_the_end ;;
    bad-hash) setup "$CASE" start; start_setup tampered; boot; to_the_end ;;
    bad-tar-hash) setup "$CASE" start; start_setup; m tb-bundle-sha256 "$(printf '%064d' 0)"; boot; to_the_end ;;
    refused-rehearsal) setup "$CASE" start; start_setup rehearsal; boot; to_the_end ;;
    wizard-refused) setup "$CASE" start weak-password; start_setup; boot; to_the_end ;;
    oom) setup "$CASE" "start g6" oom-ingest; start_setup; boot; to_the_end ;;
    list-differs) setup "$CASE" "start g9" list-differs; start_setup; boot; power_cycle; to_the_end ;;
    identity-differs) setup "$CASE" start template-differs image-differs tokens-differ; start_setup; boot; to_the_end ;;
    resume-after-stop)
      setup "$CASE" start fail-qualify; start_setup; boot
      wait_for "the done marker" is_done; wait_for "the power-off" is_off
      rm -f "$S/knobs/fail-qualify"; m tb-retry "retry-1"   # the fix, and the driver's --resume (a new tb-retry)
      boot; to_the_end ;;
    acc-qualify-fails)
      setup "$CASE" start fail-qualify; start_setup; m tb-mode validation
      cp "$ROOT/deploy/gcp/validation-site-answers.yaml" "$S/metadata/tb-site-answers"
      rm -f "$S/metadata/tb-answers-secret" "$S/metadata/tb-answers-version"; boot; to_the_end ;;
    build-validation)
      setup "$CASE" build; build_setup; m tb-mode validation; rm -f "$S/metadata/tb-vendor-key-secret" "$S/metadata/tb-vendor-key-version"
      boot; to_the_end ;;
    acc) setup "$CASE" "start acc" acc-tripwire; start_setup; acc_setup; boot; to_the_end; acc_collect ;;
    acc-preempt)
      setup "$CASE" "start acc"; echo 1.5 > "$S/knobs/acc-job-seconds"; start_setup; acc_setup
      m tb-acc-tripwire-setting TB_GATEWAY_PHI_TRIPWIRE=off; boot
      wait_for "the first set's second protocol to be mailed" grep -q '^acc-send FEAS MNCT90000002 new$' "$S/calls.log"
      "$HERE/standins/reboot.sh" "$S"            # a pre-emption in the middle of the set
      to_the_end; acc_collect ;;
    acc-blocked) setup "$CASE" "start acc" acc-blocked; start_setup; acc_setup; boot; to_the_end ;;
    *) die "no such case: $CASE" ;;
  esac
  python3 "$HERE/check.py" "$CASE" "$S" || die "case $CASE: the checks above"
  vm_kill
  log "case $CASE passed"
done
log "all cases passed: ${CASES[*]}"
