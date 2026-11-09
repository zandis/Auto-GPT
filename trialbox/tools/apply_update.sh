#!/bin/sh
# Apply a signed offline update bundle (SPEC §10.1 "Updates"; DECISIONS D-77, D-138). No auto-update: an operator
# runs this, from the install folder, as root.
#
#   tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup]
#
# 1. verify: Ed25519 signature of manifest.json with the box's vendor key (TB_VENDOR_PUBKEY, default
#    deploy/keys/vendor_ed25519.pub), manifest schema, every payload's size + sha256, no extra/unsafe members —
#    in a network-less trialbox-py container (host python3 + cryptography is used when available);
#    a tampered or unsigned bundle is REJECTED (exit 1) and nothing is changed;
# 2. stage the verified payloads (re-hashed while copying); --dry-run stops here;
# 3. the update path (python3 -m tools.trialbox update; tools/trialbox/update.py, D-138):
#    backup first (D-126; refused without the backup key and a target) -> rollback point (images tagged
#    <repo>:rollback-<bundle>, overwritten models kept, local database dumps) -> apply (docker load, models, other
#    files) -> migrate and restart (the services migrate at start) -> rulesets (criteria-compiler import with the
#    approval and equivalence gates) -> check (every service healthy; TB_UPDATE_CHECK_CMD) -> `update.applied`
#    in the audit log. Any failure after the rollback point: images, models and database are put back, the box
#    restarts and is checked again, `update.rolled_back` is audited, exit 1.
#    A box that is not running yet (the first install) only loads the payloads; install.sh audits it after start.
#    --target demo: the one-container demo VM (docs/RUNBOOK.md §11), checked by running e2e_simple in the new container.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUNDLE=${1:?usage: tools/apply_update.sh BUNDLE.tar [--dry-run] [--target compose|demo] [--no-backup]}
shift
DRY=""; TARGET=${TB_UPDATE_TARGET:-compose}; NOBACKUP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=--dry-run ;;
    --target) TARGET=$2; shift ;;
    --no-backup) NOBACKUP=--no-backup ;;
    *) echo "apply_update: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
PUBKEY=${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}
IMAGE=${TB_PY_IMAGE:-trialbox-py:1.0.0}

[ -f "$BUNDLE" ] || { echo "no such bundle: $BUNDLE" >&2; exit 2; }
[ -f "$PUBKEY" ] || { echo "vendor public key not installed: $PUBKEY" >&2; exit 2; }
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/tb-update.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT INT TERM
BUNDLE_ABS=$(cd "$(dirname "$BUNDLE")" && pwd)/$(basename "$BUNDLE")
PUB_ABS=$(cd "$(dirname "$PUBKEY")" && pwd)/$(basename "$PUBKEY")

if [ -z "${TB_VERIFY_IN_DOCKER:-}" ] && PYTHONPATH="$ROOT/libs" python3 -c "import cryptography, tb_contracts" 2>/dev/null; then
  SUMMARY=$(PYTHONPATH="$ROOT/libs" python3 "$ROOT/tools/verify_update.py" "$BUNDLE_ABS" --pubkey "$PUB_ABS" --stage "$STAGE") \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }
else
  SUMMARY=$(docker run --rm --network none --user "$(id -u):$(id -g)" \
      -v "$BUNDLE_ABS:/in/bundle.tar:ro" -v "$PUB_ABS:/in/vendor.pub:ro" -v "$STAGE:/stage" \
      "$IMAGE" python /app/tools/verify_update.py /in/bundle.tar --pubkey /in/vendor.pub --stage /stage) \
    || { echo "update REJECTED: $BUNDLE" >&2; exit 1; }
fi
echo "verified: $SUMMARY"

if [ "$DRY" = "--dry-run" ]; then
  echo "dry run: staged in $STAGE (removed on exit); nothing applied"
  find "$STAGE" -type f ! -name manifest.json | sed "s#^$STAGE/#  would apply #"
  exit 0
fi

printf '%s' "$SUMMARY" > "$STAGE.summary.json"
trap 'rm -rf "$STAGE" "$STAGE.summary.json"' EXIT INT TERM
cd "$ROOT"
python3 -m tools.trialbox update --stage "$STAGE" --summary "$STAGE.summary.json" --target "$TARGET" \
  --deploy "$ROOT/deploy" $NOBACKUP
