#!/usr/bin/env bash
# The box run's cloud-side driver (lane G's main paid line: R2 and plan v7 §7.1 G-2, G-6, G-9, G-10). The work runs
# ON the VM (deploy/gcp/box-install-run.sh, with deploy/gcp/box_vm.py as its helper); this driver sets the VM up,
# starts it, power-cycles it when G-9 asks, collects the results from the bucket and stops it. Owner's yes first for
# anything but --estimate and --dry-run: it starts a paid VM (tb-gpu-sim, g4-standard-48 + RTX PRO 6000).
#
#   export CLOUDSDK_CONFIG=<a private folder> TB_SA_KEY_FILE=<the deployer's key file> TB_BUCKET=gs://trialbox-demo-runs
#   deploy/gcp/box-run.sh --estimate --steps build,start,g6,g9,g10                    # free: time and US$, sources
#   deploy/gcp/box-run.sh --steps build --release-id 2026.11-1 --release-seq 3 --commit <sha> --key-version <N> \
#       [--dry-run] [--no-wait] [VM] [ZONE]                          # R2: build and sign on the runner VM
#   deploy/gcp/box-run.sh --steps start,g6,g9,g10 --release-id 2026.11-1 --study <RULESET> \
#       --g10-image <vllm image ref> [--g10-bundle gs://... --g10-bundle-sha256 <hex>] [--answers-version <N>] \
#       [--doctor-expected name,name] [--qualify-evidence "n12=gs://... public_e2e=gs://... goldens=gs://..."] \
#       [--commit <sha>] [--dry-run] [--no-wait] [VM] [ZONE]          # G-2 then the tests, one VM launch
#   deploy/gcp/box-run.sh --collect <run id> [--follow]   # results so far; a power cycle G-9 asked for; the report
#   deploy/gcp/box-run.sh --resume <run id>               # start it again after a pre-emption (finished steps kept)
#   deploy/gcp/box-run.sh --stop [<run id>]               # stop, check TERMINATED, put the VM back as it is kept
#
# What a launch does (each gcloud call through `gc`, deploy/gcp/gcloud-auth.sh: timeouts, re-activation):
#   1. refuses unless the VM is TERMINATED, TB_BUCKET is set and the plan's inputs are there;
#   2. build only: the VM runs as the dedicated service account TB_BUNDLE_SIGNER_SA (default tb-bundle-signer), the
#      only reader of the secret TB_VENDOR_KEY_SM_NAME (default tb-vendor-signing-key); the metadata holds the
#      secret's NAME and version, never the key (tools/box_run.py metadata refuses a key-like value);
#   3. the cloud-side hard cap: --max-run-duration = the sum of the groups' caps (tools/box_run.py GROUP_CAP_HOURS),
#      --instance-termination-action=STOP, SPOT unless TB_PROVISIONING=STANDARD; the VM's own cap and watchdog too;
#   4. the startup script, the helper and one metadata file per key (--metadata-from-file), then the start;
#   5. --no-wait: it returns; else it follows (one look a minute) until the VM is TERMINATED with its run ended.
# The VM uploads results.tgz to $TB_BUCKET/boxruns/<run id>/ after every step and powers itself off once its last
# upload went through. A G-9 power cycle: the VM writes POWER-CYCLE-REQUEST there; --collect (or the follow) stops
# the VM, checks TERMINATED, removes the request and starts it again. --stop and the end of a collect put the VM back:
# the usual startup script (gpu-sim-startup.sh), SPOT, the default compute service account, the tb-* keys removed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-$ROOT/.venv/bin/python}"
DRY=0; WAIT=1; FOLLOW=0; ESTIMATE=0; STOP=0; COLLECT=""; RESUME=""; STEPS=""
declare -A V=()
while [ $# -gt 0 ]; do
  case "$1" in
    --estimate) ESTIMATE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --no-wait) WAIT=0; shift ;;
    --follow) FOLLOW=1; shift ;;
    --stop) STOP=1; shift; case "${1:-}" in ""|-*) ;; *) COLLECT="$1"; shift ;; esac ;;
    --collect) COLLECT="$2"; shift 2 ;;
    --resume) RESUME="$2"; shift 2 ;;
    --steps) STEPS="${2//,/ }"; shift 2 ;;
    --release-id) V[tb-release-id]="$2"; shift 2 ;;
    --release-seq) V[tb-release-seq]="$2"; shift 2 ;;
    --commit) V[tb-commit]="$2"; shift 2 ;;
    --key-version) V[tb-vendor-key-version]="$2"; shift 2 ;;
    --study) V[tb-study]="$2"; shift 2 ;;
    --g10-image) V[tb-g10-vllm-image]="$2"; shift 2 ;;
    --g10-bundle) V[tb-g10-bundle]="$2"; shift 2 ;;
    --g10-bundle-sha256) V[tb-g10-bundle-sha256]="$2"; shift 2 ;;
    --answers-version) V[tb-answers-version]="$2"; shift 2 ;;
    --doctor-expected) V[tb-doctor-expected]="${2//,/ }"; shift 2 ;;
    --qualify-evidence) V[tb-qualify-evidence]="$2"; shift 2 ;;
    --bundle) V[tb-bundle]="$2"; shift 2 ;;
    --bundle-sha256) V[tb-bundle-sha256]="$2"; shift 2 ;;
    -h|--help) sed -n 2,33p "$0"; exit 0 ;;
    -*) echo "box-run: unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
VM="${1:-tb-gpu-sim}"; ZONE="${2:-asia-east1-a}"
cd "$ROOT"
br() { env PYTHONPATH=libs:services:. "$PY" -m tools.box_run "$@"; }
if [ "$ESTIMATE" = 1 ]; then br estimate --steps "${STEPS:-build start g6 g9 g10}"; exit 0; fi

export GC_DRY="$DRY"
# shellcheck source=deploy/gcp/gcloud-auth.sh
. "$ROOT/deploy/gcp/gcloud-auth.sh"
eval "$(br settings)"   # KEY_SECRET, SIGNER_SA, PROVISIONING (tb_common.config.DECLARED)
BUCKET="${TB_BUCKET:-}"
[ -n "$BUCKET" ] || { echo "box-run: set TB_BUCKET=gs://<bucket> (results, the bundle and the power-cycle request go through it)" >&2; exit 2; }
if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG and activate the service account in it}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"*) echo "CLOUDSDK_CONFIG must be private" >&2; exit 2 ;; esac
fi
gc_start || exit 5
RUN_ID="${COLLECT:-${RESUME:-${TB_RUN_ID:-box-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)}}}"
OUT="${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RUN_ID}"
mkdir -p "$OUT"; umask 077
OBJ="$BUCKET/boxruns/$RUN_ID"

status() { if [ "$DRY" = 1 ]; then echo TERMINATED; else gc compute instances describe "$VM" --zone "$ZONE" --format='value(status)' || echo unknown; fi; }
project() { if [ "$DRY" = 1 ]; then echo "<project>"; else gcloud config get-value project 2>/dev/null; fi; }
wait_terminated() {  # the stop is checked, not assumed: TERMINATED within TB_SETTLE_S (240 s: a GPU VM's stop takes minutes)
  local end=$((SECONDS + ${TB_SETTLE_S:-240})) s
  while :; do
    s="$(status)"; [ "$s" = TERMINATED ] && { echo "VM $VM: TERMINATED"; return 0; }
    [ "$SECONDS" -lt "$end" ] || { echo "VM $VM: still $s after ${TB_SETTLE_S:-240} s: check it by hand" >&2; return 1; }
    sleep 15
  done
}
reset_vm() {  # the VM as it is kept: spot, the usual startup script, the default service account, no tb-* key
  local keys
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --provisioning-model=SPOT --instance-termination-action=STOP \
    --clear-max-run-duration || true
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file startup-script="$ROOT/deploy/gcp/gpu-sim-startup.sh" || true
  keys="$(cat "$OUT/metadata-keys" 2>/dev/null | tr ' ' ,)"
  [ -z "$keys" ] || gc compute instances remove-metadata "$VM" --zone "$ZONE" --keys "${keys/startup-script,/}" || true
  if [ -f "$OUT/signer" ]; then   # the build ran as the signer: back to the default compute account
    gc compute instances set-service-account "$VM" --zone "$ZONE" --service-account "$(cat "$OUT/default-sa")" --scopes cloud-platform || true
    rm -f "$OUT/signer"
  fi
  [ "$DRY" = 1 ] || gc compute instances describe "$VM" --zone "$ZONE" --format='value(status,serviceAccounts[0].email)' || true
}
stop_vm() { gc compute instances stop "$VM" --zone "$ZONE" || true; [ "$DRY" = 1 ] || wait_terminated; reset_vm; }
fetch() {  # results.tgz from the bucket into $OUT, the report; returns 1 when there is none yet
  gc storage cp "$OBJ/results.tgz" "$OUT/results.tgz.new" >/dev/null 2>&1 || { [ "$DRY" = 1 ] && return 0; echo "no results.tgz in $OBJ yet"; return 1; }
  [ "$DRY" = 1 ] && return 0
  tar -tzf "$OUT/results.tgz.new" >/dev/null 2>&1 || { echo "results.tgz came incomplete"; return 1; }
  mv -f "$OUT/results.tgz.new" "$OUT/results.tgz"
  br results "$OUT/results.tgz" --out "$OUT" > /dev/null && echo "report: $OUT/report.md"
}
ended() { [ -s "$OUT/summary.json" ] && "$PY" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ended") else 1)' "$OUT/summary.json"; }
power_cycle_asked() { [ "$DRY" = 0 ] && gc storage ls "$OBJ/POWER-CYCLE-REQUEST" >/dev/null 2>&1; }
power_cycle() {  # G-9: stop (checked), the request removed, start; the VM's next boot goes on from there
  echo "the VM asked for its power cycle (G-9): stopping it"
  gc compute instances stop "$VM" --zone "$ZONE"; wait_terminated || return 1
  gc storage rm "$OBJ/POWER-CYCLE-REQUEST" >/dev/null || true
  gc compute instances start "$VM" --zone "$ZONE"
  echo "started again: the run goes on in the next boot"
}
one_look() {  # one look: results, a power cycle asked for, the state; 0 = the run is over and the VM is off
  local s
  fetch || true
  if power_cycle_asked; then power_cycle; return 1; fi
  s="$(status)"
  if [ "$s" = TERMINATED ]; then
    if ended; then echo "run $RUN_ID ended: $(sed -n 's/.*"ended": "\([^"]*\)".*/\1/p' "$OUT/summary.json" | head -1)"; reset_vm; return 0; fi
    echo "VM $VM is TERMINATED before the run ended (a pre-emption, or the cloud cap): --resume $RUN_ID goes on (finished steps kept), --stop puts it back"
    return 0
  fi
  echo "VM $VM is $s; run $RUN_ID goes on"
  return 1
}

if [ "$STOP" = 1 ]; then stop_vm; [ -z "$COLLECT" ] || fetch || true; exit 0; fi
if [ -n "$COLLECT" ]; then
  if [ "$FOLLOW" = 1 ]; then until one_look; do sleep 60; done; else one_look || true; fi
  exit 0
fi
if [ -n "$RESUME" ]; then
  [ "$(status)" = TERMINATED ] || { echo "VM $VM is not TERMINATED" >&2; exit 2; }
  cap="$(cat "$OUT/cap-hours" 2>/dev/null || echo 4)"
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${cap}h" --instance-termination-action=STOP
  gc compute instances start "$VM" --zone "$ZONE"
  [ "$WAIT" = 0 ] && exit 0
  until one_look; do sleep 60; done; exit 0
fi

# ---------------------------------------------------------------- a launch
[ -n "$STEPS" ] || { echo "box-run: --steps build | start,g6,g9,g10 (see --help)" >&2; exit 2; }
case " $STEPS " in *" build "*) [ "$STEPS" = build ] || { echo "box-run: build is its own launch (another service account)" >&2; exit 2; } ;; esac
[ "$(status)" = TERMINATED ] || { echo "VM $VM is $(status), not TERMINATED: one run at a time" >&2; exit 2; }
RID="${V[tb-release-id]:-}"
V[tb-run-id]="$RUN_ID"; V[tb-bucket]="$BUCKET"; V[tb-vendor-pub]="${V[tb-vendor-pub]:-$BUCKET/r2/keys/vendor_ed25519.pub}"
if [ "$STEPS" = build ]; then
  V[tb-src]="${V[tb-src]:-$BUCKET/r2/$RID/src.bundle}"; V[tb-out]="${V[tb-out]:-$BUCKET/r2/$RID}"
  V[tb-vendor-key-secret]="$KEY_SECRET"
else
  V[tb-bundle]="${V[tb-bundle]:-$BUCKET/r2/$RID/trialbox-$RID.tar}"
  if [ -z "${V[tb-bundle-sha256]:-}" ] && [ "$DRY" = 0 ]; then   # the build's own .sha256 beside the bundle
    V[tb-bundle-sha256]="$(gc storage cat "${V[tb-bundle]}.sha256" 2>/dev/null | cut -d' ' -f1 || true)"
  fi
  [ "$DRY" = 1 ] && V[tb-bundle-sha256]="${V[tb-bundle-sha256]:-<sha256 from ${V[tb-bundle]}.sha256>}"
  V[tb-answers-secret]="${V[tb-answers-secret]:-tb-r2-answers}"; V[tb-answers-version]="${V[tb-answers-version]:-1}"
fi
sets=(); for k in "${!V[@]}"; do sets+=(--set "$k=${V[$k]}"); done
rm -rf "$OUT/md"
br metadata --steps "$STEPS" --out "$OUT/md" "${sets[@]}" > "$OUT/metadata-keys" || exit 2
CAP=$(br estimate --steps "$STEPS" --json | "$PY" -c 'import json,sys; print(sum(l["cap_hours"] for l in json.load(sys.stdin)["launches"]))')
echo "$CAP" > "$OUT/cap-hours"
br estimate --steps "$STEPS"
FILES="startup-script=$ROOT/deploy/gcp/box-install-run.sh,tb-helper=$ROOT/deploy/gcp/box_vm.py"
for k in $(cat "$OUT/metadata-keys"); do FILES="$FILES,$k=$OUT/md/$k"; done
echo "startup-script tb-helper $(cat "$OUT/metadata-keys")" > "$OUT/metadata-keys"
if [ "$STEPS" = build ]; then
  if [ "$DRY" = 0 ]; then
    gc compute instances describe "$VM" --zone "$ZONE" --format='value(serviceAccounts[0].email)' > "$OUT/default-sa"
  else echo "<project-number>-compute@developer.gserviceaccount.com" > "$OUT/default-sa"; fi
  gc compute instances set-service-account "$VM" --zone "$ZONE" \
    --service-account "$SIGNER_SA@$(project).iam.gserviceaccount.com" --scopes cloud-platform
  touch "$OUT/signer"
fi
trap 'echo "box-run: the launch did not finish: stopping the VM"; stop_vm' ERR
gc compute instances set-scheduling "$VM" --zone "$ZONE" --provisioning-model="$PROVISIONING" \
  --max-run-duration="${CAP}h" --instance-termination-action=STOP
gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file "$FILES"
gc compute instances start "$VM" --zone "$ZONE"
trap - ERR
[ "$DRY" = 0 ] || echo "(dry run: the commands above were printed, nothing was changed or started)"
echo "run $RUN_ID started on $VM ($ZONE), $PROVISIONING, cloud cap ${CAP} h; results: $OBJ/results.tgz"
echo "later: $0 --collect $RUN_ID [--follow]; $0 --stop $RUN_ID"
[ "$WAIT" = 0 ] || [ "$DRY" = 1 ] && exit 0
until one_look; do sleep 60; done
