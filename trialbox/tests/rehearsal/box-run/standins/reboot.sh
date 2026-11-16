#!/bin/bash
# Stand-in for the driver's power cycle of the VM (a stop and a start; on the cloud: two gcloud calls of the driver,
# never made here). reboot.sh <state dir>: every process of the "VM" is killed at once (no warning, as a power cut),
# the stand-in box takes the interruption (standins/tool.py interrupt), and the disk boots again with a new boot id.
set -eu
BR_S=$1; HERE="$(cd "$(dirname "$0")" && pwd)"
export BR_S
kill -KILL -- "-$(cat "$BR_S/vm.pgid")" 2>/dev/null || true
echo TERMINATED > "$BR_S/status"
echo reboot >> "$BR_S/calls.log"
[ ! -f "$BR_S/box/wizard-done" ] || python3 "$HERE/tool.py" interrupt
"$HERE/boot.sh" "$BR_S"
