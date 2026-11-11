#!/usr/bin/env bash
# G1b on the owner's B200 (T-114, D-428; RUNBOOK §11 "G1b on the owner's B200"). Replaces the cloud form of WS-02.7:
# no gcloud, no rental, no network. The owner or the named operator (Q-12) runs it as root on the B200 itself:
#
#   sudo tools/b200_qualify.sh --bundle tb-b200.tar.gz --sha256 <hex sent separately> --operator <name> \
#       --env-file <site .env> --qualify-args <file> [--out /var/tmp/tb-g1b] [--yes]
#
# (`tools/b200_qualify.sh` is in the bundle too: copy it out, or run it from any checkout.) Steps:
#   1. the bundle's sha256, then every file against its manifest (python3 -m tools.b200_qualify verify);
#   2. `docker load` of the bundle's images; the weights are the bundle's (TB_MODELS_DIR, unless the env file sets it);
#   3. the host fingerprint before partitioning (GPU, driver, CUDA, MIG, kernel, OS, toolkit, docker, vLLM digest);
#   4. for each of the two layouts (eval/qualification/b200-layouts.json): MIG on, the card partitioned into the
#      judge's and the verifier's instances, the pair started on them (deploy/docker-compose.shared-quota.yml), the
#      serving record captured and stamped with this layout's fingerprint, `trialbox eval qualify --profile
#      shared-quota` run through the gateway, the pair stopped;
#   5. the G1b record (g1b-record.json, G1b.md) and g1b-results.tar.gz: send that file back, nothing else.
# Partitioning stops anything else on GPU 0: the script asks first (--yes skips the question). MIG stays on with the
# last layout; `nvidia-smi -i 0 -mig 0` turns it off.
#
# Tests (tests/unit/test_b200_qualify.py) run it with TB_B200_STANDIN=1 and stand-in nvidia-smi and docker on PATH
# (tests/rehearsal/b200/); a stand-in run's record is `standin`, never `passed`.
set -euo pipefail

die() { echo "b200_qualify: $*" >&2; exit 2; }
say() { echo "== $*"; }
BUNDLE="" SHA="" OPERATOR="" ENV_FILE="" QARGS="" OUT="/var/tmp/tb-g1b" YES=0
GATEWAY="${TB_GATEWAY_URL:-http://127.0.0.1:8010/v1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --bundle) BUNDLE="$2"; shift 2 ;;
    --sha256) SHA="$2"; shift 2 ;;
    --operator) OPERATOR="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --qualify-args) QARGS="$2"; shift 2 ;;
    --gateway-url) GATEWAY="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "unknown argument $1 (see --help)" ;;
  esac
done
export PYTHONDONTWRITEBYTECODE=1  # the bundle stays as its manifest says
STANDIN="${TB_B200_STANDIN:-0}"
QUALIFY="${TB_B200_QUALIFY_CMD:-}"
[ -n "$BUNDLE" ] && [ -f "$BUNDLE" ] || die "--bundle <file> is required"
[ -n "$OPERATOR" ] || die "--operator <name> is required (the owner or the named operator, Q-12)"
[ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ] || die "--env-file <the site's .env: images, model key, weights> is required"
[ -z "$QARGS" ] || [ -f "$QARGS" ] || die "--qualify-args $QARGS: no such file"
[ -z "$QUALIFY" ] || [ "$STANDIN" = 1 ] || die "TB_B200_QUALIFY_CMD is a stand-in: refused without TB_B200_STANDIN=1"
for tool in python3 tar sha256sum docker nvidia-smi; do
  command -v "$tool" >/dev/null || die "$tool is not on this host"
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "python3 3.11 or later is needed"
[ "$STANDIN" = 1 ] || [ "$(id -u)" = 0 ] || die "run as root: MIG partitioning needs it"

# 1. the bundle
if [ -z "$SHA" ] && [ -f "$BUNDLE.sha256" ]; then SHA="$(cut -d' ' -f1 "$BUNDLE.sha256")"; fi
[ -n "$SHA" ] || die "--sha256 <hex> is required (sent separately from the bundle)"
GOT="$(sha256sum "$BUNDLE" | cut -d' ' -f1)"
[ "$GOT" = "$SHA" ] || die "the bundle's sha256 is $GOT, not $SHA: do not run it"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
rm -rf "$OUT/bundle" && mkdir -p "$OUT/bundle"
tar -xzf "$BUNDLE" -C "$OUT/bundle"
echo "$SHA" > "$OUT/bundle.sha256"
CODE="$OUT/bundle/code"
cd "$CODE"
PY=(python3 -m tools.b200_qualify)
say "1. bundle"
"${PY[@]}" verify "$OUT/bundle"

# 2. images and weights
say "2. images"
while IFS= read -r img; do
  [ -n "$img" ] && docker load -i "$OUT/bundle/$img"
done < <("${PY[@]}" images "$OUT/bundle")
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export TB_MODELS_DIR="${TB_MODELS_DIR:-$OUT/bundle/weights}"

# 3. the host
say "3. host fingerprint"
mkdir -p "$OUT/host"
"${PY[@]}" fingerprint --out "$OUT/host/fingerprint.json"
grep -q '"gpu_name": ".*B200' "$OUT/host/fingerprint.json" || die "this host has no B200 (see $OUT/host/fingerprint.json)"

COMPOSE=(docker compose --project-directory "$CODE/deploy" -f "$CODE/deploy/docker-compose.yml"
  -f "$CODE/deploy/docker-compose.secrets.yml" -f "$CODE/deploy/docker-compose.shared-quota.yml"
  -f "$CODE/deploy/platform/docker-compose.platform.yml" --env-file "$ENV_FILE" --profile gpu)
EXTRA=()
if [ -n "$QARGS" ]; then
  while IFS= read -r line; do
    case "$line" in ''|'#'*) ;; *) EXTRA+=("$line") ;; esac
  done < "$QARGS"
fi

# 4. the two layouts
for LAY in $("${PY[@]}" layouts); do
  D="$OUT/$LAY"
  rm -rf "$D" && mkdir -p "$D"
  CGI="$("${PY[@]}" cgi "$LAY")"
  say "4. layout $LAY: MIG instances $CGI"
  if [ "$YES" != 1 ]; then
    read -r -p "Partition GPU 0 into $CGI? Anything else on the card stops. [y/N] " ok
    [ "$ok" = y ] || [ "$ok" = Y ] || die "not partitioned: stopped by the operator"
  fi
  nvidia-smi -i 0 -mig 1
  nvidia-smi mig -i 0 -dci >/dev/null 2>&1 || true
  nvidia-smi mig -i 0 -dgi >/dev/null 2>&1 || true
  nvidia-smi mig -i 0 -cgi "$CGI" -C
  nvidia-smi -L > "$D/nvidia-smi-L.txt"
  "${PY[@]}" env "$LAY" --list "$D/nvidia-smi-L.txt" > "$D/serve.env"
  set -a
  # shellcheck disable=SC1091
  . "$D/serve.env"
  set +a
  "${COMPOSE[@]}" up -d --wait llm-service llm-verifier gateway
  JC="$("${COMPOSE[@]}" ps -q llm-service)"
  VC="$("${COMPOSE[@]}" ps -q llm-verifier)"
  python3 tools/serving_config.py capture --container "judge=$JC" --container "verifier=$VC" \
    --models-dir "$TB_MODELS_DIR" --notes "G1b layout $LAY on the owner's B200 (T-114)" \
    --out "$D/serving_config.json" || true
  "${PY[@]}" fingerprint --out "$D/fingerprint.json"
  [ -f "$D/serving_config.json" ] && "${PY[@]}" stamp "$D/serving_config.json" "$D/fingerprint.json"
  docker logs "$JC" > "$D/judge.log" 2>&1 || true
  docker logs "$VC" > "$D/verifier.log" 2>&1 || true
  if [ -n "$QUALIFY" ]; then read -r -a QCMD <<< "$QUALIFY"; else QCMD=(python3 -m tools.trialbox eval qualify); fi
  "${QCMD[@]}" --profile shared-quota --gateway-url "$GATEWAY" --server-log "$D/judge.log" \
    --server-log "$D/verifier.log" --operator "$OPERATOR" --out "$D/qualification" ${EXTRA[@]+"${EXTRA[@]}"} || true
  newest="$(ls -t "$D"/qualification/*.json 2>/dev/null | head -1 || true)"
  [ -n "$newest" ] && cp "$newest" "$D/qualification.json"
  "${COMPOSE[@]}" down
done

# 5. the record
say "5. G1b record"
rc=0
"${PY[@]}" record "$OUT" --operator "$OPERATOR" || rc=$?
tar -czf "$OUT/g1b-results.tar.gz" -C "$OUT" --exclude=./bundle --exclude=./g1b-results.tar.gz .
echo "Send back $OUT/g1b-results.tar.gz (no weights, no images, no keys)."
echo "MIG stays on with the last layout; nvidia-smi -i 0 -mig 0 turns it off."
exit "$rc"
