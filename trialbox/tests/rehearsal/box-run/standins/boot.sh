#!/bin/bash
# Stand-in for a boot of the "VM": deploy/gcp/box-install-run.sh, unchanged, as its startup script, in a process group
# of its own (the "VM"), with the shims first on the PATH and its disk under $BR_S/vm. boot.sh <state dir>
set -eu
BR_S=$1; BR_HERE="$(cd "$(dirname "$0")/.." && pwd)"
TBROOT="$(cd "$BR_HERE/../../.." && pwd)"
export BR_S BR_HERE
n=$(($(cat "$BR_S/boots" 2>/dev/null || echo 0) + 1)); echo "$n" > "$BR_S/boots"
echo RUNNING > "$BR_S/status"
mkdir -p "$BR_S/vm"
env PATH="$BR_HERE/shims:$PATH" TB_BOXRUN_ROOT="$BR_S/vm/tb" TB_BOXRUN_LOGDIR="$BR_S/vm/log" TB_BOXRUN_SBIN="$BR_S/vm/sbin" \
  TB_BOXRUN_TLS="$BR_S/vm/tls" TB_BOXRUN_SERIAL="$BR_S/vm/serial.log" TB_BOXRUN_BOOT_ID="rehearsal-boot-$n" \
  TB_BOXRUN_MINUTE_S=1 TB_BOXRUN_POLL_S=0.2 TB_BOXRUN_DOOR_HOST=127.0.0.1 \
  setsid bash -c 'echo $$ > "$BR_S/vm.pgid"; exec bash "$1"' _ "$TBROOT/deploy/gcp/box-install-run.sh" \
  > "$BR_S/boot-$n.out" 2>&1 < /dev/null &
