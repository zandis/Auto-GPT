#!/usr/bin/env bash
# TrialBox: the steps of the Windows installer that run inside WSL2, as root (NEW-WIN-1, D-600).
# deploy/windows/box-install.ps1 calls one step at a time and logs what each prints:
#
#   wsl-setup.sh wslconf                 /etc/wsl.conf gets [boot] systemd=true; prints "changed" or "kept"
#   wsl-setup.sh pid1                    prints the name of process 1 (systemd, once the distribution restarted)
#   wsl-setup.sh no-linux-driver         fails when a Linux NVIDIA driver is installed or loaded (WSL2 uses the
#                                        Windows driver; a Linux one breaks it: plan v7.2 section 2.3 rule 3)
#   wsl-setup.sh packages DEBS_DIR       Docker Engine, the compose plugin and the NVIDIA Container Toolkit from the
#                                        media's packages (no network); Docker gets the nvidia runtime and starts
#   wsl-setup.sh gpu                     a container started with --gpus all sees the card; prints the card's line
#   wsl-setup.sh host-tree TAR PUBKEY    the release's host tree to /opt/trialbox, never over an existing folder
#   wsl-setup.sh install BUNDLE [--yes]  deploy/box-install.sh in this terminal (the first-run code, the owner's wait)
#   wsl-setup.sh state                   prints installed=1 once box-install.sh has said the box is ready
#   wsl-setup.sh boot-check              Docker and the stack are enabled to start with the distribution (NEW-WIN-2)
#   wsl-setup.sh network-mode            prints WSL2's networking mode: mirrored, nat, ... (NEW-WIN-4)
#   wsl-setup.sh egress-check            the egress table of D-377 is loaded and its unit is active (NEW-WIN-4)
#   wsl-setup.sh egress-proof            a container on the egress network is seen stopped by the table: prints
#                                        verdict=held, verdict=OUT or verdict=inconclusive
#   wsl-setup.sh lan-check               the box's input firewall is open to the network this PC is really on
#
# Every step may be run again. None removes or replaces a file it did not write.
# Knobs for the tests only: TB_WSL_ETC (/etc), TB_WSL_PROC (/proc), TB_WSL_ROOT (/opt/trialbox), TB_WSL_SMI (the
# Windows driver's nvidia-smi), TB_WSL_NO_ROOT=1.
set -euo pipefail
ETC="${TB_WSL_ETC:-/etc}"
PROC="${TB_WSL_PROC:-/proc}"
ROOT="${TB_WSL_ROOT:-/opt/trialbox}"
SMI="${TB_WSL_SMI:-/usr/lib/wsl/lib/nvidia-smi}"
PROBE_IMAGE="trialbox-gpu-probe:local"
DONE_MARK="$ROOT/deploy/site/box/windows-install-done"
READY_LINE="TrialBox is ready"   # the last line of deploy/box-install.sh (tests/unit/test_windows_box_install.py)
# Packages of a Linux NVIDIA driver: every NVIDIA package is one, unless it is the container toolkit's own
# (a new driver package name is refused by itself; a new toolkit package must be added to TOOLKIT_RE)
DRIVER_RE='^(nvidia-|libnvidia-|linux-modules-nvidia-|linux-objects-nvidia-|linux-signatures-nvidia-|xserver-xorg-video-nvidia|cuda-drivers)'
TOOLKIT_RE='^(nvidia-container-toolkit|nvidia-container-toolkit-base|nvidia-container-runtime|nvidia-docker2|libnvidia-container1|libnvidia-container-tools)$'
LIBDIR="${TB_WSL_LIBDIR:-/usr/lib/x86_64-linux-gnu}"
SYS="${TB_WSL_SYS:-/sys}"
driver_names() { grep -E "$DRIVER_RE" | grep -Ev "$TOOLKIT_RE" || true; }
die() { echo "wsl-setup: $*" >&2; exit 1; }
[ "${TB_WSL_NO_ROOT:-0}" = 1 ] || [ "$(id -u)" = 0 ] || die "run it as root"
STEP="${1:-}"; [ $# -gt 0 ] && shift

case "$STEP" in
  wslconf)
    f="$ETC/wsl.conf"
    python3 - "$f" <<'EOP'
import configparser, pathlib, shutil, sys
p = pathlib.Path(sys.argv[1])
c = configparser.ConfigParser(strict=False)
c.optionxform = str  # keep the keys' case
if p.exists():
    c.read(p, encoding="utf-8")
if c.get("boot", "systemd", fallback="").strip().lower() == "true":
    print("kept")
    sys.exit(0)
if p.exists() and not p.with_name("wsl.conf.before-trialbox").exists():
    shutil.copy2(p, p.with_name("wsl.conf.before-trialbox"))
if not c.has_section("boot"):
    c.add_section("boot")
c.set("boot", "systemd", "true")
with p.open("w", encoding="utf-8") as fh:
    c.write(fh, space_around_delimiters=False)
print("changed")
EOP
    ;;
  pid1)
    cat "$PROC/1/comm"
    ;;
  no-linux-driver)
    # every state but "not installed" and "only its settings left": a half-installed driver is a driver
    found="$(dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' 2>/dev/null | awk '$1 !~ /^.[nc]/ {print $2}' | driver_names | tr '\n' ' ')"
    [ -z "$found" ] || die "a Linux NVIDIA driver is installed in WSL2: ${found}(WSL2 uses the Windows driver; remove these packages)"
    [ ! -e "$PROC/driver/nvidia/version" ] && [ ! -e "$SYS/module/nvidia" ] \
      || die "a Linux NVIDIA kernel driver is loaded in WSL2 ($PROC/driver/nvidia/version or $SYS/module/nvidia)"
    # a driver installed without packages (the .run installer) leaves its library in the system's own folder; the
    # Windows driver's copy lives under /usr/lib/wsl only
    [ ! -e "$LIBDIR/libnvidia-ml.so.1" ] || die "a Linux NVIDIA driver's library is installed in WSL2 ($LIBDIR/libnvidia-ml.so.1)"
    echo "no Linux NVIDIA driver"
    ;;
  packages)
    debs="${1:-}"; [ -d "$debs" ] || die "no such folder of packages: $debs"
    shopt -s nullglob
    files=("$debs"/*.deb)
    [ "${#files[@]}" -gt 0 ] || die "no package in $debs"
    for f in "${files[@]}"; do
      name="$(basename "$f")"
      if [ -n "$(printf '%s\n' "${name%%_*}" | driver_names)" ]; then
        die "the media carries a Linux NVIDIA driver package ($name): it is never installed in WSL2"
      fi
    done
    DEBIAN_FRONTEND=noninteractive dpkg -i --skip-same-version "${files[@]}" || die "the packages did not install (dpkg, above)"
    command -v docker >/dev/null || die "the packages carried no Docker Engine"
    command -v nvidia-ctk >/dev/null || die "the packages carried no NVIDIA Container Toolkit"
    runtimes() { docker info --format '{{range $k, $v := .Runtimes}}{{$k}} {{end}}' 2>/dev/null; }
    systemctl enable docker >/dev/null || die "docker.service could not be enabled"
    if runtimes | grep -qw nvidia; then
      echo "Docker already has the nvidia runtime: not restarted"   # a second run never restarts Docker under a live stack
    else
      nvidia-ctk runtime configure --runtime=docker || die "nvidia-ctk could not configure Docker"
      systemctl restart docker || die "docker.service did not start"
    fi
    systemctl enable --now cron >/dev/null 2>&1 || echo "wsl-setup: warning: cron is not enabled (the backup's schedule needs it)" >&2
    runtimes | grep -qw nvidia || die "Docker does not list the nvidia runtime"
    echo "Docker Engine $(docker version --format '{{.Server.Version}}') with the nvidia runtime"
    ;;
  gpu)
    [ -x "$SMI" ] || die "the Windows NVIDIA driver is not visible in WSL2 ($SMI is missing): install or update the driver on Windows"
    q=("--query-gpu=name,driver_version,memory.total" "--format=csv,noheader")
    "$SMI" "${q[@]}" >/dev/null || die "the Windows NVIDIA driver does not answer inside WSL2 ($SMI)"
    if ! docker image inspect "$PROBE_IMAGE" >/dev/null 2>&1; then
      # a probe image from this system's own files (no image is on the box yet, and none is downloaded): the
      # driver's nvidia-smi and the C library it needs. The driver's own libraries are left out on purpose: the
      # container gets them only from the NVIDIA Container Toolkit, which is what this step proves.
      tmp="$(mktemp -d)"
      mkdir -p "$tmp/probe" "$tmp/etc" "$tmp/tmp"
      cp "$SMI" "$tmp/probe/nvidia-smi"
      mapfile -t libs < <(ldd "$SMI" | awk '$2 == "=>" && $3 ~ /^\// {print $3} $1 ~ /^\// {print $1}' | grep -v '^/usr/lib/wsl/' | sed 's#^/##' | sort -u)
      [ "${#libs[@]}" -gt 0 ] || die "could not read which libraries $SMI needs (ldd)"
      tar -c -h -C / "${libs[@]}" -C "$tmp" probe etc tmp | docker import - "$PROBE_IMAGE" >/dev/null || die "could not build the probe image"
      rm -rf "$tmp"
    fi
    out="$(docker run --rm --network none --gpus all "$PROBE_IMAGE" /probe/nvidia-smi "${q[@]}" 2>&1)" \
      || die "no container sees the card (docker run --gpus all): $(printf '%s' "$out" | tail -1)"
    printf '%s\n' "$out" | tail -1
    ;;
  host-tree)
    tarf="${1:-}"; pub="${2:-}"
    [ -f "$tarf" ] && [ -f "$pub" ] || die "usage: wsl-setup.sh host-tree TAR PUBKEY"
    if [ -f "$ROOT/deploy/box-install.sh" ]; then
      echo "kept: $ROOT is already there"
    elif [ -e "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
      die "$ROOT exists and is not a TrialBox host tree: it is not replaced"
    else
      # unpacked beside the folder and moved into place whole: an interrupted unpack never looks like a host tree
      part="$ROOT.unpacking"
      mkdir -p "$part"
      tar -xf "$tarf" -C "$part" --no-same-owner || die "the host tree did not unpack"
      [ -f "$part/deploy/box-install.sh" ] || die "the host tree carries no deploy/box-install.sh"
      [ ! -d "$ROOT" ] || rmdir "$ROOT"   # an empty folder only (checked above)
      mv "$part" "$ROOT"
      echo "unpacked: $ROOT"
    fi
    key="$ROOT/deploy/keys/vendor_ed25519.pub"
    if [ -f "$key" ]; then
      cmp -s "$key" "$pub" || die "the vendor key on the media differs from the one already at $key"
    else
      mkdir -p "$(dirname "$key")"
      cp "$pub" "$key"
    fi
    echo "vendor key sha256 $(sha256sum "$key" | cut -d' ' -f1)"
    ;;
  install)
    bundle="${1:-}"; yes="${2:-}"
    [ -f "$ROOT/deploy/box-install.sh" ] || die "no host tree at $ROOT (step host-tree)"
    if [ -f "$DONE_MARK" ]; then echo "TrialBox is already installed here ($DONE_MARK): nothing was changed"; exit 0; fi
    args=()
    if [ -f "$ROOT/deploy/site/box/answers.json" ] && grep -q "TrialBox is running" "$ROOT/deploy/site/box/install.log" 2>/dev/null; then
      args=(--firstrun)   # an earlier run installed the stack and stopped before the owner finished the set-up
    else
      if [ ! -r "$bundle" ]; then
        # the media is a drive WSL2 did not mount by itself (a USB disk): mount it read-only
        case "$bundle" in /mnt/[a-z]/*) l="${bundle#/mnt/}"; l="${l%%/*}" ;; *) die "no such bundle: $bundle" ;; esac
        mkdir -p "/mnt/$l"
        mount -t drvfs "${l^^}:" "/mnt/$l" -o ro || die "the media's drive ${l^^}: could not be mounted in WSL2"
        [ -r "$bundle" ] || die "no such bundle: $bundle"
      fi
      args=("$bundle"); [ "$yes" != "--yes" ] || args+=(--yes)
    fi
    work="$(mktemp -d)"
    mkfifo "$work/pipe"
    # the window shows every byte as it comes (tee does not wait for a line end: the installer asks a question);
    # the reader keeps nothing but how often the last line came: this script writes the first-run code nowhere
    # (box-install.sh itself keeps it in its first-run folder, and outside WSL2 in /etc/issue.d: lane D's #368)
    grep -c "$READY_LINE" < "$work/pipe" > "$work/seen" &
    reader=$!
    set +e
    bash "$ROOT/deploy/box-install.sh" "${args[@]}" | tee "$work/pipe"
    rc="${PIPESTATUS[0]}"
    wait "$reader"
    set -e
    if [ "$(cat "$work/seen")" != 0 ]; then mkdir -p "$(dirname "$DONE_MARK")"; date -u +%FT%TZ > "$DONE_MARK"; fi
    rm -rf "$work"
    exit "$rc"
    ;;
  state)
    if [ -f "$DONE_MARK" ]; then echo "installed=1"; else echo "installed=0"; fi
    ;;
  boot-check)
    off=""
    for u in docker.service trialbox.service; do
      [ "$(systemctl is-enabled "$u" 2>/dev/null || true)" = enabled ] || off="$off $u"
    done
    [ -z "$off" ] || die "not enabled to start with the distribution:$off (after a restart TrialBox would stay down)"
    echo "docker.service and trialbox.service start with the distribution"
    ;;
  update-window)
    # NEW-WIN-5 (D-606): the window the Windows installer gave Windows Update ("<start hour>+<hours>"), or "kept"
    # when the site's IT holds the policy. trialbox doctor (update_window) reads it
    # the whole value, not a line of it: it becomes a file trialbox doctor reads
    [[ "${1:-}" =~ ^([0-9]{1,2}\+[0-9]{1,2}|kept)$ ]] || die "update-window: want <start hour>+<hours> or kept"
    mkdir -p "$(dirname "$DONE_MARK")"
    printf '%s\n' "$1" > "$(dirname "$DONE_MARK")/windows-update-window"
    echo "update window recorded for the host check: $1"
    ;;
  windows-drives)
    # NEW-WIN-7 (D-608): the letters of the workstation's own drives (the system drive, the data drive, every disk
    # that is not on USB), for the backup check: a Windows drive that is none of them is an outside drive
    [[ "${1:-}" =~ ^[A-Z](,[A-Z])*$ ]] || die "windows-drives: want drive letters, as C,D"
    mkdir -p "$(dirname "$DONE_MARK")"
    printf '%s\n' "$1" > "$(dirname "$DONE_MARK")/windows-drives"
    echo "this PC's own drives recorded for the backup check: $1"
    ;;
  backup-speed)
    # NEW-WIN-7 (D-608): how fast this box writes to a backup path, in MB/s, measured by writing <MiB> of zeros
    # there and waiting until they are on the disk. A path through Windows (/mnt/<drive>, a share) is far slower
    # than WSL2's own disk; TB_BACKUP_MIN_MBPS (D-455) must stay below it, and trialbox doctor checks that.
    #   wsl-setup.sh backup-speed <target folder> <MiB to write>
    dir="${1:-}"; mib="${2:-}"
    [ -d "$dir" ] || die "backup-speed: no such folder: $dir"
    [[ "$mib" =~ ^[1-9][0-9]*$ ]] || die "backup-speed: want the MiB to write, a whole number (1024 is a fair test)"
    case "$dir" in *$'\t'*|*$'\n'*) die "backup-speed: a folder name with a tab or a line break cannot be recorded" ;; esac
    f="$dir/.trialbox-speed-test.$$"
    trap 'rm -f "$f"' EXIT
    t0="$(date +%s.%N)"
    dd if=/dev/zero of="$f" bs=1M count="$mib" conv=fsync status=none || die "backup-speed: writing to $dir failed"
    t1="$(date +%s.%N)"
    rm -f "$f"; trap - EXIT
    mbps="$(python3 -c 'import sys; a, b, n = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]); print(f"{n * 1.048576 / max(b - a, 1e-3):.1f}")' "$t0" "$t1" "$mib")"
    mkdir -p "$(dirname "$DONE_MARK")"
    printf '%s\t%s\n' "$mbps" "$(cd "$dir" && pwd -P)" >> "$(dirname "$DONE_MARK")/backup-speed"
    echo "mbps=$mbps path=$dir written_mib=$mib"
    ;;
  network-mode)
    # wslinfo comes with WSL 2.0 and later; without it the mode cannot be mirrored
    if command -v wslinfo >/dev/null 2>&1; then wslinfo --networking-mode | tr -d '\r' | tail -1; else echo unknown; fi
    ;;
  egress-check)
    # deploy/egress.py: the table every TrialBox container network is behind; trialbox-egress.service loads it
    # closed before Docker starts (D-377). Nobody had run it under WSL2 before this step
    [ "$(systemctl is-active trialbox-egress.service 2>/dev/null || true)" = active ] \
      || die "trialbox-egress.service is not active: the egress rules are not loaded (containers would have a way out)"
    nft list table inet trialbox_egress >/dev/null 2>&1 \
      || die "the nftables table inet trialbox_egress is not loaded under this WSL2 kernel and networking mode"
    echo "egress table trialbox_egress loaded; trialbox-egress.service active"
    ;;
  egress-proof)
    # Is a container really stopped from reaching outside? One on the egress network (it has a route out; the
    # table is what stops it) tries an address that is nobody's. The proof is the table's own counter of dropped
    # packets: it must rise. A refused or timed-out connection alone proves nothing (the site's network may have
    # dropped it), and a connection that succeeds means the table does not act.
    target="${TB_WSL_PROBE_ADDR:-192.0.2.1}"   # TEST-NET-1 (RFC 5737): an address that belongs to no machine
    net="$(docker network ls --format '{{.Name}}' | grep -m1 'egress-net$' || true)"
    [ -n "$net" ] || { echo "verdict=inconclusive: no egress network (is the stack up?)"; exit 0; }
    c="$(docker ps --filter "network=$net" --format '{{.Names}}' | head -1)"
    [ -n "$c" ] || { echo "verdict=inconclusive: no running container on $net"; exit 0; }
    denied() { nft list table inet trialbox_egress 2>/dev/null | awk '/trialbox default deny/ { for (i = 1; i < NF; i++) if ($i == "packets") s += $(i + 1) } END { print s + 0 }'; }
    before="$(denied)"
    if docker exec "$c" python3 -c "import socket; socket.create_connection(('$target', 443), 3)" >/dev/null 2>&1; then got=connected; else got=no-connection; fi
    after="$(denied)"
    echo "egress_container=$c target=$target result=$got denied_before=$before denied_after=$after"
    if [ "$got" = connected ]; then echo "verdict=OUT"
    elif [ "$after" -gt "$before" ]; then echo "verdict=held"
    else echo "verdict=inconclusive: no connection, but the table counted no dropped packet"; fi
    ;;
  lan-check)
    # the box's own input firewall admits the console's port from CLINIC_RANGES (deploy/site/hardening.conf, written
    # by the box plan from the network it detected). Under mirrored networking that must be this PC's real network:
    # the one of the interface the default route uses
    conf="$ROOT/deploy/site/hardening.conf"
    ranges="$(sed -n 's/^CLINIC_RANGES="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$conf" 2>/dev/null | head -1)"
    dev="$(ip -4 route show default 2>/dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
    addr="$(ip -o -4 addr show dev "${dev:-none}" scope global 2>/dev/null | awk '{ print $4; exit }')"
    python3 - "$ranges" "$addr" <<'EOP'
import ipaddress, sys
ranges, addr = sys.argv[1], sys.argv[2]
said = f"firewall open to '{ranges or 'nothing'}'; this PC's network address '{addr or 'not found'}'"
try:
    host = ipaddress.ip_interface(addr)
    nets = [ipaddress.ip_network(r, strict=False) for r in ranges.replace(",", " ").split()]
except ValueError:
    print(said)
    sys.exit(1)
ok = any(n.version == 4 and host.ip in n and n.prefixlen <= host.network.prefixlen for n in nets)
print(said)
sys.exit(0 if ok else 1)
EOP
    ;;
  *)
    die "unknown step '${STEP}' (see the head of this file)"
    ;;
esac
