#!/usr/bin/env bash
# Several TEST boxes side by side on one host (card H-106; docs/runbook/test-boxes.md). A plain script: no agent.
#
#   sudo tools/testboxes.sh up BUNDLE --pub KEY [--parent DIR] [--answers FILE] SPEC...
#   sudo tools/testboxes.sh list
#   sudo tools/testboxes.sh remove NAME [--yes]
#
# SPEC is NAME:OFFSET[:CARDS[:GB[:PROFILE]]], for example
#   walk:1:0                   box "walk", ports +10, card 0, no cap
#   p32:2:1:32:rtx5090         box "p32", ports +20, card 1, capped to 32 GB, the rtx5090 profile
#   cpu:5                      box "cpu", ports +50, no card (the stub models)
# Each box NAME is installed from the one signed BUNDLE into DIR/NAME (default /opt/trialbox-test/NAME): the bootstrap
# checks the bundle with the vendor key and unpacks its host tree there, then that folder's deploy/install.sh runs
# with --test-box NAME --port-offset OFFSET (and --gpus, --gpu-mem-gb, --gpu) --environment TEST --yes. One box at a
# time (they share the engine's image store); each box's output is in DIR/NAME.install.log.
# `list` shows every box on this host (from the container engine). `remove NAME` takes one test box away whole: its
# containers, networks and volumes (by its own project's label only) and its folder; never another box (refused for
# a box that is not a test box of that name). Without --yes it says what it would remove.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
usage() { sed -n 2,6p "$0" >&2; exit 2; }
py() { (cd "$HERE" && python3 -m tools.trialbox.testbox "$@"); }
[ $# -ge 1 ] || usage
cmd="$1"; shift
case "$cmd" in
  list) py list; exit $? ;;
  remove)
    [ $# -ge 1 ] || usage
    name="$1"; shift
    py remove --name "$name" "$@"; exit $? ;;
  up) ;;
  *) usage ;;
esac
[ $# -ge 1 ] || usage
BUNDLE="$1"; shift
PUB=""; PARENT=/opt/trialbox-test; ANSWERS=""; SPECS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --pub) PUB="${2:-}"; shift ;;
    --parent) PARENT="${2:-}"; shift ;;
    --answers) ANSWERS="${2:-}"; shift ;;
    -*) echo "testboxes: unknown option $1" >&2; exit 2 ;;
    *) SPECS+=("$1") ;;
  esac
  shift
done
[ -n "$PUB" ] && [ -f "$PUB" ] || { echo "testboxes: --pub KEY: the vendor key, given apart from the bundle" >&2; exit 2; }
[ -f "$BUNDLE" ] || { echo "testboxes: no such bundle: $BUNDLE" >&2; exit 2; }
[ "${#SPECS[@]}" -gt 0 ] || usage
case "$PARENT" in /*) ;; *) echo "testboxes: --parent must be a full path" >&2; exit 2 ;; esac
mkdir -p "$PARENT" || exit 2
failed=0
for spec in "${SPECS[@]}"; do
  IFS=: read -r name offset cards gb profile <<< "$spec"
  args=(--test-box "$name" --port-offset "$offset" --environment TEST --yes)
  if [ -n "$cards" ]; then args+=(--mode gpu --gpus "$cards"); else args+=(--mode stub); fi
  [ -z "$gb" ] || args+=(--gpu-mem-gb "$gb")
  [ -z "$profile" ] || args+=(--gpu "$profile")
  [ -z "$ANSWERS" ] || args+=(--answers "$ANSWERS")
  log="$PARENT/$name.install.log"
  echo "testboxes: $name -> $PARENT/$name (${args[*]}); log $log"
  # the bootstrap's own folder knob, set here for this one child: the box's folder, never /opt/trialbox
  if TB_BOOTSTRAP_ROOT="$PARENT/$name" bash "$HERE/deploy/bootstrap.sh" "$BUNDLE" --pub "$PUB" -- "${args[@]}" > "$log" 2>&1; then
    echo "testboxes: $name: installed ($(grep -m1 'TEST BOX' "$log" | sed 's/^ *//'))"
  else
    echo "testboxes: $name: the install failed (exit $?): the last lines of $log" >&2
    tail -5 "$log" >&2
    failed=$((failed + 1))
  fi
done
py list
[ "$failed" = 0 ]
