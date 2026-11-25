#!/usr/bin/env bash
# TrialBox one-file installer for a hospital workstation or server (clinical review 2026-11, section 6; RUNBOOK §1).
#
#   sudo deploy/install.sh trialbox-<version>.tar --tier small|medium|large [--answers site.yaml] [--yes]
#   sudo deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--gpu rtxpro6000|gb10|rtx5090|rtx4090] [--yes]
#        [--environment DEV|TEST|VALIDATION|PRODUCTION]   (D-837; default PRODUCTION, D-127)
#        [--ssh-off-over-ssh]   (H-70: run over SSH, hardening.conf's SSH=off is refused unless this is given)
#        [--test-box NAME --port-offset N [--gpus 2,3] [--gpu-mem-gb 48]]   (H-106: one of several TEST boxes on a host)
#   sudo deploy/install.sh --check            # host checks only (deploy/check_host.sh)
#   deploy/install.sh --tier large --tier-check   # only: may this tier be installed on this machine?
#   Without a TPM, set bundle and answers to their paths. The KEK passphrase (12 characters or more, one line) comes
#   from a file only root can read (type it after sudo's own password prompt, then Enter; nothing is shown):
#   sudo bash -c 'umask 077; IFS= read -rs TB_KEK_PASSPHRASE; printf "%s\n" "$TB_KEK_PASSPHRASE" > /root/trialbox-kek.pass'
#   sudo TB_KEK_BACKEND=passphrase deploy/install.sh "$bundle" --answers "$answers" --kek-passphrase-file /root/trialbox-kek.pass
#   or is typed when asked (twice, not shown): ... --kek-passphrase-stdin. The file must be a regular file owned by
#   root with mode 0600; it is removed once the keys are sealed (--keep-kek-passphrase-file keeps it). A passphrase in
#   the environment (TB_KEK_PASSPHRASE) is refused: sudo logs the variables it keeps (RUNBOOK §23, H-96).
#   ... --ctgov live|offline                       # ClinicalTrials.gov: online, or the copy in each update (D-140)
#   deploy/install.sh --ctgov-check                # only: which ClinicalTrials.gov mode would be suggested here?
#
# Tiers (D-138, tools/tiers.py): small = rtx5090, medium = gb10, large = rtxpro6000 (the boxes of D-124). A tier is
# installed only from a measured serving record of its own uncapped card (deploy/site/ or deploy/measured/
# serving_config.<gpu>.json, tools/serving_config.py measured); there is no override. --gpu with
# TB_ACCEPT_UNMEASURED_GPU=1 stays for a trial boot of an unmeasured card, and is not a tier install; since D-726 only
# on a rehearsal box (--rehearsal sets it; TB_COMPOSE_OVERRIDE= empty keeps the real model servers).
#
# What it does, in order, and stops at the first failure:
#   1. host:      Docker Engine + compose plugin present and running; GPU driver when --mode gpu (auto when nvidia-smi
#                 works); vendor public key installed (deploy/keys/vendor_ed25519.pub)
#   2. bundle:    verify the Ed25519 signature and every payload hash, then load images, models and rulesets
#                 (tools/apply_update.sh; a tampered bundle changes nothing). The bundle's host tree (compose files,
#                 host tools, configuration; T-631, D-367) is unpacked to releases/<id> beside this folder and
#                 `current` names it; the folder's release files become links through `current` (a copied file is
#                 moved to releases/.replaced-<time>/), the site's own files in deploy/ stay. The install then goes
#                 on from the signed tree: deploy/install.sh, now a link into it, runs again
#                 H-95: straight from the stick, nothing copied first; a release in two packs takes the model
#                 pack (engine image, weights) with --model-pack FILE or finds it beside the bundle, and loads it first
#   3. settings:  deploy/settings.yaml + deploy/.env from the settings wizard (questions, or --answers), random
#                 service passwords; .env 0600, settings.yaml 0640 for group tb; an existing settings.yaml is kept
#                 and re-validated
#   4. start:     down --remove-orphans after a failed run, only in this install's own project, never a healthy stack
#                 docker compose up --wait --pull never with the chosen model profile (every image from the bundle,
#                 digest pins kept on either Docker image store: tools/image_pins.py); egress rules (deploy/network.sh);
#                 the systemd units of deploy/systemd (egress closed at boot before Docker, the stack after a restart,
#                 the egress refresh and watchdog timers; D-377)
#   5. accounts:  first console administrator (password and enrolment code on a terminal once, in no log); users page
#   6. check:     deploy/check_host.sh; the https:// console URL must answer; the intake address
# Host baseline (T-634, D-408): in VALIDATION and PRODUCTION the site keys are sealed under a KEK right after they are
# made (deploy/hardening/seal_keys.sh), and with deploy/site/hardening.conf the input firewall and SSH are set after
# the egress rules (deploy/hardening/apply.sh). The disk unlock is hospital IT's, once, at OS install
# (deploy/hardening/disk-unlock.sh); the host check FAILs a disk the TPM alone opens.
# Site inputs and a finished install (T-632, D-382): the site's mapping lives in deploy/site/mapping (the adapter and
# the wizard look there before the image) and the feed folder is TB_SOURCE_DIR (required in PRODUCTION). TLS is on:
# the wizard's TB_TLS_HOSTNAME (asked here when missing) adds deploy/docker-compose.identity.yml after `console.cli
# check-tls` passed. Both cron files (log retention, backups) are installed. The judge is named from the
# configuration (tools/pin_model.py --name-judge). The install ends with exit 1 when a FAIL line remains.
# In GPU mode step 3 also makes the key of the on-box model servers (TB_LLM_API_KEY, D-177) and step 4 checks that
# they serve the pinned names and require that key (trialbox doctor --serving): a mismatch stops the install.
# The box form (T-729, D-466): deploy/box-install.sh runs this script with TB_BOX=1 and an answers file it planned from
# the detected hardware: deploy/docker-compose.box.yml is added (the console's first-run folder) and no administrator
# is made here (the owner makes the first accounts in the first-run wizard). TB_BOX_DEFER_SEAL=1 (a board without a
# TPM) leaves the site keys to the box's apply step, which seals them under the passphrase the owner set.
# TB_COMPOSE_OVERRIDE=<file> adds one compose file after the others (the box rehearsal's model stand-ins, D-176); it is
# printed and kept in deploy/.env COMPOSE_FILE so every later compose command uses it too.
# --rehearsal (D-726, D-887): a rehearsal box, which says so. It is TEST from before the bundle loads (deploy/site/
# rehearsal.json), refused on a PRODUCTION or VALIDATION box and on a box whose volumes hold data from no rehearsal;
# deploy/.env gets TB_ENV=VALIDATION (the integrator's (i): D3 stays on the box, so SCREEN reaches the pinned builds)
# and TB_REHEARSAL=1, doctor says "REHEARSAL BOX", and a site box refuses a bundle built with make_bundle.sh
# --rehearsal. The model stand-ins and TB_ACCEPT_UNMEASURED_GPU=1 work on a rehearsal box only.
# Re-running is safe: every step is idempotent. Nothing leaves the host: no registry, no download, no telemetry.
# The one exception: when live ClinicalTrials.gov is chosen, one HTTPS request to clinicaltrials.gov (no data sent)
# checks that this host can reach it (D-140).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ARGS=("$@")  # D-367: the install goes on from the signed tree with the same arguments
BUNDLE=""; ANSWERS=""; MODE="${TB_LLM_MODE:-auto}"; GPU="${TB_GPU_PROFILE:-auto}"; YES=0; CHECK=0
TIER=""; TIER_CHECK=0; GPU_SET=0; MODE_SET=0; CTGOV="${TB_CTGOV_INSTALL:-}"; CTGOV_CHECK=0; REHEARSAL=0
ENVIRONMENT=""; SSH_OFF_OVER_SSH=0; REAL_SERVERS=0; GPU_INDEX=""; ENGINE_PROBE=""; MODEL_PACK=""
TEST_BOX=""; TEST_BOX_SET=0; PORT_OFFSET=""; TEST_GPUS=""; TEST_GPU_MEM=""  # H-106: the command line's only, never a caller's
BENCH=0  # H-116: the command line's only (--bench), never a caller's
# ---- STOP-OR-WARN (H-94, the owner's ruling 7092087958, D-1091; the same bytes in every script that has it): on a PoC box
# the install, start and update paths stop for five things only (D-1091), each named where it stops as "H-94 (N)":
# (1) the bundle's or update's signature or hashes do not hold; (2) the machine physically cannot run it (disk,
# memory, card); (3) a PoC box would load real patient data or become PRODUCTION; (4) the step needs root and does
# not have it; (5) a secret would be read from, or written to, a place others can read. Every other stop calls
# stop_or_warn: on a PoC box a warning, a line of the one list (deploy/site/poc-stops.jsonl, which trialbox doctor
# shows) and the step goes on; on any other box the same stop as before, the same words and exit code. "H-94
# depends (N)" marks a stop kept because it protects stop N on the input that reaches it (D-1091, H94-03).
# A PoC box (tools/trialbox/stops.py poc_box, the same rule): every source that speaks says DEV, TEST or VALIDATION.
# The sources are TB_ENV in deploy/.env read as compose reads it (an "export", blanks, a comment; the last line wins.
# A file that cannot be read, or a value none of the four: PRODUCTION), an installed box with none (PRODUCTION,
# D-127), the rehearsal mark on a box that records none yet (VALIDATION), and this run's command line, upper-cased
# only, as ENV-EARLY reads it (TB_STOP_ARG_ENV, TB_STOP_REHEARSAL: set by the script itself, never read from a
# caller's environment). Nothing speaking (a fresh box, no environment given) is PRODUCTION.
tb_env_raw() {  # FILE: TB_ENV's value as compose reads it (an "export", blanks around the name and the value, a comment
  # after an unquoted value; the last line wins), quotes kept; nothing when the file names none or cannot be read
  { sed -n -E 's/^[[:space:]]*(export[[:space:]]+)?TB_ENV[[:space:]]*=//p' "$1" 2>/dev/null || true; } | tail -1 \
    | sed -E -e "/^[[:space:]]*[\"']/!s/[[:space:]]+#.*\$//" -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//'
}
tb_env_of() { tb_env_raw "$1" | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]'; }  # FILE: no quotes, no blanks, upper case
tb_poc_box() {
  _d="$TB_STOP_DEPLOY"; _rec=""
  if [ -e "$_d/.env" ] || [ -L "$_d/.env" ]; then
    [ -f "$_d/.env" ] && [ -r "$_d/.env" ] || return 1
    _rec="$(tb_env_of "$_d/.env")"
  fi
  if [ -z "$_rec" ] && { [ -e "$_d/settings.yaml" ] || [ -e "$_d/updates/installed.json" ]; }; then _rec=PRODUCTION; fi
  if [ -z "$_rec" ] && [ -f "$_d/site/rehearsal.json" ]; then _rec=VALIDATION; fi
  _arg="$(printf '%s' "$TB_STOP_ARG_ENV" | tr '[:lower:]' '[:upper:]')"
  [ -n "$_arg" ] || [ "$TB_STOP_REHEARSAL" != 1 ] || _arg=VALIDATION
  for _e in "$_rec" "$_arg"; do case "$_e" in ""|DEV|TEST|VALIDATION) ;; *) return 1 ;; esac; done
  [ -n "$_rec$_arg" ]
}
tb_stop_json() {  # one line, no secret's value, no path under uploads/, escaped for a JSON string
  printf '%s' "$1" | tr -d '\000-\037' | sed -e 's#[^ ]*/uploads/[^ ]*#<a path under uploads/>#g' \
    -e 's/\([a-z0-9_]*\(password\|passphrase\|token\|secret\|_key\)\)=[^ ]*/\1=<hidden>/gI' -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}
tb_stop_list() {  # KEY SKIPPED WHAT: one line of the list, written by root or the installer only; never a stop
  _f="$TB_STOP_DEPLOY/site/poc-stops.jsonl"; _o=""
  [ ! -e "$_f" ] || _o="$(stat -c %u "$_f" 2>/dev/null || echo unknown)"
  # a link is never followed, nor a second name of another file (review L-2 of #1430: one name, its own)
  if [ ! -L "$_f" ] && { [ ! -e "$_f" ] || [ "$(stat -c %h "$_f" 2>/dev/null)" = 1 ]; } \
      && { [ -z "$_o" ] || [ "$_o" = 0 ] || [ "$_o" = "$(id -u)" ]; } && mkdir -p "${_f%/*}" 2>/dev/null \
      && (umask 027; printf '{"key": "%s", "what": "%s", "skipped": "%s", "at": "%s", "by": "%s"}\n' "$(tb_stop_json "$TB_STOP_FILE/$1")" \
        "$(tb_stop_json "$3")" "$(tb_stop_json "$2")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TB_STOP_FILE" >> "$_f") 2>/dev/null; then
    chmod 0640 "$_f" 2>/dev/null || true
  else
    printf '%s: warning: the PoC list %s cannot be written; the step goes on\n' "$TB_STOP_WHO" "$_f" >&2
  fi
}
stop_or_warn() {  # [--rc N] [--silent] KEY SKIPPED WHAT...: PoC box: a warning, a line of the list, 0; else the stop
  _rc=1; _silent=0
  while :; do case "$1" in --rc) _rc="$2"; shift 2 ;; --silent) _silent=1; shift ;; *) break ;; esac; done
  _key="$1"; _skipped="$2"; shift 2
  if ! tb_poc_box; then
    if command -v alive_stop >/dev/null 2>&1; then alive_stop; fi
    [ "$_silent" = 1 ] || printf '%s: %s\n' "$TB_STOP_WHO" "$*" >&2
    exit "$_rc"
  fi
  # a warning never says REFUSED (review L-3 of #1430): "update REFUSED" warns as "update"
  printf '%s: warning (PoC box, H-94): %s%s\n' "${TB_STOP_WHO%% REFUSED*}" "$*" "${_skipped:+; skipped: $_skipped}" >&2
  tb_stop_list "$_key" "$_skipped" "$*"
  return 0
}
tb_kept_fails() {  # stdin: a host check's output; stdout: its FAIL lines of a kept refusal, which stop on every box
  # (5) a secret's mode (deploy/.env, a key, a token); (2) what the machine cannot run (memory class, card, driver,
  # toolkit, disk space); (3) the poc profile on a PRODUCTION box (review H-1 of #1430). Every other FAIL line warns
  _in="$(cat)"
  { printf '%s\n' "$_in" | grep -E '^FAIL .*[Mm]ode' | grep -Ei '\.env|secret|key|token|passphrase|password'
    printf '%s\n' "$_in" | grep -E '^FAIL .*(under 96 GiB|GB10 profile on|NVIDIA driver|nvidia-container-toolkit not configured|but no nvidia-smi|free space on|TB_HOST_PROFILE=poc on a PRODUCTION box)'
  } | sort -u || true
}
# ---- end of STOP-OR-WARN
# H-94: this run's command line is read once before the arguments are, so a stop while they are read knows the box
TB_STOP_WHO=install; TB_STOP_FILE=install.sh; TB_STOP_DEPLOY="$ROOT/deploy"; TB_STOP_ARG_ENV=""; TB_STOP_REHEARSAL=0
_prev=""; _clear=1
for _a in "$@"; do
  [ "$_prev" != --environment ] || TB_STOP_ARG_ENV="$_a"
  [ "$_a" != --rehearsal ] || TB_STOP_REHEARSAL=1
  case "$_a" in --check|--tier-check|--ctgov-check|--keep-poc-list) _clear=0 ;; esac
  _prev="$_a"
done
# the list is this install's (review L-3 of #1396): emptied when an install starts, before its first stop_or_warn;
# kept by the run from the signed tree (the same install, TB_INSTALL_SIGNED naming the release `current` names) and
# by a run that only checks, and when box-install.sh runs it (--keep-poc-list: box-install.sh empties it itself; the
# option only keeps more lines, and no variable of a caller's is read for it). rm takes a link away, never what it names
if [ "$_clear" = 1 ] \
    && { [ -z "${TB_INSTALL_SIGNED:-}" ] || [ "$TB_INSTALL_SIGNED" != "$(readlink "$ROOT/current" 2>/dev/null)" ]; }; then
  rm -f -- "$TB_STOP_DEPLOY/site/poc-stops.jsonl" 2>/dev/null || true
fi
PP_FILE=""; PP_KEEP=0; PP_STDIN=0; PP_FD=""; PP_REMOVE=""  # H-96: the KEK passphrase's two ways in (the KEK-INPUT block)
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift ;;
    --tier-check) TIER_CHECK=1 ;;
    --answers) ANSWERS="$2"; shift ;;
    --mode) MODE="$2"; MODE_SET=1; shift ;;
    --gpu) GPU="$2"; GPU_SET=1; shift ;;
    --yes) YES=1 ;;
    --ctgov) CTGOV="$2"; shift ;;
    --ctgov-check) CTGOV_CHECK=1 ;;
    --check) CHECK=1 ;;
    --rehearsal) REHEARSAL=1 ;;
    --environment) ENVIRONMENT="$2"; shift ;;
    --ssh-off-over-ssh) SSH_OFF_OVER_SSH=1 ;;
    --keep-poc-list) ;;  # H-94: box-install.sh's run keeps the list box-install.sh began (read above)
    --model-pack) MODEL_PACK="$2"; shift ;;  # H-95: the model pack the software pack needs (else found beside it)
    --test-box) TEST_BOX="${2:-}"; TEST_BOX_SET=1; shift ;;  # H-106: a test box, one of several on this host (TEST-BOX below)
    --port-offset) PORT_OFFSET="${2:-}"; shift ;;
    --gpus) TEST_GPUS="${2:-}"; shift ;;
    --gpu-mem-gb) TEST_GPU_MEM="${2:-}"; shift ;;
    --bench) BENCH=1 ;;  # H-116: a PRODUCTION box on the bench host, beside test boxes (BENCH below)
    # REHEARSAL-REAL-SERVERS (H-89): a rehearsal's only (refused below without --rehearsal)
    --rehearsal-real-servers) REAL_SERVERS=1 ;;
    --gpu-index) GPU_INDEX="$2"; shift ;;
    --engine-probe) ENGINE_PROBE="$2"; shift ;;
    # ---- end of REHEARSAL-REAL-SERVERS (H-89)
    --kek-passphrase-file) PP_FILE="${2:-}"; shift ;;
    --keep-kek-passphrase-file) PP_KEEP=1 ;;
    --kek-passphrase-stdin) PP_STDIN=1 ;;
    --kek-passphrase-fd) PP_FD="${2:-}"; shift ;;  # the installer's own hand-on (the signed re-run)
    --kek-passphrase-remove) PP_REMOVE="${2:-}"; shift ;;  # the signed re-run's: the operator's file, never opened again
    -h|--help) sed -n 2,47p "$0"; exit 0 ;;
    -*) echo "install: unknown option $1" >&2; exit 2 ;;  # H-94 not a stop: a usage error, refused by name on every box (review L-5 of #1430): an option not understood is never acted on, nor its value taken for the bundle
    *) BUNDLE="$1" ;;
  esac
  shift
done
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
# D-831: a long step says it is alive once a minute on stderr (a watchdog sees life): alive_start before it,
# alive_stop after; die stops it too. The heartbeat ends its own sleep when stopped: a sleep left behind would hold a
# pipe open for up to a minute. indent prefixes each line as it comes (sed block-buffers into a pipe or a log)
ALIVE_PID=""
alive_start() {
  local what="$1" installer=$$
  # it also ends within a minute of the installer's own end (set -e, a signal): it never outlives the install
  ( s=""; trap 'kill "$s" 2>/dev/null; exit 0' TERM; n=0
    while kill -0 "$installer" 2>/dev/null; do
      sleep 60 & s=$!; wait "$s"; n=$((n + 1))
      kill -0 "$installer" 2>/dev/null && echo "    ... still $what ($n min)" >&2
    done
  ) >&2 & ALIVE_PID=$!
}
alive_stop() {
  [ -n "$ALIVE_PID" ] || return 0
  kill "$ALIVE_PID" 2>/dev/null || true; wait "$ALIVE_PID" 2>/dev/null || true; ALIVE_PID=""
}
die() { alive_stop; printf 'install: %s\n' "$*" >&2; exit 1; }
indent() { while IFS= read -r line || [ -n "$line" ]; do printf '    %s\n' "$line"; done; }
TB_STOP_ARG_ENV="$ENVIRONMENT"; TB_STOP_REHEARSAL="$REHEARSAL"
# TEST-BOX (H-106, the owner's ruling 7117794599): "one box per host" binds PRODUCTION, not testing. --test-box NAME
# makes this folder one of several TEST boxes on the host, each with its own folder, compose project, port offset,
# networks, cards and memory cap (tools/trialbox/testbox.py). The mode is this option, recorded in the folder's own
# deploy/site/test-box.env: a later run, update or command reads the record, never a caller's variable. A test box is
# TEST (or DEV); PRODUCTION refuses the option, and refuses a host where a test box runs (TEST-BOX: the host, below)
TEST_BOX_REC=""
[ "$TEST_BOX_SET" = 0 ] || [ -n "$TEST_BOX" ] || die "--test-box needs a NAME: an empty one is never taken for no test box (nothing was changed)"  # H-94 not a stop: a usage error, refused by name on every box
[ ! -f "$ROOT/deploy/site/test-box.env" ] || TEST_BOX_REC="$(sed -n 's/^TB_TEST_BOX=//p' "$ROOT/deploy/site/test-box.env" | tail -1)"
[ -n "$TEST_BOX" ] || TEST_BOX="$TEST_BOX_REC"  # the folder's own record speaks for a run without the option
if [ -z "$TEST_BOX_REC" ] && [ -f "$ROOT/deploy/.env" ] && grep -Eq '^(TB_TEST_BOX=[^[:space:]]|COMPOSE_PROJECT_NAME=tbt-)' "$ROOT/deploy/.env"; then
  die "deploy/.env names a test box but its record (deploy/site/test-box.env) is missing or empty: this folder is never run as the ordinary box (the host's command, units and cron files). Remove the box (tools/testboxes.sh remove NAME) and install it again (nothing was changed)"  # H-94 (3): a test box never takes the ordinary box's host files
fi
if [ -z "$TEST_BOX" ]; then
  [ -z "$PORT_OFFSET$TEST_GPUS$TEST_GPU_MEM" ] || die "--port-offset, --gpus and --gpu-mem-gb go with --test-box NAME"  # H-94 not a stop: a usage error, refused by name on every box
else
  [ "$REHEARSAL" = 0 ] || die "--test-box and --rehearsal: a test box is no rehearsal box; give one"  # H-94 not a stop: a usage error, refused by name on every box
  case "$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')" in
    ""|DEV|TEST) ;;
    *) die "--test-box makes a TEST box, not $ENVIRONMENT: a test box never holds a site's data and never becomes PRODUCTION (nothing was changed)" ;;  # H-94 (3)
  esac
  ENVIRONMENT="${ENVIRONMENT:-TEST}"; TB_STOP_ARG_ENV="$ENVIRONMENT"
  if [ -z "$TEST_BOX_REC" ] && { [ -e "$ROOT/deploy/.env" ] || [ -e "$ROOT/deploy/settings.yaml" ] || [ -e "$ROOT/deploy/updates/installed.json" ]; }; then
    die "--test-box: this folder holds a box installed as no test box: a test box starts in a folder of its own (nothing was changed)"  # H-94 (3): a site's box, with its data, is never made a test box
  fi
fi
# ---- end of TEST-BOX
# BENCH (H-116, D-1357; the integrator's ruling 7124901315): --bench marks a PRODUCTION box on the owner's bench host:
# every PRODUCTION protection stays (TB_ENV stays PRODUCTION, so no PoC leniency), and test boxes may run beside it,
# sharing nothing with it. The mark is this option, written into the folder's own deploy/site/bench-box.env (root's,
# with the install's trace: tools/trialbox/benchbox.py); a later run, start or command reads the record, never a
# caller's variable. Refused on a box that is not PRODUCTION, on a test box, and with a sending identity (ENV-BENCH)
[ -z "${TB_BENCH+x}" ] || die "TB_BENCH is set in this run's environment: the bench mark comes only from the install option --bench, written into the box's own record; unset it (nothing was changed)"  # H-94 (3): a caller's variable never puts a PRODUCTION box beside a test box
BENCH_MARK=""
if [ "$BENCH" = 1 ]; then
  [ -z "${TEST_BOX:-}" ] || die "--bench and --test-box: a test box never carries the bench mark, which is a PRODUCTION box's (nothing was changed)"  # H-94 (3)
  [ "$REHEARSAL" = 0 ] || die "--bench and --rehearsal: a rehearsal box never carries the bench mark, which is a PRODUCTION box's (nothing was changed)"  # H-94 (3)
  BENCH_ENV="$(printf '%s' "${ENVIRONMENT:-PRODUCTION}" | tr '[:lower:]' '[:upper:]')"; BENCH_NOW="$(tb_env_of "$ROOT/deploy/.env")"
  [ "$BENCH_ENV" = PRODUCTION ] && { [ -z "$BENCH_NOW" ] || [ "$BENCH_NOW" = PRODUCTION ]; } \
    || die "--bench marks a PRODUCTION box, not ${BENCH_NOW:-$BENCH_ENV}: the mark keeps every PRODUCTION protection and is never a PoC box's (nothing was changed)"  # H-94 (3)
  command -v python3 >/dev/null || die "--bench needs python3 on the host (tools/trialbox/benchbox.py writes the box's record)"  # H-94 depends (3): the record is the mark
  python3 -m tools.trialbox.benchbox may --deploy "$ROOT/deploy" >/dev/null || die "--bench: refused (above)"  # H-94 (3)
  BENCH_MARK="--bench"  # review 1484-1: the record is written at ENV-BENCH, past every refusal that says nothing was changed
fi
if [ "$BENCH" = 0 ] && { [ -e "$ROOT/deploy/site/bench-box.env" ] || [ -L "$ROOT/deploy/site/bench-box.env" ] || { [ -f "$ROOT/deploy/.env" ] && grep -Eq '^[[:space:]]*(export[[:space:]]+)?TB_BENCH[[:space:]]*=' "$ROOT/deploy/.env"; }; }; then
  command -v python3 >/dev/null || die "this box carries the bench mark, which needs python3 on the host to be checked (tools/trialbox/benchbox.py)"  # H-94 depends (3): an unchecked mark would put a PRODUCTION box beside test boxes
  BENCH_MARK="$(python3 -m tools.trialbox.benchbox check --deploy "$ROOT/deploy")" || die "the bench mark of this box is refused (above)"  # H-94 (3): a mark the install option did not write never puts a PRODUCTION box beside test boxes
fi
# ---- end of BENCH
# KEK-INPUT (H-96, F-45, H-94 (5); the integrator's ruling 7094934985): never from the environment (refused, before
# anything); from --kek-passphrase-file FILE (checked here and read again by the seal step, which removes it) or
# --kek-passphrase-stdin (read here, once). The signed re-run gets a stdin passphrase on a pipe at fd 8
# (--kek-passphrase-fd 8): never an argument, never the environment, never a file. KP_VALUE is never exported
KP_WHO=install
# ---- KEK-INPUT functions (H-96, F-45, H-94 (5); the integrator's ruling 7094934985). The same lines are in deploy/install.sh,
# deploy/box-install.sh and deploy/hardening/seal_keys.sh; a test holds the three together. The passphrase comes from
#   --kek-passphrase-file FILE  one line of a regular file (not a link) owned by root (the user that runs this), mode
#                               0600; removed once the keys are sealed, unless --keep-kek-passphrase-file
#   --kek-passphrase-stdin      one line on stdin; on a terminal it is asked twice, not shown
# and never from the environment: TB_KEK_PASSPHRASE or TB_KEK_NEW_PASSPHRASE there is refused, with or without sudo
# (sudo writes a variable it keeps, with its value, to the system journal). The value lives in KP_VALUE, never
# exported, and goes on by a pipe: never an argument, never a sudo environment, never a file. Nothing prints it.
KP_VALUE=""; KP_FILE=""
kp_die() { printf '%s: %s\n' "$KP_WHO" "$*" >&2; exit 1; }
kp_refuse_env() {  # an empty variable is dropped
  for kp_var in TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE; do
    kp_set=""
    eval "kp_set=\${$kp_var:+yes}"
    [ "$kp_set" != yes ] || { printf '%s: %s is set in the environment: refused, nothing was changed. A passphrase given by the environment can be in the system journal (sudo logs the variables it keeps, with their values): treat that passphrase as exposed and rotate it (RUNBOOK §23, rotate the KEK passphrase). Give it in a file only root can read: --kek-passphrase-file FILE (a regular file, owned by root, mode 0600), or on stdin: --kek-passphrase-stdin. Then unset %s.\n' "$KP_WHO" "$kp_var" "$kp_var" >&2; exit 2; }  # H-94 (5)
  done
  unset TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE kp_set kp_var
}
kp_check_value() {  # one line, not empty, no control character (the image and the host read it alike)
  [ -n "$KP_VALUE" ] || kp_die "the KEK passphrase from $1 is empty: nothing was changed"
  case "$KP_VALUE" in *[[:cntrl:]]*) KP_VALUE=""; kp_die "the KEK passphrase from $1 holds a line break or another control character: write it again on one line; nothing was sealed" ;; esac
}
kp_read_file() {  # H-94 (5): refused unless its folders are safe and the opened file is regular, root's, 0600, one name
  kp_fix="write the passphrase on one line of a regular file owned by root with mode 0600, in a folder only root can write (sudo install -m 0600 -o root -g root /dev/null /root/trialbox-kek.pass, then write it there); nothing was changed"
  # (M-1 of the review of #1398) the folders as their real paths: the file's own folder and every one above it owned
  # by root (the user that runs this), and writable by no one else; above the file's own folder a shared folder with
  # the sticky bit (/tmp) is allowed, as no one else can rename what is root's there
  kp_dir="$(cd -P -- "$(dirname -- "$1")" 2>/dev/null && pwd -P)" \
    || kp_die "--kek-passphrase-file $1: its folder cannot be reached: refused; $kp_fix"  # H-94 (5)
  kp_name="${kp_dir%/}/${1##*/}"; kp_d="$kp_dir"; kp_own=1
  while :; do
    kp_st="$(stat -c '%u %a' -- "$kp_d" 2>/dev/null)" || kp_die "--kek-passphrase-file $1: the folder $kp_d cannot be read: refused; $kp_fix"  # H-94 (5)
    kp_m="${kp_st#* }"
    case "${kp_st%% *}" in 0|"$(id -u)") ;; *) kp_die "--kek-passphrase-file $1: the folder $kp_d is owned by uid ${kp_st%% *}, not root: refused; $kp_fix" ;; esac  # H-94 (5)
    case "${kp_m#"${kp_m%??}"}" in
      [0145][0145]) ;;
      *) case "$kp_own:${#kp_m}:$kp_m" in 0:4:[1357]*) ;; *) kp_die "--kek-passphrase-file $1: the folder $kp_d can be written by others (mode $kp_m): refused; $kp_fix" ;; esac ;;  # H-94 (5)
    esac
    [ "$kp_d" != / ] || break
    kp_d="$(dirname -- "$kp_d")"; kp_own=0
  done
  # opened once on fd 7 and read from it; what was opened is checked through /dev/fd/7 (the same open file, never the
  # name again), and the name must still be that very file, not a link (the shell cannot open without following one)
  [ ! -L "$kp_name" ] || kp_die "--kek-passphrase-file $1 is a link: refused; $kp_fix"  # H-94 (5)
  [ -f "$kp_name" ] || kp_die "--kek-passphrase-file $1 is not a regular file: refused; $kp_fix"  # H-94 (5): never a fifo opened
  exec 7< "$kp_name"
  kp_fd="$(stat -L -c '%F|%u|%a|%h|%d:%i' /dev/fd/7 2>/dev/null)" || kp_fd=""
  kp_nm="$(stat -c '%F|%d:%i' -- "$kp_name" 2>/dev/null)" || kp_nm=""
  kp_t="${kp_fd%%|*}"; kp_r="${kp_fd#*|}"; kp_u="${kp_r%%|*}"; kp_r="${kp_r#*|}"; kp_a="${kp_r%%|*}"; kp_r="${kp_r#*|}"
  kp_h="${kp_r%%|*}"; kp_i="${kp_r#*|}"
  kp_bad=""
  case "$kp_nm" in "symbolic link|"*) kp_bad="is a link" ;; esac
  [ -n "$kp_bad" ] || case "$kp_t" in "regular file"|"regular empty file") ;; *) kp_bad="is not a regular file" ;; esac
  [ -n "$kp_bad" ] || [ "$kp_nm" = "$kp_t|$kp_i" ] || kp_bad="changed while it was opened"
  [ -n "$kp_bad" ] || [ "$kp_u" = "$(id -u)" ] || kp_bad="is owned by uid $kp_u, not root (the user that runs this)"
  [ -n "$kp_bad" ] || [ "$kp_a" = 600 ] || kp_bad="has mode $kp_a, not 0600"
  [ -n "$kp_bad" ] || [ "$kp_h" = 1 ] || kp_bad="has $kp_h names (hard links), not one"
  if [ -n "$kp_bad" ]; then exec 7<&-; kp_die "--kek-passphrase-file $1 $kp_bad: refused; $kp_fix"; fi  # H-94 (5)
  KP_VALUE=""; IFS= read -r KP_VALUE <&7 || [ -n "$KP_VALUE" ] || :
  kp_rest="$(wc -c <&7)"; exec 7<&-
  if [ "$kp_rest" != 0 ]; then KP_VALUE=""; kp_die "--kek-passphrase-file $1 holds a line break or another control character: write it again on one line; nothing was sealed"; fi  # H-94 (5)
  KP_FILE="$kp_name"
  kp_check_value "--kek-passphrase-file $1"
}
kp_read_stdin() {
  KP_VALUE=""
  if [ -t 0 ]; then
    stty -echo 2>/dev/null; printf 'KEK passphrase (12 characters or more, not shown): ' >&2; IFS= read -r KP_VALUE || :
    printf '\nthe same again: ' >&2; kp_again=""; IFS= read -r kp_again || :; stty echo 2>/dev/null; printf '\n' >&2
    [ "$KP_VALUE" = "$kp_again" ] || { KP_VALUE=""; kp_again=""; kp_die "the two passphrases differ: nothing was changed"; }
    kp_again=""
  else
    IFS= read -r KP_VALUE || [ -n "$KP_VALUE" ] || kp_die "--kek-passphrase-stdin: nothing on stdin; nothing was changed"
  fi
  kp_check_value "stdin"
}
kp_remove_file() {  # unlinked, never written through its name (a link is taken away, never what it names)
  rm -f -- "$1"; [ ! -e "$1" ] && [ ! -L "$1" ] || kp_die "the passphrase file $1 could not be removed: remove it yourself"  # H-94 (5)
}
# ---- end of KEK-INPUT functions
kp_refuse_env
case "$PP_FILE:$PP_STDIN:$PP_FD" in
  :0:|/*:0:|:1:|:0:[3-9]) ;;
  ?*:0:) die "--kek-passphrase-file: give the file's full path (/root/...): nothing was changed" ;;  # H-94 (5)
  *) die "--kek-passphrase-file, --kek-passphrase-stdin, --kek-passphrase-fd 3-9: give one; nothing was changed" ;;  # H-94 (5)
esac
case "$PP_REMOVE:$PP_FD" in
  :*|/*:?*) ;;
  *) die "--kek-passphrase-remove goes with --kek-passphrase-fd and a full path (the installer's own hand-on)" ;;  # H-94 (5)
esac
[ "$PP_KEEP" = 0 ] || [ -n "$PP_FILE$PP_REMOVE" ] || die "--keep-kek-passphrase-file goes with --kek-passphrase-file"  # H-94 (5)
if [ -n "$PP_FILE" ]; then kp_read_file "$PP_FILE"
elif [ "$PP_STDIN" = 1 ]; then kp_read_stdin
elif [ -n "$PP_FD" ]; then
  IFS= read -r KP_VALUE <&"$PP_FD" || [ -n "$KP_VALUE" ] || die "--kek-passphrase-fd $PP_FD: no passphrase there"  # H-94 (5)
  eval "exec $PP_FD<&-"
  kp_check_value "the installer's hand-on"
  KP_FILE="$PP_REMOVE"  # the operator's file the first run read: removed once sealed, never opened here
fi
# ---- end of KEK-INPUT
# ENV-EARLY (D-1365, re-check of #1175): an environment that is not one of the four stops here, at argument parsing,
# before anything is loaded, linked, made or copied: --environment, or (neither it nor --rehearsal given) a TB_ENV an
# existing deploy/.env already holds, read without changing anything. Read as the settings step reads them
EARLY_ENV="$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')"
EARLY_FROM="--environment"
if [ -z "$EARLY_ENV" ] && [ "$REHEARSAL" != 1 ] && [ -f "$ROOT/deploy/.env" ] && [ -r "$ROOT/deploy/.env" ]; then
  EARLY_ENV="$(tb_env_of "$ROOT/deploy/.env")"
  EARLY_FROM="TB_ENV in deploy/.env"
fi
case "$EARLY_ENV" in
  ""|DEV|TEST|VALIDATION|PRODUCTION) ;;
  *) stop_or_warn early-env "" "the environment '$EARLY_ENV' ($EARLY_FROM) is not DEV, TEST, VALIDATION or PRODUCTION: nothing was loaded or written" ;;
esac
# ---- end of ENV-EARLY
# REHEARSAL-REAL-SERVERS (H-89): the real model servers on a rehearsal box whose card and driver are not the profile's
# (the bench host: whole B200-class cards on a driver below gpu.driver_min). One explicit command line, never a
# default or an environment variable:
#   deploy/install.sh <bundle> --rehearsal --rehearsal-real-servers --gpu rtxpro6000|rtx5090 --gpu-index N --engine-probe FILE
# Each opened profile is held to its own card's memory on the bench's card (its utilisations scaled down, D-1087)
# Without --rehearsal each new option is refused here, before anything is checked or written; without the options
# the three refusals (the driver, the card, the record) stand as before. tools/rehearsal_real.py decides each step;
# the box says "rehearsal: driver below the minimum, not this profile's card, not valid for a site"
if [ "$REHEARSAL" != 1 ]; then
  RRS_IGNORED="the option (ignored)"
  [ "$REAL_SERVERS" = 0 ] || { stop_or_warn --rc 2 rrs-without-rehearsal "$RRS_IGNORED" "--rehearsal-real-servers is for a rehearsal box only: give --rehearsal too (nothing was checked or written)"; REAL_SERVERS=0; }
  [ -z "$GPU_INDEX" ] || { stop_or_warn --rc 2 gpu-index-without-rehearsal "$RRS_IGNORED" "--gpu-index is for a rehearsal with real servers only (--rehearsal --rehearsal-real-servers); nothing was checked or written"; GPU_INDEX=""; }
  [ -z "$ENGINE_PROBE" ] || { stop_or_warn --rc 2 engine-probe-without-rehearsal "$RRS_IGNORED" "--engine-probe is for a rehearsal with real servers only (--rehearsal --rehearsal-real-servers); nothing was checked or written"; ENGINE_PROBE=""; }
elif [ "$REAL_SERVERS" != 1 ]; then
  [ -z "$GPU_INDEX$ENGINE_PROBE" ] || { stop_or_warn --rc 2 rrs-options-without-rrs "the options (ignored)" "--gpu-index and --engine-probe go with --rehearsal-real-servers; nothing was checked or written"; GPU_INDEX=""; ENGINE_PROBE=""; }
else
  # H-94: each check of the bench-only options, on a PoC box, drops the real servers: the install goes on as a plain
  # rehearsal (the model stand-ins), and the checks after the first are not asked again
  rrs_drop() {  # KEY WHAT: stop_or_warn, then no real servers
    stop_or_warn "$1" "--rehearsal-real-servers (a plain rehearsal: the model stand-ins)" "$2"
    REAL_SERVERS=0; GPU_INDEX=""; ENGINE_PROBE=""
  }
  [ "$GPU_SET" = 1 ] || rrs_drop rrs-profile-missing "--rehearsal-real-servers: name the profile: --gpu rtxpro6000 or --gpu rtx5090 (each held to its own card's memory)"
  [ "$REAL_SERVERS" = 0 ] || case "$GPU" in
    rtxpro6000|rtx5090) ;;
    dgpu48|gb10) die "--rehearsal-real-servers: the $GPU profile is not opened for a rehearsal with real servers (docs/handover/rehearsal-real-servers-h89-2026-11-22.md says why)" ;;  # H-94 (2): a profile not opened for the real servers is not shown to run on this card (lane H lead)
    *) rrs_drop rrs-profile-unknown "--rehearsal-real-servers: name the profile: --gpu rtxpro6000 or --gpu rtx5090 (each held to its own card's memory)" ;;
  esac
  [ "$REAL_SERVERS" = 0 ] || [ -z "$TIER" ] || rrs_drop rrs-tier "--rehearsal-real-servers is no tier install: drop --tier"
  [ "$REAL_SERVERS" = 0 ] || [ "$MODE_SET" = 0 ] || [ "$MODE" = gpu ] || rrs_drop rrs-mode "--rehearsal-real-servers needs the GPU: drop --mode $MODE"
  [ "$REAL_SERVERS" = 0 ] || case "$GPU_INDEX" in ""|*[!0-9]*) rrs_drop rrs-gpu-index "--rehearsal-real-servers: --gpu-index N names the one whole card (0, 1, ...), never all" ;; esac
  [ "$REAL_SERVERS" = 0 ] || { [ -n "$ENGINE_PROBE" ] && [ -f "$ENGINE_PROBE" ]; } || rrs_drop rrs-engine-probe "--rehearsal-real-servers: --engine-probe FILE, the engine probe's result taken on that card (tools/engine_probe.py run), is missing"
  [ "$REAL_SERVERS" = 0 ] || ENGINE_PROBE="$(readlink -f "$ENGINE_PROBE")"
  # on a PoC box before the override's check: a run that drops the real servers hands its stand-ins on to the signed
  # re-run, which drops them again here first. Elsewhere master's order (after the environment's check), so
  # master's first words (review L-1)
  [ "$REAL_SERVERS" = 0 ] || command -v python3 >/dev/null || ! tb_poc_box || rrs_drop rrs-python3 "--rehearsal-real-servers needs python3 on the host (tools/rehearsal_real.py)"
  # the script's own override is never handed to the signed re-run (H-89, above the exec); a caller's own stays
  # refused on every box (the lane H lead's list for H-94; H94-07 asks the integrator)
  [ "$REAL_SERVERS" = 0 ] || [ -z "${TB_COMPOSE_OVERRIDE:-}" ] || die "--rehearsal-real-servers writes the box's compose override itself: unset TB_COMPOSE_OVERRIDE"  # H-94 (3): a caller's override on the real servers is a state a site must never get (lane H lead)
  if [ "$REAL_SERVERS" = 1 ] && [ -n "$ENVIRONMENT" ] && [ "$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')" != VALIDATION ]; then
    [ "$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')" != PRODUCTION ] || die "--rehearsal makes a VALIDATION box, not $ENVIRONMENT"  # H-94 (3): a rehearsal box never becomes PRODUCTION
    stop_or_warn rrs-environment "--environment $ENVIRONMENT (a rehearsal box is VALIDATION)" "--rehearsal makes a VALIDATION box, not $ENVIRONMENT"
    ENVIRONMENT=""; TB_STOP_ARG_ENV=""
  fi
  [ "$REAL_SERVERS" = 0 ] || command -v python3 >/dev/null || rrs_drop rrs-python3 "--rehearsal-real-servers needs python3 on the host (tools/rehearsal_real.py)"
  [ "$REAL_SERVERS" = 0 ] || MODE=gpu
fi
# ---- end of REHEARSAL-REAL-SERVERS (H-89)
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
# OPS-004 (D-570): after an install from a bundle the shipped files under deploy/ are links into ../current
# (tools/host_tree.py). A container that gets deploy/ alone sees them dangle (found by the box rehearsal: the measured
# record, the image lock, the compose files). Every container started on deploy/ also gets the release tree where
# those links point: /current beside a mount at /d, /app/current beside one at /app/deploy. A checkout has no
# release tree and gets nothing.
tree_args() {
  TREE_D=(); TREE_APP=()
  if [ -d "$ROOT/current" ]; then
    local tree; tree="$(readlink -f "$ROOT/current")"
    TREE_D=(-v "$tree:/current:ro"); TREE_APP=(-v "$tree:/app/current:ro")
  fi
}
PUBKEY="${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}"

if [ "$CHECK" = 1 ]; then exec sh "$ROOT/deploy/check_host.sh" "$@"; fi

# ------------------------------------------------------------------------------------------------ ClinicalTrials.gov
# D-140 (owner, 2026-11-09): each hospital chooses; the default is offline. live = the box may reach
# clinicaltrials.gov:443; offline = no outbound access, the trials come from the reference data pack in each signed
# update. live on a host without internet is refused back to offline. TB_CTGOV_PROBE=ok|fail stands in for the
# network in the tests.
ctgov_internet() {
  case "${TB_CTGOV_PROBE:-}" in ok) return 0 ;; fail) return 1 ;; esac
  if command -v curl >/dev/null; then curl -fsS -o /dev/null -m 8 https://clinicaltrials.gov/api/v2/version 2>/dev/null
  else timeout 8 bash -c ': </dev/tcp/clinicaltrials.gov/443' 2>/dev/null; fi
}
ctgov_question() {
  cat <<'EOQ'
  ClinicalTrials.gov: may this box reach clinicaltrials.gov on the internet?
    offline = no (default). TrialBox uses the copy that comes with each update: no outbound access; the data are as of the update.
    live    = yes. TrialBox asks ClinicalTrials.gov directly: always current; one outbound address; no patient data is sent.
  ClinicalTrials.gov：この機器からインターネット上の clinicaltrials.gov に接続してよいですか？
    offline = いいえ（既定）。更新のたびに届く写しを使います。外部へは接続しません。データは更新の時点のものです。
    live    = はい。TrialBox が ClinicalTrials.gov に直接問い合わせます。常に最新。外部への接続先は1か所で、患者データは送りません。
  ClinicalTrials.gov：本機可以連上網際網路的 clinicaltrials.gov 嗎？
    offline = 不可以（預設）。使用每次更新附帶的資料副本：不對外連線；資料為該次更新當時的版本。
    live    = 可以。TrialBox 直接查詢 ClinicalTrials.gov：資料隨時最新；只對外連一個位址；不傳送病人資料。
EOQ
}
if [ "$CTGOV_CHECK" = 1 ]; then
  if ctgov_internet; then echo "internet: yes (live is possible; the default stays offline)"
  else echo "internet: no (offline only)"; fi
  exit 0
fi
case "$CTGOV" in ""|live|offline) ;; *) stop_or_warn --rc 2 ctgov-value "--ctgov $CTGOV (the box's mode, else offline)" "--ctgov must be live or offline"; CTGOV="" ;; esac

# ------------------------------------------------------------------------------------------------ 0. tier
# D-138: before anything is loaded or started. The record rule is tools/serving_config.py's (D-112, D-124).
# TB_TIER_TEST_ARCH / TB_TIER_TEST_CARD stand in for uname and nvidia-smi in the tests only, TB_TEST_MEM_KIB for
# /proc/meminfo's MemTotal (card 10E-5: a GB10 under 96 GiB is not tier medium).
TIER_RECORD=""
TIER_DROPPED="--tier $TIER (dropped: the profile is detected, as an install without a tier)"
if [ -n "$TIER" ]; then
  [ "$GPU_SET" = 0 ] || stop_or_warn tier-and-gpu "--gpu $GPU (the tier names its profile)" "--tier and --gpu: give one (a tier names its GPU profile)"
  [ "$MODE_SET" = 0 ] || [ "$MODE" = gpu ] || stop_or_warn tier-mode "--mode $MODE (a tier is the GPU)" "--tier needs the GPU: drop --mode $MODE"
  if ! command -v python3 >/dev/null; then
    stop_or_warn tier-python3 "$TIER_DROPPED" "--tier needs python3 on the host to read the serving records"
    TIER=""; [ "$TIER_CHECK" = 0 ] || exit 3  # H-94 not a stop: --tier-check's own answer (no), not an install
  fi
fi
if [ -n "$TIER" ]; then
  set +e
  TIER_OUT="$(python3 "$ROOT/tools/tiers.py" check --tier "$TIER" --deploy "$ROOT/deploy" \
    ${TB_TIER_TEST_ARCH:+--arch "$TB_TIER_TEST_ARCH"} ${TB_TIER_TEST_CARD:+--card "$TB_TIER_TEST_CARD"} \
    ${TB_TEST_MEM_KIB:+--mem-kib "$TB_TEST_MEM_KIB"})"
  rc=$?
  set -e
  if [ "$rc" != 0 ]; then  # the reason is on stderr: what is missing and how to get a record
    [ "$TIER_CHECK" = 0 ] || exit 3  # H-94 not a stop: --tier-check's own answer (no), not an install
    stop_or_warn --rc 3 --silent tier-record "$TIER_DROPPED" "tier $TIER may not be installed on this machine (the reason above)"
    TIER=""
  else
    GPU="${TIER_OUT%% *}"; TIER_RECORD="${TIER_OUT#* }"; MODE=gpu
    echo "    tier $TIER: $GPU profile, measured record $TIER_RECORD"
    [ "$TIER_CHECK" = 0 ] || exit 0
  fi
elif [ "$TIER_CHECK" = 1 ]; then
  # H-94 not a stop: a usage error, refused by name on every box (review M-3 of #1430): a run that asks only a check
  # never becomes an install
  die "--tier-check needs --tier small|medium|large"
fi
# H-94 (1): no bundle, no signature that holds: nothing is loaded from nothing
[ -n "$BUNDLE" ] || die "usage: deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--yes]"  # H-94 (1)
[ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"  # H-94 (1)
# ---- MODEL-PACK (H-95): a release in two packs. The model pack is --model-pack FILE, else the file beside the bundle
# whose signed manifest has the sha256 the software pack names (tools/packs.py find; a file's name decides nothing).
# None for a whole bundle. Whether the pair holds is the verifier's (apply_update.sh, H-94 (1)), before any load
if [ -z "$MODEL_PACK" ] && command -v python3 >/dev/null; then
  MODEL_PACK="$(python3 "$ROOT/tools/packs.py" find "$BUNDLE" 2>/dev/null || true)"
fi
[ -z "$MODEL_PACK" ] || [ -f "$MODEL_PACK" ] || die "no such model pack: $MODEL_PACK"  # H-94 (1)
# ---- end of MODEL-PACK
# H-70: the host baseline near the end (deploy/hardening/apply.sh) refuses SSH=off from an SSH session; ask it now,
# when it will run (root, deploy/site/hardening.conf), so an install over SSH stops before anything is loaded or written.
# --ssh-off-over-ssh (or TB_SSH_OFF_OVER_SSH=yes, which sudo may drop) goes ahead, and is handed on to apply.sh
# H-94: on a PoC box the warning skips the host baseline's apply step near the end (HB_SKIP), so the session stays
HB_OVER=(); [ "$SSH_OFF_OVER_SSH" = 1 ] && HB_OVER=(--ssh-off-over-ssh)
HB_SKIP=0
if [ "$(id -u)" = 0 ] && [ -f "$ROOT/deploy/site/hardening.conf" ]; then
  sh "$ROOT/deploy/hardening/apply.sh" --conf "$ROOT/deploy/site/hardening.conf" ${HB_OVER[@]+"${HB_OVER[@]}"} check \
    || { stop_or_warn host-baseline-ssh "the host baseline (input firewall and SSH: deploy/hardening/apply.sh all)" "the host baseline would cut this SSH session (above): nothing was loaded or written"; HB_SKIP=1; }
fi

# ------------------------------------------------------------------------------------------------ 1. host
say "host"
# D-1091 (H94-03): these protect none of the five, so on a PoC box they warn; every step that runs Docker then fails
# where it runs (the bundle's load first: kept refusal 1, nothing is acted on that was not loaded)
NO_DOCKER="every step that runs Docker (each fails where it runs)"
command -v docker >/dev/null || stop_or_warn docker-missing "$NO_DOCKER" "Docker is not installed (Docker Engine 27+ with the compose plugin; docs/SECURITY.md)"
docker info >/dev/null 2>&1 || stop_or_warn docker-not-running "$NO_DOCKER" "Docker is not running (sudo systemctl start docker)"
docker compose version >/dev/null 2>&1 || stop_or_warn compose-missing "$NO_DOCKER" "the docker compose plugin is missing"
# HOST-PYTHON (D-831): the host steps run python3 -m tools.... (anchors, pre-start, doctor, the secrets); the modules
# they import at the top are checked here, before anything loads, not 20 minutes in. module:Debian package, one per
# word. Not cryptography: the host python3 may lack it (libs/tb_common/kek.py). Without python3 those steps say so.
HOST_PY_MODULES="yaml:python3-yaml"
if command -v python3 >/dev/null; then
  HOST_PY_MISSING=""
  for pair in $HOST_PY_MODULES; do
    python3 -c "import ${pair%%:*}" 2>/dev/null || HOST_PY_MISSING="$HOST_PY_MISSING ${pair#*:}"
  done
  # D-1091: protects none of the five; on a PoC box the host steps that import them fail where they run
  [ -z "$HOST_PY_MISSING" ] || stop_or_warn host-python-modules "the host steps that import them (each fails where it runs)" "the host's python3 lacks what the installer needs:$HOST_PY_MISSING (Debian/Ubuntu: sudo apt-get install -y$HOST_PY_MISSING); install it, then re-run; nothing was changed"
fi
# ---- end of HOST-PYTHON
if [ "$MODE" = auto ]; then
  if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then MODE=gpu; else MODE=stub; fi
fi
case "$MODE" in
  # H-94 (2): no card the driver can see
  gpu) command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 || die "--mode gpu but nvidia-smi finds no GPU (driver + container toolkit; docs/SECURITY.md)"
       docker info 2>/dev/null | grep -qi nvidia || echo "install: warning: Docker lists no nvidia runtime; the model service may not start" >&2 ;;
  stub) echo "    no GPU: structured criteria only (FEAS, NAV, COHORT); note criteria wait for a GPU or a pinned cloud model" ;;
  *) stop_or_warn mode-value "--mode $MODE (stub)" "--mode must be gpu or stub"; MODE=stub ;;  # D-1091: protects none of the five
esac
# GPU profile (D-95, D-124; deploy/gpu_profile.sh detects it from the card): rtxpro6000 = judge and verifier both
# resident on a 96 GB card at 32k; gb10 = the same pair resident on a 128 GB DGX Spark at 16k (a Spark under 96 GiB
# is gb10-64, refused: D-1335); rtx5090 = the same pair on one
# 32 GB card with the sleep swap at 8k; all three exclude on a note only when both models agree. rtx4090 = the judge
# alone on a 24 GB card, note answers never exclude; default = base llm-service
if [ "$MODE" = gpu ] && [ "$GPU" = auto ]; then
  GPU="$(sh "$ROOT/deploy/gpu_profile.sh")"
fi
# card 10E-5 (D-1335): gb10 is the 128 GB Spark. A host under 96 GiB of memory is the 64 GB class however gb10 was
# chosen (detected, --gpu, TB_GPU_PROFILE, --tier medium, a rehearsal): refused below. TB_TEST_MEM_KIB stands in for
# /proc/meminfo's MemTotal in the tests only
if [ "$MODE" = gpu ] && [ "$GPU" = gb10 ]; then
  GPU="$(sh "$ROOT/deploy/gpu_profile.sh" memory-class "${TB_TEST_MEM_KIB:-}")"
fi
# H-94: on a PoC box three of these five warn and the box goes on without its model servers (--mode stub)
GPU_STUB="the model servers (the box goes on as --mode stub: structured criteria only)"
case "$GPU" in  # a B200 is never an appliance (D-211, D-409): two MIG instances on a platform, RUNBOOK §17
  shared-quota) stop_or_warn gpu-shared-quota "$GPU_STUB" "this card has MIG on (shared-quota): install.sh does not serve it; use deploy/platform (RUNBOOK §17)"; MODE=stub; GPU=default ;;
  b200-no-mig) stop_or_warn gpu-b200-no-mig "$GPU_STUB" "a B200 serves TrialBox only as two MIG instances: enable MIG, make the two instances, use deploy/platform (RUNBOOK §17)"; MODE=stub; GPU=default ;;
  gb10-64) die "this DGX Spark has under 96 GiB of memory (the 64 GB class): TrialBox does not serve the model pair on it. The gb10 profile is sized for 128 GB (its model servers alone are capped at 74 GiB), and no profile of the 64 GB class is measured, so none is guessed (card 10E-5, D-1335). Install with --mode stub (structured criteria only; note criteria wait for a GPU), or use a 128 GB Spark or another measured box" ;;  # H-94 (2): the 64 GB class cannot hold the pair (D-1335)
  arm64-dgpu) stop_or_warn gpu-arm64-dgpu "$GPU_STUB" "an Arm 64-bit host with a discrete card that is not a GB10 has no TrialBox profile (unmeasured, root review 24): install with --mode stub, or see RUNBOOK §28"; MODE=stub; GPU=default ;;
  # cards 24-5 and 24-6: the 48 GB draft is never installed, whatever is set; TB_UNMEASURED_DGPU48_MEASURING_RUN=1 is
  # honoured by its measuring run alone (tools/dgpu48.py), which starts only the model servers and installs nothing
  dgpu48) die "dgpu48 is a DRAFT, UNMEASURED 48 GB profile: no install serves it. Its one use is the measuring run (TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure, RUNBOOK §29)" ;;  # H-94 (2): a draft, unmeasured profile is not shown to run on any card
esac
case "$GPU" in auto|default|rtxpro6000|gb10|rtx5090|rtx4090) ;; *) stop_or_warn gpu-value "$GPU_STUB" "--gpu must be rtxpro6000, gb10, rtx5090, rtx4090 or default"; MODE=stub; GPU=default ;; esac  # D-1091
# REHEARSAL-REAL-SERVERS (H-89): the box may be a rehearsal box (the rule of REHEARSAL below, read before the GPU
# check, so a site box is refused before any allowance), and the one card named carries the pair. The GPU check then
# runs under the mark: the driver below the minimum is a WARN only with a passed probe of this card, this driver and
# the pinned image (tools/images_lock.py host --rehearsal-real-servers); anything else FAILs as before
RRS_HOST=(); RRS_REC=""
if [ "$REAL_SERVERS" = 1 ]; then
  # H-94 (3): a site box (which may hold real patient data) is never made a rehearsal box
  python3 -m tools.rehearsal_real box --deploy "$ROOT/deploy" || die "--rehearsal-real-servers: refused (above): nothing was loaded or written"
  for f in "deploy/site/serving_config.$GPU.json" "deploy/measured/serving_config.$GPU.json"; do
    [ -f "$f" ] && { RRS_REC="$f"; break; }
  done
  # H-94 (2): the card named cannot carry the pair
  python3 -m tools.rehearsal_real card --profile "$GPU" --gpu-index "$GPU_INDEX" ${RRS_REC:+--record "$RRS_REC"} | sed 's/^/    /' \
    || die "--rehearsal-real-servers: the card at index $GPU_INDEX cannot carry the pair (above): nothing was loaded or written"
  RRS_HOST=(--rehearsal-real-servers --engine-probe "$ENGINE_PROBE" --gpu-index "$GPU_INDEX")
  export TB_COMPOSE_OVERRIDE="$ROOT/deploy/site/rehearsal-real-servers.yml"
fi
# ---- end of REHEARSAL-REAL-SERVERS (H-89)
# D-348: the vLLM image of deploy/images.lock must run here (its architecture, the driver its CUDA needs, the GPU's
# compute capability), before anything is loaded: a CUDA 13 image on an older driver would only fail at start
if [ "$MODE" = gpu ]; then
  if command -v python3 >/dev/null; then
    # H-94 (2): the driver, the architecture or the card's compute capability cannot run the pinned image
    sh "$ROOT/deploy/check_host.sh" --gpu-only --gpu "$GPU" ${RRS_HOST[@]+"${RRS_HOST[@]}"} 2>&1 | sed 's/^/    /' \
      || die "this GPU host cannot run the vLLM image of deploy/images.lock (FAIL above); nothing was changed"
  else
    echo "install: warning: no python3: the GPU host is not checked against deploy/images.lock" >&2
  fi
fi
[ -f "$PUBKEY" ] || die "vendor public key missing: copy vendor_ed25519.pub (from the vendor, out of band) to $PUBKEY"  # H-94 (1): no key, no signature check
# ---- SIDECAR (H-22, D-996): make_bundle.sh names each file bare (the bundle, the bootstrap and its .sig), so the
# check works wherever the stick is mounted; only the bundle's own line is checked here
if [ -f "$BUNDLE.sha256" ]; then
  SUM_LINE="$(awk -v n="$(basename "$BUNDLE")" '$2 == n || $2 == "*" n' "$BUNDLE.sha256")"
  # H-94 (1): the bundle's hash
  [ -n "$SUM_LINE" ] || die "$(basename "$BUNDLE").sha256 does not name $(basename "$BUNDLE") (a sidecar from before D-996 names the vendor's own path): compare its sum with: sha256sum $BUNDLE"
  (cd "$(dirname "$BUNDLE")" && printf '%s\n' "$SUM_LINE" | sha256sum -c - >/dev/null) || die "bundle checksum mismatch: $(basename "$BUNDLE") is not the file the vendor handed over"  # H-94 (1)
fi
# H-95: the model pack's own sidecar, the same way
if [ -n "$MODEL_PACK" ] && [ -f "$MODEL_PACK.sha256" ]; then
  SUM_LINE="$(awk -v n="$(basename "$MODEL_PACK")" '$2 == n || $2 == "*" n' "$MODEL_PACK.sha256")"
  [ -n "$SUM_LINE" ] || die "$(basename "$MODEL_PACK").sha256 does not name $(basename "$MODEL_PACK"): compare its sum with: sha256sum $MODEL_PACK"  # H-94 (1)
  (cd "$(dirname "$MODEL_PACK")" && printf '%s\n' "$SUM_LINE" | sha256sum -c - >/dev/null) || die "model pack checksum mismatch: $(basename "$MODEL_PACK") is not the file the vendor handed over"  # H-94 (1)
fi
# ---- end of SIDECAR
echo "    docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), model profile: $MODE, gpu: $GPU, vendor key: $PUBKEY"

# INSTALL-LOCK (review 2 of #1305, M-2): one installer at a time on this folder, taken here, before the first thing is
# written. A second run while one holds it refuses and changes or removes nothing: its project cleanup would take down
# the first run's containers while they start. flock on the deploy folder itself, opened read-only: no lock file is
# written, and the lock ends with the installer's process, so a killed run leaves none behind. The run from the signed
# tree (exec below) keeps the lock it inherits on fd 9: it is not taken twice
# H-94: on a PoC box with no flock, or a folder that cannot be opened, the warning skips the lock (LOCKED=0)
INSTALL_LOCK="$(readlink -f "$ROOT/deploy")"
LOCKED=1; NO_LOCK="the install lock (a second installer on this folder is not kept out)"
command -v flock >/dev/null || { stop_or_warn install-lock-flock "$NO_LOCK" "flock (util-linux) is missing, so a second installer could not be kept out: install util-linux, then re-run; nothing was changed"; LOCKED=0; }
if [ "$LOCKED" = 1 ] && [ "$(readlink -f "/proc/$$/fd/9" 2>/dev/null)" != "$INSTALL_LOCK" ]; then
  exec 9<"$INSTALL_LOCK" || { stop_or_warn install-lock-open "$NO_LOCK" "the deploy folder $INSTALL_LOCK cannot be opened for the install lock; nothing was changed"; LOCKED=0; }
fi
# D-1091: protects none of the five. On a PoC box the warning skips this run's project cleanup (SECOND_RUN), so the
# other run's containers are not taken down by it
SECOND_RUN=0
[ "$LOCKED" = 0 ] || flock -n 9 || { stop_or_warn second-installer "this run's project cleanup (the other run's containers are kept)" "another deploy/install.sh is running on this folder (it holds $INSTALL_LOCK): let it finish, then re-run; nothing was changed or removed"; SECOND_RUN=1; }
# ---- end of INSTALL-LOCK
# TEST-BOX (H-106): the host. A test box's record names its own project (its volumes, the site keys among them, and
# its networks); it is exported here so every command of this run, compose's and the script's own, is the box's. No
# secret of a test box goes where another box's could: no caller's secrets folder, and never the host's KEK folder
TB_PROJECT=""  # H-106: the script's own (a test box's record), never a caller's
# HOST-LOCK (H-106, OCR 1452-2, 1452-13): one box's install at a time on this host, from the check of the host's boxes
# to the install's end (its volumes exist by then), so two installs started together never both pass the check. A lock
# held by another install is waited for, never a stop. The lock lives in a folder of root's own under /run (not the
# shared /run/lock, where any account can make the file first); a lock that cannot be taken, or a wait of an hour,
# is said on the console and the install goes on. An install not run as root (a developer's) takes no lock
TB_HOST_LOCK_DIR=/run/trialbox-boxes TB_ME="$(id -u)"
TB_HOST_LOCK="$TB_HOST_LOCK_DIR/host.lock"
if { [ -n "${TEST_BOX:-}" ] || ! tb_poc_box; } && [ "$TB_ME" = 0 ] \
    && [ "$(readlink -f "/proc/$$/fd/6" 2>/dev/null)" != "$TB_HOST_LOCK" ]; then
  if command -v flock >/dev/null && install -d -m 0700 -o "$TB_ME" "$TB_HOST_LOCK_DIR" 2>/dev/null \
      && [ ! -L "$TB_HOST_LOCK_DIR" ] && [ "$(stat -c %u "$TB_HOST_LOCK_DIR")" = "$TB_ME" ] && { exec 6>>"$TB_HOST_LOCK"; } 2>/dev/null; then
    # the note goes to a terminal only: a captured output is the same whether this run waited or not
    flock -n 6 || { [ ! -t 2 ] || echo "install: note: another box's install holds this host's lock ($TB_HOST_LOCK): waiting for it" >&2
      flock -w 3600 6 || echo "install: warning: waited an hour for this host's box lock ($TB_HOST_LOCK): going on without it; an install started beside this one is not kept out" >&2; }
  else
    echo "install: warning: this host's box lock ($TB_HOST_LOCK) could not be taken (flock, or a folder of root's own there): going on without it; an install started beside this one is not kept out" >&2
  fi
fi
if [ -n "${TEST_BOX:-}" ]; then
  [ -z "${TB_SECRETS_HOST_DIR:-}" ] || die "--test-box: TB_SECRETS_HOST_DIR is set in the environment: a test box keeps its keys in its own project's volume, never in a folder a caller names (another box's could be it). Unset it (nothing was changed)"  # H-94 (5)
  [ -z "${TB_KEK_BACKEND:-}" ] && [ -z "$KP_VALUE" ] && [ ! -e "$ROOT/deploy/site/hardening.conf" ] \
    || die "--test-box: a test box's site keys are never sealed: the KEK folder (/run/trialbox) and the host baseline are the host's, one for every box. Drop TB_KEK_BACKEND, the KEK passphrase options and deploy/site/hardening.conf (nothing was changed)"  # H-94 (5)
  command -v python3 >/dev/null || die "--test-box needs python3 on the host (tools/trialbox/testbox.py keeps the box's record)"  # H-94 depends (5): the record names the project that keeps this box's keys apart
  TB_PROJECT="$(python3 -m tools.trialbox.testbox record --deploy "$ROOT/deploy" --name "${TEST_BOX:-}" ${PORT_OFFSET:+--port-offset "$PORT_OFFSET"} ${TEST_GPUS:+--gpus "$TEST_GPUS"} ${TEST_GPU_MEM:+--gpu-mem-gb "$TEST_GPU_MEM"})" \
    || die "--test-box: refused (above)"  # H-94 depends (5): no record, no project of the box's own
  export COMPOSE_PROJECT_NAME="$TB_PROJECT"
  TB_OTHERS="$(python3 -m tools.trialbox.testbox others --deploy "$ROOT/deploy")" \
    || die "--test-box: the container engine cannot list the boxes on this host, so a PRODUCTION box beside this one cannot be ruled out (is Docker running?)"  # H-94 (3)
  TB_PROD="$(printf '%s\n' "$TB_OTHERS" | awk -F'\t' '$2 == "production" {print $1}' | tr '\n' ' ')"
  [ -z "${TB_PROD// /}" ] || die "--test-box: this host holds a PRODUCTION box (project ${TB_PROD% }): a test box is never installed beside it (data would be typed into the wrong box); nothing was changed"  # H-94 (3)
  echo "install: note: test box ${TEST_BOX:-} (project $TB_PROJECT); other boxes on this host: $(printf '%s\n' "$TB_OTHERS" | awk -F'\t' 'NF {printf "%s%s (%s)", s, $1, $2; s=", "}' | grep . || echo none)" >&2
elif ! tb_poc_box && command -v python3 >/dev/null; then
  # PRODUCTION, as before, but never beside a test box (whatever any variable says: read from the engine). An engine
  # that cannot be asked leaves the install as before: its next Docker step stops it
  # OCR 1452-2: only an engine that cannot be asked at all (exit 3) leaves the install as before; any other failure of
  # the listing refuses, and a test box's project counts whatever its folder says (gone, unreadable, a broken record)
  TB_RC=0; TB_OTHERS="$(python3 -m tools.trialbox.testbox others --deploy "$ROOT/deploy" 2>/dev/null)" || TB_RC=$?
  [ "$TB_RC" = 0 ] || [ "$TB_RC" = 3 ] || die "the boxes on this host could not be listed (tools/trialbox/testbox.py others, exit $TB_RC): a PRODUCTION box is never installed beside a test box it could not see; nothing was changed"  # H-94 (3)
  if [ "$TB_RC" = 0 ]; then
    TB_TESTS="$(printf '%s\n' "$TB_OTHERS" | awk -F'\t' '$2 == "test" || $1 ~ /^tbt-/ {print $1}' | tr '\n' ' ')"
    # H-116: a bench box (PRODUCTION, its mark the install option's) may have test boxes beside it
    [ -z "$BENCH_MARK" ] || { echo "install: note: a bench box (PRODUCTION · BENCH); test boxes beside it on this host: ${TB_TESTS:-none}" >&2; TB_TESTS=""; }
    [ -z "${TB_TESTS// /}" ] || die "this host runs test boxes (${TB_TESTS% }): a PRODUCTION box is installed on a host of its own; remove them first (tools/testboxes.sh remove NAME); nothing was changed"  # H-94 (3): a test box beside the real one takes the real one's patients
  fi
fi
# ---- end of TEST-BOX: the host

# REHEARSAL (D-726): before anything loads
# the bundle's release record is judged against the box's environment while it loads (D-127): a rehearsal is TEST
# from here on, read from the mark until deploy/.env says so. TB_ENV is read as Python reads it (no quotes, no spaces,
# upper case); only DEV, TEST or nothing may become a rehearsal box, and a VALIDATION box that already is one (D-887)
RH_ENV=""; [ -f deploy/.env ] && RH_ENV="$(tb_env_of deploy/.env)"
# a rehearsal box (or one left half emptied) never becomes a site box by an install without the argument. H-94: on
# a box that is not a PoC box the helper stops (the mark never becomes PRODUCTION: kept refusal 3, through the
# helper's own rule); on a PoC box the install goes on as the rehearsal box it is, as with --rehearsal
if [ "$REHEARSAL" != 1 ] && { [ -f deploy/site/rehearsal.json ] || { [ -f deploy/.env ] && grep -q '^TB_REHEARSAL=1' deploy/.env; }; }; then
  stop_or_warn rehearsal-without-argument "the install as a site box (it goes on as the rehearsal box it is: --rehearsal)" "this box was a rehearsal box (deploy/site/rehearsal.json or TB_REHEARSAL=1): run with --rehearsal, or empty it first (RUNBOOK §16, \"A rehearsal box\")"
  REHEARSAL=1; TB_STOP_REHEARSAL=1
fi
if [ "$REHEARSAL" = 1 ]; then
  case "$RH_ENV" in
    ""|DEV|TEST) ;;
    # H-94 (3): a site box (VALIDATION with no mark, or PRODUCTION) may hold real patient data: never a rehearsal box
    VALIDATION) [ -f deploy/site/rehearsal.json ] || die "--rehearsal: this box is VALIDATION (deploy/.env TB_ENV) with no rehearsal mark: a site box is never made a rehearsal box" ;;  # H-94 (3)
    *) die "--rehearsal: this box is $RH_ENV (deploy/.env TB_ENV): a site box is never made a rehearsal box" ;;  # H-94 (3)
  esac
  if [ ! -f deploy/site/rehearsal.json ]; then
    for f in settings.yaml updates/installed.json; do
      # H-94 (3): a site's install from no rehearsal: its data are taken as real patient data
      [ ! -e "deploy/$f" ] || die "--rehearsal: this box holds a site's install (deploy/$f) from no rehearsal: a rehearsal starts on an empty box"
    done
    # H-94 (3): volumes that cannot be listed cannot be shown to hold no real patient data
    RH_VOLS="$(docker volume ls -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-trialbox}")" \
      || die "--rehearsal: docker cannot list the volumes, so the box's data cannot be checked (is Docker running?)"
    RH_VOLS="$(printf '%s' "$RH_VOLS" | tr '\n' ' ')"
    # H-94 (3): data from no rehearsal are taken as real patient data
    [ -z "${RH_VOLS// /}" ] || die "--rehearsal: this box holds data from no rehearsal (volumes: $RH_VOLS): a rehearsal starts on an empty box"
  fi
  STANDINS="$ROOT/tools/rehearse_box/standins.yml"
  [ -f "$STANDINS" ] || { stop_or_warn rehearsal-standins "the model stand-ins (the real model servers, as TB_COMPOSE_OVERRIDE= empty)" "--rehearsal: no model stand-ins at tools/rehearse_box/standins.yml"; STANDINS=""; }
  mkdir -p deploy/site && printf '{"rehearsal": true}\n' > deploy/site/rehearsal.json
  # the stand-ins unless TB_COMPOSE_OVERRIDE is set: set empty, the real model servers (an unmeasured card's trial boot)
  export TB_COMPOSE_OVERRIDE="${TB_COMPOSE_OVERRIDE-$STANDINS}"
  export TB_ACCEPT_UNMEASURED_GPU=1
  echo "install: note: a rehearsal box (TB_ENV VALIDATION, ${TB_COMPOSE_OVERRIDE:-the real model servers}, an unmeasured card accepted)" >&2
fi
# ---- end of REHEARSAL (D-726): before anything loads
# REHEARSAL-REAL-SERVERS (H-89): after the mark, the box's record and compose file (deploy/site); a box that ran the
# real servers as a rehearsal is re-run with the same options or emptied, never installed as anything else
if [ "$REAL_SERVERS" = 1 ]; then
  # H-94 (2) and (3): the card checked again, and a site box is never made a rehearsal box
  python3 -m tools.rehearsal_real write --deploy "$ROOT/deploy" --profile "$GPU" --gpu-index "$GPU_INDEX" --engine-probe "$ENGINE_PROBE" ${RRS_REC:+--record "$RRS_REC"} \
    | sed 's/^/install: warning: /' >&2 || die "--rehearsal-real-servers: refused (above)"
elif [ -f deploy/site/rehearsal-real-servers.json ] || [ -f deploy/site/rehearsal-real-servers.yml ]; then
  stop_or_warn rrs-box-without-options "" "this box ran the real model servers as a rehearsal (deploy/site/rehearsal-real-servers.json): run with --rehearsal --rehearsal-real-servers, or empty it first (RUNBOOK §16, \"A rehearsal box\")"
fi
# ---- end of REHEARSAL-REAL-SERVERS (H-89)

# FINISH-EARLY (10K-4, D-1390): tools/trialbox/finish_check.py reads deploy/.env, the mount table and /sys and writes
# nothing: exit 1 is a refusal (each line names the setting to change), any other code means it did not run. Here a
# re-run on an installed box (deploy/.env is there) is checked before the bundle step, which on a running box applies
# the update and restarts the stack: refused here, nothing was loaded or changed. Not for a box's own install before
# its set-up (TB_BOX=1), a rehearsal (--rehearsal: a VALIDATION box), nor the run from the signed tree after a load
# (TB_INSTALL_SIGNED): the release that load brought is applied already, so FINISH-GATE says so when it refuses
# D-1091 (H94-03): it protects none of the five, so on a PoC box it warns (there it refuses only an anchor folder the
# console may not be given). Root's nightly signer and the install's first head write into each anchor folder
# (tools/trialbox/audit_heads.py), so a warning sets ANCHOR_UNSAFE: no anchor is mounted, written or signed into
finish_check() {  # $1: the point's key; $2: what is true when it refuses; the rest: finish-check's options (fixed words)
  local key="$1" said="$2" rc=0
  shift 2
  python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" "$@" || rc=$?
  case "$rc" in
    0) return 0 ;;
    1) stop_or_warn "$key" "$ANCHOR_SKIPS" "$said (above: the setting to change in deploy/.env; RUNBOOK §5)" ;;
    *) stop_or_warn "$key-did-not-run" "$ANCHOR_SKIPS" "the finish check did not run (exit $rc, above), so nothing about the folders was decided: $said" ;;
  esac
  ANCHOR_UNSAFE=1
}
ANCHOR_UNSAFE=0
ANCHOR_SKIPS="the anchor folders: not mounted into the console, no first head, no nightly signed head (the cron writes the log retention only)"
# Review 3 of #1303: skipped only by the run the bundle step below does not load again (TB_INSTALL_SIGNED is the
# release `current` names): any other value of it (one carried in by sudo -E) is checked here like any re-run (M2).
# The environment judged is the stricter of the one the box records (deploy/.env TB_ENV; none on an installed box is
# PRODUCTION, D-127; a value that is none of the four is taken as PRODUCTION) and --environment, so a PRODUCTION
# box re-run with --environment VALIDATION is refused here, not after the load (M1)
SIGNED_RUN=0
if [ -n "${TB_INSTALL_SIGNED:-}" ] && [ "$TB_INSTALL_SIGNED" = "$(readlink "$ROOT/current" 2>/dev/null)" ]; then
  SIGNED_RUN=1
fi
GATE_ENV="$EARLY_ENV"
if [ -f "$ROOT/deploy/.env" ] && [ -r "$ROOT/deploy/.env" ] && [ "$GATE_ENV" != PRODUCTION ]; then
  REC_ENV="$(tb_env_of "$ROOT/deploy/.env")"
  if [ -z "$REC_ENV" ] && { [ -f "$ROOT/deploy/settings.yaml" ] || [ -f "$ROOT/deploy/updates/installed.json" ]; }; then
    REC_ENV=PRODUCTION
  fi
  case "$REC_ENV" in
    "") ;;
    DEV|TEST|VALIDATION) GATE_ENV="${GATE_ENV:-$REC_ENV}" ;;
    *) GATE_ENV=PRODUCTION ;;
  esac
fi
if [ "${TB_BOX:-0}" != 1 ] && [ "$REHEARSAL" != 1 ] && [ "$SIGNED_RUN" != 1 ] && [ -f "$ROOT/deploy/.env" ]; then
  if command -v python3 >/dev/null; then
    finish_check finish-early "nothing was loaded or changed; then re-run" ${GATE_ENV:+--environment "$GATE_ENV"}
  elif [ "${GATE_ENV:-PRODUCTION}" = PRODUCTION ]; then
    stop_or_warn finish-early-no-python3 "" "no python3 on this host: a PRODUCTION install cannot check its backup target and audit anchor folder; nothing was loaded or changed (RUNBOOK §5)"
  fi
fi
# ---- end of FINISH-EARLY

# ------------------------------------------------------------------------------------------------ 2. bundle
# D-888: a re-run on a box installed before deploy/.env named its settings: the update's guard (and compose) see them
[ -f deploy/settings.yaml ] && export TB_SETTINGS_FILE="./settings.yaml"
say "bundle: verify and load (host tree, images, models, rulesets)"
# D-367: the second run, from the signed tree this run's load switched `current` to, does not load again
if [ "$SIGNED_RUN" != 1 ]; then  # the same test as FINISH-EARLY's skip (above)
  # H-95: every pack is verified (signature, every payload hash, read from the stick: nothing is copied) before any
  # pack is loaded; the software pack as if its model pack were held, which is loaded first
  # H-95: the three sizes first (from the manifests, before the stick is read whole), then stop (2) before anything
  # is read or loaded when a file system cannot hold what the load writes on it at its peak, with the numbers
  # (a manifest that cannot be read is left to the verifier below: stop (1))
  if command -v python3 >/dev/null && SIZES="$(python3 "$ROOT/tools/packs.py" sizes "$BUNDLE" ${MODEL_PACK:+--model-pack "$MODEL_PACK"} 2>/dev/null)"; then
    echo "    disk: $SIZES"
    DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
    SPACE_RC=0
    SPACE="$(python3 "$ROOT/tools/packs.py" space "$BUNDLE" ${MODEL_PACK:+--model-pack "$MODEL_PACK"} \
      --docker-root "${DOCKER_ROOT:-/var/lib/docker}" --models "$ROOT/deploy/models" --stage "${TMPDIR:-/tmp}" \
      --deploy "$ROOT" --updates "$ROOT/deploy/updates" 2>&1)" || SPACE_RC=$?
    [ "$SPACE_RC" != 1 ] || die "the disk cannot hold the install at its peak; nothing was loaded: $SPACE"  # H-94 (2)
    [ -z "$SPACE" ] || printf '%s\n' "$SPACE" | indent
  fi
  WITH_MODEL=()
  if [ -n "$MODEL_PACK" ]; then
    echo "    verifying the signature and every file of the model pack $(basename "$MODEL_PACK") (minutes for the weights)"
    alive_start "verifying the model pack"
    # H-94 (1): the signature and every payload hash
    sh "$ROOT/tools/apply_update.sh" "$MODEL_PACK" --for-software "$BUNDLE" --dry-run >/dev/null || die "the model pack is not a valid signed TrialBox model pack; nothing was changed"
    alive_stop
    WITH_MODEL=(--with-model-pack "$MODEL_PACK")
  fi
  echo "    verifying the signature and every file of $(basename "$BUNDLE") (minutes for a large bundle)"
  alive_start "verifying the bundle"
  # H-94 (1): the signature and every payload hash
  # (the redirection stands before the model pack's options: they are still arguments of apply_update.sh)
  sh "$ROOT/tools/apply_update.sh" "$BUNDLE" --dry-run >/dev/null ${WITH_MODEL[@]+"${WITH_MODEL[@]}"} || die "the bundle is not a valid signed TrialBox release; nothing was changed"
  alive_stop
  export PYTHONUNBUFFERED=1
  if [ -n "$MODEL_PACK" ]; then
    echo "    loading the model pack: the engine image and the weights, straight from the stick (10-20 minutes)"
    alive_start "loading the model pack"
    # H-94 (1): each payload is hashed again as it streams in; one whose hash fails is not loaded
    TB_SKIP_AUDIT=1 sh "$ROOT/tools/apply_update.sh" "$MODEL_PACK" --for-software "$BUNDLE" 2>&1 | indent || die "loading the model pack failed"
    alive_stop
  fi
  echo "    loading the images, models and rulesets straight from the stick (10-20 minutes for a GPU bundle)"
  alive_start "loading the bundle"
  # H-94 (1): the load checks each payload's hash as it lands; a failed load leaves nothing verified to act on
  TB_SKIP_AUDIT=1 sh "$ROOT/tools/apply_update.sh" "$BUNDLE" 2>&1 | indent || die "loading the bundle failed"
  alive_stop
fi
# H-94 (1): the signed release does not hold what every later step runs (its image, its host tree, its installer)
docker image inspect "$IMAGE_PY" >/dev/null 2>&1 || die "the bundle carried no $IMAGE_PY image"  # H-94 (1)
# T-631, D-367: compose files, host tools and configuration come only from the signed release
[ -L "$ROOT/current" ] && [ -d "$ROOT/current/deploy" ] \
  || die "the bundle carried no host tree (payload kind host, D-367): build the release with tools/make_bundle.sh of T-631 or later"  # H-94 (1)
RELEASE="$(readlink "$ROOT/current")"
echo "    release: $ROOT/current -> $RELEASE"
if [ "${TB_INSTALL_SIGNED:-}" != "$RELEASE" ]; then
  # deploy/install.sh is now a link into the signed tree (run by that path, so ROOT stays this folder)
  [ -L "$ROOT/deploy/install.sh" ] || die "deploy/install.sh is not the signed release's (tools/host_tree.py status)"  # H-94 (1)
  say "continuing from the signed release ($ROOT/deploy/install.sh -> $(readlink "$ROOT/deploy/install.sh"))"
  # REHEARSAL-REAL-SERVERS (H-89): the compose override this run exported (above) is never handed on: the run from
  # the signed tree writes it again itself, so any value it is given is a caller's and is refused there
  [ "$REAL_SERVERS" != 1 ] || unset TB_COMPOSE_OVERRIDE
  # ---- end of REHEARSAL-REAL-SERVERS (H-89)
  # KEK-INPUT (H-96): the passphrase this run read (from the file or stdin) goes on by a pipe at fd 8, its options
  # swapped for the fd's; the file's name goes with it only to be removed once sealed, never to be opened again
  if [ -n "$KP_VALUE" ]; then
    PP_ARGS=(); skip=0
    for a in ${ARGS[@]+"${ARGS[@]}"}; do
      if [ "$skip" = 1 ]; then skip=0; continue; fi
      case "$a" in
        --kek-passphrase-stdin) continue ;;
        --kek-passphrase-fd|--kek-passphrase-file|--kek-passphrase-remove) skip=1; continue ;;
      esac
      PP_ARGS+=("$a")
    done
    [ -z "$KP_FILE" ] || PP_ARGS+=(--kek-passphrase-remove "$KP_FILE")
    TB_INSTALL_SIGNED="$RELEASE" exec bash "$ROOT/deploy/install.sh" ${PP_ARGS[@]+"${PP_ARGS[@]}"} --kek-passphrase-fd 8 \
      8< <(printf '%s\n' "$KP_VALUE")
  fi
  # ---- end of KEK-INPUT
  TB_INSTALL_SIGNED="$RELEASE" exec bash "$ROOT/deploy/install.sh" ${ARGS[@]+"${ARGS[@]}"}
fi

# Expose the signed host CLI on PATH. The link follows the release selected by an update or rollback.
# H-106: a test box never takes the host's `trialbox` (the ordinary box's): its own is its folder's, and
# `trialbox --box NAME ...` reaches it (tools/trialbox/launch.py)
if [ "$(id -u)" = 0 ] && [ -z "${TEST_BOX:-}" ]; then
  install -d /usr/local/bin
  ln -sfnT "$ROOT/tools/trialbox/__main__.py" /usr/local/bin/trialbox
fi

# ------------------------------------------------------------------------------------------------ 3. settings
say "settings"
FRESH=0; [ -f deploy/.env ] || FRESH=1   # a box installed before step 8 keeps its shared token until rotation
# D-837: a TB_ENV written into deploy/.env before the wizard rewrites the file (ENVIRONMENT below keeps it)
PRE_ENV=""; [ -f deploy/.env ] && PRE_ENV="$(tb_env_of deploy/.env)"
mkdir -p deploy/keys deploy/secrets deploy/site/mapping deploy/site/terminology
# D-991: deploy/site/terminology is where the site's IT puts the code-system files it loads (deploy/terminology.sh,
# docs/handover/OFFLINE-MEDIA.md); git and the image ignore it
# T-632 (OPS-011): the site's own mapping is in deploy/site/mapping, never in the image; the wizard and the adapter see
# it at /etc/trialbox/mapping and look there first (adapter.mapping.site). A mapping folder beside the answers file
# is copied in once (the site's kit: answers.yaml + mapping/), never over a file the site already has
MAPPING_MOUNT=(-v "$ROOT/deploy/site/mapping:/etc/trialbox/mapping:ro")
if [ -n "$ANSWERS" ] && [ -d "$(dirname "$ANSWERS")/mapping" ] && [ "$(cd "$(dirname "$ANSWERS")/mapping" && pwd)" != "$ROOT/deploy/site/mapping" ]; then
  cp -rn "$(dirname "$ANSWERS")/mapping/." deploy/site/mapping/ && echo "    site mapping folder: deploy/site/mapping (from $(dirname "$ANSWERS")/mapping)"
fi
# WIZARD-ENV (D-1365): the wizard is told the site's environment, so PRODUCTION refuses a silent chart-number rule
# and an unnamed health-page watcher. As ENVIRONMENT below decides it: --environment, a rehearsal's VALIDATION, a
# TB_ENV written before, else PRODUCTION (D-127). A box's first-run page asks them itself (TB_BOX=1): not told there
# Review of #1175, S1: a value that is not one of the four stops the install here, before anything is written (a
# typo must not run the wizard unguarded and leave a settings.yaml the next run keeps)
WIZ_ARGS=()
WIZ_ENV="$ENVIRONMENT"; [ -n "$WIZ_ENV" ] || { [ "$REHEARSAL" != 1 ] || WIZ_ENV=VALIDATION; }
WIZ_ENV="$(printf '%s' "${WIZ_ENV:-${PRE_ENV:-PRODUCTION}}" | tr '[:lower:]' '[:upper:]')"
case "$WIZ_ENV" in
  DEV|TEST|VALIDATION|PRODUCTION) [ "${TB_BOX:-0}" = 1 ] || WIZ_ARGS=(--environment "$WIZ_ENV") ;;
  *) stop_or_warn wizard-env "" "the environment '$WIZ_ENV' (--environment, or TB_ENV in deploy/.env) is not DEV, TEST, VALIDATION or PRODUCTION: the settings wizard was not run" ;;
esac
# ---- end of WIZARD-ENV (D-1365)
SETTINGS_NEW=0
if [ ! -f deploy/settings.yaml ]; then
  SETTINGS_NEW=1  # D-736: a fresh install (a re-run keeps the site's settings and never stops a running site)
  if [ -n "$ANSWERS" ] && [ ! -f "$ANSWERS" ]; then
    stop_or_warn answers-file "the answers file (the questions, when there is a terminal)" "no such answers file: $ANSWERS"
    ANSWERS=""
  fi
  if [ -n "$ANSWERS" ]; then
    tree_args
    docker run --rm -e TB_CTGOV_MODE="$CTGOV" -v "$ROOT/deploy:/out" ${TREE_D[@]+"${TREE_D[@]}"} "${MAPPING_MOUNT[@]}" -v "$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS"):/in/answers.yaml:ro" \
      --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.settings_wizard --answers /in/answers.yaml --out /out/settings.yaml --env-out /out/.env ${WIZ_ARGS[@]+"${WIZ_ARGS[@]}"}
  else
    # D-1091: protects none of the five; on a PoC box no settings.yaml is made and the services that read it fail
    if [ -t 0 ]; then
      tree_args
      docker run --rm -it -e TB_CTGOV_MODE="$CTGOV" -v "$ROOT/deploy:/out" ${TREE_D[@]+"${TREE_D[@]}"} "${MAPPING_MOUNT[@]}" --user "$(id -u):$(id -g)" "$IMAGE_PY" \
        python -m tools.settings_wizard --out /out/settings.yaml --env-out /out/.env ${WIZ_ARGS[@]+"${WIZ_ARGS[@]}"}
    else
      stop_or_warn no-settings "the settings wizard (no settings.yaml: the services cannot start)" "no deploy/settings.yaml and no terminal for the questions: pass --answers site.yaml (RUNBOOK §1 step 3)"
    fi
  fi
else
  echo "    keeping deploy/settings.yaml (re-validating)"
  docker run --rm -v "$ROOT/deploy/settings.yaml:/in/settings.yaml:ro" "$IMAGE_PY" python -m tools.settings_wizard --check /in/settings.yaml
fi
[ -f deploy/.env ] || cp .env.example deploy/.env
# D-140: the ClinicalTrials.gov mode in plain words (en, ja, zh-TW) unless --ctgov gave it or the box already has one
if [ -z "$CTGOV" ]; then CTGOV="$(sed -n 's/^TB_CTGOV_MODE=//p' deploy/.env | tail -1)"; fi
case "$CTGOV" in
  live|offline) ;;
  *) CTGOV=offline
     if [ "$YES" != 1 ] && [ -t 0 ]; then
       ctgov_question; printf '  offline / live [offline]: '; read -r ans
       case "${ans:-offline}" in live|offline) CTGOV="${ans:-offline}" ;; *) stop_or_warn ctgov-answer "the answer $ans (offline)" "answer offline or live" ;; esac
     fi ;;
esac
if [ "$CTGOV" = live ] && ! ctgov_internet; then
  echo "install: clinicaltrials.gov does not answer from this host: ClinicalTrials.gov set to offline (re-run with --ctgov live once it does)" >&2
  CTGOV=offline
fi
echo "    ClinicalTrials.gov: $CTGOV"
sed -i "/^TB_CTGOV_MODE=/d" deploy/.env && echo "TB_CTGOV_MODE=$CTGOV" >> deploy/.env
# random service passwords where the example ones are still in place
# D-378: and one per service role of the trial database (deploy/docker/db-init/30-service-roles.sh); D-394: the
# audit writer's role too
for k in POSTGRES_PASSWORD POSTGRES_WF_PASSWORD TB_DB_PW_LAKE TB_DB_PW_CRITERIA_COMPILER TB_DB_PW_ADAPTER \
         TB_DB_PW_ORCHESTRATOR TB_DB_PW_MAIL_GATEWAY TB_DB_PW_GATEWAY TB_DB_PW_CONSOLE TB_DB_PW_AUDIT_WRITER \
         TB_DB_PW_FHIR_STORE; do
  if grep -q "^$k=change-me" deploy/.env || ! grep -q "^$k=" deploy/.env; then
    sed -i.bak "/^$k=/d" deploy/.env && printf '%s=%s\n' "$k" "$(rand 32)" >> deploy/.env
  fi
done
rm -f deploy/.env.bak
# D-128, D-138: one token per service (deploy/secrets/services/, 0600; never printed). A new box has no shared
# token at all; an older box keeps its shared one working, with a warning, until `trialbox secrets rotate`.
if [ "$FRESH" = 1 ] || grep -q '^TB_SERVICE_TOKEN=change-me' deploy/.env; then sed -i '/^TB_SERVICE_TOKEN=/d' deploy/.env; fi
if command -v python3 >/dev/null; then
  python3 -m tools.trialbox secrets init --deploy "$ROOT/deploy" | sed 's/^/    /'
else
  tree_args
  docker run --rm --user 0 -v "$ROOT/deploy:/d" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" python -m tools.trialbox secrets init --deploy /d | sed 's/^/    /'
fi
# D-126: the host tools reach the one trial database as `trialbox`; each service has its own role (D-378)
WF_PW="$(sed -n 's/^POSTGRES_WF_PASSWORD=//p' deploy/.env | tail -1)"
sed -i "/^TB_DB_URL=/d" deploy/.env && echo "TB_DB_URL=postgresql://trialbox:${WF_PW}@db:5432/trialbox_wf" >> deploy/.env
# REHEARSAL (D-726): the box says TEST
# D-887 (the integrator's (i)): it says VALIDATION, where D3 stays on the box (D-823), with the mark and TB_REHEARSAL=1
if [ "$REHEARSAL" = 1 ]; then
  RH_ENV="$(tb_env_of deploy/.env)"
  case "$RH_ENV" in
    ""|DEV|TEST) ;;
    VALIDATION) [ -f deploy/site/rehearsal.json ] || stop_or_warn rehearsal-answers-validation "" "--rehearsal: the answers make this box VALIDATION with no rehearsal mark: a rehearsal box is made by --rehearsal" ;;
    *) die "--rehearsal: the answers make this box $RH_ENV: a rehearsal box is VALIDATION" ;;  # H-94 (3): a rehearsal box never becomes PRODUCTION
  esac
  sed -i '/^TB_ENV=/d; /^TB_REHEARSAL=/d' deploy/.env && printf 'TB_ENV=VALIDATION\nTB_REHEARSAL=1\n' >> deploy/.env
fi
# ---- end of REHEARSAL (D-726): the box says TEST
# REHEARSAL-REAL-SERVERS (H-89): deploy/.env says the box ran the real servers (the console's banner, the start check)
# and the profile's own memory cap on this card: its utilisations, scaled to its card's memory (the record's "caps")
if [ "$REAL_SERVERS" = 1 ]; then
  sed -i '/^TB_REHEARSAL_REAL_SERVERS=/d' deploy/.env && echo "TB_REHEARSAL_REAL_SERVERS=1" >> deploy/.env
  python3 -c 'import json,sys; [print(f"{k}={v}") for k, v in sorted(json.load(open(sys.argv[1]))["caps"].items())]' \
    deploy/site/rehearsal-real-servers.json > deploy/site/.rehearsal-caps || { stop_or_warn rrs-caps "the profile's memory caps on this card (the compose defaults)" "--rehearsal-real-servers: the record names no caps"; : > deploy/site/.rehearsal-caps; }
  while IFS='=' read -r k v; do
    sed -i "/^$k=/d" deploy/.env && echo "$k=$v" >> deploy/.env
  done < deploy/site/.rehearsal-caps
  rm -f deploy/site/.rehearsal-caps
fi
# ---- end of REHEARSAL-REAL-SERVERS (H-89)
# ENVIRONMENT (D-837): --environment, or a TB_ENV written before the wizard rewrote deploy/.env; never changed
# silently (a pre-written VALIDATION was lost and the D-127 default below made the box PRODUCTION)
NOW_ENV="$(tb_env_of deploy/.env)"
if [ -n "$ENVIRONMENT" ]; then
  ENVIRONMENT="$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')"
  case "$ENVIRONMENT" in DEV|TEST|VALIDATION|PRODUCTION) ;; *) stop_or_warn environment-value "" "--environment must be DEV, TEST, VALIDATION or PRODUCTION, not $ENVIRONMENT" ;; esac
  if [ "$REHEARSAL" = 1 ] && [ "$ENVIRONMENT" != VALIDATION ]; then
    [ "$ENVIRONMENT" != PRODUCTION ] || die "--rehearsal makes a VALIDATION box, not $ENVIRONMENT"  # H-94 (3): a rehearsal box never becomes PRODUCTION
    stop_or_warn rehearsal-environment "--environment $ENVIRONMENT (a rehearsal box is VALIDATION)" "--rehearsal makes a VALIDATION box, not $ENVIRONMENT"
    ENVIRONMENT=VALIDATION; TB_STOP_ARG_ENV=VALIDATION
  fi
  if [ -n "$NOW_ENV" ] && [ "$NOW_ENV" != "$ENVIRONMENT" ]; then
    # H-94 (3): to or from PRODUCTION, a box's environment is never changed by an install
    [ "$NOW_ENV" != PRODUCTION ] && [ "$ENVIRONMENT" != PRODUCTION ] \
      || die "deploy/.env says TB_ENV=$NOW_ENV and --environment says $ENVIRONMENT: a box's environment is not changed by an install"  # H-94 (3)
    stop_or_warn environment-change "--environment $ENVIRONMENT (the box stays $NOW_ENV)" "deploy/.env says TB_ENV=$NOW_ENV and --environment says $ENVIRONMENT: a box's environment is not changed by an install"
    ENVIRONMENT="$NOW_ENV"; TB_STOP_ARG_ENV="$NOW_ENV"
  fi
  sed -i '/^TB_ENV=/d' deploy/.env && echo "TB_ENV=$ENVIRONMENT" >> deploy/.env
elif [ -z "$NOW_ENV" ] && [ -n "$PRE_ENV" ]; then
  sed -i '/^TB_ENV=/d' deploy/.env && echo "TB_ENV=$PRE_ENV" >> deploy/.env
  echo "    TB_ENV=$PRE_ENV kept (written in deploy/.env before the settings wizard)"
fi
# ---- end of ENVIRONMENT
# D-127 (review F-06): a box is PRODUCTION unless the operator set TB_ENV on purpose (timers, mail, REDCap, gates)
grep -q '^TB_ENV=' deploy/.env || echo "TB_ENV=PRODUCTION" >> deploy/.env
TB_ENV_SITE="$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1)"
TB_ENV_SITE="$(tb_env_raw deploy/.env)"  # H94-08: as compose reads it (the line above is master's; tests pin its place)
envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }
envset() { sed -i "/^$1=/d" deploy/.env && printf '%s=%s\n' "$1" "$2" >> deploy/.env; }
# ENV-BENCH (H-116): deploy/.env says TB_BENCH=1 (the console's banner reads it there), and the mark is checked again
# now that deploy/.env is the site's (the wizard's mail relay): a bench box sends no mail outside the host
if [ -n "$BENCH_MARK" ]; then
  python3 -m tools.trialbox.benchbox may --deploy "$ROOT/deploy" >/dev/null || die "the bench mark of this box is refused (above)"  # H-94 (3)
  envset TB_BENCH 1  # before the record: a stop between the two leaves TB_BENCH with no record, which is refused
  [ "$BENCH" = 0 ] || python3 -m tools.trialbox.benchbox write --deploy "$ROOT/deploy" >/dev/null || die "--bench: the record cannot be written (above)"  # H-94 (3)
  python3 -m tools.trialbox.benchbox check --deploy "$ROOT/deploy" >/dev/null || die "the bench mark of this box is refused (above)"  # H-94 (3)
fi
# TEST-BOX (H-106): deploy/.env carries the record (the box's name, project and ports): every later compose command
# and `trialbox` command reads them there. No unit, timer or cron file of the host's is a test box's (TB_SYSTEMD=0)
if [ -n "${TEST_BOX:-}" ]; then
  TB_LINES="$(python3 -m tools.trialbox.testbox env --deploy "$ROOT/deploy")" || die "--test-box: the box's record cannot be read (above)"  # H-94 depends (5): no record, no project of the box's own
  while IFS='=' read -r k v; do [ -z "$k" ] || envset "$k" "$v"; done <<< "$TB_LINES"
  TB_SYSTEMD=0; export TB_SYSTEMD
fi
# HOST PROFILE (D-837): TB_HOST_PROFILE=poc, a proof of concept or validation run on a plain VM: the host-facility
# checks (TPM seal, LUKS, egress table, systemd units, firewall, SSH, cron) WARN and are listed, here, in
# check_host.sh and in doctor. Never on PRODUCTION. It sets TB_SYSTEMD's default to 0 (no units on such a VM)
HOST_PROFILE="${TB_HOST_PROFILE:-$(envget TB_HOST_PROFILE)}"; HOST_PROFILE="${HOST_PROFILE:-site}"
case "$HOST_PROFILE" in
  site) ;;
  poc)
    # H-94 (3): the PoC relaxations never on a PRODUCTION box
    [ "$TB_ENV_SITE" != PRODUCTION ] \
      || die "TB_HOST_PROFILE=poc is never a PRODUCTION box: install with --environment VALIDATION (or TEST), or without the profile"
    envset TB_HOST_PROFILE poc
    TB_SYSTEMD="${TB_SYSTEMD:-0}"; export TB_SYSTEMD
    echo "    host profile poc ($TB_ENV_SITE): WARN, not FAIL, for the TPM seal, LUKS, the egress table, the systemd units, the firewall, SSH and cron (listed by the host check)"
    ;;
  *) stop_or_warn host-profile-value "TB_HOST_PROFILE=$HOST_PROFILE (read as site)" "TB_HOST_PROFILE must be site or poc, not '$HOST_PROFILE'"; HOST_PROFILE=site ;;
esac
# ---- end of HOST PROFILE
# D-726: what only a rehearsal box may use (the model stand-ins, an unmeasured card's trial boot)
rehearsal_only() {  # KEY WHAT. D-887: TEST with TB_REHEARSAL=1, or VALIDATION with TB_REHEARSAL=1 and the mark file
  # H-94: on a PoC box that is no rehearsal box, a warning (the stand-ins or the unmeasured card are used)
  [ "$(envget TB_REHEARSAL)" = 1 ] && { [ "$TB_ENV_SITE" = TEST ] || { [ "$TB_ENV_SITE" = VALIDATION ] && [ -f deploy/site/rehearsal.json ]; }; } \
    || stop_or_warn "$1" "" "$2: only on a rehearsal box (TB_REHEARSAL=1 on TEST, or on VALIDATION with deploy/site/rehearsal.json: deploy/install.sh --rehearsal); this box is $TB_ENV_SITE"
}
# D-726 (review F1): the stand-ins are known by what the file says, wherever it lies (a copy, the release tree's own)
is_standins() {
  grep -qx 'x-trialbox-rehearsal-standins: true' "$1"
}
# T-632 (OPS-011): the feed folder. The wizard wrote TB_SOURCE_DIR (the host folder) and TB_SOURCE_MOUNT (the
# settings' data_source.path); compose mounts the one at the other. PRODUCTION never falls back to the test fixture
SRC_DIR="$(envget TB_SOURCE_DIR)"
if [ -z "$SRC_DIR" ]; then
  [ "$TB_ENV_SITE" != PRODUCTION ] || stop_or_warn feed-folder-production "" "no feed folder: set TB_SOURCE_DIR in deploy/.env (the host folder the HIS export lands in; the settings wizard asks for it, RUNBOOK §1 step 3)"
  echo "    feed folder: none set ($TB_ENV_SITE): the synthetic fixture is mounted"
else
  case "$SRC_DIR" in /*) SRC_ABS="$SRC_DIR" ;; *) SRC_ABS="$ROOT/deploy/${SRC_DIR#./}" ;; esac
  case "$SRC_ABS" in "$ROOT"/deploy/site/*) mkdir -p "$SRC_ABS" ;; esac   # the default ./site/feed is made here
  [ -d "$SRC_ABS" ] || stop_or_warn feed-folder-missing "the feed folder's contents (Docker mounts an empty folder there)" "the feed folder $SRC_DIR (TB_SOURCE_DIR) is not a folder on this host: mount the HIS export there first"
  echo "    feed folder: $SRC_ABS -> $(envget TB_SOURCE_MOUNT) in the adapter"
fi
# T-632 (OPS-013): TLS on. The console is reached only at https://TB_TLS_HOSTNAME through Caddy (RUNBOOK §12)
TLS_HOST="$(envget TB_TLS_HOSTNAME)"
if [ -z "$TLS_HOST" ] && [ "$YES" != 1 ] && [ -t 0 ]; then
  printf '  The console'"'"'s DNS name for https (from hospital IT, e.g. trialbox.hospital.tw): '; read -r TLS_HOST
  [ -z "$TLS_HOST" ] || envset TB_TLS_HOSTNAME "$TLS_HOST"
fi
if [ -z "$TLS_HOST" ]; then
  [ "$TB_ENV_SITE" != PRODUCTION ] || stop_or_warn tls-production "" "no TLS host name: a PRODUCTION box runs only behind https. Put TB_TLS_HOSTNAME (and TB_TLS_MODE) in deploy/.env or the answers file (tls_hostname), then re-run (RUNBOOK §12)"
  echo "    TLS: off ($TB_ENV_SITE, no TB_TLS_HOSTNAME): the console stays on 127.0.0.1"
else
  grep -q '^TB_TLS_MODE=.' deploy/.env || envset TB_TLS_MODE internal
  # D-887: reached at https only, so the session cookie is Secure in every environment (doctor secure_cookie FAILs it
  # off on VALIDATION); a value the site wrote is kept
  grep -q '^TB_CONSOLE_SECURE_COOKIE=' deploy/.env || envset TB_CONSOLE_SECURE_COOKIE 1
fi
# H-48 (D-1328): TB_TLS_OLD_CLIENTS, the one setting that relaxes 443 for a hospital's old client: off (the default) or
# cbc (also the four TLS 1.2 ECDHE AES-CBC-SHA suites). Any other value is refused before Caddy reads it (RUNBOOK §12)
# the value compose gives Caddy: an exported TB_TLS_OLD_CLIENTS wins over deploy/.env, as compose does; quotes dropped
TLS_OLD="${TB_TLS_OLD_CLIENTS-$(envget TB_TLS_OLD_CLIENTS)}"; TLS_OLD="${TLS_OLD//[\"\']/}"; TLS_OLD="${TLS_OLD:-off}"
case "$TLS_OLD" in
  off) ;;
  cbc) [ -z "$TLS_HOST" ] || echo "    TLS: TB_TLS_OLD_CLIENTS=cbc: 443 also serves TLS 1.2 ECDHE AES-CBC-SHA to old clients (audited; doctor and the TLS check name it)" ;;
  *) stop_or_warn tls-old-clients-value "TB_TLS_OLD_CLIENTS=$TLS_OLD (set to off, the strict default, in deploy/.env)" "TB_TLS_OLD_CLIENTS must be off or cbc, not '$TLS_OLD': fix it in deploy/.env (RUNBOOK §12), then re-run"
     TLS_OLD=off; envset TB_TLS_OLD_CLIENTS off; export TB_TLS_OLD_CLIENTS=off ;;
esac
# SAE-MAILBOX (D-736): the trial office is told at once when a serious adverse event is entered (LIFE-007)
SAE_TO="$(envget TB_SAE_OFFICE_MAILBOX)"
[ -n "$SAE_TO" ] || SAE_TO="${TB_SAE_OFFICE_MAILBOX:-}"   # exported for this run
if [ -z "$SAE_TO" ] && [ "$YES" != 1 ] && [ -t 0 ]; then
  printf '  The trial office'"'"'s mailbox, told at once when a serious adverse event is entered (e.g. trial-office@hospital.tw): '; read -r SAE_TO || SAE_TO=""
fi
SAE_TO="$(printf '%s' "$SAE_TO" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
case "$SAE_TO" in \"*\") SAE_TO="${SAE_TO#\"}"; SAE_TO="${SAE_TO%\"}" ;; \'*\') SAE_TO="${SAE_TO#\'}"; SAE_TO="${SAE_TO%\'}" ;; esac
if [ -n "$SAE_TO" ] && ! printf '%s\n' "$SAE_TO" | grep -Eqx "[A-Za-z0-9._%+-][A-Za-z0-9._%+'-]*@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+"; then
  stop_or_warn sae-mailbox-form "TB_SAE_OFFICE_MAILBOX (not set: nobody is mailed)" "TB_SAE_OFFICE_MAILBOX $SAE_TO is not one mail address (for example trial-office@hospital.tw)"
  SAE_TO=""
fi
if [ -n "$SAE_TO" ]; then
  envset TB_SAE_OFFICE_MAILBOX "$SAE_TO"
  echo "    SAE office mailbox: $SAE_TO"
elif [ "$TB_ENV_SITE" = PRODUCTION ] && [ "${TB_BOX:-0}" != 1 ] && [ "${SETTINGS_NEW:-0}" = 1 ]; then
  stop_or_warn sae-mailbox-production "" "no SAE office mailbox: when a serious adverse event is entered the trial office must be told at once (a sponsor report can be due within 24 h). Put TB_SAE_OFFICE_MAILBOX in deploy/.env or sae_office_mailbox in the answers file, then re-run (RUNBOOK §1)"
else
  echo "install: warning: no SAE office mailbox ($TB_ENV_SITE): nobody is mailed when a serious adverse event is entered until TB_SAE_OFFICE_MAILBOX is set in deploy/.env (RUNBOOK §1)" >&2
fi
# ---- end of SAE-MAILBOX (D-736): the trial office is told at once when a serious adverse event is entered (LIFE-007)
# TB_LLM_MODE is the services' word (tb_common.config: vllm | stub ...), not the compose profile's (gpu | stub), D-142
LLM_MODE=stub; [ "$MODE" = gpu ] && LLM_MODE=vllm
grep -q '^TB_LLM_MODE=' deploy/.env && sed -i "s/^TB_LLM_MODE=.*/TB_LLM_MODE=$LLM_MODE/" deploy/.env || echo "TB_LLM_MODE=$LLM_MODE" >> deploy/.env
# D-177: the on-box model servers take calls only with this key (vLLM VLLM_API_KEY); the gateway alone holds it
if [ "$MODE" = gpu ] && ! grep -q '^TB_LLM_API_KEY=.' deploy/.env; then
  sed -i '/^TB_LLM_API_KEY=/d' deploy/.env && printf 'TB_LLM_API_KEY=%s\n' "$(rand 48)" >> deploy/.env
fi
NOTE_BLOCK=both_agree; [ "$GPU" = rtx4090 ] && NOTE_BLOCK=never
# the pair profiles run the verifier build: name it, or both_agree has no second model (doctor note_block), D-142
case "$MODE:$GPU" in gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)
  grep -q '^TB_GATEWAY_VERIFIER_MODEL=.' deploy/.env || { sed -i "/^TB_GATEWAY_VERIFIER_MODEL=/d" deploy/.env; echo "TB_GATEWAY_VERIFIER_MODEL=v-verifier" >> deploy/.env; }
  # and the judge build by name: a judge that names none could be answered by another build of its route (D-276)
  grep -q '^TB_GATEWAY_MODEL=.' deploy/.env || { sed -i "/^TB_GATEWAY_MODEL=/d" deploy/.env; echo "TB_GATEWAY_MODEL=j-workhorse" >> deploy/.env; } ;;
esac
grep -q '^TB_NOTE_BLOCK=' deploy/.env && sed -i "s/^TB_NOTE_BLOCK=.*/TB_NOTE_BLOCK=$NOTE_BLOCK/" deploy/.env || echo "TB_NOTE_BLOCK=$NOTE_BLOCK" >> deploy/.env
grep -q '^COMPOSE_PROFILES=' deploy/.env && sed -i "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=$MODE/" deploy/.env || echo "COMPOSE_PROFILES=$MODE" >> deploy/.env
# T-692 (D-473, OD-10): the adapter's and the lake's memory caps from the patient count (the lake's CURRENT snapshot,
# else TB_SITE_PATIENTS) and the measured record deploy/measured/ingest_memory.json; the orchestrator's (H23b-01,
# D-1005) from deploy/measured/orchestrator_memory.json (the size ladder's peaks), written only above the compose
# default; a cap set by hand is kept and `trialbox doctor` (memory_caps) says when it is too small
if command -v python3 >/dev/null; then
  LAKE_HOST="$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_lake-data" 2>/dev/null || true)"
  # D-832: the die hangs on the pipe (under pipefail a failing pipe ended the script before a PIPESTATUS line)
  python3 -m tools.trialbox.memcaps --env-file deploy/.env ${LAKE_HOST:+--lake "$LAKE_HOST"} --write 2>&1 | indent || stop_or_warn memcaps "the memory caps (the compose defaults)" "the memory caps could not be sized (above): set TB_MEM_ADAPTER, TB_MEM_LAKE and TB_MEM_ORCH in deploy/.env, then re-run"
else
  echo "install: warning: no python3: TB_MEM_ADAPTER, TB_MEM_LAKE and TB_MEM_ORCH keep the compose defaults (doctor memory_caps checks them)" >&2
fi
# T-703 (D-751): PostgreSQL's buffers, WAL, maintenance memory, /dev/shm and idle-transaction limit from TB_MEM_DB;
# a value set by hand is kept and `trialbox doctor` (postgres_memory) fails on the defaults of a large host
if command -v python3 >/dev/null; then
  python3 -m tools.trialbox.pgsize --env-file deploy/.env --write 2>&1 | indent || stop_or_warn pgsize "PostgreSQL's sizes (the compose defaults)" "PostgreSQL could not be sized (above): set the TB_PG_* values in deploy/.env, then re-run"
fi
chmod 600 deploy/.env
# the services run as tb (uid and gid 10001, deploy/docker/python.Dockerfile) and read settings.yaml read-only: a root
# 0600 file stopped every service at start (found by the box rehearsal, D-176). Group tb reads it, nobody else.
[ ! -f deploy/settings.yaml ] || { chown "$(id -u):10001" deploy/settings.yaml && chmod 640 deploy/settings.yaml; }
export TB_SETTINGS_FILE="./settings.yaml"
# D-888: in deploy/.env too, so every start mounts it (the systemd unit, an update, an operator's docker compose up)
envset TB_SETTINGS_FILE "./settings.yaml"
# ---- PINS: the models this box serves, pinned to the release's weights before anything starts on them
if [ "$MODE" = gpu ]; then
  # D-142 (review R-01): pin the profile's deployed pair from the site's own weights, which must be the release
  # models/registry.yaml expects (D-358), as candidate; PRODUCTION routes it once `trialbox eval qualify` passes and
  # `pin_model --promote` makes it champion (until then: champion_unqualified / no_eligible_build). Pins are kept.
  mkdir -p deploy/site
  for v in JUDGE_MODEL_DIR JUDGE_MODEL JUDGE_CHAT_TEMPLATE VERIFIER_MODEL_DIR VERIFIER_MODEL; do  # as compose reads them from deploy/.env
    val="$(sed -n "s/^$v=//p" deploy/.env | tail -1)"; [ -z "$val" ] || export "$v=$val"
  done
  say "pinning the $GPU model pair from deploy/models (tools/pin_model.py --install)"
  # D-835: as the installer's own user (the image user 10001 cannot write a root-owned deploy/site, and a failed pin
  # was only a warning: lane G's box went on with no model pinned); a pin that fails stops the install
  alive_start "hashing the model weights"
  # D-887: the box (TB_ENV, TB_REHEARSAL) goes to the pin, which pins the rehearsal media's placeholders on a
  # rehearsal box only, from a rehearsal bundle (deploy/updates/installed.json), every folder a placeholder
  tree_args
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d" ${TREE_D[@]+"${TREE_D[@]}"} -e JUDGE_MODEL_DIR -e JUDGE_MODEL -e JUDGE_CHAT_TEMPLATE -e VERIFIER_MODEL_DIR -e VERIFIER_MODEL \
    -e TB_ENV="$TB_ENV_SITE" -e TB_REHEARSAL="$(envget TB_REHEARSAL)" "$IMAGE_PY" \
    python -m tools.pin_model --install "$GPU" --models-root /d/models --out /d/site/registry.site.yaml \
    || die "a model of the $GPU pair is not pinned (see above): put its weights in deploy/models (RUNBOOK §8), then run install again"  # H-94 (1): the pin hashes the weights against the release's (D-358, D-887)
  alive_stop
else
  # D-1066 (D-998, the owner's ruling): a box without a GPU is a product form (a feasibility-only site that may add a
  # GPU later). Its embed service runs the embedder on the CPU and refuses to start in PRODUCTION without a pin, so
  # the embedder alone is pinned from the bundle's weights (every site bundle carries them, tools/release.py)
  mkdir -p deploy/site
  for v in EMBED_MODEL_DIR EMBED_MODEL; do  # as compose reads them from deploy/.env
    val="$(sed -n "s/^$v=//p" deploy/.env | tail -1)"; [ -z "$val" ] || export "$v=$val"
  done
  say "pinning the embedder from deploy/models (tools/pin_model.py --install-embedder)"
  alive_start "hashing the embedder's weights"
  tree_args
  if ! docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d" ${TREE_D[@]+"${TREE_D[@]}"} -e EMBED_MODEL_DIR -e EMBED_MODEL \
      -e TB_ENV="$TB_ENV_SITE" "$IMAGE_PY" \
      python -m tools.pin_model --install-embedder --models-root /d/models --out /d/site/registry.site.yaml; then
    alive_stop
    if [ "$TB_ENV_SITE" = PRODUCTION ]; then
      stop_or_warn pin-embedder-production "" "the embedder is not pinned (see above): a PRODUCTION box without a GPU needs it (D-1066); install from a bundle that carries embedder/, then run install again"
    fi
    echo "install: warning: the embedder is not pinned; on a $TB_ENV_SITE box the embed service runs its hash stub" >&2
  fi
  alive_stop
fi
if ls deploy/site/registry.site.yaml >/dev/null 2>&1; then
  # SEC-64: every pinned build's weights must still hash to its pin, or the box does not start on them
  say "checking the pinned model weights (tools/pin_model.py --verify-all)"
  alive_start "checking the model weights"
  tree_args
  docker run --rm -v "$ROOT/deploy:/d:ro" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" \
    python -m tools.pin_model --verify-all /d/models --out /d/site/registry.site.yaml \
    || die "model weights do not match their pins (see above): restore the pinned files or re-pin with tools/pin_model.py (RUNBOOK §8)"  # H-94 (1): weights whose hashes do not hold are never served
  alive_stop
else
  echo "install: note: no model pinned yet (deploy/site/registry.site.yaml): the gateway routes nothing to a local model until you run tools/pin_model.py or make spark-e2e (RUNBOOK §8)" >&2
fi
# ---- end of PINS

case "$MODE:$GPU" in gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)
  # D-112, D-124: a pair profile starts only on a serving-config record of that profile on that card, uncapped
  # (tools/serving_config.py measured <profile>): the site's own record (deploy/gcp/capture-serving-config.sh after a
  # first boot) or the vendor's, shipped in the bundle (deploy/measured/). Otherwise only when the operator accepts
  # an unmeasured card for a trial boot. The Spark is measured when a site orders one (owner decision, 2026-11-08).
  REC=""
  for f in "deploy/site/serving_config.$GPU.json" "deploy/measured/serving_config.$GPU.json"; do
    [ -f "$f" ] && { REC="$f"; break; }
  done
  if [ -n "$REC" ]; then
    tree_args
    if docker run --rm -v "$ROOT/deploy:/d:ro" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" python -m tools.serving_config measured "$GPU" "/d/${REC#deploy/}"; then
      echo "    $GPU profile measured: $REC"
    else
      stop_or_warn serving-record "the record $REC (an unmeasured card's trial boot)" "$REC is not a measurement of the $GPU profile on its own card (see above)"
    fi
    # REHEARSAL-REAL-SERVERS (H-89): a record of another card, as TB_ACCEPT_UNMEASURED_GPU=1 for no record: a
    # rehearsal box only (rehearsal_only), and it says so
    if [ "$REAL_SERVERS" = 1 ]; then
      rehearsal_only rrs-record-other-card "--rehearsal-real-servers (the $GPU record is of another card)"
      echo "install: warning: $(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); c=d["card"]; print(d["words"] + ": the record " + sys.argv[2] + " was measured on " + c["profile_card"] + ", the servers run on card " + str(c["index"]) + ", " + c["found"])' deploy/site/rehearsal-real-servers.json "$REC")" >&2
    fi
    # ---- end of REHEARSAL-REAL-SERVERS (H-89)
  elif [ -z "$TIER" ] && [ "${TB_ACCEPT_UNMEASURED_GPU:-0}" = 1 ]; then
    rehearsal_only unmeasured-card "TB_ACCEPT_UNMEASURED_GPU=1 (an unmeasured card's trial boot)"
    echo "install: warning: $GPU profile not yet measured on this card (TB_ACCEPT_UNMEASURED_GPU=1): capture deploy/site/serving_config.$GPU.json after the first boot (RUNBOOK §8)" >&2
  else
    stop_or_warn serving-record-missing "the measurement (an unmeasured card's trial boot)" "the $GPU profile has no measurement on its own card (deploy/site/ or deploy/measured/serving_config.$GPU.json). For a first trial boot re-run as a rehearsal box (TB_COMPOSE_OVERRIDE= deploy/install.sh <bundle> --gpu $GPU --rehearsal), then capture the record (RUNBOOK §1)"
  fi ;;
esac
case "$MODE:$GPU" in
  gpu:rtxpro6000) PROFILE=P-PRO6000 ;; gpu:gb10) PROFILE=P-GB10 ;; gpu:rtx5090|gpu:rtx4090) PROFILE=P-5090 ;; *) PROFILE=P-GB10 ;;
esac
grep -q '^TB_PROFILE=' deploy/.env && sed -i "s/^TB_PROFILE=.*/TB_PROFILE=$PROFILE/" deploy/.env || echo "TB_PROFILE=$PROFILE" >> deploy/.env
sed -i "/^TB_TIER=/d" deploy/.env; [ -z "$TIER" ] || echo "TB_TIER=$TIER" >> deploy/.env

# ------------------------------------------------------------------------------------------------ 4. start
COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.secrets.yml)
FILES="$ROOT/deploy/docker-compose.yml:$ROOT/deploy/docker-compose.secrets.yml"
case "$MODE:$GPU" in
  gpu:rtxpro6000) COMPOSE+=(-f deploy/docker-compose.rtxpro6000.yml); FILES="$FILES:$ROOT/deploy/docker-compose.rtxpro6000.yml" ;;
  gpu:gb10) COMPOSE+=(-f deploy/docker-compose.gb10.yml); FILES="$FILES:$ROOT/deploy/docker-compose.gb10.yml" ;;
  gpu:rtx5090|gpu:rtx4090) COMPOSE+=(-f deploy/docker-compose.rtx5090.yml); FILES="$FILES:$ROOT/deploy/docker-compose.rtx5090.yml" ;;
esac
if [ -n "$TLS_HOST" ]; then
  # the certificate, its key and the host name are checked before Caddy uses them (console.cli check-tls); the
  # hospital's files are mounted where deploy/.env names them
  say "TLS: https://$TLS_HOST ($(envget TB_TLS_MODE))"
  TLS_MOUNT=()
  for v in TB_TLS_CERT_FILE TB_TLS_KEY_FILE; do f="$(envget "$v")"; [ -z "$f" ] || TLS_MOUNT+=(-v "$f:$f:ro"); done
  docker run --rm -e TB_ENV="$TB_ENV_SITE" -e TB_TLS_MODE="$(envget TB_TLS_MODE)" -e TB_TLS_HOSTNAME="$TLS_HOST" \
    -e TB_TLS_CERT_FILE="$(envget TB_TLS_CERT_FILE)" -e TB_TLS_KEY_FILE="$(envget TB_TLS_KEY_FILE)" \
    ${TLS_MOUNT[@]+"${TLS_MOUNT[@]}"} --user 0 "$IMAGE_PY" python -m console.cli check-tls 2>&1 \
    | indent || { stop_or_warn tls-check "TLS (deploy/docker-compose.identity.yml is not added: the console stays on 127.0.0.1)" "the TLS settings do not pass (FAIL above): fix TB_TLS_* in deploy/.env (RUNBOOK §12), then re-run"; TLS_HOST=""; }
  [ -z "$TLS_HOST" ] || { COMPOSE+=(-f deploy/docker-compose.identity.yml); FILES="$FILES:$ROOT/deploy/docker-compose.identity.yml"; }
fi
if [ "${TB_BOX:-0}" = 1 ]; then  # T-729: the console's first-run folder (box-install.sh makes it, tmpfs)
  COMPOSE+=(-f deploy/docker-compose.box.yml); FILES="$FILES:$ROOT/deploy/docker-compose.box.yml"
fi
LOCK_FILES="$FILES"
# ANCHOR-GATE (10K-4, D-1390): the anchor folder is judged before anything mounts it (the read probe below, the
# console), whatever TB_BOX says: the rule for a folder the console may be given (finish-check --anchor-only)
if command -v python3 >/dev/null; then
  finish_check anchor-gate "the audit anchor folder is not given to the console: nothing was mounted, the stack was not started" --anchor-only
fi
# ---- end of ANCHOR-GATE
# ANCHOR-MOUNT (D-638): the audit page checks the chain against the signed heads of the anchor folders, which are
# host paths: a compose file of the installer's own mounts each into the console, read-only, and gives the console
# the name (the shipped compose file clears it). No folder set: no file, and an earlier one is taken away. The
# command prints the file, then each folder; a folder that is not there, or that the console's user cannot read
# (asked of the console's own image), stops the install: the page would say "no signed heads" on a healthy chain
NO_ANCHOR="the audit anchor folders' mount into the console (the audit page finds no signed head)"
ANCHOR_OK=1  # set here, never a caller's (review H-2 of #1396); ANCHOR_UNSAFE is the script's too (set above)
if [ "$ANCHOR_OK" = 1 ] && [ "${ANCHOR_UNSAFE:-0}" = 0 ] && command -v python3 >/dev/null; then
  ANCHOR_OUT="$(python3 -m tools.trialbox anchors-compose --deploy "$ROOT/deploy")" \
    || { stop_or_warn anchors-compose "$NO_ANCHOR" "TB_AUDIT_ANCHOR_TARGETS in deploy/.env names a folder that cannot be mounted (above)"; ANCHOR_OUT=""; }
  if [ -n "$ANCHOR_OUT" ]; then
    ANCHOR_FILE="${ANCHOR_OUT%%$'\n'*}"
    while IFS= read -r anchor; do
      # H-94 not a stop: the exit inside the probe container's script is the probe's own answer
      docker run --rm --network none -v "$anchor:/anchor:ro" "$IMAGE_PY" sh -c \
        'test -r /anchor && test -x /anchor && for d in heads keys; do [ ! -e "/anchor/$d" ] || { test -r "/anchor/$d" && test -x "/anchor/$d"; } || exit 1; done' </dev/null \
        || { stop_or_warn anchor-read "$NO_ANCHOR" "TB_AUDIT_ANCHOR_TARGETS: the console's user cannot read $anchor (or its heads/ or keys/): the audit page would find no signed head. Make the folder readable (chmod a+rx), then re-run"; ANCHOR_OK=0; }
    done <<< "${ANCHOR_OUT#*$'\n'}"
    [ "$ANCHOR_OK" = 0 ] || { COMPOSE+=(-f "$ANCHOR_FILE"); FILES="$FILES:$ANCHOR_FILE"; }
  fi
elif [ -n "$(envget TB_AUDIT_ANCHOR_TARGETS)" ]; then
  echo "install: note: no python3 on this host: the anchor folders are not mounted into the console, so the audit page will not check the signed heads (D-638)" >&2
fi
# H-94: on a PoC box an override that is not there, or that others could change, is warned and not used (a file
# root's later compose commands would read is never one a warned check let through)
NO_OVR="the compose override (not used)"
if [ -n "${TB_COMPOSE_OVERRIDE:-}" ] && [ ! -f "$TB_COMPOSE_OVERRIDE" ]; then
  stop_or_warn override-missing "$NO_OVR" "TB_COMPOSE_OVERRIDE: no such file $TB_COMPOSE_OVERRIDE"
  TB_COMPOSE_OVERRIDE=""
fi
if [ -n "${TB_COMPOSE_OVERRIDE:-}" ]; then  # D-176: the rehearsal's model stand-ins (or a site's own override)
  OVR="$(cd "$(dirname "$TB_COMPOSE_OVERRIDE")" && pwd)/$(basename "$TB_COMPOSE_OVERRIDE")"
  # every later compose command (as root: update, secrets rotate) reads it: only its owner (root or the installer)
  # may change it, and it must stay where it is
  OVR_OK=1
  [ "$(stat -c %u "$OVR")" = 0 ] || [ "$(stat -c %u "$OVR")" = "$(id -u)" ] || { stop_or_warn override-owner "$NO_OVR" "TB_COMPOSE_OVERRIDE: $OVR is not owned by root or $(id -un)"; OVR_OK=0; }
  [ "$OVR_OK" = 0 ] || [ $((0$(stat -c %a "$OVR") & 022)) = 0 ] || { stop_or_warn override-mode "$NO_OVR" "TB_COMPOSE_OVERRIDE: $OVR is writable by group or others (chmod go-w)"; OVR_OK=0; }
  if [ "$OVR_OK" = 1 ]; then
    is_standins "$OVR" && rehearsal_only standins "the model stand-ins ($OVR says x-trialbox-rehearsal-standins)"
    echo "install: note: compose override in use: $OVR (kept in deploy/.env COMPOSE_FILE)" >&2
    COMPOSE+=(-f "$OVR"); FILES="$FILES:$OVR"
  else
    OVR=""
  fi
fi
# TEST-BOX (H-106): the box's cards (deploy/site/test-box.yml, every service that reserves a card) and its memory cap
# (the servers' utilisations in deploy/.env, scaled to the cap: the serving engine holds them to it, not Docker)
if [ -n "${TEST_BOX:-}" ]; then
  TB_CARDS="$(python3 -m tools.trialbox.testbox override --deploy "$ROOT/deploy" --files "$FILES")" \
    || die "--test-box: the box's cards could not be written (above)"  # H-94 (2): without it its servers take another box's card, which cannot hold both
  [ -z "$TB_CARDS" ] || { COMPOSE+=(-f "$TB_CARDS"); FILES="$FILES:$TB_CARDS"; }
  if [ "$MODE" = gpu ]; then
    TB_LINES="$(python3 -m tools.trialbox.testbox env --deploy "$ROOT/deploy" --profile "$GPU")" || die "--test-box: the memory cap cannot be set on this card (above)"  # H-94 (2)
    while IFS='=' read -r k v; do [ -z "$k" ] || envset "$k" "$v"; done <<< "$TB_LINES"
  fi
fi
COMPOSE+=(--profile "$MODE")
# D-348: every third-party image of TrialBox's own compose files is the one deploy/images.lock pins, by digest (the
# site's TB_COMPOSE_OVERRIDE is its own and is not checked)
if command -v python3 >/dev/null; then
  python3 -m tools.images_lock check-compose --files "$LOCK_FILES" 2>&1 | sed 's/^/    /' \
    || die "a compose file names a third-party image that deploy/images.lock does not pin (FAIL above)"  # H-94 (1): an image with no digest pin
fi
# the same file set for every later `docker compose --project-directory deploy ...` (secrets rotate, update, logs)
sed -i "/^COMPOSE_FILE=/d" deploy/.env && echo "COMPOSE_FILE=$FILES" >> deploy/.env
# D-138 log retention: where collected service logs and the audit archive go (RUNBOOK §2 "Logs"); the days are in
# settings.yaml retention (the wizard's jp/tw defaults)
grep -q '^TB_LOG_DIR=' deploy/.env || echo "TB_LOG_DIR=$ROOT/deploy/logs" >> deploy/.env
grep -q '^TB_AUDIT_ARCHIVE_DIR=' deploy/.env || echo "TB_AUDIT_ARCHIVE_DIR=$ROOT/deploy/logs/audit-archive" >> deploy/.env
grep -q '^TB_BACKUP_TARGETS=' deploy/.env || echo "TB_BACKUP_TARGETS=$ROOT/deploy/backups" >> deploy/.env
# FINISH-GATE (10K-4, D-1390): before the stack starts, unless TB_BOX=1 (deploy/box-install.sh checks after the
# set-up): in PRODUCTION (read as the tool reads TB_ENV) a backup target shown to be off the box and the hospital's
# audit share as the anchor folder. By here this run has loaded the bundle (on a box that was running, apply_update.sh
# has applied the release and restarted the stack, as trialbox update does) and written its settings; a refusal says so
if [ "${TB_BOX:-0}" != 1 ]; then
  if command -v python3 >/dev/null; then
    finish_check finish-gate "not finished: the bundle this run loaded stays (on a box that was already running, its release is applied and running, as after trialbox update) and the settings it wrote stay; the install's own start, units, cron and checks were not run. Change what the lines above name in deploy/.env, then re-run this command: it goes on from here"
  elif [ "$(printf '%s' "$TB_ENV_SITE" | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')" = PRODUCTION ]; then
    stop_or_warn finish-gate-no-python3 "" "no python3 on this host: a PRODUCTION install cannot check its backup target and audit anchor folder (RUNBOOK §5)"
  fi
fi
# ---- end of FINISH-GATE
UP_EXTRA=(); [ "$MODE:$GPU" = gpu:rtx4090 ] && UP_EXTRA=(--scale llm-verifier=0)
if [ "$YES" != 1 ] && [ -t 0 ]; then
  printf 'Start the stack now with profile %s? [Y/n] ' "$MODE"; read -r ans; case "$ans" in n|N) die "stopped before start; re-run with --yes to skip the question" ;; esac  # H-94 not a stop: the operator's own answer (D-1091)
fi
say "starting the stack (profile $MODE)"
"${COMPOSE[@]}" config -q
# D-176: every image the stack runs comes from the bundle, none from a registry. A digest-pinned image is found by its
# digest (Docker's containerd image store) or by the bundle's image id (the classic overlay2 store keeps no digests;
# tools/image_pins.py sets its compose variable in deploy/.env). TB_INSTALL_PULL=missing only on a site that mirrors
# the third-party images itself (make_bundle.sh --no-third-party).
PULL="${TB_INSTALL_PULL:-never}"
case "$PULL" in never|missing) ;; *) stop_or_warn install-pull "TB_INSTALL_PULL=$PULL (never)" "TB_INSTALL_PULL must be never or missing"; PULL=never ;; esac
if command -v python3 >/dev/null; then
  # OPS-004b (D-574): what the stack will run, with the box's overrides applied; an image no service runs (a model
  # server a compose override replaces) is not asked for
  USED_IMAGES="$("${COMPOSE[@]}" config --images | sort -u)"
  python3 -m tools.image_pins resolve --deploy deploy --files "$FILES" --used "$USED_IMAGES" 2>&1 | sed 's/^/    /' \
    || die "a pinned image is not on this box (MISSING above): the bundle must carry it (make_bundle.sh without --no-third-party)"  # H-94 (1): an image pinned by digest that is not here
fi
if [ "$PULL" = never ]; then
  MISSING=""
  while IFS= read -r img; do
    docker image inspect "$img" >/dev/null 2>&1 || MISSING="$MISSING $img"
  done < <("${COMPOSE[@]}" config --images | sort -u)
  [ -z "$MISSING" ] || die "images not on this box:$MISSING. They come only from the bundle; nothing is pulled (TB_INSTALL_PULL=missing on a site with its own mirror)"  # H-94 (1)
  echo "    every image of the stack is on this box (nothing is pulled)"
fi
# D-620: this release's host-side steps before its stack starts (tools/trialbox/prestart.py), the same command an
# update runs: a step a release adds there is run by a fresh install too. The steps are safe to run again.
if command -v python3 >/dev/null; then
  # REHEARSAL-REAL-SERVERS (H-89): pre-start's first check, its rehearsal guard (start_refusal: a box with a
  # rehearsal sign never starts as PRODUCTION), is run on its own first on a PoC box, so the warning below never
  # covers it (H-94 kept refusal 3, review M-2 of #1396). On any other box pre-start refuses it itself, master's words
  if tb_poc_box; then
    python3 -m tools.rehearsal_real start --deploy "$ROOT/deploy" 2>&1 | sed 's/^/    /' \
      || die "a start-up step of this release failed (pre-start above)"  # H-94 (3)
  fi
  # ---- end of REHEARSAL-REAL-SERVERS (H-89)
  python3 -m tools.trialbox pre-start --deploy "$ROOT/deploy" 2>&1 | sed 's/^/    /' \
    || stop_or_warn pre-start "" "a start-up step of this release failed (pre-start above)"
else
  echo "    note: no python3 on this host: the release's start-up steps (tools.trialbox pre-start) were not run" >&2
fi
# PROJECT-CLEANUP (F-19): after the release's checks above passed, before anything uses the project's network. Only a
# project proven to be this install's (tools/trialbox/project_check.py) with a failed container (created, dead, exited
# non-zero, unhealthy) is taken down, with the same overlays as up and every profile of an earlier attempt. A paused,
# starting or exit-0 container is a working box's: kept. Refused while an update or the watchdog's maintenance flag is
# there (review 2 of #1305, M-1). Anything else is refused or kept.
if command -v python3 >/dev/null; then
  CLEANUP="$(python3 -m tools.trialbox.project_check --deploy "$ROOT/deploy" -- "${COMPOSE[@]}" --profile '*')" \
    || { stop_or_warn project-cleanup-refused "the cleanup of a failed earlier attempt (nothing is taken down)" "the project cleanup was refused (above): nothing was removed"; CLEANUP=none; }
else
  CLEANUP=none
  [ -z "${COMPOSE_PROJECT_NAME:-}" ] || [ "$COMPOSE_PROJECT_NAME" = trialbox ] \
    || { stop_or_warn compose-project-name "the shell's COMPOSE_PROJECT_NAME (unset for this run: this install's project)" "COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME in this shell is not this install's project: unset it, then re-run"; unset COMPOSE_PROJECT_NAME; }
  echo "    note: no python3 on this host: the project is not proven to be this install's, so nothing is cleaned up" >&2
fi
[ "${SECOND_RUN:-0}" = 0 ] || CLEANUP=none  # H-94: another installer's containers are not this run's to take down
if [ "$CLEANUP" = down ]; then
(
  COMPOSE+=(--profile '*')
  "${COMPOSE[@]}" down --remove-orphans
) || stop_or_warn project-cleanup-failed "" "project cleanup failed / 專案清理失敗 / プロジェクトのクリーンアップに失敗しました"
fi
# ---- end of PROJECT-CLEANUP
# T-612 (DATA-004): the site keys are made here and nowhere else. A key already in the secrets volume is kept; the
# ingest refuses a night whose key is missing or is not the one the box's pseudonyms were made with
say "site keys (made once, never replaced)"
KEYS_OK=1
"${COMPOSE[@]}" run --rm --no-deps -T adapter python -m adapter.cli keys-init | sed 's/^/    /' \
  || { stop_or_warn site-keys "the sealing of the site keys" "the site keys could not be made or read (above): put the site's keys back from the backup (RUNBOOK §5)"; KEYS_OK=0; }
# T-634 (D-408; OPS-043): sealed at once, before any service opens them. VALIDATION and PRODUCTION always; a DEV or TEST
# box only when it has deploy/site/hardening.conf or TB_KEK_BACKEND asks for it (D-887). The KEK's back end is the site's (TB_KEK_BACKEND in the installer's
# environment, else hardening.conf's KEK_BACKEND, default tpm; D-836); the
# host check FAILs a plain site key in VALIDATION and PRODUCTION
HB_CONF="$ROOT/deploy/site/hardening.conf"
if [ "$KEYS_OK" = 0 ]; then
  echo "    site keys: not sealed (they could not be made or read, above)"
elif [ "${TB_BOX_DEFER_SEAL:-0}" = 1 ]; then
  echo "    site keys: sealed at the box's apply step, under the owner's passphrase (box-install.sh, T-729)"
elif [ "$HOST_PROFILE" = poc ] && [ -z "${TB_KEK_BACKEND:-}" ] \
    && ! { command -v systemd-creds >/dev/null 2>&1 && systemd-creds has-tpm2 >/dev/null 2>&1; }; then
  # D-837: a plain VM has no usable TPM; the passphrase back end seals the keys when it is asked for
  echo "    site keys: not sealed (host profile poc, no usable TPM; TB_KEK_BACKEND=passphrase with --kek-passphrase-file seals them); the host check lists it"
elif [ "$TB_ENV_SITE" = PRODUCTION ] || [ "$TB_ENV_SITE" = VALIDATION ] || [ -f "$HB_CONF" ] || [ -n "${TB_KEK_BACKEND:-}" ]; then
  say "site keys sealed under the KEK (deploy/hardening/seal_keys.sh)"
  [ "$(id -u)" = 0 ] || die "sealing the site keys needs root (the secrets volume, the TPM): run the installer as root"  # H-94 (4)
  SEC_DIR="${TB_SECRETS_HOST_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets" 2>/dev/null)}"
  # KEK-INPUT (H-96): the passphrase this run read goes to the seal step by a pipe (never an argument's value, an
  # environment or the file's name again); the operator's file is removed here once the keys are sealed (rm: a link
  # is taken away, never what it names), kept with --keep-kek-passphrase-file or when the seal failed
  seal() { TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh --secrets "$SEC_DIR" --conf "$HB_CONF" "$@"; }
  sealed=0
  if [ -n "$KP_VALUE" ]; then printf '%s\n' "$KP_VALUE" | seal --kek-passphrase-stdin && sealed=1
  else seal </dev/null && sealed=1; fi
  if [ "$sealed" = 1 ] && [ -n "$KP_FILE" ]; then
    if [ "$PP_KEEP" = 1 ]; then echo "    the passphrase file $KP_FILE is kept (--keep-kek-passphrase-file): remove it yourself"
    else kp_remove_file "$KP_FILE"; echo "    the passphrase file $KP_FILE is removed"; fi
  fi
  [ "$sealed" = 1 ] \
    || stop_or_warn seal-keys "the sealing of the site keys (they stay plain files; the host check lists it)" "the site keys are not sealed (above): for TB_KEK_BACKEND=passphrase without a usable TPM, use the hidden-input example in deploy/install.sh --help; docs/security/01-the-host.md"
  PP_FILE=""; KP_FILE=""
fi
KP_VALUE=""
[ -z "$KP_FILE" ] || echo "    the KEK passphrase file $KP_FILE was not used (no seal step on this box): it stays; remove it"
KP_FILE=""

# D-378: the services' database roles, on a new volume (db-init made them) and an older one alike (idempotent)
# D-1091: protects none of the five; on a PoC box the database steps after it fail where they run
"${COMPOSE[@]}" up -d --pull "$PULL" --wait db || stop_or_warn db-start "" "the database did not start (docker compose logs db)"
# D-624: this release's steps once the database is up (tools/trialbox/prestart.py DB_STEPS: the roles of D-378, the
# schemas no service owns of D-486, whatever a later release adds), by the same command an update runs and with the
# compose files and profile an update uses (COMPOSE_FILE and COMPOSE_PROFILES in deploy/.env, written above)
if command -v python3 >/dev/null; then
  TB_INSTALL_PULL="$PULL" python3 -m tools.trialbox db-up --deploy "$ROOT/deploy" 2>&1 | sed 's/^/    /' \
    || stop_or_warn db-up "" "a database step of this release failed (db-up above; docker compose logs db)"
else
  echo "    note: no python3 on this host: the release's database steps (tools.trialbox db-up) were not run; the roles and the schemas are set by the installer" >&2
  "${COMPOSE[@]}" exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh \
    || stop_or_warn db-roles "" "the database roles could not be set (docker compose logs db)"
  # D-486 (T-718): the schemas no service owns (edc), by the box's admin; the admin's URL goes in the environment,
  # not on the command line
  TB_DB_URL="postgresql://trialbox:${WF_PW}@db:5432/trialbox_wf" "${COMPOSE[@]}" run --rm --no-deps -T -e TB_DB_URL \
    orchestrator python -m orchestrator.migrate | sed 's/^/    /' \
    || stop_or_warn db-schemas "" "the schemas of the trial database could not be made (python -m orchestrator.migrate)"
fi
# T-695 (D-752, F-24): the wait for every service healthy, from the compose files' health checks (start period, then
# the retries); the stop, from the longest stop grace. Without PyYAML on the host, the waits of before (900 s, 300 s).
BOOT_WAIT="$(python3 -m tools.trialbox.bootwait --deploy deploy 2>/dev/null)" || BOOT_WAIT=900
STOP_WAIT="$(python3 -m tools.trialbox.bootwait --deploy deploy --stop 2>/dev/null)" || STOP_WAIT=290
alive_start "waiting for every service to be healthy (up to ${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT} s)"
"${COMPOSE[@]}" up -d --pull "$PULL" "${UP_EXTRA[@]}" --wait --wait-timeout "${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT}" \
  || { alive_stop; "${COMPOSE[@]}" ps; stop_or_warn stack-health "" "the stack did not become healthy (docker compose logs)"; }  # D-1091: protects none of the five
alive_stop
if [ "$MODE" = gpu ]; then
  # D-177: the model servers must serve the names the site pinned and refuse calls without the key; otherwise the
  # gateway would get 404 or 401 on every call and the box would screen nothing (doctor check "serving")
  say "model servers: pinned served names and key (trialbox doctor --serving)"
  set +e
  tree_args
  docker run --rm --network "${TB_PROJECT:-trialbox}-model-net" --env-file deploy/.env -v "$ROOT/deploy:/app/deploy:ro" ${TREE_APP[@]+"${TREE_APP[@]}"} \
    -e TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.trialbox doctor --serving | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  set -e
  [ "$rc" = 0 ] || stop_or_warn serving "" "the model servers do not match the pins or the key (FAIL above): the stack is up but every model call would be refused; fix deploy/.env (JUDGE_MODEL, VERIFIER_MODEL), the key (python3 -m tools.trialbox secrets rotate --service model) or re-pin (RUNBOOK §8), then re-run"
fi
EGRESS_OK=0
if [ -n "${TEST_BOX:-}" ]; then  # H-106: the host's egress table is the ordinary box's alone
  echo "    test box: the host's egress table is not changed (the box's internal networks stay closed)"
elif [ "$(id -u)" = 0 ] && [ -x deploy/network.sh ]; then
  say "egress rules"
  if deploy/network.sh apply; then EGRESS_OK=1
  else echo "install: warning: egress rules not applied (deploy/network.sh apply)" >&2; fi
fi
# T-634 (D-408; OPS-052): the input firewall (443 from the clinic ranges only) and SSH, from the site's
# deploy/site/hardening.conf; without it a VALIDATION or PRODUCTION box fails the host check at the end
if [ "$(id -u)" = 0 ] && [ -f "$HB_CONF" ]; then
  say "host baseline: input firewall and SSH (deploy/hardening/apply.sh)"
  if [ "$HB_SKIP" = 1 ]; then
    echo "install: warning: the host baseline is not applied: it would cut this SSH session (above)" >&2
  else
    sh deploy/hardening/apply.sh --conf "$HB_CONF" ${HB_OVER[@]+"${HB_OVER[@]}"} all || stop_or_warn host-baseline "" "the host baseline could not be applied (above)"
  fi
elif [ ! -f "$HB_CONF" ]; then
  echo "install: warning: no deploy/site/hardening.conf (the clinic ranges, SSH, the KEK back end): copy deploy/hardening/hardening.example.conf, fill it in with hospital IT, re-run" >&2
fi
# T-108b (D-377; CR-043, OPS-049, OPS-064): the systemd units. trialbox-egress loads the closed egress table from the
# state file `apply` just wrote, before Docker starts; trialbox starts the stack after it and re-applies the rules;
# two timers refresh the rules and run the watchdog. Only once the state file exists: a boot without it would stop
# Docker. TB_SYSTEMD_DIR moves the target folder (tests); TB_SYSTEMD=0 skips the step.
SYSTEMD_DIR="${TB_SYSTEMD_DIR:-/etc/systemd/system}"
if [ "${TB_SYSTEMD:-1}" != 0 ] && [ "$(id -u)" = 0 ] && [ -d /run/systemd/system ] && command -v systemctl >/dev/null; then
  if [ "$EGRESS_OK" = 1 ]; then
    say "systemd units (egress at boot, the stack after a restart, watchdog)"
    for unit in deploy/systemd/*.service deploy/systemd/*.timer; do
      sed -e "s#@TB_ROOT@#$ROOT#g" -e "s#@TB_BOOT_WAIT@#${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT}#g" \
          -e "s#@TB_UP_EXTRA@#${UP_EXTRA[*]}#g" \
          -e "s#@TB_BOOT_LIMIT@#$(( ${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT} + 300 ))#g" \
          -e "s#@TB_STOP_LIMIT@#$(( STOP_WAIT + 10 ))#g" "$unit" > "$SYSTEMD_DIR/$(basename "$unit")"
      chmod 644 "$SYSTEMD_DIR/$(basename "$unit")"
    done
    systemctl daemon-reload
    SYSTEMD_OK=1
    # trialbox-weights.timer (T-677, D-393): the weights against their pins before the night's runs
    # trialbox-ops.timer (NEW-OPS-8, D-561): the runner that writes the host's health facts every minute and runs
    # the Operations page's requests; without it the health line is red (OPS-009)
    systemctl enable trialbox-egress.service trialbox.service trialbox-egress-refresh.timer trialbox-watchdog.timer \
      trialbox-egress-watch.service trialbox-weights.timer trialbox-ops.timer >/dev/null 2>&1 \
      || { stop_or_warn systemd-units "the start of the units" "the systemd units could not be enabled (systemctl status trialbox-egress trialbox)"; SYSTEMD_OK=0; }
    if [ "$SYSTEMD_OK" = 1 ]; then  # H-94: units a PoC box could not enable are not started
      systemctl start trialbox.service
      systemctl start trialbox-egress-refresh.timer trialbox-watchdog.timer trialbox-weights.timer \
        trialbox-egress-watch.service trialbox-ops.timer >/dev/null 2>&1 || true
    fi
    echo "    enabled: trialbox-egress, trialbox, trialbox-egress-refresh.timer, trialbox-watchdog.timer, trialbox-weights.timer, trialbox-egress-watch, trialbox-ops.timer"
  else
    echo "install: warning: systemd units not enabled: the egress rules were not applied (no state file for a boot)" >&2
  fi
fi
# H-92 (D-1090): a systemd host schedules the backup with timers, so it needs no /etc/cron.d for that
SYSTEMD_HOST=0; [ "$(id -u)" = 0 ] && [ "${TB_SYSTEMD:-1}" != 0 ] && [ -d /run/systemd/system ] \
  && command -v systemctl >/dev/null && SYSTEMD_HOST=1
CRON_DIR="${TB_CRON_DIR:-/etc/cron.d}"   # T-632: both cron files, or no finished install in PRODUCTION
CAN_CRON=0; [ -z "${TEST_BOX:-}" ] && { [ "$(id -u)" = 0 ] || [ -n "${TB_CRON_DIR:-}" ]; } && [ -d "$CRON_DIR" ] && command -v python3 >/dev/null && CAN_CRON=1  # H-106
if [ "$CAN_CRON" = 1 ]; then
  # D-138: every night collect yesterday's service logs, prune by settings.retention, copy the audit to its archive
  # NEW-STD-2 (D-562): then the night's signed head of the audit chain into TB_AUDIT_ANCHOR_TARGETS, whatever the
  # first command returned; `trialbox doctor` (audit_heads) FAILs when no folder is set or the newest head is old
  printf '%s\n' "SHELL=/bin/sh" "20 0 * * * root cd $ROOT && { python3 -m tools.trialbox logs daily; python3 -m tools.trialbox audit-sign; } >> /var/log/trialbox-retention.log 2>&1" \
    > "$CRON_DIR/trialbox-retention" && chmod 644 "$CRON_DIR/trialbox-retention"
  echo "    log retention and the signed audit head: $CRON_DIR/trialbox-retention (00:20 daily)"
elif [ "$TB_ENV_SITE" = PRODUCTION ] && [ "$SYSTEMD_HOST" != 1 ]; then
  stop_or_warn cron-production "" "the cron files cannot be installed (needs root, /etc/cron.d and python3): run the installer as root"
elif [ "$SYSTEMD_HOST" = 1 ]; then
  echo "install: warning: no $CRON_DIR: the backup runs from systemd timers; the log retention cron is not installed (H92-02)" >&2
fi
# H-94 (D-1091): a finish check warned on a PoC box: the nightly signed head is not written into the refused folder
[ "${ANCHOR_UNSAFE:-0}" = 0 ] || [ ! -f "$CRON_DIR/trialbox-retention" ] \
  || sed -i 's/; python3 -m tools.trialbox audit-sign//' "$CRON_DIR/trialbox-retention"
if [ "$(id -u)" = 0 ] && [ -d /etc/logrotate.d ] && [ -z "${TEST_BOX:-}" ]; then
  # D-389 (OPS-037): /var/log/trialbox-*.log (the retention and backup cron logs) rotate weekly, 53 kept
  install -m 644 deploy/logrotate/trialbox /etc/logrotate.d/trialbox && echo "    host logs: /etc/logrotate.d/trialbox"
fi
# D-138: the site's one-page network, port and secret sheet, from the compose files this box runs
SHEET_MOUNT=(); SHEET_FILES="$(echo "$FILES" | sed "s#$ROOT/deploy/#deploy/#g")"
if [ -n "${OVR:-}" ]; then  # the override is outside deploy/: mount it where the sheet tool looks
  SHEET_MOUNT=(-v "$OVR:/app/deploy/compose-override.yml:ro"); SHEET_FILES="${SHEET_FILES//$OVR/deploy/compose-override.yml}"
fi
FAILS=()   # T-632: a FAIL here does not stop the install half-way; the install ends with exit 1 and the list
# HW-003 (D-569): the shipped qualification record. The pair was pinned as candidate, and PRODUCTION routes a
# champion only. When a record in deploy/qualification/<profile>/ qualified exactly these weights, this model
# server image and this chat template, the pair is promoted; the promotion is kept only when the canary passes on
# this box through the gateway. Until then it waits (deploy/site/shipped-promotion.pending.json): an install that
# is interrupted here runs the canary the next time, and a failed canary puts the pair back to candidate.
if [ "$MODE" = gpu ] && [ -f deploy/site/registry.site.yaml ]; then
  say "model pair: the shipped qualification record (tools/pin_model.py --promote-shipped)"
  # on a box installed from a bundle these two are links into ../current (tools/host_tree.py): resolved here,
  # because a link out of the mounted folder dangles inside the container
  QUAL_DIR="$(readlink -f deploy/qualification 2>/dev/null || true)"; [ -d "$QUAL_DIR" ] || QUAL_DIR="$ROOT/deploy/site"
  LOCK_FILE="$(readlink -f deploy/images.lock 2>/dev/null || true)"
  pin_tool() {
    docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy/site:/d/site" -v "$QUAL_DIR:/q:ro" ${LOCK_FILE:+-v "$LOCK_FILE:/images.lock:ro"} "$IMAGE_PY" \
      python -m tools.pin_model "$@" --out /d/site/registry.site.yaml 2>&1 | sed 's/^/    /'
    return "${PIPESTATUS[0]}"
  }
  set +e
  pin_tool --promote-shipped "$GPU" --records /q --images-lock /images.lock
  rc=$?
  if [ "$rc" = 0 ]; then
    canary=1  # anything that keeps the canary from running counts as a canary that did not pass
    if "${COMPOSE[@]}" restart gateway >/dev/null 2>&1 && "${COMPOSE[@]}" up -d --wait gateway >/dev/null 2>&1; then
      say "model pair: the canary on this box (trialbox selftest)"
      if command -v python3 >/dev/null; then
        python3 -m tools.trialbox selftest 2>&1 | sed 's/^/    /'
        canary="${PIPESTATUS[0]}"
      fi
    fi
    if [ "$canary" = 0 ]; then
      pin_tool --confirm-shipped "$GPU"
      # the orchestrator ran its start canary while the pair was candidate: started again, its own canary gate
      # opens on the promoted pair (until then note answers send a patient to review and never exclude)
      "${COMPOSE[@]}" restart orchestrator >/dev/null 2>&1 \
        || FAILS+=("the orchestrator did not restart after the model pair was promoted: docker compose --project-directory deploy restart orchestrator")
    elif pin_tool --demote-pair "$GPU" && "${COMPOSE[@]}" restart gateway >/dev/null 2>&1; then
      FAILS+=("the model pair was promoted on its shipped record but the canary on this box did not pass (above): it is back to candidate and routes nothing; check the card, the driver and the model servers' logs, then re-run (RUNBOOK §11)")
    else
      FAILS+=("the model pair was promoted on its shipped record, the canary on this box did not pass (above), and the pair could NOT be put back: run python3 -m tools.pin_model --demote-pair $GPU, then restart the gateway, before anything is screened (RUNBOOK §11)")
    fi
  elif [ "$rc" = 5 ]; then  # D-887: the rehearsal media's placeholders, never promoted (said above)
    echo "    rehearsal box: the pair is the media's placeholder pins (candidate, never promoted); nothing to qualify"
  elif [ "$rc" != 4 ]; then  # 4: champion before this install and nothing waits for a canary; left as it is
    FAILS+=("the model pair is not qualified on this box (above): no record in deploy/qualification/$GPU matches its weights, model server image and chat template; it routes nothing in PRODUCTION until the release ships one or the pair is qualified here (RUNBOOK §11)")
  fi
  set -e
fi
# T-632 (OPS-014): every overlay renders; an error is shown, never hidden
tree_args
if SHEET_OUT="$(docker run --rm -v "$ROOT/deploy:/app/deploy" ${TREE_APP[@]+"${TREE_APP[@]}"} ${SHEET_MOUNT[@]+"${SHEET_MOUNT[@]}"} --user "$(id -u):$(id -g)" "$IMAGE_PY" \
     python -m tools.network_sheet --files "$SHEET_FILES" --env deploy/.env --out deploy/site/network-sheet 2>&1)"; then
  echo "    network sheet: deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}"
else
  echo "$SHEET_OUT" | tail -5 | sed 's/^/    /' >&2
  FAILS+=("network sheet not written (python -m tools.network_sheet, error above)")
fi
[ -f deploy/secrets/backup.pub ] || echo "install: note: no backup key yet. With hospital IT: python3 -m tools.trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub (RUNBOOK §5); updates refuse to run without a backup" >&2
# T-117b (D-274): the backup cron (/etc/cron.d/trialbox-backup), WAL archiving when the db image carries pgBackRest
# and a target is off the box, and the first backup. PRODUCTION needs an alert route (TB_BACKUP_ALERT_CMD, or
# TB_BACKUP_MAILTO with a mail relay, or on a box with no mail TB_BACKUP_ALERT_ROUTE=health-page, D-735); `trialbox
# doctor` then checks the backup's age and its off-box target
# H-92: on a systemd host backup-install writes the schedule as timers: no /etc/cron.d (no cron package) needed
[ "${SYSTEMD_HOST:-0}" = 1 ] && command -v python3 >/dev/null && CAN_CRON=1
[ -z "${TEST_BOX:-}" ] || echo "    test box: no backup schedule, no log retention cron (the host's are the ordinary box's; H-106)"
if [ "$CAN_CRON" = 1 ]; then
  say "backups: cron, WAL archiving, first backup"
  set +e
  PYTHONPATH="$PWD/libs${PYTHONPATH:+:$PYTHONPATH}" python3 -m tools.trialbox backup-install --deploy deploy ${TB_CRON_DIR:+--cron-dir "$TB_CRON_DIR"} ${TB_SYSTEMD_DIR:+--systemd-dir "$TB_SYSTEMD_DIR"} 2>&1 | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  set -e
  if [ "$rc" != 0 ] && [ "${TB_BOX:-0}" != 1 ]; then
    stop_or_warn backup-schedule "the backup schedule (no backup runs)" "the backup schedule is not installed (above): set TB_BACKUP_ALERT_CMD, TB_BACKUP_MAILTO with a mail relay, or on a box with no mail TB_BACKUP_ALERT_ROUTE=health-page in deploy/.env (RUNBOOK §5), then re-run"
  elif [ "$rc" != 0 ]; then
    # OPS-003 (D-566): a box has no alert route yet (no mail relay on a fresh host). A stop here is a stop before
    # the wizard; a FAIL line leaves the stack running, and box-install.sh goes on to the first-run code and
    # installs the schedule again after the owner's answers
    FAILS+=("the backup schedule is not installed yet (above): box-install.sh installs it again after the first-run set-up; if it is still missing, run the command below. 首次設定後會重新安裝備份排程，若仍未安裝，請執行此指令。初期設定後にバックアップスケジュールを再設定します。それでも未設定の場合は次のコマンドを実行してください。 PYTHONPATH=libs python3 -m tools.trialbox backup-install --deploy deploy (RUNBOOK §5)")
  fi
else
  echo "install: warning: the backup cron is not installed (needs root, /etc/cron.d and python3). 備份排程尚未安裝，需要管理員權限、/etc/cron.d 及 python3。バックアップスケジュールは未設定です。管理者権限、/etc/cron.d、python3 が必要です。 PYTHONPATH=libs python3 -m tools.trialbox backup-install --deploy deploy (RUNBOOK §5)" >&2
fi

for f in deploy/refdata/pending/*.tar; do  # D-140: the reference data pack of the install bundle, now the db runs
  [ -f "$f" ] || continue
  # 10G-1 (D-1323): a one-off run, the pack read-only, unpacked on the objects volume (TMPDIR) whose tb-refdata-*
  # leftovers it clears first; named, removed first and after a failure (review D3)
  docker rm -f tb-refdata-load >/dev/null 2>&1 || true
  if "${COMPOSE[@]}" run --rm --no-deps -T --name tb-refdata-load -e TMPDIR=/data/objects -v "$ROOT/$f:/in/refdata.tar:ro" \
    criteria-compiler sh -c 'rm -rf -- "${TMPDIR:?}"/tb-refdata-*; exec "$@"' tb-refdata-load \
    python -m tb_common.refdata load /in/refdata.tar --by deploy/install.sh; then
    # D-187: kept, not deleted: backups leave the pack's rows out and a restore loads it again from here
    mkdir -p deploy/refdata/loaded && mv -f "$f" deploy/refdata/loaded/; echo "    reference data loaded: $(basename "$f" .tar)"
  else
    docker rm -f tb-refdata-load >/dev/null 2>&1 || true
    "${COMPOSE[@]}" run --rm --no-deps -T --name tb-refdata-sweep -e TMPDIR=/data/objects criteria-compiler \
      sh -c 'rm -rf -- "${TMPDIR:?}"/tb-refdata-*' tb-refdata-sweep >/dev/null 2>&1 || true
    # H-58 (H10G1-04): a FAIL line, not a warning: an offline box without its pack has no trials
    FAILS+=("the reference data pack $(basename "$f") was not loaded (python -m tb_common.refdata load, error above): it stays in deploy/refdata/pending; re-run deploy/install.sh to load it again, or tools/apply_update.sh <bundle with refdata>")
  fi
done

if [ "$CTGOV" = offline ] && ! "${COMPOSE[@]}" exec -T criteria-compiler python -m tb_common.refdata status 2>/dev/null | grep -q pack_id; then
  echo "install: note: offline ClinicalTrials.gov needs a reference data pack: tools/apply_update.sh <bundle with refdata>" >&2
fi

# V-18 (D-1182, DB-C1): the code systems, in one step from one manifest: the hospital's licensed copies from its folder
# (TB_LICENSED_DIR) into the terminology volume, then the vocabulary and the FHIR store from the volume and the shipped
# tables. The same command is the manual update. A system not loaded is a line of the "information still needed" page,
# never a stop: deploy/terminology-update.sh loads it later, with no reinstall. Only a fault (a copy given but refused,
# or a reader not loaded) is also a line of the list; a system the box was not given is expected, not a fault
say "code systems: the hospital's folder, the vocabulary and the FHIR store (deploy/terminology-update.sh)"
deploy/terminology-update.sh 2>&1 | sed 's/^/    /' || true
while IFS="$(printf '\t')" read -r tl_key tl_why; do
  [ -z "$tl_key" ] || tb_stop_list "terminology/$tl_key" "$tl_why" "code system $tl_key not loaded (deploy/terminology-update.sh loads it later)"
done < <(PYTHONPATH=. python3 -m tools.terminology_load still-needed --faults --site deploy/site 2>/dev/null)

for f in deploy/updates/pending_audit/*.json; do  # the bundle's update.applied event, deferred until now
  [ -f "$f" ] || continue
  "${COMPOSE[@]}" exec -T orchestrator python -c '
import json, sys
from pathlib import Path
from tb_common.audit_writer import open_audit
s = json.load(sys.stdin)
open_audit(Path("/data/audit")).append("update.applied", actor="deploy/install.sh", input_sha=s["manifest_sha256"],
    detail={"bundle_id": s["bundle_id"], "signer": s["signer"], "files": s["files"]})
' < "$f" && rm -f "$f" && echo "    audited bundle $(basename "$f" .json)"
done

# H-48 (D-1328): a switch of TB_TLS_OLD_CLIENTS since the last audited one is an event of the box's audit chain,
# sent from the orchestrator's container as update.applied is: update.tls_relaxed (cbc on) or update.tls_strict (back
# to off). deploy/site/tls-old-clients.audited keeps the last audited value; an event not sent stays due (FAILS)
TLS_OLD_MARK=deploy/site/tls-old-clients.audited
TLS_OLD_WAS="$(cat "$TLS_OLD_MARK" 2>/dev/null || true)"; TLS_OLD_WAS="${TLS_OLD_WAS:-off}"
if [ "$TLS_OLD" != "$TLS_OLD_WAS" ]; then  # with TLS off too: doctor compares the setting with this marker
  TLS_OLD_EVENT=update.tls_relaxed; [ "$TLS_OLD" != off ] || TLS_OLD_EVENT=update.tls_strict
  if "${COMPOSE[@]}" exec -T orchestrator python -c '
import sys
from pathlib import Path
from tb_common.audit_writer import open_audit
event, value, was = sys.argv[1:4]
open_audit(Path("/data/audit")).append(event, actor="deploy/install.sh",
    detail={"setting": "TB_TLS_OLD_CLIENTS", "value": value, "was": was, "decision": "D-1328"})
' "$TLS_OLD_EVENT" "$TLS_OLD" "$TLS_OLD_WAS"; then
    mkdir -p deploy/site && printf '%s\n' "$TLS_OLD" > "$TLS_OLD_MARK"
    echo "    audited $TLS_OLD_EVENT (TB_TLS_OLD_CLIENTS=$TLS_OLD, was $TLS_OLD_WAS)"
  else
    FAILS+=("TB_TLS_OLD_CLIENTS=$TLS_OLD is served but its switch was not audited ($TLS_OLD_EVENT): re-run deploy/install.sh once the orchestrator is up (RUNBOOK §12)")
  fi
fi

# ------------------------------------------------------------------------------------------------ 5. accounts
if [ "${TB_BOX:-0}" = 1 ]; then  # T-729: the owner makes the first accounts in the first-run wizard
  say "first accounts: the first-run wizard (box-install.sh shows its address and one-time code)"
  ONCE_WHERE="with the account the owner makes in the first-run wizard"
else
say "first console administrator"
ADMIN_MAIL="$(sed -n 's/^MAIL_ADMIN_ADDR=//p' deploy/.env | head -1)"
ADMIN_MAIL="${ADMIN_MAIL:-${TB_ADMIN_EMAIL:-}}"
# H-96 (7097514776; H-94 (5): a secret where others can read it): the administrator's first password and enrolment
# code are shown on a terminal once and are never written to a log. On stdout only when stdout is a terminal; else on
# the controlling terminal (box-install.sh tees stdout to deploy/site/box/install.log, a rehearsal to its step log);
# with no terminal at all, in a root-only file in the home that the passwd entry names, never printed. No variable of
# the caller names where they go (no home from the environment, no knob); a link at the file's name is refused, the file is made new
show_once() {  # $1: the one-time text (an argument of a shell function: no process, no temporary file)
  local home
  ONCE_WHERE="as admin, with the password and the enrolment code shown once on this terminal above"
  if [ -t 1 ]; then printf '%s\n' "$1"; return 0; fi
  if { : >> /dev/tty; } 2>/dev/null; then
    printf '%s\n' "$1" >> /dev/tty
    echo "    shown on this terminal only: never in this output, which a log may keep"
    return 0
  fi
  home="$(getent passwd "$(id -u)" | cut -d: -f6)" || home=""  # no passwd entry: no file, a warning says so
  ONCE_FILE="${home%/}/trialbox-admin-first-sign-in${TEST_BOX:+-$TEST_BOX}"  # H-106: a test box's own
  ONCE_WHERE="as admin: the first password and the enrolment code were not kept (the FAIL lines below say why)"
  if [ -z "$home" ] || [ ! -d "$home" ]; then  # no passwd entry or home for this user (never root's on a box)
    ONCE_WHERE="as admin: the first password and the enrolment code were not kept (no home for uid $(id -u))"
    echo "    no terminal and no home for uid $(id -u) in the passwd file: the first password and enrolment code were not kept; run console.cli reset-password admin and enrol-code admin on a terminal" >&2
    return 0
  fi
  if [ -L "$ONCE_FILE" ] || { [ -e "$ONCE_FILE" ] && [ ! -f "$ONCE_FILE" ]; }; then
    FAILS+=("no terminal, and $ONCE_FILE is a link or not a regular file: the first password and enrolment code were not kept; remove it, then console.cli reset-password admin and enrol-code admin on a terminal")
    return 0
  fi
  rm -f "$ONCE_FILE"
  if ! (umask 077; set -C; printf '%s\n' "$1" > "$ONCE_FILE") 2>/dev/null; then
    FAILS+=("no terminal, and $ONCE_FILE could not be made new: the first password and enrolment code were not kept; console.cli reset-password admin and enrol-code admin on a terminal")
    return 0
  fi
  ONCE_WHERE="as admin, with the password and the enrolment code in $ONCE_FILE (root only: read it once, then remove it)"
  echo "    no terminal to show it on: it is in $ONCE_FILE (root only, 0600), not in this output. Read it once" \
    "(sudo cat $ONCE_FILE), hand it to the administrator in person, then remove it (sudo rm $ONCE_FILE)"
}
if [ -n "$ADMIN_MAIL" ]; then
  ONCE="$("${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin --mailbox "$ADMIN_MAIL")" \
    || FAILS+=("the first administrator was not made (console.cli bootstrap-admin above)")
else
  ONCE="$("${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin)" \
    || FAILS+=("the first administrator was not made (console.cli bootstrap-admin above)")
fi
# T-632 (OPS-013, D-192): the first administrator's enrolment code, shown once; without it the account cannot set
# up its authenticator. An administrator who already has one gets none (exit 2: nothing to show)
set +e
ENROL="$("${COMPOSE[@]}" exec -T console python -m console.cli enrol-code admin 2>&1)"; rc=$?
set -e
case "$rc" in
  0) ONCE="$ONCE"$'\n'"$ENROL"$'\n'"hand the enrolment code to the administrator in person; it works once, for 24 hours" ;;
  2) echo "    admin has an authenticator already: no enrolment code (console.cli reset-totp admin for a new one)" ;;
  *) ONCE="$ONCE"$'\n'"enrol-code admin failed (rc $rc):"$'\n'"$ENROL"
     FAILS+=("no enrolment code for admin (python -m console.cli enrol-code admin)") ;;
esac
ENROL=""
show_once "$(printf '%s\n' "$ONCE" | sed 's/^/    /')"
ONCE=""
echo "    add coordinators and viewers on the console's Users page, or: docker compose exec console python -m console.cli add-user"
fi

# NEW-STD-2 (D-562): the first signed head of the audit chain, when the site named an anchor folder: the night's own
# command, once, so the box does not wait for 00:20 for its first head. Not a stop: a line of the install's report
if [ -n "$(envget TB_AUDIT_ANCHOR_TARGETS)" ] && [ "$(id -u)" = 0 ] && [ "${ANCHOR_UNSAFE:-0}" = 0 ]; then
  say "audit chain: the first signed head"
  if SIGN_OUT="$(python3 -m tools.trialbox audit-sign 2>&1)"; then
    echo "$SIGN_OUT" | sed 's/^/    /'
  else
    echo "$SIGN_OUT" | tail -5 | sed 's/^/    /' >&2
    FAILS+=("the first signed audit head was not made (python3 -m tools.trialbox audit-sign, above; RUNBOOK §2)")
  fi
fi

# ------------------------------------------------------------------------------------------------ 6. check
say "host check"
HOST_ARGS=(); [ "$MODE" = gpu ] && HOST_ARGS=(--gpu "$GPU" ${RRS_HOST[@]+"${RRS_HOST[@]}"})
# H-94 (5): its FAIL lines of a kept refusal (tb_kept_fails) are kept apart: on a PoC box they stay
# FAIL lines and the install ends 1 (review M-1 of #1396); its output is shown as before. tee -a: when this output is a
# file (box-install.sh's install.log, a rehearsal's step log) /dev/fd/8 is opened again, and without -a it is emptied
HOST_OUT=""; exec 8>&1
HOST_OUT="$(sh "$ROOT/deploy/check_host.sh" ${HOST_ARGS[@]+"${HOST_ARGS[@]}"} | tee -a /dev/fd/8)" \
  || FAILS+=("the host check reported FAIL lines (above; docs/SECURITY.md)")
exec 8>&-
SECRET_FAILS=()
while IFS= read -r l; do SECRET_FAILS+=("the host check: $l"); done < <(printf '%s\n' "$HOST_OUT" | tb_kept_fails \
  | sed -E 's/^FAIL +//' || true)
# T-632 (D-382): the judge, named from the configuration: its role, the registry's label for the build this profile
# serves, and the site's pin (tools/pin_model.py --name-judge); a stub box has none
if [ "$MODE" = gpu ]; then
  tree_args
  JUDGE="$(docker run --rm -v "$ROOT/deploy:/d:ro" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" python -m tools.pin_model --name-judge "$GPU" --out /d/site/registry.site.yaml 2>&1)" \
    || FAILS+=("the judge could not be named: $JUDGE")
else
  JUDGE="judge: none (stub mode: structured criteria only; note criteria wait for a GPU)"
fi
echo "    $JUDGE"
# T-632 (OPS-013): the https:// URL must answer from this host, with the certificate the clinic PCs will see
URL="http://127.0.0.1:$(envget TB_HOST_CONSOLE_PORT | grep . || echo 8090)"
if [ -n "$TLS_HOST" ]; then
  URL="https://$TLS_HOST"; TLS_PORT=443
  [ -z "${TEST_BOX:-}" ] || { TLS_PORT="$(envget TB_TLS_PORT)"; URL="https://$TLS_HOST:$TLS_PORT"; }  # H-106
  CA=()
  if [ "$(envget TB_TLS_MODE)" = internal ]; then  # Caddy's root: hospital IT installs it on the staff PCs (RUNBOOK §12)
    mkdir -p deploy/secrets/tls
    for _ in $(seq 1 12); do
      "${COMPOSE[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt deploy/secrets/tls/caddy-root.crt >/dev/null 2>&1 && break
      sleep 5
    done
    [ -s deploy/secrets/tls/caddy-root.crt ] && CA=(--cacert deploy/secrets/tls/caddy-root.crt) && echo "    Caddy root certificate: deploy/secrets/tls/caddy-root.crt (for the staff PCs)"
  elif [ -n "$(envget TB_OIDC_CA)" ]; then
    CA=(--cacert "$(envget TB_OIDC_CA)")
  fi
  ANSWERED=0
  for _ in $(seq 1 "${TB_INSTALL_URL_TRIES:-24}"); do
    if curl -fsS -o /dev/null -m 10 ${CA[@]+"${CA[@]}"} --resolve "$TLS_HOST:$TLS_PORT:${TB_TLS_CHECK_ADDR:-127.0.0.1}" "$URL/login"; then ANSWERED=1; break; fi
    sleep 5
  done
  [ "$ANSWERED" = 1 ] && echo "    $URL/login answers (certificate checked)" || FAILS+=("$URL/login does not answer from this host (curl above; RUNBOOK §12)")
fi
# D-884: the release gates' mode from the installed record; "report" is not a green release
GATES_MODE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("vuln_mode") or "not recorded")' deploy/updates/installed.json 2>/dev/null || echo "not recorded")"
[ "$GATES_MODE" = block ] || [ "$GATES_MODE" = "not recorded" ] || GATES_MODE="$GATES_MODE (findings shown, not blocking: not a green release)"
cat <<EOT

  TrialBox is running.
  Console:            $URL   (sign in ${ONCE_WHERE:-as admin})
  Intake mailbox:     $(sed -n 's/^MAIL_INTAKE_ADDR=//p' deploy/.env | head -1)
  Feed folder:        $(envget TB_SOURCE_DIR | grep . || echo "-")   mapping: deploy/site/mapping, then the image
  $JUDGE
  First ingest:       docker compose --project-directory deploy exec adapter python -m adapter.cli run   (or 02:00 nightly)
  Acceptance:         docs/RUNBOOK.md §6 before go-live;  updates: tools/apply_update.sh <bundle>
  Release gates:      $GATES_MODE
  Known limit:        SCREEN of the whole hospital stops at about 45,000 patients (the orchestrator's memory cap,
                      TB_MEM_ORCH; lower on the two-device workstation): CHANGELOG.md, "Known limits"
EOT
# TEST-BOX (H-106): the summary says what the box is, and how its own command is reached
if [ -n "${TEST_BOX:-}" ]; then
  echo "  $(python3 -m tools.trialbox.testbox words --deploy "$ROOT/deploy")"
  echo "  Its commands:       sudo trialbox --box ${TEST_BOX:-} doctor   (or tools/testboxes.sh list; remove: tools/testboxes.sh remove ${TEST_BOX:-})"
fi
# BENCH (H-116): the summary says what the box is
[ -z "$BENCH_MARK" ] || echo "  $(python3 -m tools.trialbox.benchbox words --deploy "$ROOT/deploy")"
# REHEARSAL-REAL-SERVERS (H-89): the summary says what the box is
if [ "$REAL_SERVERS" = 1 ]; then
  echo "  REHEARSAL BOX:      $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["words"])' deploy/site/rehearsal-real-servers.json)"
fi
# ---- end of REHEARSAL-REAL-SERVERS (H-89)
# REHEARSAL-REAL-SERVERS (H-89): a rehearsal box's install is complete (no FAIL line remains): from here on the start
# check reads a missing TB_ENV as PRODUCTION (tools/rehearsal_real.py COMPLETE). Only this line writes the file
if [ "$REHEARSAL" = 1 ] && [ "${#FAILS[@]}" -eq 0 ]; then
  printf '{"rehearsal_install_complete": true}\n' > deploy/site/rehearsal-install-complete.json
fi
# ---- end of REHEARSAL-REAL-SERVERS (H-89)
# H-94: on a PoC box each FAIL line is a warning and a line of the list, and the install ends 0; elsewhere every
# FAIL line, then exit 1, as before
# H-94 (5): on a PoC box a FAIL line of the host check of a kept refusal (tb_kept_fails: a secret's mode, and (2),
# (3)) stays a FAIL: the other FAIL lines warn
# and are listed, then those lines and exit 1. On any other box the lines below stop, with master's words
if [ "${#SECRET_FAILS[@]}" -gt 0 ] && tb_poc_box; then
  for f in "${FAILS[@]}"; do stop_or_warn --silent "fail: $(printf '%s' "$f" | cut -c1-40)" "" "FAIL: $f"; done
  printf 'install: FAIL: %s\n' "${SECRET_FAILS[@]}" >&2
  exit 1  # H-94 (5): a secret's file or key where others can read it (and the (2), (3) lines of tb_kept_fails)
fi
if [ "${#FAILS[@]}" -gt 0 ]; then
  tb_poc_box || printf 'install: FAIL: %s\n' "${FAILS[@]}" >&2
  for f in "${FAILS[@]}"; do stop_or_warn --silent "fail: $(printf '%s' "$f" | cut -c1-40)" "" "FAIL: $f"; done
fi
