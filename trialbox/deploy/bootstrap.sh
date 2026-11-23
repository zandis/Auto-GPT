#!/usr/bin/env bash
# TrialBox: the install's first command (H-22, D-996; RUNBOOK §1). It runs from the USB stick, before the release's
# host tree or any TrialBox file is on the machine, and needs only what Ubuntu 24.04 has: tar, base64, openssl,
# sha256sum and python3's standard library.
#
#   sudo bash trialbox-bootstrap.sh trialbox-<version>.tar --pub <vendor_ed25519.pub, given apart from the stick> \
#       -- --tier large --answers <folder>/site.yaml
#
# Before it runs, RUNBOOK §1 checks this file's own signature (trialbox-bootstrap.sh.sig beside it, the vendor key's
# raw Ed25519 signature) with openssl. Then, in order, and nothing is written until the first two pass:
#   1. the bundle's manifest.json.sig checks with the vendor key given out of band (nothing of the manifest is read
#      before it does);
#   2. files/trialbox-host.tar, the release's host tree, has the sha256 the signed manifest names;
#   3. the tree goes to /opt/trialbox, unpacked beside it and moved whole, never over a folder that holds anything
#      else. A folder that already holds a TrialBox tree is kept: the installer replaces it from the signed bundle;
#   4. the key goes to /opt/trialbox/deploy/keys/vendor_ed25519.pub, where the installer's first step looks for it
#      (refused if a different key is already there);
#   5. deploy/install.sh runs with the bundle and the arguments after `--`; with --box, deploy/box-install.sh does
#      (the box form, HS-1: the stick's `install` launcher, deploy/launcher.sh, runs it so).
# Run it again at any time (an install that stopped is run again by the same command): nothing it did is done twice.
#
# The fingerprint it shows is the one the stick's launcher shows and the delivery sheet carries (HS-1).
# A KEK passphrase goes to the installer after `--` as --kek-passphrase-file FILE (full path) or --kek-passphrase-stdin;
# one in the environment (TB_KEK_PASSPHRASE) is refused before anything (H-96: sudo logs the variables it keeps).
# Knobs for the tests only: TB_BOOTSTRAP_NO_ROOT=1, TB_BOOTSTRAP_ROOT (/opt/trialbox).
set -euo pipefail
die() { echo "trialbox-bootstrap: $*" >&2; exit 1; }
# H-96 (F-45; the integrator's ruling 7094934985): a KEK passphrase in the environment is refused here, before anything
# is read or written, with the words of deploy/kek_passphrase.sh (this file runs before that one is on the machine)
for kp_var in TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE; do
  if [ -n "${!kp_var:-}" ]; then
    echo "trialbox-bootstrap: $kp_var is set in the environment: refused, nothing was changed. A passphrase given by the environment can be in the system journal (sudo logs the variables it keeps, with their values): treat that passphrase as exposed and rotate it (RUNBOOK §23, rotate the KEK passphrase). Give it in a file only root can read: --kek-passphrase-file FILE (a regular file, owned by root, mode 0600), or on stdin: --kek-passphrase-stdin. Then unset $kp_var." >&2
    exit 2
  fi
done
unset TB_KEK_PASSPHRASE TB_KEK_NEW_PASSPHRASE kp_var
# the fingerprint: the first 24 hex digits of the sha256 of the key's DER form, in groups of four
# (the same line is in the stick's launcher and the bundle builder; a test holds the three together)
fingerprint() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-24 | sed 's/..../& /g; s/ $//'; }
usage() {
  echo "usage: sudo bash trialbox-bootstrap.sh trialbox-<version>.tar --pub <vendor key> [--box] [-- <install.sh or box-install.sh options>]" >&2
  exit 2
}
BUNDLE=""; PUB=""; BOX=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pub) [ -n "${2:-}" ] || usage; PUB="$2"; shift ;;
    --box) BOX=1 ;;
    --) shift; break ;;
    -h|--help) sed -n 2,24p "$0"; exit 0 ;;
    -*) echo "trialbox-bootstrap: unknown option $1 (the installer's options go after --)" >&2; usage ;;
    *) [ -z "$BUNDLE" ] || usage; BUNDLE="$1" ;;
  esac
  shift
done
[ -n "$BUNDLE" ] && [ -n "$PUB" ] || usage
[ "${TB_BOOTSTRAP_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root (sudo bash $0 ...)"
[ -f "$BUNDLE" ] || die "no such bundle: $BUNDLE"
[ -f "$PUB" ] || die "--pub: no such file: $PUB"
for tool in tar base64 openssl sha256sum python3; do
  command -v "$tool" >/dev/null || die "this machine has no $tool (Ubuntu 24.04 has it: RUNBOOK §1 step 1)"
done
BUNDLE="$(cd "$(dirname "$BUNDLE")" && pwd)/$(basename "$BUNDLE")"
# the installer's update step refuses such a path late, after the tree is unpacked: refused here, before anything
case "$BUNDLE" in
  *[[:space:]*?\[]*) die "the bundle's path has a space or a glob character: $BUNDLE. Rename the stick TRIALBOX (nothing was changed)" ;;
esac
ROOT="${TB_BOOTSTRAP_ROOT:-/opt/trialbox}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ----------------------------------------------------------------------------------------- 1. the signed manifest
tar -xf "$BUNDLE" -C "$WORK" --no-same-owner manifest.json manifest.json.sig 2>/dev/null \
  || die "$(basename "$BUNDLE") is not a TrialBox bundle (no manifest.json and manifest.json.sig)"
base64 -d "$WORK/manifest.json.sig" > "$WORK/sig.raw" 2>/dev/null || die "manifest.json.sig is not base64"
openssl pkeyutl -verify -pubin -inkey "$PUB" -rawin -in "$WORK/manifest.json" -sigfile "$WORK/sig.raw" >/dev/null 2>&1 \
  || die "the bundle's signature does not check with the vendor key $PUB: the bundle is refused"
echo "bundle: signed by the vendor key (fingerprint: $(fingerprint "$PUB"))"

# ----------------------------------------------------------------------------------------------- 2. the host tree
HOST="$(python3 -I -c '
import json, re, sys
hosts = [f for f in json.load(open(sys.argv[1], encoding="utf-8"))["files"] if f.get("kind") == "host"]
if len(hosts) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]+", hosts[0]["path"]) \
        or not re.fullmatch(r"[0-9a-f]{64}", hosts[0]["sha256"]):
    sys.exit("the signed manifest names no single host tree")
print(hosts[0]["path"], hosts[0]["sha256"])
' "$WORK/manifest.json")" || die "the signed manifest names no host tree (a bundle from before T-631)"
HOST_NAME="${HOST% *}"; HOST_SHA="${HOST#* }"
tar -xf "$BUNDLE" -C "$WORK" --no-same-owner "files/$HOST_NAME" 2>/dev/null || die "the bundle carries no files/$HOST_NAME"
[ "$(sha256sum "$WORK/files/$HOST_NAME" | cut -d' ' -f1)" = "$HOST_SHA" ] \
  || die "files/$HOST_NAME does not have the sha256 the signed manifest names: the bundle is refused"

# ---------------------------------------------------------------------------------------------- 3. /opt/trialbox
if [ -f "$ROOT/deploy/install.sh" ]; then
  echo "kept: $ROOT already holds a TrialBox host tree (the installer replaces it from the signed bundle)"
elif [ -e "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
  die "$ROOT exists and is not a TrialBox host tree: it is not replaced"
else
  part="$ROOT.unpacking"   # unpacked beside the folder and moved whole: an interrupted unpack never looks like a tree
  rm -rf "$part"
  mkdir -p "$part"
  tar -xf "$WORK/files/$HOST_NAME" -C "$part" --no-same-owner || die "the host tree did not unpack"
  [ -f "$part/deploy/install.sh" ] || { rm -rf "$part"; die "the host tree carries no deploy/install.sh"; }
  [ ! -d "$ROOT" ] || rmdir "$ROOT"   # an empty folder only (checked above)
  mv "$part" "$ROOT"
  echo "unpacked: the release's host tree to $ROOT"
fi

# ------------------------------------------------------------------------------------------------- 4. the key
KEY="$ROOT/deploy/keys/vendor_ed25519.pub"
if [ -f "$KEY" ]; then
  cmp -s "$KEY" "$PUB" || die "the vendor key already at $KEY differs from $PUB: nothing was changed"
else
  mkdir -p "$(dirname "$KEY")"
  cp "$PUB" "$KEY"
  chmod 0644 "$KEY"
  echo "placed: the vendor key at $KEY"
fi

# -------------------------------------------------------------------------------------------- 5. the installer
cd "$ROOT"
rm -rf "$WORK"   # exec below replaces this shell, so the EXIT trap would never run (HS-1 finding)
trap - EXIT
if [ "$BOX" = 1 ]; then
  [ -f "$ROOT/deploy/box-install.sh" ] || die "the host tree at $ROOT carries no deploy/box-install.sh"
  echo "running: $ROOT/deploy/box-install.sh $BUNDLE $*"
  exec bash "$ROOT/deploy/box-install.sh" "$BUNDLE" "$@"
fi
echo "running: $ROOT/deploy/install.sh $BUNDLE $*"
exec bash "$ROOT/deploy/install.sh" "$BUNDLE" "$@"
