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


def prune(target: Path, keep: int, prefix: str) -> list[Path]:
    """Keep the newest ``keep`` backups of one box (``prefix``, ``trialbox-<site>-``) in a target; remove its older
    ones (with their sidecar) and its stale ``.part`` files. Other boxes' files on a shared target are never touched."""
    files = sorted(target.glob(f"{prefix}*{SUFFIX}"), key=lambda p: p.name.rsplit("-", 1)[-1])
    files = [f for f in files if site_prefix(f.name) == prefix]
    gone = files[:-keep] if keep > 0 else []
    gone += [sidecar(p) for p in gone]
    gone += [p for p in target.glob(f"{prefix}*{SUFFIX}*.part") if site_prefix(p.name.split(SUFFIX)[0] + SUFFIX)
             == prefix]  # fmt: skip
    for p in gone:
        p.unlink(missing_ok=True)
    return gone


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


_ROW = ("SELECT %L || ''|'' || count(*) || ''|'' || "
        "md5(COALESCE(string_agg(t::text, chr(10) ORDER BY t::text), '''')) FROM %I.%I t")  # fmt: skip
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
    return {"db": name, "rows_from": "snapshot", "refdata_schema": refdata,
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


def config(deploy: Path, env: Mapping[str, str]) -> Config:
    """The schedule's settings from ``deploy/.env`` (``env``, quotes removed), with the process environment winning."""
    e = {k: _unquote(v) for k, v in {**env, **{k: v for k, v in os.environ.items() if k.startswith("TB_")}}.items()}
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
                prune(f.parent, cfg.keep, site_prefix(f.name))
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

    def snapshot(self, db: str, user: str, work: Path) -> None:
        """:func:`snapshot_script` in the db container; its files are copied to ``work`` and removed there."""
        refdata = REFDATA if db == "trialbox_wf" else None
        script = work / f"{db}.sql"
        script.write_text(snapshot_script(CONTAINER_SPOOL, db, "pg_dump", f"-U {user} -d {db}", (), refdata))
        try:
            self.box.run(self.box._c("exec", "-T", "db", "sh", "-c",
                                     f"umask 077; mkdir -p {CONTAINER_SPOOL}; cat > {CONTAINER_SPOOL}/{db}.sql; "
                                     f"psql -X -q -v ON_ERROR_STOP=1 -U {user} -d {db} -f {CONTAINER_SPOOL}/{db}.sql"),
                         stdin_file=script, timeout=7200)  # fmt: skip
            self.box.run(self.box._c("cp", f"db:{CONTAINER_SPOOL}/.", str(work)), timeout=7200)
        finally:
            with contextlib.suppress(Exception):
                self.box.run(self.box._c("exec", "-T", "db", "rm", "-rf", CONTAINER_SPOOL))
        script.unlink(missing_ok=True)
        (work / f"{db}.sql").unlink(missing_ok=True)
        _write_json(work / f"{db}.dump.json", snapshot_meta(db, refdata))
        parse_snapshot(work, db)  # the dump finished and every file is there, or the run fails here

    def make_backup(self, cfg: Config) -> Callable[[list[Path]], list[Path]]:
        def run(targets: list[Path]) -> list[Path]:
            before = {t: {p.name for p in t.glob(f"trialbox-*{SUFFIX}")} for t in targets}
            work = Path(tempfile.mkdtemp(prefix=".backup-", dir=self.deploy))  # 0700; plaintext dumps: removed below
            try:
                for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):
                    self.snapshot(db, user, work)
                self.box._backup_container(work, cfg.public_key, [str(t) for t in targets], keep=cfg.keep)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            new = [sorted({p.name for p in t.glob(f"trialbox-*{SUFFIX}")} - before[t]) for t in targets]
            if not all(new):
                raise RuntimeError("the backup container wrote no new file to every target")
            return [t / n[-1] for t, n in zip(targets, new, strict=True)]

        return run

    def pgbackrest(self, kind: str) -> None:
        self.box.run(self.box._c("exec", "-T", "-u", "postgres", "db", "pgbackrest", f"--stanza={STANZA}",
                                 f"--type={kind}", "backup"), timeout=4 * 3600)  # fmt: skip

    def archiver(self) -> dict[str, Any]:
        out = self.box.run(self.box._c("exec", "-T", "db", "psql", "-U", self.env.get("POSTGRES_USER") or "hapi",
                                       "-d", "hapi", "-tAc", ARCHIVER_SQL)).strip()  # fmt: skip
        mode, failed, failing, age = [*out.split("|"), "", "0", "f", "-1"][:4]
        return {"archive_mode": mode, "failed_count": int(failed or 0), "failing": failing == "t" and mode != "off",
                "last_archived_age_s": int(age or -1)}  # fmt: skip

    def audit(self, event: str, detail: dict[str, Any]) -> None:
        code = (
            "import json, sys\nfrom tb_common.audit import AuditLog\ns = json.load(sys.stdin)\n"
            "AuditLog('/data/audit').append(s['event'], actor='backup', input_sha=s['sha'], detail=s['detail'])\n"
        )
        state = self.deploy / "site"
        state.mkdir(parents=True, exist_ok=True)
        f = state / f".audit-{event}.json"
        f.write_text(json.dumps({"event": event, "sha": detail.get("sha256") or "", "detail": detail}))
        try:
            self.box.run(self.box._c("exec", "-T", "orchestrator", "python", "-c", code), stdin_file=f)
            f.unlink(missing_ok=True)
        except Exception:  # the orchestrator is down: keep the event for the admin, never lose it
            with (state / "backup-audit-pending.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(f.read_text() + "\n")
            f.unlink(missing_ok=True)


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


def main_nightly(deploy: Path) -> int:
    from tools.trialbox import update

    with _lock(deploy) as mine:
        if not mine:
            print("backup-nightly: another backup run holds deploy/site/backup.lock")
            return 1
        ops = ComposeOps(deploy)
        ops.sweep()
        cfg = config(deploy, update._env_file(deploy / ".env"))
        res = nightly(cfg, ops.make_backup(cfg), ops.audit, ops.pgbackrest if cfg.archive_on else None)
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
