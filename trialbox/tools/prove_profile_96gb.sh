#!/usr/bin/env bash
# M9: the 96 GB profile proven under its limits on a larger card (written for the walk on the bench host; not run here).
#
#   tools/prove_profile_96gb.sh [--expect-used MIB] --gpu N --deploy DIR --out DIR \
#       --night CMD --screen CMD --backup CMD --restore CMD
#
# The four commands are the steps of the bench proof (a night on the 50,000 feed, screen-now, backup, restore): each
# is run through `tools/ballast48.py during`, which times it and reads the card's peak. Nothing here invents them.
# It refuses first (exit 2, before any change) when the card N has a compute process on it (never take a card another
# stack uses), when no nvidia runtime is registered (rows say model_serving_from_bundle=NOT PROVEN), or when
# the box's TB_ENV is PRODUCTION (tools.ballast refuses it). A card larger than the class is held down to the
# class's 97,887 MiB by tools.ballast (the same ballast as the 32 GB and 48 GB runs); the two utilisations are scaled
# to the same MiB. Host memory is capped per service by the overlay's mem_limit (docker-compose.rtxpro6000.yml).
# Under WSL2 (a Windows host: tools/prove_profile_96gb.ps1 starts this file there) nvidia-smi lists no compute
# processes, so "in use" is read from memory.used against --expect-used (default 1024 MiB: the driver's own; give
# the desktop's share on a Windows PC), and other_cards_touched can only say the one visible card was used.
# Rows go to OUT/rows.tsv: key, value. Synthetic data only.
set -euo pipefail
GPU=0; EXPECT_USED=1024; DEPLOY=""; OUT=""; NIGHT=""; SCREEN=""; BACKUP=""; RESTORE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gpu) GPU="$2"; shift 2 ;; --expect-used) EXPECT_USED="$2"; shift 2 ;; --deploy) DEPLOY="$2"; shift 2 ;; --out) OUT="$2"; shift 2 ;;
    --night) NIGHT="$2"; shift 2 ;; --screen) SCREEN="$2"; shift 2 ;;
    --backup) BACKUP="$2"; shift 2 ;; --restore) RESTORE="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ -n "$DEPLOY" ] && [ -n "$OUT" ] && [ -n "$NIGHT" ] && [ -n "$SCREEN" ] && [ -n "$BACKUP" ] && [ -n "$RESTORE" ] \
  || { echo "usage: $0 --gpu N --deploy DIR --out DIR --night CMD --screen CMD --backup CMD --restore CMD" >&2; exit 2; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
TARGET_MIB=97887   # deploy/measured/profile_record.rtxpro6000.json hardware_seen.memory_total_mib
CAP_BYTES=$((48 * 1024 * 1024 * 1024))   # TB_MEM_LLM and TB_MEM_VERIFIER of the record
mkdir -p "$OUT"; ROWS="$OUT/rows.tsv"; : > "$ROWS"
row() { printf '%s\t%s\n' "$1" "$2" | tee -a "$ROWS"; }
SMI="$(command -v nvidia-smi || echo /usr/lib/wsl/lib/nvidia-smi)"
smi() { "$SMI" -i "$GPU" "$@"; }
WSL2=0; grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null && WSL2=1
others() { "$SMI" --query-compute-apps=gpu_uuid,pid --format=csv,noheader | awk -F', ' -v u="$UUID" '$1 != u' | sort; }

UUID="$(smi --query-gpu=uuid --format=csv,noheader)"
TOTAL="$(smi --query-gpu=memory.total --format=csv,noheader,nounits)"
USED="$(smi --query-gpu=memory.used --format=csv,noheader,nounits)"
{ [ -z "$(smi --query-compute-apps=pid --format=csv,noheader)" ] && [ "$USED" -le "$EXPECT_USED" ]; } \
  || { echo "refused: card $GPU is in use by another process; it is never taken" >&2; exit 2; }
docker info --format '{{json .Runtimes}}' | grep -q nvidia \
  || { row model_serving_from_bundle NOT-PROVEN; echo "refused: no nvidia runtime in this engine" >&2; exit 2; }
OTHERS_BEFORE="$(others)"
CARD="$(smi --query-gpu=name --format=csv,noheader)"
row profile_detected "$(python3 -m tools.trialbox.profile_m9 detect x86_64 'NVIDIA RTX PRO 6000 Blackwell Server Edition' | awk '{print $2}') (from the recorded card description; this card is: $CARD)"

BALLAST=0
cleanup() {
  set +e
  [ -z "${COMPOSE_UP:-}" ] || "${COMPOSE[@]}" down
  [ "$BALLAST" = 0 ] || python3 -m tools.ballast release --ballast-container tb-ballast-m9
  [ -z "${SAMPLER:-}" ] || kill "$SAMPLER" 2>/dev/null
}
trap cleanup EXIT
if [ "$TOTAL" -gt $((TARGET_MIB + 512)) ]; then   # a real 96 GB card needs no ballast
  python3 -m tools.ballast hold --gpu "$GPU" --gpu-uuid "$UUID" --target-mib "$TARGET_MIB" --expect-used "$EXPECT_USED" --ballast-container tb-ballast-m9 \
    > "$OUT/ballast.log" 2>&1 &
  BALLAST=1
  for _ in $(seq 120); do grep -q ready "$OUT/ballast.log" && break; sleep 5; done
  grep -q ready "$OUT/ballast.log" || { echo "the ballast did not become ready: $OUT/ballast.log" >&2; exit 1; }
fi
read -r JU VU < <(python3 -c "
from tools import ballast
print(ballast.util_on($TOTAL, 0.40, $TARGET_MIB), ballast.util_on($TOTAL, 0.20, $TARGET_MIB))")
printf 'JUDGE_GPU_MEM_UTIL=%s\nVERIFIER_GPU_MEM_UTIL=%s\n' "$JU" "$VU" > "$OUT/run.env"
python3 -c "
from tools import ballast48
print(ballast48.pin_text('$UUID'), end='')" > "$OUT/gpu-pin.yml"
COMPOSE=(docker compose --project-directory "$DEPLOY" --env-file "$DEPLOY/.env" --env-file "$OUT/run.env"
  -f "$DEPLOY/docker-compose.yml" -f "$DEPLOY/docker-compose.secrets.yml" -f "$DEPLOY/docker-compose.rtxpro6000.yml"
  -f "$OUT/gpu-pin.yml" --profile gpu)
"${COMPOSE[@]}" up -d --wait
COMPOSE_UP=1

( while :; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' >> "$OUT/mem.samples"; sleep 5; done ) &
SAMPLER=$!
step() {   # NAME CMD: timed, card peak read, to OUT/step-NAME.json
  python3 tools/ballast48.py --target-mib "$TARGET_MIB" during --gpu-index "$GPU" --gpu-uuid "$UUID" \
    --out "$OUT/step-$1.json" -- bash -c "$2" || { row "step_$1" "FAIL (see $OUT/step-$1.json)"; FAILED=1; }
}
FAILED=0
step night "$NIGHT"; step screen "$SCREEN"; step backup "$BACKUP"; step restore "$RESTORE"
kill "$SAMPLER"; SAMPLER=""

python3 - "$OUT" "$CAP_BYTES" "$TARGET_MIB" "$FAILED" >> "$ROWS" <<'PY'
import json, re, sys
out, cap, target, failed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1"
unit = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30}
peak = {}
for ln in open(f"{out}/mem.samples"):
    m = re.match(r"(\S+) ([\d.]+)(B|KiB|MiB|GiB) /", ln)
    if m:
        peak[m[1]] = max(peak.get(m[1], 0), float(m[2]) * unit[m[3]])
steps = {s: json.load(open(f"{out}/step-{s}.json")) for s in ("night", "screen", "backup", "restore")}
card_peak = max(s["peak_used_mib_as_48gb"] for s in steps.values())  # tools/ballast48's key: peak used as the target card
print(f"night_50k_minutes\t{steps['night']['wall_seconds'] / 60:.1f}")
print(f"peak_memory_gb\t{max(peak.values()) / 2**30:.1f} (largest service; cap 48 for the two model servers)")
print(f"peak_card_mib\t{card_peak} (the class: {target})")
print(f"steps_exit_codes\t{[s['exit_code'] for s in steps.values()]}")
print(f"card_changed\t{any(s['card_changed'] for s in steps.values())}")
print(f"steps_ok\t{not failed and all(s['exit_code'] == 0 for s in steps.values())}")
print(f"card_within_class\t{card_peak <= target}")
PY
# limits_enforced: both model servers carry the 48 GiB host cap, and each was asked for the pinned card only
ENF=PASS
for s in llm-service llm-verifier; do
  id="$("${COMPOSE[@]}" ps -q "$s")"
  [ "$(docker inspect -f '{{.HostConfig.Memory}}' "$id")" = "$CAP_BYTES" ] || ENF=FAIL
  docker inspect -f '{{json .HostConfig.DeviceRequests}}' "$id" | grep -q "$UUID" || ENF=FAIL
done
row limits_enforced "$ENF"
OOM=0
for id in $("${COMPOSE[@]}" ps -aq); do
  [ "$(docker inspect -f '{{.State.OOMKilled}}' "$id")" != true ] || OOM=$((OOM + 1))
done
row oom_kills "$OOM"
row other_cards_touched "$(comm -13 <(printf '%s\n' "$OTHERS_BEFORE") <(others) | wc -l)"
[ "$WSL2" = 0 ] || row host "WSL2 (compute processes and other cards are not listed by this driver: other_cards_touched above is not a proof)"
row real_machine OWNER
[ "$ENF" = PASS ] && [ "$OOM" = 0 ] && [ "$FAILED" = 0 ]
