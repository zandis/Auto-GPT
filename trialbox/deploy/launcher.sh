#!/usr/bin/env bash
# TrialBox: the hospital's one command (HS-1). tools/make_bundle.sh writes this file to the stick's root as
# `install`, with the vendor key's fingerprint pinned inside it, beside the signed bundle, the bootstrap with its
# .sig and the vendor's public key. IT types:
#
#   sudo bash /media/<stick>/install
#
# No option. A copy of this file run from elsewhere takes the stick's folder as its one argument (the delivery
# sheet's line: copy it to a private file, print the copy's sha256, compare it with the sheet, run that copy).
# In order, and nothing on the machine is changed before step 4:
#   1. it finds the stick's files (exactly one bundle) and refuses a link, a file too large or a stick path with a
#      space;
#   2. it copies the bootstrap, its .sig and the key to a private folder. Only those copies are used from here on;
#   3. the key's fingerprint must be the one pinned in this file. It is shown, with the question whether it matches
#      the code on the delivery sheet. Only "yes" goes on. "no", any other answer, or no answer stops;
#   4. it checks the copied bootstrap's signature with the copied key (openssl, the vendor's raw Ed25519 signature)
#      and runs that copy in its box form (deploy/bootstrap.sh --box). The bootstrap checks the bundle's signature
#      with the same key before it writes anything.
# A wrong signature stops, with nothing changed. The longer forms (RUNBOOK §1) keep working as they are.
# The whole file is read before any of it runs (main, called on the last line): a stick changed while the question
# waits cannot change what runs. Knobs for the tests only: as deploy/bootstrap.sh (TB_BOOTSTRAP_NO_ROOT=1,
# TB_BOOTSTRAP_ROOT).
set -euo pipefail
# the vendor key's fingerprint, written in by tools/make_bundle.sh when it makes the stick
PIN="@VENDOR_KEY_FINGERPRINT@"
MAX_BYTES=262144  # the bootstrap, its .sig and the key are each far smaller
stop() { printf 'TrialBox: %s\n' "$*" >&2; exit 1; }
# the fingerprint: the first 24 hex digits of the sha256 of the key's DER form, in groups of four
# (the same line is in deploy/bootstrap.sh and tools/make_bundle.sh; a test holds the three together)
fingerprint() { openssl pkey -pubin -in "$1" -outform DER 2>/dev/null | sha256sum | cut -c1-24 | sed 's/..../& /g; s/ $//'; }
is_fingerprint() { [[ "$1" =~ ^([0-9a-f]{4}\ ){5}[0-9a-f]{4}$ ]]; }

main() {
  local stick f ans rc work bundle FP
  local -a bundles=()
  case "$#:${1:-}" in
    0:) stick="$(cd "$(dirname "$0")" && pwd)" ;;
    1:-h|1:--help) sed -n 2,19p "$0"; return 0 ;;
    1:-*) stop "this command takes no option. Type: sudo bash $0" ;;
    1:*) [ -d "$1" ] || stop "$1 is not a folder. Type the stick's folder, for example /media/<stick>"
      stick="$(cd "$1" && pwd)" ;;
    *) stop "this command takes no option. Type: sudo bash $0" ;;
  esac
  is_fingerprint "$PIN" || stop "this copy of the installer was not made for a stick. Call the vendor."
  [ "${TB_BOOTSTRAP_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || stop "run it as the administrator. Type: sudo bash $0"
  for f in openssl sha256sum head; do
    command -v "$f" >/dev/null || stop "this machine has no $f. Install Ubuntu 24.04 on it, then run this again."
  done

  # ------------------------------------------------------------------------------------- 1. the stick's files
  case "$stick" in
    *[[:space:]*?\[]*) stop "the stick's name has a space or a sign the installer cannot use. Rename the stick TRIALBOX, then run this again." ;;
  esac
  shopt -s nullglob
  for f in "$stick"/trialbox-*.tar; do
    case "$(basename "$f")" in trialbox-host.tar) ;; *) bundles+=("$f") ;; esac
  done
  shopt -u nullglob
  [ "${#bundles[@]}" = 1 ] || stop "the stick must hold exactly one TrialBox release. Call the vendor."
  bundle="${bundles[0]}"
  for f in trialbox-bootstrap.sh trialbox-bootstrap.sh.sig vendor_ed25519.pub; do
    [ -e "$stick/$f" ] || [ -L "$stick/$f" ] || stop "the stick has no $f. Call the vendor."
    [ ! -L "$stick/$f" ] && [ -f "$stick/$f" ] || stop "$f on the stick is not a plain file. Call the vendor."
  done

  # ------------------------------------------------------------------------------------ 2. the private copies
  work="$(mktemp -d)"
  # shellcheck disable=SC2064 # the folder's name, fixed now
  trap "rm -rf '$work'" EXIT
  for f in trialbox-bootstrap.sh trialbox-bootstrap.sh.sig vendor_ed25519.pub; do
    head -c "$((MAX_BYTES + 1))" "$stick/$f" > "$work/$f"
    [ "$(wc -c < "$work/$f")" -le "$MAX_BYTES" ] || stop "$f on the stick is too large. Call the vendor."
  done

  # ---------------------------------------------------------------------------------- 3. the key's fingerprint
  FP="$(fingerprint "$work/vendor_ed25519.pub")" || stop "the vendor key on the stick cannot be read. Call the vendor."
  [ "$FP" = "$PIN" ] || stop "the vendor key on the stick is not the key this installer was made for: stopped. Nothing was changed. Call the vendor."
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

  # ----------------------------------------------------------------------- 4. the bootstrap's signature, then it
  openssl pkeyutl -verify -pubin -inkey "$work/vendor_ed25519.pub" -rawin -in "$work/trialbox-bootstrap.sh" \
    -sigfile "$work/trialbox-bootstrap.sh.sig" >/dev/null 2>&1 \
    || stop "the installer on the stick is not signed by this key: stopped. Nothing was changed. Call the vendor."
  echo "  The installer on the stick is signed by this key."
  set +e
  bash "$work/trialbox-bootstrap.sh" "$bundle" --pub "$work/vendor_ed25519.pub" --box
  rc=$?
  set -e
  return "$rc"
}

main "$@"; exit $?  # H-94 not a stop: the bootstrap's own exit code
