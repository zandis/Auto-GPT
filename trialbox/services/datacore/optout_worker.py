"""The opt-out worker, v1 (T-206a, D-441): one tick takes every opted-out patient out of the stores it knows.

The register (``tb_common.optout``, schema ``optout``) is the one list of who said no: the research office and the
steward type into it, and the worker copies the hospital registry's refusals into it (the lake's ``consent`` table,
FHIR Consent ``rejected``; source ``emr``). Every screening path reads that register (D-147, D-273, D-441), so after
an opt-out and one tick no screening path lists the patient, whatever the path's own consent reading.

One tick (:func:`run_once`):

1. **The registry.** The lake's consent table as of today (the latest statement per patient decides, the rule of
   COHORT's ``n_contactable``) is copied into the register: a refusal the register lacks is added, and an opt-out the
   registry itself added is lifted when the registry no longer refuses. An opt-out the office typed is never lifted
   by the feed.
2. **The stores.** Each store in :data:`STORES` is cleared for the patients opted out now. v1 has three:
   ``candidate_pool`` (MICROBATCH's pool: the rows go), ``candidate_registry`` (an open candidate, ``candidate`` or
   ``contacted``, becomes ``withdrawn``; a patient who consented or enrolled keeps the trial's record, OD-8) and
   ``omop`` (``tb_withheld`` plus an immediate tombstone, ``omop.load.withhold``; a later load keeps them out).
3. **One audit event** ``optout.worker`` with counts only: who opted out is itself private (D-147).

A store that fails does not stop the others; the tick reports it, audits it and the next tick tries again (every
clear is idempotent). Lifting an opt-out restores nothing by itself: the patient comes back in the next SCREEN and
the next load (by design, D-441).

**Adding a store** (T-206b: profiles ``tb_patient_profile``, vectors ``services/vec``, chunks, job outputs): write
``clear(pids, env) -> dict[str, int]`` (idempotent, counts only, no pid in the result) and call
:func:`register_store` from the store's own module, or add it to :data:`BUILTIN` here. Nothing else changes.

The orchestrator runs a tick every ``TB_OPTOUT_WORKER_MINUTES`` (default 5; 0: off) in its own process
(:func:`start`), so the register's change reaches the lists within one tick even when the night schedule is on demand.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tb_common.optout import OptOutRegister, registry_state, sync_registry

log = logging.getLogger("datacore.optout_worker")

ACTOR = "optout-worker"
#: the candidate registry statuses an opt-out withdraws (before consent); consented and enrolled stay (OD-8, GCP)
OPEN_STATUSES = ("candidate", "contacted")
WITHDRAW_REASON = "opted out (research-use register)"
MINUTES_ENV = "TB_OPTOUT_WORKER_MINUTES"


@dataclass
class WorkerEnv:
    """What a tick reads and writes. ``lake``: ``query(sql, params, snapshot)`` and ``snapshot()``; ``jobs``: the
    orchestrator's job store (pool and candidate registry); ``omop``: an open OMOP store, or None (no store on this
    box). ``extra``: handles a later store needs (T-206b), by name."""

    register: OptOutRegister
    audit: Any
    now: datetime
    lake: Any | None = None
    jobs: Any | None = None
    omop: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Store:
    """One store the worker clears for the opted-out patients. ``clear`` is idempotent and returns counts only."""

    name: str
    clear: Callable[[frozenset[str], WorkerEnv], dict[str, int]]
    note: str = ""


def _clear_pool(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if env.jobs is None:
        return {"skipped": 1}
    return {"removed": int(env.jobs.pool_remove(sorted(pids)))}


def _clear_candidates(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if env.jobs is None:
        return {"skipped": 1}
    at = env.now.isoformat(timespec="seconds")
    withdrawn = kept = 0
    for rs in sorted({str(s["ruleset"]) for s in env.jobs.candidate_summaries()}):
        for row in env.jobs.candidates(rs):
            if str(row["pid"]) not in pids:
                continue
            if row["status"] in OPEN_STATUSES:
                env.jobs.candidate_set(rs, str(row["pid"]), "withdrawn", WITHDRAW_REASON, ACTOR, at, "optout", None)
                withdrawn += 1
            elif row["status"] in ("consented", "enrolled"):
                kept += 1  # the trial's own record stays (OD-8); the steward sees the count
    return {"withdrawn": withdrawn, "kept_consented_or_enrolled": kept}


def _clear_omop(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if env.omop is None:
        return {"skipped": 1}
    from omop.load import withhold

    return withhold(env.omop, pids, ACTOR).as_dict()


BUILTIN: tuple[Store, ...] = (
    Store("candidate_pool", _clear_pool, "MICROBATCH's candidate pool (orchestrator)"),
    Store("candidate_registry", _clear_candidates, "open candidates withdrawn; consented and enrolled kept (OD-8)"),
    Store("omop", _clear_omop, "tb_withheld and an immediate tombstone; later loads keep the patient out"),
)
#: the stores a tick clears, by name; T-206b adds profiles and vectors with :func:`register_store`
STORES: dict[str, Store] = {s.name: s for s in BUILTIN}


def register_store(store: Store) -> None:
    """Add (or replace, by name) a store every later tick clears."""
    STORES[store.name] = store


def run_once(env: WorkerEnv) -> dict[str, Any]:
    """One tick: the registry copied into the register, then every store cleared for the patients opted out now.
    Returns counts (never a pseudonym) and writes them as one ``optout.worker`` audit event."""
    at = env.now.isoformat()
    out: dict[str, Any] = {"registry": None, "stores": {}, "failed": []}
    if env.lake is not None:
        try:
            snap = env.lake.snapshot()
            state = registry_state(env.lake, snap, env.now.date().isoformat()) if snap else None
            if state is not None:
                added, lifted = sync_registry(env.register, state, at)
                out["registry"] = {"added": added, "lifted": lifted}
        except Exception as exc:  # the register still applies; the next tick tries the registry again
            log.error("opt-out worker: the registry was not read (%s)", type(exc).__name__)
            out["failed"].append("registry")
    pids = frozenset(env.register.effective())  # merged charts: the surviving pid too (review MED-4)
    out["opted_out"] = len(pids)
    for name, store in sorted(STORES.items()):
        try:
            out["stores"][name] = store.clear(pids, env)
        except Exception as exc:  # one store does not hold up the others; it is retried next tick
            log.error("opt-out worker: store %s not cleared (%s)", name, type(exc).__name__)
            out["failed"].append(name)
    env.audit.append("optout.worker", actor=ACTOR, detail=out)
    return out


# ------------------------------------------------------------------------------------------------ the orchestrator
def minutes() -> int:
    raw = os.environ.get(MINUTES_ENV, "").strip()
    try:
        return max(0, int(raw)) if raw else 5
    except ValueError:
        log.error("%s=%r is not a number of minutes; the worker runs every 5", MINUTES_ENV, raw)
        return 5


def _omop_store(reg: OptOutRegister) -> Any | None:
    """The box's OMOP store when it exists (dual write or the OMOP lake source); a box without one is not given one."""
    from tb_common.db import split_url

    prefix = split_url(reg.db.url)[1]
    if reg.db.fetchval("SELECT to_regclass(?)", (f'"{prefix}omop".tb_record',)) is None:
        return None
    from omop import schema

    return schema.connect(reg.db.url)


#: what the orchestrator's ``/models`` reports for the health line (``tb_common.metrics.check_optout``)
STATUS: dict[str, Any] = {"every": 0, "started": None, "ok_at": None, "failed": []}


def status() -> dict[str, Any]:
    return {**STATUS, "failed": list(STATUS["failed"])}


def _failed(orch: Any, what: list[str], now: datetime) -> None:
    STATUS["failed"] = what
    try:
        orch.audit.append("optout.worker_failed", actor=ACTOR, detail={"failed": what})
    except Exception as exc:  # the log line stays; the health line shows the failure
        log.error("opt-out worker failure not audited: %s", type(exc).__name__)


def tick(orch: Any) -> dict[str, Any] | None:
    """One tick with the orchestrator's own handles. Never raises (a scheduler job): a tick that fails or leaves a
    store not cleared is audited (``optout.worker_failed``) and turns the health line red (:data:`STATUS`)."""
    now = datetime.now(ZoneInfo(orch.cfg.env.tz))
    try:
        reg = OptOutRegister()
    except Exception as exc:
        log.error("opt-out worker: no trial database (%s)", type(exc).__name__)
        _failed(orch, ["register"], now)
        return None
    omop = None
    try:
        omop = _omop_store(reg)
        env = WorkerEnv(register=reg, audit=orch.audit, now=now, lake=orch.services.lake, jobs=orch.db, omop=omop)
        out = run_once(env)
    except Exception as exc:
        log.exception("opt-out worker tick failed: %s", type(exc).__name__)
        _failed(orch, ["tick"], now)
        return None
    finally:
        if omop is not None:
            omop.close()
        reg.close()
    if out["failed"]:
        STATUS["failed"] = list(out["failed"])  # run_once's own audit event names them
    else:
        STATUS["failed"], STATUS["ok_at"] = [], now.isoformat(timespec="seconds")
    return out


def start(orch: Any, production: bool = False) -> Any | None:
    """The worker's own interval job in the orchestrator (not the night schedule, which DEV runs on demand). The
    first tick runs at once. PRODUCTION refuses ``TB_OPTOUT_WORKER_MINUTES=0``: an opt-out must reach the stores."""
    every = minutes()
    STATUS.update(every=every, started=datetime.now(ZoneInfo(orch.cfg.env.tz)).isoformat(timespec="seconds"))
    if every == 0:
        if production:
            raise RuntimeError(f"{MINUTES_ENV}=0 is refused in PRODUCTION: the opt-out worker must run (D-441)")
        log.info("opt-out worker off (%s=0)", MINUTES_ENV)
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone=orch.cfg.env.tz)
    sched.add_job(
        lambda: tick(orch),
        "interval",
        minutes=every,
        id="optout-worker",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(ZoneInfo(orch.cfg.env.tz)),  # the first tick at start, not one interval later
    )
    sched.start()
    return sched


__all__ = ["BUILTIN", "STATUS", "STORES", "Store", "WorkerEnv", "register_store", "run_once", "start", "status", "tick"]
