#!/bin/bash
# Stand-in for lane D's box installer (deploy/box-install.sh) in the box-run rehearsal. It installs nothing: it keeps
# the ASSUMED interface of deploy/gcp/box-install-run.sh (d_install, d_wizard) and writes down every call.
#   box-install.sh <bundle.tar> --prepare --yes     "installs" up to the first-run wizard
#   box-install.sh --firstrun --answers <file>      the wizard from an answers file: the stand-in stack is "up"
# Anything else is exit 2, as the real installer answers an option it does not know.
B=$BR_S/box; mkdir -p "$B"
[ -t 0 ] && { echo "box-install stand-in: a terminal on stdin: the run must be non-interactive" >&2; exit 3; }
case "$1" in
  --firstrun)
    [ "$2" = --answers ] && [ -s "${3:-}" ] || { echo "box-install: unknown option or no answers file" >&2; exit 2; }
    [ -f "$B/installed" ] || { echo "box-install: this box was not installed by box-install.sh" >&2; exit 1; }
    echo wizard >> "$BR_S/calls.log"
    grep -c . "$3" > "$B/wizard-done"      # the number of answers, never the answers
    echo "==> the owner's answers applied; the stack is up" ;;
  -*) echo "box-install: unknown option $1" >&2; exit 2 ;;
  *)
    [ -f "$1" ] && [ "${2:-}" = --prepare ] && [ "${3:-}" = --yes ] || { echo "box-install: usage" >&2; exit 2; }
    echo install >> "$BR_S/calls.log"
    echo "==> bundle: verify and load"; sha256sum "$1" | cut -c1-16 > "$B/installed"
    echo "==> prepared: the first-run wizard is pending" ;;
esac
