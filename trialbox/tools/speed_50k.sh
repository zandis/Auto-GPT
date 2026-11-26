#!/usr/bin/env bash
# M8 (R1-P2, S2): the timed 50,000-patient screening with the real models: synthetic patients from the repo's
# generator (tools.synth_hospital, through tools.complete_run's hospital part), the judge and the verifier on their
# cards, model calls in flight 4, prefix cache off. NOT run by the builder: the walk runs it on the B200.
#
#   TB_SPEED_CARDS=<card list> TB_GPU_KEY_FILE=<root-only key file> \
#     tools/speed_50k.sh <out dir> <judge /v1 URL> <verifier /v1 URL> [serving record json]
#
# TB_SPEED_CARDS: the cards the two servers run on (nvidia-smi ids, e.g. 0 or 0,1): the integrator names them; the
# script refuses to start without them, and records them. The servers are already up (the walk starts them with
# TB_LLM_PREFIX_CACHING=no-enable, deploy/docker-compose.<profile>.yml); this script only reads them.
#
# Records, in <out dir>: speed_line.tsv (the bench rows of the spec, one table), speed_line.json (the stage record and
# whether it explains the wall time), chart_times.json (tools.chart_times report: per chart median and p95 per
# stage, the servers' queue / prefill / decode split, cards and CPU), run/ (tools.complete_run's own parts, report),
# env.txt (head, cards, concurrency, prefix-cache lines, `time -v` of the run). Counts and seconds only; no patient.
set -euo pipefail

OUT=${1:?out dir}; JUDGE=${2:?judge /v1 URL}; VERIFIER=${3:?verifier /v1 URL}; RECORD=${4:-}
PATIENTS=50000; CONCURRENCY=4
: "${TB_SPEED_CARDS:?TB_SPEED_CARDS: the cards to measure on (the integrator names them)}"
: "${TB_GPU_KEY_FILE:?TB_GPU_KEY_FILE: a root-only file holding the key of the two servers}"
cd "$(dirname "$0")/.."
export PYTHONPATH=libs:services:.
PY=${PY:-.venv/bin/python}
mkdir -p "$OUT"; ENVF="$OUT/env.txt"
TB_GPU_KEY=$(<"$TB_GPU_KEY_FILE"); export TB_GPU_KEY  # read here, never printed or written
# TB_SCREEN_TIMING=on makes the run publish its stage clock file (declared in config.py; off by default)
export TB_LLM_PREFIX_CACHING=no-enable TB_SCREEN_LLM_CONCURRENCY=$CONCURRENCY TB_SCREEN_TIMING=on

# 1. refuse a server that has its prefix cache on (the run measures the cold path); say what each reports
{
  echo "head=$(git rev-parse HEAD)"; echo "cards=$TB_SPEED_CARDS"; echo "patients=$PATIENTS"
  echo "concurrency=$CONCURRENCY"; echo "started=$(date -u +%FT%TZ)"
  nvidia-smi -i "$TB_SPEED_CARDS" --query-gpu=index,name,memory.total --format=csv,noheader || echo "nvidia-smi: none"
} > "$ENVF"
for pair in "judge=$JUDGE" "verifier=$VERIFIER"; do
  name=${pair%%=*}; url=${pair#*=}
  line=$(curl -fsS -H @<(printf "Authorization: Bearer %s\n" "$TB_GPU_KEY") "${url%/v1}/metrics" 2>/dev/null \
    | grep -m1 'cache_config_info' | grep -o 'enable_prefix_caching="[A-Za-z]*"' || true)
  echo "prefix_cache.$name=${line:-unreported}" >> "$ENVF"
  if [[ "$line" == *'"True"'* ]]; then echo "the $name server has its prefix cache on: restart it with TB_LLM_PREFIX_CACHING=no-enable" >&2; exit 3; fi
done

# 2. the run: generator, ingest, criteria, screening on the models, lists; one setting (4 calls in flight). The
#    `time -v` gives the largest single process's memory (not the sum of the parts)
args=(--dir "$OUT/run" --model pair --patients "$PATIENTS" --langs ja --only hospital
      --llm-concurrency "$CONCURRENCY" --judge-url "$JUDGE" --verifier-url "$VERIFIER" --run-id "speed-$(date -u +%Y%m%dT%H%M%S)")
[[ -n "$RECORD" ]] && args+=(--live-record "$RECORD")
rc=0; /usr/bin/time -v -o "$OUT/time.txt" "$PY" -m tools.complete_run "${args[@]}" > "$OUT/run.log" 2>&1 || rc=$?
echo "complete_run_exit=$rc" >> "$ENVF"; echo "finished=$(date -u +%FT%TZ)" >> "$ENVF"
PEAK_KB=$(awk -F: '/Maximum resident set size/ {gsub(/ /,"",$2); print $2}' "$OUT/time.txt")
echo "peak_rss_kb_largest_process=${PEAK_KB:-unknown}" >> "$ENVF"

# 3. the figures: the part's result, the stage clock's file, the audit of the calls
PART=$(find "$OUT/run/parts" -maxdepth 1 -name 'hospital-ja@c*.json' | head -n 1 || true)
[[ -n "$PART" ]] || { echo "no hospital part result: see $OUT/run.log (exit $rc)" >&2; exit $(( rc ? rc : 1 )); }
TIMING=$(find "$OUT/run" -name 'cascade_timing_*_v*.json' | head -n 1 || true)
read -r WALL SINCE UNTIL < <("$PY" -c 'import json,sys; w=json.load(open(sys.argv[1]))["screen"]["window"]; print(w["to"]-w["from"], w["from_at"], w["to_at"])' "$PART")
PEAK_GB=$(awk -v k="${PEAK_KB:-}" 'BEGIN { if (k == "") print ""; else printf "%.2f", k/1048576 }')
rows=("$PY" -m tools.speed_rows --patients "$PATIENTS" --wall "$WALL" --ruleset GZQO --equal-to-night unknown)  # a night on the same snapshot is not part of this run
[[ -n "$PEAK_GB" ]] && rows+=(--peak-gb "$PEAK_GB")
if [[ -n "$TIMING" ]]; then rows+=(--timing "$TIMING"); else echo "no stage clock file found: largest_stage is unknown" >> "$ENVF"; fi
"${rows[@]}" > "$OUT/rows.txt"
sed -n '1,5p' "$OUT/rows.txt" > "$OUT/speed_line.tsv"; sed -n '6p' "$OUT/rows.txt" > "$OUT/speed_line.json"
AUDIT=$(grep -rl --include='*.jsonl' '"llm.call"' "$OUT/run" 2>/dev/null | head -n 1 || true); [[ -n "$AUDIT" ]] && AUDIT=$(dirname "$AUDIT")
WATCH=$(find "$OUT/run/parts" -name gpu.csv 2>/dev/null | head -n 1 || true); [[ -n "$WATCH" ]] && WATCH=$(dirname "$WATCH")
if [[ -d "$AUDIT" && -d "$WATCH" ]]; then
  chart=("$PY" -m tools.chart_times report --audit-dir "$AUDIT" --folder "$WATCH" --since "$SINCE" --until "$UNTIL"
         --ingest-patients "$PATIENTS" --out "$OUT/chart_times.json")
  [[ -n "$TIMING" ]] && chart+=(--timing "$TIMING")
  "${chart[@]}" >> "$OUT/run.log" 2>&1 || echo "chart_times report failed: see run.log" >> "$ENVF"
else
  echo "chart_times report not made: audit folder or sampling folder not found" >> "$ENVF"
fi
cat "$OUT/speed_line.tsv"; exit "$rc"