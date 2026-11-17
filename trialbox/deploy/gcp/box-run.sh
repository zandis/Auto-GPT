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
#   deploy/gcp/box-run.sh --mode validation --steps build --release-id val-<commit12> --release-seq 1 --commit <sha>
#       [--dry-run] [--no-wait]       # the same build signed with a THROWAWAY key made on the VM: not a release
#   deploy/gcp/box-run.sh --mode validation --steps start,acc --release-id val-<commit12> [--only jmed,tcga:100] \
#       [--answers-version <N>] [--qualify-evidence "..."] [--dry-run] [--no-wait]   # a VALIDATION box, then Run A
#   deploy/gcp/box-run.sh --steps acc --only trec [--mode validation]   # one more set on the box already installed
#   deploy/gcp/box-run.sh --estimate --mode validation --steps start,acc [--only ...]   # free: low and high, sources
#   A validation launch with acc first asks this tree (tools/box_run.py validation-check, free) whether a VALIDATION
#   box can route the run's calls; it refuses while the check names a blocker (--even-if-blocked launches anyway:
#   the box itself stops at 52-acc-routes with the reason, after the install, so the install is paid for nothing).
#   deploy/gcp/box-run.sh --collect <run id> [--follow]   # results so far; a power cycle G-9 asked for; the report;
#                                                         # each finished accuracy set fetched and scored HERE
#   deploy/gcp/box-run.sh --resume <run id> [--only ...]   # start it again (finished steps kept): after a pre-emption,
#       or after a STOP once this script or the helper was fixed: the VM gets this tree's startup script and helper
#       and a new tb-retry, which clears the run's end and the stopped step (its part kept in logs/), so that step
#       runs again; lane G's accuracy tools are uploaded again and re-fetched; --only replaces the sets still to run
#   deploy/gcp/box-run.sh --resume <run id> --acc-deadline "set:SECONDS ..."   # D-1129: a set that ended on its own
#       budget with protocols cut runs those protocols only, in a new attempt with this budget (the old one is
#       spent); every finished protocol is kept and never screened again; one attempt record (answers, logs, score).
#       Without a budget for it, it stays done. A set with nothing cut stays done. --redo keeps its meaning.
#   deploy/gcp/box-run.sh --preflight --resume <run id> [--acc-deadline ...] [--redo ...]   # free, no gcloud call:
#       what that resume would take up, from the run's last --collect in .cache/box-run/<run id> (tools/box_run.py
#       resume-plan); a run whose state is only in the bucket is said so (the VM says it first thing on its boot)
#   deploy/gcp/box-run.sh --stop [<run id>]               # stop, check TERMINATED, put the VM back as it is kept
#   --acc-protocols "set:RS1,RS2 ...": only these protocols of a set. Checked HERE before anything starts (D1): every
#       id must be one of the set's on the box, whose prefix is the set's letter and --acc-rs-tag (tag m2 makes
#       TCGA-BRCA Gm2TCGA-BRCA). Free listing: tools/box_run.py acc-ids --only SETS --rs-tag T [--protocols ...]
#       A set whose ids are not known locally (sigir, trec2023) takes no filter: it could not be checked (D-1125).
#   --acc-streams "set:n ...": protocols of a set in flight at once. Default (D7): 3 for a compile-bound set (sigir,
#       trec, trec2023, tfda, jrct, chia: tools/box_run.py compile_bound), 1 for the others; the report says how many
#       were in flight. --resume keeps --acc-rs-tag from the launch unless it is given again (D3).
#   --src-bundle FILE (build, dev; needed by both): the release commit's git bundle, proved here (cloned into a
#       temporary folder as the VM clones it and the commit checked out: tools/box_run.py src-bundle --check) and only
#       then uploaded to r2/<ID>/src.bundle (D8); the bucket's own is never taken unproved. Make one with:
#       tools/box_run.py src-bundle --commit <full sha> --out FILE (refused in a shallow checkout).
#   The owner's live session (D-1123; D-1130 the door, D-1131 the egress, D-1132 the step, D-1133 the links). Nothing
#   from a session is evidence. Free first: --estimate, then --preflight (prints the rules it would make), then:
#   deploy/gcp/box-run.sh --mode validation --steps dev,session --release-id dev-<commit12> --commit <sha> \
#       --src-bundle FILE --session-allow <the owner's range, /24 or narrower> [--session-env dev|validation] \
#       [--session-hours 1-3] [--session-people "name:role+role,..."] [--session-synth N] --no-wait
#     --session-allow   required: tcp:443 from these ranges only (never `any`, 0.0.0.0/0 or broader than /24)
#     --session-env     dev (the integrator's ruling, the default) or validation; the launch is refused while this
#                       tree's routing policy would not route the session's calls to the box's own pair in it, or its
#                       egress table would open a way out (tools/box_run.py session-check, free)
#   deploy/gcp/box-run.sh --session-status <run id> [--boot-id ID]   # the VM, the door's rules checked, and the
#                                                         # session's ready line of THIS boot only (D-1120's rules)
#   deploy/gcp/box-run.sh --links <run id>                # ONCE, after TB-SESSION-READY: the door checked again, then
#                                                         # the one-time links printed once and the object deleted,
#                                                         # with the boot id, the certificate's SHA-256, the stop time
#   --stop and the end of a collect also remove the session's tag from the VM and its two firewall rules.
#   --preflight (free; no gcloud call, no TB_BUCKET needed): the launch as given, up to the point where it would
#       upload or start anything, with every free check (tools/box_run.py preflight: the filter, the tag, the streams,
#       the budgets, the full commit, the source bundle proved, the metadata; and the validation-check). Exit 0: the
#       paid launch with the same options passes the same checks. A launch runs the same checks first.
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
DRY=0; WAIT=1; FOLLOW=0; ESTIMATE=0; STOP=0; PREFLIGHT=0; COLLECT=""; RESUME=""; STEPS=""; MODE=production; ONLY=""; ANYWAY=0
SRC_BUNDLE=""
SESSION_ALLOW_RAW=""; SESSION_ENV_RAW=dev; SESSION_HOURS_RAW=3; SESSION_PEOPLE_RAW=""; SESSION_SYNTH_RAW=""
LINKS=""; SSTATUS=""; BOOT_ID=""
declare -A V=()
while [ $# -gt 0 ]; do
  case "$1" in
    --estimate) ESTIMATE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --preflight) PREFLIGHT=1; DRY=1; WAIT=0; shift ;;
    --no-wait) WAIT=0; shift ;;
    --follow) FOLLOW=1; shift ;;
    --stop) STOP=1; shift; case "${1:-}" in ""|-*) ;; *) COLLECT="$1"; shift ;; esac ;;
    --collect) COLLECT="$2"; shift 2 ;;
    --resume) RESUME="$2"; shift 2 ;;
    --steps) STEPS="${2//,/ }"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --even-if-blocked) ANYWAY=1; shift ;;
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
    --acc-tripwire) V[tb-acc-tripwire-setting]="$2"; shift 2 ;;
    --embed-list) V[tb-embed-list]="$2"; shift 2 ;;
    --probe) V[tb-probe]=1; shift ;;
    --direct) V[tb-direct]=1; shift ;;
    --qualify-args) V[tb-qualify-args]="$2"; shift 2 ;;
    --qualify-timebox) V[tb-qualify-timebox]="$2"; shift 2 ;;   # the owner's probe: qualify ended after N seconds
    --acc-deadline) V[tb-acc-deadline]="$2"; shift 2 ;;         # each set's time budget, seconds (a probe)
    --acc-min-start) V[tb-acc-min-start]="$2"; shift 2 ;;       # D4: seconds of a set's budget a protocol needs to start (600)
    --progress-seconds) V[tb-progress-seconds]="$2"; shift 2 ;;
    --acc-protocols) V[tb-acc-protocols]="$2"; shift 2 ;;   # "set:RS1,RS2 ...": only these protocols of the set
    --site-env) V[tb-site-env]="$2"; shift 2 ;;
    --acc-rs-tag) V[tb-acc-rs-tag]="$2"; shift 2 ;;
    --skip) V[tb-skip]="${2//,/ }"; shift 2 ;;
    --acc-streams) V[tb-acc-streams]="$2"; shift 2 ;;
    --serving) V[tb-serving]="$2"; shift 2 ;;               # shipped | tuned (the owner's exception, this box only)       # "set:n ...": protocols in flight at once per set              # steps left out of the launch, each said (never a pass)         # a second run on one box: new ruleset ids (F29)             # "TB_MEM_EMBED=16g ...": the site's deploy/.env limits
    --redo) V[tb-redo]="${2//,/ }"; shift 2 ;;   # with --resume: these steps run again (an acc set from no work)   # qualify's own size options, e.g. "--items 60 --repeat-items 40"   # 02: the installed tree brought up with the product's tools, no install.sh   # read the VM's (and after the install the box's) facts, then stop
    --src-bundle) SRC_BUNDLE="$2"; shift 2 ;;
    --session-allow) SESSION_ALLOW_RAW="$2"; shift 2 ;;     # D-1130: tcp:443 from these ranges only
    --session-env) SESSION_ENV_RAW="$2"; shift 2 ;;         # D-1132: dev (the ruling) | validation
    --session-hours) SESSION_HOURS_RAW="$2"; shift 2 ;;     # 1 to 3: the owner's sitting
    --session-people) SESSION_PEOPLE_RAW="$2"; shift 2 ;;   # name:role+role,... (DEV) or name:role,... (VALIDATION)
    --session-synth) SESSION_SYNTH_RAW="$2"; shift 2 ;;     # the synthetic hospital's patients
    --links) LINKS="$2"; shift 2 ;;                         # D-1133: the session's one-time links, once
    --session-status) SSTATUS="$2"; shift 2 ;;              # D-1132: this boot's ready line
    --boot-id) BOOT_ID="$2"; shift 2 ;;                     # with --session-status: that boot's lines only
    --bundle) V[tb-bundle]="$2"; shift 2 ;;
    --bundle-sha256) V[tb-bundle-sha256]="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    -*) echo "box-run: unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
VM="${1:-tb-gpu-sim}"; ZONE="${2:-asia-east1-a}"
cd "$ROOT"
br() { env PYTHONPATH=libs:services:. "$PY" -m tools.box_run "$@"; }
sv() { "$PY" "$ROOT/deploy/gcp/session_vm.py" "$@"; }   # the session's free checks (standard library)
SESSION=0; case " $STEPS " in *" session "*) SESSION=1 ;; esac
# a session's groups in the VM's own order (box-run's dev route compares the string; tools/box_run.py session_values
# refuses any other set of groups)
[ "$SESSION" = 0 ] || [ "$(printf '%s\n' $STEPS | sort | paste -sd' ')" != "dev session" ] || STEPS="dev session"
SESSION_HOURS=""
if [ -n "$BOOT_ID" ]; then
  [ -n "$SSTATUS" ] || { echo "box-run: --boot-id is for --session-status only" >&2; exit 2; }
  [[ "$BOOT_ID" =~ ^[0-9a-f]{16}$ ]] || { echo "box-run: --boot-id takes the 16 hex digits --links printed" >&2; exit 2; }
fi
if [ "$SESSION" = 1 ]; then
  if [ "$ESTIMATE" -eq 1 ]; then   # free: the hours alone (the ranges are the launch's)
    SESSION_HOURS="$SESSION_HOURS_RAW"
  else
    SVS="$(sv shell --allow "$SESSION_ALLOW_RAW" --env "$SESSION_ENV_RAW" --hours "$SESSION_HOURS_RAW" \
      --people "$SESSION_PEOPLE_RAW" --synth "$SESSION_SYNTH_RAW")" \
      || { echo "box-run: refused (no VM started): the session's options (above)" >&2; exit 2; }
    SESSION_ALLOW=""; SESSION_ENV=""; SESSION_PEOPLE=""; SESSION_SYNTH=""; SESSION_TAG=""; SESSION_ALLOW_RULE=""
    SESSION_DENY_RULE=""; SESSION_ALLOW_PRIORITY=""; SESSION_DENY_PRIORITY=""
    eval "$SVS"   # shlex-quoted assignments of the names above, from session_vm.py only
    V[tb-session-env]="$SESSION_ENV"; V[tb-session-minutes]=$((SESSION_HOURS * 60)); V[tb-session-people]="$SESSION_PEOPLE"
    V[tb-session-synth]="$SESSION_SYNTH"
  fi
fi
ses_hours() { [ -z "$SESSION_HOURS" ] || printf -- '--session-hours\n%s\n' "$SESSION_HOURS"; }
scheck() {  # D-1131, D-1132: would a box in the session's environment route its calls to its own pair only, and
  # let no text out? (free, local: this tree's routing policy and egress table)
  [ "$SESSION" = 1 ] || return 0
  local env="${SESSION_ENV:-$(printf '%s' "$SESSION_ENV_RAW" | tr '[:lower:]' '[:upper:]')}"
  if br session-check --env "$env" > "${1:-/dev/null}"; then
    echo "session-check: a box in $env routes the session's calls to its own served pair only and lets no text out"; return 0
  fi
  echo "session-check: a box in $env on this tree would not serve the session as ruled (tools/box_run.py session-check;" \
    "the lines above): a product change, not built around here (D-1123 section 3 item 4)" >&2
  return 1
}
case "$MODE" in production|validation) ;; *) echo "box-run: --mode production | validation" >&2; exit 2 ;; esac
if [ "$PREFLIGHT" = 1 ] && { [ -n "$COLLECT$LINKS$SSTATUS" ] || [ "$STOP" = 1 ]; }; then
  echo "box-run: --preflight checks a launch (--steps ...) or a resume (--resume), not a collect, a stop, --links or --session-status" >&2; exit 2
fi
if [ "$PREFLIGHT" = 1 ] && [ -n "$RESUME" ]; then   # D-1129: free, local: what the resume would take up
  # D-1132: a session is never resumed, not even in a preflight's plan
  if grep -qw session "${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RESUME}/md/tb-steps" 2>/dev/null \
     || [ -f "${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RESUME}/session" ]; then
    echo "box-run: refused: run $RESUME is a session; a session is never resumed: more time is a new launch (D-1123 4.4)" >&2; exit 2
  fi
  br resume-plan "${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RESUME}" --deadline "${V[tb-acc-deadline]:-}" \
    --redo "${V[tb-redo]:-}" > /dev/null || { echo "box-run: refused (no VM started): the resume's options (above)" >&2; exit 6; }
  echo "preflight: the resume plan above (nothing was read from the bucket, uploaded or started)"
  exit 0
fi
vcheck() {  # validation mode with acc: can a VALIDATION box route the run's calls on this tree? (free, local)
  case " $STEPS " in *" acc "*) [ "$MODE" = validation ] || return 0 ;; *) return 0 ;; esac
  if br validation-check > "${1:-/dev/stdout}"; then echo "validation-check: a VALIDATION box can route the run's calls"; return 0; fi
  echo "validation-check: a VALIDATION box on this tree would refuse the run's calls (tools/box_run.py validation-check):" >&2
  "$PY" -c 'import json,sys; [print("  -", b) for b in json.load(open(sys.argv[1]))["blockers"]]' "${1:-/dev/null}" >&2 2>/dev/null || true
  return 1
}
# D1 (P1b review): a protocol filter is checked against the ids the sets get on the box before anything is started
# or uploaded (free, local); a filter that matches no protocol, or names an id the set lacks, refuses the launch
if [ -n "${V[tb-acc-protocols]:-}" ]; then
  if [ -n "$RESUME" ] && [ -z "$ONLY" ]; then acc_only="$(cat "${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RESUME}/md/tb-acc-sets" 2>/dev/null | tr ' ' ,)"
  else acc_only="$ONLY"; fi
  acc_tag="${V[tb-acc-rs-tag]:-}"
  [ -n "$acc_tag" ] || [ -z "$RESUME" ] || acc_tag="$(cat "${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RESUME}/md/tb-acc-rs-tag" 2>/dev/null || true)"
  br acc-ids --only "$acc_only" --rs-tag "$acc_tag" --protocols "${V[tb-acc-protocols]}" > /dev/null \
    || { echo "box-run: refused (no VM started): --acc-protocols matches no protocol of its set (see above; tools/box_run.py acc-ids lists the ids)" >&2; exit 2; }
fi
if [ "$ESTIMATE" = 1 ]; then
  mapfile -t sh_ < <(ses_hours)
  br estimate --steps "${STEPS:-build start g6 g9 g10}" --mode "$MODE" --only "$ONLY" ${sh_[@]+"${sh_[@]}"}
  vcheck "$(mktemp)" || true
  scheck || true
  exit 0
fi

export GC_DRY="$DRY"
# shellcheck source=deploy/gcp/gcloud-auth.sh
. "$ROOT/deploy/gcp/gcloud-auth.sh"
eval "$(br settings)"   # KEY_SECRET, SIGNER_SA, PROVISIONING (tb_common.config.DECLARED)
BUCKET="${TB_BUCKET:-}"
[ "$PREFLIGHT" = 0 ] || BUCKET="${BUCKET:-gs://<TB_BUCKET>}"   # nothing is read from it or written to it
[ -n "$BUCKET" ] || { echo "box-run: set TB_BUCKET=gs://<bucket> (results, the bundle and the power-cycle request go through it)" >&2; exit 2; }
if [ "$DRY" = 0 ]; then
  : "${CLOUDSDK_CONFIG:?set a private CLOUDSDK_CONFIG and activate the service account in it}"
  case "$CLOUDSDK_CONFIG" in "$HOME/.config/gcloud"*) echo "CLOUDSDK_CONFIG must be private" >&2; exit 2 ;; esac
fi
# a run id names a folder here and a path in the bucket: the VM's own form only (its RUN_ID keeps letters, digits,
# '.', '_' and '-'), never a wildcard or a parent folder; checked before any cloud call
for _rid in "$COLLECT" "$RESUME" "$LINKS" "$SSTATUS" "${TB_RUN_ID:-}"; do
  [ -z "$_rid" ] || { [[ "$_rid" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] && [[ "$_rid" != *..* ]]; } \
    || { echo "box-run: '$_rid' is not a run id (letters, digits, '.', '_', '-'; as box-run.sh printed it)" >&2; exit 2; }
done
gc_start || exit 5
RUN_ID="${COLLECT:-${RESUME:-${LINKS:-${SSTATUS:-${TB_RUN_ID:-box-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)}}}}}"
OUT="${TB_BOXRUN_DIR:-$ROOT/.cache/box-run/$RUN_ID}"
[ "$PREFLIGHT" = 0 ] || [ -n "${TB_BOXRUN_DIR:-}" ] || OUT="$(mktemp -d)"   # a preflight leaves no run folder
mkdir -p "$OUT"; umask 077
OBJ="$BUCKET/boxruns/$RUN_ID"
HANDOFF="$BUCKET/session/$RUN_ID"   # D-1133: the one private object of the links (the VM writes, --links reads once)

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
  keys="$(cat "$OUT/metadata-keys" 2>/dev/null | tr ' ' , || true)"   # none: a --stop with no run folder here
  [ -z "$keys" ] || gc compute instances remove-metadata "$VM" --zone "$ZONE" --keys "${keys/startup-script,/}" || true
  if [ -f "$OUT/signer" ]; then   # the build ran as the signer: back to the default compute account
    gc compute instances set-service-account "$VM" --zone "$ZONE" --service-account "$(cat "$OUT/default-sa")" --scopes cloud-platform || true
    rm -f "$OUT/signer"
  fi
  session_door_down
  [ "$DRY" = 1 ] || gc compute instances describe "$VM" --zone "$ZONE" --format='value(status,serviceAccounts[0].email)' || true
}
# ---------------------------------------------------------------- the session's door (D-1130), as demo-vm.sh `up`
S_TAG=tb-session; S_ALLOW=tb-session-https; S_DENY=tb-session-deny   # session_vm.py TAG, ALLOW_RULE, DENY_RULE
rule_not_found() {  # $1 the rule, $2 gcloud's error: it says THIS rule is not found (round 4's e: a wrong project's or
  # another resource's "not found" is an error, never "the rule is gone")
  grep -qE "/firewalls/$1' was not found" "$2"
}
rule_exists() {  # 0 the rule is there, 1 gcloud says it is not found, 2 it cannot be read (round 3's finding 2: an
  # error is never "not there"; each caller fails closed on 2). In a dry run nothing exists yet (the plan is printed)
  if [ "$DRY" = 1 ]; then echo "+ gcloud compute firewall-rules describe $1 --format=value(name)   # exists?"; return 1; fi
  local err rc=0; err="$(mktemp)"
  gc compute firewall-rules describe "$1" --format='value(name)' >/dev/null 2>"$err" || rc=$?
  if [ "$rc" = 0 ]; then rm -f "$err"; return 0; fi
  if rule_not_found "$1" "$err"; then rm -f "$err"; return 1; fi
  echo "box-run: the firewall rule $1 cannot be read (not \"not found\": $(grep -v '^ *$' "$err" | head -n 1 | cut -c1-160))" >&2
  rm -f "$err"; return 2
}
rule_maybe() { local rc=0; rule_exists "$1" || rc=$?; [ "$rc" != 1 ]; }   # there, or not known not to be
rule_gone() { local rc=0; rule_exists "$1" || rc=$?; [ "$rc" = 1 ]; }      # gcloud says: not found
vm_network() {
  if [ "$DRY" = 1 ]; then echo default; return 0; fi
  basename "$(gc compute instances describe "$VM" --zone "$ZONE" --format='value(networkInterfaces[0].network)')"
}
session_door() {  # a deny-all on the session's tag, the one allow (tcp:443 from the owner's ranges), the tag on the VM
  local net; net="$(vm_network)" || return 1
  [ -n "$net" ] || { echo "box-run: the VM's network cannot be read" >&2; return 1; }
  # both rules are deleted and made again, never kept or updated: an update would keep any source tag or service
  # account someone added to the allow (the review's finding 7), or a destination that narrows the deny (the
  # re-review's B). The deny names its run: the driver takes it away only once that run's CLOSED marker exists.
  if rule_maybe "$S_ALLOW"; then gc compute firewall-rules delete "$S_ALLOW" --quiet || return 1; fi
  if rule_maybe "$S_DENY"; then gc compute firewall-rules delete "$S_DENY" --quiet || return 1; fi
  gc compute firewall-rules create "$S_DENY" --network "$net" --direction INGRESS --action DENY \
    --rules=all --source-ranges=0.0.0.0/0 --target-tags "$S_TAG" --priority "$SESSION_DENY_PRIORITY" \
    --description="TrialBox session (D-1130) run=$RUN_ID: nothing but its tcp:443 rule reaches the VM (not SSH, not an old door)" || return 1
  gc compute firewall-rules create "$S_ALLOW" --network "$net" --direction INGRESS --action ALLOW --rules=tcp:443 \
    --source-ranges="$SESSION_ALLOW" --target-tags "$S_TAG" --priority "$SESSION_ALLOW_PRIORITY" \
    --description="TrialBox session (D-1130): https from the owner's own ranges only" || return 1
  gc compute instances add-tags "$VM" --zone "$ZONE" --tags "$S_TAG" || return 1
  printf '%s\n' "$SESSION_ALLOW" > "$OUT/session"   # the ranges, for --links and --session-status
}
session_rules_check() {  # D-1130: only tcp:443 from the owner's ranges reaches the VM (every rule, every tag of the VM)
  local rules tags net rc=0 ranges
  ranges="${SESSION_ALLOW:-${SESSION_ALLOW_RAW:-$(cat "$OUT/session" 2>/dev/null)}}"
  [ -n "$ranges" ] || { echo "box-run: no session ranges for $RUN_ID here (--session-allow RANGES gives them)" >&2; return 1; }
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute firewall-rules list --format=json   # only tcp:443 from $ranges may reach the VM"
    echo "+ gcloud compute instances describe $VM --zone $ZONE --format=json   # its tags, one interface, no IPv6"
    echo "+ gcloud compute instances network-interfaces get-effective-firewalls $VM --zone $ZONE --network-interface nic0 --format=json   # firewall policies"
    return 0
  fi
  local inst eff
  net="$(vm_network)"; rules="$(mktemp)"; inst="$(mktemp)"; eff="$(mktemp)"
  { gc compute firewall-rules list --filter="network~/$net\$" --format=json > "$rules" \
    && gc compute instances describe "$VM" --zone "$ZONE" --format=json > "$inst" \
    && gc compute instances network-interfaces get-effective-firewalls "$VM" --zone "$ZONE" --network-interface nic0 --format=json > "$eff"; } \
    || { rm -f "$rules" "$inst" "$eff"; echo "box-run: the VM's rules, interfaces or firewall policies cannot be read" >&2; return 1; }
  sv rules-check "$net" "-" "$ranges" --instance "$inst" --effective "$eff" < "$rules" > "$OUT/session-rules.json" || rc=$?
  rm -f "$rules" "$inst" "$eff"
  "$PY" -c 'import json,sys
d = json.load(open(sys.argv[1]))
print("door: reaches the VM:", d["reaches_the_vm"] or "NOT PROVED")
for r in d["other_rules_that_apply_to_the_vm"]: print("  %s: %s" % (r["rule"], r["verdict"]))
for p in d["problems"]: print("  PROBLEM:", p)' "$OUT/session-rules.json" 2>/dev/null || true
  return "$rc"
}
vm_has_tag() {
  [ "$DRY" = 0 ] || return 1
  gc compute instances describe "$VM" --zone "$ZONE" --format='value(tags.items)' 2>/dev/null | tr ';,' '\n\n' | grep -qx "$S_TAG"
}
bucket_private() {  # D-1123 section 6: no allUsers/allAuthenticatedUsers, no object ACL can apply, no old versions
  local b="${BUCKET#gs://}"; b="gs://${b%%/*}"
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud storage buckets describe $b --format=json   # uniform access or public access prevention, versioning off"
    echo "+ gcloud storage buckets get-iam-policy $b --format=json   # no allUsers, no allAuthenticatedUsers"
    return 0
  fi
  local d p rc=0; d="$(mktemp)"; p="$(mktemp)"
  { gc storage buckets describe "$b" --format=json > "$d" && gc storage buckets get-iam-policy "$b" --format=json > "$p"; } \
    || { rm -f "$d" "$p"; echo "box-run: the bucket's settings or IAM policy cannot be read" >&2; return 1; }
  sv bucket-check "$d" "$p" || rc=$?
  rm -f "$d" "$p"
  [ "$rc" = 0 ] || { echo "box-run: the bucket $b is not private enough for the links object (above; D-1133)" >&2; return 1; }
  echo "bucket: $b names no allUsers and no allAuthenticatedUsers, takes no object ACL, keeps no old version"
}
session_closed() {  # the VM writes CLOSED beside the links once a session's accounts are disabled (D-1132)
  run_closed "$RUN_ID"
}
session_run() { [ "$SESSION" = 1 ] || [ -f "$OUT/session" ] || grep -qw session "$OUT/md/tb-steps" 2>/dev/null; }
deny_run() {  # the run the session's deny was made for (its description: run=<id>): 0 the deny is there (the run
  # printed, nothing when it names none), 1 there is no deny, 2 it cannot be read (round 3's finding 2: fail closed)
  [ "$DRY" = 0 ] || return 1
  local err d rc=0; err="$(mktemp)"
  d="$(gc compute firewall-rules describe "$S_DENY" --format='value(description)' 2>"$err")" || rc=$?
  if [ "$rc" != 0 ]; then
    if rule_not_found "$S_DENY" "$err"; then rm -f "$err"; return 1; fi
    echo "box-run: the firewall rule $S_DENY cannot be read: it and the tag $S_TAG are kept" >&2; rm -f "$err"; return 2
  fi
  rm -f "$err"
  printf '%s\n' "$d" | sed -n 's/.*run=\([A-Za-z0-9][A-Za-z0-9._-]*\).*/\1/p' | head -n 1
}
run_closed() {  # the run's marker says "closed" (step 56 sets it to "open" before it opens any account)
  [ "$DRY" = 0 ] && gc storage cat "$BUCKET/session/$1/CLOSED" 2>/dev/null | head -n 1 | grep -q '^closed '
}
door_away() {  # $1 the run whose door it was: allow, tag, deny, and any links object of that run nobody read (dead
  # codes). Round 3's finding 5: the deny is never removed while the allow may exist: the allow is deleted and
  # confirmed gone (gcloud says "not found") first; else the deny-all and the tag stay (1)
  if [ "$DRY" = 0 ] && ! rule_gone "$S_ALLOW"; then
    gc compute firewall-rules delete "$S_ALLOW" --quiet || true
    rule_gone "$S_ALLOW" || {
      echo "session: $S_ALLOW cannot be confirmed gone: the deny-all $S_DENY and the tag $S_TAG stay on the VM" >&2; return 1; }
  fi
  gc compute instances remove-tags "$VM" --zone "$ZONE" --tags "$S_TAG" >/dev/null 2>&1 || true
  if [ "$DRY" = 1 ] || rule_maybe "$S_DENY"; then gc compute firewall-rules delete "$S_DENY" --quiet || true; fi
  [ -z "$1" ] || [ "$DRY" = 1 ] || gc storage rm --all-versions "$BUCKET/session/$1/links-*.txt" >/dev/null 2>&1 || true
}
session_door_down() {  # --stop and the end of a collect: the allow goes; the deny and the tag go once the accounts did
  local who="" drc=0
  if [ "$DRY" = 1 ]; then session_run || return 0
  else session_run || vm_has_tag || rule_maybe "$S_ALLOW" || rule_maybe "$S_DENY" || return 0; fi
  if [ "$DRY" = 1 ] || rule_maybe "$S_ALLOW"; then gc compute firewall-rules delete "$S_ALLOW" --quiet || true; fi
  # the re-review's D: the deny-all and the tag stay until the run the deny names has its CLOSED marker, whichever
  # run this is (an older run's --stop never takes away a later session's deny, nor an unclosed one's). Round 3's
  # finding 2: a deny that cannot be read is kept, with the tag (never taken for "no deny")
  who="$(deny_run)" || drc=$?
  if [ "$drc" = 2 ]; then
    echo "session: $S_DENY cannot be read: the deny-all and the tag $S_TAG stay on the VM; $0 --stop $RUN_ID again later"; return 0
  fi
  [ -n "$who" ] || ! session_run || who="$RUN_ID"
  if [ "$DRY" = 1 ] || { [ -n "$who" ] && run_closed "$who"; } || { [ -z "$who" ] && [ "$drc" = 1 ]; }; then
    door_away "$who" || return 0
    rm -f "$OUT/session"; return 0
  fi
  echo "session: accounts not confirmed closed (no $BUCKET/session/${who:-<the run the deny names>}/CLOSED): the deny-all and the tag $S_TAG stay on the VM;"
  echo "  the next boot of any run on this disk disables them and writes CLOSED; then: $0 --stop ${who:-$RUN_ID} again"
}
session_leftover() {  # the re-review's A and D: before any launch starts the VM, what an earlier session left
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute firewall-rules describe $S_ALLOW / $S_DENY   # an earlier session's: its allow deleted; its deny and tag kept until its CLOSED"
    return 0
  fi
  local rc=0 who drc=0
  rule_exists "$S_ALLOW" || rc=$?
  # round 3's finding 2: a rule that cannot be read is never taken for "not there": no VM starts (exit 7)
  [ "$rc" != 2 ] || { echo "box-run: $S_ALLOW cannot be read: no VM starts while an earlier session's allow may be there" >&2; return 1; }
  if [ "$rc" = 0 ]; then
    echo "session: an earlier session's $S_ALLOW is still there: deleted before the VM starts"
    gc compute firewall-rules delete "$S_ALLOW" --quiet || return 1
    rule_gone "$S_ALLOW" || { echo "box-run: $S_ALLOW is not confirmed gone: no VM starts" >&2; return 1; }
  fi
  who="$(deny_run)" || drc=$?
  [ "$drc" != 2 ] || { echo "box-run: $S_DENY cannot be read: no VM starts while an earlier session's door is not known" >&2; return 1; }
  if [ "$drc" = 0 ]; then
    if [ -n "$who" ] && run_closed "$who"; then
      echo "session: run $who's accounts are closed (CLOSED): its deny-all and the tag $S_TAG are taken away"
      door_away "$who" || return 1
      return 0
    fi
    if [ "$SESSION" = 1 ]; then
      echo "box-run: an earlier session (${who:-a run the deny does not name}) is not confirmed closed: no new session while" \
           "its accounts may be open (a launch that is no session closes them at its boot, then $0 --stop ${who:-<run>})" >&2
      return 1
    fi
    echo "session: an earlier session (${who:-a run the deny does not name}) is not confirmed closed: its deny-all and the" \
         "tag $S_TAG stay (nothing from outside reaches the VM); this run's boot closes its accounts before anything is served"
    return 0
  fi
  if vm_has_tag; then gc compute instances remove-tags "$VM" --zone "$ZONE" --tags "$S_TAG" >/dev/null 2>&1 || true; fi
}
session_door_abort() {  # the launch refused after its door was made (exit 7): the VM never started, nothing opened
  echo "session: the launch is refused: its door is taken away (no account of run $RUN_ID was ever opened)"
  door_away "$RUN_ID" || return 0
  rm -f "$OUT/session"
}
stop_vm() { gc compute instances stop "$VM" --zone "$ZONE" || true; [ "$DRY" = 1 ] || wait_terminated; reset_vm; }
fetch() {  # results.tgz from the bucket into $OUT, the report; returns 1 when there is none yet
  gc storage cp "$OBJ/results.tgz" "$OUT/results.tgz.new" >/dev/null 2>&1 || { [ "$DRY" = 1 ] && return 0; echo "no results.tgz in $OBJ yet"; return 1; }
  [ "$DRY" = 1 ] && return 0
  tar -tzf "$OUT/results.tgz.new" >/dev/null 2>&1 || { echo "results.tgz came incomplete"; return 1; }
  mv -f "$OUT/results.tgz.new" "$OUT/results.tgz"
  acc_fetch
  br results "$OUT/results.tgz" --out "$OUT" > /dev/null && echo "report: $OUT/report.md"
}
acc_fetch() {  # each accuracy set the VM uploaded as it finished: fetched, unpacked under $OUT/acc/<set>, scored here
  local o name gen
  [ "$DRY" = 0 ] || return 0
  for o in $(gc storage ls "$OBJ/acc/" 2>/dev/null | grep '\.tgz$'); do
    name="$(basename "$o" .tgz)"
    # F24 (2026-11-15): a set run again (--redo) uploads again: fetched again when the object's generation changed,
    # into a clean folder (the earlier answers never scored as the new ones)
    gen="$o#$(gc storage objects describe "$o" --format='value(generation)' 2>/dev/null)"
    [ "$(cat "$OUT/acc/$name/.fetched" 2>/dev/null)" = "$gen" ] && continue
    rm -rf "$OUT/acc/$name"; mkdir -p "$OUT/acc/$name"
    gc storage cp "$o" "$OUT/acc/$name.tgz" >/dev/null && tar -xzf "$OUT/acc/$name.tgz" -C "$OUT/acc/$name" \
      && echo "$gen" > "$OUT/acc/$name/.fetched" && echo "accuracy set $name fetched"
  done
  for o in $(gc storage ls "$OBJ/acc-partial/" 2>/dev/null | grep '\.tgz$'); do   # a set in flight, or cut: its partial
    name="$(basename "$o" .tgz)"
    [ -s "$OUT/acc/$name/.fetched" ] && continue
    mkdir -p "$OUT/acc/$name"
    gc storage cp "$o" "$OUT/acc/$name.partial.tgz" >/dev/null && tar -xzf "$OUT/acc/$name.partial.tgz" -C "$OUT/acc/$name" \
      && echo "accuracy set $name: partial fetched (not finished yet)"
  done
  [ -d "$OUT/acc" ] && br acc-score "$OUT" > "$OUT/acc-score.json" && echo "accuracy scores: $OUT/acc-score.json (and acc/<set>/score.json)"
  return 0
}
ended() { [ -s "$OUT/summary.json" ] && "$PY" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ended") else 1)' "$OUT/summary.json"; }
power_cycle_asked() { [ "$DRY" = 0 ] && gc storage ls "$OBJ/POWER-CYCLE-REQUEST" >/dev/null 2>&1; }
power_cycle() {  # G-9: stop (checked), the request removed, start; the VM's next boot goes on from there
  echo "the VM asked for its power cycle (G-9): stopping it"
  gc compute instances stop "$VM" --zone "$ZONE"; wait_terminated || return 1
  gc storage rm "$OBJ/POWER-CYCLE-REQUEST" >/dev/null || true
  # round 3's finding 3: every start of the VM by the driver first takes an earlier session's allow away (or refuses)
  if ! session_leftover; then
    echo "box-run: the VM is not started again: an earlier session's door (above); --stop $RUN_ID puts it back" >&2
    return 1
  fi
  gc compute instances start "$VM" --zone "$ZONE"
  echo "started again: the run goes on in the next boot"
}
one_look() {  # one look: results, a power cycle asked for, the state; 0 = the run is over and the VM is off
  local s
  fetch || true
  if session_run && ! session_closed; then echo "session: accounts not confirmed closed (no CLOSED marker yet)"; fi
  if power_cycle_asked; then power_cycle; return 1; fi
  s="$(status)"
  if [ "$s" = TERMINATED ] && session_run && rule_maybe "$S_ALLOW"; then   # the re-review's A: a session cut (a
    echo "session: the VM is TERMINATED: the session's allow is taken away now"   # pre-emption) leaves no open door
    gc compute firewall-rules delete "$S_ALLOW" --quiet || true
  fi
  if [ "$s" = TERMINATED ]; then
    if ended; then echo "run $RUN_ID ended: $(sed -n 's/.*"ended": "\([^"]*\)".*/\1/p' "$OUT/summary.json" | head -1)"; reset_vm; return 0; fi
    echo "VM $VM is TERMINATED before the run ended (a pre-emption, or the cloud cap): --resume $RUN_ID goes on (finished steps kept), --stop puts it back"
    return 0
  fi
  echo "VM $VM is $s; run $RUN_ID goes on"
  return 1
}

if [ "$STOP" = 1 ]; then stop_vm; [ -z "$COLLECT" ] || fetch || true; exit 0; fi
if [ -n "$SSTATUS" ]; then   # D-1132: the VM, the door, and the session's ready line of this boot only (D-1120)
  s="$(status)"; echo "VM $VM ($ZONE): $s"
  session_rules_check || echo "door: NOT proved (above): give no link" >&2
  if session_closed; then echo "session: accounts closed (CLOSED marker)"; else echo "session: accounts not confirmed closed"; fi
  if [ "$s" = RUNNING ]; then
    if [ "$DRY" = 1 ]; then
      echo "+ gcloud compute instances describe $VM --zone $ZONE --format=value(lastStartTimestamp)"
      echo "+ gcloud compute instances get-serial-port-output $VM --zone $ZONE --port 1 --start 0 --format=json   # then from each page's next"
      exit 0
    fi
    last_start="$(gc compute instances describe "$VM" --zone "$ZONE" --format='value(lastStartTimestamp)' 2>/dev/null || true)"
    pages="$(mktemp -d)"; pos=0
    for i in $(seq 1 64); do   # the whole buffer, page by page (demo-vm.sh serial_pages)
      f="$pages/page-$(printf '%03d' "$i")"
      gc compute instances get-serial-port-output "$VM" --zone "$ZONE" --port 1 --start "$pos" --format=json > "$f" 2>/dev/null || { rm -f "$f"; break; }
      nxt="$("$PY" "$ROOT/deploy/gcp/demo_vm.py" serial-next < "$f")" || break
      [ "$nxt" -gt "$pos" ] || break
      pos=$nxt
    done
    args=(); [ -z "$last_start" ] || args+=(--last-start "$last_start"); [ -z "$BOOT_ID" ] || args+=(--boot-id "$BOOT_ID")
    files=("$pages"/page-*); [ -e "${files[0]}" ] || files=()
    sv boot-state ${args[@]+"${args[@]}"} ${files[@]+"${files[@]}"}
    rm -rf "$pages"
  else
    echo "session: the VM is $s: no ready line is read (a line in the serial buffer is an earlier boot's)"
  fi
  exit 0
fi
if [ -n "$LINKS" ]; then   # D-1133: the door proved, then the links object printed once and deleted
  session_rules_check || { echo "box-run: no link is given: the door is not proved (above; D-1130)" >&2; exit 3; }
  bucket_private || { echo "box-run: no link is given: the bucket is not private (above)" >&2; exit 3; }
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud storage ls $HANDOFF/links-*.txt"
    echo "+ gcloud storage cat <the newest>   # the one-time links, printed once"
    echo "+ gcloud storage rm <each links-*.txt there>"
    exit 0
  fi
  objs="$(gc storage ls "$HANDOFF/links-*.txt" 2>/dev/null | sort || true)"
  [ -n "$objs" ] || { echo "box-run: no links under $HANDOFF: the VM writes them before TB-SESSION-READY, or they were read already (new links need a new launch)" >&2; exit 3; }
  newest="$(printf '%s\n' "$objs" | tail -n 1)"
  text="$(gc storage cat "$newest")"
  printf '%s\n' "$text"
  printf '%s\n' "$text" | sv links-meta | sed 's/^boot_id=/== boot id: /; s/^certificate_sha256=/== the box'"'"'s root certificate SHA-256 (compare it in the browser): /; s/^stop=/== the session closes at (UTC): /'
  for o in $objs; do gc storage rm --all-versions "$o" >/dev/null 2>&1 || echo "box-run: could not delete $o: delete it by hand" >&2; done
  echo "== deleted from the bucket. Give the owner his line in the integrator's own session; never on a PR, in a comment or a file."
  echo "== nothing from this session is evidence."
  exit 0
fi
if [ -n "$COLLECT" ]; then
  if [ "$FOLLOW" = 1 ]; then until one_look; do sleep 60; done; else one_look || true; fi
  exit 0
fi
if [ -n "$RESUME" ]; then
  # a session is never resumed (D-1123 4.4, D-1132): a resume would boot the session's steps without the door, the
  # bucket check or the session-check of a launch (the review's finding 2). More time is a new launch.
  if session_run; then
    echo "box-run: refused: run $RUN_ID is a session; a session is never resumed: more time is a new launch (D-1123 4.4)" >&2
    exit 2
  fi
  # D-1129: what the resume takes up, from the last collect (free); a budget entry that cannot hold refuses it
  br resume-plan "$OUT" --deadline "${V[tb-acc-deadline]:-}" --redo "${V[tb-redo]:-}" > "$OUT/resume-plan.json" \
    || { echo "box-run: refused (no VM started): the resume's options (above)" >&2; exit 6; }
  [ "$(status)" = TERMINATED ] || { echo "VM $VM is not TERMINATED" >&2; exit 2; }
  session_leftover || { echo "box-run: refused (no VM started): an earlier session's door (above)" >&2; exit 7; }
  cap="$(cat "$OUT/cap-hours" 2>/dev/null || echo 4)"
  # this tree's startup script and helper, and a new tb-retry: a step that stopped runs again with the fix
  mkdir -p "$OUT/md"; date -u +%Y%m%dT%H%M%SZ > "$OUT/md/tb-retry"
  RFILES="startup-script=$ROOT/deploy/gcp/box-install-run.sh,tb-helper=$ROOT/deploy/gcp/box_vm.py,tb-retry=$OUT/md/tb-retry"
  # the launch's own keys again: the collect at the run's end put the VM back and removed them (reset_vm)
  for k in $(cat "$OUT/metadata-keys" 2>/dev/null); do
    case "$k" in
      startup-script|tb-helper|tb-retry|tb-acc-sets) ;;
      tb-site-answers) grep -qw start "$OUT/md/tb-steps" 2>/dev/null && [ ! -f "$OUT/md/tb-answers-version" ] \
        && RFILES="$RFILES,tb-site-answers=$ROOT/deploy/gcp/validation-site-answers.yaml" ;;
      *) [ -f "$OUT/md/$k" ] && RFILES="$RFILES,$k=$OUT/md/$k" ;;
    esac
  done
  [ -f "$OUT/md/tb-acc-sets" ] && [ -z "$ONLY" ] && RFILES="$RFILES,tb-acc-sets=$OUT/md/tb-acc-sets"
  if [ -s "$OUT/acc-tools.json" ]; then   # an accuracy run: lane G's tools at this commit, fetched again on the VM
    br acc-tools --out "$OUT/acc-tools.tgz" > "$OUT/acc-tools.json" || exit 2
    gc storage cp "$OUT/acc-tools.tgz" "$OBJ/acc-tools.tgz" >/dev/null
  fi
  if [ -n "$ONLY" ]; then   # the sets still to run (a finished set is kept either way)
    br metadata --steps acc --mode "$MODE" --only "$ONLY" --out "$OUT/md-only" --set tb-acc-tools=x > /dev/null || exit 2
    cp "$OUT/md-only/tb-acc-sets" "$OUT/md/tb-acc-sets"; RFILES="$RFILES,tb-acc-sets=$OUT/md/tb-acc-sets"
  fi
  # one launch's own asks (F24): a step to run again and a set budget hold for the launch that names them, never
  # for the next resume (a redo sent twice would throw away the set it just ran)
  for k in tb-redo tb-acc-deadline tb-acc-min-start tb-acc-protocols tb-site-env tb-acc-streams tb-skip tb-serving tb-qualify-timebox; do
    if [ -n "${V[$k]:-}" ]; then
      printf '%s' "${V[$k]}" > "$OUT/md/$k"
      case ",$RFILES," in *",$k="*) ;; *) RFILES="$RFILES,$k=$OUT/md/$k" ;; esac
      grep -qw "$k" "$OUT/metadata-keys" || echo "$(cat "$OUT/metadata-keys") $k" > "$OUT/metadata-keys"
    elif [ -f "$OUT/md/$k" ]; then
      rm -f "$OUT/md/$k"; RFILES=$(printf '%s' "$RFILES" | sed "s|,$k=[^,]*||")
    fi
  done
  # D3 (P1b review): the ruleset tag holds for the run (its sets were built with it): kept from the launch, and
  # replaced when this resume gives one (a redone set is then built with the new tag)
  if [ -n "${V[tb-acc-rs-tag]:-}" ]; then
    printf '%s' "${V[tb-acc-rs-tag]}" > "$OUT/md/tb-acc-rs-tag"
    case ",$RFILES," in *,tb-acc-rs-tag=*) ;; *) RFILES="$RFILES,tb-acc-rs-tag=$OUT/md/tb-acc-rs-tag" ;; esac
    grep -qw tb-acc-rs-tag "$OUT/metadata-keys" || echo "$(cat "$OUT/metadata-keys") tb-acc-rs-tag" > "$OUT/metadata-keys"
  fi
  if [ -n "${V[tb-qualify-args]:-}" ]; then
    printf '%s' "${V[tb-qualify-args]}" > "$OUT/md/tb-qualify-args"
    case ",$RFILES," in *,tb-qualify-args=*) ;; *) RFILES="$RFILES,tb-qualify-args=$OUT/md/tb-qualify-args" ;; esac
    grep -qw tb-qualify-args "$OUT/metadata-keys" || echo "$(cat "$OUT/metadata-keys") tb-qualify-args" > "$OUT/metadata-keys"
  fi
  if [ -n "${V[tb-direct]:-}" ]; then
    echo 1 > "$OUT/md/tb-direct"
    case ",$RFILES," in *,tb-direct=*) ;; *) RFILES="$RFILES,tb-direct=$OUT/md/tb-direct" ;; esac
  fi
  grep -qw tb-direct "$OUT/metadata-keys" 2>/dev/null || [ ! -f "$OUT/md/tb-direct" ] || echo "$(cat "$OUT/metadata-keys") tb-direct" > "$OUT/metadata-keys"
  grep -qw tb-retry "$OUT/metadata-keys" 2>/dev/null || echo "$(cat "$OUT/metadata-keys" 2>/dev/null) tb-retry" > "$OUT/metadata-keys"
  echo "resume $RUN_ID: retry $(cat "$OUT/md/tb-retry") with this tree ($(git rev-parse --short HEAD)), cloud cap ${cap} h"
  gc compute instances add-metadata "$VM" --zone "$ZONE" --metadata-from-file "$RFILES"
  gc compute instances set-scheduling "$VM" --zone "$ZONE" --max-run-duration="${cap}h" --instance-termination-action=STOP
  gc compute instances start "$VM" --zone "$ZONE"
  [ "$WAIT" = 0 ] && exit 0
  until one_look; do sleep 60; done; exit 0
fi

# ---------------------------------------------------------------- a launch
[ -n "$STEPS" ] || { echo "box-run: --steps build | start,g6,g9,g10 (see --help)" >&2; exit 2; }
case " $STEPS " in *" build "*) [ "$STEPS" = build ] || { echo "box-run: build is its own launch (another service account)" >&2; exit 2; } ;; esac
[ "$(status)" = TERMINATED ] || { echo "VM $VM is $(status), not TERMINATED: one run at a time" >&2; exit 2; }
[ "$SESSION" = 0 ] || sv plan "$SESSION_ALLOW"   # D-1130: the rules it would make, before anything
if ! scheck "$OUT/session-check.json"; then   # never launched blocked: a session is not a probe of the product
  echo "box-run: refused (no VM started): the session would not be served as ruled (D-1132)" >&2; exit 9
fi
if ! vcheck "$OUT/validation-check.json"; then
  [ "$ANYWAY" = 1 ] || { echo "box-run: refused (no VM started): --even-if-blocked launches anyway" >&2; exit 9; }
  echo "box-run: --even-if-blocked: launching all the same; the box will stop at 52-acc-routes" >&2
fi
RID="${V[tb-release-id]:-}"
V[tb-run-id]="$RUN_ID"; V[tb-bucket]="$BUCKET"
if [ "$MODE" = validation ]; then  # the throwaway key's public half, written beside the bundle by the build
  V[tb-vendor-pub]="${V[tb-vendor-pub]:-$BUCKET/r2/$RID/throwaway-signing-key.pub}"
else
  V[tb-vendor-pub]="${V[tb-vendor-pub]:-$BUCKET/r2/keys/vendor_ed25519.pub}"
fi
[ "$SESSION" = 0 ] || V[tb-session-handoff]="$HANDOFF"
if [ "$STEPS" = dev ] || [ "$STEPS" = "dev acc" ] || [ "$STEPS" = "dev session" ]; then   # the commit's images and tree on the VM: no bundle, no signature
  V[tb-src]="${V[tb-src]:-$BUCKET/r2/$RID/src.bundle}"; V[tb-direct]=1
elif [ "$STEPS" = build ]; then
  V[tb-src]="${V[tb-src]:-$BUCKET/r2/$RID/src.bundle}"; V[tb-out]="${V[tb-out]:-$BUCKET/r2/$RID}"
  [ "$MODE" = validation ] || V[tb-vendor-key-secret]="$KEY_SECRET"
else
  V[tb-bundle]="${V[tb-bundle]:-$BUCKET/r2/$RID/trialbox-$RID.tar}"
  if [ -z "${V[tb-bundle-sha256]:-}" ] && [ "$DRY" = 0 ]; then   # the build's own .sha256 beside the bundle
    V[tb-bundle-sha256]="$(gc storage cat "${V[tb-bundle]}.sha256" 2>/dev/null | cut -d' ' -f1 || true)"
  fi
  [ "$DRY" = 1 ] && V[tb-bundle-sha256]="${V[tb-bundle-sha256]:-<sha256 from ${V[tb-bundle]}.sha256>}"
  case " $STEPS " in *" start "*)   # validation: the embedder's file list (public names and sha256s) in the bucket
    [ "$MODE" != validation ] || V[tb-embed-list]="${V[tb-embed-list]:-$BUCKET/r2/models/e-embed-1.sha256}" ;;
  esac
  case " $STEPS " in *" start "*)   # validation: the committed synthetic site (no secret), unless an answers version
    if [ "$MODE" = production ] || [ -n "${V[tb-answers-version]:-}" ]; then
      V[tb-answers-secret]="${V[tb-answers-secret]:-tb-r2-answers}"; V[tb-answers-version]="${V[tb-answers-version]:-1}"
    fi ;;
  esac
fi
case " $STEPS " in *" acc "*)  # the public-data run turns the PHI tripwire off by its declared setting (D-506, D-511)
  [ "$MODE" != validation ] || V[tb-acc-tripwire-setting]="${V[tb-acc-tripwire-setting]:-TB_GATEWAY_PHI_TRIPWIRE=off}" ;;
esac
if [ -n "$SRC_BUNDLE" ]; then case " $STEPS " in *" build "*|*" dev "*) ;; *) echo "box-run: --src-bundle is for a build or dev launch" >&2; exit 2 ;; esac; fi
# H-1 (the P1b fixes): every free check at once, before anything is uploaded or started: the protocol filter and the
# tag (D1), the streams and the set budgets (D4, D7), the full commit and the source bundle proved as the VM clones it
# (D8), the metadata. --preflight stops here.
pfa=(); for k in "${!V[@]}"; do pfa+=(--set "$k=${V[$k]}"); done
br preflight --steps "$STEPS" --mode "$MODE" --only "$ONLY" ${SRC_BUNDLE:+--src-bundle "$SRC_BUNDLE"} "${pfa[@]}" > "$OUT/preflight.json" \
  || { echo "box-run: refused (no VM started): the preflight failed (the lines above; $OUT/preflight.json)" >&2; exit 6; }
if [ "$PREFLIGHT" = 1 ]; then
  mapfile -t sh_ < <(ses_hours)
  br estimate --steps "$STEPS" --mode "$MODE" --only "$ONLY" ${sh_[@]+"${sh_[@]}"}
  echo "preflight: every free check passed (nothing was uploaded or started; $OUT/preflight.json)"
  exit 0
fi
if [ -n "$SRC_BUNDLE" ]; then  # D8: proved by the preflight above (cloned as the VM clones it, the commit checked out)
  gc storage cp "$SRC_BUNDLE" "${V[tb-src]}" >/dev/null
  echo "source bundle proved (commit ${V[tb-commit]} checks out from it) and uploaded to ${V[tb-src]}"
fi
case " $STEPS " in *" acc "*|*" session "*)  # lane G's accuracy tools at this commit (git archive), for the VM to fetch and build with
  br acc-tools --out "$OUT/acc-tools.tgz" > "$OUT/acc-tools.json" || exit 2
  V[tb-acc-tools]="$OBJ/acc-tools.tgz"
  gc storage cp "$OUT/acc-tools.tgz" "$OBJ/acc-tools.tgz" >/dev/null ;;
esac
sets=(); for k in "${!V[@]}"; do sets+=(--set "$k=${V[$k]}"); done
rm -rf "$OUT/md"
br metadata --steps "$STEPS" --mode "$MODE" --only "$ONLY" --out "$OUT/md" "${sets[@]}" > "$OUT/metadata-keys" || exit 2
mapfile -t sh_ < <(ses_hours)
CAP=$(br estimate --steps "$STEPS" --mode "$MODE" --only "$ONLY" ${sh_[@]+"${sh_[@]}"} --json | "$PY" -c 'import json,sys; print(sum(l["cap_hours"] for l in json.load(sys.stdin)["launches"]))')
echo "$CAP" > "$OUT/cap-hours"
br estimate --steps "$STEPS" --mode "$MODE" --only "$ONLY" ${sh_[@]+"${sh_[@]}"}
FILES="startup-script=$ROOT/deploy/gcp/box-install-run.sh,tb-helper=$ROOT/deploy/gcp/box_vm.py"
case " $STEPS " in *" start "*) [ "$MODE" = validation ] && [ -z "${V[tb-answers-version]:-}" ] \
  && FILES="$FILES,tb-site-answers=$ROOT/deploy/gcp/validation-site-answers.yaml" ;; esac
for k in $(cat "$OUT/metadata-keys"); do FILES="$FILES,$k=$OUT/md/$k"; done
echo "startup-script tb-helper tb-site-answers $(cat "$OUT/metadata-keys")" > "$OUT/metadata-keys"
# the re-review's A: an earlier session's allow never outlives it into another launch (this one's door is made below)
session_leftover || { echo "box-run: refused (no VM started): an earlier session's door (above)" >&2; exit 7; }
if [ "$STEPS" = build ] && [ "$MODE" = production ]; then  # validation: the VM's own account (no vendor key read)
  if [ "$DRY" = 0 ]; then
    gc compute instances describe "$VM" --zone "$ZONE" --format='value(serviceAccounts[0].email)' > "$OUT/default-sa"
  else echo "<project-number>-compute@developer.gserviceaccount.com" > "$OUT/default-sa"; fi
  gc compute instances set-service-account "$VM" --zone "$ZONE" \
    --service-account "$SIGNER_SA@$(project).iam.gserviceaccount.com" --scopes cloud-platform
  touch "$OUT/signer"
fi
if [ "$SESSION" = 1 ]; then   # D-1130: the door before the start, proved; nothing starts while it is not. A refusal
  # after the rules were made takes them away again (the re-review's A: exit 7 left them)
  session_door || { session_door_abort; echo "box-run: refused (no VM started): the session's firewall rules could not be made" >&2; exit 7; }
  session_rules_check || { session_door_abort; echo "box-run: refused (no VM started): the door is not proved (above; D-1130)" >&2; exit 7; }
  bucket_private || { session_door_abort; echo "box-run: refused (no VM started): the links' bucket is not private (above)" >&2; exit 7; }
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
[ "$SESSION" = 0 ] || echo "session: $0 --session-status $RUN_ID until TB-SESSION-READY, then ONCE $0 --links $RUN_ID (nothing from it is evidence)"
[ "$WAIT" = 0 ] || [ "$DRY" = 1 ] && exit 0
until one_look; do sleep 60; done
