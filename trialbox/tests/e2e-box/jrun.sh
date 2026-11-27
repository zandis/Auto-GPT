#!/bin/bash
# jrun.sh ACTIONS.json LABEL : run a journey file with the browser runner (pw/journey.js), then write one step row per
# action: PASS when the status is in the action's "expect" list (default: any status below 400), or for a WAIT when the
# awaited text appeared. The values the actions saved (no secret_* value) go to evidence/LABEL.vars.json.
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib.sh
source "$HERE/lib.sh"
F=$1
L=$2
VARS=${VARS:-'{}'} "$HERE/pw.sh" journey.js < "$F" > "$EV/$L.jsonl" 2> "$EV/$L.err"
python3 "$HERE/actions.py" rows "$F" "$EV/$L.jsonl" | while IFS=$'\t' read -r j s r sec d; do rec "$j" "$s" "$r" "$sec" "$d"; done
grep '^VARS' "$EV/$L.err" | tail -1 | cut -c6- > "$EV/$L.vars.json"
