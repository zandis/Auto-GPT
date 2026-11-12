#!/usr/bin/env bash
# TrialBox complete-platform run on the RTX PRO 6000 (TB-PLAN-04 step 9, D-139, D-141, D-148, D-150). Owner's OK first:
# it starts paid VMs (tb-gpu-sim and its clones, g4-standard-48 spot, about US$2.74 an hour each).
# Gate before any paid launch: `make rehearse` passes on the commit to launch (tests/rehearsal, RUNBOOK §11).
#
#   export CLOUDSDK_CONFIG=<a private folder>              # never the default one
#   export TB_SA_KEY_FILE=<the service account key file>   # every command activates from it (its path, to gcloud)
#   gcloud config set project trialbox-demo                # once, in that config
#   deploy/gcp/complete-run.sh --estimate [--patients 50000] [--vms N] [--parts g1,embed,profile] [--only TAG,TAG]
#   deploy/gcp/complete-run.sh --dry-run [--vms N] [--zones z1,z2] [--parts ...] [--only TAG,TAG] [VM] [ZONE]
#   deploy/gcp/complete-run.sh --provision --vms N --zones z1,z2,...   # once: the clones tb-gpu-sim-2..N (they
#                                                                      # boot, power off at once, keep their disks)
#   deploy/gcp/complete-run.sh [--patients 50000] [--vms N] [--zones ...] [--parts ...] [--only TAG,TAG] [--hours H]
#                              [--no-wait | --detach]
#   deploy/gcp/complete-run.sh --collect <run id> [--follow]   # later, as often as wanted: see below
#   deploy/gcp/complete-run.sh --stop [--collect <run id> | --vms N --zones ...] [VM] [ZONE]   # stop by hand
#   deploy/gcp/complete-run.sh --teardown --vms N --zones ...   # delete the clones 2..N and their machine image
#
# The operator's shell may not outlive the run (a 9-hour run, a 2-hour shell: review H-04). The flow that needs no
# long-lived driver: start with --no-wait (it returns once the code is uploaded), then `--collect <run id>` now and
# then. Each --collect is short: one look at every VM, the results packed so far (the VM re-packs results.tgz after
# every part), the merge and the report so far; it says which VMs still run. A VM that has stopped with results not
# yet here is started once in a results-only mode (tb-collect-only: no models, no run, a 20-minute cloud cap; it powers
# off as soon as the driver has collected). --follow polls until every VM is done (the old behaviour); --detach runs
# the whole driver under setsid/nohup with its log in the run folder.
#
# --only TAG,TAG: a bounded run of some parts (complete_run tags, e.g. hospital-ja,scenario-gateway): the estimate, the
# cap and the plan hold only those parts (and prepare for a hospital part, install when named); no stub parts.
#
# Parallel (D-148): --vms N splits the run into N shards of whole parts (complete_run --only tags; longest first onto
# the least-loaded VM, tools/complete_run.py shard_plan): no part is split, so the merged report is the single-VM
# report. VM 1 is VM (tb-gpu-sim) in the first zone, VM i is VM-i in zone i (--zones, or TB_ZONES; one zone per
# region where the GPU quota is 1 per region). Every VM gets its own cap, key, watchdog and run directory
# (<run>/shard-<i>); the driver runs one child per VM, waits for all, merges parts/ and the screenshots, runs the
# stub parts and writes one report. --parts: g1 (the complete run), embed and profile (the benches,
# tools/bench_embed.py and tools/bench_profile.py); e.g. --parts g1,embed,profile. Before any start or --provision the
# driver reads the GPU and CPU quota (read-only) and refuses when N VMs cannot run (review H-05).
#
# Fail-safe (D-141; the 2026-11-09 incident: a dead driver left the VM running for 61 minutes), per VM:
#   1. Cloud-side hard cap, set before the start: max-run-duration of that VM's estimate x 1.3 rounded up (--hours to
#      change it), termination action STOP. Compute Engine stops the VM at the cap whatever else happens.
#   2. The VM stops itself (deploy/gcp/complete-run-vm.sh): a systemd hard cap, and a watchdog per phase; in the run it
#      powers off when no part has worked for 20 minutes (an in-run heartbeat, D-150), and after the done marker (at
#      once when the driver has collected, else 30 minutes later).
#   3. The workload runs on the VM (48 vCPU): the driver uploads the code (git archive of HEAD with TB_HEAD.json; its
#      sha256 goes in the metadata and the VM refuses anything else), polls, downloads the results and runs the stub
#      parts (walk, backup, update, scale) here once the VMs have stopped. The driver can die at any moment.
#   4. Every command activates the service account from TB_SA_KEY_FILE and probes the token first (gc_start); every
#      gcloud call goes through `gc` (deploy/gcp/gcloud-auth.sh): it has a timeout, and an auth error or a timeout
#      re-activates and retries once, then fails fast with "credentials expired: re-activate" (G1 bug A2).
#   5. Every part is resumable within its run: a restarted VM runs complete_run --resume, which keeps only parts of the
#      same run (<run id> and <run id>-s<N> are one run) and HEAD, and removes a stale result only of a part it runs
#      itself, so the collect's stub parts never remove the VMs' parts (G1 bug A1). A preempted VM:
#      `TB_RUN_ID=<run id> complete-run.sh --shard <i>` starts it again; `make rehearse CASES=preempt` rehearses it.
# The door (T-119, CR-048): HTTPS on 443 only, the VM's self-signed certificate made here per run and its public key
# pinned (deploy/gcp/door-tls.sh); no port 80. The bearer key and the TLS key go to the VM through Secret Manager
# (secret tb-gpu-door, one version per VM and run, destroyed once the results are here), never as metadata; a tb-key
# an older driver left in the metadata is removed. Before the start the driver refuses a VM without a service account
# and a firewall that opens tcp:80 to it or does not open tcp:443 (read-only, door_firewall_check).
# Optional TB_BUCKET=gs://<bucket>: code and results go through the bucket (the VM's service account needs storage
# access); without it they go through the door.
set -euo pipefail
ARGS=("$@")
DRY=0; STOP=0; ESTIMATE=0; WAIT=1; PATIENTS=50000; HOURS=""; COLLECT=""; VMS=1; PARTS=g1; ZONES="${TB_ZONES:-}"
SHARD=""; PROVISION=0; TEARDOWN=0; FOLLOW=0; DETACH=0; ONLY_TAGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --stop) STOP=1; shift ;;
    --estimate) ESTIMATE=1; shift ;;
    --no-wait) WAIT=0; shift ;;
    --follow) FOLLOW=1; shift ;;
    --detach) DETACH=1; shift ;;
    --patients) PATIENTS="$2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    --collect) COLLECT="$2"; shift 2 ;;
    --vms) VMS="$2"; shift 2 ;;
    --parts) PARTS="$2"; shift 2 ;;
    --zones) ZONES="$2"; shift 2 ;;
    --only) IFS=, read -r -a ONLY_TAGS <<< "$2"; shift 2 ;;
    --shard) SHARD="$2"; shift 2 ;;
    --provision) PROVISION=1; shift ;;
    --teardown) TEARDOWN=1; shift ;;
    -h|--help) sed -n 2,54p "$0"; exit 0 ;;
    *) break ;;
  esac
done
case "$VMS" in ''|*[!0-9]*|0) echo "--vms: a whole number from 1" >&2; exit 2 ;; esac
VM="${1:-tb-gpu-sim}"; ZONE="${2:-asia-east1-a}"
# RTX PRO 6000 (G4) zones, one per region: candidates only; confirm with the read-only check the dry run prints
CANDIDATE_ZONES="asia-east1-a,asia-southeast1-b,us-central1-b,europe-west4-a"
[ -n "$ZONES" ] || { if [ "$VMS" = 1 ]; then ZONES="$ZONE"; else ZONES="$ZONE,${CANDIDATE_ZONES#asia-east1-a,}"; fi; }
ZONE="$(echo "$ZONES" | cut -d, -f1)"  # VM 1's zone
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
BUCKET="${TB_BUCKET:-}"
IMAGE="${TB_MACHINE_IMAGE:-$VM-img}"
export GC_DRY="$DRY"
# shellcheck source=deploy/gcp/gcloud-auth.sh
. "$ROOT/deploy/gcp/gcloud-auth.sh"
# shellcheck source=deploy/gcp/door-tls.sh
. "$ROOT/deploy/gcp/door-tls.sh"
cd "$ROOT"
cr() { env PYTHONPATH=libs:services:. "$PY" -m tools.complete_run "$@"; }
ONLY_ARGS=(); [ "${#ONLY_TAGS[@]}" = 0 ] || ONLY_ARGS=(--only "${ONLY_TAGS[@]}")

if [ "$ESTIMATE" = 1 ]; then
  cr --estimate --patients "$PATIENTS" --vms "$VMS" --parts "$PARTS" "${ONLY_ARGS[@]}" \
    ${TB_ESTIMATE_FROM:+--estimate-from "$TB_ESTIMATE_FROM"}
  exit 0
fi
if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG and activate the service account in it}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"*) echo "CLOUDSDK_CONFIG must be private" >&2; exit 2 ;; esac
fi
unset CLOUDSDK_AUTH_ACCESS_TOKEN
# every command (launch, collect, stop, a shard child, provision, teardown) activates the service account from
# TB_SA_KEY_FILE and probes the token before its first gcloud call: an activation left from an earlier command may
# have lapsed (G1 bug A2); a dead credential fails here, at once, with "credentials expired: re-activate"
gc_start || exit 5

RUN_ID="${COLLECT:-${TB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)}}"
OUT="${TB_COMPLETE_DIR:-$ROOT/.cache/complete-run/$RUN_ID}"
mkdir -p "$OUT"
umask 077
PLAN="$OUT/plan.json"
if [ "$DETACH" = 1 ] && [ -z "$SHARD" ]; then  # the driver without the operator's shell (review H-04)
  rest=(); for x in "${ARGS[@]}"; do [ "$x" = --detach ] || rest+=("$x"); done
  TB_RUN_ID="$RUN_ID" TB_COMPLETE_DIR="$OUT" setsid nohup "$0" "${rest[@]}" > "$OUT/driver.log" 2>&1 < /dev/null &
  echo "driver detached (pid $!), run $RUN_ID: tail -f $OUT/driver.log; collect later with: $0 --collect $RUN_ID"
  exit 0
fi
plan_get() {  # shard field: one value of plan.json (vm, zone, cap_hours, hours, usd, tags as one line)
  "$PY" -c 'import json,sys; s=json.load(open(sys.argv[1]))["plan"]["shards"][int(sys.argv[2])-1]; v=s[sys.argv[3]]
print(" ".join(v) if isinstance(v, list) else v)' "$PLAN" "$1" "$2"
}
vm_name() { if [ "$1" = 1 ]; then echo "$VM"; else echo "$VM-$1"; fi; }
vm_zone() { echo "$ZONES" | cut -d, -f"$1"; }
quota_check() {  # $1 = number of VMs (zones 1..N): read-only quota reads, refuse when N VMs cannot run (review H-05)
  local n=$1 zs q r
  zs="$(echo "$ZONES" | cut -d, -f1-"$n")"
  if [ "$DRY" = 1 ]; then
    echo "# the quota (read-only; the run refuses to start when $n VM(s) cannot run):"
    echo "+ gcloud compute project-info describe --format=json   # GPUS_ALL_REGIONS"
    for r in $(echo "$zs" | tr ',' '\n' | sed 's/-[^-]*$//' | awk '!seen[$0]++'); do
      echo "+ gcloud compute regions describe $r --format=json   # RTX PRO 6000 GPUs and CPUs, regular and PREEMPTIBLE"
    done
    return 0
  fi
  q="$OUT/quota"; rm -rf "$q"; mkdir -p "$q"
  gc compute project-info describe --format=json > "$q/project.json" || { echo "quota: the project's quota is not readable" >&2; return 4; }
  for r in $(echo "$zs" | tr ',' '\n' | sed 's/-[^-]*$//' | awk '!seen[$0]++'); do
    gc compute regions describe "$r" --format=json > "$q/region-$r.json" || { echo "quota: region $r is not readable" >&2; return 4; }
  done
  cr --quota-check "$q" --quota-zones "$zs"
}

# ================================================================== one VM (a shard of the plan): the D-141 run
status() { if [ "$DRY" = 1 ]; then echo TERMINATED; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(status)' || echo unknown; fi; }
stop_vm() {
  gc compute instances stop "$VM" --zone "$ZONE" || true
  local s; s="$(status)"
  echo "VM $VM status: $s"
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file startup-script="$ROOT/deploy/gcp/gpu-sim-startup.sh" || true
  gc compute instances remove-metadata "$VM" --zone "$ZONE" --keys tb-key,tb-door-version >/dev/null 2>&1 || true
}
ip() { if [ "$DRY" = 1 ]; then echo "<vm-ip>"; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)'; fi; }
door() {  # METHOD PATH [curl args...]: the VM's door over pinned TLS, the key in a header from a file (door-tls.sh)
  local m=$1 p=$2; shift 2
  if [ "$DRY" = 1 ]; then
    echo "+ curl -X $m https://$DOOR_NAME/tb/$p --resolve $DOOR_NAME:443:<vm-ip> (only $SH/door.crt trusted, its key pinned; Authorization from $KEYF)"
    return 0
  fi
  door_curl "$SH" "$IP" "$m" "$p" "$@"
}
door_vm_ready() {  # read-only but for the scope: the VM can read its door from Secret Manager; tcp:80 closed, 443 open
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute instances describe $VM --zone $ZONE --format=json   # its service account, scopes, network, tags"
    echo "+ gcloud compute firewall-rules list --format=json   # refused: tcp:80 open to the VM, or no tcp:443 (door_firewall_check)"
    echo "+ gcloud compute instances remove-metadata $VM --zone $ZONE --keys tb-key   # a key an older driver left there"
    return 0
  fi
  local sa scopes
  gc compute instances describe "$VM" --zone "$ZONE" --format=json > "$SH/vm.json" || return 1
  sa="$("$PY" -c 'import json,sys; print(((json.load(open(sys.argv[1])).get("serviceAccounts") or [{}])[0]).get("email", ""))' "$SH/vm.json")"
  scopes="$("$PY" -c 'import json,sys; print(" ".join(((json.load(open(sys.argv[1])).get("serviceAccounts") or [{}])[0]).get("scopes") or []))' "$SH/vm.json")"
  [ -n "$sa" ] || { echo "$VM has no service account: it could not read its door from Secret Manager" >&2; return 1; }
  case " $scopes " in
    *"/auth/cloud-platform "*) ;;
    *) echo "$VM: access scope cloud-platform (Secret Manager; storage for TB_BUCKET), the same service account"
       gc compute instances set-service-account "$VM" --zone "$ZONE" --service-account "$sa" --scopes cloud-platform || return 1 ;;
  esac
  gc compute firewall-rules list --format=json > "$SH/firewall.json" || return 1
  door_firewall_check "$PY" "$SH/vm.json" "$SH/firewall.json" || return 1
  gc compute instances remove-metadata "$VM" --zone "$ZONE" --keys tb-key >/dev/null 2>&1 || true
}
door_secret_add() {  # this VM's door into Secret Manager: a new version of tb-gpu-door; its number goes to the VM
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud secrets versions add $DOOR_SECRET --data-file=$SH/door-secret.json --format=value(name)   # the key and the TLS key; never metadata"
    echo 0 > "$SH/door-version"; return 0
  fi
  local v
  gc secrets describe "$DOOR_SECRET" --format='value(name)' >/dev/null \
    || { echo "no secret $DOOR_SECRET: run deploy/gcp/setup-gcp.sh once (it makes the secret and lets the VM read it)" >&2; return 1; }
  v="$(gc secrets versions add "$DOOR_SECRET" --data-file="$SH/door-secret.json" --format='value(name)')" || return 1
  rm -f "$SH/door-secret.json" "$SH/door.key"   # the VM reads its copy from Secret Manager; none stays here
  v="${v##*/}"
  case "$v" in ''|*[!0-9]*) echo "secret $DOOR_SECRET: no version number from gcloud ('$v')" >&2; return 1 ;; esac
  echo "$v" > "$SH/door-version"
}
door_retire() {  # the results are here (or there are none): destroy this VM's door version; the key file goes
  if [ "$DRY" = 1 ]; then echo "+ gcloud secrets versions destroy <version> --secret $DOOR_SECRET --quiet   # once collected"; return 0; fi
  local v; v="$(cat "$SH/door-version" 2>/dev/null || true)"
  if [ -n "$v" ] && [ "$v" != 0 ]; then
    gc secrets versions destroy "$v" --secret "$DOOR_SECRET" --quiet >/dev/null \
      || echo "secret $DOOR_SECRET version $v: not destroyed; destroy it by hand" >&2
  fi
  rm -f "$KEYF" "$SH/door-version" "$SH/door.key" "$SH/door-secret.json"
}
fetch_results() {  # this VM's results.tgz as it is now, replacing the earlier one only when the download is whole
  if [ -n "$BUCKET" ]; then gc storage cp "$BUCKET/runs/$RUN_ID-s$i/results.tgz" "$SH/results.tgz.new" || return 1
  else door GET results.tgz -o "$SH/results.tgz.new" || return 1; fi
  [ "$DRY" = 1 ] && return 0
  tar -tzf "$SH/results.tgz.new" >/dev/null 2>&1 || { rm -f "$SH/results.tgz.new"; return 1; }
  mv -f "$SH/results.tgz.new" "$SH/results.tgz"
}
wait_door() {
  for _ in $(seq 1 "${1:-90}"); do door POST heartbeat >/dev/null 2>&1 && return 0; [ "$DRY" = 1 ] && return 0; sleep 20; done
  return 1
}
collect_start() {  # a stopped VM whose results are on its disk: start it in the results-only mode (review H-04, L-03)
  echo "$VM is TERMINATED and its results are on its disk: a results-only start (no models, no run, cloud cap 20 min)"
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration=20m --instance-termination-action=STOP
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
    "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-door-cert=$SH/door.crt" \
    --metadata "tb-door-secret=$DOOR_SECRET,tb-door-version=$(cat "$SH/door-version"),tb-collect-only=1,tb-max-minutes=15,tb-done-grace=10"
  gc compute instances start "$VM" --zone "$ZONE"
  IP="$(ip)"
  wait_door 30 || { echo "$VM: the door did not answer in 10 minutes (it powers off by itself)" >&2; return 1; }
}

shard_run() {  # $1 = shard number; VM, ZONE, caps and parts come from plan.json
  local i=$1 SH TAGS EST_H EST_USD CAP_H s p done_seen=0
  VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; TAGS="$(plan_get "$i" tags)"
  EST_H="$(plan_get "$i" hours)"; EST_USD="$(plan_get "$i" usd)"; CAP_H="${HOURS:-$(plan_get "$i" cap_hours)}"
  SH="$OUT/shard-$i"; mkdir -p "$SH"; KEYF="$SH/tb-key"
  if [ -z "$COLLECT" ]; then
    echo "VM $i/$VMS $VM ($ZONE): estimate ${EST_H} h (US\$${EST_USD}); hard cap ${CAP_H} h (STOP), at most US\$$("$PY" -c "print(round($CAP_H*2.74, 2))"); parts: $TAGS"
    s="$(status)"
    [ "$s" = TERMINATED ] || { echo "$VM is $s, not TERMINATED: stop it first (--stop) or collect its run" >&2; return 3; }
    door_vm_ready || { echo "$VM: not started (see above)" >&2; return 3; }   # its door: Secret Manager, 443 only
    # ------------------------------------------------------------ 1. the cloud-side hard cap, before the start
    gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${CAP_H}h" --instance-termination-action=STOP
    [ "$DRY" = 1 ] || gc compute instances describe "$VM" --zone "$ZONE" \
      --format='value(scheduling.maxRunDuration.seconds,scheduling.instanceTerminationAction)'
    # ------------------------------------------------------------ the door (Secret Manager, TLS), the metadata, the start
    if [ "$DRY" = 1 ]; then echo "+ a random key into $KEYF, a TLS key and its self-signed certificate $SH/door.crt (0600; door_make)"
    else door_make "$SH" || { echo "$VM: the door's key or certificate could not be made (openssl)" >&2; return 3; }; fi
    door_secret_add || { echo "$VM: not started: its door is not in Secret Manager" >&2; return 3; }
    rm -f "$SH/results.tgz" "$SH/results.final" "$SH/collect-boot" "$SH/state"
    gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
      "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-door-cert=$SH/door.crt" \
      --metadata "tb-door-secret=$DOOR_SECRET,tb-door-version=$(cat "$SH/door-version"),tb-run-id=$RUN_ID-s$i,tb-patients=$PATIENTS,tb-only=$TAGS,tb-src-sha256=$SRC_SHA,tb-collect-only=0,tb-max-minutes=$((CAP_H * 60 - 5)),tb-idle-minutes=20,tb-done-grace=30${BUCKET:+,tb-bucket=$BUCKET}"
    gc compute instances start "$VM" --zone "$ZONE"
    echo "started $VM; it stops itself (cap ${CAP_H} h, watchdog). Collect, now and later: $0 --collect $RUN_ID"
    IP="$(ip)"
    if [ -z "$BUCKET" ]; then  # 3. the code through the door (TLS) once it is up (the VM waits 30 minutes for it)
      wait_door 90 || { echo "$VM: the door did not answer in 30 minutes; it powers off by itself" >&2; return 4; }
      door PUT upload --data-binary @"$OUT/src.tgz" -H 'Content-Type: application/gzip'
    fi
    [ "$WAIT" = 1 ] || return 0
  else
    [ -f "$KEYF" ] || { echo "VM $i of run $RUN_ID: results here and its key removed: nothing to collect"; return 0; }
    IP="$(ip)"
  fi
  # -------------------------------------------------------------- poll: short calls only, nothing held open
  while :; do
    s="$(status)"
    echo "$(date -u +%H:%M) $VM $s"
    [ "$s" = RUNNING ] || break
    door POST heartbeat >/dev/null 2>&1 || true
    p="$(door GET progress 2>/dev/null || true)"
    printf '%s\n' "$p" | tail -n 3
    if printf '%s' "$p" | grep -q '^DONE'; then done_seen=1; break; fi
    [ "$DRY" = 1 ] && break
    if [ "$FOLLOW" = 0 ] && [ -n "$COLLECT" ]; then  # one look: the results so far, and come back later
      fetch_results && echo "VM $i: still running; the results so far ($(stat -c %s "$SH/results.tgz") bytes) are merged below; --collect $RUN_ID again later"
      echo running > "$SH/state"; return 0
    fi
    sleep 60
  done
  # -------------------------------------------------------------- this VM's results
  local booted=0
  if [ "$DRY" = 0 ] && [ "$done_seen" = 0 ] && [ "$s" = TERMINATED ] && [ -z "$BUCKET" ] && [ ! -f "$SH/results.final" ]; then
    # once per VM and run: a results-only boot that finds nothing is not repeated at every --collect
    [ -f "$SH/collect-boot" ] && { echo "VM $i: a results-only boot found nothing earlier; its disk has no results" >&2
                                    echo "noresults" > "$SH/state"; door_retire; return 5; }
    touch "$SH/collect-boot"
    collect_start || { echo stopped > "$SH/state"; return 5; }
    booted=1
  fi
  if fetch_results; then
    touch "$SH/results.final"; echo "done" > "$SH/state"
    door POST collected >/dev/null 2>&1 || true   # the VM powers off now
    door_retire  # the key and its secret version are kept until the results are here (--collect)
  elif [ "$done_seen" = 1 ] || [ "$booted" = 1 ]; then  # done, or started for this, and nothing to hand over
    door POST collected >/dev/null 2>&1 || true   # so it powers off now, not after its grace
    door_retire
    echo "VM $i: no results.tgz on its disk (see its serial console); it powers off now" >&2; echo "noresults" > "$SH/state"
  else
    echo "results not reachable: $VM is $s; --collect $RUN_ID later" >&2; echo stopped > "$SH/state"
  fi
}

if [ -n "$SHARD" ]; then  # a child of the driver below (or a restart of one VM by hand)
  [ -f "$PLAN" ] || { echo "no plan $PLAN (TB_RUN_ID=<run id> to restart a VM of a run)" >&2; exit 2; }
  VMS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan"]["vms"])' "$PLAN")"
  # the plan's hospital size: a child never falls back to the default (the VM ran 50,000 whatever --patients said)
  PATIENTS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["patients"])' "$PLAN")"
  SRC_SHA="$(cat "$OUT/src.tgz.sha256" 2>/dev/null || true)"
  shard_run "$SHARD"
  exit $?
fi

# ================================================================== the driver: plan, VMs, children, merge
if [ -n "$COLLECT" ] && [ -f "$PLAN" ]; then
  VMS="$("$PY" -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p["plan"]["vms"])' "$PLAN")"
  PARTS="$("$PY" -c 'import json,sys; print(",".join(json.load(open(sys.argv[1]))["parts"]))' "$PLAN")"
  PATIENTS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["patients"])' "$PLAN")"
  read -r -a ONLY_TAGS <<< "$("$PY" -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1])).get("only") or []))' "$PLAN")"
elif [ -n "$COLLECT" ]; then
  echo "no plan $PLAN: nothing to collect for run $COLLECT" >&2; exit 2
else
  [ "$(echo "$ZONES" | tr ',' '\n' | grep -c .)" -ge "$VMS" ] || { echo "--zones: $VMS zones needed, got '$ZONES'" >&2; exit 2; }
  cr --estimate --json --patients "$PATIENTS" --vms "$VMS" --parts "$PARTS" "${ONLY_ARGS[@]}" \
    ${TB_ESTIMATE_FROM:+--estimate-from "$TB_ESTIMATE_FROM"} > "$PLAN.est"
  "$PY" - "$PLAN.est" "$PLAN" "$VM" "$ZONES" <<'PY'
import json, sys
e = json.load(open(sys.argv[1]))
zones = sys.argv[4].split(",")
for s in e["plan"]["shards"]:
    i = s["shard"]
    s["vm"] = sys.argv[3] if i == 1 else f"{sys.argv[3]}-{i}"
    s["zone"] = zones[i - 1]
json.dump(e, open(sys.argv[2], "w"), indent=1)
PY
  rm -f "$PLAN.est"
fi
if [ -f "$PLAN" ]; then
  "$PY" - "$PLAN" <<'PY'
import json, sys
e = json.load(open(sys.argv[1])); p = e["plan"]
print(f"plan: {e['patients']:,} patients, parts {','.join(e['parts'])}{', only ' + ' '.join(e['only']) if e.get('only') else ''}, "
      f"{p['vms']} VM(s), US${e['price_per_hour']}/h each")
print(f"{'VM':<3} {'name':<15} {'zone':<19} {'hours':>6} {'US$':>7} {'cap h':>6} {'cap US$':>8}  parts")
for s in p["shards"]:
    print(f"{s['shard']:<3} {s['vm']:<15} {s['zone']:<19} {s['hours']:>6.2f} {s['usd']:>7.2f} {s['cap_hours']:>6} "
          f"{s['cap_usd']:>8.2f}  {' '.join(s['tags'])}")
print(f"total {p['hours']:.2f} VM-hours, US${p['usd']:.2f}; wall about {p['wall_hours']:.2f} h; at most "
      f"US${p['cap_usd']:.2f} if every VM ran to its cap")
PY
fi

if [ "$STOP" = 1 ]; then
  if [ -f "$PLAN" ]; then
    for i in $(seq 1 "$VMS"); do VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; stop_vm; done
  else
    names=(); for i in $(seq 1 "$VMS"); do names+=("$(vm_name "$i")"); done
    for i in $(seq 1 "$VMS"); do VM="${names[$((i - 1))]}"; ZONE="$(vm_zone "$i")"; stop_vm; done
  fi
  exit 0
fi

if [ "$PROVISION" = 1 ] || [ "$TEARDOWN" = 1 ]; then  # the clones 2..N of VM 1 (owner's OK: disks cost while kept)
  SRC_ZONE="$(vm_zone 1)"
  if [ "$TEARDOWN" = 1 ]; then
    for i in $(seq 2 "$VMS"); do gc compute instances delete "$(vm_name "$i")" --zone "$(vm_zone "$i")" --quiet || true; done
    gc compute machine-images delete "$IMAGE" --quiet || true
    exit 0
  fi
  gc_probe
  quota_check "$VMS" || exit 4   # before the machine image: nothing is made for VMs that cannot run (H-05, L-04)
  [ "$DRY" = 1 ] || [ "$(status)" = TERMINATED ] || { echo "$VM must be TERMINATED for its machine image" >&2; exit 3; }
  if [ "$DRY" = 1 ] || ! gc compute machine-images describe "$IMAGE" --format='value(name)' >/dev/null 2>&1; then
    gc compute machine-images create "$IMAGE" --source-instance="$VM" --source-instance-zone="$SRC_ZONE"
  fi
  printf '#!/bin/sh\n# a new clone: power off at once (the run puts its own startup script here)\nsystemctl poweroff\n' > "$OUT/poweroff.sh"
  for i in $(seq 2 "$VMS"); do
    n="$(vm_name "$i")"; z="$(vm_zone "$i")"
    if [ "$DRY" = 0 ] && gc compute instances describe "$n" --zone "$z" --format='value(status)' >/dev/null 2>&1; then
      echo "$n exists in $z"; continue; fi
    # create starts the VM: it powers itself off at boot, and a 30-minute cap stops it if that fails
    gc compute instances create "$n" --zone "$z" --source-machine-image="$IMAGE" --machine-type=g4-standard-48 \
      --provisioning-model=SPOT --instance-termination-action=STOP --max-run-duration=30m \
      --metadata-from-file startup-script="$OUT/poweroff.sh"
  done
  echo "clones made; check each is TERMINATED: gcloud compute instances list --filter='name~^$VM'"
  exit 0
fi

SRC_SHA=""
if [ -z "$COLLECT" ]; then
  if [ "$DRY" = 1 ]; then
    echo "# zones are candidates for the RTX PRO 6000 (G4); before the run, the owner checks (read-only):"
    echo "#   gcloud compute accelerator-types list --filter='name~rtx' --format='value(zone,name)'"
    for z in $(echo "$ZONES" | cut -d, -f1-"$VMS" | tr ',' ' '); do
      echo "#   gcloud compute regions describe ${z%-*} --flatten=quotas --filter='quotas.metric~RTX|CPUS' --format='table(quotas.metric,quotas.limit,quotas.usage)'"
    done | awk '!seen[$0]++'
    echo "#   gcloud compute project-info describe --flatten=quotas --filter='quotas.metric~GPUS_ALL_REGIONS' --format='table(quotas.metric,quotas.limit,quotas.usage)'"
    echo "+ git archive --format=tar.gz --add-file=TB_HEAD.json -o $OUT/src.tgz HEAD trialbox"
  else
    # the commit the VM runs, inside the archive (the VM has no repository; the report names this HEAD: review M-02)
    "$PY" -c 'import json,subprocess as s,sys; g=lambda *a: s.check_output(["git",*a],text=True).strip()
json.dump({"head": g("rev-parse","HEAD"), "subject": g("log","-1","--format=%s"), "dirty": False}, open(sys.argv[1],"w"))' \
      "$OUT/TB_HEAD.json"
    git -C "$ROOT/.." archive --format=tar.gz --add-file="$OUT/TB_HEAD.json" -o "$OUT/src.tgz" HEAD trialbox
    SRC_SHA="$(sha256sum "$OUT/src.tgz" | cut -d' ' -f1)"; echo "$SRC_SHA" > "$OUT/src.tgz.sha256"
  fi
  [ -n "$(git status --porcelain)" ] && echo "note: local changes are NOT in the run; it runs HEAD $(git rev-parse --short HEAD)" >&2
  gc_probe
  quota_check "$VMS" || exit 4
  for i in $(seq 1 "$VMS"); do  # every VM is there and stopped before any of them starts
    VM_I="$(plan_get "$i" vm)"; Z_I="$(plan_get "$i" zone)"
    if [ "$DRY" = 0 ]; then
      s="$(gc compute instances describe "$VM_I" --zone "$Z_I" --format='value(status)' 2>/dev/null || echo missing)"
      [ "$s" = TERMINATED ] || { echo "$VM_I ($Z_I) is $s: stop it, or make it with --provision" >&2; exit 3; }
    fi
  done
  if [ -n "$BUCKET" ]; then for i in $(seq 1 "$VMS"); do gc storage cp "$OUT/src.tgz" "$BUCKET/runs/$RUN_ID-s$i/src.tgz"; done; fi
fi

# -------------------------------------------------------------- one child per VM; each stops its own VM
CHILD=("$0"); [ "$DRY" = 1 ] && CHILD+=(--dry-run); [ "$WAIT" = 1 ] || CHILD+=(--no-wait); [ "$FOLLOW" = 1 ] && CHILD+=(--follow)
[ -n "$HOURS" ] && CHILD+=(--hours "$HOURS"); [ -n "$COLLECT" ] && CHILD+=(--collect "$COLLECT")
export TB_RUN_ID="$RUN_ID" TB_COMPLETE_DIR="$OUT"
if [ "$VMS" = 1 ]; then
  "${CHILD[@]}" --shard 1 "$VM" "$ZONE" || echo "VM 1 ended with an error" >&2
else
  pids=()
  for i in $(seq 1 "$VMS"); do
    ( "${CHILD[@]}" --shard "$i" "$VM" "$ZONE" 2>&1 | sed -u "s/^/[vm$i] /" ) &
    pids+=($!)
    [ "$DRY" = 1 ] && wait "${pids[-1]}"  # a dry run prints the VMs in order
  done
  for p in "${pids[@]}"; do wait "$p" || true; done
fi
[ "$WAIT" = 1 ] || [ -n "$COLLECT" ] || exit 0

# -------------------------------------------------------------- merge: parts and screenshots of every VM, one report
# the stub parts belong to the complete run (g1), not to a bounded --only run
ONLY="$("$PY" -c 'import json,sys; e=json.load(open(sys.argv[1])); t=[x for s in e["plan"]["shards"] for x in s["tags"]]
g1 = "g1" in e["parts"] and not e.get("only"); print(" ".join(t + (["walk", "backup", "update", "scale"] if g1 else [])))' "$PLAN" 2>/dev/null || echo "")"
G1=0; case ",$PARTS," in *,g1,*) [ "${#ONLY_TAGS[@]}" = 0 ] && G1=1 ;; esac
STUB=(--patients "$PATIENTS" --ocr tesseract --run-id "$RUN_ID")   # as on the VM (review M-02)
if [ "$DRY" = 1 ]; then
  for i in $(seq 1 "$VMS"); do echo "+ tar -xzf $OUT/shard-$i/results.tgz -C $OUT/shard-$i; parts/ and report/shots/ into $OUT"; done
  [ "$G1" = 1 ] && echo "+ $PY -m tools.complete_run --dir $OUT --resume --only walk backup update scale ${STUB[*]}"
  echo "+ $PY -m tools.complete_run --dir $OUT --report-only --model pair ${STUB[*]} --report-parts $ONLY"
  exit 0
fi
missing=""; running=""
mkdir -p "$OUT/parts" "$OUT/report/shots"
for i in $(seq 1 "$VMS"); do
  SH="$OUT/shard-$i"
  [ "$(cat "$SH/state" 2>/dev/null)" = running ] && running="$running $i"
  if [ -s "$SH/results.tgz" ] && rm -rf "$SH/parts" "$SH/report" && tar -xzf "$SH/results.tgz" -C "$SH"; then
    cp -p "$SH"/parts/*.json "$OUT/parts/" 2>/dev/null || true
    cp -pr "$SH"/report/shots/. "$OUT/report/shots/" 2>/dev/null || true
    for b in bench-embed bench-profile; do [ -d "$SH/$b" ] && cp -pr "$SH/$b" "$OUT/"; done
  else missing="$missing $i"; fi
done
[ -f "$OUT/shard-1/serving_config.rtxpro6000.live.json" ] && cp "$OUT/shard-1/serving_config.rtxpro6000.live.json" "$OUT/"
[ -z "$missing" ] || echo "no results from VM(s)$missing: their parts are failed rows; --collect $RUN_ID later" >&2
if [ -n "$running" ]; then
  echo "VM(s)$running still running: the report below is of the parts done so far; --collect $RUN_ID again later"
elif [ "$G1" = 1 ]; then
  env TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" --resume \
    --only walk backup update scale "${STUB[@]}" || true
fi
LIVE=(); [ -f "$OUT/serving_config.rtxpro6000.live.json" ] && LIVE=(--live-record "$OUT/serving_config.rtxpro6000.live.json")
# the parts of a VM that still runs (and the stub parts, which wait for every VM) are "pending" in the report; any
# other part without a result is "not run (VM stopped)": neither counts as a failed check (G1 bug A5)
PENDING=()
if [ -n "$running" ]; then
  for i in $running; do read -r -a t <<< "$(plan_get "$i" tags)"; PENDING+=("${t[@]}"); done
  [ "$G1" = 1 ] && PENDING+=(walk backup update scale)
fi
[ "${#PENDING[@]}" = 0 ] || PENDING=(--pending-parts "${PENDING[@]}")
# shellcheck disable=SC2086  # ONLY is a list of tags
env TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" --report-only --model pair \
  "${STUB[@]}" "${LIVE[@]}" ${TB_PLANNED_FROM:+--planned-from "$TB_PLANNED_FROM"} "${PENDING[@]}" --report-parts $ONLY || true
echo "report: $OUT/report/report.md"
for i in $(seq 1 "$VMS"); do VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; echo "VM $VM status: $(status)"; done