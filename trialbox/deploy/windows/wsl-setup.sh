#!/usr/bin/env bash
# TrialBox: the steps of the Windows installer that run inside WSL2, as root (NEW-WIN-1, D-600).
# deploy/windows/box-install.ps1 calls one step at a time and logs what each prints:
#
#   wsl-setup.sh wslconf                 /etc/wsl.conf gets [boot] systemd=true; prints "changed" or "kept"
#   wsl-setup.sh pid1                    prints the name of process 1 (systemd, once the distribution restarted)
#   wsl-setup.sh no-linux-driver         fails when a Linux NVIDIA driver is installed or loaded (WSL2 uses the
#                                        Windows driver; a Linux one breaks it: plan v7.2 section 2.3 rule 3)
#   wsl-setup.sh packages DEBS_DIR       Docker Engine, the compose plugin and the NVIDIA Container Toolkit from the
#                                        media's packages (no network); Docker gets the nvidia runtime and starts
#   wsl-setup.sh gpu                     a container started with --gpus all sees the card; prints the card's line
#   wsl-setup.sh host-tree TAR PUBKEY    the release's host tree to /opt/trialbox, never over an existing folder
#   wsl-setup.sh install BUNDLE [--yes]  deploy/box-install.sh in this terminal (the first-run code, the owner's wait)
#   wsl-setup.sh state                   prints installed=1 once box-install.sh has said the box is ready
#   wsl-setup.sh boot-check              Docker and the stack are enabled to start with the distribution (NEW-WIN-2)
#
# Every step may be run again. None removes or replaces a file it did not write.
# Knobs for the tests only: TB_WSL_ETC (/etc), TB_WSL_PROC (/proc), TB_WSL_ROOT (/opt/trialbox), TB_WSL_SMI (the
# Windows driver's nvidia-smi), TB_WSL_NO_ROOT=1.
set -euo pipefail
ETC="${TB_WSL_ETC:-/etc}"
PROC="${TB_WSL_PROC:-/proc}"
ROOT="${TB_WSL_ROOT:-/opt/trialbox}"
SMI="${TB_WSL_SMI:-/usr/lib/wsl/lib/nvidia-smi}"
PROBE_IMAGE="trialbox-gpu-probe:local"
DONE_MARK="$ROOT/deploy/site/box/windows-install-done"
READY_LINE="TrialBox is ready"   # the last line of deploy/box-install.sh (tests/unit/test_windows_box_install.py)
# packages of a Linux NVIDIA driver; the container toolkit's own packages (nvidia-container-toolkit,
# libnvidia-container1, libnvidia-container-tools) are not among them
DRIVER_RE='^(nvidia-driver-|nvidia-dkms-|nvidia-kernel-|nvidia-headless-|nvidia-utils-|nvidia-compute-utils-|libnvidia-compute-|libnvidia-gl-|libnvidia-cfg|xserver-xorg-video-nvidia|cuda-drivers)'
die() { echo "wsl-setup: $*" >&2; exit 1; }
[ "${TB_WSL_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root"
STEP="${1:-}"; [ $# -gt 0 ] && shift

case "$STEP" in
  wslconf)
    f="$ETC/wsl.conf"
    python3 - "$f" <<'EOP'
import configparser, pathlib, shutil, sys
p = pathlib.Path(sys.argv[1])
c = configparser.ConfigParser(strict=False)
c.optionxform = str  # keep the keys' case
if p.exists():
    c.read(p, encoding="utf-8")
if c.get("boot", "systemd", fallback="").strip().lower() == "true":
    print("kept")
    sys.exit(0)
if p.exists() and not p.with_name("wsl.conf.before-trialbox").exists():
    shutil.copy2(p, p.with_name("wsl.conf.before-trialbox"))
if not c.has_section("boot"):
    c.add_section("boot")
c.set("boot", "systemd", "true")
with p.open("w", encoding="utf-8") as fh:
    c.write(fh, space_around_delimiters=False)
print("changed")
EOP
    ;;
  pid1)
    cat "$PROC/1/comm"
    ;;
  no-linux-driver)
    found="$(dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' 2>/dev/null | awk '$1 ~ /^.i/ {print $2}' | grep -E "$DRIVER_RE" | head -5 | tr '\n' ' ' || true)"
    [ -z "$found" ] || die "a Linux NVIDIA driver is installed in WSL2: ${found}(WSL2 uses the Windows driver; remove these packages)"
    [ ! -e "$PROC/driver/nvidia/version" ] || die "a Linux NVIDIA kernel driver is loaded in WSL2 ($PROC/driver/nvidia/version)"
    echo "no Linux NVIDIA driver"
    ;;
  packages)
    debs="${1:-}"; [ -d "$debs" ] || die "no such folder of packages: $debs"
    shopt -s nullglob
    files=("$debs"/*.deb)
    [ "${#files[@]}" -gt 0 ] || die "no package in $debs"
    for f in "${files[@]}"; do
      name="$(basename "$f")"
      if printf '%s\n' "${name%%_*}" | grep -Eq "$DRIVER_RE"; then
        die "the media carries a Linux NVIDIA driver package ($name): it is never installed in WSL2"
      fi
    done
    DEBIAN_FRONTEND=noninteractive dpkg -i --skip-same-version "${files[@]}" || die "the packages did not install (dpkg, above)"
    command -v docker >/dev/null || die "the packages carried no Docker Engine"
    command -v nvidia-ctk >/dev/null || die "the packages carried no NVIDIA Container Toolkit"
    nvidia-ctk runtime configure --runtime=docker || die "nvidia-ctk could not configure Docker"
    systemctl enable docker >/dev/null || die "docker.service could not be enabled"
    systemctl restart docker || die "docker.service did not start"
    systemctl enable --now cron >/dev/null 2>&1 || echo "wsl-setup: warning: cron is not enabled (the backup's schedule needs it)" >&2
    docker info --format '{{range $k, $v := .Runtimes}}{{$k}} {{end}}' | grep -qw nvidia || die "Docker does not list the nvidia runtime"
    echo "Docker Engine $(docker version --format '{{.Server.Version}}') with the nvidia runtime"
    ;;
  gpu)
    [ -x "$SMI" ] || die "the Windows NVIDIA driver is not visible in WSL2 ($SMI is missing): install or update the driver on Windows"
    q=("--query-gpu=name,driver_version,memory.total" "--format=csv,noheader")
    "$SMI" "${q[@]}" >/dev/null || die "the Windows NVIDIA driver does not answer inside WSL2 ($SMI)"
    if ! docker image inspect "$PROBE_IMAGE" >/dev/null 2>&1; then
      # a probe image from this system's own files (no image is on the box yet, and none is downloaded): the
      # driver's nvidia-smi and the C library it needs. The driver's own libraries are left out on purpose: the
      # container gets them only from the NVIDIA Container Toolkit, which is what this step proves.
      tmp="$(mktemp -d)"
      mkdir -p "$tmp/probe" "$tmp/etc" "$tmp/tmp"
      cp "$SMI" "$tmp/probe/nvidia-smi"
      mapfile -t libs < <(ldd "$SMI" | awk '$2 == "=>" && $3 ~ /^\// {print $3} $1 ~ /^\// {print $1}' | grep -v '^/usr/lib/wsl/' | sed 's#^/##' | sort -u)
      [ "${#libs[@]}" -gt 0 ] || die "could not read which libraries $SMI needs (ldd)"
      tar -c -h -C / "${libs[@]}" -C "$tmp" probe etc tmp | docker import - "$PROBE_IMAGE" >/dev/null || die "could not build the probe image"
      rm -rf "$tmp"
    fi
    out="$(docker run --rm --network none --gpus all "$PROBE_IMAGE" /probe/nvidia-smi "${q[@]}" 2>&1)" \
      || die "no container sees the card (docker run --gpus all): $(printf '%s' "$out" | tail -1)"
    printf '%s\n' "$out" | tail -1
    ;;
  host-tree)
    tarf="${1:-}"; pub="${2:-}"
    [ -f "$tarf" ] && [ -f "$pub" ] || die "usage: wsl-setup.sh host-tree TAR PUBKEY"
    if [ -f "$ROOT/deploy/box-install.sh" ]; then
      echo "kept: $ROOT is already there"
    elif [ -e "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
      die "$ROOT exists and is not a TrialBox host tree: it is not replaced"
    else
      mkdir -p "$ROOT"
      tar -xf "$tarf" -C "$ROOT" --no-same-owner || die "the host tree did not unpack"
      [ -f "$ROOT/deploy/box-install.sh" ] || die "the host tree carries no deploy/box-install.sh"
      echo "unpacked: $ROOT"
    fi
    key="$ROOT/deploy/keys/vendor_ed25519.pub"
    if [ -f "$key" ]; then
      cmp -s "$key" "$pub" || die "the vendor key on the media differs from the one already at $key"
    else
      mkdir -p "$(dirname "$key")"
      cp "$pub" "$key"
    fi
    echo "vendor key sha256 $(sha256sum "$key" | cut -d' ' -f1)"
    ;;
  install)
    bundle="${1:-}"; yes="${2:-}"
    [ -f "$ROOT/deploy/box-install.sh" ] || die "no host tree at $ROOT (step host-tree)"
    if [ -f "$DONE_MARK" ]; then echo "TrialBox is already installed here ($DONE_MARK): nothing was changed"; exit 0; fi
    args=()
    if [ -f "$ROOT/deploy/site/box/answers.json" ] && grep -q "TrialBox is running" "$ROOT/deploy/site/box/install.log" 2>/dev/null; then
      args=(--firstrun)   # an earlier run installed the stack and stopped before the owner finished the set-up
    else
      if [ ! -r "$bundle" ]; then
        # the media is a drive WSL2 did not mount by itself (a USB disk): mount it read-only
        case "$bundle" in /mnt/[a-z]/*) l="${bundle#/mnt/}"; l="${l%%/*}" ;; *) die "no such bundle: $bundle" ;; esac
        mkdir -p "/mnt/$l"
        mount -t drvfs "${l^^}:" "/mnt/$l" -o ro || die "the media's drive ${l^^}: could not be mounted in WSL2"
        [ -r "$bundle" ] || die "no such bundle: $bundle"
      fi
      args=("$bundle"); [ "$yes" != "--yes" ] || args+=(--yes)
    fi
    work="$(mktemp -d)"
    mkfifo "$work/pipe"
    # the window shows every byte as it comes (tee does not wait for a line end: the installer asks a question);
    # the reader keeps nothing but how often the last line came, so the first-run code is never written anywhere
    grep -c "$READY_LINE" < "$work/pipe" > "$work/seen" &
    reader=$!
    set +e
    bash "$ROOT/deploy/box-install.sh" "${args[@]}" | tee "$work/pipe"
    rc="${PIPESTATUS[0]}"
    wait "$reader"
    set -e
    if [ "$(cat "$work/seen")" != 0 ]; then mkdir -p "$(dirname "$DONE_MARK")"; date -u +%FT%TZ > "$DONE_MARK"; fi
    rm -rf "$work"
    exit "$rc"
    ;;
  state)
    if [ -f "$DONE_MARK" ]; then echo "installed=1"; else echo "installed=0"; fi
    ;;
  boot-check)
    off=""
    for u in docker.service trialbox.service; do
      [ "$(systemctl is-enabled "$u" 2>/dev/null || true)" = enabled ] || off="$off $u"
    done
    [ -z "$off" ] || die "not enabled to start with the distribution:$off (after a restart TrialBox would stay down)"
    echo "docker.service and trialbox.service start with the distribution"
    ;;
  *)
    die "unknown step '${STEP}' (see the head of this file)"
    ;;
esac
