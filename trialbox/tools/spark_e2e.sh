#!/usr/bin/env bash
# TrialBox full-stack end to end on one box (docs/RUNBOOK.md "DGX Spark end to end"). `make spark-e2e` calls it.
#
#   tools/spark_e2e.sh                     # NVIDIA GB10 (DGX Spark): two vLLM servers with the pinned local models
#   TB_LLM_MODE=stub tools/spark_e2e.sh    # any x86_64/aarch64 Docker host without a GPU: deterministic stub
#
# Steps: host check -> images -> pin the models (site override) -> compose up (gpu|stub + test profiles; GB10 override
# in gpu mode) -> wait healthy -> gateway probe -> trialbox doctor -> ingest synthetic site A -> FEAS email through
# GreenMail, reply in MailHog -> cascade e2e through the gateway -> public eval suites through the gateway -> workflow
# store (outbox, recall ledger) on the compose Postgres -> one PASS/FAIL report with paths. Exit 0 only on PASS.
#
# The default is the recommended Spark pair: judge gpt-oss-120b (j-workhorse, llm-service, endpoint `serving`) and
# verifier Gemma 4 26B-A4B-it (v-verifier, llm-verifier, endpoint `verifier`); the cascade then runs the two-model
# AgreementJudge (a criterion blocks only when both agree). TB_SPARK_VERIFIER=0 runs the judge alone (for example the
# Qwen alternative: JUDGE_MODEL_DIR=JUDGE_MODEL=qwen3.5-35b-a3b-q4 TB_PIN_BUILD=qwen3.5-35b-a3b-candidate).
#
# In stub mode the "pinned builds" are synthetic placeholder directories pinned into a throwaway override under the
# run directory, answered by llm-stub (which stands in for llm-service and llm-verifier): it proves the pin ->
# registry -> gateway path, not a model. Only synthetic and open data are used in both modes.
#
# Knobs (environment): TB_SPARK_OUT (run directory), TB_SPARK_SKIP_BUILD=1 (use existing or registry images: set
# TB_IMAGE / TB_JVM_IMAGE), TB_SPARK_STRICT_HOST=1 (every host-check FAIL is fatal), TB_SPARK_UP_TIMEOUT (s, 1800),
# TB_SPARK_DOWN=1 (stop the stack at the end), TB_SPARK_REPRO (1 in stub mode, 0 in gpu mode), TB_EVAL_LIMIT (judge
# pairs through the model, gpu default 300, 0 = all 1015), TB_MODELS_DIR (deploy/models), JUDGE_MODEL_DIR and
# JUDGE_MODEL (gpt-oss-120b), TB_PIN_BUILD (gpt-oss-120b-spark), VERIFIER_MODEL_DIR and VERIFIER_MODEL
# (gemma-4-26b-a4b-it), TB_PIN_VERIFIER_BUILD (gemma-4-26b-a4b-it-spark), TB_SPARK_VERIFIER (1), TB_SPARK_TRIAL (GZQO),
# PY (.venv/bin/python).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 2
PY="${PY:-$ROOT/.venv/bin/python}"
MODE="${TB_LLM_MODE:-vllm}"
[ "$MODE" = "stub" ] || MODE="gpu"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${TB_SPARK_OUT:-$ROOT/build/spark-e2e/$STAMP-$MODE}"
LOGS="$OUT/logs"
mkdir -p "$LOGS"
OUT="$(cd "$OUT" && pwd)"
LOGS="$OUT/logs"
export PYTHONPATH="$ROOT/libs:$ROOT/services:$ROOT"

envfile_get() {  # value of KEY in deploy/.env (empty when absent)
  [ -f "$ROOT/deploy/.env" ] && sed -n "s/^$1=//p" "$ROOT/deploy/.env" | tail -1 | tr -d "\"'" || true
}
GW_PORT="${TB_HOST_GATEWAY_PORT:-$(envfile_get TB_HOST_GATEWAY_PORT)}"; GW_PORT="${GW_PORT:-8020}"
WF_PORT="${TB_HOST_WORKFLOW_DB_PORT:-$(envfile_get TB_HOST_WORKFLOW_DB_PORT)}"; WF_PORT="${WF_PORT:-5433}"
GATEWAY_URL="http://127.0.0.1:$GW_PORT/v1"
TRIAL="${TB_SPARK_TRIAL:-GZQO}"
MODELS_DIR="${TB_MODELS_DIR:-$ROOT/deploy/models}"
# exported: deploy/docker-compose.gb10.yml reads the same names
export JUDGE_MODEL_DIR="${JUDGE_MODEL_DIR:-gpt-oss-120b}" JUDGE_MODEL="${JUDGE_MODEL:-gpt-oss-120b}"
export VERIFIER_MODEL_DIR="${VERIFIER_MODEL_DIR:-gemma-4-26b-a4b-it}" VERIFIER_MODEL="${VERIFIER_MODEL:-gemma-4-26b-a4b-it}"
BUILD="${TB_PIN_BUILD:-gpt-oss-120b-spark}"
VBUILD="${TB_PIN_VERIFIER_BUILD:-gemma-4-26b-a4b-it-spark}"
VERIFIER="${TB_SPARK_VERIFIER:-1}"
UP_ARGS=()

COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml)
if [ "$MODE" = "gpu" ]; then
  COMPOSE+=(-f deploy/docker-compose.gb10.yml -f deploy/docker-compose.test.yml --profile gpu --profile test)
  [ "$VERIFIER" = 1 ] || UP_ARGS=(--scale llm-verifier=0)
  REPRO="${TB_SPARK_REPRO:-0}"     # vLLM does not promise batch-invariant output; opt in with TB_SPARK_REPRO=1
  export TB_EVAL_LIMIT="${TB_EVAL_LIMIT:-300}"
  SITE_DIR="$ROOT/deploy/site"
else
  COMPOSE+=(-f deploy/docker-compose.test.yml --profile stub --profile test)
  REPRO="${TB_SPARK_REPRO:-1}"
  SITE_DIR="$OUT/site"
fi
export TB_SETTINGS_FILE="../.cache/test-settings.yaml" TB_SITE_DIR="$SITE_DIR" TB_ENV=TEST TB_DATA_CLASS=D0
export TB_GATEWAY_MODEL=j-workhorse   # every model call asks for the on-box build; refused unless pinned
OVERRIDE="$SITE_DIR/registry.site.yaml"

# ------------------------------------------------------------------------------------------------ step bookkeeping
NAMES=(); STATES=(); NOTES=(); N=0; BLOCKED=""
record() { NAMES+=("$1"); STATES+=("$2"); NOTES+=("$3"); }
# step <name> <fatal:0|1> <command...>: runs with output in logs/NN-name.log; a fatal failure skips the rest
step() {
  local name="$1" fatal="$2"; shift 2
  N=$((N + 1)); local log; log="$LOGS/$(printf %02d "$N")-$name.log"
  if [ -n "$BLOCKED" ]; then record "$name" SKIP "not run: $BLOCKED failed"; return 1; fi
  echo "==> [$N] $name (log: $log)"
  local t0=$SECONDS
  if "$@" >"$log" 2>&1; then
    record "$name" PASS "$((SECONDS - t0)) s; $log"; return 0
  fi
  record "$name" FAIL "$((SECONDS - t0)) s; see $log"
  tail -n 15 "$log" | sed 's/^/    /'
  [ "$fatal" = 1 ] && BLOCKED="$name"
  return 1
}

# ------------------------------------------------------------------------------------------------ steps
host_check() {
  local args=(); [ "$MODE" = "gpu" ] && args=(--gb10)
  local out rc
  out="$(sh deploy/check_host.sh "${args[@]}" --env deploy/.env 2>&1)"; rc=$?
  echo "$out"
  [ "${TB_SPARK_STRICT_HOST:-0}" = 1 ] && return $rc
  if [ "$MODE" = "gpu" ]; then  # the GB10 runtime lines must pass; appliance hardening lines are reported only
    for want in "aarch64 host" "NVIDIA driver 580.142" "nvidia container runtime"; do
      echo "$out" | grep -q "^PASS  $want" || { echo "required for the e2e: $want"; return 1; }
    done
    # MailHog (test profile) is published for amd64 only: the Spark runs it under binfmt emulation
    [ -e /proc/sys/fs/binfmt_misc/qemu-x86_64 ] \
      || { echo "required: amd64 emulation for MailHog (docker run --privileged --rm tonistiigi/binfmt --install amd64)"; return 1; }
  fi
  echo "informational (TB_SPARK_STRICT_HOST=1 makes them fatal): $(echo "$out" | grep -c '^FAIL') appliance check(s) failed"
  return 0
}

prepare() {
  make deploy/.env .cache/test-secrets/site_hmac.key .cache/test-settings.yaml PY="$PY"
  docker info >/dev/null && "${COMPOSE[@]}" config -q
}

build_images() {
  if [ "${TB_SPARK_SKIP_BUILD:-0}" = 1 ]; then
    echo "TB_SPARK_SKIP_BUILD=1: using ${TB_IMAGE:-trialbox-py:1.0.0} and ${TB_JVM_IMAGE:-trialbox-jvm:1.0.0}"
    docker image inspect "${TB_IMAGE:-trialbox-py:1.0.0}" "${TB_JVM_IMAGE:-trialbox-jvm:1.0.0}" >/dev/null 2>&1 \
      || "${COMPOSE[@]}" pull --ignore-buildable gateway orchestrator
    return
  fi
  make images PY="$PY"   # native build: arm64 on the Spark, amd64 on x86
  docker image inspect trialbox-py:1.0.0 --format 'trialbox-py: {{.Architecture}}'
  docker image inspect trialbox-jvm:1.0.0 --format 'trialbox-jvm: {{.Architecture}}'
}

# pin_one <build> <model dir name> <served name> <endpoint>: pins and verifies; the last output line is the sha256
pin_one() {
  local build="$1" name="$2" served="$3" endpoint="$4" dir
  if [ "$MODE" = "gpu" ]; then
    dir="$MODELS_DIR/$name"
    [ -d "$dir" ] || { echo "model weights not found at $dir (place them under deploy/models, RUNBOOK)"; return 1; }
  else
    dir="$OUT/placeholder-$name"   # synthetic bytes, stands in for weights (stub mode only)
    mkdir -p "$dir"
    printf 'trialbox stub-mode placeholder for %s, not a model\n' "$name" >"$dir/placeholder.safetensors"
    printf '{"architectures": ["TrialBoxPlaceholder"]}\n' >"$dir/config.json"
  fi
  "$PY" -m tools.pin_model --build "$build" --model-dir "$dir" --served-name "$served" --endpoint "$endpoint" \
    --out "$OVERRIDE" || return 1
  "$PY" -m tools.pin_model --build "$build" --model-dir "$dir" --out "$OVERRIDE" --verify || return 1
  "$PY" -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["builds"][sys.argv[2]]["sha256"])' \
    "$OVERRIDE" "$build"
}

pin() {
  local out
  out="$(pin_one "$BUILD" "$JUDGE_MODEL_DIR" "$JUDGE_MODEL" serving)" || { echo "$out"; return 1; }
  echo "$out"
  PIN_SHA="$(echo "$out" | tail -1)"
  export TB_GATEWAY_EXPECT_SHA="$PIN_SHA"
  echo "pinned $BUILD sha256 $PIN_SHA in $OVERRIDE"
  [ "$VERIFIER" = 1 ] || return 0
  out="$(pin_one "$VBUILD" "$VERIFIER_MODEL_DIR" "$VERIFIER_MODEL" verifier)" || { echo "$out"; return 1; }
  echo "$out"
  VPIN_SHA="$(echo "$out" | tail -1)"
  # the cascade puts every decided answer to the verifier build through the same gateway (AgreementJudge)
  export TB_GATEWAY_VERIFIER_URL="$GATEWAY_URL" TB_GATEWAY_VERIFIER_MODEL=v-verifier
  export TB_GATEWAY_VERIFIER_EXPECT_SHA="$VPIN_SHA"
  echo "pinned $VBUILD sha256 $VPIN_SHA in $OVERRIDE"
}

compose_up() {
  "${COMPOSE[@]}" rm -sf gateway   # the gateway reads the site pins at start: always start it fresh
  "${COMPOSE[@]}" up -d --wait --wait-timeout "${TB_SPARK_UP_TIMEOUT:-1800}" "${UP_ARGS[@]}"; local rc=$?
  "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
  return $rc
}

gateway_probe() {  # the registry the gateway loaded carries the site pins, and each call is answered by its build
  probe_build "$BUILD" "$PIN_SHA" j-workhorse || return 1
  [ "$VERIFIER" = 1 ] || return 0
  probe_build "$VBUILD" "$VPIN_SHA" v-verifier
}

probe_build() {  # probe_build <build> <sha256> <alias>
  "$PY" - "$GATEWAY_URL" "$1" "$2" "$3" <<'EOF'
import sys

import httpx
from tb_common.llm import load_prompt, render
from tb_contracts import inline_schema
from tb_llm import CallLabels, GatewayClient, json_schema_format

url, build, sha, alias = sys.argv[1:5]
base = url.rsplit("/v1", 1)[0]
ready = httpx.get(f"{base}/readyz", timeout=30).json()
print("readyz:", ready)
assert "+site." in ready["registry_version"], "gateway did not load the site override"
rows = {b["build_id"]: b for b in httpx.get(f"{base}/registry/v1/builds", timeout=30).json()["builds"]}
assert rows[build]["sha256"] == sha, f"gateway registry has {rows[build]['sha256']} for {build}"
p = load_prompt("judge")
body_vars = {"criterion_text": "Age >= 18 years", "note_question": "Is the patient an adult?",
             "index_date": "2026-10-05", "excerpts": [{"date": "2026-10-01", "note_type": "progress",
                                                       "text": "Synthetic note: 54-year-old outpatient."}]}
labels = CallLabels("D0", "feasibility", "SPARK-E2E", "s3_note_judgement", "judge", f"judge@{p.meta.version}")
res = GatewayClient(url, "orchestrator", model=alias).chat(
    render(p, body_vars), labels, response_format=json_schema_format("judge", inline_schema(p.meta.output_schema)),
    max_tokens=p.meta.max_tokens,
)
print("probe:", {"alias": res.alias, "build_sha": res.build_sha, "model": res.model, "data": res.data})
assert res.build_sha == sha and isinstance(res.data, dict), "probe not answered by the pinned build"
EOF
}

doctor() {
  TB_REGISTRY_OVERRIDE="$OVERRIDE" "$PY" -m tools.trialbox doctor --env-file deploy/.env --settings .cache/test-settings.yaml
}

ingest() { "$PY" -m tests.stack; }

feas_email() {
  TB_INTEGRATION=1 "$PY" -m pytest -q -p no:cacheprovider -m e2e --junitxml="$OUT/feas_email.xml" \
    "tests/e2e/test_mail_compose.py::test_feas_email_to_pdf"
}

cascade() {
  local args=(); [ "$REPRO" = 1 ] || args=(--no-repro)
  TB_GATEWAY_URL="$GATEWAY_URL" "$PY" -m tools.cascade_e2e --source tests/fixtures/synthetic_patients/site-a \
    --trial "$TRIAL" --out "$OUT/cascade" "${args[@]}"
}

eval_public() {
  TB_GATEWAY_URL="$GATEWAY_URL" make eval-public PY="$PY"
}

workflow_store() {
  local pw; pw="$(envfile_get POSTGRES_WF_PASSWORD)"; pw="${pw:-$(envfile_get POSTGRES_PASSWORD)}"
  "${COMPOSE[@]}" exec -T workflow-db sh -c \
    'psql -U trialbox -d trialbox_wf -tAc "SELECT 1 FROM pg_database WHERE datname='"'"'trialbox_wf_e2e'"'"'" | grep -q 1 \
     || createdb -U trialbox trialbox_wf_e2e' || return 1
  TB_PG_DSN="postgresql://trialbox:$pw@127.0.0.1:$WF_PORT/trialbox_wf_e2e" "$PY" -m pytest -q -p no:cacheprovider -rs \
    tests/unit/test_outbox_killloop.py::test_postgres_backend_same_semantics \
    tests/unit/test_recall_ledger.py::test_postgres_ledger_round_trip
}

# ------------------------------------------------------------------------------------------------ run
echo "TrialBox spark e2e: mode $MODE, run directory $OUT"
PIN_SHA=""; VPIN_SHA=""
step host-check 0 host_check
step prepare 1 prepare
step images 1 build_images
step pin-model 1 pin
step compose-up 1 compose_up
step gateway-probe 1 gateway_probe
step doctor 0 doctor
step ingest-site-a 1 ingest
step feas-email 0 feas_email
step cascade-e2e 0 cascade
step eval-public 0 eval_public
step workflow-store 0 workflow_store

"${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}' >"$LOGS/compose-ps.txt" 2>&1
"${COMPOSE[@]}" logs --no-color --timestamps >"$LOGS/compose.log" 2>&1
[ "${TB_SPARK_DOWN:-0}" = 1 ] && "${COMPOSE[@]}" down >>"$LOGS/compose.log" 2>&1

# host-check is informational unless strict (its failures are listed, they do not fail the run)
VERDICT=PASS
for i in "${!NAMES[@]}"; do
  if [ "${STATES[$i]}" != PASS ] && { [ "${NAMES[$i]}" != host-check ] || [ "${TB_SPARK_STRICT_HOST:-0}" = 1 ] \
      || [ "${STATES[$i]}" = SKIP ]; }; then
    VERDICT=FAIL
  fi
done
EVAL_ARCHIVE="$(grep -h '^archived:' "$LOGS"/*-eval-public.log 2>/dev/null | sed 's/^archived: //' | paste -sd ' ' -)"
{
  echo "# TrialBox spark e2e: $VERDICT"
  echo
  vnote="verifier off"; [ "$VERIFIER" = 1 ] && vnote="verifier $VBUILD pinned at ${VPIN_SHA:-none}"
  echo "Mode $MODE, $(uname -m), $(date -u +%Y-%m-%dT%H:%M:%SZ). Judge $BUILD pinned at ${PIN_SHA:-none}; $vnote" \
    "($OVERRIDE)."
  echo
  echo "| # | step | result | detail |"
  echo "| --- | --- | --- | --- |"
  for i in "${!NAMES[@]}"; do echo "| $((i + 1)) | ${NAMES[$i]} | ${STATES[$i]} | ${NOTES[$i]} |"; done
  echo
  echo "Artefacts:"
  echo "- cascade summary: $OUT/cascade/e2e_summary.md"
  echo "- FEAS email test: $OUT/feas_email.xml"
  echo "- eval archives: ${EVAL_ARCHIVE:-none}"
  echo "- compose logs: $LOGS/compose.log"
} | tee "$OUT/report.md"
"$PY" - "$OUT" "$VERDICT" "$MODE" "${PIN_SHA:-}" "${NAMES[@]}" -- "${STATES[@]}" <<'EOF' || true
import json
import sys

out, verdict, mode, sha, *rest = sys.argv[1:]
cut = rest.index("--")
names, states = rest[:cut], rest[cut + 1 :]
doc = {"verdict": verdict, "mode": mode, "pinned_sha256": sha or None, "steps": dict(zip(names, states, strict=True))}
with open(f"{out}/report.json", "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=1)
EOF
echo "report: $OUT/report.md"
[ "$VERDICT" = PASS ]
