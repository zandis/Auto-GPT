#!/bin/sh
# Appliance host checks (SPEC §10.1; docs/SECURITY.md). Prints PASS / WARN / FAIL per item; exit 1 on any FAIL.
#
#   deploy/check_host.sh [--gb10 | --gpu <profile>] [--gpu-only | --baseline] [--env deploy/.env] [--secrets <dir>]
#                        [--wsl2 [--wsl2-distro <name>] [--escrow "<who keeps the BitLocker recovery password>"]]
#
# Read-only: changes nothing. Run as root on the appliance after installation and after every update.
# --gpu names the GPU profile (rtxpro6000, gb10, rtx5090, rtx4090, default; --gb10 is --gpu gb10). With a profile, or
# TB_LLM_MODE=vllm in the env file, the host is checked against the vLLM image of deploy/images.lock (D-348): its
# architecture, the NVIDIA driver (FAIL below the image's CUDA need) and the GPU's compute capability.
# --gpu-only runs only those GPU checks (install.sh runs it before it loads anything).
# --baseline runs only the host baseline (T-634, D-408): the host system, the disk under Docker's data root and its
# unlock (deploy/hardening/luks_policy.py: FAIL when the TPM alone opens it), swap, the site keys (FAIL when plain in
# VALIDATION or PRODUCTION), the input firewall, SSH, free space, the cron files, the time zone and OS patches.
# --wsl2 (T-210a, D-421): the host is Windows with WSL2; on by itself on a WSL2 kernel. BitLocker takes the place of
# LUKS and the TPM: deploy/windows/host_facts.ps1 reads Windows through interop (run WSL from an elevated terminal)
# and deploy/windows/wsl2_policy.py judges BitLocker, the page file, hibernation, WSL swap, Remote Desktop, Windows
# Update restarts, the start-at-boot task, the clocks and the disk file, as preflight.ps1 does before the install.
# TB_HOST_ROOT moves every host file it reads (/etc, /run, /dev, /var, /proc) under a folder: the tests only.
# With gb10, a host under 96 GiB of memory (MemTotal, deploy/gpu_profile.sh memory-class) FAILs: it is the 64 GB
# Spark class, refused by install.sh (card 10E-5, D-1335; H10E5-03). TB_TEST_MEM_KIB stands in for MemTotal in tests.
set -u
GB10=0; GPU_PROFILE=""; GPU_ONLY=0; BASELINE=0; ENV_FILE="$(dirname "$0")/.env"
WSL2=0; WSL2_DISTRO="${WSL_DISTRO_NAME:-}"; ESCROW=""
SECRETS="${TB_SECRETS_HOST_DIR:-/var/lib/docker/volumes/trialbox_tb-secrets/_data}"
HR="${TB_HOST_ROOT:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --baseline) BASELINE=1 ;;
    --wsl2) WSL2=1 ;;
    --wsl2-distro) WSL2_DISTRO="$2"; shift ;;
    --escrow) ESCROW="$2"; shift ;;
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
# a GB10 host under 96 GiB is the 64 GB class (gb10-64): the same refusal as install.sh's; unknown memory is not judged
gb10_memory_check() {
  [ "$(sh "$ROOT_DIR/deploy/gpu_profile.sh" memory-class "${TB_TEST_MEM_KIB:-}")" = gb10-64 ] || return 0
  fail "this DGX Spark has under 96 GiB of memory (the 64 GB class): TrialBox does not serve the model pair on it. The gb10 profile is sized for 128 GB, and no profile of the 64 GB class is measured, so none is guessed (card 10E-5, D-1335). Install with --mode stub, or use a 128 GB Spark or another measured box"
}
[ -n "$GPU_PROFILE" ] || [ "$(envget TB_LLM_MODE)" != vllm ] || GPU_PROFILE=default
if [ "$GPU_ONLY" = 1 ]; then
  [ -n "$GPU_PROFILE" ] || { echo "--gpu-only needs --gpu <profile> or --gb10" >&2; exit 2; }
  [ "$GB10" = 1 ] && { [ "$(uname -m)" = "aarch64" ] && pass "aarch64 host" || fail "GB10 profile on $(uname -m)"; }
  [ "$GB10" = 1 ] && gb10_memory_check
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
# D-837: TB_HOST_PROFILE=poc (a proof of concept or validation run on a plain VM): the host-facility checks (TPM seal,
# LUKS, egress table, firewall, SSH, cron) WARN and are listed at the end; never on PRODUCTION
HOST_PROFILE="$(envget TB_HOST_PROFILE)"; FACILITIES=""
facility() {  # facility strict|fail MESSAGE LABEL: as strict/fail, or a listed WARN under the poc profile
  if [ "$HOST_PROFILE" = poc ] && [ "$TBENV" != PRODUCTION ]; then
    warn "$2 [host profile poc]"; FACILITIES="$FACILITIES, $3"
  elif [ "$1" = strict ]; then strict "$2"; else fail "$2"; fi
}
facilities() { [ -z "$FACILITIES" ] || warn "host profile poc: ${FACILITIES#, } (each one fails on a site host)"; }
# D-887: a rehearsal box (TB_REHEARSAL=1 on TEST, or on VALIDATION with the mark deploy/site/rehearsal.json:
# deploy/install.sh --rehearsal) runs in a container on a developer's or CI's host: no encrypted disk, no NET_ADMIN.
# What only the site's host can have is a WARN there
rehearsal_box() { [ "$(envget TB_REHEARSAL)" = 1 ] && { [ "$TBENV" = TEST ] || { [ "$TBENV" = VALIDATION ] && [ -f "$(dirname "$ENV_FILE")/site/rehearsal.json" ]; }; }; }
if [ "$HOST_PROFILE" = poc ] && [ "$TBENV" = PRODUCTION ]; then
  fail "TB_HOST_PROFILE=poc on a PRODUCTION box: the host-facility checks are never relaxed there (remove it from $ENV_FILE)"
fi
KREL="$(cat "$HR/proc/sys/kernel/osrelease" 2>/dev/null || true)"
case "$KREL" in *[Mm]icrosoft*WSL2*) WSL2=1 ;; esac  # a WSL2 kernel: the Windows checks are on by themselves

# the host system (D-408: Ubuntu 24.04 LTS, or the DGX Spark's own Ubuntu-based system, until the owner answers)
OS_ID="$(sed -n 's/^ID=//p' "$HR/etc/os-release" 2>/dev/null | tr -d '"')"
OS_VER="$(sed -n 's/^VERSION_ID=//p' "$HR/etc/os-release" 2>/dev/null | tr -d '"')"
if [ "$OS_ID" = ubuntu ] && [ "$OS_VER" = 24.04 ] && [ "$WSL2" = 1 ]; then
  pass "host system Ubuntu $OS_VER in WSL2 on Windows (D-408, D-421)"
elif [ "$OS_ID" = ubuntu ] && [ "$OS_VER" = 24.04 ]; then
  pass "host system Ubuntu $OS_VER (D-408)"
else
  warn "host system '${OS_ID:-?} ${OS_VER:-?}': D-408 names Ubuntu 24.04 LTS (Windows with WSL2: check_host --wsl2, T-210a)"
fi

# Windows with WSL2 (T-210a, D-421; CR-041, OPS-061): the facts from Windows, judged by deploy/windows/wsl2_policy.py
wsl2_checks() {
  case "$KREL" in
    *[Mm]icrosoft*WSL2*) pass "WSL2 kernel $KREL" ;;
    *) fail "--wsl2 on a kernel that is not WSL2 ('${KREL:-unknown}')"; return ;;
  esac
  ps="$(command -v powershell.exe || echo /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe)"
  facts_ps="$(wslpath -w "$ROOT_DIR/deploy/windows/host_facts.ps1" 2>/dev/null || true)"
  if [ ! -x "$ps" ] || [ -z "$facts_ps" ]; then
    fail "Windows interop off: no powershell.exe or wslpath ([interop] enabled=true in /etc/wsl.conf)"; return
  fi
  lo="$(date +%s)"
  facts="$("$ps" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$facts_ps" -Distro "$WSL2_DISTRO" \
    -RecoveryKeyEscrow "$ESCROW" 2>/dev/null | tr -d '\r')"
  hi="$(date +%s)"
  sflag=""; [ "$STRICT" = 1 ] && sflag=--strict
  out="$(printf '%s\nclock_linux_lo=%s\nclock_linux_hi=%s\n' "$facts" "$lo" "$hi" \
    | python3 "$ROOT_DIR/deploy/windows/wsl2_policy.py" --facts - $sflag 2>&1)"
  printf '%s\n' "$out" | grep -E '^(PASS|WARN|FAIL) ' || fail "Windows host not judged: $out"
  FAILS=$((FAILS + $(printf '%s\n' "$out" | grep -c '^FAIL ')))
}
DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
DOCKER_ROOT="${DOCKER_ROOT:-/var/lib/docker}"
if [ "$WSL2" = 1 ]; then
  wsl2_checks
else
# disk encryption where the data is: Docker's data root and the backup staging folder (OPS-015), not any crypt device
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
  elif rehearsal_box; then
    warn "LUKS: $d is not on a dm-crypt device: a rehearsal box's host is not the site's (the site's IQ checks it)"
  else
    facility fail "LUKS: $d is not on a dm-crypt device (full-disk encryption required)" LUKS
  fi
done
# the unlock: no way into the volume that needs neither the hospital network nor a person (OPS-043)
for dev in $LUKS_DEVS; do
  out="$(python3 "$ROOT_DIR/deploy/hardening/luks_policy.py" "$dev" 2>&1)"
  if [ "$HOST_PROFILE" = poc ] && [ "$TBENV" != PRODUCTION ]; then
    echo "$out" | grep -E '^(PASS|WARN|FAIL) ' | sed 's/^FAIL /WARN /; s/$/ [host profile poc]/' || warn "LUKS unlock of $dev not judged: $out"
    FACILITIES="$FACILITIES, LUKS unlock"
  else
    echo "$out" | grep -E '^(PASS|WARN|FAIL) ' || fail "LUKS unlock of $dev not judged: $out"
    FAILS=$((FAILS + $(echo "$out" | grep -c '^FAIL ')))
  fi
done
fi  # the LUKS lines; on WSL2 BitLocker's lines above
if [ -z "$(swapon --noheadings 2>/dev/null)" ]; then pass "swap disabled"; else fail "swap is enabled (swapoff -a; remove from /etc/fstab)"; fi
if [ "$WSL2" = 1 ]; then :  # WSL2 sees no TPM; Windows' TPM is judged with BitLocker's protectors above
elif [ -e "$HR/dev/tpmrm0" ] || [ -e "$HR/dev/tpm0" ]; then
  # D-836: a device node is not enough; systemd-creds needs the TPM and its TSS2 libraries. Asked of the running host
  # only (a test's TB_HOST_ROOT has no kernel to ask)
  if [ -z "$HR" ] && command -v systemd-creds >/dev/null 2>&1 && ! systemd-creds has-tpm2 >/dev/null 2>&1; then
    facility strict "TPM 2.0 device present but not usable (systemd-creds has-tpm2): the KEK cannot be sealed to it (TB_KEK_BACKEND=passphrase with TB_KEK_PASSPHRASE)" TPM
  else
    pass "TPM 2.0 device present"
  fi
else facility strict "no TPM device: the disk unlock and the KEK cannot be bound to this board (TB_KEK_BACKEND=passphrase with TB_KEK_PASSPHRASE)" TPM; fi

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
      facility strict "$f is a plain file (mode $m): seal it (deploy/hardening/seal_keys.sh; python3 -m tools.keys init)" "$f sealed"
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
  facility strict "input firewall not loaded: deploy/hardening/apply.sh firewall (443 from the clinic ranges only)" firewall
fi
if command -v sshd >/dev/null 2>&1 && { systemctl is-active --quiet ssh.service 2>/dev/null || systemctl is-active --quiet ssh.socket 2>/dev/null; }; then
  cfg="$(sshd -T 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  bad=""
  echo "$cfg" | grep -qx 'permitrootlogin no' || bad="$bad root login;"
  echo "$cfg" | grep -qx 'passwordauthentication no' || bad="$bad passwords;"
  echo "$cfg" | grep -qx 'kbdinteractiveauthentication no' || bad="$bad keyboard-interactive;"
  if [ -z "$bad" ]; then pass "SSH on: keys only, no root login"; else facility strict "SSH allows:$bad (deploy/hardening/apply.sh ssh)" SSH; fi
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
  if [ -f "$HR/etc/cron.d/$c" ]; then pass "cron file /etc/cron.d/$c"; else facility strict "cron file /etc/cron.d/$c missing (re-run install.sh)" "cron $c"; fi
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
  facilities
  [ "$FAILS" -eq 0 ] && { echo "host baseline checks passed"; exit 0; } || { echo "$FAILS baseline check(s) failed"; exit 1; }
fi

# network egress (§2, deploy/network.sh)
if command -v nft >/dev/null 2>&1 && nft list table inet trialbox_egress >/dev/null 2>&1; then
  pass "egress allowlist table loaded (deploy/network.sh apply)"
else
  if rehearsal_box; then
    # D-887: a rehearsal box runs without NET_ADMIN, so deploy/network.sh cannot load the table (the site's IQ checks it)
    warn "egress allowlist not loaded: a rehearsal box has no NET_ADMIN (the site's IQ checks deploy/network.sh)"
  else
    facility fail "egress allowlist not loaded: run deploy/network.sh apply after docker compose up" "egress table"
  fi
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
  gb10_memory_check
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
  # T-712 (D-481): the doctor reads the box's own file and compose files (the database passwords check); the
  # deploy folder is mounted below, so the file is there when it is the box's deploy/.env
  [ "$(cd "$(dirname "$ENV_FILE")" && pwd)" = "$(cd "$ROOT_DIR/deploy" && pwd)" ] \
    && [ "$(basename "$ENV_FILE")" = .env ] && set -- "$@" --env-file /app/deploy/.env
  # the host's zone for doctor's site_tz check (D-315): the container's /etc is the image's, not the host's
  HOST_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null \
    || readlink /etc/localtime 2>/dev/null | sed 's|.*zoneinfo/||')"
  # the KEK the unseal writes (tb_common.kek, D-347), read-only, when this host has one
  KEK_DIR="${TB_KEK_HOST_DIR:-/run/trialbox}"; KEK_MOUNT=""
  [ -d "$KEK_DIR" ] && KEK_MOUNT="$KEK_DIR:/run/trialbox:ro"
  # D-991: the code systems loaded at install (deploy/terminology.sh), read-only, so doctor's terminology line reports
  # what criteria-compiler, orchestrator and console read
  TERM_VOL="${COMPOSE_PROJECT_NAME:-trialbox}_tb-terminology"; TERM_MOUNT=""
  docker volume inspect "$TERM_VOL" >/dev/null 2>&1 && TERM_MOUNT="${TERM_VOL}:/data/terminology:ro"
  # NEW-STD-2 (D-562): doctor's audit_heads check reads the secrets volume (the audit key) and the anchor folders
  # (the signed heads) at their host paths, read-only; without them a healthy box FAILed the check in the image
  AUDIT_MOUNTS=""
  SEC_HOST="$(sed -n 's/^TB_SECRETS_HOST_DIR=//p' "$ENV_FILE" | tail -1)"
  [ -n "$SEC_HOST" ] || SEC_HOST="$(docker volume inspect -f '{{.Mountpoint}}' "${COMPOSE_PROJECT_NAME:-trialbox}_tb-secrets" 2>/dev/null)"
  [ -n "$SEC_HOST" ] && [ -d "$SEC_HOST" ] && AUDIT_MOUNTS="-v $SEC_HOST:$SEC_HOST:ro -e TB_SECRETS_HOST_DIR=$SEC_HOST"
  # D-887 (found by the box rehearsal in CI): doctor's site_key check reads the site key where the services do
  if [ -n "$SEC_HOST" ] && [ -d "$SEC_HOST" ]; then AUDIT_MOUNTS="$AUDIT_MOUNTS -v $SEC_HOST:/run/secrets/trialbox:ro"
  else AUDIT_MOUNTS="$AUDIT_MOUNTS -e TB_SECRETS_DIR=/nonexistent/secrets-volume-not-seen"; fi  # a WARN, not a FAIL
  # ...and every compose file of COMPOSE_FILE outside deploy/ (an override such as the rehearsal's stand-ins) where it is
  OLD_IFS="$IFS"; IFS=:
  for cf in $(sed -n 's/^COMPOSE_FILE=//p' "$ENV_FILE" | tail -1); do
    case "$cf" in "$ROOT_DIR/deploy/"*) ;; /*) [ -f "$cf" ] && AUDIT_MOUNTS="$AUDIT_MOUNTS -v $cf:$cf:ro" ;; esac
  done
  IFS="$OLD_IFS"
  ANCHORS="$(sed -n 's/^TB_AUDIT_ANCHOR_TARGETS=//p' "$ENV_FILE" | tail -1)"
  OLD_IFS="$IFS"; IFS=:
  for anchor in $ANCHORS; do
    [ -d "$anchor" ] && AUDIT_MOUNTS="$AUDIT_MOUNTS -v $anchor:$anchor:ro"
  done
  IFS="$OLD_IFS"
  # D-722: doctor's ldap_ca check reads the hospital's directory CA file where TB_LDAP_CA names it. Quotes and
  # blanks around the value are not part of it (compose and doctor strip them); a path relative to deploy/ is
  # inside the mount of deploy/ already. Its own quoted argument: the path may hold a space
  LDAP_CA="$(sed -n 's/^TB_LDAP_CA=//p' "$ENV_FILE" | tail -1 | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")"
  LDAP_MOUNT=""
  case "$LDAP_CA" in /*) [ -f "$LDAP_CA" ] && LDAP_MOUNT="$LDAP_CA:$LDAP_CA:ro" ;; esac
  # OPS-004 (D-570): after an install from a bundle the shipped files under deploy/ are links into ../current
  # (tools/host_tree.py); the doctor read deploy/egress.py and the compose files through them and found nothing.
  # The release tree is mounted where the links point, as install.sh does (tree_args)
  TREE_MOUNT=""
  [ -d "$ROOT_DIR/current" ] && TREE_MOUNT="$(readlink -f "$ROOT_DIR/current"):/app/current:ro"
  # D-621: the doctor's container has no network and no docker, so the host hands in what it cannot see: the
  # environment of the running containers (docker inspect, through a pipe: it holds passwords and is never
  # written to a file) and the pid map's row for the site (the fingerprint and the chart-number rule; no secret)
  PROJECT="${COMPOSE_PROJECT_NAME:-trialbox}"
  RUNNING_IDS="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null | tr '\n' ' ')"
  SITE_ID="$(sed -n 's/^TB_SITE_ID=//p' "$ENV_FILE" | tail -1)"
  PIDMAP_ROW=""
  if [ -n "$RUNNING_IDS" ] && [ -n "$SITE_ID" ]; then
    if PIDMAP_OUT="$(printf '%s\n' "SELECT fingerprint || '|' || coalesce(chartno_rule, '') FROM pidmap.site_key WHERE site_id = :'site'" \
        | docker compose --project-directory "$ROOT_DIR/deploy" exec -T db psql -X -q -tA -v ON_ERROR_STOP=1 \
            -v site="$SITE_ID" -U trialbox -d trialbox_wf 2>/dev/null)"; then
      PIDMAP_ROW="${PIDMAP_OUT:-none}"
    fi
  fi
  # $AUDIT_MOUNTS and $RUNNING_IDS are lists of words by design (the folders' paths hold no space on a box)
  running_env() {
    # shellcheck disable=SC2086
    if [ -n "$RUNNING_IDS" ] && docker inspect $RUNNING_IDS 2>/dev/null; then return 0; fi
    echo '[]'
  }
  doctor_in_image() {
    # shellcheck disable=SC2086
    if docker run --rm --network none --env-file "$ENV_FILE" -i -e TB_HOST_TZ="$HOST_TZ" \
        -e TB_DOCTOR_RUNNING_INSPECT=stdin -e TB_DOCTOR_PIDMAP_ROW="$PIDMAP_ROW" -v "$ROOT_DIR/deploy:/app/deploy:ro" \
        ${TREE_MOUNT:+-v "$TREE_MOUNT"} ${KEK_MOUNT:+-v "$KEK_MOUNT"} ${TERM_MOUNT:+-v "$TERM_MOUNT"} ${LDAP_MOUNT:+-v "$LDAP_MOUNT"} $AUDIT_MOUNTS --user 0:0 \
        "${TB_IMAGE:-trialbox-py:1.0.0}" python -m tools.trialbox doctor "$@"; then
      return 0
    fi
    return 1
  }
  if running_env | doctor_in_image "$@"; then
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

facilities
echo "---"
[ "$FAILS" -eq 0 ] && { echo "host checks passed"; exit 0; } || { echo "$FAILS check(s) failed"; exit 1; }
