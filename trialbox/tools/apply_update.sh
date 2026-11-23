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
USAGE="usage: tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup [--no-backup-reason REASON]] [--allow-downgrade REASON] [--with-model-pack MODEL_PACK (with --dry-run)] | status | rollback BUNDLE_ID | clean | ospatch BUNDLE.tar [--dry-run] [--conf FILE] | ospatch-check [--conf FILE]"
case "${1:-}" in
  status|clean) cd "$ROOT"; exec python3 -m tools.update_status --deploy "$ROOT/deploy" "$1" ;;
  rollback) cd "$ROOT"; exec python3 -m tools.update_status --deploy "$ROOT/deploy" rollback "${2:?$USAGE}" ;;
  ospatch-check) cd "$ROOT"; shift; exec python3 "$ROOT/deploy/hardening/ospatch.py" check --deploy "$ROOT/deploy" "$@" ;;
  ""|-h|--help) echo "$USAGE" >&2; exit 2 ;;
esac
OSPATCH=""; OSCONF=""
if [ "$1" = ospatch ]; then OSPATCH=1; shift; [ $# -gt 0 ] || { echo "$USAGE" >&2; exit 2; }; fi
BUNDLE=$1
shift
DRY=""; TARGET=${TB_UPDATE_TARGET:-compose}; NOBACKUP=""; NOBACKUP_REASON=""; DOWNGRADE=""; WITH_MODEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=--dry-run ;;
    --conf) [ -n "$OSPATCH" ] || { echo "apply_update: --conf is for ospatch" >&2; exit 2; }; OSCONF=$2; shift ;;
    --target) TARGET=$2; shift ;;
    --no-backup) NOBACKUP=--no-backup ;;
    --no-backup-reason) NOBACKUP_REASON=${2:?--no-backup-reason needs a reason}; shift ;;
    --allow-downgrade) DOWNGRADE=${2:?--allow-downgrade needs a reason}; shift ;;
    # H-95: a dry run of a software pack as if this model pack were held (install.sh checks both before loading);
    # without --dry-run it changes nothing: the load is checked against the box's own record
    --with-model-pack) WITH_MODEL=${2:?--with-model-pack needs a model pack}; shift ;;
    *) echo "apply_update: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -z "$NOBACKUP_REASON" ] || [ -n "$NOBACKUP" ] || { echo "apply_update: --no-backup-reason goes with --no-backup" >&2; exit 2; }
# D-1321: the box's environment as the update path reads it (deploy/.env's last TB_ENV line, the rehearsal mark
# when it names none; tools/trialbox/update.py ComposeBox.environment)
if [ -z "$OSPATCH" ] && [ -n "$NOBACKUP" ] && [ -z "$NOBACKUP_REASON" ]; then
  BOX_ENV=""; [ -f "$ROOT/deploy/.env" ] && BOX_ENV="$(sed -n 's/^TB_ENV=//p' "$ROOT/deploy/.env" | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
  [ -z "$BOX_ENV" ] && [ -f "$ROOT/deploy/site/rehearsal.json" ] && BOX_ENV=TEST
  case "$BOX_ENV" in
    DEV|TEST|VALIDATION) ;;
    *) echo "update REFUSED: --no-backup on a PRODUCTION box needs --no-backup-reason REASON (audited); nothing was changed" >&2; exit 2 ;;
  esac
fi
PUBKEY=${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}
NEXTKEY="$ROOT/deploy/keys/vendor_ed25519.next.pub"
IMAGE=${TB_PY_IMAGE:-trialbox-py:1.0.0}

[ -f "$BUNDLE" ] || { echo "no such bundle: $BUNDLE" >&2; exit 2; }
if [ -f "$UPDATES/IN_PROGRESS.json" ]; then
  echo "update REFUSED: an update is unfinished ($UPDATES/IN_PROGRESS.json)." >&2
  echo "  tools/apply_update.sh status, then tools/apply_update.sh rollback <bundle> (nothing was changed)" >&2
  exit 1
fi
SECRETS=${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/trialbox_tb-secrets/_data}
if [ -d "$SECRETS" ]; then
  ( cd "$ROOT" && PYTHONPATH="$ROOT/libs:$ROOT" python3 -m tools.keys check --for-update --secrets "$SECRETS" ) \
    || { echo "update REFUSED: the site keys (above); nothing was changed" >&2; exit 1; }
fi
[ -f "$UPDATES/trust.json" ] || [ -f "$PUBKEY" ] || { echo "vendor public key not installed: $PUBKEY" >&2; exit 2; }
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/tb-update.XXXXXX")
chmod 0700 "$STAGE"  # H-95: a folder of its own, 0700 wherever TMPDIR points (mktemp -d makes it so; said here)
trap 'rm -rf "$STAGE"' EXIT INT TERM HUP
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
if [ -n "$WITH_MODEL" ] && [ -n "$DRY" ]; then  # a dry run only: a load checks the box's own record
  WITH_MODEL=$(cd "$(dirname "$WITH_MODEL")" && pwd)/$(basename "$WITH_MODEL")
  set -- "$@" --model-pack-candidate "$WITH_MODEL"
fi
# the docker fallback passes these paths as mount arguments: no whitespace or glob characters in any of them
case "$ROOT|$BUNDLE_ABS|$STAGE|$PUBKEY|$WITH_MODEL" in
  *[[:space:]*?\[]*) echo "update REFUSED: a path has a space or a glob character: $ROOT, $BUNDLE_ABS, $STAGE, $PUBKEY $WITH_MODEL" >&2; exit 2 ;;
esac

# host python3 with cryptography (a clean site host has it from the media's debs; tools/verify_update.py checks the
# manifest schema without jsonschema there, D-176): on a first install the trialbox-py image is still inside the bundle
if [ -z "${TB_VERIFY_IN_DOCKER:-}" ] && python3 -c "import cryptography" 2>/dev/null; then
  SUMMARY=$(PYTHONPATH="$ROOT/libs:$ROOT" python3 "$ROOT/tools/verify_update.py" "$@") \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }
else
  # this install's verifier (mounted read-only), not the one inside the image (the image may be a release older than
  # the manifest format); every host path keeps its own absolute path inside the container
  MOUNTS="-v $ROOT:$ROOT:ro -v $BUNDLE_ABS:$BUNDLE_ABS:ro -v $STAGE:$STAGE"
  [ -f "$PUBKEY" ] && MOUNTS="$MOUNTS -v $PUBKEY:$PUBKEY:ro"
  [ -n "$WITH_MODEL" ] && MOUNTS="$MOUNTS -v $WITH_MODEL:$WITH_MODEL:ro"
  # shellcheck disable=SC2086
  SUMMARY=$(docker run --rm --network none --user "$(id -u):$(id -g)" $MOUNTS -e PYTHONPATH="$ROOT/libs:$ROOT" \
      "$IMAGE" python "$ROOT/tools/verify_update.py" "$@") \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }
fi
echo "verified: $SUMMARY"

# T-634 (D-408): an OS patch bundle goes to the host's packages, never to the TrialBox update path, and back
if [ -n "$OSPATCH" ]; then
  # shellcheck disable=SC2086
  python3 "$ROOT/deploy/hardening/ospatch.py" apply --stage "$STAGE" --deploy "$ROOT/deploy" \
    ${OSCONF:+--conf "$OSCONF"} $DRY
  exit $?
fi
if [ -d "$STAGE/other/ospatch" ]; then
  echo "update REFUSED: $BUNDLE is an OS patch bundle: tools/apply_update.sh ospatch $BUNDLE (nothing was changed)" >&2
  exit 1
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
sh "$ROOT/deploy/settings_guard.sh" "$ROOT/deploy" || { echo "update REFUSED: nothing was changed" >&2; exit 1; }
python3 -m tools.trialbox update --stage "$STAGE" --summary "$STAGE/summary.json" --target "$TARGET" \
  --deploy "$ROOT/deploy" --bundle "$BUNDLE_ABS" $NOBACKUP ${NOBACKUP_REASON:+--no-backup-reason "$NOBACKUP_REASON"}
