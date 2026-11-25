"""10K-4 (D-1390): what a PRODUCTION install may not finish with, and which folder the console may be given.

    python3 -m tools.trialbox finish-check --deploy deploy                   # exit 1, each reason on stderr
    python3 -m tools.trialbox finish-check --deploy deploy --environment PRODUCTION   # before deploy/.env says so
    python3 -m tools.trialbox finish-check --deploy deploy --anchor-only     # the console's folder only (any start)
    python3 -m tools.trialbox finish-check --deploy deploy --mount-anchors   # then the anchor folder into the console
    python3 -m tools.trialbox finish-check --deploy deploy --print-anchors   # the anchor folders, one per line

Exit 0: passed; 1: refused (each line names the setting to change); 2: the check could not run (above).

**The rule: accept only what can be shown.** Whatever the check cannot tell (a disk it cannot name, an address it
cannot resolve, a mount whose source it cannot place) is refused as "cannot be told", never taken as fine.

**Every folder named in ``deploy/.env``** (the anchor folders, the backup targets, the log folder) must
(:func:`folder_problem`):

* pass the text rule of ``tb_common.host_folders`` (one plain full path; no system folder equal, inside or around);
* be there, its real path the path written (no link anywhere in it);
* when its mount is a bind (``/proc/self/mountinfo``'s root field is not ``/``), have a source the check can place
  on the host, and that source must pass the same rule (a bind of ``/etc`` is ``/etc``);
* not overlap the install folder, ``deploy/secrets``, the feed folder, the audit volume and archive, the host's
  secrets and key folders, nor one another (the log folder alone may be the install's own ``deploy/logs``);
* be on a mount that is visible (not hidden under a later mount) with a file system of :data:`ALLOWED_FS`.

**The anchor folder** (:func:`anchor_problem`) is bind-mounted read-only into the console, so before it is mounted
(in every environment, and at every start of the stack through ``deploy/settings_guard.sh``) it must also: not be
on a Windows drive or share of WSL2 (9p, drvfs); have parents owned by root (the installer's own user) that no group
or other account may write, so nobody but root can swap a link in. **In PRODUCTION** it must be the hospital's
audit share itself: the mount point of a network share (nfs, nfs4, cifs, smb3) that is not served by the box.

**A PRODUCTION box** (``TB_ENV`` read as install.sh reads it; none is PRODUCTION, D-127) does not finish without a
backup target off the box (:func:`off_the_box`), counted only when it can be shown, and only when the nightly backup
(``backup_schedule.target_kind``) counts it too, so the two never disagree:

* a share (nfs, nfs4, cifs, smb3) whose server is not the box: the server's name resolves, and none of its addresses
  (nor the ``addr=`` the kernel mounted it from), an IPv4-mapped IPv6 address read as its IPv4 address, is a
  loopback, link-local, multicast or unspecified address, one of the box's own, or in a network of a local-only
  interface of the box (loopback, docker0 and other container links, a bridge without a physical port: its
  containers; ``ip -j -d addr``, :func:`local_only`); a name that does not resolve, or a box whose own addresses
  cannot be read (no ``ip``), cannot be told;
* a local disk whose whole-disk chain (``/sys``: a partition's parent, the members of a device-mapper or md device,
  every device of a btrfs file system) ends only in physical disks (not loop, zram, ram, nbd, nor a virtual device
  without members), none of them a disk of ``/``, the install folder, Docker's data root (the database and the
  audit volumes), the audit folders or the host's key and secrets folders (``TB_KEK_HOST_DIR``,
  ``TB_SECRETS_HOST_DIR``); and ``TB_BACKUP_OFFBOX`` names it (the nightly backup's rule);
* Under WSL2 a Windows drive is counted only by ``backup_schedule``'s outside-drive rule (D-608).

Stand-ins for the tests only: ``TB_FINISH_MOUNTINFO`` (read for ``/proc/self/mountinfo``; beside it ``hosts``, the
names a test resolves, ``own-addresses``, the box's addresses, and ``local-networks``, the networks of its
local-only interfaces), ``TB_FINISH_SYS`` (for ``/sys``) and
``TB_FINISH_TEST_ROOT`` (a folder that stands for ``/``). They are honoured only when ``TB_TEST_ROOT`` names a folder
holding the tests' marker (``.tb-test-root``, ``tools.pglocal.MARKER``) and every stand-in is inside it; set any
other way (``sudo -E`` included) the check refuses, saying so. Standard library only; ``yaml`` only to write the
console's mount.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "libs") not in sys.path:
    sys.path.insert(0, str(ROOT / "libs"))  # the host's python3 (logs.py, ops.py do the same): standard library only

from tb_common import host_folders as hf  # noqa: E402
from tb_common import site_needs  # noqa: E402

ANCHOR_ENV = "TB_AUDIT_ANCHOR_TARGETS"
LOCAL_FS = ("ext4", "xfs", "btrfs", "exfat", "vfat", "ntfs3")
NETWORK_FS = ("nfs", "nfs4", "cifs", "smb3")
WINDOWS_FS = ("9p", "drvfs")  # WSL2's Windows drives and shares (backup_schedule's own rule decides, D-608)
ALLOWED_FS = (*LOCAL_FS, *NETWORK_FS, *WINDOWS_FS)
NOT_DISKS = ("loop", "zram", "ram", "nbd")  # block devices that are a file, memory or a network peer, never a disk
LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "wsl.localhost", "wsl$"})
MARKER = ".tb-test-root"  # tools.pglocal.MARKER: the tests' own root (tests/conftest.py)
STAND_INS = ("TB_FINISH_MOUNTINFO", "TB_FINISH_SYS", "TB_FINISH_TEST_ROOT")
#: deploy/.env's host folders a named folder may not overlap (the log folder's own exceptions are in problems())
DATA_FOLDERS = ("TB_SOURCE_DIR", "TB_AUDIT_HOST_DIR", "TB_AUDIT_ARCHIVE_DIR", "TB_SECRETS_HOST_DIR", "TB_KEK_HOST_DIR")
INSTALL = "the install folder"
ARCHIVE = "the folder TB_AUDIT_ARCHIVE_DIR names"


@dataclass(frozen=True)
class Mount:
    point: str
    majmin: str
    fstype: str
    source: str
    options: str = ""
    root: str = "/"  # the folder of the source mounted here (a bind's source folder; "/" for a plain mount)


#: interfaces whose networks are the box's own (containers, bridges and links of this box): a share served from an
#: address in one of them is served by the box. By name, else by kind (``ip -d``'s ``linkinfo.info_kind``)
LOCAL_ONLY_NAMES = ("docker", "br-", "virbr", "veth", "cni", "podman", "lxcbr", "lxdbr", "flannel", "cali", "weave")
LOCAL_ONLY_KINDS = ("veth", "dummy")


def _bridge_has_a_port_off_the_box(name: str, sys_root: Path) -> bool:
    """A bridge with a physical port (``/sys/class/net/<br>/brif/<port>``, the port with a ``device``) reaches the
    network outside; one whose ports are all virtual (a container's veth) is the box's own."""
    brif = sys_root / "class" / "net" / name / "brif"
    try:
        return any((sys_root / "class" / "net" / port.name / "device").exists() for port in brif.iterdir())
    except OSError:
        return False


def local_only(link: dict[str, Any], sys_root: Path = Path("/sys")) -> bool:
    """Whether an interface of ``ip -j -d addr`` reaches nothing off the box (loopback, a container's link, a bridge
    without a physical port, a dummy): its networks are the box's own."""
    name = str(link.get("ifname") or "")
    kind = str((link.get("linkinfo") or {}).get("info_kind") or "")
    if link.get("link_type") == "loopback" or name.startswith(LOCAL_ONLY_NAMES) or kind in LOCAL_ONLY_KINDS:
        return True
    return kind == "bridge" and not _bridge_has_a_port_off_the_box(name, sys_root)


def own_network(
    links: list[dict[str, Any]], sys_root: Path = Path("/sys")
) -> tuple[frozenset[str], frozenset[str]] | None:
    """The box's own addresses and the networks of its local-only interfaces (:func:`local_only`), from the
    interfaces ``ip -j -d addr`` lists; None when they cannot be read."""
    found: set[str] = set()
    nets: set[str] = set()
    try:
        for link in links:
            for a in link.get("addr_info", []):
                if not a.get("local"):
                    continue
                found.add(str(a["local"]))
                network = str(ipaddress.ip_interface(f"{a['local']}/{a.get('prefixlen', '')}").network)
                if local_only(link, sys_root):
                    nets.add(network)
    except (ValueError, TypeError, AttributeError):
        return None
    return (frozenset(found), frozenset(nets)) if found else None


def _own_network() -> tuple[frozenset[str], frozenset[str]] | None:
    """:func:`own_network` of this host; None when ``ip`` is not there or does not answer (which networks are the
    box's own cannot be told without it)."""
    ip = shutil.which("ip")
    if not ip:
        return None
    try:
        out = subprocess.run([ip, "-j", "-d", "addr", "show"], capture_output=True, text=True, timeout=10, check=True)
        links = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return own_network(links) if isinstance(links, list) else None


def _plain_ip(a: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """An address as the box is reached by it: an IPv4-mapped IPv6 address (``::ffff:127.0.0.1``) is its IPv4
    address, and so is every other spelling that carries an IPv4 address in its last 32 bits: IPv4-compatible
    (``::127.0.0.1``), SIIT (``::ffff:0:127.0.0.1``) and the NAT64 prefix (``64:ff9b::127.0.0.1``); a zone
    (``fe80::1%eth0``) is dropped; None when it is no address."""
    try:
        ip = ipaddress.ip_address(a.strip("[]").split("%", 1)[0])
    except ValueError:
        return None
    if not isinstance(ip, ipaddress.IPv6Address):
        return ip
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    n = int(ip)
    if (n >> 32 == 0 and n > 1) or n >> 32 == 0xFFFF0000 or n >> 32 == 0x64FF9B << 64:
        return ipaddress.IPv4Address(n & 0xFFFFFFFF)
    return ip


@dataclass
class Host:
    """What the check reads of the host; each part can be given (the tests)."""

    mountinfo: str = ""
    sys_root: Path = Path("/sys")
    test_root: str = ""  # a folder standing for "/" (the tests only)
    hosts: dict[str, list[str]] | None = None  # the tests' names; None: the host's resolver
    own: frozenset[str] | None = None  # the box's own addresses; None: cannot be told
    local_nets: frozenset[str] = frozenset()  # the networks of its local-only interfaces (docker0, a bridge, ...)
    refused: str = ""  # the stand-ins were set outside a marked test root
    _mounts: list[Mount] = field(default_factory=list)

    @classmethod
    def from_environ(cls) -> Host:
        given = {k: os.environ.get(k, "") for k in STAND_INS if os.environ.get(k)}
        if given:
            tr = os.environ.get("TB_TEST_ROOT", "")
            real_tr = os.path.realpath(tr) if tr else ""
            inside = all(os.path.realpath(v).startswith(real_tr + "/") for v in given.values()) if real_tr else False
            if not (real_tr and os.path.isfile(os.path.join(real_tr, MARKER)) and inside):
                return cls(refused=f"{', '.join(sorted(given))} set in this command's environment outside a marked "
                                   "test root (TB_TEST_ROOT with .tb-test-root): these stand-ins are for the tests "
                                   "only; unset them (sudo -E carries them over) and run again")  # fmt: skip
            info = Path(given.get("TB_FINISH_MOUNTINFO") or "/proc/self/mountinfo")
            hosts: dict[str, list[str]] = {}
            try:
                for line in (info.parent / "hosts").read_text(encoding="utf-8").splitlines():
                    name, *addrs = line.split()
                    hosts[name.lower()] = addrs
            except (OSError, ValueError):
                pass
            try:
                text = (info.parent / "own-addresses").read_text(encoding="utf-8")
                own: frozenset[str] | None = frozenset(text.split())
            except OSError:
                own = None
            nets = frozenset(_read(info.parent / "local-networks").split())
            return cls(_read(info), Path(given.get("TB_FINISH_SYS") or "/sys"),
                       given.get("TB_FINISH_TEST_ROOT", "").rstrip("/"), hosts, own, nets)  # fmt: skip
        got = _own_network()
        own, nets = got if got is not None else (None, frozenset())
        return cls(_read(Path("/proc/self/mountinfo")), Path("/sys"), "", None, own, nets)

    def on_disk(self, folder: str) -> str:
        """Where a named folder is looked for (itself; under the test root in the tests)."""
        return f"{self.test_root}{folder}" if self.test_root else folder

    def named(self, real: str) -> str:
        """A real path as it is judged (the inverse of on_disk; outside the test root: itself)."""
        if self.test_root and (real == self.test_root or real.startswith(self.test_root + "/")):
            return real[len(self.test_root) :] or "/"
        return real

    def resolve(self, name: str) -> list[str]:
        """The addresses of a share's server; empty: it does not resolve (cannot be told)."""
        try:
            return [str(ipaddress.ip_address(name.strip("[]")))]
        except ValueError:
            pass
        if self.hosts is not None:
            return list(self.hosts.get(name.lower(), []))
        try:
            return sorted({str(a[4][0]) for a in socket.getaddrinfo(name, None)})
        except (OSError, UnicodeError):
            return []

    def visible(self) -> list[Mount]:
        """The mounts, less any hidden under a later mount at the same point or above it."""
        if not self._mounts:
            ms = parse_mountinfo(self.mountinfo)
            self._mounts = [m for i, m in enumerate(ms) if not any(_under(m.point, n.point) for n in ms[i + 1 :])]
        return self._mounts

    def mount_of(self, folder: str) -> Mount | None:
        """The visible mount holding ``folder``: the longest mount point it is, or is below."""
        best: Mount | None = None
        for m in self.visible():
            if _under(folder, m.point) and (best is None or len(m.point) >= len(best.point)):
                best = m
        return best

    def host_path(self, folder: str) -> str | None:
        """Where ``folder`` really is on the host: itself for a plain mount; for a bind (a root field other than
        ``/``), the source folder under the visible mount of the same file system at ``/`` (or at its own root);
        None when that cannot be placed."""
        m = self.mount_of(folder)
        if m is None:
            return None
        if m.root == "/" or m.point == "/":
            return folder
        rest = folder[len(m.point.rstrip("/")) :]
        for n in self.visible():
            same = n.majmin == m.majmin and n.source == m.source
            if same and n is not m and (m.root == n.root or m.root.startswith(n.root.rstrip("/") + "/")):
                below = m.root[len(n.root.rstrip("/")) :] if n.root != "/" else m.root
                return (n.point.rstrip("/") + below + rest) or "/"
        return None


def _under(folder: str, point: str) -> bool:
    return folder == point or folder.startswith(point.rstrip("/") + "/")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _unescape(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def parse_mountinfo(text: str) -> list[Mount]:
    """``/proc/self/mountinfo``: id, parent, major:minor, root, mount point, options, optional fields, ``-``, file
    system, source, super options; in its own order (a later mount may hide an earlier one)."""
    out: list[Mount] = []
    for line in text.splitlines():
        parts = line.split()
        if "-" not in parts or len(parts) < 7:
            continue
        sep = parts.index("-")
        if len(parts) < sep + 3:
            continue
        opts = parts[sep + 3] if len(parts) > sep + 3 else ""
        out.append(Mount(_unescape(parts[4]), parts[2], parts[sep + 1], _unescape(parts[sep + 2]), opts,
                         _unescape(parts[3])))  # fmt: skip
    return out


def whole_disks(name: str, sys_root: Path, depth: int = 0) -> frozenset[str] | None:
    """The physical whole disks under a block device, or None when that cannot be shown: a device that is a file,
    memory or a network peer (loop, zram, ram, nbd), a virtual device with no members, a disk with no ``device``
    (no hardware behind it), or a name /sys does not know. A partition is its parent disk; a device-mapper or md
    device is the disks of every member (``slaves``)."""
    if not name or depth > 8 or "/" in name or name.startswith(NOT_DISKS):
        return None
    d = sys_root / "class" / "block" / name
    if not d.exists():
        return None
    real = Path(os.path.realpath(d))
    slaves = real / "slaves"
    if slaves.is_dir() and any(slaves.iterdir()):
        found: set[str] = set()
        for s in sorted(slaves.iterdir()):
            got = whole_disks(s.name, sys_root, depth + 1)
            if got is None:
                return None
            found |= got
        return frozenset(found)
    disk = real.parent if (real / "partition").exists() else real
    if disk.name.startswith(NOT_DISKS) or "virtual" in disk.parts or not (disk / "device").exists():
        return None
    return frozenset({disk.name})


def _btrfs_members(m: Mount, sys_root: Path) -> list[str] | None:
    """Every device of the btrfs file system the mount's source belongs to (``/sys/fs/btrfs/<fsid>/devices``)."""
    src = Path(os.path.realpath(m.source)).name if m.source.startswith("/dev/") else ""
    base = sys_root / "fs" / "btrfs"
    if not src or not base.is_dir():
        return None
    for fs in sorted(base.iterdir()):
        devices = fs / "devices"
        if devices.is_dir() and (devices / src).exists():
            return sorted(p.name for p in devices.iterdir())
    return None


def disks_of(m: Mount, sys_root: Path) -> frozenset[str] | None:
    """The physical whole disks a local mount is on, or None when that cannot be shown."""
    if m.fstype == "btrfs":
        members = _btrfs_members(m, sys_root)
        if not members:
            return None
        found: set[str] = set()
        for name in members:
            got = whole_disks(name, sys_root)
            if got is None:
                return None
            found |= got
        return frozenset(found)
    by_number = sys_root / "dev" / "block" / m.majmin
    if m.majmin and by_number.exists():
        return whole_disks(Path(os.path.realpath(by_number)).name, sys_root)
    if m.source.startswith("/dev/"):
        return whole_disks(Path(os.path.realpath(m.source)).name, sys_root)
    return None


def read_env(path: Path) -> dict[str, str]:
    """``deploy/.env`` as install.sh reads it (``sed -n 's/^KEY=//p' | tail -1``): only a line that starts with the
    key and ``=`` counts, the last one wins; quotes, spaces and a Windows line end around a value are dropped."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for raw in text.splitlines():
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)$", raw)
        if m:
            out[m.group(1)] = m.group(2).strip(" \t\r").strip('"').strip("'")
    return out


def environment(env: dict[str, str]) -> str:
    """``TB_ENV`` as install.sh reads it (quotes, spaces, tabs and CR dropped, upper case); none is PRODUCTION."""
    return re.sub(r"[\"' \t\r]", "", env.get("TB_ENV") or "").upper() or "PRODUCTION"


def anchor_folders(env: dict[str, str]) -> list[str]:
    """The folders of ``TB_AUDIT_ANCHOR_TARGETS`` (separated as ``anchors.plan`` separates them), as written."""
    out: list[str] = []
    for raw in (env.get(ANCHOR_ENV) or "").split(os.pathsep):
        folder = raw.strip(" \t")
        folder = folder.rstrip("/") or folder
        if folder and folder not in out:
            out.append(folder)
    return out


def backup_targets(env: dict[str, str]) -> list[str]:
    """``TB_BACKUP_TARGETS`` split as ``backup_schedule`` splits it (comma or space)."""
    return [t for t in (env.get("TB_BACKUP_TARGETS") or "").replace(",", " ").split() if t]


def _overlap(folder: str, keep_clear: dict[str, str]) -> str:
    for what, other in keep_clear.items():
        if other and hf.overlaps(folder, other):
            return f"is {what} ({other}), or inside or around it"
    return ""


def folder_problem(folder: str, host: Host, keep_clear: dict[str, str]) -> str:
    """Why ``folder`` may not be named (empty: it may). ``keep_clear``: what it may not overlap, by what to call it."""
    system = hf.system_folder(folder) if folder.startswith("/") else ""
    if system:
        return f"is the system folder {system}, or inside or around it"
    if hf.plain(folder) != folder:
        return "is not one plain full path (letters, digits, '.', '_', '-' and '/'; no '.', '..' or '//' part)"
    where = host.on_disk(folder)
    if not os.path.isdir(where):
        return "is not there (no such folder)"
    real = host.named(os.path.realpath(where))
    if real != folder:
        return f"has a link in its path: it is really {real}"
    why = _overlap(folder, keep_clear)
    if why:
        return why
    m = host.mount_of(folder)
    if m is None or m.fstype not in ALLOWED_FS:
        found = m.fstype if m else "no file system the box can name"
        return f"is on {found}, not on a disk or a share ({', '.join(ALLOWED_FS)})"
    source = host.host_path(folder)
    if source is None:
        return f"is a bind mount whose source cannot be told ({m.source}, {m.root})"
    if source != folder:
        system = hf.system_folder(source)
        if system:
            return f"is a bind mount of {source}: the system folder {system}, or inside or around it"
        why = _overlap(source, keep_clear)
        if why:
            return f"is a bind mount of {source}, which {why}"
    return ""


def _share_host(m: Mount) -> str:
    """The server of an nfs (``host:/path``) or cifs/smb3 (``//host/share``) source; empty when it cannot be read."""
    if m.fstype in ("cifs", "smb3"):
        got = re.match(r"^(?://|\\\\)([^/\\]+)[/\\]", m.source)
        return got.group(1).lower() if got else ""
    got = re.match(r"^(\[[^\]]+\]|[^:/]+):/", m.source)
    return got.group(1).lower() if got else ""


def _share_addresses(m: Mount, server: str, host: Host) -> list[str]:
    """The addresses of a share's server: its name resolved, and the address the kernel mounted it from (the
    ``addr=`` of the nfs and cifs mount options), so a name that now resolves elsewhere does not hide the box."""
    addrs = host.resolve(server)
    if addrs:
        addrs += [o[len("addr=") :] for o in m.options.split(",") if o.startswith("addr=")]
    return addrs


def _the_box(a: str, host: Host) -> str:
    """Why address ``a`` may be the box itself (empty: it is shown not to be). An IPv4-mapped IPv6 address is its
    IPv4 address; a loopback, unspecified, link-local or multicast address, one of the box's own, and any address in
    a network of a local-only interface of the box (docker0, a bridge without a physical port) is the box."""
    ip = _plain_ip(a)
    if ip is None:
        return "is no address the check can read"
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast:
        return "is an address of this box"
    if ip in {_plain_ip(o) for o in host.own or ()}:
        return "is an address of this box"
    for net in sorted(host.local_nets):
        try:
            inside = ip in ipaddress.ip_network(net, strict=False)
        except ValueError:
            return f"cannot be told apart from this box's own networks ({net} cannot be read)"
        if inside:
            return f"is in {net}, a network of this box's own (its containers' or a bridge's)"
    return ""


def share_problem(m: Mount, host: Host) -> str:
    """Why a share is not off the box (served by the box, or its server cannot be told); empty when it is off."""
    server = _share_host(m)
    if not server:
        return f"is a share whose server cannot be told ({m.source})"
    if server in LOCAL_NAMES:
        return f"is a share served by this box ({server})"
    addrs = _share_addresses(m, server, host)
    if not addrs:
        return f"is a share whose server {server} cannot be told (the name does not resolve)"
    if host.own is None:
        return ("is a share, but this box's own addresses cannot be read (ip -j -d addr), so its server cannot be "
                "told apart")  # fmt: skip
    for a in addrs:
        why = _the_box(a, host)
        if why:
            return f"is a share served by this box ({server}: {a} {why})"
    return ""


def _docker_root(host: Host) -> str:
    try:
        cfg = json.loads(Path(host.on_disk("/etc/docker/daemon.json")).read_text(encoding="utf-8"))
        root = str(cfg.get("data-root") or "")
    except (OSError, ValueError, AttributeError):
        root = ""
    return root.rstrip("/") or "/var/lib/docker"


def box_disks(host: Host, deploy: Path, env: dict[str, str]) -> tuple[frozenset[str] | None, str]:
    """The physical disks of ``/``, the install folder, Docker's data root (the database and audit volumes), the
    audit folders and the host's key and secrets folders, and what could not be told (empty when every one was)."""
    found: set[str] = set()
    named = {"/": "/", INSTALL: host.named(str(deploy.resolve())), "Docker's data root": _docker_root(host)}
    for k in ("TB_AUDIT_HOST_DIR", "TB_AUDIT_ARCHIVE_DIR", "TB_KEK_HOST_DIR", "TB_SECRETS_HOST_DIR"):
        if env.get(k):
            named[k] = env[k]
    for what, folder in named.items():
        m = host.mount_of(folder)
        if m is not None and m.fstype in NETWORK_FS:
            continue
        got = disks_of(m, host.sys_root) if m is not None else None
        if got is None:
            return None, f"the disk of {what} ({folder}) cannot be told"
        found |= got
    return frozenset(found), ""


def _nightly_counts(folder: str, m: Mount, host: Host, deploy: Path, declared: list[str]) -> str:
    """The nightly backup's own verdict (``backup_schedule.target_kind``): empty when it counts the folder off the
    box, else its words. The gate never counts what the nightly backup would not."""
    from tools.trialbox import backup_schedule as bs

    mounts = None  # the host's own /proc/mounts, as the nightly backup reads it
    if host.test_root:  # the tests' host: the same mounts, at their places under the test root
        mounts = "".join(f"{n.source} {host.on_disk(n.point)} {n.fstype} {n.options}\n" for n in host.visible())
    t = bs.target_kind(Path(host.on_disk(folder)), mounts_text=mounts, declared=[host.on_disk(d) for d in declared],
                       local=(Path(host.on_disk("/")), deploy), windows_own=bs.windows_own_drives(deploy))  # fmt: skip
    return "" if t.offbox else f"is not counted off the box by the nightly backup ({t.kind})"


def off_the_box(folder: str, host: Host, deploy: Path, env: dict[str, str] | None = None) -> str:
    """Why a backup folder that passes :func:`folder_problem` is not shown to be off the box; empty when it is."""
    env = env or {}
    m = host.mount_of(folder)
    if m is None:
        return "its mount cannot be found"
    declared = [d.rstrip("/") for d in (env.get("TB_BACKUP_OFFBOX") or "").replace(",", " ").split() if d]
    if m.fstype in NETWORK_FS:
        why = share_problem(m, host)
        return why or _nightly_counts(folder, m, host, deploy, declared)
    if m.fstype in WINDOWS_FS:
        return _nightly_counts(folder, m, host, deploy, declared)
    disks = disks_of(m, host.sys_root)
    if disks is None:
        return (f"its disk cannot be told ({m.source}): only a physical disk counts, not a loop device, zram, a "
                "ram disk, nbd or a virtual device without members")  # fmt: skip
    mine, unknown = box_disks(host, deploy, env)
    if mine is None:
        return f"{unknown}, so no local disk is counted off the box"
    shared = sorted(disks & mine)
    if shared:
        return (f"is on a disk of the box itself ({', '.join(shared)}: the system disk, the install folder's, the "
                "database's, the audit folders' or the key and secrets folders'): another partition or volume of it is "
                "not off the box")  # fmt: skip
    if not any(_under(folder, d) for d in declared):
        return "is on another disk, but TB_BACKUP_OFFBOX does not name it (the nightly backup counts it only then)"
    return _nightly_counts(folder, m, host, deploy, declared)


def anchor_problem(folder: str, host: Host, keep_clear: dict[str, str], production: bool) -> str:
    """Why ``folder`` may not be given to the console (empty: it may)."""
    why = folder_problem(folder, host, keep_clear)
    if why:
        return why
    m = host.mount_of(folder)
    assert m is not None  # folder_problem found it
    if m.fstype in WINDOWS_FS:
        return f"is on a Windows drive or share of WSL2 ({m.fstype}): the console is never given one"
    me = os.geteuid()
    parts = folder.split("/")[1:-1]
    for i in range(len(parts) + 1):
        parent = "/" + "/".join(parts[:i])
        st = os.stat(host.on_disk(parent))
        if st.st_uid not in (0, me) or st.st_mode & 0o022:
            return (f"has a parent folder {parent} that another account owns or may write: anybody who can write "
                    "there could put a link in its place before the console starts")  # fmt: skip
    if production:
        if m.point != folder or m.fstype not in NETWORK_FS:
            return (f"is not the hospital's audit share itself (it is on {m.fstype} at {m.point}): a box in use "
                    "needs the share's own mount point (nfs, nfs4, cifs, smb3)")  # fmt: skip
        why = share_problem(m, host)
        if why:
            return why
    return ""


def _base(deploy: Path, env: dict[str, str], host: Host) -> dict[str, str]:
    install = host.named(str(deploy.resolve().parent))
    secrets = host.named(str((deploy / "secrets").resolve()))
    data = {f"the folder {k} names": env.get(k, "") for k in DATA_FOLDERS}
    return {INSTALL: install, "deploy/secrets": secrets, **data}


def anchor_problems(deploy: Path, env: dict[str, str], host: Host, production: bool) -> list[str]:
    base = _base(deploy, env, host)
    targets = backup_targets(env)
    out: list[str] = []
    for a in anchor_folders(env):
        clear = {**base, "the log folder (TB_LOG_DIR)": env.get("TB_LOG_DIR", ""),
                 **{f"a backup target ({t})": t for t in targets}}  # fmt: skip
        why = anchor_problem(a, host, clear, production)
        if why:
            out.append(f"the audit anchor folder {a} {why}: set {ANCHOR_ENV} in deploy/.env to the mount point of the "
                       "hospital's audit share")  # fmt: skip
    return out


def problems(deploy: Path, env: dict[str, str], host: Host | None = None, anchor_only: bool = False) -> list[str]:
    """Why this install may not finish (or its anchor folder not be given to the console); empty when it may."""
    host = host or Host.from_environ()
    if host.refused:
        return [host.refused]
    production = environment(env) == "PRODUCTION" and not anchor_only
    out = anchor_problems(deploy, env, host, production)
    if not production:
        return out
    base = _base(deploy, env, host)
    install = base[INSTALL]
    targets = backup_targets(env)
    log = env.get("TB_LOG_DIR", "")
    # M1 (D-1280): an item the host marked as a stand-in is open on "Information still needed", and the step that
    # needs it refuses on this box; a folder that is named and wrong still stops here
    open_items = site_needs.read_stand_ins(deploy)[0]
    if not anchor_folders(env) and "audit_share" not in open_items:
        out.append(f"no audit anchor folder: set {ANCHOR_ENV} in deploy/.env to the mount point of the hospital's "
                   "audit share")  # fmt: skip
    if log:
        logs = f"{install}/deploy/logs"
        clear = {**base, **{f"a backup target ({t})": t for t in targets}}
        if log == logs or log.startswith(logs + "/"):  # install.sh's own: inside the install folder, the archive in it
            clear.pop(INSTALL)
            clear.pop(ARCHIVE)
        why = folder_problem(log, host, clear)
        if why:
            out.append(f"the log folder {log} {why}: set TB_LOG_DIR in deploy/.env to a folder of its own, or "
                       "remove the line (the install writes deploy/logs)")  # fmt: skip
    own = f"{install}/deploy/backups"  # install.sh's own default: on this machine for now
    if "backup_target" in open_items and all(t == own for t in targets):
        return out
    if not targets:
        out.append("no backup target: set TB_BACKUP_TARGETS in deploy/.env to the folder where the second disk or "
                   "the hospital's share is mounted")  # fmt: skip
        return out
    said: list[str] = []
    for t in targets:
        clear = {**base, "the log folder (TB_LOG_DIR)": log}
        why = folder_problem(t, host, clear) or off_the_box(t, host, deploy, env)
        if not why:
            return out
        said.append(f"{t} {why}")
    out.append(f"no backup target is shown to be off the box ({'; '.join(said)}): set TB_BACKUP_TARGETS in "
               "deploy/.env to the folder where the second disk or the hospital's share is mounted, and for a "
               "second disk TB_BACKUP_OFFBOX to the same folder")  # fmt: skip
    return out


def _write_env(path: Path, lines: list[str]) -> None:
    """``deploy/.env`` replaced whole, each line with its own line end as read: a new file beside it (``mkstemp``: a
    name nobody else can take, owner-only from creation), given the old file's mode (and owner, as root), then
    renamed over it, so a failed write leaves the old file. A link is never replaced (refused before)."""
    st = path.stat()
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))
            os.fchmod(f.fileno(), st.st_mode & 0o7777)
            if os.geteuid() == 0:
                os.fchown(f.fileno(), st.st_uid, st.st_gid)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def mount_anchors(deploy: Path) -> str:
    """The anchor folders of ``deploy/.env`` into the console, as ``install.sh`` does it; an error, or empty.
    Called once :func:`problems` has passed them."""
    env_file = deploy / ".env"
    if env_file.is_symlink():
        return "deploy/.env is a link: it is not rewritten (make it a file, then run this again)"
    env = read_env(env_file)
    folders = anchor_folders(env)
    text = ""
    if env_file.exists():
        with env_file.open(encoding="utf-8", newline="") as f:  # each line's own end, a CR included
            text = f.read()
    lines = text.splitlines(keepends=True)
    at = [i for i, ln in enumerate(lines) if ln.startswith("COMPOSE_FILE=")]
    if not at:  # not written by deploy/install.sh: nothing is guessed; doctor's anchor_mount check says it
        if folders:
            print("    note: the audit anchor folders are not mounted into the console: deploy/.env has no "
                  "COMPOSE_FILE line (deploy/install.sh writes it); run the install again (D-638)")  # fmt: skip
        return ""
    try:
        from tools.trialbox import anchors
    except ImportError as exc:  # yaml: the host's python3 without python3-yaml
        return f"this host's python3 cannot write the console's mount ({exc}): install python3-yaml"
    try:
        made = anchors.write(deploy, env)
    except anchors.AnchorError as exc:
        return str(exc)
    line = lines[at[-1]]
    end = line[len(line.rstrip("\r\n")) :]
    files = [f for f in line.rstrip("\r\n").split("=", 1)[1].split(os.pathsep) if f.strip()]
    kept = [f for f in files if not anchors._same(deploy, f, deploy / anchors.NAME)]
    if made is not None:
        kept.append(str(made))
    new = "COMPOSE_FILE=" + os.pathsep.join(kept) + end
    if new != line:
        lines[at[-1]] = new
        _write_env(env_file, lines)
    return ""


def main_action(deploy: Path, mount: bool = False, print_anchors: bool = False, env_name: str = "",
                anchor_only: bool = False) -> int:  # fmt: skip
    try:
        return _main(deploy, mount, print_anchors, env_name, anchor_only)
    except Exception as exc:  # any failure of the check itself is exit 2, never a pass
        print(f"finish-check: the check could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def _main(deploy: Path, mount: bool, print_anchors: bool, env_name: str, anchor_only: bool) -> int:
    env = read_env(deploy / ".env")
    if env_name:
        env["TB_ENV"] = env_name
    found = problems(deploy, env, anchor_only=anchor_only)
    for p in found:
        print(f"finish-check: {p}", file=sys.stderr)
    if found:
        print("finish-check: refused; each line above names the setting to change in deploy/.env. A PRODUCTION "
              "install needs a backup target shown to be off the box (a share the box does not serve, or a physical "
              "disk that holds none of the box's own data) and the hospital's audit share as its anchor folder; of "
              "the folders the first-run page asks, the console reads that one only, read-only (RUNBOOK §5)",
              file=sys.stderr)  # fmt: skip
        return 1
    if environment(env) == "PRODUCTION" and not (print_anchors or anchor_only):
        print("    finish check: a backup target is off the box; the audit anchor folder is the hospital's share")
    if mount:
        err = mount_anchors(deploy)
        if err:
            print(f"finish-check: {err}", file=sys.stderr)
            return 1
    if print_anchors:
        for a in anchor_folders(env):
            print(a)
    return 0
