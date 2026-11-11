#!/bin/sh
# Appliance host checks (SPEC §10.1; docs/SECURITY.md). Prints PASS / WARN / FAIL per item; exit 1 on any FAIL.
#
#   deploy/check_host.sh [--gb10 | --gpu <profile>] [--gpu-only | --baseline] [--env deploy/.env] [--secrets <dir>]
#
# Read-only: changes nothing. Run as root on the appliance after installation and after every update.
# --gpu names the GPU profile (rtxpro6000, gb10, rtx5090, rtx4090, default; --gb10 is --gpu gb10). With a profile, or
# TB_LLM_MODE=vllm in the env file, the host is checked against the vLLM image of deploy/images.lock (D-348): its
# architecture, the NVIDIA driver (FAIL below the image's CUDA need) and the GPU's compute capability.
# --gpu-only runs only those GPU checks (install.sh runs it before it loads anything).
# --baseline runs only the host baseline (T-634, D-408): the host system, the disk under Docker's data root and its
# unlock (deploy/hardening/luks_policy.py: FAIL when the TPM alone opens it), swap, the site keys (FAIL when plain in
# VALIDATION or PRODUCTION), the input firewall, SSH, free space, the cron files, the time zone and OS patches.
# TB_HOST_ROOT moves every host file it reads (/etc, /run, /dev, /var) under a folder: the tests only.
set -u
GB10=0; GPU_PROFILE=""; GPU_ONLY=0; BASELINE=0; ENV_FILE="$(dirname "$0")/.env"
SECRETS="${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/trialbox_tb-secrets/_data}"
HR="${TB_HOST_ROOT:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --baseline) BASELINE=1 ;;
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

# ------------------------------------------------------------------------------------------------ host baseline
# T-634 (D-408; OPS-015, OPS-043, OPS-052, OPS-062). TB_ENV in the env file decides how strict: PRODUCTION when unset
# (D-127); VALIDATION and PRODUCTION FAIL what DEV and TEST only WARN.
TBENV="$(envget TB_ENV | tr '[:lower:]' '[:upper:]')"; TBENV="${TBENV:-PRODUCTION}"
STRICT=0; case "$TBENV" in VALIDATION|PRODUCTION) STRICT=1 ;; esac
strict() { if [ "$STRICT" = 1 ]; then fail "$1"; else warn "$1 (FAIL in VALIDATION and PRODUCTION)"; fi; }

# the host system (D-408: Ubuntu 24.04 LTS, or the DGX Spark's own Ubuntu-based system, until the owner answers)
OS_ID="$(sed -n 's/^ID=//p' "$HR/etc/os-release" 2>/dev/null | tr -d '"')"
OS_VER="$(sed -n 's/^VERSION_ID=//p' "$HR/etc/os-release" 2>/dev/null | tr -d '"')"
if [ "$OS_ID" = ubuntu ] && [ "$OS_VER" = 24.04 ]; then
  pass "host system Ubuntu $OS_VER (D-408)"
else
  warn "host system '${OS_ID:-?} ${OS_VER:-?}': D-408 names Ubuntu 24.04 LTS (Windows with WSL2: check_host --wsl2, T-210a)"
fi

# disk encryption where the data is: Docker's data root and the backup staging folder (OPS-015), not any crypt device
DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
DOCKER_ROOT="${DOCKER_ROOT:-/var/lib/docker}"
crypt_under() {  # the LUKS devices under the file system that holds $1 ("" when it is not on dm-crypt)
  src="$(df --output=source "$HR$1" 2>/dev/null | tail -1)"
  [ -n "$src" ] || return 0
  lsblk -rsno NAME,TYPE "$src" 2>/dev/null | awk '$2 == "crypt" {print $1}' | head -1
}
LUKS_DEVS=""
for d in "$DOCKER_ROOT" "$ROOT_DIR/deploy/backups"; do
  [ -e "$HR$d" ] || continue
  c="$(crypt_under "$d")"
  if [ -n "$c" ]; then
    pass "LUKS: $d is on the encrypted device $c"
    dev="$(cryptsetup status "$c" 2>/dev/null | sed -n 's/^ *device: *//p')"
    case " $LUKS_DEVS " in *" $dev "*) ;; *) [ -n "$dev" ] && LUKS_DEVS="$LUKS_DEVS $dev" ;; esac
  else
    fail "LUKS: $d is not on a dm-crypt device (full-disk encryption required)"
  fi
done
# the unlock: no way into the volume that needs neither the hospital network nor a person (OPS-043)
for dev in $LUKS_DEVS; do
  out="$(python3 "$ROOT_DIR/deploy/hardening/luks_policy.py" "$dev" 2>&1)"
  echo "$out" | grep -E '^(PASS|WARN|FAIL) ' || fail "LUKS unlock of $dev not judged: $out"
  FAILS=$((FAILS + $(echo "$out" | grep -c '^FAIL ')))
done
if [ -z "$(swapon --noheadings 2>/dev/null)" ]; then pass "swap disabled"; else fail "swap is enabled (swapoff -a; remove from /etc/fstab)"; fi
if [ -e "$HR/dev/tpmrm0" ] || [ -e "$HR/dev/tpm0" ]; then pass "TPM 2.0 device present"; else strict "no TPM device: the disk unlock and the KEK cannot be bound to this board"; fi

# the site keys: wrapped under the KEK (D-347), never plain in VALIDATION or PRODUCTION (T-634)
if [ -f "$ENV_FILE" ]; then
  m=$(mode "$ENV_FILE"); [ "$m" = "600" ] || [ "$m" = "400" ] && pass ".env mode $m" || fail ".env mode $m (want 600, root-owned)"
else
  fail ".env not found at $ENV_FILE"
fi
if [ -d "$SECRETS" ]; then
  for f in site_hmac.key pid_map.key; do  # the pid map rows are in the trial database (schema pidmap)
    if [ -f "$SECRETS/$f" ]; then
      m=$(mode "$SECRETS/$f")
      strict "$f is a plain file (mode $m): seal it (deploy/hardening/seal_keys.sh; python3 -m tools.keys init)"
    elif [ -f "$SECRETS/$f.wrapped" ]; then
      pass "$f sealed under the KEK ($f.wrapped)"
    else
      warn "$f not present (made only by install.sh, T-612; the ingest refuses a night without the site key)"
    fi
  done
  if [ -f "$SECRETS/kek.json" ]; then
    if [ -f "$HR/etc/credstore.encrypted/trialbox-kek" ] || ! grep -q '"backend": *"file"' "$SECRETS/kek.json"; then
      pass "KEK: $(sed -n 's/.*"backend": *"\([a-z]*\)".*/\1/p' "$SECRETS/kek.json" | head -1) back end"
    else
      warn "KEK back end file but no sealed credential in /etc/credstore.encrypted/trialbox-kek (seal it to the TPM)"
    fi
  fi
else
  warn "secrets volume not found at $SECRETS (pass --secrets)"
fi

# the input firewall and SSH (deploy/hardening/apply.sh; OPS-052)
if command -v nft >/dev/null 2>&1 && nft list table inet trialbox_input >/dev/null 2>&1; then
  pass "input firewall loaded (table inet trialbox_input)"
else
  strict "input firewall not loaded: deploy/hardening/apply.sh firewall (443 from the clinic ranges only)"
fi
if command -v sshd >/dev/null 2>&1 && { systemctl is-active --quiet ssh.service 2>/dev/null || systemctl is-active --quiet ssh.socket 2>/dev/null; }; then
  cfg="$(sshd -T 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  bad=""
  echo "$cfg" | grep -qx 'permitrootlogin no' || bad="$bad root login;"
  echo "$cfg" | grep -qx 'passwordauthentication no' || bad="$bad passwords;"
  echo "$cfg" | grep -qx 'kbdinteractiveauthentication no' || bad="$bad keyboard-interactive;"
  if [ -z "$bad" ]; then pass "SSH on: keys only, no root login"; else strict "SSH allows:$bad (deploy/hardening/apply.sh ssh)"; fi
else
  pass "SSH off"
fi

# room to work: Docker's data root (backups and updates stage there too)
free="$(df -P "$HR$DOCKER_ROOT" 2>/dev/null | awk 'NR == 2 {gsub("%", "", $5); print 100 - $5}')"
if [ -z "$free" ]; then warn "free space on $DOCKER_ROOT unknown"
elif [ "$free" -lt 10 ]; then fail "free space on $DOCKER_ROOT: $free% (below 10%)"
elif [ "$free" -lt 20 ]; then warn "free space on $DOCKER_ROOT: $free% (below 20%)"
else pass "free space on $DOCKER_ROOT: $free%"; fi

# the two cron files of the install (T-632: log retention, backups)
for c in trialbox-retention trialbox-backup; do
  if [ -f "$HR/etc/cron.d/$c" ]; then pass "cron file /etc/cron.d/$c"; else strict "cron file /etc/cron.d/$c missing (re-run install.sh)"; fi
done
# the host's time zone (doctor compares it with the site's, D-315)
HOST_TZ_NAME="$(timedatectl show -p Timezone --value 2>/dev/null || cat "$HR/etc/timezone" 2>/dev/null || true)"
if [ -n "$HOST_TZ_NAME" ]; then pass "host time zone $HOST_TZ_NAME"; else warn "host time zone not set (timedatectl set-timezone)"; fi

# OS patches (tools/apply_update.sh ospatch; OPS-024)
OSP="$ROOT_DIR/deploy/updates/ospatch"
if [ -f "$OSP/REBOOT_PENDING.json" ]; then
  warn "an OS patch waits for its reboot: reboot in the window, then tools/apply_update.sh ospatch-check"
elif [ -f "$HR/var/run/reboot-required" ]; then
  warn "the host needs a reboot for its updates (/var/run/reboot-required)"
fi
last="$(ls "$OSP" 2>/dev/null | sed -n 's/^\([0-9]\{4\}-[0-9][0-9]-[0-9][0-9]\)\.json$/\1/p' | sort | tail -1)"
if [ -n "$last" ]; then
  if grep -q '"canary": "failed"' "$OSP/$last.json"; then fail "OS patch $last: its canary failed (RUNBOOK §24)"
  else pass "last OS patch snapshot $last"; fi
fi

if [ "$BASELINE" = 1 ]; then
  echo "---"
  [ "$FAILS" -eq 0 ] && { echo "host baseline checks passed"; exit 0; } || { echo "$FAILS baseline check(s) failed"; exit 1; }
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
