#!/usr/bin/env bash
# The bench's GPU box rehearsal (card H-105b; docs/runbook/13-bench-ci-runner.md), run by the workflow's
# rehearse-gpu-box job on a GPU slot, for a train and the owner's run by hand only. Each step says PASS, FAIL or
# NOT RUN with its reason; the job fails on a FAIL, and a NOT RUN is never counted as a pass.
#   facts    the host's TPM (none in a container: the box takes the passphrase path, and the report says so) and the
#            GPU record of the CI cards the job was given (model, memory, driver, count; no serial, no UUID)
#   weights  the host's weights folder is mounted, readable and read-only (the ruling on H105-03: no download)
#   engine   the job's own nested rootless engine answers (the box's engine; never the bench host's)
#   install  the box install under a real init, the first-run step and the service unit's start: NOT RUN until the
#            integrator rules how a rehearsal box takes the first-run step (deploy/box-install.sh refuses
#            --rehearsal with --firstrun, H-94 (3))
#   serving  the real model servers on the CI cards from the weights folder: NOT RUN until a step serves them (H105-03)
#   gpu_box.sh OUT_DIR [JOB_FILE] [WEIGHTS_DIR] [MOUNTS_FILE]
set -uo pipefail
OUT="${1:?usage: gpu_box.sh OUT_DIR [JOB_FILE]}"
JOB_FILE="${2:-/scratch/.tb-bench/job.json}"
WEIGHTS="${3:-/weights}"
MOUNTS="${4:-/proc/self/mounts}"
mkdir -p "$OUT"
NAMES=()
STATES=()
NOTES=()
record() { NAMES+=("$1"); STATES+=("$2"); NOTES+=("$3"); echo "$2 $1: $3"; }

# facts: the TPM
if [ -e /dev/tpmrm0 ] || [ -e /dev/tpm0 ]; then
  record tpm PASS "a TPM is present: the box may seal to it"
else
  record tpm PASS "no TPM: the passphrase path (the box seals its keys under the passphrase KEK)"
fi

# facts: the GPU record, with the query tool the launcher wrote into the job's card file (never one found on PATH)
tool="$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1])).get("tool", ""))' "$JOB_FILE" 2>/dev/null)"
if [ -z "$tool" ] || [ ! -x "$tool" ]; then
  record gpu FAIL "no card query tool in the job's card file: not a GPU slot, or the file is missing"
else
  if "$tool" --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits > "$OUT/gpu.csv" 2>"$OUT/gpu.err"; then
    python3 -I - "$OUT/gpu.csv" "$OUT/gpu-record.json" <<'PY'
import json, sys
rows = [[c.strip() for c in line.split(",")] for line in open(sys.argv[1]) if line.strip()]
cards = [{"model": r[0], "memory_mib": int(float(r[1])), "driver": r[2]} for r in rows if len(r) == 3]
json.dump({"count": len(cards), "cards": cards}, open(sys.argv[2], "w"), indent=1)
PY
    record gpu PASS "the GPU record: $(python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1])); print(d["count"], "card(s),", ", ".join(sorted({c["model"] for c in d["cards"]})))' "$OUT/gpu-record.json")"
  else
    record gpu FAIL "the card query tool failed: $(tail -c 300 "$OUT/gpu.err")"
  fi
fi

# weights: the host's folder, read-only (a job that can write it is refused: the version check rests on its hashes)
# (by the mount's own options: a write test proves nothing for a user that may write anyway)
opts="$(awk -v m="$WEIGHTS" '$2 == m {print $4}' "$MOUNTS" 2>/dev/null | tail -n 1)"
if [ ! -d "$WEIGHTS" ] || [ ! -r "$WEIGHTS" ]; then
  record weights FAIL "no readable weights folder at $WEIGHTS"
elif [ -z "$opts" ]; then
  record weights FAIL "$WEIGHTS is not a mount of its own"
elif ! printf '%s' ",$opts," | grep -q ',ro,'; then
  record weights FAIL "the weights folder is mounted writable ($opts): it must be read-only"
else
  record weights PASS "the weights folder is mounted read-only"
fi

# engine: the job's own nested rootless engine
if command -v podman >/dev/null && podman info --format '{{.Host.Security.Rootless}}' > "$OUT/engine.txt" 2>&1 \
   && [ "$(cat "$OUT/engine.txt")" = true ]; then
  record engine PASS "the job's own engine answers, rootless"
else
  record engine FAIL "the job's own engine does not answer rootless: $(tail -c 300 "$OUT/engine.txt")"
fi

record install "NOT RUN" "the box install under a real init, the first-run step and the unit start wait for the integrator's ruling: deploy/box-install.sh refuses --rehearsal with --firstrun (H-94 (3))"
record serving "NOT RUN" "no step serves the weights folder on the CI cards yet (finding H105-03: the source is ruled, the serving step is not built)"

fails=0
{
  echo "### GPU box rehearsal on the bench"
  echo
  echo "| step | state | note |"
  echo "| --- | --- | --- |"
  for i in "${!NAMES[@]}"; do
    echo "| ${NAMES[$i]} | ${STATES[$i]} | ${NOTES[$i]} |"
    [ "${STATES[$i]}" != FAIL ] || fails=$((fails + 1))
  done
} > "$OUT/report.md"
python3 -I - "$OUT/report.json" "${NAMES[@]}" -- "${STATES[@]}" <<'PY'
import json, sys
args = sys.argv[2:]
cut = args.index("--")
names, states = args[:cut], args[cut + 1:]
json.dump({"steps": dict(zip(names, states))}, open(sys.argv[1], "w"), indent=1)
PY
echo "gpu box: $fails failure(s); not run: install, serving"
[ "$fails" = 0 ]
