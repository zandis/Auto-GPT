#!/bin/sh
# Apply a signed offline update bundle (SPEC §10.1 "Updates"; DECISIONS D-77). No auto-update: an operator runs this.
#
#   tools/apply_update.sh BUNDLE.tar [--dry-run]
#
# 1. verify: Ed25519 signature of manifest.json with the box's vendor key (TB_VENDOR_PUBKEY, default
#    deploy/keys/vendor_ed25519.pub), manifest schema, every payload's size + sha256, no extra/unsafe members —
#    in a network-less trialbox-py container (host python3 + cryptography is used when available);
#    a tampered or unsigned bundle is REJECTED (exit 1) and nothing is changed;
# 2. stage the verified payloads (re-hashed while copying);
# 3. apply by kind: image -> docker load; model -> TB_MODELS_DIR (default deploy/models); ruleset -> criteria-compiler
#    import (approved + equivalence gate, tagged in the ruleset repository); other -> deploy/updates/<bundle id>/;
# 4. append an `update.applied` audit event (bundle id, manifest sha256, files).
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUNDLE=${1:?usage: tools/apply_update.sh BUNDLE.tar [--dry-run]}
DRY=${2:-}
PUBKEY=${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}
IMAGE=${TB_PY_IMAGE:-trialbox-py:1.0.0}
COMPOSE=${TB_COMPOSE:-docker compose --project-directory $ROOT/deploy -f $ROOT/deploy/docker-compose.yml}
MODELS=${TB_MODELS_DIR:-$ROOT/deploy/models}

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
BUNDLE_ID=$(printf '%s' "$SUMMARY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bundle_id"])')

if [ "$DRY" = "--dry-run" ]; then
  echo "dry run: staged in $STAGE (removed on exit); nothing applied"
  find "$STAGE" -type f ! -name manifest.json | sed "s#^$STAGE/#  would apply #"
  exit 0
fi

if [ -d "$STAGE/image" ]; then
  find "$STAGE/image" -type f | while read -r f; do echo "docker load: ${f#"$STAGE"/image/}"; docker load -i "$f"; done
fi
if [ -d "$STAGE/model" ]; then
  mkdir -p "$MODELS"
  (cd "$STAGE/model" && find . -type f) | while read -r f; do
    mkdir -p "$MODELS/$(dirname "$f")"; cp "$STAGE/model/$f" "$MODELS/$f"; echo "model: ${f#./}"
  done
fi
if [ -d "$STAGE/ruleset" ]; then
  find "$STAGE/ruleset" -type f -name '*.zip' | while read -r f; do
    $COMPOSE cp "$f" criteria-compiler:/tmp/ruleset-update.zip
    $COMPOSE exec -T criteria-compiler python -m criteria_compiler.import_ruleset /tmp/ruleset-update.zip --by "update:$BUNDLE_ID"
  done
fi
if [ -d "$STAGE/other" ]; then
  mkdir -p "$ROOT/deploy/updates/$BUNDLE_ID"; cp -R "$STAGE/other/." "$ROOT/deploy/updates/$BUNDLE_ID/"
fi
printf '%s' "$SUMMARY" | $COMPOSE exec -T orchestrator python -c '
import json, sys
from tb_common.audit import AuditLog
s = json.load(sys.stdin)
AuditLog("/data/audit").append("update.applied", actor="apply_update.sh", input_sha=s["manifest_sha256"],
    detail={"bundle_id": s["bundle_id"], "signer": s["signer"], "files": s["files"]})
' && echo "update $BUNDLE_ID applied and audited"
