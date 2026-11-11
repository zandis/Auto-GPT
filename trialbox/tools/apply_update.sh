#!/bin/sh
# Apply a signed offline update bundle (SPEC §10.1 "Updates"; DECISIONS D-77, D-138, D-210). No auto-update: an
# operator runs this, from the install folder, as root.
#
#   tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup] [--allow-downgrade REASON]
#   tools/apply_update.sh status              # the update in progress (or not), the installed release, the keys
#   tools/apply_update.sh rollback BUNDLE_ID  # roll back an update that was interrupted (power cut, kill -9)
#   tools/apply_update.sh clean               # remove left-over rollback points of finished updates
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
# 2. stage the verified payloads (re-hashed while copying); --dry-run stops here;
# 3. the update path (python3 -m tools.trialbox update; tools/trialbox/update.py): preflight again under the update
#    lock (compat.json against the schema versions read from the database, release_seq, the backup key and target,
#    the free space on every file system it writes, with the numbers) — a refused preflight changes nothing; then
#    the marker deploy/updates/IN_PROGRESS.json -> backup first (D-126) -> rollback point (images tagged
#    <repo>:rollback-<bundle>, overwritten models kept, database dumps encrypted with a per-update key,
#    rulesets-data tagged) -> apply -> migrate and restart -> rulesets -> check -> reference data (its own step) ->
#    installed.json, trust.json, `update.applied` audited, the rollback point deleted, the marker removed.
#    Any failure from apply to check: everything is put back, `update.rolled_back` audited, the marker removed;
#    if the rollback itself fails the marker stays (restore from the backup, RUNBOOK §5).
#    A box that is not running yet (the first install) only loads the payloads; install.sh audits it after start.
#    --target demo: the one-container demo VM (docs/RUNBOOK.md §11), checked by running e2e_simple in the new container.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
UPDATES="$ROOT/deploy/updates"
USAGE="usage: tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup] [--allow-downgrade REASON] | status | rollback BUNDLE_ID | clean"
case "${1:-}" in
  status|clean) cd "$ROOT"; exec python3 -m tools.update_status --deploy "$ROOT/deploy" "$1" ;;
  rollback) cd "$ROOT"; exec python3 -m tools.update_status --deploy "$ROOT/deploy" rollback "${2:?$USAGE}" ;;
  ""|-h|--help) echo "$USAGE" >&2; exit 2 ;;
esac
BUNDLE=$1
shift
DRY=""; TARGET=${TB_UPDATE_TARGET:-compose}; NOBACKUP=""; DOWNGRADE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=--dry-run ;;
    --target) TARGET=$2; shift ;;
    --no-backup) NOBACKUP=--no-backup ;;
    --allow-downgrade) DOWNGRADE=${2:?--allow-downgrade needs a reason}; shift ;;
    *) echo "apply_update: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
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
trap 'rm -rf "$STAGE"' EXIT INT TERM HUP
BUNDLE_ABS=$(cd "$(dirname "$BUNDLE")" && pwd)/$(basename "$BUNDLE")

# the verifier's arguments: the trust and the installed record are read only, and only when they exist
set -- "$BUNDLE_ABS" --stage "$STAGE"
[ -f "$UPDATES/trust.json" ] && set -- "$@" --trust "$UPDATES/trust.json"
[ -f "$UPDATES/installed.json" ] && set -- "$@" --installed "$UPDATES/installed.json"
[ -f "$ROOT/deploy/images.lock" ] && set -- "$@" --images-lock "$ROOT/deploy/images.lock"
if [ ! -f "$UPDATES/trust.json" ]; then
  PUBKEY=$(cd "$(dirname "$PUBKEY")" && pwd)/$(basename "$PUBKEY")
  set -- "$@" --pubkey "$PUBKEY"
  [ -f "$NEXTKEY" ] && set -- "$@" --pubkey "$NEXTKEY"
fi
[ -n "$DOWNGRADE" ] && set -- "$@" --allow-downgrade "$DOWNGRADE"
# the docker fallback passes these paths as mount arguments: no whitespace or glob characters in any of them
case "$ROOT|$BUNDLE_ABS|$STAGE|$PUBKEY" in
  *[[:space:]*?\[]*) echo "update REFUSED: a path has a space or a glob character: $ROOT, $BUNDLE_ABS, $STAGE, $PUBKEY" >&2; exit 2 ;;
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
  # shellcheck disable=SC2086
  SUMMARY=$(docker run --rm --network none --user "$(id -u):$(id -g)" $MOUNTS -e PYTHONPATH="$ROOT/libs:$ROOT" \
      "$IMAGE" python "$ROOT/tools/verify_update.py" "$@") \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }
fi
echo "verified: $SUMMARY"

if [ "$DRY" = "--dry-run" ]; then
  echo "dry run: staged in $STAGE (removed on exit); nothing applied"
  find "$STAGE" -type f ! -name manifest.json | sed "s#^$STAGE/#  would apply #"
  exit 0
fi

# in the 0700 stage folder, beside the staged manifest.json whose sha256 the update path checks against it
( umask 077; printf '%s' "$SUMMARY" > "$STAGE/summary.json" )
cd "$ROOT"
python3 -m tools.trialbox update --stage "$STAGE" --summary "$STAGE/summary.json" --target "$TARGET" \
  --deploy "$ROOT/deploy" $NOBACKUP
