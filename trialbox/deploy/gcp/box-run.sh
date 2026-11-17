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
if [ "$PREFLIGHT" = 1 ] && { [ -n "$RESUME$COLLECT$LINKS$SSTATUS" ] || [ "$STOP" = 1 ]; }; then
  echo "box-run: --preflight checks a launch (--steps ...), not a resume, a collect or a stop" >&2; exit 2
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
rule_exists() {  # in a dry run nothing exists yet (the whole plan is printed)
  if [ "$DRY" = 1 ]; then echo "+ gcloud compute firewall-rules describe $1 --format=value(name)   # exists?"; return 1; fi
  gc compute firewall-rules describe "$1" --format='value(name)' >/dev/null 2>&1
}
vm_network() {
  if [ "$DRY" = 1 ]; then echo default; return 0; fi
  basename "$(gc compute instances describe "$VM" --zone "$ZONE" --format='value(networkInterfaces[0].network)')"
}
session_door() {  # a deny-all on the session's tag, the one allow (tcp:443 from the owner's ranges), the tag on the VM
  local net; net="$(vm_network)" || return 1
  [ -n "$net" ] || { echo "box-run: the VM's network cannot be read" >&2; return 1; }
  rule_exists "$S_DENY" || gc compute firewall-rules create "$S_DENY" --network "$net" --direction INGRESS --action DENY \
    --rules=all --source-ranges=0.0.0.0/0 --target-tags "$S_TAG" --priority "$SESSION_DENY_PRIORITY" \
    --description="TrialBox session (D-1130): nothing but its tcp:443 rule reaches the VM (not SSH, not an old door)" || return 1
  if rule_exists "$S_ALLOW"; then
    gc compute firewall-rules update "$S_ALLOW" --rules=tcp:443 --source-ranges="$SESSION_ALLOW" \
      --target-tags "$S_TAG" --priority "$SESSION_ALLOW_PRIORITY" || return 1
  else
    gc compute firewall-rules create "$S_ALLOW" --network "$net" --direction INGRESS --action ALLOW --rules=tcp:443 \
      --source-ranges="$SESSION_ALLOW" --target-tags "$S_TAG" --priority "$SESSION_ALLOW_PRIORITY" \
      --description="TrialBox session (D-1130): https from the owner's own ranges only" || return 1
  fi
  gc compute instances add-tags "$VM" --zone "$ZONE" --tags "$S_TAG" || return 1
  printf '%s\n' "$SESSION_ALLOW" > "$OUT/session"   # the ranges, for --links and --session-status
}
session_rules_check() {  # D-1130: only tcp:443 from the owner's ranges reaches the VM (every rule, every tag of the VM)
  local rules tags net rc=0 ranges
  ranges="${SESSION_ALLOW:-$(cat "$OUT/session" 2>/dev/null)}"
  [ -n "$ranges" ] || { echo "box-run: no session ranges for $RUN_ID here (--session-allow RANGES gives them)" >&2; return 1; }
  if [ "$DRY" = 1 ]; then
    echo "+ gcloud compute firewall-rules list --format=json   # only tcp:443 from $ranges may reach the VM"
    echo "+ gcloud compute instances describe $VM --zone $ZONE --format=value(tags.items)"
    return 0
  fi
  net="$(vm_network)"; rules="$(mktemp)"
  gc compute firewall-rules list --filter="network~/$net\$" --format=json > "$rules" || { rm -f "$rules"; return 1; }
  tags="$(gc compute instances describe "$VM" --zone "$ZONE" --format='value(tags.items)' | tr ';,' '  ')"
  sv rules-check "$net" "$tags" "$ranges" < "$rules" > "$OUT/session-rules.json" || rc=$?
  rm -f "$rules"
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
bucket_private() {  # D-1123 section 6: the links object's bucket is not public (no allUsers, no allAuthenticatedUsers)
  local b="${BUCKET#gs://}"; b="gs://${b%%/*}"
  if [ "$DRY" = 1 ]; then echo "+ gcloud storage buckets get-iam-policy $b --format=json   # no allUsers, no allAuthenticatedUsers"; return 0; fi
  local pol; pol="$(gc storage buckets get-iam-policy "$b" --format=json)" || { echo "box-run: the bucket's IAM policy cannot be read" >&2; return 1; }
  if printf '%s' "$pol" | grep -qE '"allUsers"|"allAuthenticatedUsers"'; then
    echo "box-run: the bucket $b is public (allUsers or allAuthenticatedUsers in its IAM policy): the links object would be readable by anyone" >&2
    return 1
  fi
  echo "bucket: $b names no allUsers and no allAuthenticatedUsers"
}
session_door_down() {  # --stop and the end of a collect: the tag off the VM, the two rules deleted (each if there)
  [ "$SESSION" = 1 ] || [ -f "$OUT/session" ] || vm_has_tag || return 0
  gc compute instances remove-tags "$VM" --zone "$ZONE" --tags "$S_TAG" >/dev/null 2>&1 || true
  local r; for r in "$S_ALLOW" "$S_DENY"; do
    if [ "$DRY" = 1 ] || rule_exists "$r"; then gc compute firewall-rules delete "$r" --quiet || true; fi
  done
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
if [ -n "$SSTATUS" ]; then   # D-1132: the VM, the door, and the session's ready line of this boot only (D-1120)
  s="$(status)"; echo "VM $VM ($ZONE): $s"
  session_rules_check || echo "door: NOT proved (above): give no link" >&2
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
  for o in $objs; do gc storage rm "$o" >/dev/null 2>&1 || echo "box-run: could not delete $o: delete it by hand" >&2; done
  echo "== deleted from the bucket. Give the owner his line in the integrator's own session; never on a PR, in a comment or a file."
  echo "== nothing from this session is evidence."
  exit 0
fi
if [ -n "$COLLECT" ]; then
  if [ "$FOLLOW" = 1 ]; then until one_look; do sleep 60; done; else one_look || true; fi
  exit 0
fi
if [ -n "$RESUME" ]; then
  [ "$(status)" = TERMINATED ] || { echo "VM $VM is not TERMINATED" >&2; exit 2; }
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
if [ "$STEPS" = build ] && [ "$MODE" = production ]; then  # validation: the VM's own account (no vendor key read)
  if [ "$DRY" = 0 ]; then
    gc compute instances describe "$VM" --zone "$ZONE" --format='value(serviceAccounts[0].email)' > "$OUT/default-sa"
  else echo "<project-number>-compute@developer.gserviceaccount.com" > "$OUT/default-sa"; fi
  gc compute instances set-service-account "$VM" --zone "$ZONE" \
    --service-account "$SIGNER_SA@$(project).iam.gserviceaccount.com" --scopes cloud-platform
  touch "$OUT/signer"
fi
if [ "$SESSION" = 1 ]; then   # D-1130: the door before the start, proved; nothing starts while it is not
  session_door || { echo "box-run: refused (no VM started): the session's firewall rules could not be made" >&2; exit 7; }
  session_rules_check || { echo "box-run: refused (no VM started): the door is not proved (above; D-1130)" >&2; exit 7; }
  bucket_private || { echo "box-run: refused (no VM started): the links' bucket is not private (above)" >&2; exit 7; }
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
