#!/usr/bin/env bash
# TrialBox complete-platform run on the RTX PRO 6000 (TB-PLAN-04 step 9, D-139, D-141, D-147). Owner's OK first: it
# starts paid VMs (tb-gpu-sim and its clones, g4-standard-48 spot, about US$2.74 an hour each).
#
#   export CLOUDSDK_CONFIG=<a private folder>              # never the default one
#   export TB_SA_KEY_FILE=<the service account key file>   # gcloud re-activates from it on an auth error
#   gcloud auth activate-service-account --key-file "$TB_SA_KEY_FILE" && gcloud config set project trialbox-demo
#   deploy/gcp/complete-run.sh --estimate [--patients 50000] [--vms N] [--parts g1,embed,profile]  # nothing started
#   deploy/gcp/complete-run.sh --dry-run [--vms N] [--zones z1,z2] [--parts ...] [VM] [ZONE]  # every command, none run
#   deploy/gcp/complete-run.sh --provision --vms N --zones z1,z2,...   # once: the clones tb-gpu-sim-2..N (they
#                                                                      # boot, power off at once, keep their disks)
#   deploy/gcp/complete-run.sh [--patients 50000] [--vms N] [--zones ...] [--parts ...] [--hours H] [--no-wait]
#   deploy/gcp/complete-run.sh --collect <run id>          # later: every VM's results, the stub parts, the report
#   deploy/gcp/complete-run.sh --stop [--collect <run id> | --vms N --zones ...] [VM] [ZONE]   # stop by hand
#   deploy/gcp/complete-run.sh --teardown --vms N --zones ...   # delete the clones 2..N and their machine image
#
# Parallel (D-147): --vms N splits the run into N shards of whole parts (complete_run --only tags; longest first onto
# the least-loaded VM, tools/complete_run.py shard_plan): no part is split, so the merged report is the single-VM
# report. VM 1 is VM (tb-gpu-sim) in the first zone, VM i is VM-i in zone i (--zones, or TB_ZONES; one zone per
# region where the GPU quota is 1 per region). Every VM gets its own cap, key, watchdog and run directory
# (<run>/shard-<i>); the driver runs one child per VM, waits for all, merges parts/ and the screenshots, runs the
# stub parts and writes one report. --parts: g1 (the complete run), embed and profile (the benches,
# tools/bench_embed.py and tools/bench_profile.py); e.g. --parts g1,embed,profile.
#
# Fail-safe (D-141; the 2026-11-09 incident: a dead driver left the VM running for 61 minutes), per VM:
#   1. Cloud-side hard cap, set before the start: max-run-duration of that VM's estimate x 1.3 rounded up (--hours to
#      change it), termination action STOP. Compute Engine stops the VM at the cap whatever else happens.
#   2. The VM stops itself (deploy/gcp/complete-run-vm.sh): a systemd hard cap, and a watchdog that powers off when
#      the heartbeat is not touched for 20 minutes or the done marker appears (after the driver collects, or 30
#      minutes later).
#   3. The workload runs on the VM (48 vCPU): the driver uploads the code (git archive of HEAD), polls, downloads the
#      results and runs the stub parts (walk, backup, update, scale) here once the VMs have stopped. The driver can
#      die at any moment; `--collect <run id>` picks the run up again (every VM of it).
#   4. Every gcloud call goes through `gc` (deploy/gcp/gcloud-auth.sh): an auth error re-activates the service
#      account from TB_SA_KEY_FILE and retries once; a probe before the start fails fast.
#   5. Every part is resumable: a restarted VM runs complete_run --resume (parts with a passed result are kept). A
#      preempted VM: `TB_RUN_ID=<run id> complete-run.sh --shard <i>` starts that VM again on the same plan.
# Optional TB_BUCKET=gs://<bucket>: code and results go through the bucket (the VM's service account needs
# storage access); without it they go over HTTP to the VM, the key in the Authorization header.
set -euo pipefail
DRY=0; STOP=0; ESTIMATE=0; WAIT=1; PATIENTS=50000; HOURS=""; COLLECT=""; VMS=1; PARTS=g1; ZONES="${TB_ZONES:-}"
SHARD=""; PROVISION=0; TEARDOWN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --stop) STOP=1; shift ;;
    --estimate) ESTIMATE=1; shift ;;
    --no-wait) WAIT=0; shift ;;
    --patients) PATIENTS="$2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    --collect) COLLECT="$2"; shift 2 ;;
    --vms) VMS="$2"; shift 2 ;;
    --parts) PARTS="$2"; shift 2 ;;
    --zones) ZONES="$2"; shift 2 ;;
    --shard) SHARD="$2"; shift 2 ;;
    --provision) PROVISION=1; shift ;;
    --teardown) TEARDOWN=1; shift ;;
    -h|--help) sed -n 2,40p "$0"; exit 0 ;;
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
cd "$ROOT"
cr() { env PYTHONPATH=libs:services:. "$PY" -m tools.complete_run "$@"; }

if [ "$ESTIMATE" = 1 ]; then
  cr --estimate --patients "$PATIENTS" --vms "$VMS" --parts "$PARTS" ${TB_ESTIMATE_FROM:+--estimate-from "$TB_ESTIMATE_FROM"}
  exit 0
fi
if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG and activate the service account in it}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"*) echo "CLOUDSDK_CONFIG must be private" >&2; exit 2 ;; esac
fi
unset CLOUDSDK_AUTH_ACCESS_TOKEN

RUN_ID="${COLLECT:-${TB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)}}"
OUT="${TB_COMPLETE_DIR:-$ROOT/.cache/complete-run/$RUN_ID}"
mkdir -p "$OUT"
umask 077
PLAN="$OUT/plan.json"
plan_get() {  # shard field: one value of plan.json (vm, zone, cap_hours, hours, usd, tags as one line)
  "$PY" -c 'import json,sys; s=json.load(open(sys.argv[1]))["plan"]["shards"][int(sys.argv[2])-1]; v=s[sys.argv[3]]
print(" ".join(v) if isinstance(v, list) else v)' "$PLAN" "$1" "$2"
}
vm_name() { if [ "$1" = 1 ]; then echo "$VM"; else echo "$VM-$1"; fi; }
vm_zone() { echo "$ZONES" | cut -d, -f"$1"; }

# ================================================================== one VM (a shard of the plan): the D-141 run
status() { if [ "$DRY" = 1 ]; then echo TERMINATED; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(status)' || echo unknown; fi; }
stop_vm() {
  gc compute instances stop "$VM" --zone "$ZONE" || true
  local s; s="$(status)"
  echo "VM $VM status: $s"
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file startup-script="$ROOT/deploy/gcp/gpu-sim-startup.sh" || true
}
ip() { if [ "$DRY" = 1 ]; then echo "<vm-ip>"; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)'; fi; }
door() {  # METHOD PATH [curl args...]: the VM's door, the key in a header read from the key file (never argv)
  local m=$1 p=$2; shift 2
  if [ "$DRY" = 1 ]; then echo "+ curl -X $m http://<vm-ip>/tb/$p (Authorization from $KEYF)"; return 0; fi
  curl -fsS --max-time 600 -X "$m" -H @<(printf 'Authorization: Bearer %s\n' "$(cat "$KEYF")") "http://$IP/tb/$p" "$@"
}

shard_run() {  # $1 = shard number; VM, ZONE, caps and parts come from plan.json
  local i=$1 SH TAGS EST_H EST_USD CAP_H s p
  VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; TAGS="$(plan_get "$i" tags)"
  EST_H="$(plan_get "$i" hours)"; EST_USD="$(plan_get "$i" usd)"; CAP_H="${HOURS:-$(plan_get "$i" cap_hours)}"
  SH="$OUT/shard-$i"; mkdir -p "$SH"; KEYF="$SH/tb-key"
  if [ -z "$COLLECT" ]; then
    echo "VM $i/$VMS $VM ($ZONE): estimate ${EST_H} h (US\$${EST_USD}); hard cap ${CAP_H} h (STOP), at most US\$$("$PY" -c "print(round($CAP_H*2.74, 2))"); parts: $TAGS"
    s="$(status)"
    [ "$s" = TERMINATED ] || { echo "$VM is $s, not TERMINATED: stop it first (--stop) or collect its run" >&2; return 3; }
    # ------------------------------------------------------------ 1. the cloud-side hard cap, before the start
    gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${CAP_H}h" --instance-termination-action=STOP
    [ "$DRY" = 1 ] || gc compute instances describe "$VM" --zone "$ZONE" \
      --format='value(scheduling.maxRunDuration.seconds,scheduling.instanceTerminationAction)'
    # ------------------------------------------------------------ the key, the metadata, the start
    if [ "$DRY" = 1 ]; then echo "+ a random key into $KEYF (0600)"
    else "$PY" -c 'import secrets; print(secrets.token_urlsafe(32))' > "$KEYF"; fi
    gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file \
      "startup-script=$ROOT/deploy/gcp/complete-run-vm.sh,tb-serving-config=$ROOT/tools/serving_config.py,tb-key=$KEYF" \
      --metadata "tb-run-id=$RUN_ID-s$i,tb-patients=$PATIENTS,tb-only=$TAGS,tb-max-minutes=$((CAP_H * 60 - 5)),tb-idle-minutes=20,tb-done-grace=30${BUCKET:+,tb-bucket=$BUCKET}"
    gc compute instances start "$VM" --zone "$ZONE"
    echo "started $VM; it stops itself (cap ${CAP_H} h, watchdog 20 min idle). Pick the run up again with: $0 --collect $RUN_ID"
    IP="$(ip)"
    if [ -z "$BUCKET" ]; then  # 3. the code over HTTP once the door is up (the VM waits 30 minutes for it)
      for _ in $(seq 1 90); do door POST heartbeat >/dev/null 2>&1 && break; [ "$DRY" = 1 ] && break; sleep 20; done
      door PUT upload --data-binary @"$OUT/src.tgz" -H 'Content-Type: application/gzip'
    fi
    [ "$WAIT" = 1 ] || return 0
  else
    [ -f "$KEYF" ] || { echo "no key for VM $i of run $RUN_ID in $SH" >&2; return 2; }
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
    printf '%s' "$p" | grep -q '^DONE' && break
    [ "$DRY" = 1 ] && break
    sleep 60
  done
  # -------------------------------------------------------------- this VM's results
  if [ -n "$BUCKET" ]; then gc storage cp "$BUCKET/runs/$RUN_ID-s$i/results.tgz" "$SH/results.tgz" || true
  else door GET results.tgz -o "$SH/results.tgz" || echo "results not reachable: $VM has stopped; start it to resume, or --collect later" >&2
  fi
  door POST collected >/dev/null 2>&1 || true   # the VM powers off now
  [ "$DRY" = 1 ] || [ ! -s "$SH/results.tgz" ] || rm -f "$KEYF"  # kept until the results are here (--collect)
}

if [ -n "$SHARD" ]; then  # a child of the driver below (or a restart of one VM by hand)
  [ -f "$PLAN" ] || { echo "no plan $PLAN (TB_RUN_ID=<run id> to restart a VM of a run)" >&2; exit 2; }
  VMS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan"]["vms"])' "$PLAN")"
  shard_run "$SHARD"
  exit $?
fi

# ================================================================== the driver: plan, VMs, children, merge
if [ -n "$COLLECT" ] && [ -f "$PLAN" ]; then
  VMS="$("$PY" -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p["plan"]["vms"])' "$PLAN")"
  PARTS="$("$PY" -c 'import json,sys; print(",".join(json.load(open(sys.argv[1]))["parts"]))' "$PLAN")"
  PATIENTS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["patients"])' "$PLAN")"
elif [ -z "$COLLECT" ]; then
  [ "$(echo "$ZONES" | tr ',' '\n' | grep -c .)" -ge "$VMS" ] || { echo "--zones: $VMS zones needed, got '$ZONES'" >&2; exit 2; }
  cr --estimate --json --patients "$PATIENTS" --vms "$VMS" --parts "$PARTS" \
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
print(f"plan: {e['patients']:,} patients, parts {','.join(e['parts'])}, {p['vms']} VM(s), US${e['price_per_hour']}/h each")
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

if [ -z "$COLLECT" ]; then
  if [ "$DRY" = 1 ]; then
    echo "# zones are candidates for the RTX PRO 6000 (G4); before the run, the owner checks (read-only):"
    echo "#   gcloud compute accelerator-types list --filter='name~rtx' --format='value(zone,name)'"
    for z in $(echo "$ZONES" | cut -d, -f1-"$VMS" | tr ',' ' '); do
      echo "#   gcloud compute regions describe ${z%-*} --flatten=quotas --filter='quotas.metric~RTX|CPUS' --format='table(quotas.metric,quotas.limit,quotas.usage)'"
    done | awk '!seen[$0]++'
    echo "#   gcloud compute project-info describe --flatten=quotas --filter='quotas.metric~GPUS_ALL_REGIONS' --format='table(quotas.metric,quotas.limit,quotas.usage)'"
    echo "+ git archive --format=tar.gz -o $OUT/src.tgz HEAD trialbox"
  else
    git -C "$ROOT/.." archive --format=tar.gz -o "$OUT/src.tgz" HEAD trialbox
  fi
  [ -n "$(git status --porcelain)" ] && echo "note: local changes are NOT in the run; it runs HEAD $(git rev-parse --short HEAD)" >&2
  gc_probe
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
CHILD=("$0"); [ "$DRY" = 1 ] && CHILD+=(--dry-run); [ "$WAIT" = 1 ] || CHILD+=(--no-wait)
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
ONLY="$("$PY" -c 'import json,sys; e=json.load(open(sys.argv[1])); t=[x for s in e["plan"]["shards"] for x in s["tags"]]
g1 = "g1" in e["parts"]; print(" ".join(t + (["walk", "backup", "update", "scale"] if g1 else [])))' "$PLAN" 2>/dev/null || echo "")"
G1=0; case ",$PARTS," in *,g1,*) G1=1 ;; esac
if [ "$DRY" = 1 ]; then
  for i in $(seq 1 "$VMS"); do echo "+ tar -xzf $OUT/shard-$i/results.tgz -C $OUT/shard-$i; parts/ and report/shots/ into $OUT"; done
  [ "$G1" = 1 ] && echo "+ $PY -m tools.complete_run --dir $OUT --resume --only walk backup update scale"
  echo "+ $PY -m tools.complete_run --dir $OUT --report-only --model pair --patients $PATIENTS --report-parts $ONLY"
  exit 0
fi
missing=""
mkdir -p "$OUT/parts" "$OUT/report/shots"
for i in $(seq 1 "$VMS"); do
  SH="$OUT/shard-$i"
  if [ -s "$SH/results.tgz" ] && tar -xzf "$SH/results.tgz" -C "$SH"; then
    cp -p "$SH"/parts/*.json "$OUT/parts/" 2>/dev/null || true
    cp -pr "$SH"/report/shots/. "$OUT/report/shots/" 2>/dev/null || true
    for b in bench-embed bench-profile; do [ -d "$SH/$b" ] && cp -pr "$SH/$b" "$OUT/"; done
  else missing="$missing $i"; fi
done
[ -f "$OUT/shard-1/serving_config.rtxpro6000.live.json" ] && cp "$OUT/shard-1/serving_config.rtxpro6000.live.json" "$OUT/"
[ -z "$missing" ] || echo "no results from VM(s)$missing: their parts are failed rows; --collect $RUN_ID later" >&2
[ "$G1" = 1 ] && { env TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" --resume \
  --only walk backup update scale || true; }
LIVE=(); [ -f "$OUT/serving_config.rtxpro6000.live.json" ] && LIVE=(--live-record "$OUT/serving_config.rtxpro6000.live.json")
env TB_ENV=DEV PYTHONPATH=libs:services:. "$PY" -m tools.complete_run --dir "$OUT" --report-only --model pair \
  --patients "$PATIENTS" "${LIVE[@]}" --report-parts $ONLY || true
echo "report: $OUT/report/report.md"
for i in $(seq 1 "$VMS"); do VM="$(plan_get "$i" vm)"; ZONE="$(plan_get "$i" zone)"; echo "VM $VM status: $(status)"; done
