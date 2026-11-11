#!/usr/bin/env bash
# TrialBox one-file installer for a hospital workstation or server (clinical review 2026-11, section 6; RUNBOOK §1).
#
#   sudo deploy/install.sh trialbox-<version>.tar --tier small|medium|large [--answers site.yaml] [--yes]
#   sudo deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--gpu rtxpro6000|gb10|rtx5090|rtx4090] [--yes]
#   sudo deploy/install.sh --check            # host checks only (deploy/check_host.sh)
#   deploy/install.sh --tier large --tier-check   # only: may this tier be installed on this machine?
#   ... --ctgov live|offline                       # ClinicalTrials.gov: online, or the copy in each update (D-140)
#   deploy/install.sh --ctgov-check                # only: which ClinicalTrials.gov mode would be suggested here?
#
# Tiers (D-138, tools/tiers.py): small = rtx5090, medium = gb10, large = rtxpro6000 (the boxes of D-124). A tier is
# installed only from a measured serving record of its own uncapped card (deploy/site/ or deploy/measured/
# serving_config.<gpu>.json, tools/serving_config.py measured); there is no override. --gpu with
# TB_ACCEPT_UNMEASURED_GPU=1 stays for a trial boot of an unmeasured card, and is not a tier install.
#
# What it does, in order, and stops at the first failure:
#   1. host:      Docker Engine + compose plugin present and running; GPU driver when --mode gpu (auto when nvidia-smi
#                 works); vendor public key installed (deploy/keys/vendor_ed25519.pub)
#   2. bundle:    verify the Ed25519 signature and every payload hash, then load images, models and rulesets
#                 (tools/apply_update.sh; a tampered bundle changes nothing). The bundle's host tree (compose files,
#                 host tools, configuration; T-631, D-367) is unpacked to releases/<id> beside this folder and
#                 `current` names it; the folder's release files become links through `current` (a copied file is
#                 moved to releases/.replaced-<time>/), the site's own files in deploy/ stay. The install then goes
#                 on from the signed tree: deploy/install.sh, now a link into it, runs again
#   3. settings:  deploy/settings.yaml + deploy/.env from the settings wizard (questions, or --answers), random
#                 service passwords; .env 0600, settings.yaml 0640 for group tb; an existing settings.yaml is kept
#                 and re-validated
#   4. start:     docker compose up --wait --pull never with the chosen model profile (every image from the bundle,
#                 digest pins kept on either Docker image store: tools/image_pins.py); egress rules (deploy/network.sh);
#                 the systemd units of deploy/systemd (egress closed at boot before Docker, the stack after a restart,
#                 the egress refresh and watchdog timers; D-377)
#   5. accounts:  first console administrator (password printed once); users page for the rest
#   6. check:     deploy/check_host.sh; the console URL and the intake address
# In GPU mode step 3 also makes the key of the on-box model servers (TB_LLM_API_KEY, D-177) and step 4 checks that
# they serve the pinned names and require that key (trialbox doctor --serving): a mismatch stops the install.
# TB_COMPOSE_OVERRIDE=<file> adds one compose file after the others (the box rehearsal's model stand-ins, D-176); it is
# printed and kept in deploy/.env COMPOSE_FILE so every later compose command uses it too.
# Re-running is safe: every step is idempotent. Nothing leaves the host: no registry, no download, no telemetry.
# The one exception: when live ClinicalTrials.gov is chosen, one HTTPS request to clinicaltrials.gov (no data sent)
# checks that this host can reach it (D-140).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ARGS=("$@")  # D-367: the install goes on from the signed tree with the same arguments
BUNDLE=""; ANSWERS=""; MODE="${TB_LLM_MODE:-auto}"; GPU="${TB_GPU_PROFILE:-auto}"; YES=0; CHECK=0
TIER=""; TIER_CHECK=0; GPU_SET=0; MODE_SET=0; CTGOV="${TB_CTGOV_INSTALL:-}"; CTGOV_CHECK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift ;;
    --tier-check) TIER_CHECK=1 ;;
    --answers) ANSWERS="$2"; shift ;;
    --mode) MODE="$2"; MODE_SET=1; shift ;;
    --gpu) GPU="$2"; GPU_SET=1; shift ;;
    --yes) YES=1 ;;
    --ctgov) CTGOV="$2"; shift ;;
    --ctgov-check) CTGOV_CHECK=1 ;;
    --check) CHECK=1 ;;
    -h|--help) sed -n 2,40p "$0"; exit 0 ;;
    -*) echo "install: unknown option $1" >&2; exit 2 ;;
    *) BUNDLE="$1" ;;
  esac
  shift
done
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
PUBKEY="${TB_VENDOR_PUBKEY:-$ROOT/deploy/keys/vendor_ed25519.pub}"

if [ "$CHECK" = 1 ]; then exec sh "$ROOT/deploy/check_host.sh" "$@"; fi

# ------------------------------------------------------------------------------------------------ ClinicalTrials.gov
# D-140 (owner, 2026-11-09): each hospital chooses; the default is offline. live = the box may reach
# clinicaltrials.gov:443; offline = no outbound access, the trials come from the reference data pack in each signed
# update. live on a host without internet is refused back to offline. TB_CTGOV_PROBE=ok|fail stands in for the
# network in the tests.
ctgov_internet() {
  case "${TB_CTGOV_PROBE:-}" in ok) return 0 ;; fail) return 1 ;; esac
  if command -v curl >/dev/null; then curl -fsS -o /dev/null -m 8 https://clinicaltrials.gov/api/v2/version 2>/dev/null
  else timeout 8 bash -c ': </dev/tcp/clinicaltrials.gov/443' 2>/dev/null; fi
}
ctgov_question() {
  cat <<'EOQ'
  ClinicalTrials.gov: may this box reach clinicaltrials.gov on the internet?
    offline = no (default). TrialBox uses the copy that comes with each update: no outbound access; the data are as of the update.
    live    = yes. TrialBox asks ClinicalTrials.gov directly: always current; one outbound address; no patient data is sent.
  ClinicalTrials.gov：この機器からインターネット上の clinicaltrials.gov に接続してよいですか？
    offline = いいえ（既定）。更新のたびに届く写しを使います。外部へは接続しません。データは更新の時点のものです。
    live    = はい。TrialBox が ClinicalTrials.gov に直接問い合わせます。常に最新。外部への接続先は1か所で、患者データは送りません。
  ClinicalTrials.gov：本機可以連上網際網路的 clinicaltrials.gov 嗎？
    offline = 不可以（預設）。使用每次更新附帶的資料副本：不對外連線；資料為該次更新當時的版本。
    live    = 可以。TrialBox 直接查詢 ClinicalTrials.gov：資料隨時最新；只對外連一個位址；不傳送病人資料。
EOQ
}
if [ "$CTGOV_CHECK" = 1 ]; then
  if ctgov_internet; then echo "internet: yes (live is possible; the default stays offline)"
  else echo "internet: no (offline only)"; fi
  exit 0
fi
case "$CTGOV" in ""|live|offline) ;; *) echo "install: --ctgov must be live or offline" >&2; exit 2 ;; esac

# ------------------------------------------------------------------------------------------------ 0. tier
# D-138: before anything is loaded or started. The record rule is tools/serving_config.py's (D-112, D-124).
# TB_TIER_TEST_ARCH / TB_TIER_TEST_CARD stand in for uname and nvidia-smi in the tests only.
TIER_RECORD=""
if [ -n "$TIER" ]; then
  [ "$GPU_SET" = 0 ] || die "--tier and --gpu: give one (a tier names its GPU profile)"
  [ "$MODE_SET" = 0 ] || [ "$MODE" = gpu ] || die "--tier needs the GPU: drop --mode $MODE"
  command -v python3 >/dev/null || die "--tier needs python3 on the host to read the serving records"
  set +e
  TIER_OUT="$(python3 "$ROOT/tools/tiers.py" check --tier "$TIER" --deploy "$ROOT/deploy" \
    ${TB_TIER_TEST_ARCH:+--arch "$TB_TIER_TEST_ARCH"} ${TB_TIER_TEST_CARD:+--card "$TB_TIER_TEST_CARD"})"
  rc=$?
  set -e
  [ "$rc" = 0 ] || exit 3   # the reason is on stderr: what is missing and how to get a record
  GPU="${TIER_OUT%% *}"; TIER_RECORD="${TIER_OUT#* }"; MODE=gpu
  echo "    tier $TIER: $GPU profile, measured record $TIER_RECORD"
  [ "$TIER_CHECK" = 0 ] || exit 0
elif [ "$TIER_CHECK" = 1 ]; then
  die "--tier-check needs --tier small|medium|large"
fi
[ -n "$BUNDLE" ] || die "usage: deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--yes]"
[ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"

# ------------------------------------------------------------------------------------------------ 1. host
say "host"
command -v docker >/dev/null || die "Docker is not installed (Docker Engine 27+ with the compose plugin; docs/SECURITY.md)"
docker info >/dev/null 2>&1 || die "Docker is not running (sudo systemctl start docker)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is missing"
if [ "$MODE" = auto ]; then
  if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then MODE=gpu; else MODE=stub; fi
fi
case "$MODE" in
  gpu) command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1 || die "--mode gpu but nvidia-smi finds no GPU (driver + container toolkit; docs/SECURITY.md)"
       docker info 2>/dev/null | grep -qi nvidia || echo "install: warning: Docker lists no nvidia runtime; the model service may not start" >&2 ;;
  stub) echo "    no GPU: structured criteria only (FEAS, NAV, COHORT); note criteria wait for a GPU or a pinned cloud model" ;;
  *) die "--mode must be gpu or stub" ;;
esac
# GPU profile (D-95, D-124; deploy/gpu_profile.sh detects it from the card): rtxpro6000 = judge and verifier both
# resident on a 96 GB card at 32k; gb10 = the same pair resident on a DGX Spark at 16k; rtx5090 = the same pair on one
# 32 GB card with the sleep swap at 8k; all three exclude on a note only when both models agree. rtx4090 = the judge
# alone on a 24 GB card, note answers never exclude; default = base llm-service
if [ "$MODE" = gpu ] && [ "$GPU" = auto ]; then
  GPU="$(sh "$ROOT/deploy/gpu_profile.sh")"
fi
case "$GPU" in auto|default|rtxpro6000|gb10|rtx5090|rtx4090) ;; *) die "--gpu must be rtxpro6000, gb10, rtx5090, rtx4090 or default" ;; esac
# D-348: the vLLM image of deploy/images.lock must run here (its architecture, the driver its CUDA needs, the GPU's
# compute capability), before anything is loaded: a CUDA 13 image on an older driver would only fail at start
if [ "$MODE" = gpu ]; then
  if command -v python3 >/dev/null; then
    sh "$ROOT/deploy/check_host.sh" --gpu-only --gpu "$GPU" 2>&1 | sed 's/^/    /' \
      || die "this GPU host cannot run the vLLM image of deploy/images.lock (FAIL above); nothing was changed"
  else
    echo "install: warning: no python3: the GPU host is not checked against deploy/images.lock" >&2
  fi
fi
[ -f "$PUBKEY" ] || die "vendor public key missing: copy vendor_ed25519.pub (from the vendor, out of band) to $PUBKEY"
if [ -f "$BUNDLE.sha256" ]; then
  (cd "$(dirname "$BUNDLE")" && sha256sum -c "$(basename "$BUNDLE").sha256" >/dev/null) || die "bundle checksum mismatch"
fi
echo "    docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), model profile: $MODE, gpu: $GPU, vendor key: $PUBKEY"

# ------------------------------------------------------------------------------------------------ 2. bundle
say "bundle: verify and load (host tree, images, models, rulesets)"
# D-367: the second run, from the signed tree this run's load switched `current` to, does not load again
if [ -z "${TB_INSTALL_SIGNED:-}" ] || [ "$TB_INSTALL_SIGNED" != "$(readlink "$ROOT/current" 2>/dev/null)" ]; then
  sh "$ROOT/tools/apply_update.sh" "$BUNDLE" --dry-run >/dev/null || die "the bundle is not a valid signed TrialBox release; nothing was changed"
  TB_SKIP_AUDIT=1 sh "$ROOT/tools/apply_update.sh" "$BUNDLE" 2>&1 | sed 's/^/    /' || die "loading the bundle failed"
fi
docker image inspect "$IMAGE_PY" >/dev/null 2>&1 || die "the bundle carried no $IMAGE_PY image"
# T-631, D-367: compose files, host tools and configuration come only from the signed release
[ -L "$ROOT/current" ] && [ -d "$ROOT/current/deploy" ] \
  || die "the bundle carried no host tree (payload kind host, D-367): build the release with tools/make_bundle.sh of T-631 or later"
RELEASE="$(readlink "$ROOT/current")"
echo "    release: $ROOT/current -> $RELEASE"
if [ "${TB_INSTALL_SIGNED:-}" != "$RELEASE" ]; then
  # deploy/install.sh is now a link into the signed tree (run by that path, so ROOT stays this folder)
  [ -L "$ROOT/deploy/install.sh" ] || die "deploy/install.sh is not the signed release's (tools/host_tree.py status)"
  say "continuing from the signed release ($ROOT/deploy/install.sh -> $(readlink "$ROOT/deploy/install.sh"))"
  TB_INSTALL_SIGNED="$RELEASE" exec bash "$ROOT/deploy/install.sh" ${ARGS[@]+"${ARGS[@]}"}
fi

# ------------------------------------------------------------------------------------------------ 3. settings
say "settings"
FRESH=0; [ -f deploy/.env ] || FRESH=1   # a box installed before step 8 keeps its shared token until rotation
mkdir -p deploy/keys deploy/secrets
if [ ! -f deploy/settings.yaml ]; then
  if [ -n "$ANSWERS" ]; then
    [ -f "$ANSWERS" ] || die "no such answers file: $ANSWERS"
    docker run --rm -e TB_CTGOV_MODE="$CTGOV" -v "$ROOT/deploy:/out" -v "$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS"):/in/answers.yaml:ro" \
      --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.settings_wizard --answers /in/answers.yaml --out /out/settings.yaml --env-out /out/.env
  else
    [ -t 0 ] || die "no deploy/settings.yaml and no terminal for the questions: pass --answers site.yaml (RUNBOOK §1 step 3)"
    docker run --rm -it -e TB_CTGOV_MODE="$CTGOV" -v "$ROOT/deploy:/out" --user "$(id -u):$(id -g)" "$IMAGE_PY" \
      python -m tools.settings_wizard --out /out/settings.yaml --env-out /out/.env
  fi
else
  echo "    keeping deploy/settings.yaml (re-validating)"
  docker run --rm -v "$ROOT/deploy/settings.yaml:/in/settings.yaml:ro" "$IMAGE_PY" python -m tools.settings_wizard --check /in/settings.yaml
fi
[ -f deploy/.env ] || cp .env.example deploy/.env
# D-140: the ClinicalTrials.gov mode in plain words (en, ja, zh-TW) unless --ctgov gave it or the box already has one
if [ -z "$CTGOV" ]; then CTGOV="$(sed -n 's/^TB_CTGOV_MODE=//p' deploy/.env | tail -1)"; fi
case "$CTGOV" in
  live|offline) ;;
  *) CTGOV=offline
     if [ "$YES" != 1 ] && [ -t 0 ]; then
       ctgov_question; printf '  offline / live [offline]: '; read -r ans
       case "${ans:-offline}" in live|offline) CTGOV="${ans:-offline}" ;; *) die "answer offline or live" ;; esac
     fi ;;
esac
if [ "$CTGOV" = live ] && ! ctgov_internet; then
  echo "install: clinicaltrials.gov does not answer from this host: ClinicalTrials.gov set to offline (re-run with --ctgov live once it does)" >&2
  CTGOV=offline
fi
echo "    ClinicalTrials.gov: $CTGOV"
sed -i "/^TB_CTGOV_MODE=/d" deploy/.env && echo "TB_CTGOV_MODE=$CTGOV" >> deploy/.env
# random service passwords where the example ones are still in place
for k in POSTGRES_PASSWORD POSTGRES_WF_PASSWORD; do
  if grep -q "^$k=change-me" deploy/.env || ! grep -q "^$k=" deploy/.env; then
    sed -i.bak "/^$k=/d" deploy/.env && printf '%s=%s\n' "$k" "$(rand 32)" >> deploy/.env
  fi
done
rm -f deploy/.env.bak
# D-128, D-138: one token per service (deploy/secrets/services/, 0600; never printed). A new box has no shared
# token at all; an older box keeps its shared one working, with a warning, until `trialbox secrets rotate`.
if [ "$FRESH" = 1 ] || grep -q '^TB_SERVICE_TOKEN=change-me' deploy/.env; then sed -i '/^TB_SERVICE_TOKEN=/d' deploy/.env; fi
if command -v python3 >/dev/null; then
  python3 -m tools.trialbox secrets init --deploy "$ROOT/deploy" | sed 's/^/    /'
else
  docker run --rm --user 0 -v "$ROOT/deploy:/d" "$IMAGE_PY" python -m tools.trialbox secrets init --deploy /d | sed 's/^/    /'
fi
# D-126: every service reaches the one trial database with the workflow role's password
WF_PW="$(sed -n 's/^POSTGRES_WF_PASSWORD=//p' deploy/.env | tail -1)"
sed -i "/^TB_DB_URL=/d" deploy/.env && echo "TB_DB_URL=postgresql://trialbox:${WF_PW}@db:5432/trialbox_wf" >> deploy/.env
# D-127 (review F-06): a box is PRODUCTION unless the operator set TB_ENV on purpose (timers, mail, REDCap, gates)
grep -q '^TB_ENV=' deploy/.env || echo "TB_ENV=PRODUCTION" >> deploy/.env
# TB_LLM_MODE is the services' word (tb_common.config: vllm | stub ...), not the compose profile's (gpu | stub), D-142
LLM_MODE=stub; [ "$MODE" = gpu ] && LLM_MODE=vllm
grep -q '^TB_LLM_MODE=' deploy/.env && sed -i "s/^TB_LLM_MODE=.*/TB_LLM_MODE=$LLM_MODE/" deploy/.env || echo "TB_LLM_MODE=$LLM_MODE" >> deploy/.env
# D-177: the on-box model servers take calls only with this key (vLLM VLLM_API_KEY); the gateway alone holds it
if [ "$MODE" = gpu ] && ! grep -q '^TB_LLM_API_KEY=.' deploy/.env; then
  sed -i '/^TB_LLM_API_KEY=/d' deploy/.env && printf 'TB_LLM_API_KEY=%s\n' "$(rand 48)" >> deploy/.env
fi
NOTE_BLOCK=both_agree; [ "$GPU" = rtx4090 ] && NOTE_BLOCK=never
# the pair profiles run the verifier build: name it, or both_agree has no second model (doctor note_block), D-142
case "$MODE:$GPU" in gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)
  grep -q '^TB_GATEWAY_VERIFIER_MODEL=.' deploy/.env || { sed -i "/^TB_GATEWAY_VERIFIER_MODEL=/d" deploy/.env; echo "TB_GATEWAY_VERIFIER_MODEL=v-verifier" >> deploy/.env; }
  # and the judge build by name: a judge that names none could be answered by another build of its route (D-276)
  grep -q '^TB_GATEWAY_MODEL=.' deploy/.env || { sed -i "/^TB_GATEWAY_MODEL=/d" deploy/.env; echo "TB_GATEWAY_MODEL=j-workhorse" >> deploy/.env; } ;;
esac
grep -q '^TB_NOTE_BLOCK=' deploy/.env && sed -i "s/^TB_NOTE_BLOCK=.*/TB_NOTE_BLOCK=$NOTE_BLOCK/" deploy/.env || echo "TB_NOTE_BLOCK=$NOTE_BLOCK" >> deploy/.env
grep -q '^COMPOSE_PROFILES=' deploy/.env && sed -i "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=$MODE/" deploy/.env || echo "COMPOSE_PROFILES=$MODE" >> deploy/.env
chmod 600 deploy/.env
# the services run as tb (uid and gid 10001, deploy/docker/python.Dockerfile) and read settings.yaml read-only: a root
# 0600 file stopped every service at start (found by the box rehearsal, D-176). Group tb reads it, nobody else.
chown "$(id -u):10001" deploy/settings.yaml && chmod 640 deploy/settings.yaml
export TB_SETTINGS_FILE="./settings.yaml"
if [ "$MODE" = gpu ]; then
  # D-142 (review R-01): pin the profile's deployed pair from the site's own weights (champion: the status PRODUCTION
  # routes); without it every PRODUCTION model call is refused (build_unpinned). Builds already pinned are kept.
  mkdir -p deploy/site
  for v in JUDGE_MODEL_DIR JUDGE_MODEL VERIFIER_MODEL_DIR VERIFIER_MODEL; do  # as compose reads them from deploy/.env
    val="$(sed -n "s/^$v=//p" deploy/.env | tail -1)"; [ -z "$val" ] || export "$v=$val"
  done
  say "pinning the $GPU model pair from deploy/models (tools/pin_model.py --install)"
  docker run --rm -v "$ROOT/deploy:/d" -e JUDGE_MODEL_DIR -e JUDGE_MODEL -e VERIFIER_MODEL_DIR -e VERIFIER_MODEL "$IMAGE_PY" \
    python -m tools.pin_model --install "$GPU" --models-root /d/models --out /d/site/registry.site.yaml \
    || echo "install: warning: a model of the $GPU pair is not pinned (see above): it routes nothing until its weights are in deploy/models and install runs again (RUNBOOK §8)" >&2
  if ls deploy/site/registry.site.yaml >/dev/null 2>&1; then
    # SEC-64: every pinned build's weights must still hash to its pin, or the box does not start on them
    say "checking the pinned model weights (tools/pin_model.py --verify-all)"
    docker run --rm -v "$ROOT/deploy:/d:ro" "$IMAGE_PY" \
      python -m tools.pin_model --verify-all /d/models --out /d/site/registry.site.yaml \
      || die "model weights do not match their pins (see above): restore the pinned files or re-pin with tools/pin_model.py (RUNBOOK §8)"
  else
    echo "install: note: no model pinned yet (deploy/site/registry.site.yaml): the gateway routes nothing to a local model until you run tools/pin_model.py or make spark-e2e (RUNBOOK §8)" >&2
  fi
fi

case "$MODE:$GPU" in gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)
  # D-112, D-124: a pair profile starts only on a serving-config record of that profile on that card, uncapped
  # (tools/serving_config.py measured <profile>): the site's own record (deploy/gcp/capture-serving-config.sh after a
  # first boot) or the vendor's, shipped in the bundle (deploy/measured/). Otherwise only when the operator accepts
  # an unmeasured card for a trial boot. The Spark is measured when a site orders one (owner decision, 2026-11-08).
  REC=""
  for f in "deploy/site/serving_config.$GPU.json" "deploy/measured/serving_config.$GPU.json"; do
    [ -f "$f" ] && { REC="$f"; break; }
  done
  if [ -n "$REC" ]; then
    docker run --rm -v "$ROOT/deploy:/d:ro" "$IMAGE_PY" python -m tools.serving_config measured "$GPU" "/d/${REC#deploy/}" \
      || die "$REC is not a measurement of the $GPU profile on its own card (see above)"
    echo "    $GPU profile measured: $REC"
  elif [ -z "$TIER" ] && [ "${TB_ACCEPT_UNMEASURED_GPU:-0}" = 1 ]; then
    echo "install: warning: $GPU profile not yet measured on this card (TB_ACCEPT_UNMEASURED_GPU=1): capture deploy/site/serving_config.$GPU.json after the first boot (RUNBOOK §8)" >&2
  else
    die "the $GPU profile has no measurement on its own card (deploy/site/ or deploy/measured/serving_config.$GPU.json). For a first trial boot re-run with TB_ACCEPT_UNMEASURED_GPU=1, then capture the record (RUNBOOK §8)"
  fi ;;
esac
case "$MODE:$GPU" in
  gpu:rtxpro6000) PROFILE=P-PRO6000 ;; gpu:gb10) PROFILE=P-GB10 ;; gpu:rtx5090|gpu:rtx4090) PROFILE=P-5090 ;; *) PROFILE=P-GB10 ;;
esac
grep -q '^TB_PROFILE=' deploy/.env && sed -i "s/^TB_PROFILE=.*/TB_PROFILE=$PROFILE/" deploy/.env || echo "TB_PROFILE=$PROFILE" >> deploy/.env
sed -i "/^TB_TIER=/d" deploy/.env; [ -z "$TIER" ] || echo "TB_TIER=$TIER" >> deploy/.env

# ------------------------------------------------------------------------------------------------ 4. start
COMPOSE=(docker compose --project-directory deploy -f deploy/docker-compose.yml -f deploy/docker-compose.secrets.yml)
FILES="$ROOT/deploy/docker-compose.yml:$ROOT/deploy/docker-compose.secrets.yml"
case "$MODE:$GPU" in
  gpu:rtxpro6000) COMPOSE+=(-f deploy/docker-compose.rtxpro6000.yml); FILES="$FILES:$ROOT/deploy/docker-compose.rtxpro6000.yml" ;;
  gpu:gb10) COMPOSE+=(-f deploy/docker-compose.gb10.yml); FILES="$FILES:$ROOT/deploy/docker-compose.gb10.yml" ;;
  gpu:rtx5090|gpu:rtx4090) COMPOSE+=(-f deploy/docker-compose.rtx5090.yml); FILES="$FILES:$ROOT/deploy/docker-compose.rtx5090.yml" ;;
esac
LOCK_FILES="$FILES"
if [ -n "${TB_COMPOSE_OVERRIDE:-}" ]; then  # D-176: the rehearsal's model stand-ins (or a site's own override)
  [ -f "$TB_COMPOSE_OVERRIDE" ] || die "TB_COMPOSE_OVERRIDE: no such file $TB_COMPOSE_OVERRIDE"
  OVR="$(cd "$(dirname "$TB_COMPOSE_OVERRIDE")" && pwd)/$(basename "$TB_COMPOSE_OVERRIDE")"
  # every later compose command (as root: update, secrets rotate) reads it: only its owner (root or the installer)
  # may change it, and it must stay where it is
  [ "$(stat -c %u "$OVR")" = 0 ] || [ "$(stat -c %u "$OVR")" = "$(id -u)" ] || die "TB_COMPOSE_OVERRIDE: $OVR is not owned by root or $(id -un)"
  [ $((0$(stat -c %a "$OVR") & 022)) = 0 ] || die "TB_COMPOSE_OVERRIDE: $OVR is writable by group or others (chmod go-w)"
  echo "install: note: compose override in use: $OVR (kept in deploy/.env COMPOSE_FILE)" >&2
  COMPOSE+=(-f "$OVR"); FILES="$FILES:$OVR"
fi
COMPOSE+=(--profile "$MODE")
# D-348: every third-party image of TrialBox's own compose files is the one deploy/images.lock pins, by digest (the
# site's TB_COMPOSE_OVERRIDE is its own and is not checked)
if command -v python3 >/dev/null; then
  python3 -m tools.images_lock check-compose --files "$LOCK_FILES" 2>&1 | sed 's/^/    /' \
    || die "a compose file names a third-party image that deploy/images.lock does not pin (FAIL above)"
fi
# the same file set for every later `docker compose --project-directory deploy ...` (secrets rotate, update, logs)
sed -i "/^COMPOSE_FILE=/d" deploy/.env && echo "COMPOSE_FILE=$FILES" >> deploy/.env
# D-138 log retention: where collected service logs and the audit archive go (RUNBOOK §2 "Logs"); the days are in
# settings.yaml retention (the wizard's jp/tw defaults)
grep -q '^TB_LOG_DIR=' deploy/.env || echo "TB_LOG_DIR=$ROOT/deploy/logs" >> deploy/.env
grep -q '^TB_AUDIT_ARCHIVE_DIR=' deploy/.env || echo "TB_AUDIT_ARCHIVE_DIR=$ROOT/deploy/logs/audit-archive" >> deploy/.env
grep -q '^TB_BACKUP_TARGETS=' deploy/.env || echo "TB_BACKUP_TARGETS=$ROOT/deploy/backups" >> deploy/.env
UP_EXTRA=(); [ "$MODE:$GPU" = gpu:rtx4090 ] && UP_EXTRA=(--scale llm-verifier=0)
if [ "$YES" != 1 ] && [ -t 0 ]; then
  printf 'Start the stack now with profile %s? [Y/n] ' "$MODE"; read -r ans; case "$ans" in n|N) die "stopped before start; re-run with --yes to skip the question" ;; esac
fi
say "starting the stack (profile $MODE)"
"${COMPOSE[@]}" config -q
# D-176: every image the stack runs comes from the bundle, none from a registry. A digest-pinned image is found by its
# digest (Docker's containerd image store) or by the bundle's image id (the classic overlay2 store keeps no digests;
# tools/image_pins.py sets its compose variable in deploy/.env). TB_INSTALL_PULL=missing only on a site that mirrors
# the third-party images itself (make_bundle.sh --no-third-party).
PULL="${TB_INSTALL_PULL:-never}"
case "$PULL" in never|missing) ;; *) die "TB_INSTALL_PULL must be never or missing" ;; esac
if command -v python3 >/dev/null; then
  python3 -m tools.image_pins resolve --deploy deploy --files "$FILES" 2>&1 | sed 's/^/    /' \
    || die "a pinned image is not on this box (MISSING above): the bundle must carry it (make_bundle.sh without --no-third-party)"
fi
if [ "$PULL" = never ]; then
  MISSING=""
  while IFS= read -r img; do
    docker image inspect "$img" >/dev/null 2>&1 || MISSING="$MISSING $img"
  done < <("${COMPOSE[@]}" config --images | sort -u)
  [ -z "$MISSING" ] || die "images not on this box:$MISSING. They come only from the bundle; nothing is pulled (TB_INSTALL_PULL=missing on a site with its own mirror)"
  echo "    every image of the stack is on this box (nothing is pulled)"
fi
# T-612 (DATA-004): the site keys are made here and nowhere else. A key already in the secrets volume is kept; the
# ingest refuses a night whose key is missing or is not the one the box's pseudonyms were made with
say "site keys (made once, never replaced)"
"${COMPOSE[@]}" run --rm --no-deps -T adapter python -m adapter.cli keys-init | sed 's/^/    /' \
  || die "the site keys could not be made or read (above): put the site's keys back from the backup (RUNBOOK §5)"
"${COMPOSE[@]}" up -d --pull "$PULL" "${UP_EXTRA[@]}" --wait --wait-timeout "${TB_INSTALL_UP_TIMEOUT:-900}" \
  || { "${COMPOSE[@]}" ps; die "the stack did not become healthy (docker compose logs)"; }
if [ "$MODE" = gpu ]; then
  # D-177: the model servers must serve the names the site pinned and refuse calls without the key; otherwise the
  # gateway would get 404 or 401 on every call and the box would screen nothing (doctor check "serving")
  say "model servers: pinned served names and key (trialbox doctor --serving)"
  set +e
  docker run --rm --network trialbox-model-net --env-file deploy/.env -v "$ROOT/deploy:/app/deploy:ro" \
    --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.trialbox doctor --serving | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  set -e
  [ "$rc" = 0 ] || die "the model servers do not match the pins or the key (FAIL above): the stack is up but every model call would be refused; fix deploy/.env (JUDGE_MODEL, VERIFIER_MODEL, TB_LLM_API_KEY) or re-pin (RUNBOOK §8), then re-run"
fi
EGRESS_OK=0
if [ "$(id -u)" = 0 ] && [ -x deploy/network.sh ]; then
  say "egress rules"
  if deploy/network.sh apply; then EGRESS_OK=1
  else echo "install: warning: egress rules not applied (deploy/network.sh apply)" >&2; fi
fi
# T-108b (D-377; CR-043, OPS-049, OPS-064): the systemd units. trialbox-egress loads the closed egress table from the
# state file `apply` just wrote, before Docker starts; trialbox starts the stack after it and re-applies the rules;
# two timers refresh the rules and run the watchdog. Only once the state file exists: a boot without it would stop
# Docker. TB_SYSTEMD_DIR moves the target folder (tests); TB_SYSTEMD=0 skips the step.
SYSTEMD_DIR="${TB_SYSTEMD_DIR:-/etc/systemd/system}"
if [ "${TB_SYSTEMD:-1}" != 0 ] && [ "$(id -u)" = 0 ] && [ -d /run/systemd/system ] && command -v systemctl >/dev/null; then
  if [ "$EGRESS_OK" = 1 ]; then
    say "systemd units (egress at boot, the stack after a restart, watchdog)"
    for unit in deploy/systemd/*.service deploy/systemd/*.timer; do
      sed "s#@TB_ROOT@#$ROOT#g" "$unit" > "$SYSTEMD_DIR/$(basename "$unit")"
      chmod 644 "$SYSTEMD_DIR/$(basename "$unit")"
    done
    systemctl daemon-reload
    systemctl enable trialbox-egress.service trialbox.service trialbox-egress-refresh.timer trialbox-watchdog.timer \
      trialbox-egress-watch.service >/dev/null 2>&1 || die "the systemd units could not be enabled (systemctl status trialbox-egress trialbox)"
    systemctl start trialbox-egress.service trialbox-egress-refresh.timer trialbox-watchdog.timer \
      trialbox-egress-watch.service >/dev/null 2>&1 || true
    echo "    enabled: trialbox-egress, trialbox, trialbox-egress-refresh.timer, trialbox-watchdog.timer, trialbox-egress-watch"
    echo "    (trialbox-ops.timer is installed, not enabled: RUNBOOK §15)"
  else
    echo "install: warning: systemd units not enabled: the egress rules were not applied (no state file for a boot)" >&2
  fi
fi
if [ "$(id -u)" = 0 ] && [ -d /etc/cron.d ] && command -v python3 >/dev/null; then
  # D-138: every night collect yesterday's service logs, prune by settings.retention, copy the audit to its archive
  printf '%s\n' "SHELL=/bin/sh" "20 0 * * * root cd $ROOT && python3 -m tools.trialbox logs daily >> /var/log/trialbox-retention.log 2>&1" \
    > /etc/cron.d/trialbox-retention && chmod 644 /etc/cron.d/trialbox-retention
  echo "    log retention: /etc/cron.d/trialbox-retention (00:20 daily)"
fi
# D-138: the site's one-page network, port and secret sheet, from the compose files this box runs
SHEET_MOUNT=(); SHEET_FILES="$(echo "$FILES" | sed "s#$ROOT/deploy/#deploy/#g")"
if [ -n "${OVR:-}" ]; then  # the override is outside deploy/: mount it where the sheet tool looks
  SHEET_MOUNT=(-v "$OVR:/app/deploy/compose-override.yml:ro"); SHEET_FILES="${SHEET_FILES//$OVR/deploy/compose-override.yml}"
fi
docker run --rm -v "$ROOT/deploy:/app/deploy" ${SHEET_MOUNT[@]+"${SHEET_MOUNT[@]}"} --user "$(id -u):$(id -g)" "$IMAGE_PY" \
  python -m tools.network_sheet --files "$SHEET_FILES" --env deploy/.env --out deploy/site/network-sheet \
  >/dev/null 2>&1 && echo "    network sheet: deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}" \
  || echo "install: note: network sheet not written (python -m tools.network_sheet)" >&2
[ -f deploy/secrets/backup.pub ] || echo "install: note: no backup key yet. With hospital IT: python3 -m tools.trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub (RUNBOOK §5); updates refuse to run without a backup" >&2
# T-117b (D-274): the backup cron (/etc/cron.d/trialbox-backup), WAL archiving when the db image carries pgBackRest
# and a target is off the box, and the first backup. PRODUCTION needs an alert route (TB_BACKUP_ALERT_CMD, or
# TB_BACKUP_MAILTO with a mail relay); `trialbox doctor` then checks the backup's age and its off-box target
if [ "$(id -u)" = 0 ] && [ -d /etc/cron.d ] && command -v python3 >/dev/null; then
  say "backups: cron, WAL archiving, first backup"
  set +e
  python3 -m tools.trialbox backup-install --deploy deploy 2>&1 | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  set -e
  [ "$rc" = 0 ] || die "the backup schedule is not installed (above): set TB_BACKUP_ALERT_CMD or TB_BACKUP_MAILTO in deploy/.env (RUNBOOK §5), then re-run"
else
  echo "install: warning: the backup cron is not installed (needs root, /etc/cron.d and python3): python3 -m tools.trialbox backup-install --deploy deploy (RUNBOOK §5)" >&2
fi

for f in deploy/refdata/pending/*.tar; do  # D-140: the reference data pack of the install bundle, now the db runs
  [ -f "$f" ] || continue
  if "${COMPOSE[@]}" cp "$f" criteria-compiler:/tmp/refdata-install.tar \
    && "${COMPOSE[@]}" exec -T criteria-compiler python -m tb_common.refdata load /tmp/refdata-install.tar --by deploy/install.sh; then
    # D-187: kept, not deleted: backups leave the pack's rows out and a restore loads it again from here
    mkdir -p deploy/refdata/loaded && mv -f "$f" deploy/refdata/loaded/; echo "    reference data loaded: $(basename "$f" .tar)"
  else
    echo "install: warning: reference data $(basename "$f") not loaded (python -m tb_common.refdata load)" >&2
  fi
done
if [ "$CTGOV" = offline ] && ! "${COMPOSE[@]}" exec -T criteria-compiler python -m tb_common.refdata status 2>/dev/null | grep -q pack_id; then
  echo "install: note: offline ClinicalTrials.gov needs a reference data pack: tools/apply_update.sh <bundle with refdata>" >&2
fi

for f in deploy/updates/pending_audit/*.json; do  # the bundle's update.applied event, deferred until now
  [ -f "$f" ] || continue
  "${COMPOSE[@]}" exec -T orchestrator python -c '
import json, sys
from pathlib import Path
from tb_common.audit import AuditLog
s = json.load(sys.stdin)
AuditLog(Path("/data/audit")).append("update.applied", actor="deploy/install.sh", input_sha=s["manifest_sha256"],
    detail={"bundle_id": s["bundle_id"], "signer": s["signer"], "files": s["files"]})
' < "$f" && rm -f "$f" && echo "    audited bundle $(basename "$f" .json)"
done

# ------------------------------------------------------------------------------------------------ 5. accounts
say "first console administrator"
ADMIN_MAIL="$(sed -n 's/^MAIL_ADMIN_ADDR=//p' deploy/.env | head -1)"
ADMIN_MAIL="${ADMIN_MAIL:-${TB_ADMIN_EMAIL:-}}"
if [ -n "$ADMIN_MAIL" ]; then
  "${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin --mailbox "$ADMIN_MAIL"
else
  "${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin
fi
echo "    add coordinators and viewers on the console's Users page, or: docker compose exec console python -m console.cli add-user"

# ------------------------------------------------------------------------------------------------ 6. check
say "host check"
HOST_ARGS=(); [ "$MODE" = gpu ] && HOST_ARGS=(--gpu "$GPU")
sh "$ROOT/deploy/check_host.sh" ${HOST_ARGS[@]+"${HOST_ARGS[@]}"} || echo "install: host check reported FAIL lines above: fix them before go-live (docs/SECURITY.md)" >&2
PORT="$(sed -n 's/^TB_HOST_CONSOLE_PORT=//p' deploy/.env | head -1)"
cat <<EOT

  TrialBox is running.
  Console:            http://127.0.0.1:${PORT:-8090}   (sign in as admin with the password printed above)
  Intake mailbox:     $(sed -n 's/^MAIL_INTAKE_ADDR=//p' deploy/.env | head -1)
  First ingest:       docker compose --project-directory deploy exec adapter python -m adapter.cli run   (or 02:00 nightly)
  Acceptance:         docs/RUNBOOK.md §6 before go-live;  updates: tools/apply_update.sh <bundle>
EOT
