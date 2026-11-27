#!/bin/bash
# vmctl.sh new NAME PORTBASE MEDIA_IMG [VCPU MEM] | start NAME | stop NAME [--kill] | ssh NAME cmd... | put NAME SRC DST
#          | attach NAME IMG | status NAME | remove NAME
# One test VM: a qcow2 overlay on the read-only Ubuntu 24.04 cloud image, a cloud-init seed, its own OVMF vars, a
# sparse docker disk and the install media (a read-only raw ext4 image), all under $E2E_VMS (default /dev/shm/e2e-box).
# User-mode networking (no bridge, no host firewall change); ports on 127.0.0.1: PORTBASE ssh, +1 console (443).
# E2E_CPUSET pins qemu (the host's VM cores). `remove` deletes only that VM's own folder.
set -euo pipefail
cmd=${1:?command}
name=${2:?name}
[[ $name =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "bad VM name $name" >&2; exit 2; }
VMS=${E2E_VMS:-/dev/shm/e2e-box}
D=$VMS/$name
BASE=${E2E_BASE_IMG:?the Ubuntu 24.04 cloud image (noble-server-cloudimg-amd64.img)}
KEY=${E2E_HOME:-$HOME/e2e-box}/keys/id_ed25519
sshv() {
  ssh -i "$KEY" -p "$(cat "$D/portbase")" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 tbadmin@127.0.0.1 "$@"
}
ours() { # pid : this VM's qemu, not a reused pid
  [ -n "${1:-}" ] && tr '\0' ' ' < "/proc/$1/cmdline" 2> /dev/null | grep -q -- "qemu-system-x86_64 -name $name "
}
qmp() { printf '%s' "$1" | timeout 10 nc -U "$D/qmp"; }
case $cmd in
  new)
    base=${3:?port base}
    media=${4:?media image}
    vcpu=${5:-24}
    mem=${6:-96G}
    [ ! -e "$D" ] || { echo "$name exists"; exit 1; }
    mkdir -p "$D" && chmod 0700 "$D"
    mkdir -p "$(dirname "$KEY")"
    [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C e2e-box -f "$KEY"
    echo "$base" > "$D/portbase"
    echo "$vcpu $mem" > "$D/size"
    echo "$media" > "$D/media"
    qemu-img create -q -f qcow2 -b "$BASE" -F qcow2 "$D/disk.qcow2" 200G
    cp /usr/share/OVMF/OVMF_VARS_4M.fd "$D/vars.fd"
    truncate -s "${E2E_DOCKER_DISK:-160G}" "$D/docker.raw"
    cat > "$D/user-data" << YY
#cloud-config
hostname: $name
users:
  - name: tbadmin
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys: ["$(cat "$KEY.pub")"]
package_update: true
packages: [ca-certificates, nftables, cron, python3, python3-yaml, python3-cryptography, openssl, curl, iproute2, iptables, kmod, xxd, tmux]
fs_setup: [{label: dockerdata, filesystem: ext4, device: /dev/vdd, partition: none}]
mounts: [["/dev/vdc", "/mnt/media", "ext4", "ro,noload,nofail", "0", "0"], ["/dev/vdd", "/var/lib/docker", "ext4", "defaults,nofail", "0", "0"]]
runcmd:
  - [mkdir, -p, /mnt/media]
  - [sh, -c, "install -m 0755 -d /etc/apt/keyrings && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable' > /etc/apt/sources.list.d/docker.list && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce=5:${E2E_DOCKER:-28.0.4}-1~ubuntu.24.04~noble docker-ce-cli=5:${E2E_DOCKER:-28.0.4}-1~ubuntu.24.04~noble containerd.io docker-buildx-plugin docker-compose-plugin && apt-mark hold docker-ce docker-ce-cli"]
  - [sh, -c, "touch /var/lib/tbvm-ready"]
YY
    printf 'instance-id: %s\nlocal-hostname: %s\n' "$name" "$name" > "$D/meta-data"
    cloud-localds "$D/seed.iso" "$D/user-data" "$D/meta-data"
    echo "created $name (ports $base, $((base + 1)))"
    ;;
  start)
    read -r vcpu mem < "$D/size"
    base=$(cat "$D/portbase")
    pin=()
    [ -z "${E2E_CPUSET:-}" ] || pin=(taskset -c "$E2E_CPUSET")
    "${pin[@]}" qemu-system-x86_64 -name "$name" -machine q35,accel=kvm,memory-backend=m0 -cpu host -smp "$vcpu" -m "$mem" \
      -object "memory-backend-memfd,id=m0,size=$mem,share=on" -display none -daemonize -pidfile "$D/pid" \
      -serial "file:$D/serial.log" -qmp "unix:$D/qmp,server=on,wait=off" \
      -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd -drive "if=pflash,format=raw,file=$D/vars.fd" \
      -object iothread,id=io0 -object iothread,id=io1 \
      -drive "if=none,id=d0,format=qcow2,file=$D/disk.qcow2,cache=unsafe,aio=threads" -device virtio-blk-pci,drive=d0,iothread=io0 \
      -drive "if=none,id=d1,format=raw,media=cdrom,readonly=on,file=$D/seed.iso" -device virtio-blk-pci,drive=d1 \
      -drive "if=none,id=d2,format=raw,readonly=on,cache=none,aio=io_uring,file=$(cat "$D/media")" -device virtio-blk-pci,drive=d2 \
      -drive "if=none,id=d3,format=raw,file=$D/docker.raw,cache=unsafe,aio=threads" -device virtio-blk-pci,drive=d3,iothread=io1 \
      -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:$base-:22,hostfwd=tcp:127.0.0.1:$((base + 1))-:443${E2E_FWD:-}" -device virtio-net-pci,netdev=n0 \
      -device virtio-rng-pci -device pcie-root-port,id=hp1,chassis=9,slot=9
    echo "started $name pid $(cat "$D/pid")"
    ;;
  stop)
    p=$(cat "$D/pid")
    ours "$p" || { echo "$name is not running (pid $p is not its qemu)"; exit 1; }
    if [ "${3:-}" = --kill ]; then # a power cut
      kill -9 "$p"
      for _ in $(seq 1 180); do kill -0 "$p" 2> /dev/null || break; sleep 1; done
      echo "killed $name (power loss)"
      exit 0
    fi
    qmp '{"execute":"qmp_capabilities"}{"execute":"system_powerdown"}' > /dev/null || true
    for _ in $(seq 1 60); do kill -0 "$p" 2> /dev/null || { echo "stopped $name"; exit 0; }; sleep 2; done
    echo "$name still up after 120 s"
    exit 1
    ;;
  ssh)
    shift 2
    sshv "$@"
    ;;
  put)
    scp -q -i "$KEY" -P "$(cat "$D/portbase")" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
      "${3:?source}" tbadmin@127.0.0.1:"${4:?destination}"
    ;;
  attach) # hot-plug a second read-only media image (the next bundle) on the spare PCIe port
    qmp '{"execute":"qmp_capabilities"}{"execute":"blockdev-add","arguments":{"driver":"raw","node-name":"hot1","read-only":true,"file":{"driver":"file","filename":"'"${3:?image}"'","read-only":true}}}{"execute":"device_add","arguments":{"driver":"virtio-blk-pci","bus":"hp1","drive":"hot1","id":"hot1dev"}}' | tail -c 200
    echo
    ;;
  status)
    if ours "$(cat "$D/pid" 2> /dev/null)"; then echo "$name running"; else echo "$name stopped"; fi
    ;;
  remove)
    if ours "$(cat "$D/pid" 2> /dev/null)"; then echo "stop $name first"; exit 1; fi
    rm -rf "${D:?}"
    echo "removed $name"
    ;;
  *)
    echo "unknown command $cmd" >&2
    exit 2
    ;;
esac
