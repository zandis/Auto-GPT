"""The nightly backup, its off-box rule and the age alert (WS-08.6, D-187, D-188). Standard library only at import,
so the host's ``python3`` runs it from the install folder (cron, ``deploy/backup/trialbox-backup.cron``):

    python3 -m tools.trialbox backup-nightly            # 04:45: the .tbbak to every target, then pgBackRest
    python3 -m tools.trialbox backup-status [--json]    # hourly: exit 1 and alert when the newest good one is too old

**One snapshot per database** (:func:`snapshot_script`). The box keeps running while it is backed up, so the dump,
the row counts of the manifest and the hospital's own reference rows are all read inside one ``REPEATABLE READ``
transaction: ``psql`` exports its snapshot, ``pg_dump --snapshot`` dumps exactly that state, and the same session
counts and hashes every table and copies out the ``refdata`` rows the hospital loaded itself (``site-fetch``
sources). A restore must then give the same rows, or it fails. The rows of the vendor's reference pack
(``ctgov_study``, ``trial``, ``term`` of the vendor's sources) are left out: the pack is public and several GB; its
``pack`` and ``source`` rows are kept, and a restore loads the pack again from the folder where install and update
keep it (``deploy/refdata/loaded``).

**Nightly** (:func:`nightly`). The script runs in the ``db`` container (``docker compose exec``) into
``/tmp/tb-backup`` there; the files are copied to a 0700 folder under ``deploy/`` and both are removed right after.
``trialbox backup`` runs in a one-off container with every volume read-only (the update path's own step,
``update.ComposeBox``) and writes the encrypted file to every directory of ``TB_BACKUP_TARGETS``. When WAL archiving
is on (``TB_PG_ARCHIVE_MODE=on``), pgBackRest then takes a differential backup, or a full one on
``TB_PGBACKREST_FULL_DAY`` (default Sunday, the box's local day). The result goes to ``deploy/site/backup-last.json``
(0600: time, file name, size, sha256, targets, errors; never a row or a file's content) and to the audit
(``backup.done`` / ``backup.failed``). A run holds a lock, sweeps what a killed run left, and checks free space first.
D-455: nothing is paused by default. Each database is one snapshot; the files are read after both snapshots; the
record names that window (``point_in_time``). ``TB_BACKUP_QUIESCE=pause`` keeps D-274's pause of every service but
``db``, never while a job runs, and under the watchdog's maintenance flag. Every step's time limit comes from the size
it reads (:func:`step_timeout`, OD-10), and a target keeps backups by count and by size (:func:`prune`). The dump
folder carries a ``host/`` part (``deploy/.env``, settings, ``deploy/site``, ``deploy/secrets``, the
Authelia and Caddy volumes). ``backup-install`` (install.sh) writes the cron file, turns WAL archiving on where the
image and an off-box share allow it, and runs the first backup; in PRODUCTION it needs an alert route.

**Off-box.** A target counts as off-box when it is a network share (NFS, SMB/CIFS, SSHFS ... or a Windows UNC path
mounted in WSL2), a USB disk, or a path that hospital IT declared in ``TB_BACKUP_OFFBOX`` (e.g. an iSCSI volume in
another room) that is on another device than the box's own disk or carries a ``.trialbox-offbox`` file. In
PRODUCTION a backup is *good* only on an off-box target: a box whose targets are all on its own disks writes its
backup and still fails (exit 1, ``backup.failed``) and stays red.

**Age alert** (:func:`status`, :func:`alert`). The newest good backup is the one ``backup-last.json`` records after a
successful run, found on a counted target with the same name, size and sha256 (its ``.sha256`` sidecar). It is too
old after ``TB_BACKUP_MAX_AGE_HOURS`` (default 36, the admin tile's red, WS-08.5); dated more than an hour in the
future, or not matching the recorded time, it is wrong. A failed last nightly run, a failed pgBackRest run, and WAL
archiving that fails, is off while the site turned it on, or has archived nothing for 26 hours are alerts too. An
alert is audited (``backup.alert``, again every 24 h while it lasts, ``backup.alert_cleared`` when it ends) and sent
to ``TB_BACKUP_ALERT_CMD`` (a command that reads the message on stdin, e.g. the hospital's mail relay), and the
command exits 1 so cron's ``MAILTO`` mails it too. The message names the problem and the box, never patient data.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SUFFIX = ".tbbak"
REFDATA = "refdata"
BULK_REFDATA = ("ctgov_study", "trial", "term")  # the vendor pack's rows: left out, the site-fetch ones copied out
NETWORK_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "sshfs", "glusterfs", "ceph",
                        "fuse.rclone", "davfs", "fuse.s3fs", "afs"})  # fmt: skip
OFFBOX_MARKER = ".trialbox-offbox"
MAX_AGE_HOURS = 36.0
ARCHIVE_STALE_HOURS = 26
REALERT = timedelta(hours=24)
STANZA = "trialbox"
CONTAINER_SPOOL = "/tmp/tb-backup"
QUIESCE_KEEP = frozenset({"db"})  # D-274 (DI-11): with TB_BACKUP_QUIESCE=pause, every other running service is paused
# D-455 (OD-10): a step's time limit is START_S + bytes / MIN_MBPS; both are declared settings with their reason
MIN_MBPS = 5.0  # a tenth of the 30-50 MB/s measured for pg_dump on a box disk: only a hung step is stopped
STEP_START_S = 900.0  # the part of a step that does not grow with the data: a container start, a connection
KEEP_SHARE = 0.5  # the part of a target this box's backups may fill (the rest: other users, the next night's file)
# D-455: jobs that are running (the orchestrator's own "interrupted" query, orchestrator/db.py)
RUNNING_JOBS_SQL = ("SELECT count(*) FROM orch.jobs WHERE queued = 0 AND state NOT IN ('done', 'failed', "
                    "'awaiting_approval')")  # fmt: skip
# D-274 (OPS-046): volumes a rebuild needs beyond the data. traces-data is left out on purpose: model traces are
# diagnostics, not needed to rebuild, and may hold note text (PV-13)
HOST_VOLUMES = ("authelia-data", "caddy-data")

Audit = Callable[[str, dict[str, Any]], None]


# ------------------------------------------------------------------------------------------------ files
def safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s)[:40] or "box"


def site_prefix(name: str) -> str:
    """``trialbox-<site>-`` of a backup's file name: the files of one box on a share other boxes may use too."""
    return name[: -len(SUFFIX)].rsplit("-", 1)[0] + "-"


def sidecar(file: Path) -> Path:
    return file.with_name(file.name + ".sha256")


def read_sidecar(file: Path) -> str | None:
    """The sha256 written beside ``file`` when it was complete, or None (no sidecar: not a finished backup)."""
    try:
        sha, _, rest = sidecar(file).read_text(encoding="utf-8").strip().partition("  ")
    except OSError:
        return None
    return sha if rest == file.name and len(sha) == 64 else None


def stamp_of(file: Path) -> datetime | None:
    """The time in a backup's file name (``trialbox-<site>-YYYYmmddTHHMMSSZ.tbbak``), UTC."""
    try:
        return datetime.strptime(file.name[: -len(SUFFIX)].rsplit("-", 1)[-1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def prune(target: Path, keep: int, prefix: str, max_bytes: int | None = None) -> list[Path]:
    """Keep the newest ``keep`` backups of one box (``prefix``, ``trialbox-<site>-``) in a target; remove its older
    ones (with their sidecar) and its stale ``.part`` files. Other boxes' files on a shared target are never touched.
    ``max_bytes`` (D-455, F-26): the kept files' total size too; the oldest go first, the newest is always kept."""
    files = sorted(target.glob(f"{prefix}*{SUFFIX}"), key=lambda p: p.name.rsplit("-", 1)[-1])
    files = [f for f in files if site_prefix(f.name) == prefix]
    gone = files[:-keep] if keep > 0 else []
    if max_bytes is not None:
        kept = files[len(gone) :]
        total = sum(_size(f) for f in kept)
        while len(kept) > 1 and total > max_bytes:
            total -= _size(kept[0])
            gone.append(kept.pop(0))
    gone += [sidecar(p) for p in gone]
    gone += [p for p in target.glob(f"{prefix}*{SUFFIX}*.part") if site_prefix(p.name.split(SUFFIX)[0] + SUFFIX)
             == prefix]  # fmt: skip
    for p in gone:
        p.unlink(missing_ok=True)
    return gone


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def step_timeout(nbytes: int | None, min_mbps: float = MIN_MBPS, start_s: float = STEP_START_S) -> float | None:
    """A backup step's time limit from the bytes it reads (D-455, OD-10): ``start_s`` plus ``nbytes`` at ``min_mbps``.
    None when the size is not known: no limit then, never a fixed guess (a hung step holds the lock; the age alert)."""
    if nbytes is None or nbytes < 0:
        return None
    return round(start_s + nbytes / (min_mbps * 1e6), 1)


def tree_bytes(root: Path) -> int | None:
    """The bytes of every file under ``root``, or None when it cannot be read (not there, not root)."""
    if not root.is_dir():
        return None
    total = 0
    try:
        for dirpath, _dirs, names in os.walk(root, onerror=_raise):
            for n in names:
                with contextlib.suppress(OSError):
                    total += os.lstat(os.path.join(dirpath, n)).st_size
    except OSError:
        return None
    return total


def _raise(e: OSError) -> None:
    raise e


def volume_bytes(env: Mapping[str, str], fallback: int | None) -> int | None:
    """What the backup container reads besides the dumps: the box's volumes, walked on the host (D-455). A volume the
    host cannot read counts as ``fallback`` (the last good backup's size) once; None when nothing is known."""
    from tools.trialbox import update

    root = Path(env.get("TB_DOCKER_VOLUMES") or os.environ.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes")
    total, unknown = 0, False
    for vol in update.BACKUP_VOLUMES.values():
        n = tree_bytes(root / f"trialbox_{vol}" / "_data")
        if n is None:
            unknown = True
        else:
            total += n
    if unknown:
        if fallback is None:
            return None
        total += fallback
    return total


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


# ------------------------------------------------------------------------------------------------ one snapshot
def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


ROW_HASH = "rs1"  # D-274 (CR-057): the table's content hash; "md5" is the one every backup before it used
EMPTY_HASH = {"md5": "d41d8cd98f00b204e9800998ecf8427e", "rs1": "rs1:0:0"}  # the hash of a table with no rows


def row_agg(scheme: str = ROW_HASH) -> str:
    """The SQL of a table's content hash over its rows aliased ``t``, for ``SELECT count(*), <this> FROM x t``.

    ``rs1`` (D-274, CR-057): two sums of 64-bit pieces of each row's md5. A sum does not depend on row order and
    never builds one value over the whole table, so a table of any size hashes (``md5``, the old form, aggregated the
    whole table into one string, and Postgres refuses a string over 1 GB). ``md5`` stays to restore older backups."""
    if scheme == "md5":
        return "md5(COALESCE(string_agg(t::text, chr(10) ORDER BY t::text), ''))"
    if scheme != "rs1":
        raise ValueError(f"unknown row hash {scheme!r}")
    part = "COALESCE(sum(('x' || {}(md5(t::text), 16))::bit(64)::bigint), 0)"
    return f"'rs1:' || {part.format('left')} || ':' || {part.format('right')}"


_ROW = "SELECT %L || ''|'' || count(*) || ''|'' || " + row_agg().replace("'", "''") + " FROM %I.%I t"
_SITE = " WHERE source_id IN (SELECT source_id FROM %I.source WHERE distribution = ''site-fetch'')"


def snapshot_script(out: str, name: str, pg_dump: str, conn: str, schemas: Sequence[str], refdata: str | None) -> str:
    """A ``psql`` script: one ``REPEATABLE READ`` transaction exports its snapshot; ``pg_dump --snapshot`` writes
    ``<out>/<name>.dump`` from it (exit code in ``.dump.rc``); the same session writes every table's row count and
    content hash (``.rows``), the reference packs (``.packs``) and the hospital's own reference rows
    (``.site.<table>.copy``). ``conn`` is how ``pg_dump`` reaches the database where ``psql`` runs."""
    for s in (out, name, pg_dump, conn, *schemas):
        if "'" in s:
            raise ValueError(f"a quote in {s!r}")
    o = f"{out}/{name}"
    likes = ", ".join(_lit(p.replace("*", "%")) for p in schemas) or "'%'"
    rs = _lit(refdata or "")
    bulk = ", ".join(_lit(t) for t in BULK_REFDATA)
    dump_args = " ".join(f'--schema "{s}"' for s in schemas)
    if refdata:
        dump_args += "".join(f' --exclude-table-data "{refdata}.{t}"' for t in BULK_REFDATA)
    tables = ("FROM information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', "
              f"'information_schema') AND table_schema LIKE ANY(ARRAY[{likes}])")  # fmt: skip
    has_src = "to_regclass(format('%I.source', table_schema)) IS NOT NULL"
    lines = [
        "\\pset format unaligned",
        "\\pset tuples_only on",
        "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;",
        f"SELECT pg_export_snapshot() \\g '{o}.snapshot'",
        f'\\! sh -c \'{pg_dump} -Fc -Z0 --no-owner --no-privileges --snapshot="$(cat {o}.snapshot)" {conn} '
        f'{dump_args} -f "{o}.dump"; echo $? > "{o}.dump.rc"\'',
        f"\\o '{o}.rows'",
        f"SELECT format('{_ROW}', table_schema || '.' || table_name, table_schema, table_name) {tables} "
        f"AND NOT (table_schema = {rs} AND table_name IN ({bulk})) ORDER BY table_schema, table_name \\gexec",
        f"SELECT format('{_ROW}{_SITE}', 'site:' || table_schema || '.' || table_name, table_schema, table_name, "
        f"table_schema) {tables} AND table_schema = {rs} AND table_name IN ({bulk}) AND {has_src} "
        "ORDER BY table_name \\gexec",
        f"\\o '{o}.packs'",
        "SELECT format('SELECT pack_id || ''|'' || data_as_of || ''|'' || origin FROM %I.pack ORDER BY pack_id', "
        f"table_schema) {tables} AND table_schema = {rs} AND table_name = 'pack' \\gexec",
    ]
    for t in BULK_REFDATA:
        lines += [
            f"\\o '{o}.site.{t}.copy'",
            f"SELECT format('COPY (SELECT * FROM %I.%I t{_SITE}) TO STDOUT', table_schema, table_name, table_schema) "
            f"{tables} AND table_schema = {rs} AND table_name = {_lit(t)} AND {has_src} \\gexec",
        ]
    lines += ["\\o", "COMMIT;", ""]
    return "\n".join(lines)


def snapshot_meta(name: str, refdata: str | None) -> dict[str, Any]:
    return {"db": name, "rows_from": "snapshot", "refdata_schema": refdata, "row_hash": ROW_HASH,
            "excluded_tables": [f"{refdata}.{t}" for t in BULK_REFDATA] if refdata else []}  # fmt: skip


def parse_snapshot(d: Path, name: str) -> dict[str, Any]:
    """What :func:`snapshot_script` wrote in ``d``: rows, the hospital's own reference rows, packs, site files."""
    rc = (d / f"{name}.dump.rc").read_text().strip() if (d / f"{name}.dump.rc").is_file() else "missing"
    if rc != "0" or not (d / f"{name}.dump").is_file():
        raise RuntimeError(f"pg_dump of {name} in the snapshot failed (exit {rc})")
    rows: dict[str, list[Any]] = {}
    site: dict[str, list[Any]] = {}
    for line in (d / f"{name}.rows").read_text(encoding="utf-8").splitlines():
        if line.strip():
            key, n, md5 = line.rsplit("|", 2)
            (site if key.startswith("site:") else rows)[key.removeprefix("site:")] = [int(n), md5]
    packs = [dict(zip(("pack_id", "data_as_of", "origin"), ln.split("|"), strict=False))
             for ln in (d / f"{name}.packs").read_text(encoding="utf-8").splitlines() if ln.strip()]  # fmt: skip
    meta = _read_json(d / f"{name}.dump.json") or snapshot_meta(name, None)
    files = {t: d / f"{name}.site.{t}.copy" for t in BULK_REFDATA if (d / f"{name}.site.{t}.copy").is_file()}
    return {**meta, "rows": rows, "site_rows": site, "packs": packs, "site_files": files}


# ------------------------------------------------------------------------------------------------ targets
@dataclass(frozen=True)
class Target:
    path: str
    kind: str  # network share | usb disk | declared off-box | this box | declared, but on this box's disk
    offbox: bool
    fstype: str = ""


def _unescape(s: str) -> str:
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def _mounts(text: str | None) -> list[tuple[str, str, str]]:
    if text is None:
        try:
            text = Path("/proc/mounts").read_text(encoding="utf-8")
        except OSError:
            text = ""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 3:
            out.append((_unescape(f[0]), _unescape(f[1]), f[2]))
    return out


def _resolve(path: Path) -> Path:
    """``path`` with the symlinks of its existing part resolved; a part not made yet is kept as written."""
    p, tail = Path(os.path.normpath(path.absolute())), list[str]()
    while not p.exists() and p != p.parent:
        tail.insert(0, p.name)
        p = p.parent
    return p.resolve().joinpath(*tail)


def _existing(path: Path) -> Path:
    p = _resolve(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _is_usb(device: str, sys_block: Path) -> bool:
    if not device.startswith("/dev/"):
        return False
    name = Path(device).resolve().name if Path(device).exists() else Path(device).name
    node = sys_block / name
    try:
        real = node.resolve()
    except OSError:
        return False
    if "/usb" in str(real):
        return True
    for d in (real, real.parent):
        try:
            if (d / "removable").read_text().strip() == "1":
                return True
        except OSError:
            continue
    return False


def target_kind(
    path: Path,
    mounts_text: str | None = None,
    declared: Sequence[str] = (),
    sys_block: Path = Path("/sys/class/block"),
    local: Sequence[Path] = (Path("/"),),
) -> Target:
    """Where ``path`` lives: on a network share, a USB disk, a declared off-box volume, or this box's own disks.
    A declared path counts only on another device than every ``local`` path, or with a ``.trialbox-offbox`` file."""
    real = _resolve(Path(path))
    for d in declared:
        dd = _resolve(Path(d))
        if d and (real == dd or dd in real.parents):
            here = _existing(dd)
            marked = (dd / OFFBOX_MARKER).is_file()
            other_dev = all(here.stat().st_dev != _existing(p).stat().st_dev for p in local)
            if marked or other_dev:
                return Target(str(path), "declared off-box", True)
            return Target(str(path), "declared, but on this box's disk (no .trialbox-offbox file)", False)
    best = ("", "/", "")
    for src, mnt, fstype in _mounts(mounts_text):
        m = Path(mnt)
        if (real == m or m in real.parents) and len(mnt) >= len(best[1]):
            best = (src, mnt, fstype)
    src, _, fstype = best
    if fstype in NETWORK_FS or src.startswith(("//", "\\\\")):  # a UNC source: a Windows share mounted in WSL2
        return Target(str(path), "network share", True, fstype)
    if _is_usb(src, sys_block):
        return Target(str(path), "usb disk", True, fstype)
    return Target(str(path), "this box", False, fstype)


# ------------------------------------------------------------------------------------------------ configuration
@dataclass
class Config:
    deploy: Path
    targets: list[Path]
    public_key: Path
    production: bool = True
    keep: int = 14
    max_age_hours: float = MAX_AGE_HOURS
    archive_on: bool = False
    full_day: int = 6  # Monday 0 ... Sunday 6, in the box's local time
    declared_offbox: list[str] = field(default_factory=list)
    alert_cmd: str = ""
    site: str = ""
    tz: str = "UTC"
    mailto: str = ""  # D-274: cron's MAILTO, an alert route only where the host has a mail transfer agent
    archive_set: str = ""  # TB_PG_ARCHIVE_MODE as written ("" when the site never chose)
    pgbackrest_repo: str = ""
    keep_share: float = KEEP_SHARE  # D-455: TB_BACKUP_KEEP_SHARE
    min_mbps: float = MIN_MBPS  # D-455: TB_BACKUP_MIN_MBPS
    step_start_s: float = STEP_START_S  # D-455: TB_BACKUP_STEP_START_S
    quiesce: str = "off"  # D-455: TB_BACKUP_QUIESCE, off (the snapshot alone) or pause

    def timeout(self, nbytes: int | None) -> float | None:
        return step_timeout(nbytes, self.min_mbps, self.step_start_s)

    def keep_bytes(self, target: Path) -> int | None:
        """The most this box's backups may fill of ``target`` (D-455, F-26): ``keep_share`` of its capacity."""
        try:
            return int(shutil.disk_usage(_existing(target)).total * self.keep_share)
        except OSError:
            return None

    @property
    def alert_route(self) -> bool:
        return bool(self.alert_cmd or self.mailto)

    @property
    def last_file(self) -> Path:
        return self.deploy / "site" / "backup-last.json"

    @property
    def alert_file(self) -> Path:
        return self.deploy / "site" / "backup-alert.json"

    def classify(self, p: Path) -> Target:
        return target_kind(p, declared=self.declared_offbox, local=(Path("/"), self.deploy))


def _split(v: str) -> list[str]:
    return [t for t in v.replace(",", " ").split() if t]


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def config(deploy: Path, env: Mapping[str, str], process_env: bool = True) -> Config:
    """The schedule's settings from ``deploy/.env`` (``env``, quotes removed), with the process environment winning
    (``process_env``; doctor passes its own merged settings and False)."""
    proc = {k: v for k, v in os.environ.items() if k.startswith("TB_")} if process_env else {}
    e = {k: _unquote(v) for k, v in {**env, **proc}.items()}
    return Config(
        deploy=deploy,
        targets=[Path(t) for t in _split(e.get("TB_BACKUP_TARGETS", ""))],
        public_key=Path(e.get("TB_BACKUP_PUBKEY") or deploy / "secrets" / "backup.pub"),
        production=(e.get("TB_ENV") or "PRODUCTION").upper() == "PRODUCTION",
        keep=int(e.get("TB_BACKUP_KEEP") or 14),
        max_age_hours=float(e.get("TB_BACKUP_MAX_AGE_HOURS") or MAX_AGE_HOURS),
        archive_on=(e.get("TB_PG_ARCHIVE_MODE") or "off").lower() == "on",
        full_day=int(e.get("TB_PGBACKREST_FULL_DAY") or 6),
        declared_offbox=_split(e.get("TB_BACKUP_OFFBOX", "")),
        alert_cmd=e.get("TB_BACKUP_ALERT_CMD", ""),
        site=e.get("TB_SITE_ID", ""),
        tz=e.get("TB_TZ") or "Asia/Taipei",
        mailto=e.get("TB_BACKUP_MAILTO", ""),
        archive_set=(e.get("TB_PG_ARCHIVE_MODE") or "").lower(),
        pgbackrest_repo=e.get("TB_PGBACKREST_REPO", ""),
        keep_share=float(e.get("TB_BACKUP_KEEP_SHARE") or KEEP_SHARE),
        min_mbps=float(e.get("TB_BACKUP_MIN_MBPS") or MIN_MBPS),
        step_start_s=float(e.get("TB_BACKUP_STEP_START_S") or STEP_START_S),
        quiesce="pause" if (e.get("TB_BACKUP_QUIESCE") or "off").lower() == "pause" else "off",
    )


def _local_weekday(now: datetime, tz: str) -> int:
    try:
        from zoneinfo import ZoneInfo

        return now.astimezone(ZoneInfo(tz)).weekday()
    except Exception:  # an unknown zone name: UTC
        return now.weekday()


# ------------------------------------------------------------------------------------------------ nightly
def _free_space_errors(cfg: Config, last: Mapping[str, Any]) -> list[str]:
    """A run that cannot fit fails before it starts: each target needs 1.2 times the last good backup, the deploy
    folder (the dumps pass through it) three times."""
    est = int((last.get("good_file") or {}).get("bytes") or 0)
    if not est:
        return []
    out = []
    for where, need in [*((t, est * 1.2) for t in cfg.targets), (cfg.deploy, est * 3.0)]:
        try:
            free = shutil.disk_usage(_existing(Path(where))).free
        except OSError:
            continue
        if free < need:
            out.append(f"not enough free space on {where}: {free // 2**20} MiB free, about {int(need) // 2**20} "
                       "MiB needed")  # fmt: skip
    return out


def nightly(
    cfg: Config,
    make_backup: Callable[[list[Path]], Sequence[Path]],
    audit: Audit,
    pgbackrest: Callable[[str], None] | None = None,
    now: datetime | None = None,
    classify: Callable[[Path], Target] | None = None,
) -> dict[str, Any]:
    """One nightly run: the encrypted backup to every target, then pgBackRest; record and audit the result."""
    now = now or datetime.now(UTC)
    kinds = [(classify or cfg.classify)(t) for t in cfg.targets]
    prev = _read_json(cfg.last_file)
    res: dict[str, Any] = {"at": now.isoformat(timespec="seconds"), "ok": False, "targets": [asdict(k) for k in kinds],
                           "file": None, "errors": [], "good_at": prev.get("good_at"),
                           "good_file": prev.get("good_file")}  # fmt: skip
    errors: list[str] = res["errors"]
    if not cfg.targets:
        errors.append("no backup target: set TB_BACKUP_TARGETS in deploy/.env (RUNBOOK §5)")
    elif not cfg.public_key.is_file():
        errors.append(f"no backup key {cfg.public_key}: trialbox backup-keygen with hospital IT (RUNBOOK §5)")
    elif space := _free_space_errors(cfg, prev):
        errors += space
    else:
        if cfg.production and not any(k.offbox for k in kinds):
            errors.append("no off-box target: every TB_BACKUP_TARGETS directory is on this box (RUNBOOK §5)")
        try:
            files = list(make_backup(cfg.targets))
            copies: list[dict[str, Any]] = []
            for f in files:
                prune(f.parent, cfg.keep, site_prefix(f.name), cfg.keep_bytes(f.parent))
                sha = read_sidecar(f)
                if sha is None:
                    raise RuntimeError(f"{f} has no .sha256 sidecar: the backup did not complete")
                copies.append({"path": str(f), "bytes": f.stat().st_size, "sha256": sha})
            if not copies or len({(c["sha256"], c["bytes"]) for c in copies}) != 1:
                raise RuntimeError("the copies of the backup differ or none was written")
            if len(copies) != len(cfg.targets):
                raise RuntimeError(f"written to {len(copies)} of {len(cfg.targets)} targets")
            res["file"] = {"name": Path(copies[0]["path"]).name, "bytes": copies[0]["bytes"],
                           "sha256": copies[0]["sha256"], "copies": copies}  # fmt: skip
        except Exception as e:  # every failure is recorded, audited and alerted (exit 1)
            errors.append(f"backup failed: {type(e).__name__}: {str(e)[-400:]}")
    pit = getattr(make_backup, "point_in_time", None)
    if pit is not None:  # D-455: what the point in time is (the snapshots, the files' window, a pause if any)
        res["point_in_time"] = dict(pit)
    if cfg.archive_on and pgbackrest is not None:
        kind = "full" if _local_weekday(now, cfg.tz) == cfg.full_day else "diff"
        try:
            pgbackrest(kind)
            res["pgbackrest"] = {"type": kind, "ok": True}
        except Exception as e:
            res["pgbackrest"] = {"type": kind, "ok": False}
            errors.append(f"pgBackRest {kind} backup failed: {type(e).__name__}: {str(e)[-300:]}")
    res["ok"] = not errors
    if res["ok"]:
        res["good_at"] = res["at"]
        res["good_file"] = {k: res["file"][k] for k in ("name", "bytes", "sha256")}
    _write_json(cfg.last_file, res)
    detail = {"file": (res["file"] or {}).get("name"), "bytes": (res["file"] or {}).get("bytes"),
              "sha256": (res["file"] or {}).get("sha256"), "targets": len(kinds),
              "offbox_targets": sum(k.offbox for k in kinds), "pgbackrest": res.get("pgbackrest"),
              "errors": errors}  # fmt: skip
    audit("backup.done" if res["ok"] else "backup.failed", detail)
    return res


# ------------------------------------------------------------------------------------------------ status and alert
def recorded_good(dirs: Sequence[Path], good_file: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The good backup ``backup-last.json`` records, on one of ``dirs`` with the same name, size and sha256."""
    if not good_file:
        return None
    for d in dirs:
        f = Path(d) / str(good_file.get("name"))
        at = stamp_of(f)
        if at is None or not f.is_file() or f.stat().st_size != good_file.get("bytes"):
            continue
        if read_sidecar(f) == good_file.get("sha256"):
            return {"at": at, "path": str(f), "bytes": good_file["bytes"], "sha256": good_file["sha256"]}
    return None


def status(
    cfg: Config,
    now: datetime | None = None,
    archiver: Mapping[str, Any] | None = None,
    classify: Callable[[Path], Target] | None = None,
) -> dict[str, Any]:
    """``level`` ok or alert, the newest good backup and its age, and every problem in plain words."""
    now = now or datetime.now(UTC)
    kinds = [(classify or cfg.classify)(t) for t in cfg.targets]
    problems: list[str] = []
    counted = [Path(k.path) for k in kinds if k.offbox or not cfg.production]
    if not cfg.targets:
        problems.append("no backup target (TB_BACKUP_TARGETS)")
    elif cfg.production and not counted:
        problems.append("no off-box backup target: every target is on this box")
    last = _read_json(cfg.last_file)
    good = recorded_good(counted, last.get("good_file"))
    age_h = None
    if good is None:
        if counted:
            problems.append("no good backup on " + ("an off-box target" if cfg.production else "any target")
                            + " (the one backup-last.json records: same name, size and sha256)")  # fmt: skip
    else:
        age_h = round((now - good["at"]).total_seconds() / 3600, 1)
        if age_h < -1:
            problems.append("the newest good backup is dated in the future: the clock or the file name is wrong")
        elif age_h > cfg.max_age_hours:
            problems.append(f"the newest good backup is {age_h:.0f} h old (limit {cfg.max_age_hours:.0f} h)")
        try:
            good_at = datetime.fromisoformat(str(last.get("good_at")))
            if abs((good_at - good["at"]).total_seconds()) > 3600:
                problems.append("the newest good backup's file name and deploy/site/backup-last.json disagree on "
                                "its time")  # fmt: skip
        except ValueError:
            problems.append("deploy/site/backup-last.json has no time for the good backup")
    if cfg.production and not cfg.alert_route:
        problems.append("no alert route: set TB_BACKUP_ALERT_CMD (or TB_BACKUP_MAILTO with a mail relay) in "
                        "deploy/.env (RUNBOOK §5)")  # fmt: skip
    if last and not last.get("ok"):
        problems.append(f"the last nightly backup at {last.get('at', '?')} failed (deploy/site/backup-last.json)")
    if last.get("pgbackrest") and not last["pgbackrest"].get("ok"):
        problems.append("the last pgBackRest backup failed (deploy/site/backup-last.json)")
    if cfg.archive_on and archiver is not None:
        mode = archiver.get("archive_mode")
        if archiver.get("error"):
            problems.append("the database did not answer the WAL archiving check (RUNBOOK §5)")
        elif mode != "on":
            problems.append(f"WAL archiving is on in deploy/.env but the database says archive_mode={mode}: "
                            "docker compose --project-directory deploy up -d db (RUNBOOK §5)")  # fmt: skip
        elif archiver.get("failing"):
            problems.append("WAL archiving to pgBackRest is failing: PITR is not current and pg_wal grows "
                            "(RUNBOOK §5)")  # fmt: skip
        elif (age_s := int(archiver.get("last_archived_age_s", -1))) == -1 or age_s > ARCHIVE_STALE_HOURS * 3600:
            problems.append(f"no WAL archived for more than {ARCHIVE_STALE_HOURS} h (RUNBOOK §5)")
    out = {"level": "alert" if problems else "ok", "at": now.isoformat(timespec="seconds"), "problems": problems,
           "age_hours": age_h, "max_age_hours": cfg.max_age_hours, "targets": [asdict(k) for k in kinds],
           "newest_good": None if good is None else {**good, "at": good["at"].isoformat(timespec="seconds")},
           }  # fmt: skip
    if archiver is not None:
        out["archiver"] = dict(archiver)
    return out


def alert(
    cfg: Config,
    st: Mapping[str, Any],
    audit: Audit,
    send: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> str:
    """Audit and send an alert when one starts, changes or has lasted another 24 h; audit its end. Returns what was
    done: ``sent``, ``cleared`` or ``quiet``."""
    now = now or datetime.now(UTC)
    prev = _read_json(cfg.alert_file)
    if st["level"] == "alert":
        sent = prev.get("sent_at")
        kinds = sorted({re.sub(r"[0-9][0-9:.T+-]*", "#", p) for p in st["problems"]})  # the age changes hourly
        due = (prev.get("level") != "alert" or prev.get("kinds") != kinds or not sent
               or now - datetime.fromisoformat(sent) >= REALERT)  # fmt: skip
        if not due:
            return "quiet"
        audit("backup.alert", {"problems": st["problems"], "age_hours": st.get("age_hours")})
        msg = (f"TrialBox {cfg.site or 'box'}: backup alert\n" + "".join(f"- {p}\n" for p in st["problems"])
               + "What to do: docs/RUNBOOK.md §5 (Backup). This message holds no patient data.\n")  # fmt: skip
        if send is not None:
            try:
                send(msg)
            except Exception as e:  # the audit and the exit code still carry the alert
                audit("backup.alert_not_sent", {"error": f"{type(e).__name__}: {str(e)[-200:]}"})
        _write_json(cfg.alert_file, {"level": "alert", "problems": st["problems"], "kinds": kinds,
                                     "sent_at": now.isoformat()})  # fmt: skip
        return "sent"
    if prev.get("level") == "alert":
        audit("backup.alert_cleared", {"newest_good": (st.get("newest_good") or {}).get("at")})
        _write_json(cfg.alert_file, {"level": "ok", "cleared_at": now.isoformat()})
        return "cleared"
    return "quiet"


def send_cmd(cmd: str) -> Callable[[str], None] | None:
    """``TB_BACKUP_ALERT_CMD`` as a sender: the command reads the message on stdin."""
    if not cmd:
        return None

    def send(msg: str) -> None:
        subprocess.run(shlex.split(cmd), input=msg.encode(), check=True, timeout=120, capture_output=True)

    return send


# ------------------------------------------------------------------------------------------------ the compose box
ARCHIVER_SQL = (
    "SELECT current_setting('archive_mode'), COALESCE(failed_count, 0), "
    "COALESCE(last_failed_time > COALESCE(last_archived_time, 'epoch'), false), "
    "COALESCE(EXTRACT(EPOCH FROM now() - last_archived_time)::bigint, -1) FROM pg_stat_archiver"
)


class ComposeOps:
    """The nightly run's steps on a site box (``docker compose --project-directory deploy``)."""

    def __init__(self, deploy: Path, run: Callable[..., str] | None = None) -> None:
        from tools.trialbox import update

        self.deploy = deploy
        self.box = update.ComposeBox(deploy, run or update.run_cmd)
        self.env = self.box.env

    def sweep(self) -> None:
        """What a killed run left: dump folders under deploy/ and the spool in the db container."""
        for d in self.deploy.glob(".backup-*"):
            shutil.rmtree(d, ignore_errors=True)
        with contextlib.suppress(Exception):
            self.box.run(self.box._c("exec", "-T", "db", "rm", "-rf", CONTAINER_SPOOL))

    def db_bytes(self, db: str, user: str) -> int | None:
        """``pg_database_size`` of ``db`` (D-455: what its snapshot step reads), or None when it cannot be asked."""
        return self.box.db_bytes(db, user)

    def cluster_bytes(self) -> int | None:
        """Every database of the server together (what a pgBackRest backup reads at most)."""
        try:
            sql = "SELECT sum(pg_database_size(datname))::bigint FROM pg_database"
            user = self.env.get("POSTGRES_USER") or "hapi"
            out = self.box.run(
                self.box._c("exec", "-T", "db", "psql", "-X", "-At", "-U", user, "-d", "hapi", "-c", sql)
            )
            return int(out.strip())
        except Exception:  # no answer: no size, so no limit (D-455)
            return None

    def running_jobs(self) -> int | None:
        """How many jobs the orchestrator is running now (D-455: a pause is never taken under one), or None."""
        return self.box.running_jobs()

    def snapshot(self, db: str, user: str, work: Path, timeout: float | None = None) -> None:
        """:func:`snapshot_script` in the db container; its files are copied to ``work`` and removed there. Each of
        the two steps has ``timeout`` seconds (D-455: from the database's size; None: no limit)."""
        refdata = REFDATA if db == "trialbox_wf" else None
        script = work / f"{db}.sql"
        script.write_text(snapshot_script(CONTAINER_SPOOL, db, "pg_dump", f"-U {user} -d {db}", (), refdata))
        try:
            self.box.run(self.box._c("exec", "-T", "db", "sh", "-c",
                                     f"umask 077; mkdir -p {CONTAINER_SPOOL}; cat > {CONTAINER_SPOOL}/{db}.sql; "
                                     f"psql -X -q -v ON_ERROR_STOP=1 -U {user} -d {db} -f {CONTAINER_SPOOL}/{db}.sql"),
                         stdin_file=script, timeout=timeout)  # fmt: skip
            self.box.run(self.box._c("cp", f"db:{CONTAINER_SPOOL}/.", str(work)), timeout=timeout)
        finally:
            with contextlib.suppress(Exception):
                self.box.run(self.box._c("exec", "-T", "db", "rm", "-rf", CONTAINER_SPOOL))
        script.unlink(missing_ok=True)
        (work / f"{db}.sql").unlink(missing_ok=True)
        _write_json(work / f"{db}.dump.json", snapshot_meta(db, refdata))
        parse_snapshot(work, db)  # the dump finished and every file is there, or the run fails here

    def writers(self) -> list[str]:
        """The running services but ``db``: the ones a backup holds still (D-274, DI-11)."""
        out = self.box.run(self.box._c("ps", "--status", "running", "--services"))
        return sorted({x for x in out.split() if x not in QUIESCE_KEEP})

    def host_files(self, dest: Path) -> list[str]:
        """What a rebuild needs besides the data (D-274, DI-12, OPS-046), copied into ``dest`` (inside the 0700 work
        folder): ``deploy/.env``, the settings file, ``deploy/site`` (pins, mapping, records), ``deploy/secrets``
        (the pgBackRest cipher, the public backup key) and the volumes of the identity provider and the proxy (its
        CA: without it every clinic PC must trust a new root). Returns the names taken."""
        dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        taken: list[str] = []
        settings = Path(self.env.get("TB_SETTINGS_FILE") or "settings.yaml")
        settings = settings if settings.is_absolute() else self.deploy / settings
        for src, name in ((self.deploy / ".env", "deploy.env"), (settings, "settings.yaml")):
            if src.is_file():
                shutil.copy2(src, dest / name)
                taken.append(name)
        skip = shutil.ignore_patterns("backup.lock", ".audit-*", "*.tmp")
        for sub in ("site", "secrets"):
            if (self.deploy / sub).is_dir():
                shutil.copytree(self.deploy / sub, dest / sub, symlinks=True, ignore=skip, dirs_exist_ok=True)
                taken.append(sub)
        for vol in HOST_VOLUMES:
            root = self.env.get("TB_DOCKER_VOLUMES") or os.environ.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes"
            src = Path(root) / f"trialbox_{vol}" / "_data"
            try:
                if not src.is_dir():
                    continue
                shutil.copytree(src, dest / "volumes" / vol, symlinks=True, dirs_exist_ok=True)
                taken.append(f"volume {vol}")
            except OSError:  # not readable here (not root): the backup goes on without it, and says so
                taken.append(f"volume {vol}: not readable")
        return taken

    def make_backup(self, cfg: Config, quiesce: str | None = None) -> Callable[[list[Path]], list[Path]]:
        """The nightly step (D-455). Each database is one snapshot (``trialbox_wf``, then ``hapi``), then the backup
        container reads every volume; nothing is paused and ``point_in_time`` records the window (each snapshot's
        time, the end of the file reads). ``quiesce`` (default ``cfg.quiesce``, ``TB_BACKUP_QUIESCE``) ``pause``
        keeps D-274's pause of the services that write (all but ``db``) from the first snapshot to the end of the
        container, unpaused whatever happens, under the watchdog's maintenance flag, and never while a job runs.
        Every step's time limit comes from the bytes it reads (:func:`step_timeout`); ``limits`` records them."""
        from tools.trialbox import watchdog

        mode = quiesce or cfg.quiesce

        def run(targets: list[Path]) -> list[Path]:
            before = {t: {p.name for p in t.glob(f"trialbox-*{SUFFIX}")} for t in targets}
            work = Path(tempfile.mkdtemp(prefix=".backup-", dir=self.deploy))  # 0700; plaintext dumps: removed below
            paused: list[str] = []
            started = datetime.now(UTC)
            pit: dict[str, Any] = {"held": False, "paused": [], "why": "the snapshot alone (D-455)",
                                   "snapshot_at": {}, "limits": {}}  # fmt: skip
            run.point_in_time = pit  # type: ignore[attr-defined]
            with contextlib.ExitStack() as stack:
                try:
                    if mode == "pause":
                        jobs = self.running_jobs()
                        if jobs != 0:
                            pit["running_jobs"] = jobs
                            pit["why"] = ("TB_BACKUP_QUIESCE=pause, but " + ("the running jobs could not be counted"
                                          if jobs is None else f"{jobs} job(s) running") + ": not paused, the "
                                          "snapshot alone (D-455)")  # fmt: skip
                        else:
                            paused = self.writers()
                            stack.enter_context(watchdog.maintenance(self.deploy, "backup", "services paused"))
                            if paused:
                                self.box.run(self.box._c("pause", *paused))
                            pit.update({"held": True, "paused": paused, "why": "TB_BACKUP_QUIESCE=pause"})
                    for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):
                        limit = cfg.timeout(self.db_bytes(db, user))
                        pit["limits"][db] = limit
                        pit["snapshot_at"][db] = datetime.now(UTC).isoformat(timespec="seconds")
                        self.snapshot(db, user, work, timeout=limit)
                    self.host_files(work / "host")
                    prev = int((_read_json(cfg.last_file).get("good_file") or {}).get("bytes") or 0) or None
                    vols = volume_bytes(self.env, prev)
                    dumps = tree_bytes(work) or 0
                    limit = cfg.timeout(None if vols is None else dumps + vols)
                    pit["limits"]["container"] = limit
                    self.box._backup_container(work, cfg.public_key, [str(t) for t in targets], keep=cfg.keep,
                                               timeout=limit)  # fmt: skip
                    pit["files_done_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                finally:
                    if paused:
                        self.box.run(self.box._c("unpause", *paused))
                        pit["held_s"] = round((datetime.now(UTC) - started).total_seconds())
                    shutil.rmtree(work, ignore_errors=True)
            new = [sorted({p.name for p in t.glob(f"trialbox-*{SUFFIX}")} - before[t]) for t in targets]
            if not all(new):
                raise RuntimeError("the backup container wrote no new file to every target")
            return [t / n[-1] for t, n in zip(targets, new, strict=True)]

        return run

    def pgbackrest(self, kind: str) -> None:
        """A pgBackRest backup; its limit from the size of every database (D-455: a full one reads them all)."""
        limit = config(self.deploy, self.env).timeout(self.cluster_bytes())
        self.box.run(self.box._c("exec", "-T", "-u", "postgres", "db", "pgbackrest", f"--stanza={STANZA}",
                                 f"--type={kind}", "backup"), timeout=limit)  # fmt: skip

    def archiver(self) -> dict[str, Any]:
        out = self.box.run(self.box._c("exec", "-T", "db", "psql", "-U", self.env.get("POSTGRES_USER") or "hapi",
                                       "-d", "hapi", "-tAc", ARCHIVER_SQL)).strip()  # fmt: skip
        mode, failed, failing, age = [*out.split("|"), "", "0", "f", "-1"][:4]
        return {"archive_mode": mode, "failed_count": int(failed or 0), "failing": failing == "t" and mode != "off",
                "last_archived_age_s": int(age or -1)}  # fmt: skip

    def audit(self, event: str, detail: dict[str, Any]) -> None:
        """Append ``event`` to the box's audit log through the orchestrator. Events kept while it was down
        (``deploy/site/backup-audit-pending.jsonl``) go first, in order (D-274, DI-10); what cannot be sent stays."""
        code = (
            "import json, sys\nfrom tb_common.audit_writer import open_audit\ns = json.load(sys.stdin)\n"
            "open_audit().append(s['event'], actor='backup', input_sha=s['sha'], detail=s['detail'])\n"
        )
        state = self.deploy / "site"
        state.mkdir(parents=True, exist_ok=True)
        pending = state / "backup-audit-pending.jsonl"
        lines = [ln for ln in (pending.read_text(encoding="utf-8").splitlines() if pending.is_file() else []) if ln]
        lines.append(json.dumps({"event": event, "sha": detail.get("sha256") or "", "detail": detail}))
        left: list[str] = []
        for ln in lines:
            if left:  # keep the order: after one fails, the rest wait too
                left.append(ln)
                continue
            f = state / f".audit-{json.loads(ln)['event']}.json"
            f.write_text(ln, encoding="utf-8")
            try:
                self.box.run(self.box._c("exec", "-T", "orchestrator", "python", "-c", code), stdin_file=f)
            except Exception:  # the orchestrator is down: keep the event for the admin, never lose it
                left.append(ln)
            finally:
                f.unlink(missing_ok=True)
        if left:
            pending.write_text("".join(x + "\n" for x in left), encoding="utf-8")
        else:
            pending.unlink(missing_ok=True)


@contextlib.contextmanager
def _lock(deploy: Path) -> Iterator[bool]:
    import fcntl

    (deploy / "site").mkdir(parents=True, exist_ok=True)
    with (deploy / "site" / "backup.lock").open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


# ------------------------------------------------------------------------------------------------ install (D-274)
CRON_NAME = "trialbox-backup"


def set_env(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in a ``deploy/.env`` (replaced in place, else appended); the file keeps its mode."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out = [ln for ln in lines if not ln.startswith(f"{key}=")]
    out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def cron_text(template: str, root: Path, mailto: str) -> str:
    """The cron file for this box: the install folder for ``/opt/trialbox`` and the site's ``MAILTO`` (empty: cron
    mails nothing, the alert goes through ``TB_BACKUP_ALERT_CMD``)."""
    if any(c in str(root) for c in "\n#%") or any(c in mailto for c in "\n\"'"):
        raise ValueError("an install folder or MAILTO with a newline, #, % or a quote")
    out = []
    for ln in template.replace("/opt/trialbox", str(root)).splitlines():
        out.append(f'MAILTO="{mailto}"' if ln.startswith("MAILTO=") else ln)
    return "\n".join(out) + "\n"


def install_cron(cfg: Config, cron_dir: Path, root: Path, has_mta: bool) -> list[str]:
    """Write ``<cron_dir>/trialbox-backup`` (0644). In PRODUCTION an alert route is required (D-274, OPS-028):
    ``TB_BACKUP_ALERT_CMD``, or ``TB_BACKUP_MAILTO`` on a host that has a mail transfer agent; else ValueError."""
    notes = []
    if cfg.mailto and not has_mta:
        msg = "TB_BACKUP_MAILTO is set but this host has no mail transfer agent (sendmail): cron cannot mail"
        if cfg.production and not cfg.alert_cmd:
            raise ValueError(msg + "; set TB_BACKUP_ALERT_CMD (RUNBOOK §5)")
        notes.append("note: " + msg)
    if cfg.production and not cfg.alert_route:
        raise ValueError(
            "PRODUCTION needs a backup alert route: TB_BACKUP_ALERT_CMD (a command that reads the "
            "message on stdin), or TB_BACKUP_MAILTO and a mail relay, in deploy/.env (RUNBOOK §5)"
        )
    if not cfg.alert_route:
        notes.append("note: no backup alert route (TB_BACKUP_ALERT_CMD, TB_BACKUP_MAILTO): alerts reach the audit "
                     "and the admin page only")  # fmt: skip
    template = (cfg.deploy / "backup" / f"{CRON_NAME}.cron").read_text(encoding="utf-8")
    cron_dir.mkdir(parents=True, exist_ok=True)
    dest = cron_dir / CRON_NAME
    tmp = cron_dir / f".{CRON_NAME}.tmp"  # cron reads no file whose name has a dot
    tmp.write_text(cron_text(template, root, cfg.mailto if has_mta else ""), encoding="utf-8")
    os.chmod(tmp, 0o644)
    tmp.replace(dest)
    return [f"cron: {dest} (04:45 nightly backup, hourly age check)", *notes]


def setup_archiving(cfg: Config, ops: ComposeOps, classify: Callable[[Path], Target] | None = None) -> list[str]:
    """WAL archiving on by default (D-274, DATA-024, OPS-048): unless the site wrote ``TB_PG_ARCHIVE_MODE=off``, turn
    it on when the db image carries pgBackRest and the repository is off the box (``TB_PGBACKREST_REPO``, else
    ``pgbackrest-<site>`` on the first off-box target): the cipher pass is made once (``deploy/secrets/pgbackrest``),
    the stanza is created, archiving is switched on and ``pgbackrest check`` must archive a segment, or it is
    switched off again (a failing ``archive_command`` would fill the disk). Returns what was done, in plain words."""
    env_file = cfg.deploy / ".env"
    if cfg.archive_set == "off":
        return ["WAL archiving: off (TB_PG_ARCHIVE_MODE=off in deploy/.env, the site's choice)"]
    if cfg.archive_on:
        return ["WAL archiving: on (deploy/.env)"]
    cls = classify or cfg.classify
    try:
        ops.box.run(ops.box._c("exec", "-T", "db", "sh", "-c", "command -v pgbackrest"))
    except Exception:
        return ["WAL archiving: off: the db image has no pgBackRest (POSTGRES_IMAGE; RUNBOOK §5); doctor warns"]
    repo = cfg.pgbackrest_repo
    if not repo:
        off = [t for t in cfg.targets if cls(t).offbox]
        if not off:
            return ["WAL archiving: off: no off-box target for the pgBackRest repository (TB_BACKUP_TARGETS or "
                    "TB_PGBACKREST_REPO); doctor warns"]  # fmt: skip
        repo = str(off[0] / f"pgbackrest-{safe(cfg.site or 'box')}")
    elif not cls(Path(repo)).offbox:
        return [f"WAL archiving: off: TB_PGBACKREST_REPO {repo} is on this box; doctor warns"]
    Path(repo).mkdir(parents=True, exist_ok=True)
    cipher = cfg.deploy / "secrets" / "pgbackrest" / "cipher.conf"
    if not cipher.is_file():
        import secrets as _secrets

        cipher.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(cipher.parent, 0o700)
        fd = os.open(cipher, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"[global]\nrepo1-cipher-pass={_secrets.token_urlsafe(48)}\n")
    set_env(env_file, "TB_PGBACKREST_REPO", repo)
    pg = ("exec", "-T", "-u", "postgres", "db", "pgbackrest", f"--stanza={STANZA}")
    try:
        uid = ops.box.run(ops.box._c("exec", "-T", "db", "id", "-u", "postgres")).strip() or "999"
        with contextlib.suppress(OSError):  # the container's postgres user reads it (root runs install)
            for f in (cipher.parent, cipher, Path(repo)):
                os.chown(f, int(uid), int(uid))
        ops.box.run(ops.box._c("up", "-d", "db"), timeout=900)  # the repository mount
        ops.box.run(ops.box._c(*pg, "stanza-create"), timeout=900)
        set_env(env_file, "TB_PG_ARCHIVE_MODE", "on")
        ops.box.run(ops.box._c("up", "-d", "db"), timeout=900)
        ops.box.run(ops.box._c(*pg, "check"), timeout=900)
    except Exception as e:
        set_env(env_file, "TB_PG_ARCHIVE_MODE", "off")
        with contextlib.suppress(Exception):
            ops.box.run(ops.box._c("up", "-d", "db"), timeout=900)
        return [f"WAL archiving: off: set-up failed ({type(e).__name__}: {str(e)[-200:]}); RUNBOOK §5"]
    return [f"WAL archiving: on, to {repo} (point-in-time restore; the cipher pass is in {cipher}: give hospital "
            "IT a copy with the backup key)"]  # fmt: skip


def main_install(deploy: Path, cron_dir: Path = Path("/etc/cron.d"), first: bool = True) -> int:
    """``trialbox backup-install`` (install.sh's backup step, D-274): the cron file, WAL archiving, the first
    backup. Exit 1 only when the cron file cannot be installed (in PRODUCTION: no alert route)."""
    from tools.trialbox import update

    cfg = config(deploy, update._env_file(deploy / ".env"))
    try:
        for n in install_cron(cfg, cron_dir, deploy.resolve().parent, shutil.which("sendmail") is not None):
            print(n)
    except (OSError, ValueError) as e:
        print(f"backup-install: {e}")
        return 1
    ops = ComposeOps(deploy)
    for n in setup_archiving(cfg, ops):
        print(n)
    if not first:
        return 0
    if not cfg.public_key.is_file():
        print("first backup: not yet: no backup key (trialbox backup-keygen with hospital IT, RUNBOOK §5); "
              "the cron runs it every night from then on")  # fmt: skip
        return 0
    rc = main_nightly(deploy)
    print("first backup: " + ("done" if rc == 0 else "FAILED (above); backup-status stays red until it works"))
    return 0


class BackupBusy(RuntimeError):
    """Another backup run holds ``deploy/site/backup.lock``."""


def run_backup(deploy: Path, ops: ComposeOps | None = None, quiesce: str | None = None,
               with_pgbackrest: bool = True) -> tuple[Config, ComposeOps, dict[str, Any]]:  # fmt: skip
    """One backup run under ``backup.lock``: the nightly's, and the console's "Back up now" (D-455: ``quiesce``
    ``off``, no pgBackRest). Raises :class:`BackupBusy` when another run holds the lock."""
    from tools.trialbox import update

    with _lock(deploy) as mine:
        if not mine:
            raise BackupBusy("another backup run holds deploy/site/backup.lock")
        ops = ops or ComposeOps(deploy)
        ops.sweep()
        cfg = config(deploy, update._env_file(deploy / ".env"))
        pgb = ops.pgbackrest if cfg.archive_on and with_pgbackrest else None
        return cfg, ops, nightly(cfg, ops.make_backup(cfg, quiesce), ops.audit, pgb)


def main_nightly(deploy: Path) -> int:
    try:
        cfg, ops, res = run_backup(deploy)
    except BackupBusy:
        print("backup-nightly: another backup run holds deploy/site/backup.lock")
        return 1
    for e in res["errors"]:
        print(f"backup-nightly: {e}")
    if res["file"]:
        print(f"backup-nightly: wrote {res['file']['name']} ({res['file']['bytes']} bytes) to "
              f"{len(res['file']['copies'])} targets")  # fmt: skip
    st = status(cfg, archiver=_try(ops.archiver) if cfg.archive_on else None)
    alert(cfg, st, ops.audit, send_cmd(cfg.alert_cmd))
    return 0 if res["ok"] else 1


def main_status(deploy: Path, as_json: bool = False, quiet: bool = False) -> int:
    from tools.trialbox import update

    cfg = config(deploy, update._env_file(deploy / ".env"))
    ops = ComposeOps(deploy)
    st = status(cfg, archiver=_try(ops.archiver) if cfg.archive_on else None)
    alert(cfg, st, ops.audit, send_cmd(cfg.alert_cmd))
    if quiet and st["level"] == "ok":
        return 0
    if as_json:
        print(json.dumps(st, indent=1, ensure_ascii=False))
    else:
        good = st["newest_good"]
        print(f"backup {st['level'].upper()}: newest good "
              + (f"{Path(good['path']).name} ({st['age_hours']} h old)" if good else "none"))  # fmt: skip
        for p in st["problems"]:
            print(f"  - {p}")
    return 0 if st["level"] == "ok" else 1


def _try(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as e:  # the db is down: that is an alert too
        return {"failing": True, "error": f"{type(e).__name__}: {str(e)[-200:]}"}
