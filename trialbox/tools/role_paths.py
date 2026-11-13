"""ROLE-PATHS (D-720): each service's real write paths, run under the role script as the service's own role.

The backup drill's role check (D-573, ``tools/backup_drill.py`` ``roles_after_restore``) opens every store with DDL
of its own. On 2026-11-13 it said "7 service roles, 70 stores opened" on a box where the opt-out worker failed at
every tick and no role could load the OMOP store: it never ran a line of a service's code. This round does, on a
throwaway cluster with the real ``deploy/docker/db-init/30-service-roles.sh``:

* **a temporary table on every store connection**: as each service role, on a connection to each store of its list
  as the service opens it (``tb_common.db`` sets the role to the store's group), ``CREATE TEMP TABLE``. The OMOP
  load, the OMOP export and the vocabulary load each make one inside their transaction;
* **the OMOP load**, as the adapter: ``omop.schema.connect`` and ``omop.load.load_batch`` with one synthetic
  patient;
* **the OMOP export as of a time**, as the lake: ``omop.export.export_rows``;
* **the opt-out tick**, as the orchestrator, on a box that has an OMOP store: ``datacore.optout_worker.tick``.

Each path is named with what it raised. A path is added here when a service gets a new way to write a store that
is not a plain statement on its own store's connection (another store asked, a temporary object, a function).
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROLES_SCRIPT = ROOT / "deploy" / "docker" / "db-init" / "30-service-roles.sh"
NAME = "roles: each service's real write paths run as its own role (D-720)"
SNAPSHOT = "2000-01-02"


def _said(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:160] if str(exc).strip() else ''}"


class _Heard(logging.Handler):
    """What a function that never raises said went wrong: the error records of its logger, with the exception."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.said: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        exc = record.exc_info[1] if record.exc_info else None
        self.said.append(_said(exc) if exc is not None else record.getMessage()[:160])


def _as(url: str, role: str) -> str:
    return url.replace("postgresql://trialbox@", f"postgresql://{role}@", 1)


def _patient(gender: str = "male") -> dict[str, list[dict[str, Any]]]:
    return {"Patient": [{"resourceType": "Patient", "id": "drill-1", "birthDate": "1960-01-01", "gender": gender}]}


def temp_tables(url: str, access: dict[str, list[str]], owned: list[str]) -> list[str]:
    """Where a service cannot make a temporary table on a store connection of its own; one line per store."""
    from tb_common.db import Database

    bad: list[str] = []
    for role, schemas in sorted(access.items()):
        for schema in sorted(schemas):
            if schema in owned:  # D-486: made by the install step; the service is a writer, tested by its own check
                continue
            try:
                with Database.connect(_as(url, role), schema) as db, db.transaction() as tx:
                    tx.execute("CREATE TEMP TABLE tb_drill_tmp (k INT) ON COMMIT DROP")
            except Exception as exc:
                bad.append(f"{role} on {schema}: {_said(exc)}")
    return bad


def omop_load(url: str) -> None:
    from omop import load, schema

    db = schema.connect(_as(url, "tb_adapter"))
    try:
        load.load_batch(db, "feed", SNAPSHOT, _patient())
    finally:
        db.close()


def omop_export(url: str) -> None:
    """An export as of a time between two loads of one record: the wind-back gives the record its before-image
    back through a temporary table, which an export of "now" or of an unchanged store never makes."""
    from omop import export, load, schema

    writer = schema.connect(_as(url, "tb_adapter"))
    try:
        # the same one patient in every batch: a batch without them would be a mass removal, which the load refuses
        load.load_batch(writer, "feed", "2000-01-03", _patient())
        between = writer.fetchval("SELECT clock_timestamp()")
        load.load_batch(writer, "feed", "2000-01-04", _patient(gender="female"))
    except Exception as exc:
        raise RuntimeError(f"its two loads did not run ({_said(exc)})") from exc
    finally:
        writer.close()
    db = schema.connect(_as(url, "tb_lake"))
    try:
        export.export_rows(db, as_of=between)
    finally:
        db.close()


def optout_tick(url: str) -> None:
    """The orchestrator's own tick, with its handles: the trial database as ``tb_orchestrator``, an audit log that
    keeps what it is given, no lake and no job store (the worker takes a box without them)."""
    from datacore import optout_worker
    from omop import schema
    from tb_common.config import site_tz

    schema.connect(url).close()  # the box has an OMOP store (dual write, or the OMOP lake source)
    events: list[str] = []
    orch = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz=site_tz(None))),  # the site's zone (TB_TZ, D-315)
        audit=SimpleNamespace(append=lambda event, **_kw: events.append(event)),
        services=SimpleNamespace(lake=None),
        db=None,
    )
    heard = _Heard()  # the tick never raises (a scheduler job): what stopped it is in its log line
    optout_worker.log.addHandler(heard)
    before = os.environ.get("TB_DB_URL")
    os.environ["TB_DB_URL"] = _as(url, "tb_orchestrator")
    try:
        out = optout_worker.tick(orch)
    finally:
        optout_worker.log.removeHandler(heard)
        if before is None:
            os.environ.pop("TB_DB_URL", None)
        else:
            os.environ["TB_DB_URL"] = before
    if out is None:
        why = "; ".join(heard.said) or "nothing logged"
        raise RuntimeError(f"the tick did not run (failed {optout_worker.status()['failed']}): {why}")
    if out.get("failed"):
        raise RuntimeError(f"the tick left stores not cleared: {sorted(out['failed'])}")


PATHS: list[tuple[str, Callable[[str], None]]] = [
    ("the OMOP load as tb_adapter", omop_load),
    ("the OMOP export as of a time as tb_lake", omop_export),
    ("the opt-out tick as tb_orchestrator", optout_tick),
]


def failures(url: str, access: dict[str, list[str]], owned: list[str]) -> list[str]:
    """Every path that does not run, with what it raised; empty when all run."""
    bad = [f"a temporary table: {line}" for line in temp_tables(url, access, owned)]
    for name, run in PATHS:
        try:
            run(url)
        except Exception as exc:
            bad.append(f"{name}: {_said(exc)}")
    return bad


def brief(bad: list[str], keep: int = 3) -> list[str]:
    """The lines for the drill's one line: every path by name; of the temporary tables the first few and a count."""
    temp = [b for b in bad if b.startswith("a temporary table: ")]
    rest = [b for b in bad if not b.startswith("a temporary table: ")]
    more = [f"a temporary table: {len(temp) - keep} more store connections the same"] if len(temp) > keep else []
    return temp[:keep] + more + rest


def check(root: Path, script: Path = ROLES_SCRIPT) -> tuple[str, bool, str]:
    """The drill's line: a throwaway cluster, the role script as the installer runs it, then every path."""
    from tools import backup_drill, pglocal
    from tools.trialbox import backup as bk

    access = backup_drill.service_access(script)
    owned = backup_drill.owned_schemas(script)
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    try:
        url = pglocal.ensure(root)
    except Exception as exc:
        return (NAME, False, f"no throwaway cluster: {_said(exc)}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(
        PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}",
        PGHOST=str((root / "run").resolve()),
        POSTGRES_USER="postgres",
        TB_WF_DB=pglocal.DB,
        TB_DB_ROLES_CMD=f"sh {shlex.quote(str(script))}",
    )
    try:
        state = bk.reapply_service_roles(env)["state"]
        if state != "applied":
            return (NAME, False, f"the role script was not applied: {state}")
        bad = failures(url, access, owned)
        stores = sum(1 for schemas in access.values() for s in schemas if s not in owned)
        if bad:
            return (NAME, False, f"{len(bad)} do not run: " + "; ".join(brief(bad)))
        return (NAME, True, f"a temporary table on {stores} store connections, and {len(PATHS)} paths: "
                            + ", ".join(name for name, _ in PATHS))  # fmt: skip
    except Exception as exc:
        return (NAME, False, _said(exc))
    finally:
        pglocal.stop(root)
        shutil.rmtree(root, ignore_errors=True)
