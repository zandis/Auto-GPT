#!/usr/bin/env bash
# The 48 GB measuring run, unattended (lane H, card H-53): H-47's sheet (docs/plan/measurements/48gb-measuring-run-
# 2026-11-19.md) as a run the integrator starts with no SSH. This driver makes a NEW Spot VM for the run (100 GB
# disk), gives it tools/measure48-vm.sh as its start-up script and tools/measure48_vm.py as its helper, and
# collects the records the VM puts in the bucket as it goes; the VM powers itself off at the end, on success and on
# failure, and the collect that finds it ended deletes it. Owner's yes first for anything but --estimate and
# --preflight: the launch starts a paid VM (g4-standard-48 + RTX PRO 6000, US$2.74 an hour SPOT).
#
#   export CLOUDSDK_CONFIG=<a private folder> TB_SA_KEY_FILE=<the deployer's key file> TB_BUCKET=gs://trialbox-demo-runs
#   deploy/gcp/measure48-run.sh --estimate [--no-o]           # free, no gcloud: stages, hours, US$, stop line, cap
#   deploy/gcp/measure48-run.sh --preflight [--commit <sha>] [--no-o] [VM] [ZONE]   # read-only gcloud calls only:
#       the commit, its archive, the pinned weights list (fetch_weights --dry-run), the quota (one Spot RTX PRO 6000
#       and the region's HDB_TOTAL_GB for the 100 GB disk), the VM name free, the bucket readable
#   deploy/gcp/measure48-run.sh [--commit <sha>] [--no-o] [--dry-run] [VM] [ZONE]   # the launch (returns at once)
#   deploy/gcp/measure48-run.sh --collect <run id> [--keep-vm] [VM] [ZONE]   # the records so far and the summary;
#       a run that ended on a VM that is TERMINATED: the VM is deleted (--keep-vm leaves it)
#   deploy/gcp/measure48-run.sh --resume <run id> [VM] [ZONE]  # a pre-empted VM (STOP) started again, with the cap
#       left of the run's 4 h (the VM's clock less 8 minutes a boot); refused when the run's steps.json has no clock
#   deploy/gcp/measure48-run.sh --stop <run id> [VM] [ZONE]    # stop now by hand (the VM's last upload stays), collect
#   deploy/gcp/measure48-run.sh --delete <run id> [VM] [ZONE]  # delete the run's VM (TERMINATED, and that run's)
#   --collect, --stop, --resume and --delete act on a VM only when it carries label trialbox=h53-48gb AND metadata
#   tb-run-id=<run id>: a VM that now has the name but is another run's (or anything else) is refused, unchanged.
#
# VM defaults to tb-h47-48gb (H-47's name for this run's VM), ZONE to asia-east1-a (the driver's default, as
# deploy/gcp/box-run.sh). Only tb-h47-... and tb-h53-... names are taken: this driver never starts, stops or deletes a
# kept VM (tb-gpu-sim, tb-demo-vm, tb-preview-vm, tb-steps-vm) or a neighbour of one. The run's bucket folder: $TB_BUCKET/m48runs/<run id>/ (src.tgz, and the
# records the VM uploads after every step). The local folder: .cache/measure48/<run id>/.
# Why not box-run.sh --steps measure48: box-run.sh drives one kept VM (tb-gpu-sim, 400 GB, the box's own host with the
# driver and the weights on its disk) that it starts and puts back; it never makes or deletes one, and this run may not
# use tb-gpu-sim. Its VM script is the box's install harness (bundles, wizard, sessions). This run needs a new VM, a
# plain image and a 100 GB disk: the same conventions (gcloud-auth.sh's gc, TB_BUCKET, the records up after every
# step, a cap, power-off on every way out, --estimate / --preflight / --collect / --resume) in a script of its own.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
H="$ROOT/tools/measure48_vm.py"
ESTIMATE=0; PREFLIGHT=0; DRY=0; COLLECT=""; RESUME=""; STOPRUN=""; DELETE=""; KEEPVM=0; NO_O=0; COMMIT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --estimate) ESTIMATE=1; shift ;;
    --preflight) PREFLIGHT=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --collect) COLLECT="$2"; shift 2 ;;
    --resume) RESUME="$2"; shift 2 ;;
    --stop) STOPRUN="$2"; shift 2 ;;
    --delete) DELETE="$2"; shift 2 ;;
    --keep-vm) KEEPVM=1; shift ;;
    --no-o) NO_O=1; shift ;;
    --commit) COMMIT="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    -*) echo "measure48-run: unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
VM="${1:-tb-h47-48gb}"; ZONE="${2:-asia-east1-a}"
cd "$ROOT"
hp() { "$PY" "$H" "$@"; }
LOCAL="${TB_M48_DIR:-$ROOT/.cache/measure48}"   # the run folders here (the rehearsal points it elsewhere)
O_ARGS=(); [ "$NO_O" = 0 ] || O_ARGS=(--no-o)
if [ "$ESTIMATE" = 1 ]; then hp estimate ${O_ARGS[@]+"${O_ARGS[@]}"}; exit 0; fi
# only this run's own names: tb-h47-... or tb-h53-... (never a kept VM nor a neighbour of one, e.g. tb-gpu-sim2)
[[ "$VM" =~ ^tb-h(47|53)-[a-z0-9-]*[a-z0-9]$ ]] && [ "${#VM}" -le 63 ] || {
  echo "measure48-run: refused: $VM is not this run's VM name (tb-h47-... or tb-h53-...; default tb-h47-48gb); the kept" \
    "VMs (tb-gpu-sim, tb-demo-vm, tb-preview-vm, tb-steps-vm) are never used" >&2; exit 2; }
# shellcheck source=deploy/gcp/gcloud-auth.sh
. "$ROOT/deploy/gcp/gcloud-auth.sh"
[ "$DRY" = 0 ] || export GC_DRY=1
BUCKET="${TB_BUCKET:-}"
[ -n "$BUCKET" ] || { echo "measure48-run: set TB_BUCKET=gs://<bucket> (the records come back through it)" >&2; exit 2; }
status() { if [ "$DRY" = 1 ]; then echo "${TB_M48_DRY_STATUS:-NONE}"; return; fi
  gc compute instances describe "$VM" --zone "$ZONE" --format='value(status)' 2>/dev/null || echo NONE; }
owned() {  # $1 run id: 0 when the VM by that name carries this driver's label AND that run id (else it is not ours)
  [ "$DRY" = 0 ] || { echo "+ gcloud compute instances describe $VM (label trialbox=h53-48gb, tb-run-id=$1)"; return 0; }
  local d; d=$(gc compute instances describe "$VM" --zone "$ZONE" --format=json 2>/dev/null) || return 1
  printf '%s' "$d" | "$PY" -c 'import json, sys
d = json.load(sys.stdin)
md = {i.get("key"): i.get("value") for i in (d.get("metadata") or {}).get("items") or []}
ok = (d.get("labels") or {}).get("trialbox") == "h53-48gb" and md.get("tb-run-id") == sys.argv[1]
sys.exit(0 if ok else 1)' "$1"
}
mine() {  # mine <run id> <what it would do>: refuse unless the VM is this run's
  owned "$1" && return 0
  echo "measure48-run: refused to $2 $VM: it is not run $1's VM (label trialbox=h53-48gb and metadata tb-run-id=$1" \
    "are not both on it); nothing was changed" >&2
  return 1
}
collect() {  # $1 run id: the records so far, the summary; a run that ended on a stopped VM: the VM deleted
  local run=$1 out="$LOCAL/$1" st
  mkdir -p "$out"
  gc storage rsync --recursive "$BUCKET/m48runs/$run" "$out" --exclude 'src\.tgz$' > /dev/null \
    || { echo "collect: nothing in $BUCKET/m48runs/$run yet" >&2; }
  [ -s "$out/steps.json" ] && hp summary "$out" | tee "$out/summary.json"
  st=$(status)
  echo "collect: VM $VM is $st; records in $out"
  if [ -s "$out/steps.json" ] && "$PY" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ended") else 1)' "$out/steps.json"; then
    if [ "$st" = TERMINATED ] && [ "$KEEPVM" = 0 ] && mine "$run" delete; then
      gc compute instances delete "$VM" --zone "$ZONE" --quiet && echo "collect: the run ended; VM $VM deleted (its disk with it)"
    fi
  elif [ "$st" = TERMINATED ]; then
    echo "collect: VM $VM stopped before the run ended (a pre-emption, or the cloud's cap): $0 --resume $run, or $0 --delete $run"
  fi
}
if [ -n "$COLLECT" ]; then gc_start; collect "$COLLECT"; exit 0; fi
if [ -n "$DELETE" ]; then
  gc_start; mine "$DELETE" delete || exit 2
  [ "$(status)" = TERMINATED ] || { echo "measure48-run: $VM is $(status), not TERMINATED: --stop $DELETE first" >&2; exit 2; }
  gc compute instances delete "$VM" --zone "$ZONE" --quiet; exit 0
fi
if [ -n "$STOPRUN" ]; then
  gc_start; mine "$STOPRUN" stop || exit 2
  gc compute instances stop "$VM" --zone "$ZONE"; collect "$STOPRUN"; exit 0
fi
BOOT_MARGIN_MIN=8   # a boot's minutes before the VM's clock starts (create or start, the image's own start): billed, uncounted
if [ -n "$RESUME" ]; then
  gc_start; mine "$RESUME" "start again" || exit 2
  [ "$(status)" = TERMINATED ] || { echo "measure48-run: $VM is $(status), not TERMINATED" >&2; exit 2; }
  collect "$RESUME" > /dev/null
  # the clock the VM uploaded, or no start: a missing clock must never become a fresh 240 minutes
  used=$("$PY" -c 'import json,sys; v=json.load(open(sys.argv[1]))["used_s"]; assert isinstance(v, int); print(v)' \
    "$LOCAL/$RESUME/steps.json" 2>/dev/null) \
    || { echo "measure48-run: refused: run $RESUME's steps.json has no used_s (the VM's clock): not started again; --delete $RESUME" >&2; exit 2; }
  boots=$(grep -c ' boot ' "$LOCAL/$RESUME/clock.txt" 2>/dev/null) || boots=1
  [ "$boots" -ge 1 ] || boots=1
  # minutes left of the 4 h: the VM's own clock, and each boot's uncounted minutes (BOOT_MARGIN_MIN)
  left=$(( (4 * 3600 - used) / 60 - boots * BOOT_MARGIN_MIN ))
  [ "$left" -ge 15 ] || { echo "measure48-run: $((used / 60)) minutes on the VM's clock and $boots boot(s) of the run's 240: not started again; --delete $RESUME" >&2; exit 2; }
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${left}m" --instance-termination-action=STOP \
    --provisioning-model=SPOT
  gc compute instances start "$VM" --zone "$ZONE"
  echo "run $RESUME started again on $VM, cloud cap ${left} min; later: $0 --collect $RESUME"; exit 0
fi

# ------------------------------------------------------------------ the launch (and --preflight, which stops before it spends)
COMMIT="${COMMIT:-$(git rev-parse HEAD)}"
COMMIT="$(git rev-parse --verify --quiet "$COMMIT^{commit}")" || { echo "measure48-run: not a commit here: $COMMIT" >&2; exit 2; }
RUN_ID="${TB_RUN_ID:-m48-$(date -u +%Y%m%dT%H%M%SZ)-${COMMIT:0:12}}"
OUT="$LOCAL/$RUN_ID"; mkdir -p "$OUT"
OBJ="$BUCKET/m48runs/$RUN_ID"
hp estimate ${O_ARGS[@]+"${O_ARGS[@]}"} | tail -n 3
LINE_MIN=$(hp stop-line-min ${O_ARGS[@]+"${O_ARGS[@]}"})
# the commit's tree, as complete-run.sh uploads it: a git archive with TB_HEAD.json (the VM checks both)
"$PY" -c 'import json,subprocess as s,sys; c=sys.argv[2]; g=lambda *a: s.check_output(["git",*a],text=True).strip()
json.dump({"head": c, "subject": g("log","-1","--format=%s",c), "dirty": False}, open(sys.argv[1],"w"))' "$OUT/TB_HEAD.json" "$COMMIT"
git -C "$ROOT/.." archive --format=tar.gz --add-file="$OUT/TB_HEAD.json" -o "$OUT/src.tgz" "$COMMIT" trialbox
SRC_SHA="$(sha256sum "$OUT/src.tgz" | cut -d' ' -f1)"
echo "source: $COMMIT, $(wc -c < "$OUT/src.tgz") bytes, sha256 $SRC_SHA"
# the weights' pinned list (free, no network): the VM fetches exactly these from the public hub, with no token. They
# go to the VM's empty 100 GB disk, not to this machine: the list is made for an empty folder and that disk (DISK_GB),
# so a short disk here (Cloud Shell's 5 GB, a CI runner) does not refuse the run; the VM's s04 guard checks its own
mkdir -p "$OUT/vm-models"
PYTHONPATH=. "$PY" -c 'import sys
from pathlib import Path
from tools import fetch_weights as f, measure48_vm as m
sys.exit(f.run("rtxpro6000", Path(sys.argv[1]), dry_run=True, free_bytes=lambda _p: m.DISK_GB * 10**9))' \
  "$OUT/vm-models" > "$OUT/weights-dry-run.txt" \
  || { echo "measure48-run: refused: tools/fetch_weights.py --dry-run fails here (above)" >&2; exit 2; }
tail -n 1 "$OUT/weights-dry-run.txt"
gc_start
st=$(status)
[ "$st" = NONE ] || { echo "measure48-run: refused: a VM $VM exists ($st): collect and delete it first" >&2; exit 2; }
Q="$OUT/quota"; mkdir -p "$Q"
if [ "$DRY" = 1 ]; then echo "+ gcloud compute project-info describe; regions describe ${ZONE%-*} (the quota, read-only)"
else
  gc compute project-info describe --format=json > "$Q/project.json"
  gc compute regions describe "${ZONE%-*}" --format=json > "$Q/region-${ZONE%-*}.json"
  hp quota "$Q" --zone "$ZONE" --disk-gb 100 || exit 4
fi
gc storage ls "$BUCKET" > /dev/null || { echo "measure48-run: refused: $BUCKET is not readable" >&2; exit 2; }
if [ "$PREFLIGHT" = 1 ]; then
  echo "preflight: the launch's checks passed (nothing was uploaded, made or started); the launch: $0 --commit $COMMIT$([ "$NO_O" = 0 ] || echo ' --no-o') $VM $ZONE"
  exit 0
fi
gc storage cp "$OUT/src.tgz" "$OBJ/src.tgz"
MD="tb-run-id=$RUN_ID,tb-bucket=$BUCKET,tb-src=$OBJ/src.tgz,tb-src-sha256=$SRC_SHA,tb-commit=$COMMIT"
MD="$MD,tb-stop-line-minutes=$LINE_MIN,tb-cap-minutes=240,tb-o=$((1 - NO_O)),block-project-ssh-keys=TRUE"
gc compute instances create "$VM" --zone "$ZONE" --machine-type g4-standard-48 \
  --provisioning-model SPOT --instance-termination-action STOP --max-run-duration 4h \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --boot-disk-size 100GB --boot-disk-type hyperdisk-balanced \
  --shielded-vtpm --shielded-integrity-monitoring --no-shielded-secure-boot \
  --scopes storage-rw --labels trialbox=h53-48gb \
  --metadata-from-file "startup-script=$ROOT/tools/measure48-vm.sh,tb-m48-helper=$H" --metadata "$MD"
[ "$DRY" = 0 ] || echo "(dry run: the commands above were printed, nothing was uploaded, made or started)"
echo "run $RUN_ID started on $VM ($ZONE), SPOT, cloud cap 4 h, stop line $LINE_MIN min of the VM's clock"
echo "later: $0 --collect $RUN_ID $VM $ZONE   (as often as wanted; the one that finds it ended deletes the VM)"
