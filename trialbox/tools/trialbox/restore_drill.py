"""``trialbox restore-drill`` (T-730d, D-892): the whole proof that a backup restores, typed by hospital IT on the host
with the private key in hand (D-126: the box cannot open its own backups).

    trialbox restore-drill <backup file> --key /media/usb/trialbox-backup.key

1. Free space is checked first: the unpacked backup in the work folder and the scratch databases where the database
   keeps its files; short of either, nothing starts and the need is said in GB.
2. The backup is opened with the key and every file is checked against its signed manifest (``backup.unpack``).
3. Each database of the backup is restored into a **scratch** database on the same server (``tb_drill_<id>_<name>``),
   never the live one, and its rows and content hashes are compared with the manifest, as ``trialbox restore`` does.
4. The scratch databases and the unpacked files are dropped at the end, after a failure too.
5. The result (pass or fail, the backup's date and what was compared; never the key or its path) is the box's
   key-check record (``deploy/site/backup-verified.json``, which the health check reads: red after
   ``TB_HEALTH_VERIFIED_DAYS``) and an audit event (``backup.restore_drill``). A failed drill is a backup problem in
   ``backup-status``, so it goes through the box's alert route (mail, or the health page, D-735).
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from tools.trialbox import backup_schedule as _sched

if TYPE_CHECKING:
    from tools.trialbox import backup as bk

SCRATCH_PREFIX = "tb_drill_"
UNPACK_FACTOR = 4.0  # the unpacked backup: a compressed dump and the lake are about this many times the file
SCRATCH_FACTOR = 2.0  # the scratch databases: a restored dump with its indexes, about this many times the file
EVENT = "backup.restore_drill"
GB = 1024**3


class DrillError(RuntimeError):
    pass


def _dbname(dsn: str) -> str:
    from psycopg.conninfo import conninfo_to_dict

    return str(conninfo_to_dict(dsn).get("dbname") or "")


def scratch_source(src: bk.DbSource, admin_dsn: str, name: str) -> bk.DbSource:
    """The scratch twin of ``src``: the same schemas, in database ``name`` on the server of ``admin_dsn``. Refused
    unless the name is a drill's own and is neither the live database nor the admin's (never the live one)."""
    from psycopg.conninfo import make_conninfo

    live = {_dbname(src.dsn), _dbname(admin_dsn)}
    if not name.startswith(SCRATCH_PREFIX) or name in live:
        raise DrillError(f"refused: {name!r} is not a drill's scratch database (it would be a live one)")
    return replace(src, dsn=make_conninfo(admin_dsn, dbname=name))


def _create(admin_dsn: str, name: str) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(admin_dsn, autocommit=True) as con:
        con.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop(admin_dsn: str, name: str) -> None:
    import psycopg
    from psycopg import sql

    if not name.startswith(SCRATCH_PREFIX):  # the last guard before a DROP DATABASE
        raise DrillError(f"refused to drop {name!r}: not a drill's scratch database")
    with psycopg.connect(admin_dsn, autocommit=True) as con:
        con.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def space_needed(file: Path) -> dict[str, int]:
    size = file.stat().st_size
    return {"unpack": int(size * UNPACK_FACTOR), "scratch": int(size * SCRATCH_FACTOR)}


def check_space(file: Path, work: Path, db_dir: Path, free: Callable[[Path], int]) -> None:
    """Refuse before anything starts when the work folder or the database's folder is short; say how much."""
    need = space_needed(file)
    short = []
    for what, where, n in (("the unpacked backup", work, need["unpack"]), ("the scratch databases", db_dir,
                                                                           need["scratch"])):  # fmt: skip
        have = free(where)
        if have < n:
            short.append(f"{what} needs {n / GB:.1f} GB free in {where}, {have / GB:.1f} GB is free")
    if short:
        raise DrillError("not enough free space, nothing was started: " + "; ".join(short))


def compare(src: bk.DbSource, want: Mapping[str, Any]) -> list[str]:
    """The tables whose rows or content hash differ from the manifest, as ``trialbox restore`` compares them."""
    from tools.trialbox import backup as bk

    scheme = want.get("row_hash", "md5")
    skip = [*want.get("excluded_tables", []), *want.get("excluded_data_schemas", [])]
    got = bk.row_counts(src, skip, scheme)
    diff = sorted(k for k in set(got) | set(want["rows"]) if got.get(k) != want["rows"].get(k))
    if want.get("refdata_schema"):
        site = bk.site_row_counts(src, want["refdata_schema"], scheme)
        wsite = want.get("site_rows", {})
        empty = [0, _sched.EMPTY_HASH[scheme]]
        diff += sorted(f"site:{k}" for k in set(site) | set(wsite) if site.get(k, empty) != wsite.get(k, empty))
    return diff


def finish_database(scratch: bk.DbSource, unpacked: Path, want: Mapping[str, Any]) -> list[str]:
    from tools.trialbox import backup as bk

    for table in _sched.BULK_REFDATA:
        rows = unpacked / "db" / f"{scratch.name}.site.{table}.copy"
        if want.get("refdata_schema") and rows.is_file() and rows.stat().st_size:
            bk._copy_in(scratch, f"{want['refdata_schema']}.{table}", rows)
    return compare(scratch, want)


class DrillOps(Protocol):
    def unpack(self, file: Path, key: Path, into: Path) -> dict[str, Any]: ...
    def create(self, db: str, name: str) -> None: ...
    def restore_compare(self, db: str, name: str, into: Path, want: Mapping[str, Any]) -> list[str]: ...
    def drop(self, name: str) -> None: ...


class LocalDrill:
    """The direct CLI, for an environment with the Python dependencies and PostgreSQL client installed."""

    def __init__(self, env: Mapping[str, str]) -> None:
        from tools.trialbox import backup as bk

        self.env = env
        self.sources = {s.name: s for s in bk.db_sources(env)}
        # Direct callers supply a scratch-capable connection. The installed box uses its own cluster role.
        self.admin = (self.sources.get("trialbox_wf") or next(iter(self.sources.values()))).dsn
        self.created: set[str] = set()

    def unpack(self, file: Path, key: Path, into: Path) -> dict[str, Any]:
        from tools.trialbox import backup as bk

        return bk.unpack(file, key, into, lake_from_restic=False)

    def create(self, db: str, name: str) -> None:
        if db not in self.sources:
            raise DrillError(f"the backup holds database {db} but its URL is not set on this box")
        scratch = scratch_source(self.sources[db], self.admin, name)
        self.created.add(name)  # after the live-name guard, before the server answers (review 2 of #1305, L-1)
        _create(self.admin, _dbname(scratch.dsn))

    def restore_compare(self, db: str, name: str, into: Path, want: Mapping[str, Any]) -> list[str]:
        from tools.trialbox import backup as bk

        scratch = scratch_source(self.sources[db], self.admin, name)
        bk.restore_db(scratch, into / "db" / f"{db}.dump", self.env)
        return finish_database(scratch, into, want)

    def drop(self, name: str) -> None:
        if name not in self.created:  # only a name that passed the guard in create: never a live or admin database
            raise DrillError(f"refused to drop {name!r}: this drill did not create it")
        _drop(self.admin, name)


def drill(
    file: Path,
    key: Path,
    env: Mapping[str, str],
    *,
    work: Path | None = None,
    db_dir: Path | None = None,
    free: Callable[[Path], int] | None = None,
    now: datetime | None = None,
    name: Callable[[str], str] | None = None,
    ops: DrillOps | None = None,
) -> dict[str, Any]:
    """Run the drill on ``file`` with ``key``; return the result (``ok`` true or false). Raises :class:`DrillError`
    only when nothing was started (space, settings); every later failure is a result with ``ok`` false."""
    now = now or datetime.now(UTC)
    work = work or Path(tempfile.gettempdir())
    db_dir = db_dir or work
    check_space(file, work, db_dir, free or (lambda p: shutil.disk_usage(p).free))
    ops = ops or LocalDrill(env)
    drill_id = secrets.token_hex(4)
    scratch_name = name or (lambda db: f"{SCRATCH_PREFIX}{drill_id}_{db}")
    made: list[str] = []
    res: dict[str, Any] = {"ok": False, "at": now.isoformat(timespec="seconds"), "file": file.name,
                           "drill": drill_id, "databases": {}}  # fmt: skip
    unpacked = Path(tempfile.mkdtemp(prefix="tb-drill-", dir=work))
    try:
        manifest = ops.unpack(file, key, unpacked)  # D-968: the drill reads the sealed part
        res.update(created_at=manifest["created_at"], site=manifest.get("site", ""), sha256=manifest["_sha256"],
                   files=len(manifest["files"]))  # fmt: skip
        for db, want in manifest["databases"].items():
            scratch_db = scratch_name(db)
            made.append(scratch_db)  # before the server answers: a lost acknowledgement is still dropped
            try:
                ops.create(db, scratch_db)
            except DrillError:  # refused before the server was asked (a live or invalid name): nothing to drop
                made.remove(scratch_db)
                raise
            diff = ops.restore_compare(db, scratch_db, unpacked, want)
            res["databases"][db] = {"tables": len(want["rows"]), "rows": sum(r[0] for r in want["rows"].values()),
                                    "differ": diff[:10], "differ_count": len(diff)}  # fmt: skip
        bad = {db: r["differ_count"] for db, r in res["databases"].items() if r["differ_count"]}
        res["ok"] = not bad
        if bad:
            res["error"] = "restored rows differ from the backup's manifest: " + ", ".join(
                f"{db} in {n} table(s)" for db, n in sorted(bad.items())
            )
    except Exception as e:  # a database that refused (psycopg), a damaged dump: a failed drill, said
        res["error"] = f"{type(e).__name__}: {str(e)[-400:]}"
    finally:
        dropped = []
        for n in made:
            try:
                ops.drop(n)
                dropped.append(n)
            except Exception as e:  # said in the result: a scratch database left behind is named, never hidden
                res["ok"] = False
                res.setdefault(
                    "error", "scratch cleanup failed / 暫存資料庫清理失敗 / 一時データベースの削除に失敗しました"
                )
                res.setdefault("left_behind", []).append(f"{n} ({type(e).__name__})")
        shutil.rmtree(unpacked, ignore_errors=True)
        res["scratch_dropped"] = dropped
        res["unpacked_removed"] = not unpacked.exists()
        if not res["unpacked_removed"]:
            res["ok"] = False
            res.setdefault("error", "could not remove the unpacked backup")
    return res


def audit_detail(res: Mapping[str, Any]) -> dict[str, Any]:
    return {k: res.get(k) for k in ("ok", "at", "file", "created_at", "files", "databases", "error", "drill", "sha256")}


def record(deploy: Path, res: Mapping[str, Any], env: Mapping[str, str], dirs: Mapping[str, Path]) -> str:
    """The drill's result as the box's key-check record and an audit event; never the key or its path."""
    from tb_common import metrics

    from tools.trialbox import backup as bk

    metrics.record_drill(deploy, res)
    detail = audit_detail(res)
    actor = {**env, "TB_RESTORE_ACTOR": env.get("TB_RESTORE_ACTOR") or "trialbox restore-drill"}
    return bk._audit(dirs, actor, EVENT, str(res.get("sha256") or ""), detail)
