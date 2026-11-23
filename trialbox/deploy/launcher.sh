#!/usr/bin/env bash
# TrialBox: the hospital's one command (HS-1). tools/make_bundle.sh copies this file to the stick's root as
# `install`, beside the signed bundle, the bootstrap with its .sig and the vendor's public key. IT types:
#
#   sudo bash /media/<stick>/install
#
# No option. In order, and nothing on the machine is changed before step 3:
#   1. it finds the stick's four files beside itself (exactly one bundle);
#   2. it shows the vendor key's fingerprint and asks whether it matches the code on the delivery sheet.
#      Only "yes" goes on. "no", any other answer, or no answer (standard input closed) stops;
#   3. it copies the bootstrap and the key to a private folder, checks the bootstrap's signature there with the key
#      (openssl, the vendor's raw Ed25519 signature) and runs that copy in its box form (deploy/bootstrap.sh --box).
#      The bootstrap checks the bundle's signature with the same key before it writes anything.
# A wrong signature stops here, with nothing changed. The longer forms (RUNBOOK §1) keep working as they are.
# Knobs for the tests only: as deploy/bootstrap.sh (TB_BOOTSTRAP_NO_ROOT=1, TB_BOOTSTRAP_ROOT).
set -euo pipefail
stop() { printf 'TrialBox: %s\n' "$*" >&2; exit 1; }
# the fingerprint: the first 24 hex digits of the sha256 of the key's DER form, in groups of four
# (the same line is in deploy/bootstrap.sh and tools/make_bundle.sh; a test holds the three together)
fingerprint() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-24 | sed 's/..../& /g; s/ $//'; }
case "${1:-}" in
  "") ;;
  -h|--help) sed -n 2,15p "$0"; exit 0 ;;
  *) stop "this command takes no option. Type: sudo bash $0" ;;
esac
[ "${TB_BOOTSTRAP_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || stop "run it as the administrator. Type: sudo bash $0"
for tool in openssl sha256sum; do
  command -v "$tool" >/dev/null || stop "this machine has no $tool. Install Ubuntu 24.04 on it, then run this again."
done
STICK="$(cd "$(dirname "$0")" && pwd)"

# --------------------------------------------------------------------------------------- 1. the stick's files
shopt -s nullglob
bundles=()
for f in "$STICK"/trialbox-*.tar; do
  case "$(basename "$f")" in trialbox-host.tar) ;; *) bundles+=("$f") ;; esac
done
shopt -u nullglob
[ "${#bundles[@]}" = 1 ] || stop "the stick must hold exactly one TrialBox release. Call the vendor."
BUNDLE="${bundles[0]}"
for f in trialbox-bootstrap.sh trialbox-bootstrap.sh.sig vendor_ed25519.pub; do
  [ -f "$STICK/$f" ] || stop "the stick has no $f. Call the vendor."
done

# ------------------------------------------------------------------------------------ 2. the key's fingerprint
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$STICK/vendor_ed25519.pub" "$STICK/trialbox-bootstrap.sh" "$STICK/trialbox-bootstrap.sh.sig" "$WORK/"
FP="$(fingerprint "$WORK/vendor_ed25519.pub")"
[ "${#FP}" = 29 ] || stop "the vendor key on the stick cannot be read. Call the vendor."
echo
echo "  Vendor key fingerprint:  $FP"
echo
echo "  Compare it with the code on the delivery sheet."
printf '  Type yes if they are the same, no if not: '
ans=""
read -r ans || { echo; stop "no answer: stopped. Nothing was changed. Run the command again and type yes or no."; }
case "$ans" in
  yes|YES|Yes|y|Y) ;;
  *) stop "the fingerprint was not confirmed: stopped. Nothing was changed. Call the vendor." ;;
esac

# ------------------------------------------------------------------------- 3. the bootstrap's signature, then it
openssl pkeyutl -verify -pubin -inkey "$WORK/vendor_ed25519.pub" -rawin -in "$WORK/trialbox-bootstrap.sh" \
  -sigfile "$WORK/trialbox-bootstrap.sh.sig" >/dev/null 2>&1 \
  || stop "the installer on the stick is not signed by this key: stopped. Nothing was changed. Call the vendor."
echo "  The installer on the stick is signed by this key."
set +e
bash "$WORK/trialbox-bootstrap.sh" "$BUNDLE" --pub "$WORK/vendor_ed25519.pub" --box
rc=$?
set -e
exit "$rc"
