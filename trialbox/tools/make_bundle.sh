#!/usr/bin/env bash
# Vendor side: build the one-file offline release bundle that deploy/install.sh (new site) and tools/apply_update.sh
# (existing site) accept. Images are exported with `docker save`; models, rulesets and the installer ride along; the
# manifest is Ed25519-signed with the vendor key (tools/sign_bundle.py, D-77). Nothing in it is site-specific.
#
#   tools/make_bundle.sh --key keys/vendor_ed25519.key --id 2026.11-1 --out dist/trialbox-2026.11-1.tar \
#       [--models deploy/models] [--rulesets dist/rulesets] [--image trialbox-py:1.0.0 --image trialbox-jvm:1.0.0 ...]
#
# Default images: trialbox-py:1.0.0, trialbox-jvm:1.0.0 and the third-party images compose pulls (so the site needs no
# registry access). Add --no-third-party on a site that mirrors them itself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY=""; ID=""; OUT=""; MODELS=""; RULESETS=""; THIRD=1
IMAGES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY="$2"; shift ;;
    --id) ID="$2"; shift ;;
    --out) OUT="$2"; shift ;;
    --models) MODELS="$2"; shift ;;
    --rulesets) RULESETS="$2"; shift ;;
    --image) IMAGES+=("$2"); shift ;;
    --no-third-party) THIRD=0 ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "make_bundle: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$KEY" ] && [ -n "$ID" ] && [ -n "$OUT" ] || { echo "make_bundle: --key, --id and --out are required" >&2; exit 2; }
[ -f "$KEY" ] || { echo "make_bundle: no such key $KEY" >&2; exit 2; }
command -v docker >/dev/null || { echo "make_bundle: docker is needed to export images" >&2; exit 2; }
PY="${PY:-$ROOT/.venv/bin/python}"; [ -x "$PY" ] || PY=python3

if [ ${#IMAGES[@]} -eq 0 ]; then
  IMAGES=("${TB_IMAGE:-trialbox-py:1.0.0}" "${TB_JVM_IMAGE:-trialbox-jvm:1.0.0}")
  if [ "$THIRD" = 1 ]; then
    # every image compose would pull (postgres, minio, hapi, greenmail, mailhog, vllm...), from the rendered config
    while IFS= read -r img; do
      case "$img" in trialbox-*) ;; *) IMAGES+=("$img") ;; esac
    done < <(docker compose --project-directory "$ROOT/deploy" -f "$ROOT/deploy/docker-compose.yml" \
               -f "$ROOT/deploy/docker-compose.test.yml" --profile stub --profile test --profile gpu config --images 2>/dev/null | sort -u)
  fi
fi

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/tb-bundle.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT INT TERM
ITEMS=()
echo "==> images"
for img in "${IMAGES[@]}"; do
  docker image inspect "$img" >/dev/null 2>&1 || { echo "    pulling $img"; docker pull -q "$img" >/dev/null; }
  f="$STAGE/$(printf '%s' "$img" | tr '/:' '__').tar"
  echo "    $img"
  docker save "$img" -o "$f"
  ITEMS+=("image:$f=$(basename "$f")")
done
if [ -n "$MODELS" ]; then
  echo "==> models from $MODELS"
  while IFS= read -r f; do
    rel="${f#"$MODELS"/}"; echo "    $rel"; ITEMS+=("model:$f=$rel")
  done < <(find "$MODELS" -type f | sort)
fi
if [ -n "$RULESETS" ]; then
  echo "==> rulesets from $RULESETS"
  while IFS= read -r f; do
    echo "    $(basename "$f")"; ITEMS+=("ruleset:$f=$(basename "$f")")
  done < <(find "$RULESETS" -type f -name '*.zip' | sort)
fi
echo "==> installer, runbook, settings example"
for f in deploy/install.sh deploy/check_host.sh deploy/settings.example.yaml .env.example docs/RUNBOOK.md; do
  ITEMS+=("other:$ROOT/$f=$(basename "$f")")
done
mkdir -p "$(dirname "$OUT")"
echo "==> signing $OUT (bundle id $ID)"
PYTHONPATH="$ROOT/libs:$ROOT" "$PY" "$ROOT/tools/sign_bundle.py" build --key "$KEY" --id "$ID" --out "$OUT" \
  --description "TrialBox release $ID: images, models, rulesets, installer" "${ITEMS[@]}"
sha256sum "$OUT" | tee "$OUT.sha256"
echo "done: hand over $OUT and $OUT.sha256 on a USB stick; the site runs: deploy/install.sh $(basename "$OUT")"
