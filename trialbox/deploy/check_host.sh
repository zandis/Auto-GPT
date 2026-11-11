#!/bin/sh
# Appliance host checks (SPEC §10.1; docs/SECURITY.md). Prints PASS / WARN / FAIL per item; exit 1 on any FAIL.
#
#   deploy/check_host.sh [--gb10 | --gpu <profile>] [--gpu-only] [--env deploy/.env] [--secrets <dir>]
#
# Read-only: changes nothing. Run as root on the appliance after installation and after every update.
# --gpu names the GPU profile (rtxpro6000, gb10, rtx5090, rtx4090, default; --gb10 is --gpu gb10). With a profile, or
# TB_LLM_MODE=vllm in the env file, the host is checked against the vLLM image of deploy/images.lock (D-348): its
# architecture, the NVIDIA driver (FAIL below the image's CUDA need) and the GPU's compute capability.
# --gpu-only runs only those GPU checks (install.sh runs it before it loads anything).
set -u
GB10=0; GPU_PROFILE=""; GPU_ONLY=0; ENV_FILE="$(dirname "$0")/.env"
SECRETS="${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/trialbox_tb-secrets/_data}"
while [ $# -gt 0 ]; do
  case "$1" in
    --gb10) GB10=1; GPU_PROFILE=gb10 ;;
    --gpu) GPU_PROFILE="$2"; [ "$2" = gb10 ] && GB10=1; shift ;;
    --gpu-only) GPU_ONLY=1 ;;
    --env) ENV_FILE="$2"; shift ;;
    --secrets) SECRETS="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
FAILS=0
pass() { echo "PASS  $1"; }
warn() { echo "WARN  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
mode() { stat -c %a "$1" 2>/dev/null; }
envget() { [ -r "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# the vLLM image of deploy/images.lock against this host (D-348; tools/images_lock.py, standard library only)
gpu_image_check() {
  if [ "$GB10" = 1 ]; then img="${VLLM_GB10_IMAGE:-$(envget VLLM_GB10_IMAGE)}"; else img="${VLLM_IMAGE:-$(envget VLLM_IMAGE)}"; fi
  drv=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
  cap=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1)
  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found: the GPU host cannot be checked against deploy/images.lock"; return
  fi
  out=$(cd "$ROOT_DIR" && python3 -m tools.images_lock host --arch "$(uname -m)" --driver "$drv" \
    --compute-cap "$cap" --image "$img" 2>&1)
  echo "$out" | grep -E '^(PASS|WARN|FAIL) ' || echo "FAIL  tools.images_lock: $out"
  n=$(echo "$out" | grep -c '^FAIL ')
  [ "$n" -gt 0 ] && FAILS=$((FAILS + n))
  echo "$out" | grep -qE '^(PASS|WARN|FAIL) ' || FAILS=$((FAILS + 1))
}
[ -n "$GPU_PROFILE" ] || [ "$(envget TB_LLM_MODE)" != vllm ] || GPU_PROFILE=default
if [ "$GPU_ONLY" = 1 ]; then
  [ -n "$GPU_PROFILE" ] || { echo "--gpu-only needs --gpu <profile> or --gb10" >&2; exit 2; }
  [ "$GB10" = 1 ] && { [ "$(uname -m)" = "aarch64" ] && pass "aarch64 host" || fail "GB10 profile on $(uname -m)"; }
  gpu_image_check
  echo "---"
  [ "$FAILS" -eq 0 ] && { echo "GPU host checks passed"; exit 0; } || { echo "$FAILS GPU check(s) failed"; exit 1; }
fi

# disk encryption and swap (§10.1 "Disk")
if command -v lsblk >/dev/null 2>&1 && lsblk -rno TYPE 2>/dev/null | grep -qx crypt; then
  pass "LUKS: an encrypted (crypt) block device is in use"
else
  fail "LUKS: no dm-crypt device found (full-disk encryption required)"
fi
if [ -z "$(swapon --noheadings 2>/dev/null)" ]; then pass "swap disabled"; else fail "swap is enabled (swapoff -a; remove from /etc/fstab)"; fi
if [ -e /dev/tpmrm0 ] || [ -e /dev/tpm0 ]; then pass "TPM 2.0 device present"; else warn "no TPM device: secrets cannot be TPM-sealed"; fi

# secrets and configuration permissions (§10.1 "Secrets")
if [ -f "$ENV_FILE" ]; then
  m=$(mode "$ENV_FILE"); [ "$m" = "600" ] || [ "$m" = "400" ] && pass ".env mode $m" || fail ".env mode $m (want 600, root-owned)"
else
  fail ".env not found at $ENV_FILE"
fi
if [ -d "$SECRETS" ]; then
  for f in site_hmac.key pid_map.key; do  # the pid map rows are in the trial database (schema pidmap)
    if [ -f "$SECRETS/$f" ]; then
      m=$(mode "$SECRETS/$f"); case "$m" in 600|400|640|644) [ "$m" = "600" ] || [ "$m" = "400" ] && pass "$f mode $m" || warn "$f mode $m (want 600)";; *) fail "$f mode $m";; esac
    else
      warn "$f not present (made only by install.sh, T-612; the ingest refuses a night without the site key)"
    fi
  done
else
  warn "secrets volume not found at $SECRETS (pass --secrets)"
fi

# network egress (§2, deploy/network.sh)
if command -v nft >/dev/null 2>&1 && nft list table inet trialbox_egress >/dev/null 2>&1; then
  pass "egress allowlist table loaded (deploy/network.sh apply)"
else
  fail "egress allowlist not loaded: run deploy/network.sh apply after docker compose up"
fi

# container runtime
if command -v docker >/dev/null 2>&1; then
  v=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "?")
  case "$v" in 2[7-9].*|[3-9][0-9].*) pass "Docker Engine $v";; *) warn "Docker Engine $v (27+ expected)";; esac
else
  fail "docker not installed"
fi
if command -v chronyc >/dev/null 2>&1 || command -v timedatectl >/dev/null 2>&1; then
  if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -qx yes; then pass "clock synchronised (audit timestamps)"; else warn "clock not NTP-synchronised"; fi
fi

# GPU / GB10 (§2; docker-compose.gb10.yml)
if [ "$GB10" = 1 ]; then
  [ "$(uname -m)" = "aarch64" ] && pass "aarch64 host" || fail "GB10 profile on $(uname -m)"
  d=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
  if [ "$d" = "580.142" ]; then pass "NVIDIA driver 580.142 (pinned)"; else fail "NVIDIA driver '${d:-none}' (GB10 requires 580.142; hold it with apt-mark)"; fi
  if apt-mark showhold 2>/dev/null | grep -q nvidia; then pass "NVIDIA driver packages held"; else warn "driver packages not held (apt-mark hold)"; fi
  if docker info 2>/dev/null | grep -qi nvidia; then pass "nvidia container runtime"; else fail "nvidia-container-toolkit not configured"; fi
  gpu_image_check
elif command -v nvidia-smi >/dev/null 2>&1; then
  pass "GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)"
  [ -z "$GPU_PROFILE" ] || gpu_image_check
elif [ -n "$GPU_PROFILE" ]; then
  fail "GPU profile $GPU_PROFILE but no nvidia-smi (NVIDIA driver not installed)"
else
  warn "no NVIDIA GPU: run with TB_LLM_MODE=stub or the cloud flag"
fi
# trialbox doctor (spec v4 S1-16): topology, class ceiling, gateway-only model reach, channel engine, Hermes pin,
# publish gate. TB_SETTINGS names the site settings file; TB_DATAPLAT_DIR the data-platform workdir.
if command -v python3 >/dev/null 2>&1 && ! python3 -c "import pydantic, yaml" 2>/dev/null \
    && command -v docker >/dev/null 2>&1 && docker image inspect "${TB_IMAGE:-trialbox-py:1.0.0}" >/dev/null 2>&1; then
  # a site host has no pydantic (found by the box rehearsal, D-176): the doctor runs in the box's own image
  set -- ; [ -f "$ROOT_DIR/deploy/settings.yaml" ] && set -- --settings /app/deploy/settings.yaml
  # the host's zone for doctor's site_tz check (D-315): the container's /etc is the image's, not the host's
  HOST_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null \
    || readlink /etc/localtime 2>/dev/null | sed 's|.*zoneinfo/||')"
  # the KEK the unseal writes (tb_common.kek, D-347), read-only, when this host has one
  KEK_DIR="${TB_KEK_HOST_DIR:-/run/trialbox}"; KEK_MOUNT=""
  [ -d "$KEK_DIR" ] && KEK_MOUNT="$KEK_DIR:/run/trialbox:ro"
  if docker run --rm --network none --env-file "$ENV_FILE" -e TB_HOST_TZ="$HOST_TZ" -v "$ROOT_DIR/deploy:/app/deploy:ro" \
      ${KEK_MOUNT:+-v "$KEK_MOUNT"} --user 0:0 \
      "${TB_IMAGE:-trialbox-py:1.0.0}" python -m tools.trialbox doctor "$@"; then
    pass "trialbox doctor"
  else
    fail "trialbox doctor (see the lines above)"
  fi
elif command -v python3 >/dev/null 2>&1; then
  if (cd "$ROOT_DIR" && PYTHONPATH=libs:services:. python3 -m tools.trialbox doctor --env-file "$ENV_FILE" ${TB_SETTINGS:+--settings "$TB_SETTINGS"}); then
    pass "trialbox doctor"
  else
    fail "trialbox doctor (see the lines above)"
  fi
else
  fail "python3 not found: trialbox doctor cannot run"
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "host checks passed"; exit 0; } || { echo "$FAILS check(s) failed"; exit 1; }
