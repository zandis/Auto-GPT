#!/bin/bash
# Stand-in for a boot of the "VM": deploy/gcp/box-install-run.sh, unchanged, as its startup script, in a process group
# of its own (the "VM"), with the shims first on the PATH and its disk under $BR_S/vm. boot.sh <state dir>
# The real deploy/box-install.sh runs with its own test knobs (TB_BOX_*): the hardware from a file, the image's
# Python as the repo's venv, the inner install.sh, compose and the host check as stand-ins (standins/*.sh).
set -eu
BR_S=$1; BR_HERE="$(cd "$(dirname "$0")/.." && pwd)"
TBROOT="$(cd "$BR_HERE/../../.." && pwd)"
export BR_S BR_HERE
n=$(($(cat "$BR_S/boots" 2>/dev/null || echo 0) + 1)); echo "$n" > "$BR_S/boots"
echo RUNNING > "$BR_S/status"
mkdir -p "$BR_S/vm/shm"
# a "VM" disk 2 GiB larger than its root partition (sysfs as the kernel shows it): the boot's grow_root grows it
if [ ! -d "$BR_S/sys" ]; then
  mkdir -p "$BR_S/sys/devices/sda/sda1" "$BR_S/sys/class/block" "$BR_S/sys/dev/block"
  echo $(( (12 << 30) / 512 )) > "$BR_S/sys/devices/sda/size"
  echo $(( (10 << 30) / 512 )) > "$BR_S/sys/devices/sda/sda1/size"; echo 1 > "$BR_S/sys/devices/sda/sda1/partition"
  ln -s ../../devices/sda "$BR_S/sys/class/block/sda"; ln -s ../../devices/sda/sda1 "$BR_S/sys/class/block/sda1"
  ln -s ../../devices/sda/sda1 "$BR_S/sys/dev/block/8:1"
fi
env PATH="$BR_HERE/shims:$PATH" TB_BOXRUN_ROOT="$BR_S/vm/tb" TB_BOXRUN_LOGDIR="$BR_S/vm/log" TB_BOXRUN_SBIN="$BR_S/vm/sbin" \
  TB_BOXRUN_TLS="$BR_S/vm/tls" TB_BOXRUN_SERIAL="$BR_S/vm/serial.log" TB_BOXRUN_BOOT_ID="rehearsal-boot-$n" \
  TB_BOXRUN_MINUTE_S=1 TB_BOXRUN_POLL_S=0.2 TB_BOXRUN_DOOR_HOST=127.0.0.1 TB_BOXRUN_SHM="$BR_S/vm/shm" \
  TB_BOXRUN_CGROUP="$BR_S/cgroup" \
  TB_BOX_NO_ROOT=1 TB_BOX_HARDWARE="$BR_S/hardware.json" TB_BOX_INSTALL="$BR_HERE/standins/install-inner.sh" \
  TB_BOX_PY="$TBROOT/.venv/bin/python" TB_BOX_COMPOSE="$BR_HERE/standins/compose-up.sh" \
  TB_BOX_HOST_CHECK="$BR_HERE/standins/host-check.sh" TB_FIRSTRUN_HOST_DIR="$BR_S/vm/firstrun" TB_BOX_POLL_S=0.2 \
  TB_SYSTEMD=0 TB_BOXRUN_INSTALL="$BR_HERE/standins/install-validation.sh" TB_BOXRUN_MOUNT="$BR_HERE/standins/bind-models.sh" \
  TB_BOXRUN_TODAY=2026-11-20 TB_BOXRUN_ACC_PY="$BR_HERE/standins/accpy" \
  TB_BOXRUN_SYS="$BR_S/sys" TB_BOXRUN_ROOT_MAJMIN=8:1 TB_BOXRUN_SYSTEMD_DIRS="$BR_S/vm/systemd" \
  setsid bash -c 'echo $$ > "$BR_S/vm.pgid"; exec bash "$1"' _ "$TBROOT/deploy/gcp/box-install-run.sh" \
  > "$BR_S/boot-$n.out" 2>&1 < /dev/null &
