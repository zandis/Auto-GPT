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

**Nightly** (:func:`nightly`). The script runs in the ``db`` container (``docker compose exec``); the dump streams
to a 0700 folder under ``deploy/`` (10G-1: nothing is copied out of the container's tmpfs /tmp, where only the
script's small files are written), and both are removed right after.
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
Authelia and Caddy volumes). ``backup-install`` (install.sh) writes the schedule (a systemd timer where systemd is
the init, else the cron file; H-92), turns WAL archiving on where the
image and an off-box share allow it, and runs the first backup; in PRODUCTION it needs an alert route.

**Incremental (PERF-010, D-968, D-977).** Each night the host decides before the job starts
(:meth:`ComposeOps.incremental`): with ``TB_BACKUP_RESTIC=auto`` (the default) and the KEK covered by the custodians'
shares (a shamir KEK, or a TPM KEK whose escrow set is the current one), the host makes ``restic.key`` under the KEK
if it is not there yet, and the job runs in the release's backup image (``TB_BACKUP_IMAGE``, restic inside) with
``--restic``: the lake's served files go to the restic repository beside each target, the rest to the ``.tbbak``.
Otherwise the single ``.tbbak``, as before, and the reason. The choice is in ``backup-last.json`` and the audit
(``incremental``); a restic key the custodians could not open is never made.

**Windows (WSL2; NEW-WIN-7, D-608).** A Windows drive mounted in WSL2 (``/mnt/e``) is off-box only when the
Windows installer recorded the workstation's own drives (``deploy/site/box/windows-drives``), the drive is none
of them, and its root carries the installer's mark of an outside drive (``box-install.ps1 -BackupDrive E:``). A
share of the PC itself (``\\\\localhost``, ``\\\\wsl.localhost``) is this box. The speed of a target's path is
measured once (``deploy/windows/wsl-setup.sh backup-speed``, recorded in ``deploy/site/box/backup-speed``) and
``trialbox doctor`` holds ``TB_BACKUP_MIN_MBPS`` against it.

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
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.update_status import write_atomic

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
# D-455: jobs that are running or queued to run (not done, failed or waiting for an approval; orchestrator/db.py)
RUNNING_JOBS_SQL = "SELECT count(*) FROM orch.jobs WHERE state NOT IN ('done', 'failed', 'awaiting_approval')"
# D-455 (R1, the owner's ruling of 2026-11-12): the backup waits while a job runs, at most TB_BACKUP_JOB_WAIT_S, then
# takes the snapshot anyway (it is consistent on its own) and records the jobs it ran beside. The default is the
# night's own schedule: the age alert is MAX_AGE_HOURS (36) after the last good backup and the cron runs every 24 h,
# so a night's backup may end at most 12 h after its 04:45 start and still keep the box green; half of that (6 h) is
# the wait, the other half the backup itself (1 to 5 h for 200 to 500 GB at 500,000 patients, review F-02).
JOB_WAIT_S = (MAX_AGE_HOURS - 24) / 2 * 3600
JOB_POLL_S = 60.0  # how often the job count is asked while the backup waits (a poll, not a limit)
JOBS_LIST_SQL = ("SELECT job_id || '|' || type FROM orch.jobs WHERE state NOT IN ('done', 'failed', "
                 "'awaiting_approval') ORDER BY received_at")  # fmt: skip
QUERY_TIMEOUT_S = 60.0  # a catalogue query (a size, a count), not work sized by the data: TB_BACKUP_QUERY_TIMEOUT_S


def query_timeout(env: Mapping[str, str]) -> float:
    """The limit of the backup's small queries (the database sizes, the job count): ``TB_BACKUP_QUERY_TIMEOUT_S``."""
    try:
        v = float(
            env.get("TB_BACKUP_QUERY_TIMEOUT_S") or os.environ.get("TB_BACKUP_QUERY_TIMEOUT_S") or QUERY_TIMEOUT_S
        )
    except ValueError:
        return QUERY_TIMEOUT_S
    return v if v > 0 else QUERY_TIMEOUT_S


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


MIN_GOOD = 2  # D-455 (M1): retention by size never leaves fewer good backups on a target without an error


def prune(target: Path, keep: int, prefix: str, max_bytes: int | None = None, min_good: int = 1,
          notes: list[str] | None = None) -> list[Path]:  # fmt: skip
    """Keep the newest ``keep`` backups of one box (``prefix``, ``trialbox-<site>-``) in a target; remove its older
    ones (with their sidecar) and its stale ``.part`` files. Other boxes' files on a shared target are never touched.
    Only a file with its ``.sha256`` sidecar counts as a backup (D-455, M1): one without (a run cut short) is neither
    counted nor kept as a backup, and is left for a person. ``max_bytes`` (F-26): the kept backups' total size too,
    the oldest first, but never fewer than ``min_good``; when that is still too big, ``notes`` says so."""
    files = sorted(target.glob(f"{prefix}*{SUFFIX}"), key=lambda p: p.name.rsplit("-", 1)[-1])
    files = [f for f in files if site_prefix(f.name) == prefix and read_sidecar(f) is not None]
    gone = files[:-keep] if keep > 0 else []
    if max_bytes is not None:
        kept = files[len(gone) :]
        total = sum(_size(f) for f in kept)
        while len(kept) > max(min_good, 1) and total > max_bytes:
            total -= _size(kept[0])
            gone.append(kept.pop(0))
        if total > max_bytes and notes is not None:
            notes.append(f"{target}: the {len(kept)} newest good backups take {total // 2**20} MiB, more than the "
                         f"{max_bytes // 2**20} MiB TB_BACKUP_KEEP_SHARE allows; kept anyway (a bigger target, or "
                         "a larger share)")  # fmt: skip
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
    try:
        readable = root.is_dir() and os.access(root, os.R_OK | os.X_OK)
    except OSError:
        readable = False
    for vol in update.BACKUP_VOLUMES.values():
        d = root / f"trialbox_{vol}" / "_data"
        n = (0 if not d.parent.exists() else tree_bytes(d)) if readable else None  # a volume never made: 0 bytes
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


#: 10G-1 (D-1323): the compose nightly's stream helper, written to the db container's spool and run as
#: ``sh <spool>/emit NAME``: it copies its stdin to its stdout (psql's own, so ``exec -T``'s) while ``wc -c`` counts
#: the bytes through a FIFO, then appends "<bytes> NAME" to the spool's index. ``sh <spool>/emit --end`` prints the
#: index and a fixed trailer (:data:`STREAM_TRAILER`). Nothing of the data is written in the spool (a tmpfs).
EMIT_SH = r"""d=$(dirname "$0")
if [ "$1" = --end ]; then
  [ -f "$d/index" ] || : > "$d/index"
  cat "$d/index"; printf 'TBSTREAM %016d\n' "$(wc -c < "$d/index")"; exit 0
fi
f="$d/.fifo.$$"
mkfifo "$f" || exit 1
wc -c < "$f" > "$f.n" &
tee "$f"; rc=$?
wait
n=$(tr -d ' ' < "$f.n"); rm -f "$f" "$f.n"
printf '%s %s\n' "$n" "$1" >> "$d/index"
exit $rc
"""
STREAM_TRAILER = 26  # len("TBSTREAM %016d\n")


def stream_items(name: str) -> tuple[str, ...]:
    """What ``snapshot_script(..., stream=True)`` sends for database ``name``, in order: the dump, the row counts,
    the packs, each of the hospital's own reference tables (an empty one when it has none) and the exit code."""
    return (f"{name}.dump", f"{name}.rows", f"{name}.packs", *(f"{name}.site.{t}.copy" for t in BULK_REFDATA),
            f"{name}.dump.rc")  # fmt: skip


def split_stream(stream: Path, work: Path, name: str) -> list[str]:
    """10G-1 / D-455: the compose nightly's stdout (``snapshot_script(..., stream=True)``) back into the files the
    staged form writes: ``<name>.dump`` first (the stream file is truncated to it and renamed: never copied), then
    each small file. The byte counts the container recorded must add up to what arrived, else the backup fails: a
    short or damaged stream is never sealed as a good backup. Exactly :func:`stream_items` must be there (review
    B1): a part missing or one more fails the backup."""
    want = stream_items(name)
    size = stream.stat().st_size
    with stream.open("rb") as fh:
        if size < STREAM_TRAILER:
            raise RuntimeError(f"the snapshot stream of {name} is {size} bytes: no trailer")
        fh.seek(size - STREAM_TRAILER)
        tail = fh.read(STREAM_TRAILER)
        if not (tail.startswith(b"TBSTREAM ") and tail.endswith(b"\n") and tail[9:25].isdigit()):
            raise RuntimeError(f"the snapshot stream of {name} has no trailer (cut short?)")
        ilen = int(tail[9:25])
        body = size - STREAM_TRAILER - ilen
        if body < 0:
            raise RuntimeError(f"the snapshot stream of {name} is shorter than its index")
        fh.seek(body)
        items: list[tuple[int, str]] = []
        for ln in fh.read(ilen).decode("utf-8").splitlines():
            count, _, item = ln.partition(" ")
            if not count.isdigit() or item not in want or item in (i for _, i in items):
                raise RuntimeError(f"the snapshot stream of {name} has a bad index line {ln[:80]!r}")
            items.append((int(count), item))
        missing = sorted(set(want) - {i for _, i in items})
        if missing:  # review B1: exactly the expected set; a lost part is a failed backup, never "no rows"
            raise RuntimeError(f"the snapshot stream of {name} lacks {', '.join(missing)}")
        if sum(n for n, _ in items) != body:
            raise RuntimeError(f"the snapshot stream of {name}: the container wrote {sum(n for n, _ in items)} bytes, "
                               f"{body} arrived")  # fmt: skip
        if not items or items[0][1] != f"{name}.dump":
            raise RuntimeError(f"the snapshot stream of {name} does not start with its dump")
        off = items[0][0]
        for n, item in items[1:]:
            fh.seek(off)
            fd = os.open(work / item, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out:
                left = n
                while left:
                    chunk = fh.read(min(left, 1 << 20))
                    if not chunk:
                        raise RuntimeError(f"the snapshot stream of {name} ended inside {item}")
                    out.write(chunk)
                    left -= len(chunk)
            off += n
    os.truncate(stream, items[0][0])
    stream.replace(work / f"{name}.dump")
    return [i for _, i in items]


def snapshot_script(
    out: str, name: str, pg_dump: str, conn: str, schemas: Sequence[str], refdata: str | None,
    stream: bool = False,
) -> str:  # fmt: skip
    """A ``psql`` script: one ``REPEATABLE READ`` transaction exports its snapshot; ``pg_dump --snapshot`` writes
    ``<out>/<name>.dump`` from it (exit code in ``.dump.rc``); the same session writes every table's row count and
    content hash (``.rows``), the reference packs (``.packs``) and the hospital's own reference rows
    (``.site.<table>.copy``). ``conn`` is how ``pg_dump`` reaches the database where ``psql`` runs.
    ``stream`` (the compose nightly, 10G-1): each of those goes through ``sh <out>/emit NAME`` (:data:`EMIT_SH`) to
    psql's own stdout instead, the dump first, the exit code last, then the index and trailer (:func:`split_stream`
    takes them apart on the host). Only the script, the snapshot id, the exit code and the index are written in
    ``<out>``: the db container's /tmp is a tmpfs (memory) that ``docker cp`` cannot read."""
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
    emit = f"sh {out}/emit"

    def to(item: str) -> str:  # where psql's \\o sends one output: a file, or the stream helper (a pipe)
        return f"\\o |{emit} {name}.{item}" if stream else f"\\o '{o}.{item}'"

    run = f'{pg_dump} -Fc -Z0 --no-owner --no-privileges --snapshot="$(cat {o}.snapshot)" {conn} {dump_args}'
    if stream:  # the dump through the stream helper; its exit code still to a file (a few bytes)
        dump = f'{{ {run}; echo $? > "{o}.dump.rc"; }} | {emit} {name}.dump'
    else:
        dump = f'{run} -f "{o}.dump"; echo $? > "{o}.dump.rc"'
    lines = [
        "\\pset format unaligned",
        "\\pset tuples_only on",
        "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;",
        f"SELECT pg_export_snapshot() \\g '{o}.snapshot'",
        f"\\! sh -c '{dump}'",
        to("rows"),
        f"SELECT format('{_ROW}', table_schema || '.' || table_name, table_schema, table_name) {tables} "
        f"AND NOT (table_schema = {rs} AND table_name IN ({bulk})) ORDER BY table_schema, table_name \\gexec",
        f"SELECT format('{_ROW}{_SITE}', 'site:' || table_schema || '.' || table_name, table_schema, table_name, "
        f"table_schema) {tables} AND table_schema = {rs} AND table_name IN ({bulk}) AND {has_src} "
        "ORDER BY table_name \\gexec",
        to("packs"),
        "SELECT format('SELECT pack_id || ''|'' || data_as_of || ''|'' || origin FROM %I.pack ORDER BY pack_id', "
        f"table_schema) {tables} AND table_schema = {rs} AND table_name = 'pack' \\gexec",
    ]
    for t in BULK_REFDATA:
        lines += [
            to(f"site.{t}.copy"),
            f"SELECT format('COPY (SELECT * FROM %I.%I t{_SITE}) TO STDOUT', table_schema, table_name, table_schema) "
            f"{tables} AND table_schema = {rs} AND table_name = {_lit(t)} AND {has_src} \\gexec",
        ]
    lines += ["\\o", "COMMIT;"]
    if stream:  # the exit code (a few bytes), then the index and the trailer
        lines += [f"\\! sh -c '{emit} {name}.dump.rc < \"{o}.dump.rc\"; {emit} --end'"]
    return "\n".join([*lines, ""])


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
    # network share | usb disk | declared off-box | this box | declared, but on this box's disk | (WSL2, NEW-WIN-7)
    # Windows drive X:, not one of this PC's own
    kind: str
    offbox: bool
    fstype: str = ""


def _unescape(s: str) -> str:
    return s.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def _mounts(text: str | None) -> list[tuple[str, str, str, str]]:
    """(source, mount point, file system, options) of every mount."""
    if text is None:
        try:
            text = Path("/proc/mounts").read_text(encoding="utf-8")
        except OSError:
            text = ""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 3:
            out.append((_unescape(f[0]), _unescape(f[1]), f[2], _unescape(f[3]) if len(f) > 3 else ""))
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


SPEED_FILE = "backup-speed"  # under deploy/site/box: "<MB/s>\t<MiB written>\t<path>" per measured target path


def measured_speeds(deploy: Path) -> dict[str, tuple[float, int]]:
    """NEW-WIN-7 (D-608): what ``wsl-setup.sh backup-speed`` measured for each backup path: (MB/s, MiB written)."""
    out: dict[str, tuple[float, int]] = {}
    try:
        lines = (deploy / "site" / "box" / SPEED_FILE).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return out
    for line in lines:
        speed, _, rest = line.partition("\t")
        mib, _, path = rest.partition("\t")
        try:
            value, written = float(speed), int(mib)
        except ValueError:
            continue
        if path and math.isfinite(value) and value > 0 and written > 0:
            out[path] = (value, written)  # a later line for the same path is the newer measurement
    return out


WINDOWS_DRIVES_FILE = "windows-drives"  # under deploy/site/box: the letters of the workstation's own drives


def windows_own_drives(deploy: Path) -> frozenset[str] | None:
    """NEW-WIN-7 (D-608): the drive letters the Windows installer recorded as the workstation's own (the system
    drive, the drive of WSL2's virtual disk, every other disk that is not on USB). ``None`` when there is no
    record: then no Windows drive counts as off-box."""
    try:
        text = (deploy / "site" / "box" / WINDOWS_DRIVES_FILE).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):  # no record, or one that is not text: no record
        return None
    letters = [p.strip().upper() for p in text.split(",")]
    if not letters or not all(len(p) == 1 and "A" <= p <= "Z" for p in letters):
        return None
    return frozenset(letters)


OUTSIDE_MARK = ".trialbox-outside-drive"  # at the root of an outside drive: written by box-install.ps1 -BackupDrive
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "wsl.localhost", "wsl$"})


def _windows_path(src: str, fstype: str, options: str = "") -> tuple[str, str]:
    """(drive letter, share host) of a Windows path mounted in WSL2; ``("", "")`` for anything else.

    WSL2 mounts a Windows drive or share with the file system ``9p`` (``drvfs`` under WSL1) and writes the Windows
    path as the source (``E:\\``, ``\\\\nas\\share``) or, with the source ``drvfs``, in the options
    (``aname=drvfs;path=E:\\``). Where both name a path they must agree: a line that names two is believed in
    neither (the strict side)."""
    if fstype not in ("9p", "drvfs"):
        return "", ""
    named = [src] if src not in ("", "drvfs", "none") else []
    by_option = re.search(r"(?:^|[;,])path=([^;,]*)", options)
    if by_option and (fstype == "drvfs" or re.search(r"(?:^|[;,])aname=drvfs(?:[;,]|$)", options)):
        named.append(by_option.group(1))
    found: set[tuple[str, str]] = set()
    for text in named:
        drive = re.fullmatch(r"([A-Za-z]):[\\/]?", text)
        share = re.match(r"(?:\\\\|//)([^\\/]+)[\\/]", text + "/")
        found.add((drive.group(1).upper(), "") if drive else ("", share.group(1).lower()) if share else ("", ""))
    return found.pop() if len(found) == 1 else ("", "")


def target_kind(
    path: Path,
    mounts_text: str | None = None,
    declared: Sequence[str] = (),
    sys_block: Path = Path("/sys/class/block"),
    local: Sequence[Path] = (Path("/"),),
    windows_own: frozenset[str] | None = None,
) -> Target:
    """Where ``path`` lives: on a network share, a USB disk, a declared off-box volume, or this box's own disks.
    A declared path counts only on another device than every ``local`` path, or with a ``.trialbox-offbox`` file.

    Under WSL2 (NEW-WIN-7, D-608) a Windows drive counts as off-box only when all of this holds: the Windows
    installer recorded the workstation's own drives (``windows_own``), the drive is none of them, and the drive's
    own root carries the mark the installer writes on a disk it saw on USB (``box-install.ps1 -BackupDrive``).
    The mark travels with the disk: a letter that later names another volume has none."""
    real = _resolve(Path(path))
    best = ("", "/", "", "")
    for src, mnt, fstype, options in _mounts(mounts_text):
        m = Path(mnt)
        if (real == m or m in real.parents) and len(mnt) >= len(best[1]):
            best = (src, mnt, fstype, options)
    src, mount_point, fstype, options = best
    letter, host = _windows_path(src, fstype, options)
    for d in declared:
        dd = _resolve(Path(d))
        if d and (real == dd or dd in real.parents):
            here = _existing(dd)
            marked = (dd / OFFBOX_MARKER).is_file()
            # a Windows drive is always "another device" than WSL2's own disk, the data drive too: it is not
            # taken as off-box for that
            other_dev = not letter and all(here.stat().st_dev != _existing(p).stat().st_dev for p in local)
            if marked or other_dev:
                return Target(str(path), "declared off-box", True)
            return Target(str(path), "declared, but on this box's disk (no .trialbox-offbox file)", False)
    if fstype in ("9p", "drvfs"):
        unc_host = host
    else:
        unc = re.match(r"(?:\\\\|//)([^\\/]+)", src)
        unc_host = unc.group(1).lower() if unc else ""
    if unc_host in LOCAL_HOSTS:
        return Target(str(path), "this box", False, fstype)  # a share of this PC itself, or WSL2's own files
    if fstype in NETWORK_FS or unc_host:  # a UNC source: a Windows share mounted in WSL2
        return Target(str(path), "network share", True, fstype)
    if _is_usb(src, sys_block):
        return Target(str(path), "usb disk", True, fstype)
    if letter and windows_own is not None and letter not in windows_own:
        if (Path(mount_point) / OUTSIDE_MARK).is_file():
            return Target(str(path), f"Windows drive {letter}:, an outside drive", True, fstype)
        return Target(
            str(path),
            f"Windows drive {letter}:, not marked as an outside drive (box-install.ps1 -BackupDrive {letter}:)",
            False,
            fstype,
        )
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
    alert_page: bool = False  # D-735: TB_BACKUP_ALERT_ROUTE=health-page, the site chose the /admin health tab
    alert_watcher: str = ""  # 10K-21 (D-1365): TB_BACKUP_ALERT_WATCHER, the person who opens it every working day
    archive_set: str = ""  # TB_PG_ARCHIVE_MODE as written ("" when the site never chose)
    pgbackrest_repo: str = ""
    keep_share: float = KEEP_SHARE  # D-455: TB_BACKUP_KEEP_SHARE
    min_mbps: float = MIN_MBPS  # D-455: TB_BACKUP_MIN_MBPS
    step_start_s: float = STEP_START_S  # D-455: TB_BACKUP_STEP_START_S
    quiesce: str = "off"  # D-455: TB_BACKUP_QUIESCE, off (the snapshot alone) or pause
    restic: str = "auto"  # D-977: TB_BACKUP_RESTIC, auto (the lake to restic when shares cover the KEK) or off
    # D-455 (R1): TB_BACKUP_JOB_WAIT_S as config() reads it (default JOB_WAIT_S); a Config built in code waits 0 s
    job_wait_s: float = 0.0
    setting_errors: list[str] = field(default_factory=list)  # D-455: a bad setting fails the run with a record

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
        return bool(self.alert_cmd or self.mailto or self.alert_page)

    def page_only(self, has_mta: bool) -> bool:
        """D-735: the health tab is the only working route: no alert command, and no ``MAILTO`` that this host can
        send (a box's settings always name the owner's address; without a mail transfer agent cron mails nothing)."""
        return self.alert_page and not self.alert_cmd and not (self.mailto and has_mta)

    def page_watch(self) -> str:
        """10K-21 (D-1365): who opens the health tab every working day, as the route is shown; or the next action."""
        if self.alert_watcher:
            return f"{self.alert_watcher} opens the health tab every working day (TB_BACKUP_ALERT_WATCHER)"
        return ("nobody is named to open the health tab every working day: set TB_BACKUP_ALERT_WATCHER in deploy/.env "
                "to that person's name (D-1365)")  # fmt: skip

    @property
    def last_file(self) -> Path:
        return self.deploy / "site" / "backup-last.json"

    @property
    def alert_file(self) -> Path:
        return self.deploy / "site" / "backup-alert.json"

    def classify(self, p: Path) -> Target:
        return target_kind(
            p,
            declared=self.declared_offbox,
            local=(Path("/"), self.deploy),
            windows_own=windows_own_drives(self.deploy),
        )


def _split(v: str) -> list[str]:
    return [t for t in v.replace(",", " ").split() if t]


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


PAGE_ROUTE = "health-page"
ROUTE_HINT = (
    "TB_BACKUP_ALERT_CMD (a command that reads the message on stdin), or TB_BACKUP_MAILTO and a mail relay, or, on a "
    f"box with no mail, TB_BACKUP_ALERT_ROUTE={PAGE_ROUTE} (the /admin health tab), in deploy/.env (RUNBOOK §5)"
)


def has_mta() -> bool:
    """Whether this host can send cron's mail (a mail transfer agent's ``sendmail``)."""
    return shutil.which("sendmail") is not None


def _alert_page(e: Mapping[str, str], errors: list[str]) -> bool:
    """``TB_BACKUP_ALERT_ROUTE`` (D-735): empty, or ``health-page``; any other value is a setting error, no route."""
    raw = (e.get("TB_BACKUP_ALERT_ROUTE") or "").strip()
    if not raw:
        return False
    if raw.lower() == PAGE_ROUTE:
        return True
    errors.append(f"TB_BACKUP_ALERT_ROUTE={raw!r} is not {PAGE_ROUTE!r} (deploy/.env, RUNBOOK §5)")
    return False


def _num(e: Mapping[str, str], key: str, default: float, errors: list[str], hi: float | None = None,
         zero: bool = False) -> float:  # fmt: skip
    """A positive number setting (D-455): a value that is not a number, not above 0 or above ``hi`` is reported in
    ``errors`` (the run then fails with a record) and the default is used meanwhile."""
    raw = (e.get(key) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        errors.append(f"{key}={raw!r} is not a number (deploy/.env)")
        return default
    if not (v >= 0 if zero else v > 0) or (hi is not None and v > hi):
        low = "0 or more" if zero else "above 0"
        errors.append(f"{key}={raw!r} must be {low}{f' and at most {hi:g}' if hi is not None else ''} (deploy/.env)")
        return default
    return v


def absolute(path: Path) -> Path:
    """H-100: ``path`` made absolute against the working folder, links kept (``--deploy deploy`` from the install
    folder). The container engine reads a bind source that is not absolute (``deploy/secrets/backup.pub``) as the
    name of a volume, so every folder and file the backup container binds goes through here first."""
    return Path(os.path.abspath(path))


def config(deploy: Path, env: Mapping[str, str], process_env: bool = True) -> Config:
    """The schedule's settings from ``deploy/.env`` (``env``, quotes removed), with the process environment winning
    (``process_env``; doctor passes its own merged settings and False)."""
    proc = {k: v for k, v in os.environ.items() if k.startswith("TB_")} if process_env else {}
    e = {k: _unquote(v) for k, v in {**env, **proc}.items()}
    errors: list[str] = []
    return Config(
        deploy=deploy,
        targets=[Path(t) for t in _split(e.get("TB_BACKUP_TARGETS", ""))],
        public_key=absolute(Path(e.get("TB_BACKUP_PUBKEY") or deploy / "secrets" / "backup.pub")),
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
        alert_page=_alert_page(e, errors),
        alert_watcher=(e.get("TB_BACKUP_ALERT_WATCHER") or "").strip(),  # 10K-21 (D-1365)
        archive_set=(e.get("TB_PG_ARCHIVE_MODE") or "").lower(),
        pgbackrest_repo=e.get("TB_PGBACKREST_REPO", ""),
        keep_share=_num(e, "TB_BACKUP_KEEP_SHARE", KEEP_SHARE, errors, hi=1.0),
        min_mbps=_num(e, "TB_BACKUP_MIN_MBPS", MIN_MBPS, errors),
        step_start_s=_num(e, "TB_BACKUP_STEP_START_S", STEP_START_S, errors),
        quiesce="pause" if (e.get("TB_BACKUP_QUIESCE") or "off").lower() == "pause" else "off",
        job_wait_s=_num(e, "TB_BACKUP_JOB_WAIT_S", JOB_WAIT_S, errors, zero=True),
        restic=_restic_setting(e, errors),
        setting_errors=errors,
    )


def _restic_setting(e: Mapping[str, str], errors: list[str]) -> str:
    """D-977: ``TB_BACKUP_RESTIC`` is ``auto`` (the default) or ``off``; anything else is a setting error."""
    raw = (e.get("TB_BACKUP_RESTIC") or "auto").strip().lower()
    if raw not in ("auto", "off"):
        errors.append(f"TB_BACKUP_RESTIC={raw!r} is not auto or off (deploy/.env)")
        return "off"
    return raw


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
    if cfg.setting_errors:
        errors += [f"bad setting: {x}" for x in cfg.setting_errors]
    elif not cfg.targets:
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
                sha = read_sidecar(f)
                if sha is None:
                    raise RuntimeError(f"{f} has no .sha256 sidecar: the backup did not complete")
                copies.append({"path": str(f), "bytes": f.stat().st_size, "sha256": sha})
            if not copies or len({(c["sha256"], c["bytes"]) for c in copies}) != 1:
                raise RuntimeError("the copies of the backup differ or none was written")
            if len(copies) != len(cfg.targets):
                raise RuntimeError(f"written to {len(copies)} of {len(cfg.targets)} targets")
            notes: list[str] = []
            for f in files:  # D-455 (M1): only after every copy is checked, and only good backups count
                prune(f.parent, cfg.keep, site_prefix(f.name), cfg.keep_bytes(f.parent), MIN_GOOD, notes)
            errors += notes
            res["file"] = {"name": Path(copies[0]["path"]).name, "bytes": copies[0]["bytes"],
                           "sha256": copies[0]["sha256"], "copies": copies}  # fmt: skip
        except Exception as e:  # every failure is recorded, audited and alerted (exit 1)
            errors.append(f"backup failed: {type(e).__name__}: {str(e)[-400:]}")
    pit = getattr(make_backup, "point_in_time", None)
    if pit is not None:  # D-455: what the point in time is (the snapshots, the files' window, a pause if any)
        res["point_in_time"] = dict(pit)
    inc = getattr(make_backup, "incremental", None)
    if inc is not None:  # D-977: whether the lake went to restic tonight, and why (never a key)
        res["incremental"] = dict(inc)
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
              "beside_jobs": (res.get("point_in_time") or {}).get("beside_jobs"),
              "incremental": res.get("incremental"), "errors": errors}  # fmt: skip
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


def drill_failure(deploy: Path) -> str:
    """T-730d (D-892): the last restore drill's failure in plain words, or "" (none, or a later one passed)."""
    rec = _read_json(deploy / "site" / "backup-verified.json")
    failed, passed = str(rec.get("drill_failed_at") or ""), str(rec.get("at") or "")
    if not failed or (passed and passed > failed):
        return ""
    return (f"the restore drill of {failed[:10]} failed: {str(rec.get('drill_error') or '?')[:200]} "
            "(trialbox restore-drill, RUNBOOK §5)")  # fmt: skip


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
        problems.append("no alert route: set " + ROUTE_HINT)
    if last and not last.get("ok"):
        problems.append(f"the last nightly backup at {last.get('at', '?')} failed (deploy/site/backup-last.json)")
    if last.get("pgbackrest") and not last["pgbackrest"].get("ok"):
        problems.append("the last pgBackRest backup failed (deploy/site/backup-last.json)")
    drill = drill_failure(cfg.deploy)
    if drill:  # T-730d (D-892): a failed restore drill goes through the alert route, until a drill passes
        problems.append(drill)
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


def mode_of(path: Path, default: int = 0o644) -> int:
    """The mode a file rewritten whole keeps (H-142 .k): its own, or ``default`` (``open``'s under umask 022)."""
    try:
        return path.stat().st_mode & 0o7777
    except OSError:
        return default


class ComposeOps:
    """The nightly run's steps on a site box (``docker compose --project-directory deploy``)."""

    def __init__(self, deploy: Path, run: Callable[..., str] | None = None) -> None:
        from tools.trialbox import update

        deploy = absolute(deploy)  # H-100: every folder the backup container binds is an absolute path
        self.deploy = deploy
        self.box = update.ComposeBox(deploy, run or update.run_cmd)
        self.env = self.box.env
        self.clock: Callable[[], float] = time.monotonic  # D-455 (R1): the wait for running jobs (tests replace both)
        self.sleep: Callable[[float], None] = time.sleep

    def running_job_list(self) -> list[dict[str, str]] | None:
        """The jobs running or queued (id and type only; never a patient), or None when they cannot be listed."""
        try:
            argv = self.box._c("exec", "-T", "db", "psql", "-X", "-At", "-U", "trialbox", "-d", "trialbox_wf", "-c",
                               JOBS_LIST_SQL)  # fmt: skip
            out = self.box.run(argv, timeout=query_timeout(self.env))
        except Exception:
            return None
        return [dict(zip(("job_id", "type"), [*ln.split("|", 1), ""][:2], strict=True))
                for ln in out.splitlines() if ln.strip()]  # fmt: skip

    def wait_for_jobs(self, bound_s: float) -> tuple[int | None, float]:
        """Wait while a job runs or is queued (an unknown count counts as running), at most ``bound_s`` (D-455, R1).
        Returns the count when the wait ended (0: none left) and the seconds waited."""
        start = self.clock()
        while True:
            n = self.running_jobs()
            waited = self.clock() - start
            if n == 0 or waited >= bound_s:
                return n, round(waited, 1)
            self.sleep(min(JOB_POLL_S, bound_s - waited))

    def sweep(self) -> None:
        """What a killed run left: dump folders under deploy/ and the spool in the db container."""
        for d in self.deploy.glob(".backup-*"):
            shutil.rmtree(d, ignore_errors=True)
        with contextlib.suppress(Exception):
            self.box.run(self.box._c("exec", "-T", "db", "rm", "-rf", CONTAINER_SPOOL))

    def incremental(self, cfg: Config) -> tuple[bool, str]:
        """D-977: whether tonight's backup sends the lake to restic, and why, decided on the host before the job
        starts. Only when ``TB_BACKUP_RESTIC`` is ``auto`` and the custodians' shares cover the KEK
        (``restic_repo.shares_cover``); the host then makes ``restic.key`` under the KEK if it is not there yet
        (``tools.keys restic-key``'s own function). Anything else keeps the single encrypted backup and says why; a
        restic key the custodians could not open is never made."""
        from tools.trialbox import restic_repo as rr

        if cfg.restic == "off":
            return False, "TB_BACKUP_RESTIC=off: the single encrypted backup"
        sec = self.secrets_dir()
        why = rr.shares_cover(sec)
        if why:
            return False, why
        env: dict[str, str] = dict(os.environ)
        env.update({k: self.env[k] for k in ("TB_KEK_FILE",) if k in self.env})  # H-97: never the passphrase
        try:
            made = rr.make_key(sec, env)
        except Exception as e:  # a locked KEK, a plain key left there: named, never with a key in it
            return False, f"no restic key ({type(e).__name__}: {str(e)[-200:]}): the single encrypted backup tonight"
        return True, "restic key made under the KEK; the lake to restic" if made else "the lake to restic"

    def secrets_dir(self) -> Path:
        """The host's secrets folder: ``TB_SECRETS_DIR`` from ``deploy/.env``, else the box's secrets volume. The
        nightly checks this folder's KEK, makes ``restic.key`` in it, and the restic job opens the same one (D-978)."""
        from tools import keys as keys_cli

        return Path(self.env.get("TB_SECRETS_DIR") or keys_cli.HOST_SECRETS)

    def db_bytes(self, db: str, user: str) -> int | None:
        """``pg_database_size`` of ``db`` (D-455: what its snapshot step reads), or None when it cannot be asked."""
        return self.box.db_bytes(db, user)

    def cluster_bytes(self) -> int | None:
        """Every database of the server together (what a pgBackRest backup reads at most)."""
        try:
            sql = "SELECT sum(pg_database_size(datname))::bigint FROM pg_database"
            user = self.env.get("POSTGRES_USER") or "hapi"
            out = self.box.run(
                self.box._c("exec", "-T", "db", "psql", "-X", "-At", "-U", user, "-d", "hapi", "-c", sql),
                timeout=query_timeout(self.env),
            )
            return int(out.strip())
        except Exception:  # no answer: no size, so no limit (D-455)
            return None

    def running_jobs(self) -> int | None:
        """How many jobs the orchestrator is running now (D-455: a pause is never taken under one), or None."""
        return self.box.running_jobs()

    def snapshot(self, db: str, user: str, work: Path, timeout: float | None = None, at: str | None = None) -> None:
        """:func:`snapshot_script` in the db container, received on the host in ``work``; the spool there is removed.
        The step has ``timeout`` seconds (D-455: from the database's size; None: no limit).

        10G-1 (D-1323): nothing is staged for ``compose cp``. The db container's /tmp is a tmpfs, which ``docker cp``
        does not see (box rehearsal, CI run 44469191433: "Could not find the file /tmp/tb-backup/."), and which
        counts against the container's memory limit. So every output is streamed (``stream=True``): the dump, the
        row counts and hashes, the packs and the hospital's own reference rows go through :data:`EMIT_SH` to psql's
        stdout, which ``exec -T`` hands to ``<db>.stream`` here; :func:`split_stream` takes it apart and checks the
        byte counts the container recorded. The spool is emptied first (review B2: a stale index from a run whose
        removal failed would refuse a good backup). Only the script, the snapshot id, the exit code and the index
        (bytes, not data) are written in the spool."""
        refdata = REFDATA if db == "trialbox_wf" else None
        script = work / f"{db}.sql"
        script.write_text(snapshot_script(CONTAINER_SPOOL, db, "pg_dump", f"-U {user} -d {db}", (), refdata,
                                          stream=True))  # fmt: skip
        stream = work / f"{db}.stream"
        try:
            self.box.run(self.box._c("exec", "-T", "db", "sh", "-c",
                                     f'umask 077; rm -rf -- {CONTAINER_SPOOL}; mkdir -p {CONTAINER_SPOOL}; '
                                     f'printf "%s" "$1" > {CONTAINER_SPOOL}/emit; cat > "$2"; '
                                     f'psql -X -q -v ON_ERROR_STOP=1 -U {user} -d {db} -f "$2"',
                                     "tb-snapshot", EMIT_SH, f"{CONTAINER_SPOOL}/{db}.sql"),
                         stdin_file=script, stdout_file=stream, timeout=timeout)  # fmt: skip
            split_stream(stream, work, db)
        finally:
            stream.unlink(missing_ok=True)
            with contextlib.suppress(Exception):
                self.box.run(self.box._c("exec", "-T", "db", "rm", "-rf", CONTAINER_SPOOL))
        script.unlink(missing_ok=True)
        (work / f"{db}.sql").unlink(missing_ok=True)
        at = at or datetime.now(UTC).isoformat(timespec="milliseconds")
        _write_json(work / f"{db}.dump.json", {**snapshot_meta(db, refdata), "snapshot_at": at})  # D-455 (M3)
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
        patterns = shutil.ignore_patterns("backup.lock", ".audit-*", "*.tmp")
        licensed = self.deploy / "site" / "terminology"

        def skip(folder: str, names: list[str]) -> set[str]:
            # V-18 (D-1182): the hospital's licensed copies (deploy/site/terminology, the default TB_LICENSED_DIR)
            # never leave the box; a restore reloads them from the hospital's folder
            out = set(patterns(folder, names))
            return out | ({"terminology"} if Path(folder) == licensed.parent else set())

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

    def make_backup(
        self, cfg: Config, quiesce: str | None = None, wait: bool = True
    ) -> Callable[[list[Path]], list[Path]]:
        """The nightly step (D-455). Each database is one snapshot (``trialbox_wf``, then ``hapi``), then the backup
        container reads every volume; nothing is paused and ``point_in_time`` records the window (each snapshot's
        time, the end of the file reads). ``quiesce`` (default ``cfg.quiesce``, ``TB_BACKUP_QUIESCE``) ``pause``
        keeps D-274's pause of the services that write (all but ``db``) from the first snapshot to the end of the
        container, unpaused whatever happens, under the watchdog's maintenance flag, and never while a job runs.
        Every step's time limit comes from the bytes it reads (:func:`step_timeout`); ``limits`` records them.
        ``wait`` (the nightly; not the console's "Back up now", which a person asked for now): first wait while a job
        runs, at most ``cfg.job_wait_s`` (R1), then go on; ``beside_jobs`` records the jobs it ran beside."""
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
                    if wait:  # D-455 (R1): the backup waits for a running job, at most TB_BACKUP_JOB_WAIT_S
                        left, waited = self.wait_for_jobs(cfg.job_wait_s)
                        pit["waited_s"] = waited
                        if left != 0:
                            pit["beside_jobs"] = {"count": left, "jobs": self.running_job_list() if left else None,
                                                  "waited_s": waited, "bound_s": cfg.job_wait_s}  # fmt: skip
                    # every size first: a pause is only taken when every step under it has a limit (D-455, M4)
                    sizes = {
                        db: self.db_bytes(db, user) for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi"))
                    }
                    prev = int((_read_json(cfg.last_file).get("good_file") or {}).get("bytes") or 0) or None
                    vols = volume_bytes(self.env, prev)
                    if mode == "pause":
                        jobs = self.running_jobs()
                        unsized = [k for k, v in {**sizes, "volumes": vols}.items() if v is None]
                        if jobs != 0 or unsized:
                            pit["running_jobs"] = jobs
                            why = (
                                (
                                    "the jobs could not be counted"
                                    if jobs is None
                                    else f"{jobs} job(s) running or queued"
                                )
                                if jobs != 0
                                else f"no size for {', '.join(unsized)} (a step without a limit)"
                            )
                            pit["why"] = f"TB_BACKUP_QUIESCE=pause, but {why}: not paused, the snapshot alone (D-455)"
                        else:
                            paused = self.writers()
                            stack.enter_context(watchdog.maintenance(self.deploy, "backup", "services paused"))
                            if paused:
                                self.box.run(self.box._c("pause", *paused))
                            pit.update({"held": True, "paused": paused, "why": "TB_BACKUP_QUIESCE=pause"})
                    for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):
                        limit = cfg.timeout(sizes[db])
                        pit["limits"][db] = limit
                        at = datetime.now(UTC).isoformat(timespec="milliseconds")
                        pit["snapshot_at"][db] = at
                        self.snapshot(db, user, work, timeout=limit, at=at)
                    self.host_files(work / "host")
                    dumps = tree_bytes(work) or 0
                    limit = cfg.timeout(None if vols is None else dumps + vols)
                    pit["limits"]["container"] = limit
                    use, why = self.incremental(cfg)  # D-977: tonight's choice, made on the host
                    run.incremental = {"restic": use, "why": why}  # type: ignore[attr-defined]
                    self.box._backup_container(work, cfg.public_key, [str(t) for t in targets], keep=cfg.keep,
                                               timeout=limit, restic=use,
                                               secrets=self.secrets_dir() if use else None)  # fmt: skip
                    pit["files_done_at"] = datetime.now(UTC).isoformat(timespec="milliseconds")
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
            write_atomic(f, ln)  # H-142 (.k): never a half-written event on the orchestrator's stdin
            try:
                self.box.run(self.box._c("exec", "-T", "orchestrator", "python", "-c", code), stdin_file=f)
            except Exception:  # the orchestrator is down: keep the event for the admin, never lose it
                left.append(ln)
            finally:
                f.unlink(missing_ok=True)
        if left:  # H-142 (.k): written whole beside it, then renamed: a kill mid-write never empties the kept events
            write_atomic(pending, "".join(x + "\n" for x in left), mode_of(pending))
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


def cron_old_form(text: str) -> str:
    """H-88: why an installed ``trialbox-backup`` file is of the form before the tools brought their own environment
    (it sets ``PYTHONPATH``, which the tool no longer reads), or "" when it is the current form."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if any(ln.startswith("PYTHONPATH=") for ln in lines):
        return "it sets PYTHONPATH"
    return ""


def _route_notes(cfg: Config, has_mta: bool) -> list[str]:
    """The alert route's refusals and notes, the same for the cron file and the timer (D-274, OPS-028, D-735)."""
    notes = []
    if cfg.mailto and not has_mta:
        msg = "TB_BACKUP_MAILTO is set but this host has no mail transfer agent (sendmail): cron cannot mail"
        if cfg.production and not cfg.alert_cmd and not cfg.alert_page:
            raise ValueError(msg + "; set TB_BACKUP_ALERT_CMD, or on a box with no mail "
                             f"TB_BACKUP_ALERT_ROUTE={PAGE_ROUTE} (RUNBOOK §5)")  # fmt: skip
        notes.append("note: " + msg)
    if cfg.production and not cfg.alert_route:
        bad = "".join(f"; {x}" for x in cfg.setting_errors if "TB_BACKUP_ALERT_ROUTE" in x)
        raise ValueError("PRODUCTION needs a backup alert route: " + ROUTE_HINT + bad)
    if cfg.page_only(has_mta):
        notes.append("note: backup alerts reach the /admin health tab and the audit only; nobody is mailed: someone "
                     "must open the health tab every working day (TB_BACKUP_ALERT_ROUTE, RUNBOOK §5); "
                     + cfg.page_watch())  # fmt: skip
    if not cfg.alert_route:
        notes.append("note: no backup alert route (TB_BACKUP_ALERT_CMD, TB_BACKUP_MAILTO): alerts reach the audit "
                     "and the admin page only")  # fmt: skip
    return notes


def _write(dest: Path, text: str) -> None:
    tmp = dest.parent / f".{dest.name}.tmp"  # cron reads no file whose name has a dot
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    tmp.replace(dest)


def install_cron(cfg: Config, cron_dir: Path, root: Path, has_mta: bool) -> list[str]:
    """Write ``<cron_dir>/trialbox-backup`` (0644). In PRODUCTION an alert route is required (D-274, OPS-028):
    ``TB_BACKUP_ALERT_CMD``, or ``TB_BACKUP_MAILTO`` on a host that has a mail transfer agent; else ValueError."""
    notes = _route_notes(cfg, has_mta)
    template = (cfg.deploy / "backup" / f"{CRON_NAME}.cron").read_text(encoding="utf-8")
    cron_dir.mkdir(parents=True, exist_ok=True)
    dest = cron_dir / CRON_NAME
    _write(dest, cron_text(template, root, cfg.mailto if has_mta else ""))
    return [f"cron: {dest} (04:45 nightly backup, hourly age check)", *notes]


# H-92: where systemd is the init, the schedule is a systemd timer per line of the cron file (a box may run no cron
# daemon); the cron file only where there is no systemd. Never both: installing the timers removes the cron file.
SYSTEMD_RUN = Path("/run/systemd/system")
SYSTEMD_DIR = Path("/etc/systemd/system")
TIMERS = ("trialbox-backup-nightly.timer", "trialbox-backup-status.timer")  # one per line of the cron file
TIMER = TIMERS[0]  # the nightly backup's timer
FIRES = frozenset({"enabled", "enabled-runtime"})  # ``systemctl is-enabled`` words of a timer that will fire
CRON_DAEMONS = frozenset({"cron", "crond", "cronie", "fcron", "dcron"})
_JOB = re.compile(r"^([0-9]{1,2}) ([0-9]{1,2}|\*) \* \* \* root (.+)$")
CRON_PATH = "/usr/bin:/bin"  # cron's own PATH: the timer's service runs with the same
# D-1090: a fixed hour in 02:00-02:59 has no time on the spring-forward day of most zones: systemd skips that day
# (Persistent does not catch it, nothing was missed) where cron runs it after the jump; refused, never guessed
SKIPPED_HOURS = frozenset({2})


class ScheduleError(RuntimeError):
    """Nothing can be left with one schedule: the message is the one action."""


def systemd_init() -> bool:
    """Whether systemd is this host's init and can be asked (install.sh's test for its units)."""
    return SYSTEMD_RUN.is_dir() and shutil.which("systemctl") is not None


def cron_daemon(proc: Path = Path("/proc")) -> bool:
    """Whether a cron daemon runs on this host (a process of that name)."""
    for comm in proc.glob("[0-9]*/comm"):
        with contextlib.suppress(OSError):
            if comm.read_text(encoding="utf-8").strip() in CRON_DAEMONS:
                return True
    return False


def _ask(*args: str) -> str:
    try:
        r = subprocess.run(["systemctl", *args], capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return (r.stdout.strip().splitlines() or ["unknown"])[0]


def timer_word(unit: str) -> str | None:
    """``systemctl is-enabled``'s word for a timer, ``stopped`` for one enabled but not running; None where systemd
    is not the init."""
    if not systemd_init():
        return None
    word = _ask("is-enabled", unit)
    if word in FIRES and _ask("is-active", unit) != "active":
        return "stopped"
    return word


unit_enabled = timer_word  # backup-status and older callers


def timer_jobs(text: str) -> list[tuple[str, str, str]]:
    """(unit name, ``OnCalendar``, command) for each job line of a rendered cron file: the same command, the same
    local time. A line a timer cannot carry exactly is a ValueError, never a guess: an environment line other than
    ``SHELL=/bin/sh`` and ``MAILTO=``, a day, month or weekday field, a step, a minute or hour out of range, a fixed
    hour the spring-forward day skips (D-1090)."""
    jobs = []
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", ln):
            if ln.strip() == "SHELL=/bin/sh" or ln.startswith("MAILTO="):
                continue
            raise ValueError(f"an environment line the timer cannot carry: {ln}")
        m = _JOB.match(ln)
        sub = re.search(r"-m tools\.trialbox ([a-z][a-z-]*)", m.group(3)) if m else None
        if not m or not sub:
            raise ValueError(f"a cron line the timer cannot carry: {ln}")
        minute, hour = int(m.group(1)), None if m.group(2) == "*" else int(m.group(2))
        if minute > 59 or (hour is not None and hour > 23):
            raise ValueError(f"a minute or hour out of range: {ln}")
        if hour in SKIPPED_HOURS:
            raise ValueError(f"a fixed time in 02:00-02:59 has none on the spring-forward day: move it: {ln}")
        cal = f"*-*-* {'*' if hour is None else f'{hour:02d}'}:{minute:02d}:00"
        jobs.append((f"trialbox-{sub.group(1)}", cal, m.group(3)))
    return jobs


def _exec_start(script: str) -> str:
    if any(c in script for c in "\\'\n"):
        raise ValueError("a scheduled command with a backslash, a single quote or a newline")
    return "/bin/sh -c '" + script.replace("%", "%%").replace("$", "$$") + "'"  # systemd's own % and $


def unit_files(text: str, mailto: str = "") -> dict[str, str]:
    """The service and timer of each job of the rendered cron file. ``mailto``: what cron's MAILTO did, mail what
    the command prints (it prints only when something is wrong) through the host's sendmail."""
    if mailto and not re.fullmatch(r"[A-Za-z0-9._+@, -]+", mailto):
        raise ValueError("a MAILTO the timer cannot carry: addresses only")
    out = {}
    for name, cal, cmd in timer_jobs(text):
        script = cmd
        if mailto:
            script = (f'out=$({cmd} 2>&1); rc=$?; [ -z "$out" ] || {{ echo "To: {mailto}"; echo "Subject: TrialBox '
                      f'{name}"; echo; echo "$out"; }} | sendmail -t; exit $rc')  # fmt: skip
        head = f"# Written by trialbox backup-install from deploy/backup/{CRON_NAME}.cron (H-92); do not edit.\n"
        out[f"{name}.service"] = (f"{head}[Unit]\nDescription=TrialBox {name} (the backup schedule)\n"
                                  "After=docker.service trialbox.service\n\n[Service]\nType=oneshot\n"
                                  f"TimeoutStartSec=infinity\nEnvironment=PATH={CRON_PATH}\n"
                                  f"ExecStart={_exec_start(script)}\n")  # fmt: skip
        out[f"{name}.timer"] = (
            f"{head}[Unit]\nDescription=TrialBox {name} schedule\n\n[Timer]\n"
            f"OnCalendar={cal}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
        )
    if sorted(n for n in out if n.endswith(".timer")) != sorted(TIMERS):
        raise ValueError(f"the cron file's jobs are not the backup's timers ({', '.join(TIMERS)})")
    return out


def _systemctl(*args: str) -> None:
    subprocess.run(["systemctl", *args], check=True, capture_output=True, text=True, timeout=300)


def _units(systemd_dir: Path) -> list[Path]:
    return [systemd_dir / n for t in TIMERS for n in (t, t.replace(".timer", ".service"))]


def timers_live(systemd_dir: Path) -> bool:
    """Whether this host has the backup's timers (their unit files, or systemd answering for them)."""
    if not systemd_init():
        return False
    return any(p.exists() for p in _units(systemd_dir)) or any(timer_word(t) not in (None, "not-found")
                                                             for t in TIMERS)  # fmt: skip


def remove_timers(systemd_dir: Path) -> None:
    """Disable and stop the backup's timers, remove their units, and verify that none is left that would fire;
    else ScheduleError with the one action."""
    for args in (("disable", "--now", *TIMERS), None, ("daemon-reload",)):
        if args is None:
            for p in _units(systemd_dir):
                with contextlib.suppress(FileNotFoundError, OSError):
                    p.unlink()
            continue
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _systemctl(*args)
    left = [p.name for p in _units(systemd_dir) if p.exists()]
    words = {t: timer_word(t) for t in TIMERS}
    still = [f"{t} ({w})" for t, w in words.items() if w not in (None, "not-found", "disabled", "masked")]
    if left or still:
        raise ScheduleError(f"the backup timers could not be removed ({', '.join(left + still)}): as root, "
                            f"systemctl disable --now {' '.join(TIMERS)}, remove their units from {systemd_dir}, "
                            "then run this command again; nothing else was changed")  # fmt: skip


def install_timers(cfg: Config, systemd_dir: Path, cron_dir: Path, root: Path, has_mta: bool) -> list[str]:
    """The cron file's jobs as systemd timers (enabled and started), then the cron file removed: one schedule.
    Any failure raises; the caller then removes the timers before it writes the cron file (D-1090)."""
    template = (cfg.deploy / "backup" / f"{CRON_NAME}.cron").read_text(encoding="utf-8")
    mailto = cfg.mailto if has_mta else ""
    units = unit_files(cron_text(template, root, mailto), mailto)
    for name, text in units.items():
        _write(systemd_dir / name, text)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", *TIMERS)
    gone = cron_dir / CRON_NAME
    moved = ""
    if gone.is_file():
        gone.unlink()
        moved = f"; {gone} removed (the timer runs it now)"
    return [f"timer: {', '.join(TIMERS)} in {systemd_dir} (04:45 nightly backup, hourly age check){moved}"]


def schedule_state(cron_dir: Path, timers: Mapping[str, str | None], cron_running: bool | None) -> dict[str, str]:
    """Which schedule runs the backup: ``timer`` (systemd), ``cron`` or ``none``, with a problem (one action) and a
    warning. ``timers``: each backup timer's :func:`timer_word` (None where systemd is not the init);
    ``cron_running``: whether a cron daemon runs, None when not asked."""
    cron = cron_dir / CRON_NAME
    fix = "python3 -m tools.trialbox backup-install --deploy deploy --no-first-run as root (RUNBOOK §5)"
    words = {t: timers.get(t) for t in TIMERS}
    systemd = any(w is not None for w in words.values())
    if any(w in FIRES or w == "stopped" for w in words.values()):
        if cron.is_file():
            return {"active": "timer", "warn": "", "problem": f"both the backup timers and {cron} schedule the "
                    f"backup: {fix} removes the cron file"}  # fmt: skip
        bad = [f"{t} ({w})" for t, w in words.items() if w not in FIRES]
        if bad:
            return {"active": "timer", "warn": "", "problem": f"{', '.join(bad)} will not fire: {fix} enables and "
                    "starts every timer"}  # fmt: skip
        return {"active": "timer", "warn": "", "problem": ""}
    if not cron.is_file():
        if systemd:
            return {"active": "none", "warn": "", "problem": f"no backup timer enabled and no {cron}: {fix}"}
        if cron_dir.is_dir():
            return {"active": "none", "warn": "", "problem": f"no {cron}: python3 -m tools.trialbox backup-install "
                    "(RUNBOOK §5)"}  # fmt: skip
        return {"active": "none", "warn": "", "problem": ""}  # no host schedule here (a container, a platform)
    if cron_running is False:
        action = fix + ": it installs the timers" if systemd else "start the host's cron daemon"
        return {"active": "none", "warn": "", "problem": f"{cron} is there but no cron daemon runs and no backup "
                f"timer is enabled: nothing runs the backup; {action}"}  # fmt: skip
    warn = f"the backup runs from {cron}; on this systemd host {fix} moves it to the timers" if systemd else ""
    return {"active": "cron", "warn": warn, "problem": ""}


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


def main_install(deploy: Path, cron_dir: Path = Path("/etc/cron.d"), first: bool = True,
                 systemd_dir: Path = SYSTEMD_DIR) -> int:  # fmt: skip
    """``trialbox backup-install`` (install.sh's backup step, D-274): the schedule, WAL archiving, the first
    backup. The schedule (H-92): the systemd timers where systemd is the init and this runs as root (TB_SYSTEMD=0,
    install.sh's, keeps the cron file), else the cron file. Exit 1 only when the schedule cannot be installed (in
    PRODUCTION: no alert route)."""
    from tools.trialbox import update

    deploy = absolute(deploy)
    cfg = config(deploy, update._env_file(deploy / ".env"))
    for x in cfg.setting_errors:  # D-735 (review): a bad setting is said where the backup is installed
        print(f"backup-install: bad setting: {x}")
    root = deploy.resolve().parent
    use_timer = os.environ.get("TB_SYSTEMD", "1") != "0" and os.geteuid() == 0 and systemd_init()
    nodaemon = (f"backup-install: no cron daemon runs on this host: nothing will run {cron_dir / CRON_NAME}; start "
                "the host's cron daemon (RUNBOOK §5)")  # fmt: skip
    try:  # D-1090: never two schedules; the timers go (verified) before a cron file is written
        if use_timer:
            notes = _route_notes(cfg, has_mta())
            try:
                notes = install_timers(cfg, systemd_dir, cron_dir, root, has_mta()) + notes
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                remove_timers(systemd_dir)
                why = f"note: the timers could not be installed ({type(e).__name__}: {str(e)[-200:]}): the cron file"
                notes = [why, *install_cron(cfg, cron_dir, root, has_mta())]
                if not cron_daemon():
                    notes.append(nodaemon)
        else:
            if timers_live(systemd_dir):
                if os.geteuid() != 0:
                    raise ScheduleError(f"the backup timers are installed on this host ({', '.join(TIMERS)}): run "
                                        "this command as root; nothing was changed")  # fmt: skip
                remove_timers(systemd_dir)  # TB_SYSTEMD=0 on a host that had the timers: switch cleanly
                print("backup-install: TB_SYSTEMD=0: the backup timers removed; the cron file instead")
            notes = install_cron(cfg, cron_dir, root, has_mta())
            if not cron_daemon():
                notes.append(nodaemon)
        for n in notes:
            print(n)
    except ScheduleError as e:
        print(f"backup-install: {e}")
        return 1
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


def copy_night_length(env: Mapping[str, str], deploy: Path) -> str:
    """NEW-B-20 (D-661): copy the adapter's record of how long its nights took from the lake's volume to
    ``deploy/site/night-length.json``, where the host's doctor reads it (``tools.night_length``; it has no docker
    call and no database). Returns "" when copied, else why not (a host that cannot read the volumes, a box that
    has not run a night): the copy of an earlier run then stays as it was. Never raises: the backup goes on."""
    from tools import night_length
    from tools.trialbox import update

    root = Path(env.get("TB_DOCKER_VOLUMES") or os.environ.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes")
    src = root / f"trialbox_{update.BACKUP_VOLUMES['lake']}" / "_data" / "night_runs.json"
    dst = deploy / "site" / night_length.FILE
    tmp = dst.with_name(f"{dst.name}.tmp")
    try:
        body = src.read_bytes()
        got = json.loads(body)
        if not isinstance(got, dict) or not isinstance(got.get("nights"), list):
            raise ValueError("not a record of nights")  # a half-read or wrong-shaped file never replaces a good one
    except Exception as exc:
        return f"the night's length was not copied: {src} could not be read ({type(exc).__name__})"
    # NEW-B-26 (D-667): the orchestrator's record of when its nightly work ended goes into the same file (``work``):
    # the entries of the nights the adapter's record holds, so the copy keeps what the lake keeps and no other
    # count. A box whose scheduler does not run has none: not a failure of the copy. A part that cannot be read
    # keeps the earlier copy of that part.
    days = {n.get("snapshot") for n in got["nights"] if isinstance(n, dict) and isinstance(n.get("snapshot"), str)}
    for part, key in ((root / f"trialbox_{update.BACKUP_VOLUMES['orchestrator']}" / "_data" / "night_work.json",
                       "nights"), (dst, "work")):  # fmt: skip
        try:
            work = json.loads(part.read_bytes())[key]
            if not isinstance(work, list):
                continue
            work = [w for w in work if isinstance(w, dict) and isinstance(w.get("day"), str) and w["day"] in days]
            body = (json.dumps({"nights": got["nights"], "work": work}, indent=1) + "\n").encode()
            break
        except Exception:  # unreadable, or not writable again (nested too deep): the next part, else no ``work``
            continue
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(body)
        tmp.chmod(0o644)  # times only, and the doctor may run as the host's user, not root
        tmp.replace(dst)
    except Exception as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return f"the night's length was not copied: {dst} could not be written ({type(exc).__name__})"
    return ""


class BackupBusy(RuntimeError):
    """Another backup run holds ``deploy/site/backup.lock``."""


def run_backup(deploy: Path, ops: ComposeOps | None = None, quiesce: str | None = None, with_pgbackrest: bool = True,
               wait: bool = True) -> tuple[Config, ComposeOps, dict[str, Any]]:  # fmt: skip
    """One backup run under ``backup.lock``: the nightly's, and the console's "Back up now" (D-455: ``quiesce``
    ``off``, no pgBackRest). Raises :class:`BackupBusy` when another run holds the lock."""
    from tools.trialbox import update

    deploy = absolute(deploy)
    with _lock(deploy) as mine:
        if not mine:
            raise BackupBusy("another backup run holds deploy/site/backup.lock")
        ops = ops or ComposeOps(deploy)
        ops.sweep()
        cfg = config(deploy, update._env_file(deploy / ".env"))
        why = copy_night_length(ops.env, deploy)  # D-661: before the backup, so the backup holds this night's copy
        pgb = ops.pgbackrest if cfg.archive_on and with_pgbackrest else None
        res = nightly(cfg, ops.make_backup(cfg, quiesce, wait), ops.audit, pgb)
        res["night_length"] = why or "copied"  # for the caller's lines; not in backup-last.json (not the backup's)
        return cfg, ops, res


def main_nightly(deploy: Path) -> int:
    try:
        cfg, ops, res = run_backup(deploy)
    except BackupBusy:
        print("backup-nightly: another backup run holds deploy/site/backup.lock")
        return 1
    for e in res["errors"]:
        print(f"backup-nightly: {e}")
    if res.get("night_length") not in (None, "copied"):
        print(f"backup-nightly: {res['night_length']} (the doctor's update_window line reads the copy)")
    if res["file"]:
        print(f"backup-nightly: wrote {res['file']['name']} ({res['file']['bytes']} bytes) to "
              f"{len(res['file']['copies'])} targets")  # fmt: skip
    st = status(cfg, archiver=_try(ops.archiver) if cfg.archive_on else None)
    alert(cfg, st, ops.audit, send_cmd(cfg.alert_cmd))
    return 0 if res["ok"] else 1


def main_status(deploy: Path, as_json: bool = False, quiet: bool = False, cron_dir: Path = Path("/etc/cron.d")) -> int:
    from tools.trialbox import update

    deploy = absolute(deploy)
    cfg = config(deploy, update._env_file(deploy / ".env"))
    ops = ComposeOps(deploy)
    st = status(cfg, archiver=_try(ops.archiver) if cfg.archive_on else None)
    alert(cfg, st, ops.audit, send_cmd(cfg.alert_cmd))
    if quiet and st["level"] == "ok":
        return 0
    sched = schedule_state(cron_dir, {t: timer_word(t) for t in TIMERS}, cron_daemon())  # H-92: doctor FAILs on it
    if as_json:
        print(json.dumps({**st, "schedule": sched}, indent=1, ensure_ascii=False))
    else:
        good = st["newest_good"]
        print(f"backup {st['level'].upper()}: newest good "
              + (f"{Path(good['path']).name} ({st['age_hours']} h old)" if good else "none"))  # fmt: skip
        for p in st["problems"]:
            print(f"  - {p}")
        print(f"schedule: {sched['active']}" + (f": FAIL: {sched['problem']}" if sched["problem"] else "")
              + (f" ({sched['warn']})" if sched["warn"] else ""))  # fmt: skip
    return 0 if st["level"] == "ok" else 1


def _try(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as e:  # the db is down: that is an alert too
        return {"failing": True, "error": f"{type(e).__name__}: {str(e)[-200:]}"}
