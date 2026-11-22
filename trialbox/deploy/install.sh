#!/usr/bin/env bash
# TrialBox one-file installer for a hospital workstation or server (clinical review 2026-11, section 6; RUNBOOK §1).
#
#   sudo deploy/install.sh trialbox-<version>.tar --tier small|medium|large [--answers site.yaml] [--yes]
#   sudo deploy/install.sh trialbox-<version>.tar [--answers site.yaml] [--mode gpu|stub] [--gpu rtxpro6000|gb10|rtx5090|rtx4090] [--yes]
#        [--environment DEV|TEST|VALIDATION|PRODUCTION]   (D-837; default PRODUCTION, D-127)
#        [--ssh-off-over-ssh]   (H-70: run over SSH, hardening.conf's SSH=off is refused unless this is given)
#   sudo deploy/install.sh --check            # host checks only (deploy/check_host.sh)
#   deploy/install.sh --tier large --tier-check   # only: may this tier be installed on this machine?
#   Without a TPM, set bundle and answers to their paths. In your own Bash shell (passphrase of at least 12 characters):
#   IFS= read -rs TB_KEK_PASSPHRASE; export TB_KEK_PASSPHRASE
#   sudo --preserve-env=TB_KEK_PASSPHRASE TB_KEK_BACKEND=passphrase deploy/install.sh "$bundle" --answers "$answers"
#   unset TB_KEK_PASSPHRASE
#   sudo VAR=value command shows the value in the process list.
#   ... --ctgov live|offline                       # ClinicalTrials.gov: online, or the copy in each update (D-140)
#   deploy/install.sh --ctgov-check                # only: which ClinicalTrials.gov mode would be suggested here?
#
# Tiers (D-138, tools/tiers.py): small = rtx5090, medium = gb10, large = rtxpro6000 (the boxes of D-124). A tier is
# installed only from a measured serving record of its own uncapped card (deploy/site/ or deploy/measured/
# serving_config.<gpu>.json, tools/serving_config.py measured); there is no override. --gpu with
# TB_ACCEPT_UNMEASURED_GPU=1 stays for a trial boot of an unmeasured card, and is not a tier install; since D-726 only
# on a rehearsal box (--rehearsal sets it; TB_COMPOSE_OVERRIDE= empty keeps the real model servers).
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
#   4. start:     down --remove-orphans after a failed run, only in this install's own project, never a healthy stack
#                 docker compose up --wait --pull never with the chosen model profile (every image from the bundle,
#                 digest pins kept on either Docker image store: tools/image_pins.py); egress rules (deploy/network.sh);
#                 the systemd units of deploy/systemd (egress closed at boot before Docker, the stack after a restart,
#                 the egress refresh and watchdog timers; D-377)
#   5. accounts:  first console administrator (password and enrolment code printed once); users page for the rest
#   6. check:     deploy/check_host.sh; the https:// console URL must answer; the intake address
# Host baseline (T-634, D-408): in VALIDATION and PRODUCTION the site keys are sealed under a KEK right after they are
# made (deploy/hardening/seal_keys.sh), and with deploy/site/hardening.conf the input firewall and SSH are set after
# the egress rules (deploy/hardening/apply.sh). The disk unlock is hospital IT's, once, at OS install
# (deploy/hardening/disk-unlock.sh); the host check FAILs a disk the TPM alone opens.
# Site inputs and a finished install (T-632, D-382): the site's mapping lives in deploy/site/mapping (the adapter and
# the wizard look there before the image) and the feed folder is TB_SOURCE_DIR (required in PRODUCTION). TLS is on:
# the wizard's TB_TLS_HOSTNAME (asked here when missing) adds deploy/docker-compose.identity.yml after `console.cli
# check-tls` passed. Both cron files (log retention, backups) are installed. The judge is named from the
# configuration (tools/pin_model.py --name-judge). The install ends with exit 1 when a FAIL line remains.
# In GPU mode step 3 also makes the key of the on-box model servers (TB_LLM_API_KEY, D-177) and step 4 checks that
# they serve the pinned names and require that key (trialbox doctor --serving): a mismatch stops the install.
# The box form (T-729, D-466): deploy/box-install.sh runs this script with TB_BOX=1 and an answers file it planned from
# the detected hardware: deploy/docker-compose.box.yml is added (the console's first-run folder) and no administrator
# is made here (the owner makes the first accounts in the first-run wizard). TB_BOX_DEFER_SEAL=1 (a board without a
# TPM) leaves the site keys to the box's apply step, which seals them under the passphrase the owner set.
# TB_COMPOSE_OVERRIDE=<file> adds one compose file after the others (the box rehearsal's model stand-ins, D-176); it is
# printed and kept in deploy/.env COMPOSE_FILE so every later compose command uses it too.
# --rehearsal (D-726, D-887): a rehearsal box, which says so. It is TEST from before the bundle loads (deploy/site/
# rehearsal.json), refused on a PRODUCTION or VALIDATION box and on a box whose volumes hold data from no rehearsal;
# deploy/.env gets TB_ENV=VALIDATION (the integrator's (i): D3 stays on the box, so SCREEN reaches the pinned builds)
# and TB_REHEARSAL=1, doctor says "REHEARSAL BOX", and a site box refuses a bundle built with make_bundle.sh
# --rehearsal. The model stand-ins and TB_ACCEPT_UNMEASURED_GPU=1 work on a rehearsal box only.
# Re-running is safe: every step is idempotent. Nothing leaves the host: no registry, no download, no telemetry.
# The one exception: when live ClinicalTrials.gov is chosen, one HTTPS request to clinicaltrials.gov (no data sent)
# checks that this host can reach it (D-140).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ARGS=("$@")  # D-367: the install goes on from the signed tree with the same arguments
BUNDLE=""; ANSWERS=""; MODE="${TB_LLM_MODE:-auto}"; GPU="${TB_GPU_PROFILE:-auto}"; YES=0; CHECK=0
TIER=""; TIER_CHECK=0; GPU_SET=0; MODE_SET=0; CTGOV="${TB_CTGOV_INSTALL:-}"; CTGOV_CHECK=0; REHEARSAL=0
ENVIRONMENT=""; SSH_OFF_OVER_SSH=0
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
    --rehearsal) REHEARSAL=1 ;;
    --environment) ENVIRONMENT="$2"; shift ;;
    --ssh-off-over-ssh) SSH_OFF_OVER_SSH=1 ;;
    -h|--help) sed -n 2,45p "$0"; exit 0 ;;
    -*) echo "install: unknown option $1" >&2; exit 2 ;;
    *) BUNDLE="$1" ;;
  esac
  shift
done
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
# D-831: a long step says it is alive once a minute on stderr (a watchdog sees life): alive_start before it,
# alive_stop after; die stops it too. The heartbeat ends its own sleep when stopped: a sleep left behind would hold a
# pipe open for up to a minute. indent prefixes each line as it comes (sed block-buffers into a pipe or a log)
ALIVE_PID=""
alive_start() {
  local what="$1" installer=$$
  # it also ends within a minute of the installer's own end (set -e, a signal): it never outlives the install
  ( s=""; trap 'kill "$s" 2>/dev/null; exit 0' TERM; n=0
    while kill -0 "$installer" 2>/dev/null; do
      sleep 60 & s=$!; wait "$s"; n=$((n + 1))
      kill -0 "$installer" 2>/dev/null && echo "    ... still $what ($n min)" >&2
    done
  ) >&2 & ALIVE_PID=$!
}
alive_stop() {
  [ -n "$ALIVE_PID" ] || return 0
  kill "$ALIVE_PID" 2>/dev/null || true; wait "$ALIVE_PID" 2>/dev/null || true; ALIVE_PID=""
}
die() { alive_stop; printf 'install: %s\n' "$*" >&2; exit 1; }
indent() { while IFS= read -r line || [ -n "$line" ]; do printf '    %s\n' "$line"; done; }
# ENV-EARLY (D-1365, re-check of #1175): an environment that is not one of the four stops here, at argument parsing,
# before anything is loaded, linked, made or copied: --environment, or (neither it nor --rehearsal given) a TB_ENV an
# existing deploy/.env already holds, read without changing anything. Read as the settings step reads them
EARLY_ENV="$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')"
EARLY_FROM="--environment"
if [ -z "$EARLY_ENV" ] && [ "$REHEARSAL" != 1 ] && [ -f "$ROOT/deploy/.env" ] && [ -r "$ROOT/deploy/.env" ]; then
  EARLY_ENV="$(sed -n 's/^TB_ENV=//p' "$ROOT/deploy/.env" | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
  EARLY_FROM="TB_ENV in deploy/.env"
fi
case "$EARLY_ENV" in
  ""|DEV|TEST|VALIDATION|PRODUCTION) ;;
  *) die "the environment '$EARLY_ENV' ($EARLY_FROM) is not DEV, TEST, VALIDATION or PRODUCTION: nothing was loaded or written" ;;
esac
# ---- end of ENV-EARLY
rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
IMAGE_PY="${TB_IMAGE:-trialbox-py:1.0.0}"
# OPS-004 (D-570): after an install from a bundle the shipped files under deploy/ are links into ../current
# (tools/host_tree.py). A container that gets deploy/ alone sees them dangle (found by the box rehearsal: the measured
# record, the image lock, the compose files). Every container started on deploy/ also gets the release tree where
# those links point: /current beside a mount at /d, /app/current beside one at /app/deploy. A checkout has no
# release tree and gets nothing.
tree_args() {
  TREE_D=(); TREE_APP=()
  if [ -d "$ROOT/current" ]; then
    local tree; tree="$(readlink -f "$ROOT/current")"
    TREE_D=(-v "$tree:/current:ro"); TREE_APP=(-v "$tree:/app/current:ro")
  fi
}
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
# TB_TIER_TEST_ARCH / TB_TIER_TEST_CARD stand in for uname and nvidia-smi in the tests only, TB_TEST_MEM_KIB for
# /proc/meminfo's MemTotal (card 10E-5: a GB10 under 96 GiB is not tier medium).
TIER_RECORD=""
if [ -n "$TIER" ]; then
  [ "$GPU_SET" = 0 ] || die "--tier and --gpu: give one (a tier names its GPU profile)"
  [ "$MODE_SET" = 0 ] || [ "$MODE" = gpu ] || die "--tier needs the GPU: drop --mode $MODE"
  command -v python3 >/dev/null || die "--tier needs python3 on the host to read the serving records"
  set +e
  TIER_OUT="$(python3 "$ROOT/tools/tiers.py" check --tier "$TIER" --deploy "$ROOT/deploy" \
    ${TB_TIER_TEST_ARCH:+--arch "$TB_TIER_TEST_ARCH"} ${TB_TIER_TEST_CARD:+--card "$TB_TIER_TEST_CARD"} \
    ${TB_TEST_MEM_KIB:+--mem-kib "$TB_TEST_MEM_KIB"})"
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
# H-70: the host baseline near the end (deploy/hardening/apply.sh) refuses SSH=off from an SSH session; ask it now,
# when it will run (root, deploy/site/hardening.conf), so an install over SSH stops before anything is loaded or written.
# --ssh-off-over-ssh (or TB_SSH_OFF_OVER_SSH=yes, which sudo may drop) goes ahead, and is handed on to apply.sh
HB_OVER=(); [ "$SSH_OFF_OVER_SSH" = 1 ] && HB_OVER=(--ssh-off-over-ssh)
if [ "$(id -u)" = 0 ] && [ -f "$ROOT/deploy/site/hardening.conf" ]; then
  sh "$ROOT/deploy/hardening/apply.sh" --conf "$ROOT/deploy/site/hardening.conf" ${HB_OVER[@]+"${HB_OVER[@]}"} check \
    || die "the host baseline would cut this SSH session (above): nothing was loaded or written"
fi

# ------------------------------------------------------------------------------------------------ 1. host
say "host"
command -v docker >/dev/null || die "Docker is not installed (Docker Engine 27+ with the compose plugin; docs/SECURITY.md)"
docker info >/dev/null 2>&1 || die "Docker is not running (sudo systemctl start docker)"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is missing"
# HOST-PYTHON (D-831): the host steps run python3 -m tools.... (anchors, pre-start, doctor, the secrets); the modules
# they import at the top are checked here, before anything loads, not 20 minutes in. module:Debian package, one per
# word. Not cryptography: the host python3 may lack it (libs/tb_common/kek.py). Without python3 those steps say so.
HOST_PY_MODULES="yaml:python3-yaml"
if command -v python3 >/dev/null; then
  HOST_PY_MISSING=""
  for pair in $HOST_PY_MODULES; do
    python3 -c "import ${pair%%:*}" 2>/dev/null || HOST_PY_MISSING="$HOST_PY_MISSING ${pair#*:}"
  done
  [ -z "$HOST_PY_MISSING" ] || die "the host's python3 lacks what the installer needs:$HOST_PY_MISSING (Debian/Ubuntu: sudo apt-get install -y$HOST_PY_MISSING); install it, then re-run; nothing was changed"
fi
# ---- end of HOST-PYTHON
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
# resident on a 96 GB card at 32k; gb10 = the same pair resident on a 128 GB DGX Spark at 16k (a Spark under 96 GiB
# is gb10-64, refused: D-1335); rtx5090 = the same pair on one
# 32 GB card with the sleep swap at 8k; all three exclude on a note only when both models agree. rtx4090 = the judge
# alone on a 24 GB card, note answers never exclude; default = base llm-service
if [ "$MODE" = gpu ] && [ "$GPU" = auto ]; then
  GPU="$(sh "$ROOT/deploy/gpu_profile.sh")"
fi
# card 10E-5 (D-1335): gb10 is the 128 GB Spark. A host under 96 GiB of memory is the 64 GB class however gb10 was
# chosen (detected, --gpu, TB_GPU_PROFILE, --tier medium, a rehearsal): refused below. TB_TEST_MEM_KIB stands in for
# /proc/meminfo's MemTotal in the tests only
if [ "$MODE" = gpu ] && [ "$GPU" = gb10 ]; then
  GPU="$(sh "$ROOT/deploy/gpu_profile.sh" memory-class "${TB_TEST_MEM_KIB:-}")"
fi
case "$GPU" in  # a B200 is never an appliance (D-211, D-409): two MIG instances on a platform, RUNBOOK §17
  shared-quota) die "this card has MIG on (shared-quota): install.sh does not serve it; use deploy/platform (RUNBOOK §17)" ;;
  b200-no-mig) die "a B200 serves TrialBox only as two MIG instances: enable MIG, make the two instances, use deploy/platform (RUNBOOK §17)" ;;
  gb10-64) die "this DGX Spark has under 96 GiB of memory (the 64 GB class): TrialBox does not serve the model pair on it. The gb10 profile is sized for 128 GB (its model servers alone are capped at 74 GiB), and no profile of the 64 GB class is measured, so none is guessed (card 10E-5, D-1335). Install with --mode stub (structured criteria only; note criteria wait for a GPU), or use a 128 GB Spark or another measured box" ;;
  arm64-dgpu) die "an Arm 64-bit host with a discrete card that is not a GB10 has no TrialBox profile (unmeasured, root review 24): install with --mode stub, or see RUNBOOK §28" ;;
  # cards 24-5 and 24-6: the 48 GB draft is never installed, whatever is set; TB_UNMEASURED_DGPU48_MEASURING_RUN=1 is
  # honoured by its measuring run alone (tools/dgpu48.py), which starts only the model servers and installs nothing
  dgpu48) die "dgpu48 is a DRAFT, UNMEASURED 48 GB profile: no install serves it. Its one use is the measuring run (TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure, RUNBOOK §29)" ;;
esac
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
# ---- SIDECAR (H-22, D-996): make_bundle.sh names each file bare (the bundle, the bootstrap and its .sig), so the
# check works wherever the stick is mounted; only the bundle's own line is checked here
if [ -f "$BUNDLE.sha256" ]; then
  SUM_LINE="$(awk -v n="$(basename "$BUNDLE")" '$2 == n || $2 == "*" n' "$BUNDLE.sha256")"
  [ -n "$SUM_LINE" ] || die "$(basename "$BUNDLE").sha256 does not name $(basename "$BUNDLE") (a sidecar from before D-996 names the vendor's own path): compare its sum with: sha256sum $BUNDLE"
  (cd "$(dirname "$BUNDLE")" && printf '%s\n' "$SUM_LINE" | sha256sum -c - >/dev/null) || die "bundle checksum mismatch: $(basename "$BUNDLE") is not the file the vendor handed over"
fi
# ---- end of SIDECAR
echo "    docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), model profile: $MODE, gpu: $GPU, vendor key: $PUBKEY"

# INSTALL-LOCK (review 2 of #1305, M-2): one installer at a time on this folder, taken here, before the first thing is
# written. A second run while one holds it refuses and changes or removes nothing: its project cleanup would take down
# the first run's containers while they start. flock on the deploy folder itself, opened read-only: no lock file is
# written, and the lock ends with the installer's process, so a killed run leaves none behind. The run from the signed
# tree (exec below) keeps the lock it inherits on fd 9: it is not taken twice
INSTALL_LOCK="$(readlink -f "$ROOT/deploy")"
command -v flock >/dev/null || die "flock (util-linux) is missing, so a second installer could not be kept out: install util-linux, then re-run; nothing was changed"
if [ "$(readlink -f "/proc/$$/fd/9" 2>/dev/null)" != "$INSTALL_LOCK" ]; then
  exec 9<"$INSTALL_LOCK" || die "the deploy folder $INSTALL_LOCK cannot be opened for the install lock; nothing was changed"
fi
flock -n 9 || die "another deploy/install.sh is running on this folder (it holds $INSTALL_LOCK): let it finish, then re-run; nothing was changed or removed"
# ---- end of INSTALL-LOCK

# REHEARSAL (D-726): before anything loads
# the bundle's release record is judged against the box's environment while it loads (D-127): a rehearsal is TEST
# from here on, read from the mark until deploy/.env says so. TB_ENV is read as Python reads it (no quotes, no spaces,
# upper case); only DEV, TEST or nothing may become a rehearsal box, and a VALIDATION box that already is one (D-887)
RH_ENV=""; [ -f deploy/.env ] && RH_ENV="$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
if [ "$REHEARSAL" = 1 ]; then
  case "$RH_ENV" in
    ""|DEV|TEST) ;;
    VALIDATION) [ -f deploy/site/rehearsal.json ] || die "--rehearsal: this box is VALIDATION (deploy/.env TB_ENV) with no rehearsal mark: a site box is never made a rehearsal box" ;;
    *) die "--rehearsal: this box is $RH_ENV (deploy/.env TB_ENV): a site box is never made a rehearsal box" ;;
  esac
  if [ ! -f deploy/site/rehearsal.json ]; then
    for f in settings.yaml updates/installed.json; do
      [ ! -e "deploy/$f" ] || die "--rehearsal: this box holds a site's install (deploy/$f) from no rehearsal: a rehearsal starts on an empty box"
    done
    RH_VOLS="$(docker volume ls -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-trialbox}")" \
      || die "--rehearsal: docker cannot list the volumes, so the box's data cannot be checked (is Docker running?)"
    RH_VOLS="$(printf '%s' "$RH_VOLS" | tr '\n' ' ')"
    [ -z "${RH_VOLS// /}" ] || die "--rehearsal: this box holds data from no rehearsal (volumes: $RH_VOLS): a rehearsal starts on an empty box"
  fi
  [ -f "$ROOT/tools/rehearse_box/standins.yml" ] || die "--rehearsal: no model stand-ins at tools/rehearse_box/standins.yml"
  mkdir -p deploy/site && printf '{"rehearsal": true}\n' > deploy/site/rehearsal.json
  # the stand-ins unless TB_COMPOSE_OVERRIDE is set: set empty, the real model servers (an unmeasured card's trial boot)
  export TB_COMPOSE_OVERRIDE="${TB_COMPOSE_OVERRIDE-$ROOT/tools/rehearse_box/standins.yml}"
  export TB_ACCEPT_UNMEASURED_GPU=1
  echo "install: note: a rehearsal box (TB_ENV VALIDATION, ${TB_COMPOSE_OVERRIDE:-the real model servers}, an unmeasured card accepted)" >&2
elif [ -f deploy/site/rehearsal.json ] || { [ -f deploy/.env ] && grep -q '^TB_REHEARSAL=1' deploy/.env; }; then
  # a rehearsal box (or one left half emptied) never becomes a site box by an install without the argument
  die "this box was a rehearsal box (deploy/site/rehearsal.json or TB_REHEARSAL=1): run with --rehearsal, or empty it first (RUNBOOK §16, \"A rehearsal box\")"
fi
# ---- end of REHEARSAL (D-726): before anything loads

# FINISH-EARLY (10K-4, D-1390): tools/trialbox/finish_check.py reads deploy/.env, the mount table and /sys and writes
# nothing: exit 1 is a refusal (each line names the setting to change), any other code means it did not run. Here a
# re-run on an installed box (deploy/.env is there) is checked before the bundle step, which on a running box applies
# the update and restarts the stack: refused here, nothing was loaded or changed. Not for a box's own install before
# its set-up (TB_BOX=1), a rehearsal (--rehearsal: a VALIDATION box), nor the run from the signed tree after a load
# (TB_INSTALL_SIGNED): the release that load brought is applied already, so FINISH-GATE says so when it refuses
finish_check() {  # $1: what is true when it refuses; the rest: finish-check's own options (fixed words)
  local said="$1" rc=0
  shift
  python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" "$@" || rc=$?
  case "$rc" in
    0) ;;
    1) die "$said (above: the setting to change in deploy/.env; RUNBOOK §5)" ;;
    *) die "the finish check did not run (exit $rc, above), so nothing about the folders was decided: $said" ;;
  esac
}
# Review 3 of #1303: skipped only by the run the bundle step below does not load again (TB_INSTALL_SIGNED is the
# release `current` names): any other value of it (one carried in by sudo -E) is checked here like any re-run (M2).
# The environment judged is the stricter of the one the box records (deploy/.env TB_ENV; none on an installed box is
# PRODUCTION, D-127; a value that is none of the four is taken as PRODUCTION) and --environment, so a PRODUCTION
# box re-run with --environment VALIDATION is refused here, not after the load (M1)
SIGNED_RUN=0
if [ -n "${TB_INSTALL_SIGNED:-}" ] && [ "$TB_INSTALL_SIGNED" = "$(readlink "$ROOT/current" 2>/dev/null)" ]; then
  SIGNED_RUN=1
fi
GATE_ENV="$EARLY_ENV"
if [ -f "$ROOT/deploy/.env" ] && [ -r "$ROOT/deploy/.env" ] && [ "$GATE_ENV" != PRODUCTION ]; then
  REC_ENV="$(sed -n 's/^TB_ENV=//p' "$ROOT/deploy/.env" | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
  if [ -z "$REC_ENV" ] && { [ -f "$ROOT/deploy/settings.yaml" ] || [ -f "$ROOT/deploy/updates/installed.json" ]; }; then
    REC_ENV=PRODUCTION
  fi
  case "$REC_ENV" in
    "") ;;
    DEV|TEST|VALIDATION) GATE_ENV="${GATE_ENV:-$REC_ENV}" ;;
    *) GATE_ENV=PRODUCTION ;;
  esac
fi
if [ "${TB_BOX:-0}" != 1 ] && [ "$REHEARSAL" != 1 ] && [ "$SIGNED_RUN" != 1 ] && [ -f "$ROOT/deploy/.env" ]; then
  if command -v python3 >/dev/null; then
    finish_check "nothing was loaded or changed; then re-run" ${GATE_ENV:+--environment "$GATE_ENV"}
  elif [ "${GATE_ENV:-PRODUCTION}" = PRODUCTION ]; then
    die "no python3 on this host: a PRODUCTION install cannot check its backup target and audit anchor folder; nothing was loaded or changed (RUNBOOK §5)"
  fi
fi
# ---- end of FINISH-EARLY

# ------------------------------------------------------------------------------------------------ 2. bundle
# D-888: a re-run on a box installed before deploy/.env named its settings: the update's guard (and compose) see them
[ -f deploy/settings.yaml ] && export TB_SETTINGS_FILE="./settings.yaml"
say "bundle: verify and load (host tree, images, models, rulesets)"
# D-367: the second run, from the signed tree this run's load switched `current` to, does not load again
if [ "$SIGNED_RUN" != 1 ]; then  # the same test as FINISH-EARLY's skip (above)
  echo "    verifying the signature and every file of $(basename "$BUNDLE") (minutes for a large bundle)"
  alive_start "verifying the bundle"
  sh "$ROOT/tools/apply_update.sh" "$BUNDLE" --dry-run >/dev/null || die "the bundle is not a valid signed TrialBox release; nothing was changed"
  alive_stop
  echo "    loading the images, models and rulesets (10-20 minutes for a GPU bundle)"
  export PYTHONUNBUFFERED=1
  alive_start "loading the bundle"
  TB_SKIP_AUDIT=1 sh "$ROOT/tools/apply_update.sh" "$BUNDLE" 2>&1 | indent || die "loading the bundle failed"
  alive_stop
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

# Expose the signed host CLI on PATH. The link follows the release selected by an update or rollback.
if [ "$(id -u)" = 0 ]; then
  install -d /usr/local/bin
  ln -sfnT "$ROOT/tools/trialbox/__main__.py" /usr/local/bin/trialbox
fi

# ------------------------------------------------------------------------------------------------ 3. settings
say "settings"
FRESH=0; [ -f deploy/.env ] || FRESH=1   # a box installed before step 8 keeps its shared token until rotation
# D-837: a TB_ENV written into deploy/.env before the wizard rewrites the file (ENVIRONMENT below keeps it)
PRE_ENV=""; [ -f deploy/.env ] && PRE_ENV="$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
mkdir -p deploy/keys deploy/secrets deploy/site/mapping deploy/site/terminology
# D-991: deploy/site/terminology is where the site's IT puts the code-system files it loads (deploy/terminology.sh,
# docs/handover/OFFLINE-MEDIA.md); git and the image ignore it
# T-632 (OPS-011): the site's own mapping is in deploy/site/mapping, never in the image; the wizard and the adapter see
# it at /etc/trialbox/mapping and look there first (adapter.mapping.site). A mapping folder beside the answers file
# is copied in once (the site's kit: answers.yaml + mapping/), never over a file the site already has
MAPPING_MOUNT=(-v "$ROOT/deploy/site/mapping:/etc/trialbox/mapping:ro")
if [ -n "$ANSWERS" ] && [ -d "$(dirname "$ANSWERS")/mapping" ] && [ "$(cd "$(dirname "$ANSWERS")/mapping" && pwd)" != "$ROOT/deploy/site/mapping" ]; then
  cp -rn "$(dirname "$ANSWERS")/mapping/." deploy/site/mapping/ && echo "    site mapping folder: deploy/site/mapping (from $(dirname "$ANSWERS")/mapping)"
fi
# WIZARD-ENV (D-1365): the wizard is told the site's environment, so PRODUCTION refuses a silent chart-number rule
# and an unnamed health-page watcher. As ENVIRONMENT below decides it: --environment, a rehearsal's VALIDATION, a
# TB_ENV written before, else PRODUCTION (D-127). A box's first-run page asks them itself (TB_BOX=1): not told there
# Review of #1175, S1: a value that is not one of the four stops the install here, before anything is written (a
# typo must not run the wizard unguarded and leave a settings.yaml the next run keeps)
WIZ_ARGS=()
WIZ_ENV="$ENVIRONMENT"; [ -n "$WIZ_ENV" ] || { [ "$REHEARSAL" != 1 ] || WIZ_ENV=VALIDATION; }
WIZ_ENV="$(printf '%s' "${WIZ_ENV:-${PRE_ENV:-PRODUCTION}}" | tr '[:lower:]' '[:upper:]')"
case "$WIZ_ENV" in
  DEV|TEST|VALIDATION|PRODUCTION) [ "${TB_BOX:-0}" = 1 ] || WIZ_ARGS=(--environment "$WIZ_ENV") ;;
  *) die "the environment '$WIZ_ENV' (--environment, or TB_ENV in deploy/.env) is not DEV, TEST, VALIDATION or PRODUCTION: the settings wizard was not run" ;;
esac
# ---- end of WIZARD-ENV (D-1365)
SETTINGS_NEW=0
if [ ! -f deploy/settings.yaml ]; then
  SETTINGS_NEW=1  # D-736: a fresh install (a re-run keeps the site's settings and never stops a running site)
  if [ -n "$ANSWERS" ]; then
    [ -f "$ANSWERS" ] || die "no such answers file: $ANSWERS"
    tree_args
    docker run --rm -e TB_CTGOV_MODE="$CTGOV" -v "$ROOT/deploy:/out" ${TREE_D[@]+"${TREE_D[@]}"} "${MAPPING_MOUNT[@]}" -v "$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS"):/in/answers.yaml:ro" \
      --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.settings_wizard --answers /in/answers.yaml --out /out/settings.yaml --env-out /out/.env ${WIZ_ARGS[@]+"${WIZ_ARGS[@]}"}
  else
    [ -t 0 ] || die "no deploy/settings.yaml and no terminal for the questions: pass --answers site.yaml (RUNBOOK §1 step 3)"
    tree_args
    docker run --rm -it -e TB_CTGOV_MODE="$CTGOV" -v "$ROOT/deploy:/out" ${TREE_D[@]+"${TREE_D[@]}"} "${MAPPING_MOUNT[@]}" --user "$(id -u):$(id -g)" "$IMAGE_PY" \
      python -m tools.settings_wizard --out /out/settings.yaml --env-out /out/.env ${WIZ_ARGS[@]+"${WIZ_ARGS[@]}"}
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
# D-378: and one per service role of the trial database (deploy/docker/db-init/30-service-roles.sh); D-394: the
# audit writer's role too
for k in POSTGRES_PASSWORD POSTGRES_WF_PASSWORD TB_DB_PW_LAKE TB_DB_PW_CRITERIA_COMPILER TB_DB_PW_ADAPTER \
         TB_DB_PW_ORCHESTRATOR TB_DB_PW_MAIL_GATEWAY TB_DB_PW_GATEWAY TB_DB_PW_CONSOLE TB_DB_PW_AUDIT_WRITER \
         TB_DB_PW_FHIR_STORE; do
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
  tree_args
  docker run --rm --user 0 -v "$ROOT/deploy:/d" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" python -m tools.trialbox secrets init --deploy /d | sed 's/^/    /'
fi
# D-126: the host tools reach the one trial database as `trialbox`; each service has its own role (D-378)
WF_PW="$(sed -n 's/^POSTGRES_WF_PASSWORD=//p' deploy/.env | tail -1)"
sed -i "/^TB_DB_URL=/d" deploy/.env && echo "TB_DB_URL=postgresql://trialbox:${WF_PW}@db:5432/trialbox_wf" >> deploy/.env
# REHEARSAL (D-726): the box says TEST
# D-887 (the integrator's (i)): it says VALIDATION, where D3 stays on the box (D-823), with the mark and TB_REHEARSAL=1
if [ "$REHEARSAL" = 1 ]; then
  RH_ENV="$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
  case "$RH_ENV" in
    ""|DEV|TEST) ;;
    VALIDATION) [ -f deploy/site/rehearsal.json ] || die "--rehearsal: the answers make this box VALIDATION with no rehearsal mark: a rehearsal box is made by --rehearsal" ;;
    *) die "--rehearsal: the answers make this box $RH_ENV: a rehearsal box is VALIDATION" ;;
  esac
  sed -i '/^TB_ENV=/d; /^TB_REHEARSAL=/d' deploy/.env && printf 'TB_ENV=VALIDATION\nTB_REHEARSAL=1\n' >> deploy/.env
fi
# ---- end of REHEARSAL (D-726): the box says TEST
# ENVIRONMENT (D-837): --environment, or a TB_ENV written before the wizard rewrote deploy/.env; never changed
# silently (a pre-written VALIDATION was lost and the D-127 default below made the box PRODUCTION)
NOW_ENV="$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1 | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')"
if [ -n "$ENVIRONMENT" ]; then
  ENVIRONMENT="$(printf '%s' "$ENVIRONMENT" | tr '[:lower:]' '[:upper:]')"
  case "$ENVIRONMENT" in DEV|TEST|VALIDATION|PRODUCTION) ;; *) die "--environment must be DEV, TEST, VALIDATION or PRODUCTION, not $ENVIRONMENT" ;; esac
  [ "$REHEARSAL" != 1 ] || [ "$ENVIRONMENT" = VALIDATION ] || die "--rehearsal makes a VALIDATION box, not $ENVIRONMENT"
  [ -z "$NOW_ENV" ] || [ "$NOW_ENV" = "$ENVIRONMENT" ] \
    || die "deploy/.env says TB_ENV=$NOW_ENV and --environment says $ENVIRONMENT: a box's environment is not changed by an install"
  sed -i '/^TB_ENV=/d' deploy/.env && echo "TB_ENV=$ENVIRONMENT" >> deploy/.env
elif [ -z "$NOW_ENV" ] && [ -n "$PRE_ENV" ]; then
  sed -i '/^TB_ENV=/d' deploy/.env && echo "TB_ENV=$PRE_ENV" >> deploy/.env
  echo "    TB_ENV=$PRE_ENV kept (written in deploy/.env before the settings wizard)"
fi
# ---- end of ENVIRONMENT
# D-127 (review F-06): a box is PRODUCTION unless the operator set TB_ENV on purpose (timers, mail, REDCap, gates)
grep -q '^TB_ENV=' deploy/.env || echo "TB_ENV=PRODUCTION" >> deploy/.env
TB_ENV_SITE="$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1)"
envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }
envset() { sed -i "/^$1=/d" deploy/.env && printf '%s=%s\n' "$1" "$2" >> deploy/.env; }
# HOST PROFILE (D-837): TB_HOST_PROFILE=poc, a proof of concept or validation run on a plain VM: the host-facility
# checks (TPM seal, LUKS, egress table, systemd units, firewall, SSH, cron) WARN and are listed, here, in
# check_host.sh and in doctor. Never on PRODUCTION. It sets TB_SYSTEMD's default to 0 (no units on such a VM)
HOST_PROFILE="${TB_HOST_PROFILE:-$(envget TB_HOST_PROFILE)}"; HOST_PROFILE="${HOST_PROFILE:-site}"
case "$HOST_PROFILE" in
  site) ;;
  poc)
    [ "$TB_ENV_SITE" != PRODUCTION ] \
      || die "TB_HOST_PROFILE=poc is never a PRODUCTION box: install with --environment VALIDATION (or TEST), or without the profile"
    envset TB_HOST_PROFILE poc
    TB_SYSTEMD="${TB_SYSTEMD:-0}"; export TB_SYSTEMD
    echo "    host profile poc ($TB_ENV_SITE): WARN, not FAIL, for the TPM seal, LUKS, the egress table, the systemd units, the firewall, SSH and cron (listed by the host check)"
    ;;
  *) die "TB_HOST_PROFILE must be site or poc, not '$HOST_PROFILE'" ;;
esac
# ---- end of HOST PROFILE
# D-726: what only a rehearsal box may use (the model stand-ins, an unmeasured card's trial boot)
rehearsal_only() {  # D-887: TEST with TB_REHEARSAL=1, or VALIDATION with TB_REHEARSAL=1 and the mark file
  [ "$(envget TB_REHEARSAL)" = 1 ] && { [ "$TB_ENV_SITE" = TEST ] || { [ "$TB_ENV_SITE" = VALIDATION ] && [ -f deploy/site/rehearsal.json ]; }; } \
    || die "$1: only on a rehearsal box (TB_REHEARSAL=1 on TEST, or on VALIDATION with deploy/site/rehearsal.json: deploy/install.sh --rehearsal); this box is $TB_ENV_SITE"
}
# D-726 (review F1): the stand-ins are known by what the file says, wherever it lies (a copy, the release tree's own)
is_standins() {
  grep -qx 'x-trialbox-rehearsal-standins: true' "$1"
}
# T-632 (OPS-011): the feed folder. The wizard wrote TB_SOURCE_DIR (the host folder) and TB_SOURCE_MOUNT (the
# settings' data_source.path); compose mounts the one at the other. PRODUCTION never falls back to the test fixture
SRC_DIR="$(envget TB_SOURCE_DIR)"
if [ -z "$SRC_DIR" ]; then
  [ "$TB_ENV_SITE" != PRODUCTION ] || die "no feed folder: set TB_SOURCE_DIR in deploy/.env (the host folder the HIS export lands in; the settings wizard asks for it, RUNBOOK §1 step 3)"
  echo "    feed folder: none set ($TB_ENV_SITE): the synthetic fixture is mounted"
else
  case "$SRC_DIR" in /*) SRC_ABS="$SRC_DIR" ;; *) SRC_ABS="$ROOT/deploy/${SRC_DIR#./}" ;; esac
  case "$SRC_ABS" in "$ROOT"/deploy/site/*) mkdir -p "$SRC_ABS" ;; esac   # the default ./site/feed is made here
  [ -d "$SRC_ABS" ] || die "the feed folder $SRC_DIR (TB_SOURCE_DIR) is not a folder on this host: mount the HIS export there first"
  echo "    feed folder: $SRC_ABS -> $(envget TB_SOURCE_MOUNT) in the adapter"
fi
# T-632 (OPS-013): TLS on. The console is reached only at https://TB_TLS_HOSTNAME through Caddy (RUNBOOK §12)
TLS_HOST="$(envget TB_TLS_HOSTNAME)"
if [ -z "$TLS_HOST" ] && [ "$YES" != 1 ] && [ -t 0 ]; then
  printf '  The console'"'"'s DNS name for https (from hospital IT, e.g. trialbox.hospital.tw): '; read -r TLS_HOST
  [ -z "$TLS_HOST" ] || envset TB_TLS_HOSTNAME "$TLS_HOST"
fi
if [ -z "$TLS_HOST" ]; then
  [ "$TB_ENV_SITE" != PRODUCTION ] || die "no TLS host name: a PRODUCTION box runs only behind https. Put TB_TLS_HOSTNAME (and TB_TLS_MODE) in deploy/.env or the answers file (tls_hostname), then re-run (RUNBOOK §12)"
  echo "    TLS: off ($TB_ENV_SITE, no TB_TLS_HOSTNAME): the console stays on 127.0.0.1"
else
  grep -q '^TB_TLS_MODE=.' deploy/.env || envset TB_TLS_MODE internal
  # D-887: reached at https only, so the session cookie is Secure in every environment (doctor secure_cookie FAILs it
  # off on VALIDATION); a value the site wrote is kept
  grep -q '^TB_CONSOLE_SECURE_COOKIE=' deploy/.env || envset TB_CONSOLE_SECURE_COOKIE 1
fi
# H-48 (D-1328): TB_TLS_OLD_CLIENTS, the one setting that relaxes 443 for a hospital's old client: off (the default) or
# cbc (also the four TLS 1.2 ECDHE AES-CBC-SHA suites). Any other value is refused before Caddy reads it (RUNBOOK §12)
# the value compose gives Caddy: an exported TB_TLS_OLD_CLIENTS wins over deploy/.env, as compose does; quotes dropped
TLS_OLD="${TB_TLS_OLD_CLIENTS-$(envget TB_TLS_OLD_CLIENTS)}"; TLS_OLD="${TLS_OLD//[\"\']/}"; TLS_OLD="${TLS_OLD:-off}"
case "$TLS_OLD" in
  off) ;;
  cbc) [ -z "$TLS_HOST" ] || echo "    TLS: TB_TLS_OLD_CLIENTS=cbc: 443 also serves TLS 1.2 ECDHE AES-CBC-SHA to old clients (audited; doctor and the TLS check name it)" ;;
  *) die "TB_TLS_OLD_CLIENTS must be off or cbc, not '$TLS_OLD': fix it in deploy/.env (RUNBOOK §12), then re-run" ;;
esac
# SAE-MAILBOX (D-736): the trial office is told at once when a serious adverse event is entered (LIFE-007)
SAE_TO="$(envget TB_SAE_OFFICE_MAILBOX)"
[ -n "$SAE_TO" ] || SAE_TO="${TB_SAE_OFFICE_MAILBOX:-}"   # exported for this run
if [ -z "$SAE_TO" ] && [ "$YES" != 1 ] && [ -t 0 ]; then
  printf '  The trial office'"'"'s mailbox, told at once when a serious adverse event is entered (e.g. trial-office@hospital.tw): '; read -r SAE_TO || SAE_TO=""
fi
SAE_TO="$(printf '%s' "$SAE_TO" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
case "$SAE_TO" in \"*\") SAE_TO="${SAE_TO#\"}"; SAE_TO="${SAE_TO%\"}" ;; \'*\') SAE_TO="${SAE_TO#\'}"; SAE_TO="${SAE_TO%\'}" ;; esac
if [ -n "$SAE_TO" ]; then
  printf '%s\n' "$SAE_TO" | grep -Eqx "[A-Za-z0-9._%+-][A-Za-z0-9._%+'-]*@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+" \
    || die "TB_SAE_OFFICE_MAILBOX $SAE_TO is not one mail address (for example trial-office@hospital.tw)"
  envset TB_SAE_OFFICE_MAILBOX "$SAE_TO"
  echo "    SAE office mailbox: $SAE_TO"
elif [ "$TB_ENV_SITE" = PRODUCTION ] && [ "${TB_BOX:-0}" != 1 ] && [ "${SETTINGS_NEW:-0}" = 1 ]; then
  die "no SAE office mailbox: when a serious adverse event is entered the trial office must be told at once (a sponsor report can be due within 24 h). Put TB_SAE_OFFICE_MAILBOX in deploy/.env or sae_office_mailbox in the answers file, then re-run (RUNBOOK §1)"
else
  echo "install: warning: no SAE office mailbox ($TB_ENV_SITE): nobody is mailed when a serious adverse event is entered until TB_SAE_OFFICE_MAILBOX is set in deploy/.env (RUNBOOK §1)" >&2
fi
# ---- end of SAE-MAILBOX (D-736): the trial office is told at once when a serious adverse event is entered (LIFE-007)
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
# T-692 (D-473, OD-10): the adapter's and the lake's memory caps from the patient count (the lake's CURRENT snapshot,
# else TB_SITE_PATIENTS) and the measured record deploy/measured/ingest_memory.json; the orchestrator's (H23b-01,
# D-1005) from deploy/measured/orchestrator_memory.json (the size ladder's peaks), written only above the compose
# default; a cap set by hand is kept and `trialbox doctor` (memory_caps) says when it is too small
if command -v python3 >/dev/null; then
  LAKE_HOST="$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_lake-data" 2>/dev/null || true)"
  # D-832: the die hangs on the pipe (under pipefail a failing pipe ended the script before a PIPESTATUS line)
  python3 -m tools.trialbox.memcaps --env-file deploy/.env ${LAKE_HOST:+--lake "$LAKE_HOST"} --write 2>&1 | indent || die "the memory caps could not be sized (above): set TB_MEM_ADAPTER, TB_MEM_LAKE and TB_MEM_ORCH in deploy/.env, then re-run"
else
  echo "install: warning: no python3: TB_MEM_ADAPTER, TB_MEM_LAKE and TB_MEM_ORCH keep the compose defaults (doctor memory_caps checks them)" >&2
fi
# T-703 (D-751): PostgreSQL's buffers, WAL, maintenance memory, /dev/shm and idle-transaction limit from TB_MEM_DB;
# a value set by hand is kept and `trialbox doctor` (postgres_memory) fails on the defaults of a large host
if command -v python3 >/dev/null; then
  python3 -m tools.trialbox.pgsize --env-file deploy/.env --write 2>&1 | indent || die "PostgreSQL could not be sized (above): set the TB_PG_* values in deploy/.env, then re-run"
fi
chmod 600 deploy/.env
# the services run as tb (uid and gid 10001, deploy/docker/python.Dockerfile) and read settings.yaml read-only: a root
# 0600 file stopped every service at start (found by the box rehearsal, D-176). Group tb reads it, nobody else.
chown "$(id -u):10001" deploy/settings.yaml && chmod 640 deploy/settings.yaml
export TB_SETTINGS_FILE="./settings.yaml"
# D-888: in deploy/.env too, so every start mounts it (the systemd unit, an update, an operator's docker compose up)
envset TB_SETTINGS_FILE "./settings.yaml"
# ---- PINS: the models this box serves, pinned to the release's weights before anything starts on them
if [ "$MODE" = gpu ]; then
  # D-142 (review R-01): pin the profile's deployed pair from the site's own weights, which must be the release
  # models/registry.yaml expects (D-358), as candidate; PRODUCTION routes it once `trialbox eval qualify` passes and
  # `pin_model --promote` makes it champion (until then: champion_unqualified / no_eligible_build). Pins are kept.
  mkdir -p deploy/site
  for v in JUDGE_MODEL_DIR JUDGE_MODEL JUDGE_CHAT_TEMPLATE VERIFIER_MODEL_DIR VERIFIER_MODEL; do  # as compose reads them from deploy/.env
    val="$(sed -n "s/^$v=//p" deploy/.env | tail -1)"; [ -z "$val" ] || export "$v=$val"
  done
  say "pinning the $GPU model pair from deploy/models (tools/pin_model.py --install)"
  # D-835: as the installer's own user (the image user 10001 cannot write a root-owned deploy/site, and a failed pin
  # was only a warning: lane G's box went on with no model pinned); a pin that fails stops the install
  alive_start "hashing the model weights"
  # D-887: the box (TB_ENV, TB_REHEARSAL) goes to the pin, which pins the rehearsal media's placeholders on a
  # rehearsal box only, from a rehearsal bundle (deploy/updates/installed.json), every folder a placeholder
  tree_args
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d" ${TREE_D[@]+"${TREE_D[@]}"} -e JUDGE_MODEL_DIR -e JUDGE_MODEL -e JUDGE_CHAT_TEMPLATE -e VERIFIER_MODEL_DIR -e VERIFIER_MODEL \
    -e TB_ENV="$TB_ENV_SITE" -e TB_REHEARSAL="$(envget TB_REHEARSAL)" "$IMAGE_PY" \
    python -m tools.pin_model --install "$GPU" --models-root /d/models --out /d/site/registry.site.yaml \
    || die "a model of the $GPU pair is not pinned (see above): put its weights in deploy/models (RUNBOOK §8), then run install again"
  alive_stop
else
  # D-1066 (D-998, the owner's ruling): a box without a GPU is a product form (a feasibility-only site that may add a
  # GPU later). Its embed service runs the embedder on the CPU and refuses to start in PRODUCTION without a pin, so
  # the embedder alone is pinned from the bundle's weights (every site bundle carries them, tools/release.py)
  mkdir -p deploy/site
  for v in EMBED_MODEL_DIR EMBED_MODEL; do  # as compose reads them from deploy/.env
    val="$(sed -n "s/^$v=//p" deploy/.env | tail -1)"; [ -z "$val" ] || export "$v=$val"
  done
  say "pinning the embedder from deploy/models (tools/pin_model.py --install-embedder)"
  alive_start "hashing the embedder's weights"
  tree_args
  if ! docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy:/d" ${TREE_D[@]+"${TREE_D[@]}"} -e EMBED_MODEL_DIR -e EMBED_MODEL \
      -e TB_ENV="$TB_ENV_SITE" "$IMAGE_PY" \
      python -m tools.pin_model --install-embedder --models-root /d/models --out /d/site/registry.site.yaml; then
    alive_stop
    if [ "$TB_ENV_SITE" = PRODUCTION ]; then
      die "the embedder is not pinned (see above): a PRODUCTION box without a GPU needs it (D-1066); install from a bundle that carries embedder/, then run install again"
    fi
    echo "install: warning: the embedder is not pinned; on a $TB_ENV_SITE box the embed service runs its hash stub" >&2
  fi
  alive_stop
fi
if ls deploy/site/registry.site.yaml >/dev/null 2>&1; then
  # SEC-64: every pinned build's weights must still hash to its pin, or the box does not start on them
  say "checking the pinned model weights (tools/pin_model.py --verify-all)"
  alive_start "checking the model weights"
  tree_args
  docker run --rm -v "$ROOT/deploy:/d:ro" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" \
    python -m tools.pin_model --verify-all /d/models --out /d/site/registry.site.yaml \
    || die "model weights do not match their pins (see above): restore the pinned files or re-pin with tools/pin_model.py (RUNBOOK §8)"
  alive_stop
else
  echo "install: note: no model pinned yet (deploy/site/registry.site.yaml): the gateway routes nothing to a local model until you run tools/pin_model.py or make spark-e2e (RUNBOOK §8)" >&2
fi
# ---- end of PINS

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
    tree_args
    docker run --rm -v "$ROOT/deploy:/d:ro" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" python -m tools.serving_config measured "$GPU" "/d/${REC#deploy/}" \
      || die "$REC is not a measurement of the $GPU profile on its own card (see above)"
    echo "    $GPU profile measured: $REC"
  elif [ -z "$TIER" ] && [ "${TB_ACCEPT_UNMEASURED_GPU:-0}" = 1 ]; then
    rehearsal_only "TB_ACCEPT_UNMEASURED_GPU=1 (an unmeasured card's trial boot)"
    echo "install: warning: $GPU profile not yet measured on this card (TB_ACCEPT_UNMEASURED_GPU=1): capture deploy/site/serving_config.$GPU.json after the first boot (RUNBOOK §8)" >&2
  else
    die "the $GPU profile has no measurement on its own card (deploy/site/ or deploy/measured/serving_config.$GPU.json). For a first trial boot re-run as a rehearsal box (TB_COMPOSE_OVERRIDE= deploy/install.sh <bundle> --gpu $GPU --rehearsal), then capture the record (RUNBOOK §1)"
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
if [ -n "$TLS_HOST" ]; then
  # the certificate, its key and the host name are checked before Caddy uses them (console.cli check-tls); the
  # hospital's files are mounted where deploy/.env names them
  say "TLS: https://$TLS_HOST ($(envget TB_TLS_MODE))"
  TLS_MOUNT=()
  for v in TB_TLS_CERT_FILE TB_TLS_KEY_FILE; do f="$(envget "$v")"; [ -z "$f" ] || TLS_MOUNT+=(-v "$f:$f:ro"); done
  docker run --rm -e TB_ENV="$TB_ENV_SITE" -e TB_TLS_MODE="$(envget TB_TLS_MODE)" -e TB_TLS_HOSTNAME="$TLS_HOST" \
    -e TB_TLS_CERT_FILE="$(envget TB_TLS_CERT_FILE)" -e TB_TLS_KEY_FILE="$(envget TB_TLS_KEY_FILE)" \
    ${TLS_MOUNT[@]+"${TLS_MOUNT[@]}"} --user 0 "$IMAGE_PY" python -m console.cli check-tls 2>&1 \
    | indent || die "the TLS settings do not pass (FAIL above): fix TB_TLS_* in deploy/.env (RUNBOOK §12), then re-run"
  COMPOSE+=(-f deploy/docker-compose.identity.yml); FILES="$FILES:$ROOT/deploy/docker-compose.identity.yml"
fi
if [ "${TB_BOX:-0}" = 1 ]; then  # T-729: the console's first-run folder (box-install.sh makes it, tmpfs)
  COMPOSE+=(-f deploy/docker-compose.box.yml); FILES="$FILES:$ROOT/deploy/docker-compose.box.yml"
fi
LOCK_FILES="$FILES"
# ANCHOR-GATE (10K-4, D-1390): the anchor folder is judged before anything mounts it (the read probe below, the
# console), whatever TB_BOX says: the rule for a folder the console may be given (finish-check --anchor-only)
if command -v python3 >/dev/null; then
  finish_check "the audit anchor folder is not given to the console: nothing was mounted, the stack was not started" --anchor-only
fi
# ---- end of ANCHOR-GATE
# ANCHOR-MOUNT (D-638): the audit page checks the chain against the signed heads of the anchor folders, which are
# host paths: a compose file of the installer's own mounts each into the console, read-only, and gives the console
# the name (the shipped compose file clears it). No folder set: no file, and an earlier one is taken away. The
# command prints the file, then each folder; a folder that is not there, or that the console's user cannot read
# (asked of the console's own image), stops the install: the page would say "no signed heads" on a healthy chain
if command -v python3 >/dev/null; then
  ANCHOR_OUT="$(python3 -m tools.trialbox anchors-compose --deploy "$ROOT/deploy")" \
    || die "TB_AUDIT_ANCHOR_TARGETS in deploy/.env names a folder that cannot be mounted (above)"
  if [ -n "$ANCHOR_OUT" ]; then
    ANCHOR_FILE="${ANCHOR_OUT%%$'\n'*}"
    while IFS= read -r anchor; do
      docker run --rm --network none -v "$anchor:/anchor:ro" "$IMAGE_PY" sh -c \
        'test -r /anchor && test -x /anchor && for d in heads keys; do [ ! -e "/anchor/$d" ] || { test -r "/anchor/$d" && test -x "/anchor/$d"; } || exit 1; done' </dev/null \
        || die "TB_AUDIT_ANCHOR_TARGETS: the console's user cannot read $anchor (or its heads/ or keys/): the audit page would find no signed head. Make the folder readable (chmod a+rx), then re-run"
    done <<< "${ANCHOR_OUT#*$'\n'}"
    COMPOSE+=(-f "$ANCHOR_FILE"); FILES="$FILES:$ANCHOR_FILE"
  fi
elif [ -n "$(envget TB_AUDIT_ANCHOR_TARGETS)" ]; then
  echo "install: note: no python3 on this host: the anchor folders are not mounted into the console, so the audit page will not check the signed heads (D-638)" >&2
fi
if [ -n "${TB_COMPOSE_OVERRIDE:-}" ]; then  # D-176: the rehearsal's model stand-ins (or a site's own override)
  [ -f "$TB_COMPOSE_OVERRIDE" ] || die "TB_COMPOSE_OVERRIDE: no such file $TB_COMPOSE_OVERRIDE"
  OVR="$(cd "$(dirname "$TB_COMPOSE_OVERRIDE")" && pwd)/$(basename "$TB_COMPOSE_OVERRIDE")"
  # every later compose command (as root: update, secrets rotate) reads it: only its owner (root or the installer)
  # may change it, and it must stay where it is
  [ "$(stat -c %u "$OVR")" = 0 ] || [ "$(stat -c %u "$OVR")" = "$(id -u)" ] || die "TB_COMPOSE_OVERRIDE: $OVR is not owned by root or $(id -un)"
  [ $((0$(stat -c %a "$OVR") & 022)) = 0 ] || die "TB_COMPOSE_OVERRIDE: $OVR is writable by group or others (chmod go-w)"
  is_standins "$OVR" && rehearsal_only "the model stand-ins ($OVR says x-trialbox-rehearsal-standins)"
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
# FINISH-GATE (10K-4, D-1390): before the stack starts, unless TB_BOX=1 (deploy/box-install.sh checks after the
# set-up): in PRODUCTION (read as the tool reads TB_ENV) a backup target shown to be off the box and the hospital's
# audit share as the anchor folder. By here this run has loaded the bundle (on a box that was running, apply_update.sh
# has applied the release and restarted the stack, as trialbox update does) and written its settings; a refusal says so
if [ "${TB_BOX:-0}" != 1 ]; then
  if command -v python3 >/dev/null; then
    finish_check "not finished: the bundle this run loaded stays (on a box that was already running, its release is applied and running, as after trialbox update) and the settings it wrote stay; the install's own start, units, cron and checks were not run. Change what the lines above name in deploy/.env, then re-run this command: it goes on from here"
  elif [ "$(printf '%s' "$TB_ENV_SITE" | tr -d "\"' \r\t" | tr '[:lower:]' '[:upper:]')" = PRODUCTION ]; then
    die "no python3 on this host: a PRODUCTION install cannot check its backup target and audit anchor folder (RUNBOOK §5)"
  fi
fi
# ---- end of FINISH-GATE
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
  # OPS-004b (D-574): what the stack will run, with the box's overrides applied; an image no service runs (a model
  # server a compose override replaces) is not asked for
  USED_IMAGES="$("${COMPOSE[@]}" config --images | sort -u)"
  python3 -m tools.image_pins resolve --deploy deploy --files "$FILES" --used "$USED_IMAGES" 2>&1 | sed 's/^/    /' \
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
# D-620: this release's host-side steps before its stack starts (tools/trialbox/prestart.py), the same command an
# update runs: a step a release adds there is run by a fresh install too. The steps are safe to run again.
if command -v python3 >/dev/null; then
  python3 -m tools.trialbox pre-start --deploy "$ROOT/deploy" 2>&1 | sed 's/^/    /' \
    || die "a start-up step of this release failed (pre-start above)"
else
  echo "    note: no python3 on this host: the release's start-up steps (tools.trialbox pre-start) were not run" >&2
fi
# PROJECT-CLEANUP (F-19): after the release's checks above passed, before anything uses the project's network. Only a
# project proven to be this install's (tools/trialbox/project_check.py) with a failed container (created, dead, exited
# non-zero, unhealthy) is taken down, with the same overlays as up and every profile of an earlier attempt. A paused,
# starting or exit-0 container is a working box's: kept. Refused while an update or the watchdog's maintenance flag is
# there (review 2 of #1305, M-1). Anything else is refused or kept.
if command -v python3 >/dev/null; then
  CLEANUP="$(python3 -m tools.trialbox.project_check --deploy "$ROOT/deploy" -- "${COMPOSE[@]}" --profile '*')" \
    || die "the project cleanup was refused (above): nothing was removed"
else
  CLEANUP=none
  [ -z "${COMPOSE_PROJECT_NAME:-}" ] || [ "$COMPOSE_PROJECT_NAME" = trialbox ] \
    || die "COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME in this shell is not this install's project: unset it, then re-run"
  echo "    note: no python3 on this host: the project is not proven to be this install's, so nothing is cleaned up" >&2
fi
if [ "$CLEANUP" = down ]; then
(
  COMPOSE+=(--profile '*')
  "${COMPOSE[@]}" down --remove-orphans
) || die "project cleanup failed / 專案清理失敗 / プロジェクトのクリーンアップに失敗しました"
fi
# ---- end of PROJECT-CLEANUP
# T-612 (DATA-004): the site keys are made here and nowhere else. A key already in the secrets volume is kept; the
# ingest refuses a night whose key is missing or is not the one the box's pseudonyms were made with
say "site keys (made once, never replaced)"
"${COMPOSE[@]}" run --rm --no-deps -T adapter python -m adapter.cli keys-init | sed 's/^/    /' \
  || die "the site keys could not be made or read (above): put the site's keys back from the backup (RUNBOOK §5)"
# T-634 (D-408; OPS-043): sealed at once, before any service opens them. VALIDATION and PRODUCTION always; a DEV or TEST
# box only when it has deploy/site/hardening.conf or TB_KEK_BACKEND asks for it (D-887). The KEK's back end is the site's (TB_KEK_BACKEND in the installer's
# environment, else hardening.conf's KEK_BACKEND, default tpm; D-836); the
# host check FAILs a plain site key in VALIDATION and PRODUCTION
HB_CONF="$ROOT/deploy/site/hardening.conf"
if [ "${TB_BOX_DEFER_SEAL:-0}" = 1 ]; then
  echo "    site keys: sealed at the box's apply step, under the owner's passphrase (box-install.sh, T-729)"
elif [ "$HOST_PROFILE" = poc ] && [ -z "${TB_KEK_BACKEND:-}" ] \
    && ! { command -v systemd-creds >/dev/null 2>&1 && systemd-creds has-tpm2 >/dev/null 2>&1; }; then
  # D-837: a plain VM has no usable TPM; the passphrase back end seals the keys when it is asked for
  echo "    site keys: not sealed (host profile poc, no usable TPM; TB_KEK_BACKEND=passphrase with TB_KEK_PASSPHRASE seals them); the host check lists it"
elif [ "$TB_ENV_SITE" = PRODUCTION ] || [ "$TB_ENV_SITE" = VALIDATION ] || [ -f "$HB_CONF" ] || [ -n "${TB_KEK_BACKEND:-}" ]; then
  say "site keys sealed under the KEK (deploy/hardening/seal_keys.sh)"
  [ "$(id -u)" = 0 ] || die "sealing the site keys needs root (the secrets volume, the TPM): run the installer as root"
  SEC_DIR="${TB_SECRETS_HOST_DIR:-$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets" 2>/dev/null)}"
  TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh --secrets "$SEC_DIR" --conf "$HB_CONF" \
    || die "the site keys are not sealed (above): for TB_KEK_BACKEND=passphrase without a usable TPM, use the hidden-input example in deploy/install.sh --help; docs/security/01-the-host.md"
fi
# D-378: the services' database roles, on a new volume (db-init made them) and an older one alike (idempotent)
"${COMPOSE[@]}" up -d --pull "$PULL" --wait db || die "the database did not start (docker compose logs db)"
# D-624: this release's steps once the database is up (tools/trialbox/prestart.py DB_STEPS: the roles of D-378, the
# schemas no service owns of D-486, whatever a later release adds), by the same command an update runs and with the
# compose files and profile an update uses (COMPOSE_FILE and COMPOSE_PROFILES in deploy/.env, written above)
if command -v python3 >/dev/null; then
  TB_INSTALL_PULL="$PULL" python3 -m tools.trialbox db-up --deploy "$ROOT/deploy" 2>&1 | sed 's/^/    /' \
    || die "a database step of this release failed (db-up above; docker compose logs db)"
else
  echo "    note: no python3 on this host: the release's database steps (tools.trialbox db-up) were not run; the roles and the schemas are set by the installer" >&2
  "${COMPOSE[@]}" exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh \
    || die "the database roles could not be set (docker compose logs db)"
  # D-486 (T-718): the schemas no service owns (edc), by the box's admin; the admin's URL goes in the environment,
  # not on the command line
  TB_DB_URL="postgresql://trialbox:${WF_PW}@db:5432/trialbox_wf" "${COMPOSE[@]}" run --rm --no-deps -T -e TB_DB_URL \
    orchestrator python -m orchestrator.migrate | sed 's/^/    /' \
    || die "the schemas of the trial database could not be made (python -m orchestrator.migrate)"
fi
# T-695 (D-752, F-24): the wait for every service healthy, from the compose files' health checks (start period, then
# the retries); the stop, from the longest stop grace. Without PyYAML on the host, the waits of before (900 s, 300 s).
BOOT_WAIT="$(python3 -m tools.trialbox.bootwait --deploy deploy 2>/dev/null)" || BOOT_WAIT=900
STOP_WAIT="$(python3 -m tools.trialbox.bootwait --deploy deploy --stop 2>/dev/null)" || STOP_WAIT=290
alive_start "waiting for every service to be healthy (up to ${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT} s)"
"${COMPOSE[@]}" up -d --pull "$PULL" "${UP_EXTRA[@]}" --wait --wait-timeout "${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT}" \
  || { alive_stop; "${COMPOSE[@]}" ps; die "the stack did not become healthy (docker compose logs)"; }
alive_stop
if [ "$MODE" = gpu ]; then
  # D-177: the model servers must serve the names the site pinned and refuse calls without the key; otherwise the
  # gateway would get 404 or 401 on every call and the box would screen nothing (doctor check "serving")
  say "model servers: pinned served names and key (trialbox doctor --serving)"
  set +e
  tree_args
  docker run --rm --network trialbox-model-net --env-file deploy/.env -v "$ROOT/deploy:/app/deploy:ro" ${TREE_APP[@]+"${TREE_APP[@]}"} \
    -e TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key --user "$(id -u):$(id -g)" "$IMAGE_PY" python -m tools.trialbox doctor --serving | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  set -e
  [ "$rc" = 0 ] || die "the model servers do not match the pins or the key (FAIL above): the stack is up but every model call would be refused; fix deploy/.env (JUDGE_MODEL, VERIFIER_MODEL), the key (python3 -m tools.trialbox secrets rotate --service model) or re-pin (RUNBOOK §8), then re-run"
fi
EGRESS_OK=0
if [ "$(id -u)" = 0 ] && [ -x deploy/network.sh ]; then
  say "egress rules"
  if deploy/network.sh apply; then EGRESS_OK=1
  else echo "install: warning: egress rules not applied (deploy/network.sh apply)" >&2; fi
fi
# T-634 (D-408; OPS-052): the input firewall (443 from the clinic ranges only) and SSH, from the site's
# deploy/site/hardening.conf; without it a VALIDATION or PRODUCTION box fails the host check at the end
if [ "$(id -u)" = 0 ] && [ -f "$HB_CONF" ]; then
  say "host baseline: input firewall and SSH (deploy/hardening/apply.sh)"
  sh deploy/hardening/apply.sh --conf "$HB_CONF" ${HB_OVER[@]+"${HB_OVER[@]}"} all || die "the host baseline could not be applied (above)"
elif [ ! -f "$HB_CONF" ]; then
  echo "install: warning: no deploy/site/hardening.conf (the clinic ranges, SSH, the KEK back end): copy deploy/hardening/hardening.example.conf, fill it in with hospital IT, re-run" >&2
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
      sed -e "s#@TB_ROOT@#$ROOT#g" -e "s#@TB_BOOT_WAIT@#${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT}#g" \
          -e "s#@TB_UP_EXTRA@#${UP_EXTRA[*]}#g" \
          -e "s#@TB_BOOT_LIMIT@#$(( ${TB_INSTALL_UP_TIMEOUT:-$BOOT_WAIT} + 300 ))#g" \
          -e "s#@TB_STOP_LIMIT@#$(( STOP_WAIT + 10 ))#g" "$unit" > "$SYSTEMD_DIR/$(basename "$unit")"
      chmod 644 "$SYSTEMD_DIR/$(basename "$unit")"
    done
    systemctl daemon-reload
    # trialbox-weights.timer (T-677, D-393): the weights against their pins before the night's runs
    # trialbox-ops.timer (NEW-OPS-8, D-561): the runner that writes the host's health facts every minute and runs
    # the Operations page's requests; without it the health line is red (OPS-009)
    systemctl enable trialbox-egress.service trialbox.service trialbox-egress-refresh.timer trialbox-watchdog.timer \
      trialbox-egress-watch.service trialbox-weights.timer trialbox-ops.timer >/dev/null 2>&1 \
      || die "the systemd units could not be enabled (systemctl status trialbox-egress trialbox)"
    systemctl start trialbox.service
    systemctl start trialbox-egress-refresh.timer trialbox-watchdog.timer trialbox-weights.timer \
      trialbox-egress-watch.service trialbox-ops.timer >/dev/null 2>&1 || true
    echo "    enabled: trialbox-egress, trialbox, trialbox-egress-refresh.timer, trialbox-watchdog.timer, trialbox-weights.timer, trialbox-egress-watch, trialbox-ops.timer"
  else
    echo "install: warning: systemd units not enabled: the egress rules were not applied (no state file for a boot)" >&2
  fi
fi
CRON_DIR="${TB_CRON_DIR:-/etc/cron.d}"   # T-632: both cron files, or no finished install in PRODUCTION
CAN_CRON=0; { [ "$(id -u)" = 0 ] || [ -n "${TB_CRON_DIR:-}" ]; } && [ -d "$CRON_DIR" ] && command -v python3 >/dev/null && CAN_CRON=1
if [ "$CAN_CRON" = 1 ]; then
  # D-138: every night collect yesterday's service logs, prune by settings.retention, copy the audit to its archive
  # NEW-STD-2 (D-562): then the night's signed head of the audit chain into TB_AUDIT_ANCHOR_TARGETS, whatever the
  # first command returned; `trialbox doctor` (audit_heads) FAILs when no folder is set or the newest head is old
  printf '%s\n' "SHELL=/bin/sh" "20 0 * * * root cd $ROOT && { python3 -m tools.trialbox logs daily; python3 -m tools.trialbox audit-sign; } >> /var/log/trialbox-retention.log 2>&1" \
    > "$CRON_DIR/trialbox-retention" && chmod 644 "$CRON_DIR/trialbox-retention"
  echo "    log retention and the signed audit head: $CRON_DIR/trialbox-retention (00:20 daily)"
elif [ "$TB_ENV_SITE" = PRODUCTION ]; then
  die "the cron files cannot be installed (needs root, /etc/cron.d and python3): run the installer as root"
fi
if [ "$(id -u)" = 0 ] && [ -d /etc/logrotate.d ]; then
  # D-389 (OPS-037): /var/log/trialbox-*.log (the retention and backup cron logs) rotate weekly, 53 kept
  install -m 644 deploy/logrotate/trialbox /etc/logrotate.d/trialbox && echo "    host logs: /etc/logrotate.d/trialbox"
fi
# D-138: the site's one-page network, port and secret sheet, from the compose files this box runs
SHEET_MOUNT=(); SHEET_FILES="$(echo "$FILES" | sed "s#$ROOT/deploy/#deploy/#g")"
if [ -n "${OVR:-}" ]; then  # the override is outside deploy/: mount it where the sheet tool looks
  SHEET_MOUNT=(-v "$OVR:/app/deploy/compose-override.yml:ro"); SHEET_FILES="${SHEET_FILES//$OVR/deploy/compose-override.yml}"
fi
FAILS=()   # T-632: a FAIL here does not stop the install half-way; the install ends with exit 1 and the list
# HW-003 (D-569): the shipped qualification record. The pair was pinned as candidate, and PRODUCTION routes a
# champion only. When a record in deploy/qualification/<profile>/ qualified exactly these weights, this model
# server image and this chat template, the pair is promoted; the promotion is kept only when the canary passes on
# this box through the gateway. Until then it waits (deploy/site/shipped-promotion.pending.json): an install that
# is interrupted here runs the canary the next time, and a failed canary puts the pair back to candidate.
if [ "$MODE" = gpu ] && [ -f deploy/site/registry.site.yaml ]; then
  say "model pair: the shipped qualification record (tools/pin_model.py --promote-shipped)"
  # on a box installed from a bundle these two are links into ../current (tools/host_tree.py): resolved here,
  # because a link out of the mounted folder dangles inside the container
  QUAL_DIR="$(readlink -f deploy/qualification 2>/dev/null || true)"; [ -d "$QUAL_DIR" ] || QUAL_DIR="$ROOT/deploy/site"
  LOCK_FILE="$(readlink -f deploy/images.lock 2>/dev/null || true)"
  pin_tool() {
    docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT/deploy/site:/d/site" -v "$QUAL_DIR:/q:ro" ${LOCK_FILE:+-v "$LOCK_FILE:/images.lock:ro"} "$IMAGE_PY" \
      python -m tools.pin_model "$@" --out /d/site/registry.site.yaml 2>&1 | sed 's/^/    /'
    return "${PIPESTATUS[0]}"
  }
  set +e
  pin_tool --promote-shipped "$GPU" --records /q --images-lock /images.lock
  rc=$?
  if [ "$rc" = 0 ]; then
    canary=1  # anything that keeps the canary from running counts as a canary that did not pass
    if "${COMPOSE[@]}" restart gateway >/dev/null 2>&1 && "${COMPOSE[@]}" up -d --wait gateway >/dev/null 2>&1; then
      say "model pair: the canary on this box (trialbox selftest)"
      if command -v python3 >/dev/null; then
        python3 -m tools.trialbox selftest 2>&1 | sed 's/^/    /'
        canary="${PIPESTATUS[0]}"
      fi
    fi
    if [ "$canary" = 0 ]; then
      pin_tool --confirm-shipped "$GPU"
      # the orchestrator ran its start canary while the pair was candidate: started again, its own canary gate
      # opens on the promoted pair (until then note answers send a patient to review and never exclude)
      "${COMPOSE[@]}" restart orchestrator >/dev/null 2>&1 \
        || FAILS+=("the orchestrator did not restart after the model pair was promoted: docker compose --project-directory deploy restart orchestrator")
    elif pin_tool --demote-pair "$GPU" && "${COMPOSE[@]}" restart gateway >/dev/null 2>&1; then
      FAILS+=("the model pair was promoted on its shipped record but the canary on this box did not pass (above): it is back to candidate and routes nothing; check the card, the driver and the model servers' logs, then re-run (RUNBOOK §11)")
    else
      FAILS+=("the model pair was promoted on its shipped record, the canary on this box did not pass (above), and the pair could NOT be put back: run python3 -m tools.pin_model --demote-pair $GPU, then restart the gateway, before anything is screened (RUNBOOK §11)")
    fi
  elif [ "$rc" = 5 ]; then  # D-887: the rehearsal media's placeholders, never promoted (said above)
    echo "    rehearsal box: the pair is the media's placeholder pins (candidate, never promoted); nothing to qualify"
  elif [ "$rc" != 4 ]; then  # 4: champion before this install and nothing waits for a canary; left as it is
    FAILS+=("the model pair is not qualified on this box (above): no record in deploy/qualification/$GPU matches its weights, model server image and chat template; it routes nothing in PRODUCTION until the release ships one or the pair is qualified here (RUNBOOK §11)")
  fi
  set -e
fi
# T-632 (OPS-014): every overlay renders; an error is shown, never hidden
tree_args
if SHEET_OUT="$(docker run --rm -v "$ROOT/deploy:/app/deploy" ${TREE_APP[@]+"${TREE_APP[@]}"} ${SHEET_MOUNT[@]+"${SHEET_MOUNT[@]}"} --user "$(id -u):$(id -g)" "$IMAGE_PY" \
     python -m tools.network_sheet --files "$SHEET_FILES" --env deploy/.env --out deploy/site/network-sheet 2>&1)"; then
  echo "    network sheet: deploy/site/network-sheet.{en,ja,zh-TW}.{md,html}"
else
  echo "$SHEET_OUT" | tail -5 | sed 's/^/    /' >&2
  FAILS+=("network sheet not written (python -m tools.network_sheet, error above)")
fi
[ -f deploy/secrets/backup.pub ] || echo "install: note: no backup key yet. With hospital IT: python3 -m tools.trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub (RUNBOOK §5); updates refuse to run without a backup" >&2
# T-117b (D-274): the backup cron (/etc/cron.d/trialbox-backup), WAL archiving when the db image carries pgBackRest
# and a target is off the box, and the first backup. PRODUCTION needs an alert route (TB_BACKUP_ALERT_CMD, or
# TB_BACKUP_MAILTO with a mail relay, or on a box with no mail TB_BACKUP_ALERT_ROUTE=health-page, D-735); `trialbox
# doctor` then checks the backup's age and its off-box target
if [ "$CAN_CRON" = 1 ]; then
  say "backups: cron, WAL archiving, first backup"
  set +e
  PYTHONPATH="$PWD/libs${PYTHONPATH:+:$PYTHONPATH}" python3 -m tools.trialbox backup-install --deploy deploy ${TB_CRON_DIR:+--cron-dir "$TB_CRON_DIR"} 2>&1 | sed 's/^/    /'
  rc="${PIPESTATUS[0]}"
  set -e
  if [ "$rc" != 0 ] && [ "${TB_BOX:-0}" != 1 ]; then
    die "the backup schedule is not installed (above): set TB_BACKUP_ALERT_CMD, TB_BACKUP_MAILTO with a mail relay, or on a box with no mail TB_BACKUP_ALERT_ROUTE=health-page in deploy/.env (RUNBOOK §5), then re-run"
  elif [ "$rc" != 0 ]; then
    # OPS-003 (D-566): a box has no alert route yet (no mail relay on a fresh host). A stop here is a stop before
    # the wizard; a FAIL line leaves the stack running, and box-install.sh goes on to the first-run code and
    # installs the schedule again after the owner's answers
    FAILS+=("the backup schedule is not installed yet (above): box-install.sh installs it again after the first-run set-up; if it is still missing, run the command below. 首次設定後會重新安裝備份排程，若仍未安裝，請執行此指令。初期設定後にバックアップスケジュールを再設定します。それでも未設定の場合は次のコマンドを実行してください。 PYTHONPATH=libs python3 -m tools.trialbox backup-install --deploy deploy (RUNBOOK §5)")
  fi
else
  echo "install: warning: the backup cron is not installed (needs root, /etc/cron.d and python3). 備份排程尚未安裝，需要管理員權限、/etc/cron.d 及 python3。バックアップスケジュールは未設定です。管理者権限、/etc/cron.d、python3 が必要です。 PYTHONPATH=libs python3 -m tools.trialbox backup-install --deploy deploy (RUNBOOK §5)" >&2
fi

for f in deploy/refdata/pending/*.tar; do  # D-140: the reference data pack of the install bundle, now the db runs
  [ -f "$f" ] || continue
  # 10G-1 (D-1323): a one-off run, the pack read-only, unpacked on the objects volume (TMPDIR) whose tb-refdata-*
  # leftovers it clears first; named, removed first and after a failure (review D3)
  docker rm -f tb-refdata-load >/dev/null 2>&1 || true
  if "${COMPOSE[@]}" run --rm --no-deps -T --name tb-refdata-load -e TMPDIR=/data/objects -v "$ROOT/$f:/in/refdata.tar:ro" \
    criteria-compiler sh -c 'rm -rf -- "${TMPDIR:?}"/tb-refdata-*; exec "$@"' tb-refdata-load \
    python -m tb_common.refdata load /in/refdata.tar --by deploy/install.sh; then
    # D-187: kept, not deleted: backups leave the pack's rows out and a restore loads it again from here
    mkdir -p deploy/refdata/loaded && mv -f "$f" deploy/refdata/loaded/; echo "    reference data loaded: $(basename "$f" .tar)"
  else
    docker rm -f tb-refdata-load >/dev/null 2>&1 || true
    "${COMPOSE[@]}" run --rm --no-deps -T --name tb-refdata-sweep -e TMPDIR=/data/objects criteria-compiler \
      sh -c 'rm -rf -- "${TMPDIR:?}"/tb-refdata-*' tb-refdata-sweep >/dev/null 2>&1 || true
    # H-58 (H10G1-04): a FAIL line, not a warning: an offline box without its pack has no trials
    FAILS+=("the reference data pack $(basename "$f") was not loaded (python -m tb_common.refdata load, error above): it stays in deploy/refdata/pending; re-run deploy/install.sh to load it again, or tools/apply_update.sh <bundle with refdata>")
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
from tb_common.audit_writer import open_audit
s = json.load(sys.stdin)
open_audit(Path("/data/audit")).append("update.applied", actor="deploy/install.sh", input_sha=s["manifest_sha256"],
    detail={"bundle_id": s["bundle_id"], "signer": s["signer"], "files": s["files"]})
' < "$f" && rm -f "$f" && echo "    audited bundle $(basename "$f" .json)"
done

# H-48 (D-1328): a switch of TB_TLS_OLD_CLIENTS since the last audited one is an event of the box's audit chain,
# sent from the orchestrator's container as update.applied is: update.tls_relaxed (cbc on) or update.tls_strict (back
# to off). deploy/site/tls-old-clients.audited keeps the last audited value; an event not sent stays due (FAILS)
TLS_OLD_MARK=deploy/site/tls-old-clients.audited
TLS_OLD_WAS="$(cat "$TLS_OLD_MARK" 2>/dev/null || true)"; TLS_OLD_WAS="${TLS_OLD_WAS:-off}"
if [ "$TLS_OLD" != "$TLS_OLD_WAS" ]; then  # with TLS off too: doctor compares the setting with this marker
  TLS_OLD_EVENT=update.tls_relaxed; [ "$TLS_OLD" != off ] || TLS_OLD_EVENT=update.tls_strict
  if "${COMPOSE[@]}" exec -T orchestrator python -c '
import sys
from pathlib import Path
from tb_common.audit_writer import open_audit
event, value, was = sys.argv[1:4]
open_audit(Path("/data/audit")).append(event, actor="deploy/install.sh",
    detail={"setting": "TB_TLS_OLD_CLIENTS", "value": value, "was": was, "decision": "D-1328"})
' "$TLS_OLD_EVENT" "$TLS_OLD" "$TLS_OLD_WAS"; then
    mkdir -p deploy/site && printf '%s\n' "$TLS_OLD" > "$TLS_OLD_MARK"
    echo "    audited $TLS_OLD_EVENT (TB_TLS_OLD_CLIENTS=$TLS_OLD, was $TLS_OLD_WAS)"
  else
    FAILS+=("TB_TLS_OLD_CLIENTS=$TLS_OLD is served but its switch was not audited ($TLS_OLD_EVENT): re-run deploy/install.sh once the orchestrator is up (RUNBOOK §12)")
  fi
fi

# ------------------------------------------------------------------------------------------------ 5. accounts
if [ "${TB_BOX:-0}" = 1 ]; then  # T-729: the owner makes the first accounts in the first-run wizard
  say "first accounts: the first-run wizard (box-install.sh shows its address and one-time code)"
else
say "first console administrator"
ADMIN_MAIL="$(sed -n 's/^MAIL_ADMIN_ADDR=//p' deploy/.env | head -1)"
ADMIN_MAIL="${ADMIN_MAIL:-${TB_ADMIN_EMAIL:-}}"
if [ -n "$ADMIN_MAIL" ]; then
  "${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin --mailbox "$ADMIN_MAIL"
else
  "${COMPOSE[@]}" exec -T console python -m console.cli bootstrap-admin --username admin
fi
# T-632 (OPS-013, D-192): the first administrator's enrolment code, printed once; without it the account cannot set
# up its authenticator. An administrator who already has one gets none (exit 2: nothing to print)
set +e
ENROL="$("${COMPOSE[@]}" exec -T console python -m console.cli enrol-code admin 2>&1)"; rc=$?
set -e
case "$rc" in
  0) echo "$ENROL" | sed 's/^/    /'; echo "    hand the enrolment code to the administrator in person; it works once, for 24 hours" ;;
  2) echo "    admin has an authenticator already: no enrolment code (console.cli reset-totp admin for a new one)" ;;
  *) echo "$ENROL" | sed 's/^/    /' >&2; FAILS+=("no enrolment code for admin (python -m console.cli enrol-code admin)") ;;
esac
echo "    add coordinators and viewers on the console's Users page, or: docker compose exec console python -m console.cli add-user"
fi

# NEW-STD-2 (D-562): the first signed head of the audit chain, when the site named an anchor folder: the night's own
# command, once, so the box does not wait for 00:20 for its first head. Not a stop: a line of the install's report
if [ -n "$(envget TB_AUDIT_ANCHOR_TARGETS)" ] && [ "$(id -u)" = 0 ]; then
  say "audit chain: the first signed head"
  if SIGN_OUT="$(python3 -m tools.trialbox audit-sign 2>&1)"; then
    echo "$SIGN_OUT" | sed 's/^/    /'
  else
    echo "$SIGN_OUT" | tail -5 | sed 's/^/    /' >&2
    FAILS+=("the first signed audit head was not made (python3 -m tools.trialbox audit-sign, above; RUNBOOK §2)")
  fi
fi

# ------------------------------------------------------------------------------------------------ 6. check
say "host check"
HOST_ARGS=(); [ "$MODE" = gpu ] && HOST_ARGS=(--gpu "$GPU")
sh "$ROOT/deploy/check_host.sh" ${HOST_ARGS[@]+"${HOST_ARGS[@]}"} || FAILS+=("the host check reported FAIL lines (above; docs/SECURITY.md)")
# T-632 (D-382): the judge, named from the configuration: its role, the registry's label for the build this profile
# serves, and the site's pin (tools/pin_model.py --name-judge); a stub box has none
if [ "$MODE" = gpu ]; then
  tree_args
  JUDGE="$(docker run --rm -v "$ROOT/deploy:/d:ro" ${TREE_D[@]+"${TREE_D[@]}"} "$IMAGE_PY" python -m tools.pin_model --name-judge "$GPU" --out /d/site/registry.site.yaml 2>&1)" \
    || FAILS+=("the judge could not be named: $JUDGE")
else
  JUDGE="judge: none (stub mode: structured criteria only; note criteria wait for a GPU)"
fi
echo "    $JUDGE"
# T-632 (OPS-013): the https:// URL must answer from this host, with the certificate the clinic PCs will see
URL="http://127.0.0.1:$(envget TB_HOST_CONSOLE_PORT | grep . || echo 8090)"
if [ -n "$TLS_HOST" ]; then
  URL="https://$TLS_HOST"
  CA=()
  if [ "$(envget TB_TLS_MODE)" = internal ]; then  # Caddy's root: hospital IT installs it on the staff PCs (RUNBOOK §12)
    mkdir -p deploy/secrets/tls
    for _ in $(seq 1 12); do
      "${COMPOSE[@]}" cp caddy:/data/caddy/pki/authorities/local/root.crt deploy/secrets/tls/caddy-root.crt >/dev/null 2>&1 && break
      sleep 5
    done
    [ -s deploy/secrets/tls/caddy-root.crt ] && CA=(--cacert deploy/secrets/tls/caddy-root.crt) && echo "    Caddy root certificate: deploy/secrets/tls/caddy-root.crt (for the staff PCs)"
  elif [ -n "$(envget TB_OIDC_CA)" ]; then
    CA=(--cacert "$(envget TB_OIDC_CA)")
  fi
  ANSWERED=0
  for _ in $(seq 1 "${TB_INSTALL_URL_TRIES:-24}"); do
    if curl -fsS -o /dev/null -m 10 ${CA[@]+"${CA[@]}"} --resolve "$TLS_HOST:443:${TB_TLS_CHECK_ADDR:-127.0.0.1}" "$URL/login"; then ANSWERED=1; break; fi
    sleep 5
  done
  [ "$ANSWERED" = 1 ] && echo "    $URL/login answers (certificate checked)" || FAILS+=("$URL/login does not answer from this host (curl above; RUNBOOK §12)")
fi
# D-884: the release gates' mode from the installed record; "report" is not a green release
GATES_MODE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("vuln_mode") or "not recorded")' deploy/updates/installed.json 2>/dev/null || echo "not recorded")"
[ "$GATES_MODE" = block ] || [ "$GATES_MODE" = "not recorded" ] || GATES_MODE="$GATES_MODE (findings shown, not blocking: not a green release)"
cat <<EOT

  TrialBox is running.
  Console:            $URL   (sign in as admin with the password and the enrolment code printed above)
  Intake mailbox:     $(sed -n 's/^MAIL_INTAKE_ADDR=//p' deploy/.env | head -1)
  Feed folder:        $(envget TB_SOURCE_DIR | grep . || echo "-")   mapping: deploy/site/mapping, then the image
  $JUDGE
  First ingest:       docker compose --project-directory deploy exec adapter python -m adapter.cli run   (or 02:00 nightly)
  Acceptance:         docs/RUNBOOK.md §6 before go-live;  updates: tools/apply_update.sh <bundle>
  Release gates:      $GATES_MODE
  Known limit:        SCREEN of the whole hospital stops at about 45,000 patients (the orchestrator's memory cap,
                      TB_MEM_ORCH; lower on the two-device workstation): CHANGELOG.md, "Known limits"
EOT
if [ "${#FAILS[@]}" -gt 0 ]; then
  printf 'install: FAIL: %s\n' "${FAILS[@]}" >&2
  exit 1
fi
