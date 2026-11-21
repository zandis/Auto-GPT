"""10K-4 (D-1390): what a PRODUCTION install may not finish with, and which folders the console may be given.

    python3 -m tools.trialbox finish-check --deploy deploy                   # exit 1, each reason on stderr
    python3 -m tools.trialbox finish-check --deploy deploy --environment PRODUCTION   # before deploy/.env says so
    python3 -m tools.trialbox finish-check --deploy deploy --mount-anchors   # then the anchor folders into the console
    python3 -m tools.trialbox finish-check --deploy deploy --print-anchors   # the anchor folders, one per line

**Each folder named in ``deploy/.env``** (the audit anchor folders, the backup targets, the log folder) is judged by
what it really is, not by its name alone (:func:`folder_problem`):

* the text rule of ``tb_common.host_folders`` (one plain full path; not ``/``; no system folder equal, inside or
  containing it);
* it is a folder that is there, and its real path is the path written (no link anywhere in it, so nothing reaches
  ``/proc/<pid>/root`` or another folder through a link);
* it does not overlap (equal, inside or contain) the install folder, ``deploy/secrets``, the feed folder
  (``TB_SOURCE_DIR``), the audit volume and archive (``TB_AUDIT_HOST_DIR``, ``TB_AUDIT_ARCHIVE_DIR``), the host's
  secrets and key folders (``TB_SECRETS_HOST_DIR``, ``TB_KEK_HOST_DIR``), nor one another (the anchor folder holds
  neither a backup target nor the log folder; a backup target is not the log folder). The log folder alone may be
  ``deploy/logs`` of the install folder, or below it, as install.sh writes it, and may hold the audit archive there;
* its mount (``/proc/self/mountinfo``, the longest mount point holding it) has a file system of :data:`ALLOWED_FS`:
  never a memory or kernel file system (tmpfs, ramfs, proc, sysfs, devtmpfs, overlay, squashfs, ...).

**The anchor folders** are bind-mounted read-only into the console (D-638), so they are judged in every environment
before they are mounted, and the console is given nothing else of the host.

**A PRODUCTION box** (``TB_ENV``, read as install.sh reads it; no value is PRODUCTION, D-127) does not finish

* without a backup target off the box (:func:`off_the_box`): a folder that passes the rule above on a network file
  system (:data:`NETWORK_FS`), or on a local disk whose whole disks (``/sys``: a partition's parent disk, the
  members of a device-mapper or md device) are none of the disks of ``/`` and of the install folder. Another
  partition of the system disk is the system disk. Under WSL2 a Windows drive counts as ``backup_schedule`` counts
  it (an outside drive with its mark, D-608). Targets that are not off the box (``deploy/backups``) may stay beside
  one that is; they are not counted;
* without an anchor folder, or with an anchor or log folder that breaks the rule above.

Outside PRODUCTION only the anchor rule refuses. Nothing is written but by ``--mount-anchors``
(``deploy/box-install.sh`` after the owner's answers are applied, where ``install.sh``'s ANCHOR-MOUNT block did not
run): it writes ``deploy/site/compose.anchors.yml`` (``anchors.write``) and keeps ``COMPOSE_FILE`` naming it.

Stand-ins for the tests only (as ``TB_TIER_TEST_*``): ``TB_FINISH_MOUNTINFO`` (a file read instead of
``/proc/self/mountinfo``), ``TB_FINISH_SYS`` (a folder read instead of ``/sys``) and ``TB_FINISH_TEST_ROOT`` (a
folder that stands for ``/``: a folder named ``/mnt/x`` is looked for at ``<root>/mnt/x`` and judged as ``/mnt/x``).
Standard library only; ``yaml`` (``anchors``) only to write the console's mount.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "libs") not in sys.path:
    sys.path.insert(0, str(ROOT / "libs"))  # the host's python3 (logs.py, ops.py do the same): standard library only

from tb_common import host_folders as hf  # noqa: E402

ANCHOR_ENV = "TB_AUDIT_ANCHOR_TARGETS"
LOCAL_FS = ("ext4", "xfs", "btrfs", "exfat", "vfat", "ntfs3")
NETWORK_FS = ("nfs", "nfs4", "cifs", "smb3")
WINDOWS_FS = ("9p", "drvfs")  # WSL2's Windows drives and shares (backup_schedule's own rule decides, D-608)
ALLOWED_FS = (*LOCAL_FS, *NETWORK_FS, *WINDOWS_FS)
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


@dataclass
class Host:
    """What the check reads of the host; each part can be given (the tests)."""

    mountinfo: str = ""
    sys_root: Path = Path("/sys")
    test_root: str = ""  # a folder standing for "/" (the tests only)
    _mounts: list[Mount] = field(default_factory=list)

    @classmethod
    def from_environ(cls) -> Host:
        info = os.environ.get("TB_FINISH_MOUNTINFO") or "/proc/self/mountinfo"
        try:
            text = Path(info).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        root = os.environ.get("TB_FINISH_TEST_ROOT", "").rstrip("/")
        return cls(text, Path(os.environ.get("TB_FINISH_SYS") or "/sys"), root)

    def on_disk(self, folder: str) -> str:
        """Where a named folder is looked for (itself; under the test root in the tests)."""
        return f"{self.test_root}{folder}" if self.test_root else folder

    def named(self, real: str) -> str:
        """A real path as it is judged (the inverse of on_disk; outside the test root: itself)."""
        if self.test_root and (real == self.test_root or real.startswith(self.test_root + "/")):
            return real[len(self.test_root) :] or "/"
        return real

    def mounts(self) -> list[Mount]:
        if not self._mounts:
            self._mounts = parse_mountinfo(self.mountinfo)
        return self._mounts

    def mount_of(self, folder: str) -> Mount | None:
        """The mount that holds ``folder``: the longest mount point it is, or is below (a later one wins a tie)."""
        best: Mount | None = None
        for m in self.mounts():
            if (folder == m.point or folder.startswith(m.point.rstrip("/") + "/")) and (
                best is None or len(m.point) >= len(best.point)
            ):
                best = m
        return best


def _unescape(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def parse_mountinfo(text: str) -> list[Mount]:
    """``/proc/self/mountinfo``: id, parent, major:minor, root, mount point, options, optional fields, ``-``, file
    system, source, super options."""
    out: list[Mount] = []
    for line in text.splitlines():
        parts = line.split()
        if "-" not in parts or len(parts) < 7:
            continue
        sep = parts.index("-")
        if len(parts) < sep + 3:
            continue
        opts = parts[sep + 3] if len(parts) > sep + 3 else ""
        out.append(Mount(_unescape(parts[4]), parts[2], parts[sep + 1], _unescape(parts[sep + 2]), opts))
    return out


def whole_disks(name: str, sys_root: Path, depth: int = 0) -> frozenset[str] | None:
    """The whole disks under a block device (``/sys/class/block/<name>``): itself for a disk, the parent disk of a
    partition, the disks of every member (``slaves``) of a device-mapper or md device. None: not told."""
    if not name or depth > 8 or "/" in name:
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
    if (real / "partition").exists():
        return frozenset({real.parent.name})
    return frozenset({real.name})


def disks_of(m: Mount, sys_root: Path) -> frozenset[str] | None:
    """The whole disks a local mount is on: by its device number (``/sys/dev/block/<major:minor>``), else by its
    source (a btrfs mount has an anonymous device number); None when neither names a block device."""
    by_number = sys_root / "dev" / "block" / m.majmin
    if m.majmin and by_number.exists():
        return whole_disks(Path(os.path.realpath(by_number)).name, sys_root)
    if m.source.startswith("/dev/"):
        return whole_disks(Path(os.path.realpath(m.source)).name, sys_root)
    return None


def read_env(path: Path) -> dict[str, str]:
    """``deploy/.env`` as install.sh and doctor read it: the last line of a key wins; quotes, spaces and a Windows
    line end are not part of a value."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for raw in text.splitlines():
        line = raw.strip(" \t\r")
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip(" \t")] = value.strip(" \t").strip('"').strip("'")
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
    for what, other in keep_clear.items():
        if other and hf.overlaps(folder, other):
            return f"is {what} ({other}), or inside or around it"
    m = host.mount_of(folder)
    if m is None or m.fstype not in ALLOWED_FS:
        found = m.fstype if m else "no file system the box can name"
        return f"is on {found}, not on a disk or a share ({', '.join(ALLOWED_FS)})"
    return ""


def system_disks(host: Host, deploy: Path) -> frozenset[str] | None:
    """The whole disks of ``/`` and of the install folder; None when one cannot be told."""
    found: set[str] = set()
    for folder in ("/", host.named(str(deploy.resolve()))):
        m = host.mount_of(folder)
        if m is not None and m.fstype in NETWORK_FS:
            continue
        got = disks_of(m, host.sys_root) if m is not None else None
        if got is None:
            return None
        found |= got
    return frozenset(found)


def off_the_box(folder: str, host: Host, deploy: Path) -> str:
    """Why a backup folder that passes :func:`folder_problem` is not off the box; empty when it is."""
    m = host.mount_of(folder)
    if m is None:
        return "its mount cannot be found"
    if m.fstype in NETWORK_FS:
        return ""
    if m.fstype in WINDOWS_FS:
        from tools.trialbox import backup_schedule as bs

        mounts = f"{m.source} {host.on_disk(m.point)} {m.fstype} {m.options}\n"
        t = bs.target_kind(Path(host.on_disk(folder)), mounts_text=mounts, windows_own=bs.windows_own_drives(deploy))
        return "" if t.offbox else f"is {t.kind}"
    disks = disks_of(m, host.sys_root)
    if disks is None:
        return f"its disk cannot be told ({m.source})"
    mine = system_disks(host, deploy)
    if mine is None:
        return "the system disk cannot be told, so no local disk is counted off the box"
    shared = sorted(disks & mine)
    if shared:
        return f"is on the system disk ({', '.join(shared)}): another partition or folder of it is not off the box"
    return ""


def problems(deploy: Path, env: dict[str, str], host: Host | None = None) -> list[str]:
    """Why this install may not finish (or its anchor folder not be given to the console); empty when it may."""
    host = host or Host.from_environ()
    install = host.named(str(deploy.resolve().parent))
    secrets = host.named(str((deploy / "secrets").resolve()))
    data = {f"the folder {k} names": env.get(k, "") for k in DATA_FOLDERS}
    base = {INSTALL: install, "deploy/secrets": secrets, **data}
    anchors = anchor_folders(env)
    targets = backup_targets(env)
    log = env.get("TB_LOG_DIR", "")
    out: list[str] = []
    for a in anchors:  # every environment: the console is given this folder
        clear = {**base, "the log folder (TB_LOG_DIR)": log, **{f"a backup target ({t})": t for t in targets}}
        why = folder_problem(a, host, clear)
        if why:
            out.append(f"the audit anchor folder {a} {why}: set {ANCHOR_ENV} in deploy/.env to the folder where the "
                       "hospital's audit share is mounted (a folder of its own)")  # fmt: skip
    if environment(env) != "PRODUCTION":
        return out
    if not anchors:
        out.append(f"no audit anchor folder: set {ANCHOR_ENV} in deploy/.env to the folder where the hospital's "
                   "audit share is mounted")  # fmt: skip
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
    if not targets:
        out.append("no backup target: set TB_BACKUP_TARGETS in deploy/.env to the folder where the second disk or "
                   "the hospital's share is mounted")  # fmt: skip
        return out
    said: list[str] = []
    for t in targets:
        why = folder_problem(t, host, {**base, "the log folder (TB_LOG_DIR)": log}) or off_the_box(t, host, deploy)
        if not why:
            return out
        said.append(f"{t} {why}")
    out.append(f"no backup target is off the box ({'; '.join(said)}): set TB_BACKUP_TARGETS in deploy/.env to the "
               "folder where the second disk or the hospital's share is mounted (for a second disk, TB_BACKUP_OFFBOX "
               "to the same folder)")  # fmt: skip
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


def main_action(deploy: Path, mount: bool = False, print_anchors: bool = False, env_name: str = "") -> int:
    env = read_env(deploy / ".env")
    if env_name:
        env["TB_ENV"] = env_name
    found = problems(deploy, env)
    for p in found:
        print(f"finish-check: {p}", file=sys.stderr)
    if found:
        print("finish-check: refused; each line above names the setting to change in deploy/.env. A PRODUCTION "
              "install needs a backup target off the box (a share, or a disk that is not the system disk) and an "
              "audit anchor folder of its own on a disk or a share; the console is given that folder only, read-only "
              "(RUNBOOK §5)", file=sys.stderr)  # fmt: skip
        return 1
    if environment(env) == "PRODUCTION" and not print_anchors:
        print("    finish check: a backup target is off the box; the audit anchor folder is a folder of its own on a "
              "disk or a share")  # fmt: skip
    if mount:
        err = mount_anchors(deploy)
        if err:
            print(f"finish-check: {err}", file=sys.stderr)
            return 1
    if print_anchors:
        for a in anchor_folders(env):
            print(a)
    return 0
