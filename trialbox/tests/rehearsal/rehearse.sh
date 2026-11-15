#!/usr/bin/env bash
# The cloud run's local rehearsal (D-150; review of 2026-11-09 §5): the gate before any paid launch (RUNBOOK §11).
#
#   make rehearse                       # every case below, about 40-60 minutes, US$0
#   tests/rehearsal/rehearse.sh [CASE ...]   # some cases, in order: run-a run-b bucket served no-upload hang hang-driven busy
#                                            # preempt
#   make rehearse CASES=run-a,bucket    # commas or spaces
#
# It runs the REAL driver (deploy/gcp/complete-run.sh, the commit at HEAD, as `git archive` uploads it) against the REAL
# VM script (deploy/gcp/complete-run-vm.sh, unchanged) booted in an Ubuntu 24.04 container that stands in for
# tb-gpu-sim; only what costs money or needs the cloud is replaced:
#   * gcloud (driver-shims/gcloud): the VM is the container; start = a boot (vm/boot.sh), metadata = files; Secret
#     Manager and the bucket are folders of the state (the VM's own gcloud, shims/gcloud, reads the same folders);
#   * on the "VM" (shims/): the GCE metadata server, systemd (systemd-run, poweroff), docker (the two vLLM servers are
#     strict stand-ins, vllm_standin.py: key checked, 404 for any but the served name; nginx is the real nginx with the
#     script's own config), nvidia-smi; docker's DNS (dns_standin.py);
#   * the network: the sandbox's HTTPS proxy and its CA (apt, PyPI, nodejs.org, npm, Playwright's CDN, Maven Central,
#     NAIST, NIST, NCBI and ClinicalTrials.gov are the real ones).
# One container is one disk, booted again and again, as the VM's disk is kept:
#   run-a      a fresh disk, a bounded run: --patients 500 --only hospital-ja public-ja scenario-gateway
#              scenario-emr-fhir scenario-it-dump scenario-public-medtxt scenario-public-trec, driven with --no-wait
#              and repeated --collect: setup, the data fetch (C-02, C-03), the model servers' check (H-02), the parts,
#              results.tgz per part, power-off once collected;
#   run-b      the same disk, a new run (scenario-gateway scenario-it-dump): nothing kept from run-a (H-01), a fresh
#              log (M-01), the report's HEAD is the launched commit (M-02);
#   bucket     the same disk, TB_BUCKET set (T-119): the code and the results go through the bucket, not the door;
#              the VM powers off at once after its last upload (TB-BUCKET-DONE, B7), not after its grace;
# In every case the door is TLS on 443 with the driver's pinned certificate, the key comes from "Secret Manager" (never
# the metadata), its version is destroyed once collected, and the serving record is captured (T-119).
#   served     the judge serves a wrong name: the boot stops before any part with TB-SERVING-FAILED, results say why;
#   no-upload  nobody uploads: TB-NO-CODE after the (1-minute) wait, power-off at once (no grace: A6);
#   hang       a silent, stuck part (selftest-hang) and no driver: the watchdog powers off after the idle limit
#              (2 minutes here); --collect then starts the stopped VM results-only and gets what is there (H-04);
#              the first results-only start is refused (a stockout): said, nothing marked, the next collect starts it;
#   hang-driven  the same stuck part with a driver following it (wait mode, a poll every minute; one status describe
#              fails on the way): the poll touches driver-alive, not the heartbeat, so the VM powers off within the
#              idle limit; "unknown" is not the end of the run; the driver then collects results-only and resets it;
#   busy      a silent part that works for 5 minutes (selftest-busy), idle limit 2 minutes, no driver: the in-run
#              heartbeat keeps the VM alive (H-03); it finishes, powers off after the grace; --collect gets the result.
#   preempt    G1 bug A1: three short parts done, the VM pre-empted (stopped without warning) while the fourth, a
#              silent selftest-busy, runs; --collect starts it results-only and gets the three; then the same run is
#              started again (`TB_RUN_ID=<run> complete-run.sh --shard 1`): the three are kept (--resume), only the
#              fourth runs, and no collect removed a finished part.
# Every case is checked by check.py; the evidence stays in $TB_REHEARSAL_DIR/evidence/<case>/.
#
# Needs: docker (a private dockerd is started under $TB_REHEARSAL_DIR when none answers, and stopped afterwards),
# about 4 GB of disk, the ports 443, 8080, 127.0.0.2-3:8000 and 127.0.0.11:53 free (the container shares the host's
# network), and the sandbox proxy for egress. TB_REHEARSAL_KEEP=1 keeps the container and the daemon for a look.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TBROOT="$(cd "$HERE/../.." && pwd)"
REH="${TB_REHEARSAL_DIR:-/tmp/tb-rehearsal}"
C=tb-rehearsal-vm
IMG=tb-rehearsal/ubuntu:24.04.5
BASE_URL=https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.5-base-amd64.tar.gz
BASE_SHA=e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86
CA="${TB_REHEARSAL_CA:-${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}}"
VENV="$(readlink -f "$TBROOT/.venv")"
PY="$VENV/bin/python"
PRE_ONLY=scenario-gateway,scenario-it-dump,scenario-registry,selftest-busy   # the preempt case: 3 short parts, 1 long
POS_ONLY="${TB_REHEARSAL_ONLY:-hospital-ja,public-ja,scenario-gateway,scenario-emr-fhir,scenario-it-dump,scenario-public-medtxt,scenario-public-trec}"
# shellcheck disable=SC2206  # CASES=run-a,bucket from make: split on commas and spaces
CASES=(${*//,/ }); [ "${#CASES[@]}" -gt 0 ] || CASES=(run-a run-b bucket served no-upload hang hang-driven busy preempt)
S="$REH/state"
mkdir -p "$REH" "$REH/evidence"
log() { echo "$(date -u +%T) rehearse: $*"; }

# ------------------------------------------------------------------ docker: the host's, else a private daemon
OWN_DOCKERD=0
if ! docker info >/dev/null 2>&1; then
  SOCK="${TB_REHEARSAL_SOCK:-/tmp/tbreh}"   # a short path: unix sockets are limited to about 100 characters
  export DOCKER_HOST="unix://$SOCK/docker.sock"
  if ! docker info >/dev/null 2>&1; then
    log "starting a private dockerd under $REH (vfs, no bridge, no iptables)"
    mkdir -p "$REH/docker" "$SOCK/exec"
    nohup dockerd --data-root "$REH/docker" --exec-root "$SOCK/exec" --pidfile "$SOCK/dockerd.pid" -H "$DOCKER_HOST" \
      --bridge=none --iptables=false --ip6tables=false --storage-driver=vfs > "$REH/dockerd.log" 2>&1 &
    for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
    docker info >/dev/null 2>&1 || { tail -n 20 "$REH/dockerd.log"; exit 1; }
    OWN_DOCKERD=1
  fi
fi
prune_evidence() {  # D-201: the newest two per case, <case> and <case>.prev; older copies <case>.<anything> go
  local d name c
  for d in "$REH/evidence"/*.*; do
    [ -e "$d" ] || continue
    name="$(basename "$d")"
    for c in "${CASES[@]}" run-a run-b bucket served no-upload hang hang-driven busy preempt; do
      if [ "${name%%.*}" = "$c" ] && [ "$name" != "$c.prev" ]; then rm -rf "$d"; break; fi
    done
  done
}
cleanup() {
  [ "${TB_REHEARSAL_KEEP:-0}" = 1 ] && { log "kept: container $C, DOCKER_HOST=${DOCKER_HOST:-default}"; return; }
  docker exec "$C" sh -c 'ip addr del 172.17.0.1/32 dev lo 2>/dev/null; ip link del docker0 2>/dev/null; kill -TERM -1' \
    >/dev/null 2>&1 || true
  docker rm -f "$C" >/dev/null 2>&1 || true
  docker rmi "$IMG" >/dev/null 2>&1 || true
  if [ "$OWN_DOCKERD" = 1 ]; then
    kill "$(cat "$SOCK/dockerd.pid")" 2>/dev/null || true
    for _ in $(seq 1 30); do [ -e "$SOCK/dockerd.pid" ] || break; sleep 1; done
    # dockerd leaves its data root and network namespace mounted
    awk -v a="$REH/docker" -v b="$SOCK" 'index($2, a) == 1 || index($2, b) == 1 {print $2}' /proc/mounts | sort -r \
      | while read -r m; do umount "$m" 2>/dev/null || true; done
    rm -rf "$REH/docker" "$SOCK"
  fi
  rm -rf "$S" "$REH/runs" "$REH/base.tgz"
  prune_evidence
  log "cleaned up (evidence kept in $REH/evidence: the newest two per case)"
}
trap cleanup EXIT

# ------------------------------------------------------------------ the "VM": an Ubuntu 24.04 disk, prepared once
fresh_disk() {
  docker rm -f "$C" >/dev/null 2>&1 || true
  rm -rf "$S"; mkdir -p "$S/metadata" "$S/units" "$S/knobs/metadata" "$S/bucket"
  mkdir -p "$S/secrets/tb-gpu-door"   # the door's secret, as deploy/gcp/setup-gcp.sh makes it once (T-119)
  echo TERMINATED > "$S/status"
  if ! docker image inspect "$IMG" >/dev/null 2>&1; then
    log "fetching the Ubuntu 24.04 base"
    curl -fsSL -o "$REH/base.tgz" "$BASE_URL"
    echo "$BASE_SHA  $REH/base.tgz" | sha256sum -c --quiet -
    docker import "$REH/base.tgz" "$IMG" >/dev/null && rm -f "$REH/base.tgz"
  fi
  # the container shares the host's network (the stand-ins and nginx listen where the driver expects the VM)
  docker run -d --name "$C" --network host --cap-add NET_ADMIN \
    -e HTTPS_PROXY="${HTTPS_PROXY:-}" -e https_proxy="${HTTPS_PROXY:-}" -e NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}" \
    -e no_proxy="${NO_PROXY:-127.0.0.1,localhost}" \
    -v "$HERE:/rehearsal/h:ro" -v "$S:/rehearsal/s" -v "$TBROOT:/rehearsal/repo:ro" -v "$VENV:/rehearsal/venv:ro" \
    -v "$CA:/rehearsal/ca.crt:ro" "$IMG" sleep infinity >/dev/null
  log "preparing the disk (the GCE base image's packages)"
  docker exec "$C" bash /rehearsal/h/vm/prep.sh
}

# ------------------------------------------------------------------ the driver, exactly as the operator runs it
export TB_REH_STATE="$S" TB_REH_CONTAINER="$C" CLOUDSDK_CONFIG="$REH/gcloud-config" TB_SA_KEY_FILE=/dev/null
# the "VM" is this host (127.0.0.1): the driver reaches its door directly though the sandbox sets HTTPS_PROXY (A6)
export TB_DOOR_DIRECT=1
# the stand-ins answer, not the models: a rehearsal is never product evidence, so it launches past the validation
# reset's gate (complete-run.sh --not-product-evidence), as the operator would for a plumbing run
export TB_NOT_PRODUCT_EVIDENCE=1
# shellcheck source=deploy/gcp/door-tls.sh
. "$TBROOT/deploy/gcp/door-tls.sh"   # door_make for the no-upload case, which has no driver
mkdir -p "$CLOUDSDK_CONFIG"
drive() {  # $1 case; the driver's arguments follow (a new run id per case)
  local case=$1 rid; shift
  rid="rehearsal-$case-$(date -u +%H%M%S)"
  rm -rf "$REH/runs/$case"; mkdir -p "$REH/runs/$case"; echo "$rid" > "$REH/runs/$case/run-id"
  PATH="$HERE/driver-shims:$PATH" TB_COMPLETE_DIR="$REH/runs/$case" TB_RUN_ID="$rid" \
    "$TBROOT/deploy/gcp/complete-run.sh" "$@" >> "$REH/evidence/$case/driver.log" 2>&1
}
collect_until_done() {  # $1 case, $2 minutes: --collect again and again, as an operator with a short-lived shell would
  local case=$1 minutes=$2
  for _ in $(seq 1 $((minutes * 2))); do
    sleep 30
    PATH="$HERE/driver-shims:$PATH" TB_COMPLETE_DIR="$REH/runs/$case" \
      "$TBROOT/deploy/gcp/complete-run.sh" --collect "$(cat "$REH/runs/$case/run-id")" >> "$REH/evidence/$case/driver.log" 2>&1 || true
    case "$(cat "$REH/runs/$case/shard-1/state" 2>/dev/null)" in done|noresults) return 0 ;; esac
  done
  return 1
}
wait_terminated() {  # $1 minutes
  for _ in $(seq 1 $(($1 * 6))); do [ "$(cat "$S/status")" = TERMINATED ] && return 0; sleep 10; done
  return 1
}
knob() { mkdir -p "$S/knobs/metadata"; printf '%s' "$2" > "$S/knobs/metadata/$1"; }
start_case() {  # $1 case: its evidence folder; the console, power-off and stand-in logs from here on are this case's
  E="$REH/evidence/$1"
  if [ -d "$E" ]; then rm -rf "$E.prev"; mv "$E" "$E.prev"; fi   # the newest two per case (D-201): this and .prev
  mkdir -p "$E"
  : > "$S/console.log"; : > "$S/POWEROFF"; : > "$S/gcloud.log"; : > "$S/vm-gcloud.log"
  for n in judge verifier; do : > "$S/units/$n.log"; done
  rm -rf "$S/knobs"; mkdir -p "$S/knobs/metadata"
  for k in "$S"/metadata/*; do  # metadata stays on a VM between starts; a case's own knobs must not reach the next
    case "$(basename "$k")" in tb-code-wait-minutes|tb-selftest-seconds|tb-idle-minutes|tb-done-grace) rm -f "$k" ;; esac
  done
  knob tb-min-free-gb 2   # the sandbox's disk, not the VM's 50 GB floor
  log "case $1"
}
end_case() {  # keep this case's evidence
  cp "$S/console.log" "$S/POWEROFF" "$S/gcloud.log" "$S/vm-gcloud.log" "$E/" 2>/dev/null || true
  ls "$S/metadata" > "$E/metadata-keys" 2>/dev/null || true   # names only (T-119: no tb-key among them)
  find "$S/secrets" -type f ! -name .last -printf '%P\n' > "$E/secrets-left" 2>/dev/null || true
  for n in judge verifier front tb-door tb-watchdog; do cp "$S/units/$n.log" "$E/standin-$n.log" 2>/dev/null || true; done
  docker cp "$C:/var/lib/tb/out/results.tgz" "$E/vm-results.tgz" >/dev/null 2>&1 || true
  [ -d "$REH/runs/$1" ] && cp -r "$REH/runs/$1" "$E/out" 2>/dev/null || true
  rm -f "$E/out/shard-1/tb-key" "$E/out/shard-1/door.key" "$E/out/shard-1/door-secret.json" "$E/out/src.tgz"
}
driven() {  # $1 case, $2 minutes, driver args...: --no-wait, then --collect until done
  local case=$1 minutes=$2; shift 2
  drive "$case" --no-wait "$@" || true
  grep -q "^started " "$REH/evidence/$case/driver.log" \
    || { log "$case: the driver did not start the VM"; tail -n 20 "$REH/evidence/$case/driver.log"; return 1; }
  collect_until_done "$case" "$minutes" || log "$case: not done after $minutes minutes"
  wait_terminated 5 || log "$case: the VM did not power off within 5 minutes of the collection"
}

FAILED=()
check() { "$PY" "$HERE/check.py" "$@" || FAILED+=("$1"); }
[ "${CASES[0]}" = run-a ] || docker inspect "$C" >/dev/null 2>&1 || fresh_disk
mkdir -p "$S/secrets/tb-gpu-door" "$S/bucket"   # a disk kept from an older harness (TB_REHEARSAL_KEEP=1)
for case in "${CASES[@]}"; do
  case "$case" in
    run-a)
      fresh_disk; start_case run-a
      driven run-a 75 --patients 500 --only "$POS_ONLY" || true
      end_case run-a; check run-a "$E" --only "$POS_ONLY" --head "$(git -C "$TBROOT" rev-parse HEAD)" ;;
    run-b)
      start_case run-b
      prev="$(cat "$REH/evidence/run-a/out/run-id" 2>/dev/null || echo none)"
      driven run-b 30 --patients 500 --only scenario-gateway,scenario-it-dump || true
      end_case run-b; check run-b "$E" --only scenario-gateway,scenario-it-dump --head "$(git -C "$TBROOT" rev-parse HEAD)" --previous "$prev" ;;
    bucket)  # T-119: TB_BUCKET; the code and the results through the bucket, the door only for heartbeat and progress
      start_case bucket; mkdir -p "$S/bucket/tb-rehearsal-bucket"   # made once, as setup-gcp.sh TB_BUCKET=... does
      TB_BUCKET=gs://tb-rehearsal-bucket driven bucket 30 --patients 500 --only scenario-it-dump || true
      end_case bucket; check bucket "$E" --only scenario-it-dump --head "$(git -C "$TBROOT" rev-parse HEAD)" ;;
    served)
      start_case served; echo "local/not-the-judge" > "$S/knobs/served-judge"
      driven served 20 --patients 500 --only scenario-it-dump || true
      end_case served; check served "$E" ;;
    no-upload)  # no driver: the VM is started as the driver would, and nobody uploads
      start_case no-upload; knob tb-code-wait-minutes 1; knob tb-done-grace 1
      rm -rf "$REH/no-upload-door"; mkdir -p "$REH/no-upload-door"; PY="$PY" door_make "$REH/no-upload-door"
      ver="$(PATH="$HERE/driver-shims:$PATH" gcloud secrets versions add tb-gpu-door \
        --data-file="$REH/no-upload-door/door-secret.json" --format='value(name)')"
      PATH="$HERE/driver-shims:$PATH" gcloud compute instances add-metadata "$C" --metadata-from-file \
        "startup-script=$TBROOT/deploy/gcp/complete-run-vm.sh,tb-door-cert=$REH/no-upload-door/door.crt" \
        --metadata "tb-door-secret=tb-gpu-door,tb-door-version=${ver##*/},tb-run-id=rehearsal-no-upload,tb-only=scenario-it-dump,tb-collect-only=0,tb-max-minutes=60"
      PATH="$HERE/driver-shims:$PATH" gcloud compute instances start "$C"
      wait_terminated 15 || log "no-upload: still running after 15 minutes"
      PATH="$HERE/driver-shims:$PATH" gcloud secrets versions destroy "${ver##*/}" --secret tb-gpu-door --quiet || true
      rm -rf "$REH/no-upload-door"; end_case no-upload; check no-upload "$E" ;;
    hang)
      start_case hang; knob tb-idle-minutes 2; knob tb-done-grace 1; knob tb-selftest-seconds 900
      drive hang --no-wait --patients 500 --only selftest-hang || true
      wait_terminated 30 || log "hang: still running after 30 minutes"
      cp "$S/POWEROFF" "$REH/evidence/hang/POWEROFF.run"
      rm -rf "$S/knobs/metadata"
      echo 1 > "$S/knobs/start-fail"   # the first results-only start is refused (a stockout): tried again, not given up
      collect_until_done hang 15 || log "hang: no results after 15 minutes"
      wait_terminated 5 || true
      end_case hang; check hang "$E" ;;
    hang-driven)  # the stuck part with a driver following it (wait mode): its poll must not keep the part alive
      start_case hang-driven; knob tb-idle-minutes 2; knob tb-done-grace 1; knob tb-selftest-seconds 900
      drive hang-driven --patients 500 --only selftest-hang &
      dpid=$!
      for _ in $(seq 1 180); do grep -q "^started " "$E/driver.log" 2>/dev/null && break; sleep 5; done
      echo 1 > "$S/knobs/describe-fail"   # one status describe fails while it follows: "unknown" is not the end
      wait_terminated 30 || log "hang-driven: still running after 30 minutes"
      cp "$S/POWEROFF" "$E/POWEROFF.run"
      rm -rf "$S/knobs/metadata"
      for _ in $(seq 1 120); do kill -0 "$dpid" 2>/dev/null || break; sleep 10; done   # it collects, then ends
      kill "$dpid" 2>/dev/null || true; wait "$dpid" 2>/dev/null || true
      wait_terminated 5 || true
      end_case hang-driven; check hang-driven "$E" ;;
    busy)
      start_case busy; knob tb-idle-minutes 2; knob tb-done-grace 1; knob tb-selftest-seconds 300
      drive busy --no-wait --patients 500 --only selftest-busy || true
      wait_terminated 40 || log "busy: still running after 40 minutes"
      cp "$S/POWEROFF" "$REH/evidence/busy/POWEROFF.run"
      rm -rf "$S/knobs/metadata"
      collect_until_done busy 15 || log "busy: no results after 15 minutes"
      wait_terminated 5 || true
      end_case busy; check busy "$E" ;;
    preempt)  # G1 bug A1: pre-empted after part 3, collected, resumed; the parts already done are kept
      start_case preempt; knob tb-selftest-seconds 1800
      drive preempt --no-wait --patients 500 --only "$PRE_ONLY" || true
      for _ in $(seq 1 360); do  # the three short parts are done; the silent fourth runs
        [ "$(docker exec "$C" sh -c 'ls /var/lib/tb/runs/*/parts/*.json 2>/dev/null | wc -l')" -ge 3 ] && break
        sleep 10
      done
      sleep 20   # tb-pack after part 3 has written results.tgz
      PATH="$HERE/driver-shims:$PATH" gcloud compute instances stop "$C" >/dev/null 2>&1 || true   # the pre-emption
      wait_terminated 2 || log "preempt: the VM did not stop"
      cp "$S/POWEROFF" "$E/POWEROFF.preempt"; : > "$S/POWEROFF"
      rm -rf "$S/knobs/metadata"
      collect_until_done preempt 15 || log "preempt: no results after the pre-emption"
      cp -r "$REH/runs/preempt/parts" "$E/parts-after-collect" 2>/dev/null || true
      wait_terminated 5 || true
      knob tb-selftest-seconds 5
      PATH="$HERE/driver-shims:$PATH" TB_COMPLETE_DIR="$REH/runs/preempt" TB_RUN_ID="$(cat "$REH/runs/preempt/run-id")" \
        "$TBROOT/deploy/gcp/complete-run.sh" --no-wait --shard 1 >> "$E/driver.log" 2>&1 || true   # the resume
      collect_until_done preempt 45 || log "preempt: the resumed run is not done after 45 minutes"
      wait_terminated 5 || true
      end_case preempt; check preempt "$E" --only "$PRE_ONLY" ;;
    *) echo "unknown case $case" >&2; exit 2 ;;
  esac
done
if [ "${#FAILED[@]}" -gt 0 ]; then log "REHEARSAL FAILED: ${FAILED[*]} (evidence in $REH/evidence)"; exit 1; fi
log "REHEARSAL PASSED: ${CASES[*]} (evidence in $REH/evidence)"
