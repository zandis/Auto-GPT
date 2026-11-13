#!/usr/bin/env bash
# TrialBox complete-platform run on the RTX PRO 6000 (TB-PLAN-04 step 9, D-139, D-141, D-148, D-150). Owner's OK first:
# it starts paid VMs (tb-gpu-sim and its clones, g4-standard-48 spot, about US$2.74 an hour each).
# Gate before any paid launch: `make rehearse` passes on the commit to launch (tests/rehearsal, RUNBOOK §11).
#
#   export CLOUDSDK_CONFIG=<a private folder>              # never the default one
#   export TB_SA_KEY_FILE=<the service account key file>   # every command activates from it (its path, to gcloud)
#   gcloud config set project trialbox-demo                # once, in that config
#   deploy/gcp/complete-run.sh --estimate [--patients 50000] [--vms N] [--parts g1,embed,profile] [--only TAG,TAG]
#                              [--llm-concurrency N[,N...]]
#   deploy/gcp/complete-run.sh --dry-run [--vms N] [--zones z1,z2] [--parts ...] [--only TAG,TAG] [VM] [ZONE]
#   deploy/gcp/complete-run.sh --provision --vms N --zones z1,z2,...   # once: the clones tb-gpu-sim-2..N (they
#                                                                      # boot, power off at once, keep their disks)
#   deploy/gcp/complete-run.sh [--patients 50000] [--vms N] [--zones ...] [--parts ...] [--only TAG,TAG] [--hours H]
#                              [--llm-concurrency N[,N...]] [--no-wait | --detach]
#   deploy/gcp/complete-run.sh --collect <run id> [--follow]   # later, as often as wanted: see below
#   deploy/gcp/complete-run.sh --stop [--collect <run id> | --vms N --zones ...] [VM] [ZONE]   # stop by hand
#   deploy/gcp/complete-run.sh --teardown --vms N --zones ...   # delete the clones 2..N and their machine image
#   deploy/gcp/complete-run.sh --preflight [--vms N --zones ...]   # free: read-only gcloud calls, no VM starts
#
# Pre-flight (2026-11-12 run, A6 and A7: it failed in turn on the firewall, the Secret Manager API, the missing secret,
# the deployer's missing roles/secretmanager.viewer, and a door no proxy can carry). --preflight reads the project with
# read-only calls only and prints EVERY problem at once, each with the exact command that fixes it (the firewall in
# door mode, the Secret Manager API, the secret tb-gpu-door, the deployer's and the VMs' access, each VM and its
# service account, the bucket with TB_BUCKET); a launch runs the same checks before any VM starts and refuses on any
# problem. Without TB_BUCKET and with HTTPS_PROXY (or https_proxy) set a launch refuses at once: the door is TLS
# straight to the VM, and a machine whose HTTPS goes through a (TLS-inspecting) proxy cannot reach it, so the VM would
# wait for its code and idle out. Set TB_BUCKET, or TB_DOOR_DIRECT=1 when this machine does reach the VM directly.
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
# `chat-template` is the review's test G-1 (tools/chat_template_check.py), in a run only when --only names it.
#
# --llm-concurrency N[,N...]: the model calls SCREEN keeps in flight (TB_SCREEN_LLM_CONCURRENCY) in every part of the
# run. Not given: the serving record's max_num_seqs (deploy/measured), as an installed box runs; the plan prints it.
# A list (1,4,16,48) is the review's test G-3: the hospital part runs once per value, as its own part
# hospital-<lang>@c<N>, on one prepared hospital, so one VM run makes the whole curve. Every model part records its
# calls and tokens per second, p50 / p95 call time, the servers' /metrics before and after and the card every 10 s
# (parts/<part>/gpu.csv). The estimate's screening time is G1's 0.78 calls/s at N = 1, divided by min(N, 2)
# (TB_ESTIMATE_LLM_SPEEDUP): an upper bound for N > 1 until G-3 has measured it.
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
#      change it), termination action STOP. Compute Engine stops the VM at the cap whatever else happens. The estimate
#      is of the parts the shard has left (a restart after a pre-emption), and a VM with a hospital part runs on
#      demand, the others spot (D-468).
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
# (secret tb-gpu-door, one version per VM and run, destroyed once the results are here: a --collect that has every
# part of the plan, whether the VM still runs or the results came through the bucket, and --stop; A8), never as
# metadata; a tb-key an older driver left in the metadata is removed. Each collect and stop says "no enabled version"
# or names the versions that remain (and the report says it too: door-secret.txt). Before the start the driver refuses
# a VM without a service account and a firewall that opens tcp:80 to it or does not open tcp:443 (read-only,
# door_firewall_check). A door that does not answer in 30 minutes: the driver stops the VM (it does not wait for the
# VM's own watchdog), and the VM itself powers off at once with TB-NO-CODE when no code came (A6).
# Optional TB_BUCKET=gs://<bucket>: code and results go through the bucket (the VM's service account needs storage
# access); without it they go through the door.
# Hardening (independent review, 2026-11-12):
#   * the poll's POST /tb/heartbeat touches the VM's driver-alive, never the run's heartbeat: a driver that follows a
#     stuck part (wait mode, --follow, --detach, frequent --collect) cannot keep it alive to its cap;
#   * the poll ends only on TERMINATED or STOPPED; a describe that fails is "unknown": the poll goes on (bounded by
#     the VM's cap), a one-look --collect says "still running" and nothing is marked final or retired;
#   * a results-only start is marked (collect-boot) only once its door answered; a refused start (a stockout) is
#     said and tried again at the next --collect;
#   * a launch reads each VM's tb-run-id and refuses while that run's results are not here (state done/noresults);
#     --discard-previous launches anyway (the VM deletes the earlier run's directory and results.tgz);
#   * from the start until the upload is accepted, any exit (an error, a signal) stops the VM and retires its door;
#   * with TB_BUCKET a results.tgz the VM could not upload is fetched by a results-only start through the door, and
#     the collect names what is missing;
#   * one driver per run folder (flock on driver.lock; a second one says who holds it and exits), one launch per VM
#     (a lock per VM under .cache/complete-run/locks, TB_LOCK_DIR);
#   * a --shard restart checks the quota of its zone; at the end of a VM's collect the VM goes back to spot and the
#     usual startup script (as --stop does), once it has powered off;
#   * prepare / install (run on every VM with a hospital part) merge as failed if any VM's copy failed.
set -euo pipefail
ARGS=("$@")
DRY=0; STOP=0; ESTIMATE=0; WAIT=1; PATIENTS=50000; HOURS=""; COLLECT=""; VMS=1; PARTS=g1; ZONES="${TB_ZONES:-}"
SHARD=""; PROVISION=0; TEARDOWN=0; FOLLOW=0; DETACH=0; ONLY_TAGS=(); LLMC=""; PREFLIGHT=0; DISCARD_PREV=0
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
    --llm-concurrency) LLMC="$2"; shift 2 ;;
    --shard) SHARD="$2"; shift 2 ;;
    --provision) PROVISION=1; shift ;;
    --teardown) TEARDOWN=1; shift ;;
    --preflight) PREFLIGHT=1; shift ;;
    --discard-previous) DISCARD_PREV=1; shift ;;
    -h|--help) sed -n 2,105p "$0"; exit 0 ;;
    *) break ;;
  esac
done
case "$VMS" in ''|*[!0-9]*|0) echo "--vms: a whole number from 1" >&2; exit 2 ;; esac
# the cap is whole hours (max-run-duration ${H}h, tb-max-minutes H*60-5): refuse 2.5 before anything is made
[ -z "$HOURS" ] || case "$HOURS" in *[!0-9]*|0) echo "--hours: a whole number of hours from 1 (got '$HOURS')" >&2; exit 2 ;; esac
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
[ -z "$LLMC" ] || ONLY_ARGS+=(--llm-concurrency "$LLMC")   # the estimate and the plan: the calls in flight (G-3)
plan_lc() {  # the plan's calls in flight, space separated (a metadata value holds no comma): "16" or "1 4 16 48"
  "$PY" -c 'import json,sys; print(" ".join(str(n) for n in json.load(open(sys.argv[1])).get("llm_concurrency") or []))' "$PLAN"
}

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
vm_name() { if [ "$1" = 1 ]; then echo "$VM"; else echo "$VM-$1"; fi; }
vm_zone() { echo "$ZONES" | cut -d, -f"$1"; }

door_reach_check() {  # A6: a door no proxy can carry; before any VM starts (a dry run says what a launch would do)
  local why
  why="$(cr --door-reach-check 2>&1 >/dev/null)" && return 0
  if [ "$DRY" = 1 ]; then echo "# a launch would refuse here: $why"; return 0; fi
  echo "$why" >&2
  return 2
}

preflight() {  # A7: $1 a folder, then "name zone" per VM; read-only gcloud calls only; every problem at once
  local pf=$1 n z; shift
  if [ "$DRY" = 1 ]; then
    echo "# the pre-flight (read-only; a launch refuses on any problem, each printed with its fix):"
    echo "+ gcloud config get-value project; gcloud config get-value account   # local config"
    echo "+ gcloud secrets describe $DOOR_SECRET --format=json   # the API on, the secret there, the deployer may read it"
    echo "+ gcloud secrets get-iam-policy $DOOR_SECRET --format=json   # who adds versions, who reads them"
    for x in "$@"; do echo "+ gcloud compute instances describe ${x% *} --zone ${x#* } --format=json   # its service account"
      echo "+ gcloud compute instances get-serial-port-output ${x% *} --zone ${x#* }   # TB-IMAGES: vLLM and nginx on its disk"; done
    if [ -n "$BUCKET" ]; then
      echo "+ gcloud storage ls $BUCKET; gcloud storage buckets get-iam-policy $BUCKET --format=json   # the bucket; objectAdmin for the deployer and each VM's account"
      [ -z "${PF_RUN:-}" ] || echo "+ gcloud storage ls $BUCKET/runs/$PF_RUN-s*   # nothing there yet for the new run id"
    else
      echo "+ gcloud compute firewall-rules list --format=json   # per VM: tcp:443 open, tcp:80 closed (door_firewall_check)"
    fi
    return 0
  fi
  rm -rf "$pf"; mkdir -p "$pf"
  timeout -k 5 "$GC_TIMEOUT_S" gcloud config get-value project > "$pf/project.txt" 2>/dev/null || true
  timeout -k 5 "$GC_TIMEOUT_S" gcloud config get-value account > "$pf/account.txt" 2>/dev/null || true
  if [ -n "$BUCKET" ]; then echo bucket; else echo door; fi > "$pf/mode.txt"
  printf '%s\n' "$@" > "$pf/vms.txt"
  gc secrets describe "$DOOR_SECRET" --format=json > "$pf/secret.json" 2> "$pf/secret.err" && rm -f "$pf/secret.err"
  if [ ! -f "$pf/secret.err" ]; then
    gc secrets get-iam-policy "$DOOR_SECRET" --format=json > "$pf/secret-iam.json" 2> "$pf/secret-iam.err" \
      && rm -f "$pf/secret-iam.err"
  fi
  [ -n "$BUCKET" ] || { gc compute firewall-rules list --format=json > "$pf/firewall.json" 2> "$pf/firewall.err" \
                          && rm -f "$pf/firewall.err"; }
  for x in "$@"; do
    n="${x% *}"; z="${x#* }"
    gc compute instances describe "$n" --zone "$z" --format=json > "$pf/vm-$n.json" 2> "$pf/vm-$n.err" \
      && rm -f "$pf/vm-$n.err"
    # the images its last boot found (TB-IMAGES): a stopped VM cannot be asked, its serial console can
    gc compute instances get-serial-port-output "$n" --zone "$z" > "$pf/console-$n.txt" 2>/dev/null \
      || rm -f "$pf/console-$n.txt"
    if [ -z "$BUCKET" ] && [ -s "$pf/vm-$n.json" ] && [ -s "$pf/firewall.json" ]; then
      door_firewall_check "$PY" "$pf/vm-$n.json" "$pf/firewall.json" 2> "$pf/firewall-$n.txt" || true
    fi
  done
  if [ -n "$BUCKET" ]; then
    echo "$BUCKET" > "$pf/bucket.txt"
    gc storage ls "$BUCKET" > /dev/null 2> "$pf/bucket-ls.err" && rm -f "$pf/bucket-ls.err"
    gc storage buckets get-iam-policy "$BUCKET" --format=json > "$pf/bucket-iam.json" 2> "$pf/bucket-iam.err" \
      && rm -f "$pf/bucket-iam.err"
    if [ -n "${PF_RUN:-}" ]; then  # a launch: nothing may be there yet for its new run id (a stale src or results)
      echo "$PF_RUN" > "$pf/run-id.txt"
      gc storage ls "$BUCKET/runs/$PF_RUN-s*" > "$pf/bucket-stale.txt" 2>/dev/null || true
    fi
  fi
  cr --preflight-check "$pf"
}

if [ "$PREFLIGHT" = 1 ]; then  # A7: free; the VMs 1..N of --vms / --zones (or tb-gpu-sim in asia-east1-a)
  door_reach_check || true   # said, not refused: --preflight only reports
  vms=(); for i in $(seq 1 "$VMS"); do vms+=("$(vm_name "$i") $(vm_zone "$i")"); done
  PFD="$(mktemp -d)"
  rc=0; preflight "$PFD" "${vms[@]}" || rc=$?
  rm -rf "$PFD"
  exit "$rc"
fi

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
# ---------------------------------------------------------------- locks (review: two drivers on one run, or one VM)
LOCKS="${TB_LOCK_DIR:-$ROOT/.cache/complete-run/locks}"
lock_or_say() {  # $1 fd (8 or 7), $2 lock file, $3 what: flock -n, else say who holds it (its .who file) and fail
  local f=$2 what=$3
  if [ "$1" = 8 ]; then exec 8> "$f"; else exec 7> "$f"; fi
  if ! flock -n "$1"; then
    echo "$what: held by another driver ($(cat "$f.who" 2>/dev/null || echo 'who: unknown')); not run" >&2
    return 7
  fi
  printf 'pid %s, since %s, %s\n' "$$" "$(date -u +%FT%TZ)" "$(basename "$0") ${ARGS[*]}" > "$f.who"
}
if [ "$DRY" = 0 ] && [ "$STOP" = 0 ] && [ -z "${TB_DRIVER_LOCK_HELD:-}" ]; then
  # the driver and its shard children share it (TB_DRIVER_LOCK_HELD); a --shard by hand takes it as a driver does
  lock_or_say 8 "$OUT/driver.lock" "run $RUN_ID (folder $OUT)" || exit 7
  export TB_DRIVER_LOCK_HELD=$$
fi
plan_get() {  # shard field: one value of plan.json (vm, zone, cap_hours, hours, usd, tags as one line)
  "$PY" -c 'import json,sys; s=json.load(open(sys.argv[1]))["plan"]["shards"][int(sys.argv[2])-1]; v=s[sys.argv[3]]
print(" ".join(v) if isinstance(v, list) else v)' "$PLAN" "$1" "$2"
}
quota_check() {  # $1 = number of VMs (zones 1..N): read-only quota reads, refuse when N VMs cannot run (review H-05)
  # [$2 zones, $3 the on-demand zones]: one shard's zone (a --shard restart), instead of the plan's first N
  local n=$1 zs q r
  zs="${2:-$(echo "$ZONES" | cut -d, -f1-"$n")}"
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
  # the zones whose VM runs on demand (a hospital part, D-468) draw on the regular quota
  if [ -n "${2:-}" ]; then std="${3:-}"; else
  std="$("$PY" -c 'import json,sys; s=json.load(open(sys.argv[1]))["plan"]["shards"]
print(",".join(x["zone"] for x in s[:int(sys.argv[2])] if x.get("provisioning") == "STANDARD"))' "$PLAN" "$n" 2>/dev/null || true)"
  fi
  cr --quota-check "$q" --quota-zones "$zs" --quota-standard "$std"
}

# ================================================================== one VM (a shard of the plan): the D-141 run
status() { if [ "$DRY" = 1 ]; then echo TERMINATED; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(status)' || echo unknown; fi; }
stop_vm() {
  gc compute instances stop "$VM" --zone "$ZONE" || true
  local s; s="$(status)"
  echo "VM $VM status: $s"
  reset_vm
}
reset_vm() {  # a stopped VM back to how it is kept: spot, the usual startup script, no door metadata
  # back to spot (D-468: a run puts a VM with a hospital part on demand; a VM started by hand later must not pay 3x)
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --preemptible --provisioning-model=SPOT --instance-termination-action=STOP || true
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
  local v rc=0
  gc secrets describe "$DOOR_SECRET" --format='value(name)' >/dev/null \
    || { echo "no secret $DOOR_SECRET: run deploy/gcp/setup-gcp.sh once (it makes the secret and lets the VM read it)" >&2; return 1; }
  # A8: `gc` retries a call that timed out, so one add can leave two enabled versions, only one of them named back.
  # The enabled versions before and after the add (one shard at a time: the lock) are what this VM made: all of them
  # go in door-versions and are destroyed with it; door-version is the one the VM reads.
  exec 9> "$OUT/door.lock"; flock 9
  door_enabled > "$SH/door-before" || : > "$SH/door-before"
  v="$(gc secrets versions add "$DOOR_SECRET" --data-file="$SH/door-secret.json" --format='value(name)')" || rc=$?
  door_enabled | comm -13 "$SH/door-before" - >> "$SH/door-versions" || true
  flock -u 9; exec 9>&-
  rm -f "$SH/door-secret.json" "$SH/door.key" "$SH/door-before"   # the VM reads its copy from Secret Manager
  v="${v##*/}"
  [ "$rc" = 0 ] || { door_retire; return 1; }
  case "$v" in ''|*[!0-9]*) echo "secret $DOOR_SECRET: no version number from gcloud ('$v')" >&2; door_retire; return 1 ;; esac
  echo "$v" > "$SH/door-version"
  echo "$v" >> "$SH/door-versions"
}
door_enabled() {  # the door secret's enabled version numbers, sorted as text (for comm)
  gc secrets versions list "$DOOR_SECRET" --filter=state=enabled --format='value(name)' | sed 's#.*/##' \
    | { grep -E '^[0-9]+$' || true; } | sort
}
door_retire() {  # the results are here (or there are none, or the start gave up): destroy every door version this VM
  # made (door-versions: the one it reads and any a retried add left); the key file goes
  if [ "$DRY" = 1 ]; then echo "+ gcloud secrets versions destroy <version> --secret $DOOR_SECRET --quiet   # once collected"; return 0; fi
  local v
  for v in $(for f in "$SH/door-version" "$SH/door-versions"; do [ -f "$f" ] && { cat "$f"; echo; }; done | sort -u); do
    case "$v" in ''|0|*[!0-9]*) continue ;; esac
    gc secrets versions destroy "$v" --secret "$DOOR_SECRET" --quiet >/dev/null \
      || echo "secret $DOOR_SECRET version $v: not destroyed; destroy it by hand" >&2
  done
  rm -f "$KEYF" "$SH/door-version" "$SH/door-versions" "$SH/door.key" "$SH/door-secret.json"
}
door_versions_left() {  # A8: after a collect or stop, the door secret's enabled versions: none, or which remain
  local out vs mine="" msg f
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud secrets versions list $DOOR_SECRET --filter=state=enabled --format=value(name)   # 'no enabled version', or which remain"
    return 0
  fi
  for f in "$OUT"/shard-*/door-version "$OUT"/shard-*/door-versions; do [ -f "$f" ] && mine="$mine $(tr "\n" " " < "$f")"; done
  mine="$(echo "$mine" | tr " " "\n" | grep -E "^[0-9]+$" | sort -un | tr "\n" " " | sed "s/ $//" || true)"; mine="${mine:+ $mine}"
  if out="$(gc secrets versions list "$DOOR_SECRET" --filter=state=enabled --format='value(name)' 2>/dev/null)"; then
    vs="$(printf '%s\n' "$out" | sed 's#.*/##' | grep -E '^[0-9]+$' | sort -n | tr '\n' ' ' | sed 's/ $//' || true)"
    if [ -z "$vs" ]; then msg="door secret $DOOR_SECRET: no enabled version"
    else msg="door secret $DOOR_SECRET: enabled version(s) $vs remain (this run's not destroyed:${mine:- none}); destroy each with: gcloud secrets versions destroy <version> --secret $DOOR_SECRET --quiet"; fi
  else
    msg="door secret $DOOR_SECRET: its versions are not readable here (the deployer needs roles/secretmanager.viewer, setup-gcp.sh); this run's not destroyed:${mine:- none}"
  fi
  echo "$msg"
  [ -d "$OUT" ] && printf '%s\n' "$msg" > "$OUT/door-secret.txt"
  return 0
}
door_retire_all() {  # A8: every part of the plan is in: each VM's door version goes, a VM still running powers off
  local i
  for i in $(seq 1 "$VMS"); do
    SH="$OUT/shard-$i"; KEYF="$SH/tb-key"; VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"
    [ -f "$SH/door-version" ] || [ -f "$SH/door-versions" ] || [ -f "$KEYF" ] || continue
    if [ "$DRY" = 0 ] && [ -f "$KEYF" ] && [ "$(status)" = RUNNING ]; then
      IP="$(ip)"; door POST collected --max-time 20 >/dev/null 2>&1 || true   # it powers off now, not after its grace
    fi
    door_retire
    echo "VM $i: every part of the run is in: its door version is destroyed"
    [ "$DRY" = 1 ] || { touch "$SH/results.final"; echo "done" > "$SH/state"; }
  done
}
fetch_results() {  # this VM's results.tgz as it is now, replacing the earlier one only when the download is whole
  # TB_BUCKET: the bucket first, then the door (a VM whose upload failed keeps the archive on its disk); what is
  # missing goes to stderr and $SH/missing.txt
  local obj why=""
  rm -f "$SH/results.tgz.new" "$SH/missing.txt"
  if [ -n "$BUCKET" ]; then
    obj="$BUCKET/runs/$RUN_ID-s$i/results.tgz"
    gc storage cp "$obj" "$SH/results.tgz.new" 2>/dev/null \
      || why="$obj: not in the bucket (the VM's upload failed, TB-UPLOAD-FAILED in its log, or has not happened yet)"
    [ "$DRY" = 1 ] && return 0
  fi
  if [ ! -s "$SH/results.tgz.new" ]; then
    if [ "$DRY" = 1 ] || { [ -s "$KEYF" ] && [ -n "${IP:-}" ]; }; then
      door GET results.tgz -o "$SH/results.tgz.new" 2>/dev/null \
        || why="${why:+$why; }the door of $VM: no results.tgz (the VM is not up, or its disk has none)"
    else why="${why:+$why; }the door of $VM: not open (no key here, or the VM is not up)"; fi
  fi
  [ "$DRY" = 1 ] && return 0
  if [ -s "$SH/results.tgz.new" ] && ! tar -tzf "$SH/results.tgz.new" >/dev/null 2>&1; then
    why="${why:+$why; }results.tgz came incomplete"; rm -f "$SH/results.tgz.new"
  fi
  if [ ! -s "$SH/results.tgz.new" ]; then
    echo "VM $i: results.tgz not fetched: ${why:-?}" >&2; printf '%s\n' "${why:-?}" > "$SH/missing.txt"; return 1
  fi
  mv -f "$SH/results.tgz.new" "$SH/results.tgz"
}
settle_and_reset() {  # after "collected" the VM powers off (its watchdog looks every minute): then back to spot and
  # the usual startup script, as --stop does (TB_SETTLE_S, 240 s: two watchdog rounds and the power-off itself)
  local end=$((SECONDS + ${TB_SETTLE_S:-240})) st
  if [ "$DRY" = 1 ]; then reset_vm; return 0; fi
  while :; do
    st="$(status)"
    case "$st" in TERMINATED|STOPPED) reset_vm; echo "VM $i: powered off; back to spot and the usual startup script"; return 0 ;; esac
    [ "$SECONDS" -lt "$end" ] || { echo "VM $i: still $st after ${TB_SETTLE_S:-240} s; it powers itself off; --stop resets it to spot"; return 0; }
    sleep 15
  done
}
wait_door() {  # $1 tries of 20 s: a wall-clock bound ($1 x 20 s), whatever each call takes (each one at most 30 s)
  local end=$((SECONDS + ${1:-90} * 20))
  while :; do
    door POST heartbeat --max-time 30 >/dev/null 2>&1 && return 0
    [ "$DRY" = 1 ] && return 0
    [ "$SECONDS" -lt "$end" ] || return 1
    sleep 20
  done
}
collect_start() {  # a stopped VM whose results are on its disk: start it in the results-only mode (review H-04, L-03)
  echo "$VM is TERMINATED and its results are on its disk: a results-only start (no models, no run, cloud cap 20 min)"
  if [ ! -f "$KEYF" ] || [ ! -f "$SH/door-version" ]; then  # --stop destroyed its door (A8): a new one for this boot
    if ! door_make "$SH" || ! door_secret_add; then echo "$VM: no door for a results-only start" >&2; return 1; fi
  fi
  # each call checked: a results-only start that did not happen is said, nothing is marked, the next --collect tries
  # again (a refused start, e.g. a stockout, is no proof that the disk has no results)
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration=20m --instance-termination-action=STOP \
    || { echo "$VM: its 20-minute cap could not be set: no results-only start; --collect $RUN_ID again later" >&2
         door_retire; return 1; }
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
    "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-door-cert=$SH/door.crt" \
    --metadata "tb-door-secret=$DOOR_SECRET,tb-door-version=$(cat "$SH/door-version"),tb-collect-only=1,tb-max-minutes=15,tb-done-grace=10" \
    || { echo "$VM: its metadata could not be set: no results-only start; --collect $RUN_ID again later" >&2
         door_retire; return 1; }
  if ! gc compute instances start "$VM" --zone "$ZONE"; then
    echo "$VM: the results-only start was refused (a stockout or quota?): its disk is untouched; --collect $RUN_ID again later" >&2
    [ "$(status)" = TERMINATED ] || stop_vm
    door_retire; return 1
  fi
  IP="$(ip)" || { echo "$VM: no address after the start: stopping it" >&2; stop_vm; door_retire; return 1; }
  wait_door 30 || { echo "$VM: the door did not answer in 10 minutes: stopping it, its door destroyed" >&2
                   stop_vm; door_retire; return 1; }
  touch "$SH/collect-boot"   # only now: a results-only boot did happen (one that finds nothing is not repeated)
}

give_up_started() {  # $1 why: after the start, before the code was accepted: stop the VM, retire its door
  trap - EXIT INT TERM HUP
  echo "$VM: $1: stopping it, its door destroyed" >&2
  stop_vm || true; door_retire || true
  [ "$DRY" = 1 ] || echo noresults > "$SH/state"
}
prev_run_check() {  # $1 vm $2 zone: the run its disk holds (metadata tb-run-id) is deleted by a launch of another run
  # id (the VM keeps one run directory); refuse while that run's results are not here, unless --discard-previous
  local j prev base n st runs="${TB_RUNS_DIR:-$(dirname "$OUT")}"
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute instances describe $1 --zone $2 --format=json   # its tb-run-id: refused while that run's results are not here (--discard-previous)"
    return 0
  fi
  j="$(gc compute instances describe "$1" --zone "$2" --format=json)" || { echo "$1: its metadata is not readable" >&2; return 3; }
  prev="$(printf '%s' "$j" | "$PY" -c 'import json,sys
items = (json.load(sys.stdin).get("metadata") or {}).get("items") or []
print(next((x.get("value") or "" for x in items if x.get("key") == "tb-run-id"), ""))')"
  [ -n "$prev" ] || return 0
  base="${prev%-s*}"; n="${prev##*-s}"
  [ "$base" = "$RUN_ID" ] && return 0   # this run itself (a restart of a shard)
  st="$(cat "$runs/$base/shard-$n/state" 2>/dev/null || echo "no folder $runs/$base here")"
  case "$st" in done|noresults) return 0 ;; esac
  if [ "$DISCARD_PREV" = 1 ]; then
    echo "$1: run $prev on its disk (state: $st) is discarded (--discard-previous): the VM deletes its results" >&2
    return 0
  fi
  echo "$1 ($2) holds run $prev, whose results are not collected here (state: $st); a launch would delete them." \
       "Collect them first: $0 --collect $base; or launch with --discard-previous" >&2
  return 3
}
shard_run() {  # $1 = shard number; VM, ZONE and parts come from plan.json; the cap from what is left (shard_now)
  # SH (like VM, ZONE, KEYF) is global: the EXIT trap runs after the function's locals are gone
  local i=$1 TAGS EST_H EST_USD CAP_H PROV PRICE LEFT PREEMPT WHY_PROV s p done_seen=0
  VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; TAGS="$(plan_get "$i" tags)"
  SH="$OUT/shard-$i"; mkdir -p "$SH"; KEYF="$SH/tb-key"
  if [ -z "$COLLECT" ]; then
    # D-468 (G1 bugs A3, A4): the estimate, cap and provisioning of the parts this shard has LEFT: a restart after a
    # pre-emption (TB_RUN_ID=<run id> --shard i) gets a cap for what is left, and spot once its hospital parts are done
    cr --shard-now "$PLAN" --shard-index "$i" --run-id "$RUN_ID" --head-file "$OUT/TB_HEAD.json" \
      --parts-dir "$SH/parts" "$OUT/parts" > "$SH/now.json" || { echo "VM $i: no estimate of its parts left" >&2; return 3; }
    now_get() { "$PY" -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(" ".join(v) if isinstance(v, list) else v)' "$SH/now.json" "$1"; }
    EST_H="$(now_get hours)"; EST_USD="$(now_get usd)"; CAP_H="${HOURS:-$(now_get cap_hours)}"
    PROV="$(now_get provisioning)"; PRICE="$(now_get price_per_hour)"; LEFT="$(now_get left)"
    # why this model: the owner's TB_PROVISIONING for every VM (tools.complete_run.provisioning), else D-468
    if [ -n "${TB_PROVISIONING:-}" ]; then WHY_PROV="$([ "$PROV" = STANDARD ] && echo "on demand" || echo spot) (forced by TB_PROVISIONING)"
    elif [ "$PROV" = STANDARD ]; then WHY_PROV="on demand (a hospital part, D-468)"
    else WHY_PROV=spot; fi
    echo "VM $i/$VMS $VM ($ZONE): estimate ${EST_H} h (US\$${EST_USD}); hard cap ${CAP_H} h (STOP), at most US\$$("$PY" -c "print(round($CAP_H*$PRICE, 2))"); $WHY_PROV; parts: $TAGS; parts left: ${LEFT:-none}"
    # one launch per VM at a time (the lock is this child's: it ends with it)
    [ "$DRY" = 1 ] || { mkdir -p "$LOCKS"; lock_or_say 7 "$LOCKS/$VM-$ZONE.lock" "VM $VM ($ZONE)" || return 7; }
    if [ -z "${TB_DRIVER_CHILD:-}" ]; then  # a --shard restart by hand: the quota of its zone, as a launch reads it
      quota_check 1 "$ZONE" "$([ "$PROV" = STANDARD ] && echo "$ZONE" || true)" || { echo "$VM: not started (quota)" >&2; return 4; }
    fi
    s="$(status)"
    [ "$s" = TERMINATED ] || { echo "$VM is $s, not TERMINATED: stop it first (--stop) or collect its run" >&2; return 3; }
    prev_run_check "$VM" "$ZONE" || return 3
    door_reach_check || { echo "$VM: not started (see above)" >&2; return 3; }   # A6: a door no proxy can carry
    door_vm_ready || { echo "$VM: not started (see above)" >&2; return 3; }   # its door: Secret Manager, 443 only
    # ------------------------------------------------------------ 1. the cloud-side hard cap, before the start
    # GCE refuses STANDARD on a VM created preemptible unless the flag is cleared with it (G1 2026-11-12: "For
    # preemptible, only allowed provisioning_model value is SPOT"), and SPOT goes back with --preemptible
    if [ "$PROV" = STANDARD ]; then PREEMPT=--no-preemptible; else PREEMPT=--preemptible; fi
    gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${CAP_H}h" --instance-termination-action=STOP "$PREEMPT" --provisioning-model="$PROV"
    [ "$DRY" = 1 ] || gc compute instances describe "$VM" --zone "$ZONE" \
      --format='value(scheduling.provisioningModel,scheduling.maxRunDuration.seconds,scheduling.instanceTerminationAction)'
    # ------------------------------------------------------------ the door (Secret Manager, TLS), the metadata, the start
    if [ "$DRY" = 1 ]; then echo "+ a random key into $KEYF, a TLS key and its self-signed certificate $SH/door.crt (0600; door_make)"
    else door_make "$SH" || { echo "$VM: the door's key or certificate could not be made (openssl)" >&2; return 3; }; fi
    door_secret_add || { echo "$VM: not started: its door is not in Secret Manager" >&2; return 3; }
    rm -f "$SH/results.tgz" "$SH/results.final" "$SH/collect-boot" "$SH/state"
    gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
      "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-door-cert=$SH/door.crt" \
      --metadata "tb-door-secret=$DOOR_SECRET,tb-door-version=$(cat "$SH/door-version"),tb-run-id=$RUN_ID-s$i,tb-patients=$PATIENTS,tb-only=$TAGS,tb-llm-concurrency=$(plan_lc),tb-src-sha256=$SRC_SHA,tb-collect-only=0,tb-max-minutes=$((CAP_H * 60 - 5)),tb-idle-minutes=20,tb-done-grace=30${BUCKET:+,tb-bucket=$BUCKET}" \
      || { echo "$VM: not started: its metadata could not be set" >&2; door_retire; return 3; }
    # every give-up from here destroys the door versions it made (A8): a failed start, no door, a failed upload, and
    # (the trap) any other exit or signal before the upload is accepted: an error, Ctrl-C, a lost shell
    trap 'give_up_started "the driver ended before the code was accepted"' EXIT
    trap 'exit 9' INT TERM HUP
    gc compute instances start "$VM" --zone "$ZONE" \
      || { give_up_started "the start failed"; return 3; }
    echo "started $VM; it stops itself (cap ${CAP_H} h, watchdog). Collect, now and later: $0 --collect $RUN_ID"
    IP="$(ip)"
    if [ -z "$BUCKET" ]; then  # 3. the code through the door (TLS) once it is up (the VM waits 30 minutes for it)
      # A6: a door that never answers is a paid VM nobody can drive: stop it now, not after its own watchdog
      wait_door 90 || { give_up_started "the door did not answer in 30 minutes (no code was uploaded)"; return 4; }
      door PUT upload --data-binary @"$OUT/src.tgz" -H 'Content-Type: application/gzip' \
        || { give_up_started "the code upload failed"; return 4; }
    fi
    trap - EXIT INT TERM HUP   # the code is there (door) or in the bucket: the VM runs and stops itself
    [ "$DRY" = 1 ] || flock -u 7 2>/dev/null || true
    [ "$WAIT" = 1 ] || return 0
  else
    # nothing more to come: the results are here, or a results-only boot found none; a door that --stop destroyed
    # (A8) is made anew by the results-only boot (collect_start)
    if [ -f "$SH/results.final" ] || [ "$(cat "$SH/state" 2>/dev/null)" = noresults ] \
       || { [ ! -f "$KEYF" ] && [ ! -f "$SH/door.crt" ]; }; then
      echo "VM $i of run $RUN_ID: results here (or none to come) and its door gone: nothing to collect"; return 0
    fi
    IP="$(ip)"
  fi
  # -------------------------------------------------------------- poll: short calls only, nothing held open
  # it ends only when the VM has stopped (TERMINATED, STOPPED) or says DONE; any other answer, "unknown" (a describe
  # that failed) among them, is not the end of the run: the poll goes on, bounded by the VM's cap and 30 minutes
  local poll_end=$((SECONDS + ${CAP_H:-${HOURS:-$(plan_get "$i" cap_hours)}} * 3600 + 1800))
  while :; do
    s="$(status)"
    echo "$(date -u +%H:%M) $VM $s"
    case "$s" in TERMINATED|STOPPED) break ;; esac
    if [ "$s" = RUNNING ]; then
      door POST heartbeat >/dev/null 2>&1 || true   # the VM's driver-alive, not its run heartbeat
      p="$(door GET progress 2>/dev/null || true)"
      printf '%s\n' "$p" | tail -n 3
      if printf '%s' "$p" | grep -q '^DONE'; then done_seen=1; break; fi
    fi
    [ "$DRY" = 1 ] && break
    if [ "$FOLLOW" = 0 ] && [ -n "$COLLECT" ]; then  # one look: the results so far, and come back later
      [ "$s" = RUNNING ] || echo "VM $i: status $s: taken as still running (nothing is marked final, its door is kept)"
      fetch_results 2>/dev/null && echo "VM $i: still running; the results so far ($(stat -c %s "$SH/results.tgz") bytes) are merged below; --collect $RUN_ID again later"
      echo running > "$SH/state"; return 0
    fi
    [ "$SECONDS" -lt "$poll_end" ] \
      || { echo "VM $i: still $s past its cap: not collected; --collect $RUN_ID later" >&2; echo running > "$SH/state"; return 6; }
    sleep 60
  done
  # -------------------------------------------------------------- this VM's results
  local booted=0 got=0
  # TB_BUCKET: the bucket may already have them; else (or in door mode) a stopped VM is started results-only
  if [ "$DRY" = 0 ] && [ -n "$BUCKET" ] && [ "$s" != RUNNING ] && fetch_results; then got=1; fi
  if [ "$DRY" = 0 ] && [ "$got" = 0 ] && [ "$done_seen" = 0 ] && [ "$s" != RUNNING ] && [ ! -f "$SH/results.final" ]; then
    # once per VM and run: a results-only boot that finds nothing is not repeated at every --collect
    if [ -f "$SH/collect-boot" ]; then
      echo "VM $i: a results-only boot found nothing earlier; its disk has no results" >&2
      [ -z "$BUCKET" ] || echo "VM $i: and $BUCKET/runs/$RUN_ID-s$i/results.tgz is not there" >&2
      echo "noresults" > "$SH/state"; door_retire; reset_vm; return 5
    fi
    collect_start || { echo stopped > "$SH/state"; return 5; }   # it marks collect-boot once its door answered
    booted=1
  fi
  if [ "$got" = 1 ] || fetch_results; then
    touch "$SH/results.final"; echo "done" > "$SH/state"
    door POST collected >/dev/null 2>&1 || true   # the VM powers off now
    door_retire  # the key and its secret version are kept until the results are here (--collect)
    settle_and_reset
  elif [ "$done_seen" = 1 ] || [ "$booted" = 1 ]; then  # done, or started for this, and nothing to hand over
    door POST collected >/dev/null 2>&1 || true   # so it powers off now, not after its grace
    door_retire
    echo "VM $i: no results.tgz on its disk (see its serial console); it powers off now" >&2; echo "noresults" > "$SH/state"
    settle_and_reset
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
      f"{p['vms']} VM(s); a VM with a hospital part runs on demand (D-468), the others spot")
print(f"{'VM':<3} {'name':<15} {'zone':<19} {'hours':>6} {'US$':>7} {'cap h':>6} {'cap US$':>8}  {'model':<9} {'US$/h':>6}  parts")
for s in p["shards"]:
    print(f"{s['shard']:<3} {s['vm']:<15} {s['zone']:<19} {s['hours']:>6.2f} {s['usd']:>7.2f} {s['cap_hours']:>6} "
          f"{s['cap_usd']:>8.2f}  {s.get('provisioning', 'SPOT'):<9} {s.get('price_per_hour', 2.74):>6}  {' '.join(s['tags'])}")
print(f"total {p['hours']:.2f} VM-hours, US${p['usd']:.2f}; wall about {p['wall_hours']:.2f} h; at most "
      f"US${p['cap_usd']:.2f} if every VM ran to its cap")
sys.path[:0] = ["."]
from tools.complete_run import concurrency_lines
print("\n".join(concurrency_lines(e)))
PY
fi

if [ "$STOP" = 1 ]; then
  if [ -f "$PLAN" ]; then  # A8: a stopped VM of this run needs its door no more (a results-only boot makes a new one)
    for i in $(seq 1 "$VMS"); do
      VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; stop_vm
      SH="$OUT/shard-$i"; KEYF="$SH/tb-key"
      if [ -f "$SH/door-version" ] || [ -f "$SH/door-versions" ] || [ -f "$KEYF" ]; then door_retire; fi
    done
  else
    names=(); for i in $(seq 1 "$VMS"); do names+=("$(vm_name "$i")"); done
    for i in $(seq 1 "$VMS"); do VM="${names[$((i - 1))]}"; ZONE="$(vm_zone "$i")"; stop_vm; done
  fi
  door_versions_left
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
  door_reach_check || exit 2   # A6: before anything is made or started
  quota_check "$VMS" || exit 4
  # A7: the same read-only pre-flight as --preflight, before any VM starts: every problem at once, each with its fix
  vms=(); for i in $(seq 1 "$VMS"); do vms+=("$(plan_get "$i" vm) $(plan_get "$i" zone)"); done
  PF_RUN="$RUN_ID" preflight "$OUT/preflight" "${vms[@]}" || { echo "not started: fix the problems above (--preflight checks again, free)" >&2; exit 6; }
  for i in $(seq 1 "$VMS"); do  # every VM is there and stopped before any of them starts
    VM_I="$(plan_get "$i" vm)"; Z_I="$(plan_get "$i" zone)"
    if [ "$DRY" = 0 ]; then
      s="$(gc compute instances describe "$VM_I" --zone "$Z_I" --format='value(status)' 2>/dev/null || echo missing)"
      [ "$s" = TERMINATED ] || { echo "$VM_I ($Z_I) is $s: stop it, or make it with --provision" >&2; exit 3; }
    fi
    prev_run_check "$VM_I" "$Z_I" || exit 3   # its disk holds a run whose results are not here: nothing starts
  done
  if [ -n "$BUCKET" ]; then for i in $(seq 1 "$VMS"); do gc storage cp "$OUT/src.tgz" "$BUCKET/runs/$RUN_ID-s$i/src.tgz"; done; fi
fi

# -------------------------------------------------------------- one child per VM; each stops its own VM
CHILD=("$0"); [ "$DRY" = 1 ] && CHILD+=(--dry-run); [ "$WAIT" = 1 ] || CHILD+=(--no-wait); [ "$FOLLOW" = 1 ] && CHILD+=(--follow)
[ -n "$HOURS" ] && CHILD+=(--hours "$HOURS"); [ -n "$COLLECT" ] && CHILD+=(--collect "$COLLECT")
[ "$DISCARD_PREV" = 1 ] && CHILD+=(--discard-previous)
export TB_RUN_ID="$RUN_ID" TB_COMPLETE_DIR="$OUT" TB_DRIVER_CHILD=1
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
# the report's plan has the hospital part once per value of the run's --llm-concurrency list (G-3), as the VM's had
LC="$(plan_lc 2>/dev/null || true)"; LCR=(); [ -z "$LC" ] || LCR=(--llm-concurrency "$LC")
if [ "$DRY" = 1 ]; then
  for i in $(seq 1 "$VMS"); do echo "+ tar -xzf $OUT/shard-$i/results.tgz -C $OUT/shard-$i; parts/ and report/shots/ into $OUT"; done
  echo "# every part of the plan here: each VM's door version is destroyed (and a VM still running powers off)"
  door_retire; door_versions_left
  [ "$G1" = 1 ] && echo "+ $PY -m tools.complete_run --dir $OUT --resume --only walk backup update scale ${STUB[*]}"
  echo "+ $PY -m tools.complete_run --dir $OUT --report-only --model pair ${STUB[*]} ${LCR[*]} --report-parts $ONLY"
  exit 0
fi
missing=""; running=""
mkdir -p "$OUT/parts" "$OUT/report/shots"
rm -f "$OUT/parts/prepare.json" "$OUT/parts/install.json"   # merged afresh from every VM's copy below
for i in $(seq 1 "$VMS"); do
  SH="$OUT/shard-$i"
  [ "$(cat "$SH/state" 2>/dev/null)" = running ] && running="$running $i"
  if [ -s "$SH/results.tgz" ] && rm -rf "$SH/parts" "$SH/report" && tar -xzf "$SH/results.tgz" -C "$SH"; then
    # prepare / install run on every VM with a hospital part: merged as failed if any VM's copy failed
    cr --merge-parts "$SH/parts" --parts-dir "$OUT/parts" || true
    # each model part's measurements (G-3): the servers' /metrics before and after, gpu.csv, vllm.csv
    for d in "$SH"/parts/*/; do if [ -d "$d" ]; then cp -pr "$d" "$OUT/parts/"; fi; done
    cp -pr "$SH"/report/shots/. "$OUT/report/shots/" 2>/dev/null || true
    for b in bench-embed bench-profile; do [ -d "$SH/$b" ] && cp -pr "$SH/$b" "$OUT/"; done
  else missing="$missing $i"; fi
done
[ -f "$OUT/shard-1/serving_config.rtxpro6000.live.json" ] && cp "$OUT/shard-1/serving_config.rtxpro6000.live.json" "$OUT/"
[ -z "$missing" ] || echo "no results from VM(s)$missing: their parts are failed rows; --collect $RUN_ID later" >&2
# A8 (2026-11-12: a version stayed enabled twice, the collect having come while the VM ran or through the bucket):
# every part of the plan is here, so no VM needs its door any more: destroy each version, a running VM powers off
parts_left="$(cr --parts-missing "$PLAN" --parts-dir "$OUT/parts" 2>/dev/null || echo "?")"
if [ -z "$missing" ] && [ -z "$parts_left" ]; then
  door_retire_all; running=""
fi
door_versions_left
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
  "${STUB[@]}" "${LCR[@]}" "${LIVE[@]}" ${TB_PLANNED_FROM:+--planned-from "$TB_PLANNED_FROM"} "${PENDING[@]}" --report-parts $ONLY || true
echo "report: $OUT/report/report.md"
for i in $(seq 1 "$VMS"); do VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; echo "VM $VM status: $(status)"; done