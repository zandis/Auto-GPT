#!/usr/bin/env bash
# TrialBox: prepare a bare Ubuntu 24.04 box from the offline media (OPS-006, D-966), as root, before box-install.sh.
#
#   sudo bash <media>/linux/box-prepare.sh <media> --pub <the vendor key given to you apart from the disk>
#
# <media> is the TRIALBOX-<version> folder that tools/linux_media.py built and signed. In order, and nothing is
# installed until the first three pass:
#   1. the system is Ubuntu 24.04;
#   2. the media's vendor key is the one given out of band, SHA256SUMS carries its signature (openssl: a bare Ubuntu
#      has it), every file on the disk is listed there and matches, and nothing unlisted is there;
#   3. the packages of linux/debs install with dpkg (no network): Docker Engine, the compose plugin, the NVIDIA
#      Container Toolkit and the Linux NVIDIA driver, nftables, cron, python3's yaml and cryptography, avahi-daemon;
#   4. Docker starts with the box and gets the nvidia runtime (on a box with an NVIDIA card); cron starts;
#   5. the release's host tree goes to /opt/trialbox (never over a folder that holds something else), with the key.
# It ends with what to run next: a restart first when the driver is not loaded yet, then deploy/box-install.sh with
# the media's bundle. Run it again at any time: nothing it did is undone or done twice. The disk's unlock rule
# (HW-010) is not here: it waits on the owner's decision.
#
# Knobs for the tests only: TB_PREPARE_NO_ROOT=1, TB_PREPARE_OS_RELEASE (/etc/os-release), TB_PREPARE_ROOT
# (/opt/trialbox), TB_PREPARE_GPU (1 or 0 instead of looking for an NVIDIA card).
set -euo pipefail
die() { echo "box-prepare: $*" >&2; exit 1; }
usage() { echo "usage: box-prepare.sh <media folder> --pub <the vendor key given to you apart from the disk>" >&2; exit 2; }
MEDIA=""; PUB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pub) [ -n "${2:-}" ] || usage; PUB="$2"; shift ;;
    -h|--help) sed -n 2,20p "$0"; exit 0 ;;
    -*) echo "box-prepare: unknown option $1" >&2; usage ;;
    *) MEDIA="$1" ;;
  esac
  shift
done
[ -n "$MEDIA" ] && [ -n "$PUB" ] || usage
[ "${TB_PREPARE_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root (sudo bash $0 ...)"
MEDIA="$(cd "$MEDIA" && pwd)" || die "no such media folder"
ROOT="${TB_PREPARE_ROOT:-/opt/trialbox}"
LINUX="$MEDIA/linux"

# ---------------------------------------------------------------------------------------------------- 1. system
OSR="${TB_PREPARE_OS_RELEASE:-/etc/os-release}"
os_field() { sed -n "s/^$1=//p" "$OSR" | head -1 | tr -d "\"'"; }
os_id="$(os_field ID)"; os_ver="$(os_field VERSION_ID)"
[ "$os_id" = ubuntu ] && [ "$os_ver" = 24.04 ] || die "this media is for Ubuntu 24.04; this machine runs ${os_id:-?} ${os_ver:-?}"

# ------------------------------------------------------------------------------------------------------ 2. media
[ -f "$PUB" ] || die "--pub: no such file: $PUB"
[ -f "$LINUX/vendor_ed25519.pub" ] || die "the media has no linux/vendor_ed25519.pub"
cmp -s "$PUB" "$LINUX/vendor_ed25519.pub" || die "the vendor key on the media is not the one given to you: the media is refused"
[ -f "$MEDIA/SHA256SUMS" ] && [ -f "$MEDIA/SHA256SUMS.sig" ] || die "the media has no SHA256SUMS or no SHA256SUMS.sig: it was not signed"
openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$MEDIA/SHA256SUMS" -sigfile "$MEDIA/SHA256SUMS.sig" >/dev/null 2>&1 \
  || die "the signature over SHA256SUMS does not check with the vendor key: the media is refused"
(cd "$MEDIA" && sha256sum --quiet --strict -c SHA256SUMS) || die "a file on the media does not match SHA256SUMS (above): the media is refused"
unlisted="$(cd "$MEDIA" && find . -type f ! -name SHA256SUMS ! -name SHA256SUMS.sig | sed 's#^\./##' | sort \
  | comm -23 - <(sed 's/^[0-9a-f]\{64\}  //' SHA256SUMS | sort))"
[ -z "$unlisted" ] || die "files on the media that SHA256SUMS does not list: $(echo "$unlisted" | tr '\n' ' ')- the media is refused"
shopt -s nullglob
debs=("$LINUX"/debs/*.deb)
bundles=()
for f in "$LINUX"/trialbox-*.tar; do [ "$(basename "$f")" = trialbox-host.tar ] || bundles+=("$f"); done
[ "${#debs[@]}" -gt 0 ] || die "the media carries no package (linux/debs)"
[ "${#bundles[@]}" = 1 ] || die "the media should carry exactly one bundle (linux/trialbox-<version>.tar), found ${#bundles[@]}"
[ -f "$LINUX/trialbox-host.tar" ] || die "the media has no linux/trialbox-host.tar"
echo "media: signed by the vendor key, ${#debs[@]} packages, bundle $(basename "${bundles[0]}")"

# --------------------------------------------------------------------------------------------------- 3. packages
DEBIAN_FRONTEND=noninteractive dpkg -i --skip-same-version "${debs[@]}" || die "the packages did not install (dpkg, above)"
command -v docker >/dev/null || die "the packages carried no Docker Engine"

# ----------------------------------------------------------------------------------------------- 4. the services
gpu="${TB_PREPARE_GPU:-}"
if [ -z "$gpu" ]; then
  gpu=0
  for v in /sys/bus/pci/devices/*/vendor; do [ "$(cat "$v")" = 0x10de ] && gpu=1; done
fi
systemctl enable docker >/dev/null || die "docker.service could not be enabled"
runtimes() { docker info --format '{{range $k, $v := .Runtimes}}{{$k}} {{end}}' 2>/dev/null; }
if [ "$gpu" = 1 ]; then
  command -v nvidia-ctk >/dev/null || die "the packages carried no NVIDIA Container Toolkit"
  if runtimes | grep -qw nvidia; then
    echo "Docker already has the nvidia runtime: not restarted"   # never restarts Docker under a live stack
  else
    nvidia-ctk runtime configure --runtime=docker || die "nvidia-ctk could not configure Docker"
    systemctl restart docker || die "docker.service did not start"
  fi
  runtimes | grep -qw nvidia || die "Docker does not list the nvidia runtime"
else
  echo "box-prepare: warning: no NVIDIA card on this machine; Docker has no nvidia runtime" >&2
  systemctl start docker || die "docker.service did not start"
fi
systemctl enable --now cron >/dev/null 2>&1 || echo "box-prepare: warning: cron is not enabled (the backup's schedule needs it)" >&2
echo "Docker Engine $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"

# ---------------------------------------------------------------------------------------------- 5. the host tree
if [ -f "$ROOT/deploy/box-install.sh" ]; then
  echo "kept: $ROOT is already there"
elif [ -e "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
  die "$ROOT exists and is not a TrialBox host tree: it is not replaced"
else
  part="$ROOT.unpacking"   # unpacked beside the folder and moved whole: an interrupted unpack never looks like a tree
  rm -rf "$part"
  mkdir -p "$part"
  tar -xf "$LINUX/trialbox-host.tar" -C "$part" --no-same-owner || die "the host tree did not unpack"
  [ -f "$part/deploy/box-install.sh" ] || die "the host tree carries no deploy/box-install.sh"
  [ ! -d "$ROOT" ] || rmdir "$ROOT"   # an empty folder only (checked above)
  mv "$part" "$ROOT"
  echo "unpacked: $ROOT"
fi
key="$ROOT/deploy/keys/vendor_ed25519.pub"
if [ -f "$key" ]; then
  cmp -s "$key" "$PUB" || die "the vendor key on the media differs from the one already at $key"
else
  mkdir -p "$(dirname "$key")"
  cp "$PUB" "$key"
fi

# ----------------------------------------------------------------------------------------------------- next step
echo
echo "This machine is prepared."
if [ "$gpu" = 1 ] && ! nvidia-smi >/dev/null 2>&1; then
  echo "The NVIDIA driver loads after a restart: reboot now, then run:"
else
  echo "Next, run:"
fi
echo "  sudo $ROOT/deploy/box-install.sh ${bundles[0]}"
