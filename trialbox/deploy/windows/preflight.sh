#!/usr/bin/env bash
# TrialBox pre-flight check inside the WSL2 Ubuntu of the Windows workstation (D-125, D-138). Groundwork for the
# offline installer, which is built after the platform. Run deploy/windows/preflight.ps1 on Windows first.
#
#   bash deploy/windows/preflight.sh [DATA_DIR]       # default DATA_DIR: /opt/trialbox (or / when it does not exist)
#
# Prints one PASS or FAIL line per check, exits 1 when any check fails. Reads only; changes nothing; no network.
# Thresholds: TB_MIN_FREE_GB (500), TB_MIN_RAM_GB (32: what WSL2 itself is given), TB_MIN_WIN_BUILD (22000).
# TB_PREFLIGHT_PROC replaces /proc in the tests.
set -u
DATA="${1:-/opt/trialbox}"; [ -d "$DATA" ] || DATA=/
PROC="${TB_PREFLIGHT_PROC:-/proc}"
MIN_FREE="${TB_MIN_FREE_GB:-500}"; MIN_RAM="${TB_MIN_RAM_GB:-32}"; MIN_BUILD="${TB_MIN_WIN_BUILD:-22000}"
FAILED=0
line() { if [ "$1" = 0 ]; then echo "PASS  $2: $3"; else echo "FAIL  $2: $3"; FAILED=$((FAILED + 1)); fi; }

# 1. WSL2, not WSL1 and not a plain Linux machine
rel="$(cat "$PROC/sys/kernel/osrelease" 2>/dev/null || true)"
case "$rel" in *microsoft*WSL2*|*WSL2*microsoft*|*-microsoft-standard-WSL2*) ok=0 ;; *) ok=1 ;; esac
line "$ok" "WSL2" "kernel ${rel:-unknown}"

# 2. Windows build, from the Windows side (interop: cmd.exe /c ver)
ver="$(cmd.exe /c ver 2>/dev/null | tr -d '\r' | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' | head -1 || true)"
build="$(printf '%s' "$ver" | cut -d. -f3)"
if [ -n "$build" ] && [ "$build" -ge "$MIN_BUILD" ] 2>/dev/null; then ok=0; else ok=1; fi
line "$ok" "Windows build" "${ver:-unknown (Windows interop off?)}; need $MIN_BUILD or later (Server 2022: TB_MIN_WIN_BUILD=20348)"

# 3. CPU virtualisation: WSL2 runs in a VM, so a WSL2 kernel proves it; the CPU flags say which kind
flags="$(grep -m1 -o -w 'vmx\|svm\|hypervisor' "$PROC/cpuinfo" 2>/dev/null | head -1 || true)"
case "$rel" in *WSL2*) ok=0; inwsl=yes ;; *) inwsl=no; [ -n "$flags" ] && ok=0 || ok=1 ;; esac
line "$ok" "CPU virtualisation" "${flags:-no vmx/svm/hypervisor flag}; running in WSL2: $inwsl"

# 4. GPU driver: the Windows driver, seen through /usr/lib/wsl/lib (never install a Linux driver in WSL2)
SMI="$(command -v nvidia-smi || echo /usr/lib/wsl/lib/nvidia-smi)"
gpu="$("$SMI" --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)"
[ -n "$gpu" ] && ok=0 || ok=1
line "$ok" "GPU driver" "${gpu:-nvidia-smi sees no card (install the NVIDIA driver on Windows)}"

# 5. Disk space where the box will live (images and models about 30 GB; data and local backups the rest)
free="$(df -Pk "$DATA" 2>/dev/null | awk 'NR==2 {print int($4/1048576)}')"
[ "${free:-0}" -ge "$MIN_FREE" ] && ok=0 || ok=1
line "$ok" "Disk space" "${free:-0} GB free at $DATA (need $MIN_FREE GB)"

# 6. Memory given to WSL2 (.wslconfig [wsl2] memory=)
ram="$(awk '/^MemTotal:/ {print int($2/1048576)}' "$PROC/meminfo" 2>/dev/null)"
[ "${ram:-0}" -ge "$MIN_RAM" ] && ok=0 || ok=1
line "$ok" "Memory" "${ram:-0} GB in WSL2 (need $MIN_RAM GB; raise memory= in .wslconfig)"

# 7. systemd in WSL2 (Docker Engine and the nightly timers need it: /etc/wsl.conf [boot] systemd=true)
[ "$(cat "$PROC/1/comm" 2>/dev/null)" = systemd ] && ok=0 || ok=1
line "$ok" "systemd" "PID 1 is $(cat "$PROC/1/comm" 2>/dev/null || echo unknown)"

if [ "$FAILED" -gt 0 ]; then echo "$FAILED check(s) FAILED: fix them before installing (docs/handover/WINDOWS-INSTALL-CHECKLIST.md)"; exit 1; fi
echo "all checks passed"
