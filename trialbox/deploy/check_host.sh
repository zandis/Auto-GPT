#!/bin/sh
# Appliance host checks (SPEC §10.1; docs/HARDENING.md). Prints PASS / WARN / FAIL per item; exit 1 on any FAIL.
#
#   deploy/check_host.sh [--gb10] [--env deploy/.env] [--secrets <dir>]
#
# Read-only: changes nothing. Run as root on the appliance after installation and after every update.
set -u
GB10=0; ENV_FILE="$(dirname "$0")/.env"; SECRETS="${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/trialbox_tb-secrets/_data}"
while [ $# -gt 0 ]; do
  case "$1" in
    --gb10) GB10=1 ;;
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
  for f in site_hmac.key pid_map.key pid_map.sqlite; do
    if [ -f "$SECRETS/$f" ]; then
      m=$(mode "$SECRETS/$f"); case "$m" in 600|400|640|644) [ "$m" = "600" ] || [ "$m" = "400" ] && pass "$f mode $m" || warn "$f mode $m (want 600)";; *) fail "$f mode $m";; esac
    else
      warn "$f not present yet (created at first ingest)"
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
elif command -v nvidia-smi >/dev/null 2>&1; then
  pass "GPU: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)"
else
  warn "no NVIDIA GPU: run with TB_LLM_MODE=stub or the cloud flag"
fi
echo "---"
[ "$FAILS" -eq 0 ] && { echo "host checks passed"; exit 0; } || { echo "$FAILS check(s) failed"; exit 1; }
