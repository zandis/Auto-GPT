#!/bin/bash
# Stand-in for the driver's power cycle of the VM, or a pre-emption (a stop and a start; on the cloud: two gcloud
# calls of the driver, never made here). reboot.sh <state dir>: every process of the "VM" is killed at once (no
# warning, as a power cut), the stand-in box takes the interruption, and the disk boots again with a new boot id.
set -eu
BR_S=$1; HERE="$(cd "$(dirname "$0")" && pwd)"
export BR_S
kill -KILL -- "-$(cat "$BR_S/vm.pgid")" 2>/dev/null || true
echo TERMINATED > "$BR_S/status"
echo reboot >> "$BR_S/calls.log"
rm -rf "$BR_S/vm/shm"   # tmpfs: a power cycle empties it
python3 "$HERE/box.py" interrupt power
"$HERE/boot.sh" "$BR_S"
