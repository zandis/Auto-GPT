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
#   build-again-fails  HYG2-R2: a signing that fails leaves the last good release in the build folder as it was
#   build-cut-fails    HYG2-R2 (N4): an earlier signing was cut between its two renames (the last release in
#                      out.old), then the signing fails: the last release is back in out
#   build-pub-private  HYG2-R7: the vendor public-key object carries a private key after the public one: refused at
#                      b05, nothing of it in the build folder, nothing uploaded
#   build-recover-fails  HYG2-R2: the last release in out.old (a cut) and its way back into out blocked: b05 stops
#                      before signing and out.old is kept, never deleted
#   build-stray-out    HYG2-R2: the last release in out.old and a folder in out that is not a release: the signing
#                      stops before replacing anything and out.old is kept
#   build-validation-again-fails  HYG2-R10: a validation signing that fails keeps the public key of the bundle kept
#   build-sign-cut     HYG2-R10: a cut signing left its attempt folder and make_bundle.sh's staging: the next one
#                      removes them (one bundle of disk per cut otherwise)
#   build-preempt      a pre-emption in the middle of b03: the next boot keeps b01 and b02, runs b03 again, finishes
#   happy              start (G-2) + g6 + g9 + g10 from the signed bundle; the power cycle; results through the bucket
#                      (and the door)
#   step-fails         the qualification fails: the run stops there with the step's record
#   gate-closed        D2: the canary gate is closed at the first read: the orchestrator restarted, the gate read
#                      (with the service token, from a service's container) until open, the run goes on
#   gate-401           D2: GET /models refuses the token: a failure at once (no restart, no wait), the run stops
#   gate-never         D2: the gate stays closed after the restart and the wait: the run stops at 07g-gate
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
#   direct             validation, the direct route (tb-direct): the installed tree's stack brought up with the
#                      product's own commands (secrets init, pin_model --install as root, keys-init, db, db-up, up)
#   dev                the commit's images built on the VM (b01-b03), its tree as the box's release, the direct
#                      route, then G-1, canary, qualify: no bundle, no signature
#   acc-cut            the first set's own time budget is spent mid-way (slow jobs): no new protocol is started, the
#                      finished ones are kept and uploaded; progress lines and the partial in the bucket while it runs
#   acc-gate           every SCREEN finishes and answers nobody: the first set (the gate) is "not scored", its step
#                      stops the run with the reason and its work in the bucket, never "done" (F22)
#   acc-redo           acc-gate's stop, then --resume --redo of the gate set: its work moved aside, its jobs mailed
#                      again under new ids (the box keeps one job per mail id, F28), and it scores
#   acc-cut-resume     acc-cut's run (the first set ends on its own budget with protocols cut), then the driver's
#                      --resume with a new budget for that set only (D-1129): the set runs its cut protocols in a
#                      second attempt, never mails a finished one again, and its answers, audit, traces and score are
#                      one record of the two attempts; the other cut sets, given no budget, stay done, said
#   qualify-timebox    validation: qualify runs longer than its time box (the owner's probe): it is ended, a checkpoint
#                      a "second" while it ran (the gate it was in, the audit's calls), the run goes on
#   probe              a facts-only launch (tb-steps probe): the VM's facts written (names and sizes), the run ends
#   acc-qualify-fails  validation mode: the qualification fails a gate; that is a result (the record's failed step and
#                      its figure), the pair is not promoted, resolve says what PRODUCTION routes, the run goes on
#   session            the owner's live session (D-1132), DEV with the acting role (knob dev-routes: the DEV routing
#                      change D-1123 section 3 asks for): dev's bring-up, the public set and the synthetic hospital
#                      ingested, the box in DEV, its own egress rules applied and read back, one account by the
#                      console's code, the links to one private object, the ready line with this boot's id, the
#                      heartbeat from the owner's requests, the stop, the accounts disabled and the box back in
#                      VALIDATION; no code in any log, result or the serial port; the record says it is no evidence
#   session-stop       the hard stop (VALIDATION, one account per role): the session asked for longer than the cost
#                      cap allows ends at the cap less its margin, its accounts disabled before the cap fires
#   session-cut        a power cut while the session is open: the next boot disables its accounts before any step
#                      and before anything is served (the box's Caddy down, the re-review's A), puts the box back in
#                      VALIDATION, and never opens the session again
#   session-close-fails  as session-cut, but the console cannot be asked at the next boot: the run stops there, the
#                      box's Caddy never came up on that boot, no CLOSED marker is written (the deny stays)
#   session-update-fails  the console's and Caddy's restart policy cannot be set to `no`: no account is opened (the
#                      re-review's E), and the run's CLOSED marker is written all the same (C)
#   session-cut-56     a power cut while 56 opens the accounts, then a later boot with no tb-retry (a power cycle, a
#                      start by hand): its accounts are closed and it stops; 56 never runs again (round 3's finding 4)
#   session-unit       lane D's trialbox.service enabled on the disk (`compose up` at every boot), a power cut while the
#                      session is open: 56 disabled it first, the next boot's Caddy never serves the open accounts, the
#                      unit is put back once the accounts are disabled and CLOSED is written (round 3's finding 1)
#   session-unit-race  as session-unit, but the unit was enabled again by hand and its `compose up` lands in the middle
#                      of the close: the close stops it and waits first; Caddy never serves the open accounts
#   session-unit-fails the unit cannot be disabled: no account, no link, the run's CLOSED marker written
#   session-unit-dbus  systemctl gives no answer for trialbox.service, whose unit file exists: no account (round 4's c)
#   session-ops        lane D's Operations timer enabled again at the boot after a cut, an update's `compose up` queued:
#                      the close stops the timers first; Caddy never serves the open accounts (round 4's b)
#   session-quiet-fails  trialbox.service does not stop at the boot after a cut: Caddy is stopped all the same and
#                      tcp:443 decides; never a close while Caddy may serve (round 4's a)
#   session-ss-fails   ss gives no answer at the boot after a cut: what listens on tcp:443 cannot be told, no close
#                      runs, the run stops and says so (round 4's f)
#   session-ended-again  the run ends with its accounts open (the console cannot be asked), then the same run boots
#                      again: it closes them before it hands the ended run over (round 4's g)
#   session-wide       the driver refuses a range too wide (0.0.0.0/0, any, a /8) before anything: no VM booted
#   session-egress     the box's egress table lets a container out (as a DEV box's opens a model host): the session
#                      stops at 55-session-egress and no account or link is made
#   session-skip       a session launch whose tb-skip names one of its own steps (55, the egress proof): refused at
#                      the VM's preflight, before anything is built (the security review's finding 1)
#   session-resume     a session cut during its bring-up, then a resume (a new tb-retry): refused, no account and no
#                      link are made (finding 2: more time is a new launch)
#   session-ssh        something still listens on tcp:22 after the session's stop of sshd: no session (finding 5)
#   session-then-acc   a session (VALIDATION) to its end, then an accuracy launch on the same disk: SSH put back as it
#                      was, the box's public address put back, the session's CLOSED marker written, and the accuracy
#                      run's feed holds no table of the session's synthetic hospital (findings 5, 6, 11)
#   session-dev-refused  DEV on this tree (no routing change): the box itself refuses the session's calls at
#                      52-acc-routes, before any data, account or link
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
     resume-after-stop acc-qualify-fails probe direct dev acc-cut qualify-timebox acc-gate acc-redo gate-closed gate-401 gate-never
     acc-cut-resume build-again-fails build-cut-fails build-pub-private build-recover-fails build-validation-again-fails
     build-sign-cut build-stray-out
     session session-stop session-cut session-wide session-egress session-dev-refused session-skip session-resume
     session-ssh session-then-acc session-close-fails session-update-fails session-cut-56 session-unit session-unit-race
     session-unit-fails session-unit-dbus session-ops session-quiet-fails session-ss-fails session-ended-again)
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
import json, os, sys
s, pw = sys.argv[1], ("short" if sys.argv[2] == "short" else "owner-password-0001")
# 10K-4 (D-1390): a PRODUCTION box finishes only with a backup target shown to be off the box and the hospital's audit
# share as its anchor folder. This IS a rehearsal: the finish check reads the "VM"'s own host from stand-ins inside a
# marked test root ($S/finish with .tb-test-root, TB_TEST_ROOT; the stand-ins are honoured nowhere else): a mount
# table where /mnt/backup-disk is a second physical disk (sdb) and /mnt/audit-share the hospital's NFS share, a
# sysfs, the names a share resolves to, the VM's own address, and a folder that stands for /
f = f"{s}/finish"
os.makedirs(f, exist_ok=True)
open(f"{f}/.tb-test-root", "w").close()
for d in ("sda/sda1", "sdb/sdb1"):
    os.makedirs(f"{f}/sys/devices/pci/{d}", exist_ok=True)
    open(f"{f}/sys/devices/pci/{d}/partition", "w").write("1\n")
for disk in ("sda", "sdb"):
    os.makedirs(f"{f}/sys/devices/pci/{disk}/device", exist_ok=True)  # hardware behind it: a physical disk
os.makedirs(f"{f}/sys/class/block", exist_ok=True)
os.makedirs(f"{f}/sys/dev/block", exist_ok=True)
for name, dev, mm in (("sda", "sda", "8:0"), ("sda1", "sda/sda1", "8:1"), ("sdb", "sdb", "8:16"),
                      ("sdb1", "sdb/sdb1", "8:17")):
    for link in (f"{f}/sys/class/block/{name}", f"{f}/sys/dev/block/{mm}"):
        if not os.path.lexists(link):
            os.symlink(f"{f}/sys/devices/pci/{dev}", link)
open(f"{f}/mountinfo", "w").write("20 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
                                  "21 20 8:17 / /mnt/backup-disk rw - ext4 /dev/sdb1 rw\n"
                                  "22 20 0:50 / /mnt/audit-share rw - nfs4 nas.hospa.test:/audit rw\n")
open(f"{f}/hosts", "w").write("nas.hospa.test 192.0.2.10\n")
open(f"{f}/own-addresses", "w").write("10.140.0.2\n")
os.makedirs(f"{f}/root/mnt/backup-disk", exist_ok=True)
os.makedirs(f"{f}/root/mnt/audit-share", exist_ok=True)
# the nightly backup's own rule counts a declared folder on another device, or one with this mark: the stand-in
# disk is a folder of the rehearsal's own disk, so it carries the mark (a real second disk needs none)
open(f"{f}/root/mnt/backup-disk/.trialbox-offbox", "w").close()
# a synthetic site: no real name, address or passphrase
json.dump({"site_name": "Synthetic Hospital (rehearsal)", "tz": "Asia/Tokyo", "language": "en",
           "owner_full_name": "Rehearsal Owner", "owner_username": "owner", "owner_email": "owner@hospa.test",
           "password": pw, "box_name": "trialbox", "backup_kind": "second_disk", "backup_disk": "/dev/sdb",
           "backup_dir": "/mnt/backup-disk", "anchor_dir": "/mnt/audit-share",
           "source": "spreadsheet"}, open(f"{s}/secrets/answers/1", "w"))
json.dump({"arch": "x86_64", "cpu_count": 48, "ram_gib": 188, "disk_free_gib": 400, "tpm": True,
           "disks": [{"path": "/dev/sdb", "size_gib": 500.0, "transport": "scsi", "mounted": ""}],
           "lan": "10.140.0.0/20", "hostname": "box1", "host_tz": "Asia/Tokyo",
           "gpu_name": "NVIDIA RTX PRO 6000 Blackwell Server Edition", "gpu_mem_gib": 96.0},
          open(f"{s}/hardware.json", "w"))
PY
  export TB_TEST_ROOT="$S/finish" TB_FINISH_MOUNTINFO="$S/finish/mountinfo" TB_FINISH_SYS="$S/finish/sys" \
    TB_FINISH_TEST_ROOT="$S/finish/root"
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
    'release-gates:' $'\techo release-gates >> "$(BR_S)/calls.log"; echo "gates-args $(RELEASE_GATES_ARGS)" >> "$(BR_S)/calls.log"; if [ -f "$(BR_S)/knobs/gate-fails" ]; then echo "FAIL vllm/vllm-openai CVE-2026-128089 (stand-in)"; exit 1; fi; mkdir -p build/supply-chain dist/sbom && echo "{}" > build/supply-chain/gates.json' \
    > "$r/trialbox/Makefile"
  cat > "$r/trialbox/tools/make_bundle.sh" <<'EOS'
#!/bin/bash
# Stand-in for tools/make_bundle.sh in the box-run rehearsal: no image to export; it checks the key file as the
# real one does, then signs with the REAL signer over the real host tree (standins/mkbundle.py).
set -eu
while [ $# -gt 0 ]; do case "$1" in --key) K=$2; shift ;; --id) I=$2; shift ;; --release-seq) Q=$2; shift ;;
  --out) O=$2; shift ;; --pub) P=$2; shift ;; --gates) G=$2; shift ;; --sbom-dir) shift ;; --models) M=$2; shift ;;
  *) echo "make_bundle: unknown option $1" >&2; exit 2 ;; esac; shift; done
[ -f "$K" ] && [ -f "$G" ] || { echo "make_bundle: no key or no gates" >&2; exit 2; }
[ -n "${P:-}" ] && [ -f "$P" ] || { echo "make_bundle: --pub must name the vendor public key (as the real one, F1)" >&2; exit 2; }
# H-43: the weights the site bundle carries, as the real one reads them (find -L: through the links)
[ -n "${M:-}" ] && [ -n "$(find -L "$M/embedder" -type f 2>/dev/null)" ] || { echo "make_bundle: no embedder/ in --models" >&2; exit 2; }
echo "make-bundle models $(ls "$M" | tr '\n' ' ')" >> "$BR_S/calls.log"
[ "$(stat -c %a "$K")" = 600 ] || { echo "make_bundle: the key is not 0600" >&2; exit 2; }
[ ! -f "$BR_S/knobs/sign-fails" ] || { echo "make_bundle: the stand-in refuses this build (knob sign-fails)" >&2; exit 1; }
echo "make-bundle key-ok" >> "$BR_S/calls.log"
x=(); [ -f "$BR_S/knobs/build-rehearsal" ] && x=(--rehearsal)
mkdir -p "$(dirname "$O")"   # the real one publishes --out's folder itself
"$TB_BOX_PY" "$BR_HERE/standins/mkbundle.py" --key "$K" --id "$I" --seq "$Q" --host "$BR_S/host-for-build.tar" \
  --commit "$(git rev-parse HEAD)" --out "$O" ${x[@]+"${x[@]}"}
EOS
  chmod +x "$r/trialbox/tools/make_bundle.sh"
  git -C "$r" init -q && git -C "$r" add -A && git -C "$r" -c user.email=r@x.invalid -c user.name=rehearsal commit -qm r2
  git -C "$r" bundle create -q "$BKT/r2/src.bundle" HEAD 2>/dev/null || git -C "$r" bundle create "$BKT/r2/src.bundle" HEAD >/dev/null 2>&1
  m tb-src gs://tb-runs/r2/src.bundle; m tb-commit "$(git -C "$r" rev-parse HEAD)"
  m tb-release-id 2026.11-r; m tb-release-seq 3; m tb-vendor-key-secret vendor-key; m tb-vendor-key-version 1
  m tb-out gs://tb-runs/r2/out; m tb-build-root "$S/vm/build"
  # H-43: b05 places the site bundle's weights: the "VM's" pair folders, no template, an embedder already in place
  # (models-place keeps a folder that is there; no network here)
  if [ "$(cat "$S/metadata/tb-steps")" = build ]; then
    val_models; mkdir -p "$S/models/embedder"; echo '{"stand-in": true}' > "$S/models/embedder/config.json"
  fi
}
val_models() {  # validation: the box's flat model folders from the "VM's" model folders (no network here)
  m tb-model-links "gemma-4-26b-a4b-it-4bit=judge qwen3.5-9b-4bit=verifier"; m tb-model-template ""
}
acc_setup() {  # validation mode and the acc group: the synthetic site's answers (YAML), lane G's tools in the bucket
  m tb-mode validation; m tb-acc-sets "jmed:3 sigir:3 tfda:2"; m tb-acc-job-minutes 2; val_models
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
session_setup() {  # session_setup DEV|VALIDATION: the site files the first start left, then the driver's session keys
  start_setup; build_setup; m tb-mode validation; val_models; m tb-direct 1
  mkdir -p "$S/box-root/deploy" "$S/feed"
  printf 'TB_ENV=VALIDATION\nTB_TZ=Asia/Taipei\nTB_TLS_HOSTNAME=trialbox.hospa.test\nTB_SOURCE_DIR=%s\nTB_SOURCE_MOUNT=/data/source/site-a\n' \
    "$S/feed" > "$S/box-root/deploy/.env"
  printf 'site: {id: ACC-VALIDATION}\nrate_limit_per_sender_per_day: 20\n' > "$S/box-root/deploy/settings.yaml"
  cp "$HERE/standins/network.sh" "$S/box-root/deploy/network.sh"   # the box's own egress script (stand-in)
  echo 34.80.0.10 > "$S/external-ip"
  BR_S="$S" python3 "$HERE/standins/box.py" wizard-done
  mkdir -p "$BKT/boxruns/rehearsal-$CASE"
  (cd "$ROOT" && tar -czf "$BKT/boxruns/rehearsal-$CASE/acc-tools.tgz" tools/__init__.py tools/public_accuracy \
     tools/public_site.py tools/fetch_pinned.py eval/criterion_ml)
  m tb-acc-tools "gs://tb-runs/boxruns/rehearsal-$CASE/acc-tools.tgz"; m tb-acc-sets "jmed:3"; m tb-acc-job-minutes 2
  m tb-session-env "$1"; m tb-session-minutes 6; m tb-session-synth 20; m tb-session-idle-minutes 30
  m tb-session-handoff "gs://tb-runs/session/rehearsal-$CASE"; m block-project-ssh-keys TRUE
  m tb-skip "08-qualify 09-promote-judge 10-promote-verifier 11-resolve 12-doctor"
  if [ "$1" = DEV ]; then m tb-session-people "owner:coordinator+investigator+steward+admin"
  else m tb-session-people "owner-crc:coordinator,owner-inv:investigator,owner-stw:steward,owner-adm:admin"; fi
}
session_wide() {  # the driver, free: each too-wide range refused before anything (no gcloud on the PATH, no VM)
  local r rc
  mkdir -p "$S/evidence"
  for r in 0.0.0.0/0 any 8.0.0.0/8 1.2.0.0/16 "1.2.3.4,0.0.0.0/1"; do
    rc=0
    env -i PATH=/usr/bin:/bin HOME="$S" PY="$VPY" TMPDIR="$S" "$ROOT/deploy/gcp/box-run.sh" --preflight --mode validation \
      --steps dev,session --release-id dev-x --commit "$(printf '%040d' 0)" --session-allow "$r" \
      > "$S/evidence/wide.out" 2>> "$S/evidence/wide.err" || rc=$?
    printf '%s\t%s\n' "$r" "$rc" >> "$S/evidence/wide.rc"
  done
}
boot() { "$HERE/standins/boot.sh" "$S"; }
RES() { echo "$BKT/boxruns/${RUNID:-rehearsal-$CASE}/results.tgz"; }
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
    build)  # HYG2-R2: the release an earlier run left is retired once the new one is built
      setup "$CASE" build; build_setup; mkdir -p "$S/vm/build/out" "$S/vm/build/out.next.another-run"
      echo old > "$S/vm/build/out/earlier-release.tar"
      boot; to_the_end ;;
    build-gate-fails) setup "$CASE" build gate-fails; build_setup; boot; to_the_end ;;
    build-refused) setup "$CASE" build build-rehearsal; build_setup; boot; to_the_end ;;
    build-again-fails)
      setup "$CASE" build sign-fails; build_setup
      mkdir -p "$S/vm/build/out"; echo "the last good release" > "$S/vm/build/out/trialbox-2026.11-r.tar"
      boot; to_the_end ;;
    build-cut-fails)
      setup "$CASE" build sign-fails; build_setup
      mkdir -p "$S/vm/build/out.old"; echo "the last good release" > "$S/vm/build/out.old/trialbox-2026.11-r.tar"
      boot; to_the_end ;;
    build-pub-private)
      setup "$CASE" build; build_setup; cat "$V/keys/vendor_ed25519.key" >> "$BKT/r2/keys/vendor_ed25519.pub"
      boot; to_the_end ;;
    build-recover-fails)  # a link to nowhere: out is not there, and out.old cannot be renamed onto it
      setup "$CASE" build; build_setup
      mkdir -p "$S/vm/build/out.old"; echo "the last good release" > "$S/vm/build/out.old/trialbox-2026.11-r.tar"
      ln -s "$S/vm/build/nowhere" "$S/vm/build/out"
      boot; to_the_end ;;
    build-validation-again-fails)
      setup "$CASE" build sign-fails; build_setup; m tb-mode validation
      rm -f "$S/metadata/tb-vendor-key-secret" "$S/metadata/tb-vendor-key-version"
      mkdir -p "$S/vm/build/out"; echo "the last good release" > "$S/vm/build/out/trialbox-2026.11-r.tar"
      echo "the last throwaway key" > "$S/vm/build/out/throwaway-signing-key.pub"
      echo "the last throwaway key" > "$S/vm/build/throwaway-signing-key.pub"   # where b06 read it before
      boot; to_the_end ;;
    build-stray-out)
      setup "$CASE" build; build_setup
      mkdir -p "$S/vm/build/out.old" "$S/vm/build/out"; echo "the last good release" > "$S/vm/build/out.old/trialbox-2026.11-r.tar"
      echo "not a release" > "$S/vm/build/out/stray.txt"
      boot; to_the_end ;;
    build-sign-cut)
      setup "$CASE" build; build_setup
      mkdir -p "$S/vm/build/out" "$S/vm/build/out.next.another-run" "$S/vm/build/out.next.sign/.make_bundle-pending.x" \
        "$S/vm/build/tmp/tb-bundle.x"
      echo old > "$S/vm/build/out/earlier-release.tar"
      echo partial > "$S/vm/build/out.next.sign/.make_bundle-pending.x/trialbox-2026.11-r.tar"
      echo partial > "$S/vm/build/tmp/tb-bundle.x/image.tar"
      boot; to_the_end ;;
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
    gate-closed) setup "$CASE" start gate-closed; start_setup; boot; to_the_end ;;
    gate-401) setup "$CASE" start gate-401; start_setup; boot; to_the_end ;;
    gate-never) setup "$CASE" start gate-never; start_setup; boot; to_the_end ;;
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
    probe) setup "$CASE" probe; boot; to_the_end ;;
    qualify-timebox)
      setup "$CASE" start; echo 6 > "$S/knobs/qualify-seconds"; start_setup; m tb-mode validation; val_models
      cp "$ROOT/deploy/gcp/validation-site-answers.yaml" "$S/metadata/tb-site-answers"
      rm -f "$S/metadata/tb-answers-secret" "$S/metadata/tb-answers-version"
      m tb-qualify-timebox 2; m tb-progress-seconds 1; boot; to_the_end ;;
    acc-cut)
      setup "$CASE" "start acc"; echo 1.2 > "$S/knobs/acc-job-seconds"; start_setup; acc_setup
      m tb-acc-plan "jmed:3:0.5 sigir:3:1 tfda:2:1"; m tb-acc-min-deadline 2; m tb-acc-min-start 0.5; m tb-progress-seconds 1
      m tb-acc-protocols "sigir:SNCT90000002"; m tb-acc-streams "tfda:2"
      boot; to_the_end; acc_collect ;;
    acc-cut-resume)   # acc-cut's run, then --resume --acc-deadline "jmed:60": jmed's cut protocols in attempt 2 only
      setup "$CASE" "start acc"; echo 1.2 > "$S/knobs/acc-job-seconds"; start_setup; acc_setup
      m tb-acc-plan "jmed:3:0.5 sigir:3:0.5 tfda:2:1"; m tb-acc-min-deadline 2; m tb-acc-min-start 0.5; m tb-progress-seconds 1; m tb-acc-streams "sigir:1"
      boot; wait_for "the done marker" is_done; wait_for "the power-off" is_off
      collect; mv "$S/evidence/results" "$S/evidence/results-attempt-1"; cp "$(RES)" "$S/evidence/results-attempt-1.tgz"
      cp "$BKT/boxruns/rehearsal-$CASE/acc/jmed.tgz" "$S/evidence/jmed-attempt-1.tgz"
      cp "$S/calls.log" "$S/evidence/calls-attempt-1.log"
      # the driver's free look first (tools/box_run.py resume-plan over the last collect), then the resume itself
      mkdir -p "$S/evidence/run-folder"; cp "$(RES)" "$S/evidence/run-folder/results.tgz"
      (cd "$ROOT" && env PYTHONPATH=libs:services:. "$VPY" -m tools.box_run resume-plan "$S/evidence/run-folder" \
         --deadline "jmed:60") > "$S/evidence/resume-plan.json" 2> "$S/evidence/resume-plan.err"
      m tb-retry "retry-1"; m tb-acc-deadline "jmed:60"; boot; to_the_end; acc_collect ;;
    dev)   # the site files the first start left (the wizard's .env), then the dev launch
      setup "$CASE" dev; start_setup; build_setup; m tb-mode validation; val_models; m tb-direct 1
      mkdir -p "$S/box-root/deploy"; printf 'TB_ENV=VALIDATION\nTB_TZ=Asia/Taipei\n' > "$S/box-root/deploy/.env"
      BR_S="$S" python3 "$HERE/standins/box.py" wizard-done; boot; to_the_end ;;
    direct)   # the tree an earlier install left (current, the wizard's .env), then the direct route
      setup "$CASE" start fail-qualify; start_setup; m tb-mode validation; val_models; m tb-direct 1
      cp "$ROOT/deploy/gcp/validation-site-answers.yaml" "$S/metadata/tb-site-answers"
      rm -f "$S/metadata/tb-answers-secret" "$S/metadata/tb-answers-version"
      mkdir -p "$S/box-root/current" "$S/box-root/deploy"; printf 'TB_ENV=VALIDATION\nTB_TZ=Asia/Taipei\n' > "$S/box-root/deploy/.env"
      m tb-site-env "TB_MEM_EMBED=16g TB_ENV=PRODUCTION TB_MEM_DB=lots"
      BR_S="$S" python3 "$HERE/standins/box.py" wizard-done; boot; to_the_end ;;
    acc-qualify-fails)
      setup "$CASE" start fail-qualify; start_setup; m tb-mode validation; val_models
      cp "$ROOT/deploy/gcp/validation-site-answers.yaml" "$S/metadata/tb-site-answers"
      rm -f "$S/metadata/tb-answers-secret" "$S/metadata/tb-answers-version"; boot; to_the_end ;;
    build-validation)
      setup "$CASE" build; build_setup; m tb-mode validation; rm -f "$S/metadata/tb-vendor-key-secret" "$S/metadata/tb-vendor-key-version"
      boot; to_the_end ;;
    acc) setup "$CASE" "start acc" acc-tripwire; start_setup; acc_setup; boot; to_the_end; acc_collect ;;
    acc-gate) setup "$CASE" "start acc" acc-screen-empty; start_setup; acc_setup; boot; to_the_end ;;
    acc-redo)   # acc-gate's stop, then the fix and --resume --redo 60-acc-jmed: the set again from no work, new mails
      setup "$CASE" "start acc" acc-screen-empty; start_setup; acc_setup; boot
      wait_for "the done marker" is_done; wait_for "the power-off" is_off
      rm -f "$S/knobs/acc-screen-empty"; m tb-retry "retry-1"; m tb-redo "60-acc-jmed"; boot; to_the_end ;;
    acc-preempt)
      setup "$CASE" "start acc"; echo 1.5 > "$S/knobs/acc-job-seconds"; start_setup; acc_setup
      m tb-acc-tripwire-setting TB_GATEWAY_PHI_TRIPWIRE=off; boot
      wait_for "the first set's second protocol to be mailed" grep -q '^acc-send FEAS MNCT90000002 new$' "$S/calls.log"
      "$HERE/standins/reboot.sh" "$S"            # a pre-emption in the middle of the set
      to_the_end; acc_collect ;;
    acc-blocked) setup "$CASE" "start acc" acc-blocked; start_setup; acc_setup; boot; to_the_end ;;
    session) setup "$CASE" "dev session" dev-routes; session_setup DEV; boot; to_the_end ;;
    session-stop)   # the session asks for more than the cap leaves: it ends at the cap less its margin, closed first;
      # lane D's units enabled on the disk (rounds 3 and 4): off while the accounts are open, put back after the close
      # H-148: a "minute" of 2 s here (knob minute-s, read by standins/boot.sh): the bring-up must open the session
      # before the cap less its margin, and on a loaded runner 50 s of 1 s minutes was not always enough
      setup "$CASE" "dev session" unit-enabled ops-timer; echo 2 > "$S/knobs/minute-s"
      session_setup VALIDATION; m tb-session-minutes 600; m tb-max-minutes 60; boot; to_the_end ;;
    session-cut)
      setup "$CASE" "dev session" dev-routes; session_setup DEV; m tb-session-minutes 600; m tb-max-minutes 900; boot
      wait_for "the session to open" grep -aq 'TB-SESSION-READY' "$S/boot-1.out"
      "$HERE/standins/reboot.sh" "$S"            # a power cut while the owner reads a page
      to_the_end ;;
    session-close-fails)
      setup "$CASE" "dev session" dev-routes; session_setup DEV; m tb-session-minutes 600; m tb-max-minutes 900; boot
      wait_for "the session to open" grep -aq 'TB-SESSION-READY' "$S/boot-1.out"
      touch "$S/knobs/disable-fails"             # the console cannot be asked at the next boot
      "$HERE/standins/reboot.sh" "$S"
      to_the_end ;;
    session-update-fails) setup "$CASE" "dev session" update-fails; session_setup VALIDATION; boot; to_the_end ;;
    session-cut-56)   # round 3's finding 4: a cut while 56 opens the accounts; a later boot without tb-retry
      setup "$CASE" "dev session" dev-routes people-slow; session_setup DEV; m tb-session-minutes 600; m tb-max-minutes 900
      boot; wait_for "56 to open the accounts" grep -q '^session-people-start$' "$S/calls.log"
      "$HERE/standins/reboot.sh" "$S"            # a power cut (or a start by hand, a host restart): no tb-retry
      to_the_end ;;
    session-unit|session-unit-race)   # round 3's finding 1: lane D's trialbox.service enabled on the disk, a cut
      k=(dev-routes unit-enabled); [ "$CASE" = session-unit ] || k+=(unit-late unit-reenabled)
      setup "$CASE" "dev session" "${k[@]}"; session_setup DEV; m tb-session-minutes 600; m tb-max-minutes 900; boot
      wait_for "the session to open" grep -aq 'TB-SESSION-READY' "$S/boot-1.out"
      "$HERE/standins/reboot.sh" "$S"
      to_the_end ;;
    session-unit-fails) setup "$CASE" "dev session" unit-enabled unit-disable-fails; session_setup VALIDATION; boot; to_the_end ;;
    session-unit-dbus) setup "$CASE" "dev session" unit-enabled unit-dbus-error; session_setup VALIDATION; boot; to_the_end ;;
    session-ops|session-quiet-fails|session-ss-fails)   # round 4's b, a, f: a power cut while the session is open
      case "$CASE" in session-ops) k=(ops-timer ops-late unit-reenabled) ;; session-quiet-fails) k=(unit-enabled unit-reenabled unit-stop-hangs) ;;
        *) k=() ;; esac
      setup "$CASE" "dev session" dev-routes ${k[@]+"${k[@]}"}; session_setup DEV; m tb-session-minutes 600; m tb-max-minutes 900
      boot; wait_for "the session to open" grep -aq 'TB-SESSION-READY' "$S/boot-1.out"
      [ "$CASE" != session-ss-fails ] || touch "$S/knobs/ss-fails"   # ss gives no answer at the next boot
      "$HERE/standins/reboot.sh" "$S"
      to_the_end ;;
    session-ended-again)   # round 4's g: the run ends with its accounts open; a later boot of the same run closes them
      setup "$CASE" "dev session" dev-routes; session_setup DEV; m tb-session-minutes 600; m tb-max-minutes 900; boot
      wait_for "the session to open" grep -aq 'TB-SESSION-READY' "$S/boot-1.out"
      touch "$S/knobs/disable-fails"; "$HERE/standins/reboot.sh" "$S"
      wait_for "the done marker" is_done; wait_for "the power-off" is_off
      rm -f "$S/knobs/disable-fails"; "$HERE/standins/boot.sh" "$S"   # started again (by hand, or a later launch's start)
      to_the_end ;;
    session-wide) S="$REH/$CASE"; rm -rf "$S"; mkdir -p "$S"; session_wide ;;
    session-egress) setup "$CASE" "dev session" dev-routes egress-open; session_setup DEV; boot; to_the_end ;;
    session-dev-refused) setup "$CASE" "dev session"; session_setup DEV; boot; to_the_end ;;
    session-skip)
      setup "$CASE" "dev session"; session_setup VALIDATION
      m tb-skip "08-qualify 09-promote-judge 10-promote-verifier 11-resolve 12-doctor 55-session-egress"; boot; to_the_end ;;
    session-resume)
      setup "$CASE" "dev session"; session_setup VALIDATION; boot
      wait_for "the session's data step" grep -aq 'TB-STEP 53-acc-data start' "$S/boot-1.out"
      kill -KILL -- "-$(cat "$S/vm.pgid")" 2>/dev/null || true; echo TERMINATED > "$S/status"   # a pre-emption
      m tb-retry "retry-1"   # the driver's --resume (refused there too; here the VM's own refusal is rehearsed)
      boot; to_the_end ;;
    session-ssh) setup "$CASE" "dev session" ssh-listens; session_setup VALIDATION; boot; to_the_end ;;
    session-then-acc)
      setup "$CASE" "dev session"; session_setup VALIDATION; boot; to_the_end
      mv "$S/evidence/results" "$S/evidence/results-session"
      for k in tb-session-env tb-session-minutes tb-session-synth tb-session-idle-minutes tb-session-handoff \
               tb-session-people tb-skip block-project-ssh-keys; do rm -f "$S/metadata/$k"; done
      RUNID="rehearsal-$CASE-acc"; m tb-run-id "$RUNID"; m tb-steps acc; boot; to_the_end; RUNID="" ;;
    *) die "no such case: $CASE" ;;
  esac
  python3 "$HERE/check.py" "$CASE" "$S" || die "case $CASE: the checks above"
  vm_kill
  log "case $CASE passed"
done
log "all cases passed: ${CASES[*]}"
