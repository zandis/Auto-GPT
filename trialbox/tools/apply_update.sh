#!/bin/sh
# Apply a signed offline update bundle (SPEC §10.1 "Updates"; DECISIONS D-77, D-138, D-210). No auto-update: an
# operator runs this, from the install folder, as root.
#
#   tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup [--no-backup-reason REASON]] [--allow-downgrade REASON]
#   tools/apply_update.sh SOFTWARE_PACK.tar --dry-run --with-model-pack MODEL_PACK   # H-95: as if that model pack were held
#   tools/apply_update.sh status              # the update in progress (or not), the installed release, the keys
#   tools/apply_update.sh rollback BUNDLE_ID  # roll back an update that was interrupted (power cut, kill -9)
#   tools/apply_update.sh clean               # remove left-over rollback points of finished updates
#   tools/apply_update.sh ospatch BUNDLE.tar [--dry-run] [--conf FILE]   # an offline OS patch bundle (T-634, D-408)
#   tools/apply_update.sh ospatch-check       # after the OS patch's reboot: doctor and the canary
#
# ospatch (OPS-024): the same signed bundle format, its payloads all `other` under ospatch/ (a dated apt snapshot,
# deploy/hardening/ospatch.py). Steps 0, 0b and 1 below run as for any bundle, except that release_seq is not compared
# with installed.json (an OS snapshot does not change the TrialBox release; ospatch.py refuses a snapshot that is not
# newer than the last one applied). Then deploy/hardening/ospatch.py apply: the snapshot must match this host's system
# and architecture, held packages stay, apt reads the staged repository only, the reboot plan, the canary. An OS
# patch bundle given without `ospatch`, or a TrialBox bundle given with it, is refused.
#
# 0. refused while deploy/updates/IN_PROGRESS.json exists (an unfinished update: `status`, then `rollback`);
# 0b. the site keys (T-210b, D-347; python3 -m tools.keys check --for-update): refused when a key is both plain and
#    wrapped, a wrapped key names another KEK, the KEK sits in the secrets folder, or the keys are wrapped and the KEK
#    is not unsealed (tools/keys.py unseal): the services the update restarts could not open them, and the update
#    would roll back half way. Plain keys in VALIDATION or PRODUCTION are a warning here (doctor key_custody FAILs).
#    The secrets folder is TB_SECRETS_HOST_DIR (default: the compose volume); a host without it is not checked;
# 1. verify (tools/verify_update.py), before any payload is staged: the Ed25519 signature with a key the box trusts
#    (deploy/updates/trust.json, else deploy/keys/vendor_ed25519.pub and vendor_ed25519.next.pub), key_id, the
#    manifest schema, not_after, a key rotation (accepted once), release_seq above the installed one (an older or
#    equal one only with --allow-downgrade REASON, audited as update.downgrade), min_installed_version, the
#    compatibility table compat.json against deploy/updates/installed.json, release.json's image digests against
#    images.lock (a null digest is refused), the free space to stage; then every payload's size and sha256 while it
#    is copied — in a network-less trialbox-py container running this install's verifier (host python3 +
#    cryptography is used when available). A refused bundle changes nothing (exit 1);
#    H-95: the image archives and the weights are hashed on the stick and never staged (--stream image --stream model):
#    no copy of them is written on the box. A software pack (manifest pack, H-95) is refused unless the model pack it
#    names by its signed identity is the one in deploy/updates/model-pack.json;
# 2. stage the verified small payloads (re-hashed while copying); --dry-run stops here;
# 3. the update path (python3 -m tools.trialbox update; tools/trialbox/update.py): preflight again under the update
#    lock (compat.json against the schema versions read from the database, release_seq, the backup key and target,
#    the free space on every file system it writes, with the numbers) — a refused preflight changes nothing; then
#    the marker deploy/updates/IN_PROGRESS.json -> backup first (D-126) -> rollback point (images tagged
#    <repo>:rollback-<bundle>, overwritten models kept, database dumps encrypted with a per-update key,
#    rulesets-data tagged) -> apply -> migrate and restart -> rulesets -> check -> reference data (its own step) ->
#    installed.json, trust.json, `update.applied` audited, the rollback point deleted, the marker removed.
#    Any failure from apply to check: everything is put back, `update.rolled_back` audited, the marker removed;
#    if the rollback itself fails the marker stays (restore from the backup, RUNBOOK §5).
#    --no-backup skips the backup on a DEV, TEST or VALIDATION box; on a PRODUCTION box (deploy/.env TB_ENV, unset
#    or any other name counts as PRODUCTION, D-633) only with --no-backup-reason REASON, audited as
#    update.backup_skipped (D-1321); without one it is refused before anything is read (exit 2).
#    A box that is not running yet (the first install) only loads the payloads; install.sh audits it after start.
#    H-95: the images and the weights are read from the bundle again as they load, each hashed again on the way in;
#    one whose second read fails its hash is not loaded (tools/trialbox/update.py stream_image, stream_models).
#    --target demo: the one-container demo VM (docs/RUNBOOK.md §11), checked by running e2e_simple in the new container.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
UPDATES="$ROOT/deploy/updates"
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
# H-94: apply_update.sh has no --environment: its PoC box is the record (deploy/.env, the mark) alone
TB_STOP_WHO=apply_update; TB_STOP_FILE=apply_update.sh; TB_STOP_DEPLOY="$ROOT/deploy"; TB_STOP_ARG_ENV=""; TB_STOP_REHEARSAL=0
USAGE="usage: tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup [--no-backup-reason REASON]] [--allow-downgrade REASON] [--with-model-pack MODEL_PACK (with --dry-run)] [--for-software SOFTWARE_PACK] | status | rollback BUNDLE_ID | clean | ospatch BUNDLE.tar [--dry-run] [--conf FILE] | ospatch-check [--conf FILE]"
case "${1:-}" in
  status|clean) cd "$ROOT"; exec python3 -m tools.update_status --deploy "$ROOT/deploy" "$1" ;;
  rollback) cd "$ROOT"; exec python3 -m tools.update_status --deploy "$ROOT/deploy" rollback "${2:?$USAGE}" ;;
  ospatch-check) cd "$ROOT"; shift; exec python3 "$ROOT/deploy/hardening/ospatch.py" check --deploy "$ROOT/deploy" "$@" ;;
  ""|-h|--help) echo "$USAGE" >&2; exit 2 ;;  # H-94 not a stop: the usage, asked for or with nothing to do
esac
OSPATCH=""; OSCONF=""
if [ "$1" = ospatch ]; then OSPATCH=1; shift; [ $# -gt 0 ] || { echo "$USAGE" >&2; exit 2; }; fi  # H-94 (1): no bundle
BUNDLE=$1
shift
DRY=""; TARGET=${TB_UPDATE_TARGET:-compose}; NOBACKUP=""; NOBACKUP_REASON=""; DOWNGRADE=""; WITH_MODEL=""; FOR_SOFTWARE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=--dry-run ;;
    --conf) if [ -n "$OSPATCH" ]; then OSCONF=$2; else stop_or_warn --rc 2 conf-without-ospatch "--conf $2 (ignored)" "--conf is for ospatch"; fi; shift ;;
    --target) TARGET=$2; shift ;;
    --no-backup) NOBACKUP=--no-backup ;;
    --no-backup-reason) NOBACKUP_REASON=${2:?--no-backup-reason needs a reason}; shift ;;
    --allow-downgrade) DOWNGRADE=${2:?--allow-downgrade needs a reason}; shift ;;
    # H-95: a dry run of a software pack as if this model pack were held (install.sh checks both before loading);
    # without --dry-run it changes nothing: the load is checked against the box's own record
    --with-model-pack) WITH_MODEL=${2:?--with-model-pack needs a model pack}; shift ;;
    # H-95: a model pack with the software pack loaded straight after it (it must name this model pack)
    --for-software) FOR_SOFTWARE=${2:?--for-software needs a software pack}; shift ;;
    *) echo "apply_update: unknown option $1" >&2; exit 2 ;;  # H-94 not a stop: a usage error, refused by name on every box (review L-5 of #1430): an option not understood is never acted on, nor its value taken for the bundle
  esac
  shift
done
[ -z "$NOBACKUP_REASON" ] || [ -n "$NOBACKUP" ] || { stop_or_warn --rc 2 reason-without-no-backup "--no-backup-reason (ignored: the backup is made)" "--no-backup-reason goes with --no-backup"; NOBACKUP_REASON=""; }
# D-1321: the box's environment as the update path reads it (deploy/.env's last TB_ENV line, the rehearsal mark
# when it names none; tools/trialbox/update.py ComposeBox.environment)
if [ -z "$OSPATCH" ] && [ -n "$NOBACKUP" ] && [ -z "$NOBACKUP_REASON" ]; then
  BOX_ENV=""; [ -f "$ROOT/deploy/.env" ] && BOX_ENV="$(tb_env_of "$ROOT/deploy/.env")"
  [ -z "$BOX_ENV" ] && [ -f "$ROOT/deploy/site/rehearsal.json" ] && BOX_ENV=TEST
  case "$BOX_ENV" in
    DEV|TEST|VALIDATION) ;;
    *) TB_STOP_WHO="update REFUSED"; stop_or_warn --rc 2 no-backup-production "" "--no-backup on a PRODUCTION box needs --no-backup-reason REASON (audited); nothing was changed"; TB_STOP_WHO=apply_update ;;
  esac
fi
PUBKEY=${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}
NEXTKEY="$ROOT/deploy/keys/vendor_ed25519.next.pub"
IMAGE=${TB_PY_IMAGE:-trialbox-py:1.0.0}

[ -f "$BUNDLE" ] || { echo "no such bundle: $BUNDLE" >&2; exit 2; }  # H-94 (1): no bundle, no signature
if [ -f "$UPDATES/IN_PROGRESS.json" ]; then
  echo "update REFUSED: an update is unfinished ($UPDATES/IN_PROGRESS.json)." >&2
  echo "  tools/apply_update.sh status, then tools/apply_update.sh rollback <bundle> (nothing was changed)" >&2
  # H-94 depends (1): the box is between two releases (its rollback point holds the signed one): nothing is applied
  # over a release that is not shown whole
  exit 1
fi
SECRETS=${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/trialbox_tb-secrets/_data}
if [ -d "$SECRETS" ]; then
  ( cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT" python3 -m tools.keys check --for-update --secrets "$SECRETS" ) \
    || { echo "update REFUSED: the site keys (above); nothing was changed" >&2; exit 1; }  # H-94 (5): a KEK beside the keys it seals, keys plain and wrapped
fi
[ -f "$UPDATES/trust.json" ] || [ -f "$PUBKEY" ] || { echo "vendor public key not installed: $PUBKEY" >&2; exit 2; }  # H-94 (1)
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/tb-update.XXXXXX")
chmod 0700 "$STAGE"  # H-95: a folder of its own, 0700 wherever TMPDIR points (mktemp -d makes it so; said here)
# H-114 (ESC-4): INT, TERM and HUP alike. Before the update path starts, a signal ends the script here and nothing
# was changed (before, the trap only removed the stage and the script went on, the update path included). Once the
# update path runs, the shell waits for it: it took the same signal from the terminal, and it rolls back or finishes
# and says which; a signal sent to the shell alone leaves it to end by itself
STARTED=""
tb_signalled() {  # NAME CODE
  rm -rf "$STAGE"
  [ -z "$STARTED" ] || return 0
  trap - EXIT
  echo "apply_update: stopped by $1 before the update started; nothing was changed" >&2
  exit "$2"  # H-94 not a stop: a signal the person sent, not a guard
}
trap 'rm -rf "$STAGE"' EXIT
trap 'tb_signalled SIGINT 130' INT
trap 'tb_signalled SIGTERM 143' TERM
trap 'tb_signalled SIGHUP 129' HUP
BUNDLE_ABS=$(cd "$(dirname "$BUNDLE")" && pwd)/$(basename "$BUNDLE")

# the verifier's arguments: the trust and the installed record are read only, and only when they exist
# H-95: the images and the weights stay on the stick; the model pack the box holds, for a software pack's check
set -- "$BUNDLE_ABS" --stage "$STAGE" --stream image --stream model --model-pack-record "$UPDATES/model-pack.json"
[ -f "$UPDATES/trust.json" ] && set -- "$@" --trust "$UPDATES/trust.json"
# an OS patch does not move the TrialBox release: its order is the snapshot date's (ospatch.py)
[ -z "$OSPATCH" ] && [ -f "$UPDATES/installed.json" ] && set -- "$@" --installed "$UPDATES/installed.json"
[ -f "$ROOT/deploy/images.lock" ] && set -- "$@" --images-lock "$ROOT/deploy/images.lock"
if [ ! -f "$UPDATES/trust.json" ]; then
  PUBKEY=$(cd "$(dirname "$PUBKEY")" && pwd)/$(basename "$PUBKEY")
  set -- "$@" --pubkey "$PUBKEY"
  [ -f "$NEXTKEY" ] && set -- "$@" --pubkey "$NEXTKEY"
fi
[ -n "$DOWNGRADE" ] && set -- "$@" --allow-downgrade "$DOWNGRADE"
[ -n "$DRY" ] || WITH_MODEL=""  # a dry run only: a load checks the box's own record (and mounts nothing for it)
if [ -n "$WITH_MODEL" ]; then
  WITH_MODEL=$(cd "$(dirname "$WITH_MODEL")" && pwd)/$(basename "$WITH_MODEL")
  set -- "$@" --model-pack-candidate "$WITH_MODEL"
fi
if [ -n "$FOR_SOFTWARE" ]; then
  FOR_SOFTWARE=$(cd "$(dirname "$FOR_SOFTWARE")" && pwd)/$(basename "$FOR_SOFTWARE")
  set -- "$@" --software-candidate "$FOR_SOFTWARE"
fi
# the docker fallback passes these paths as mount arguments: no whitespace or glob characters in any of them
case "$ROOT|$BUNDLE_ABS|$STAGE|$PUBKEY|$WITH_MODEL|$FOR_SOFTWARE" in
  *[[:space:]*?\[]*) echo "update REFUSED: a path has a space or a glob character: $ROOT, $BUNDLE_ABS, $STAGE, $PUBKEY $WITH_MODEL $FOR_SOFTWARE" >&2; exit 2 ;;  # H-94 (1): the verifier would check another file
esac

# host python3 with cryptography (a clean site host has it from the media's debs; tools/verify_update.py checks the
# manifest schema without jsonschema there, D-176): on a first install the trialbox-py image is still inside the bundle
if [ -z "${TB_VERIFY_IN_DOCKER:-}" ] && python3 -c "import cryptography" 2>/dev/null; then
  SUMMARY=$(PYTHONPATH="$ROOT/libs:$ROOT" python3 "$ROOT/tools/verify_update.py" "$@") \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }  # H-94 (1)
else
  # this install's verifier (mounted read-only), not the one inside the image (the image may be a release older than
  # the manifest format); every host path keeps its own absolute path inside the container
  MOUNTS="-v $ROOT:$ROOT:ro -v $BUNDLE_ABS:$BUNDLE_ABS:ro -v $STAGE:$STAGE"
  [ -f "$PUBKEY" ] && MOUNTS="$MOUNTS -v $PUBKEY:$PUBKEY:ro"
  [ -n "$WITH_MODEL" ] && MOUNTS="$MOUNTS -v $WITH_MODEL:$WITH_MODEL:ro"
  [ -n "$FOR_SOFTWARE" ] && MOUNTS="$MOUNTS -v $FOR_SOFTWARE:$FOR_SOFTWARE:ro"
  # shellcheck disable=SC2086
  SUMMARY=$(docker run --rm --network none --user "$(id -u):$(id -g)" $MOUNTS -e PYTHONPATH="$ROOT/libs:$ROOT" \
      "$IMAGE" python "$ROOT/tools/verify_update.py" "$@") \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }  # H-94 (1)
fi
echo "verified: $SUMMARY"

# T-634 (D-408): an OS patch bundle goes to the host's packages, never to the TrialBox update path, and back
if [ -n "$OSPATCH" ]; then
  # shellcheck disable=SC2086
  python3 "$ROOT/deploy/hardening/ospatch.py" apply --stage "$STAGE" --deploy "$ROOT/deploy" \
    ${OSCONF:+--conf "$OSCONF"} $DRY
  exit $?  # H-94 not a stop: ospatch.py's own answer
fi
if [ -d "$STAGE/other/ospatch" ]; then
  echo "update REFUSED: $BUNDLE is an OS patch bundle: tools/apply_update.sh ospatch $BUNDLE (nothing was changed)" >&2
  exit 1  # H-94 (1): the signed bundle is not of the kind this command applies
fi

if [ "$DRY" = "--dry-run" ]; then
  echo "dry run: staged in $STAGE (removed on exit); nothing applied"
  find "$STAGE" -type f ! -name manifest.json | sed "s#^$STAGE/#  would apply #"
  echo "  would load from the bundle, hashed again as each loads (H-95): its images and weights"
  exit 0
fi

# in the 0700 stage folder, beside the staged manifest.json whose sha256 the update path checks against it
( umask 077; printf '%s' "$SUMMARY" > "$STAGE/summary.json" )
cd "$ROOT"
# D-888: the update restarts the stack: never on the example settings while the site's exist
# H-94 (3): the start guard warns by itself on a PoC box for what is not one of the five (7102087475); what it still
# refuses there is its kept refusal (3), a rehearsal box never starting as PRODUCTION (review M-1 of #1430)
sh "$ROOT/deploy/settings_guard.sh" "$ROOT/deploy" || { echo "update REFUSED: nothing was changed" >&2; exit 1; }  # H-94 (3)
STARTED=1
python3 -m tools.trialbox update --stage "$STAGE" --summary "$STAGE/summary.json" --target "$TARGET" \
  --deploy "$ROOT/deploy" --bundle "$BUNDLE_ABS" $NOBACKUP ${NOBACKUP_REASON:+--no-backup-reason "$NOBACKUP_REASON"}
