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
2. **The stores.** Every clear the erasure registry names (:mod:`tb_common.erasure`, T-727, D-465) is run for the
   patients opted out now, and its store is read back by the clear's verify. Today: ``candidate_pool`` (MICROBATCH's
   pool: the rows go), ``candidate_registry`` (an open candidate, ``candidate`` or ``contacted``, becomes
   ``withdrawn``; a patient who consented or enrolled keeps the trial's record, OD-8), ``omop`` (``tb_withheld``
   plus an immediate tombstone, ``omop.load.withhold``; a later load keeps them out), ``vec``
   (``VecStore.delete_patient``) and ``profile`` (``ProfileStore.erase``). A row left after a clear fails the tick.
3. **One audit event** ``optout.worker`` with counts only: who opted out is itself private (D-147).

A store that fails does not stop the others; the tick reports it, audits it and the next tick tries again (every
clear is idempotent). Lifting an opt-out restores nothing by itself: the patient comes back in the next SCREEN and
the next load (by design, D-441).

**Adding a store**: give every table it creates an entry in :mod:`tb_common.erasure` (the enumerating test fails until
it has one). For an ``erase`` entry, write ``clear(pids, env) -> dict[str, int]`` (idempotent, counts only, no pid in
the result) and ``verify(pids, env) -> {table: rows left}`` here and name them in ``erasure.CLEARS``; the worker runs
them. Until then the entry is owed (``owed_by``) and on the generated erasure-owed list.

The orchestrator runs a tick every ``TB_OPTOUT_WORKER_MINUTES`` (default 5; 0: off) in its own process
(:func:`start`), so the register's change reaches the lists within one tick even when the night schedule is on demand.
"""

from __future__ import annotations

import logging
import os
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
    #: stores that exist and could not be opened for this tick (D-683): their clear fails, the others run
    not_opened: frozenset[str] = frozenset()


def clear_pool(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if env.jobs is None:
        return {"skipped": 1}
    return {"removed": int(env.jobs.pool_remove(sorted(pids)))}


def verify_pool(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if env.jobs is None:
        return {}
    return {"orch.pool": int(env.jobs.pool_count(sorted(pids)))}


def clear_candidates(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
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


def verify_candidates(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    """What the clear promises: no open candidate of an opted-out patient (the withdrawn row itself is owed)."""
    if env.jobs is None:
        return {}
    left = sum(
        1
        for rs in sorted({str(s["ruleset"]) for s in env.jobs.candidate_summaries()})
        for r in env.jobs.candidates(rs)
        if str(r["pid"]) in pids and r["status"] in OPEN_STATUSES
    )
    return {"orch.candidates": left}


class StoreNotOpened(RuntimeError):
    """A store that exists on this box could not be opened for this tick: its clear fails (the tick names it and
    goes on), it is never reported as skipped."""


def clear_omop(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if "omop" in env.not_opened:  # D-683: the store is there and was not opened: failed, not "no store"
        raise StoreNotOpened("omop")
    if env.omop is None:
        return {"skipped": 1}
    from omop.load import withhold

    return withhold(env.omop, pids, ACTOR).as_dict()


#: the OMOP tables the withhold deletes by person (``note_nlp`` and ``fact_relationship`` go with their notes and
#: measurements, ``tb_record`` is read for live rows)
OMOP_BY_PERSON = (
    "person",
    "observation_period",
    "death",
    "visit_occurrence",
    "condition_occurrence",
    "drug_exposure",
    "procedure_occurrence",
    "measurement",
    "observation",
    "note",
    "tb_appointment",
    "tb_claim",
)


def verify_omop(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    if "omop" in env.not_opened:
        raise StoreNotOpened("omop")
    if env.omop is None or not pids:
        return {}
    db = env.omop
    persons = [
        int(r[0])
        for r in db.fetchall(
            "SELECT omop_id FROM tb_id_map WHERE id_kind = 'person' AND source_id = ANY(?)", (sorted(pids),)
        )
    ]
    out = {"omop.tb_withheld": len(pids - {str(r[0]) for r in db.fetchall("SELECT pid FROM tb_withheld")})}
    if not persons:
        return out
    for t in OMOP_BY_PERSON:
        out[f"omop.{t}"] = int(db.fetchval(f"SELECT count(*) FROM {t} WHERE person_id = ANY(?)", (persons,)))
    out["omop.tb_record"] = int(
        db.fetchval(
            "SELECT count(*) FROM tb_record WHERE status <> 'tombstoned' AND (person_id = ANY(?) OR "
            "(cdm_table = 'person' AND record_id = ANY(?))) AND coalesce(cdm_table, '') <> 'tb_consent'",
            (persons, persons),
        )
    )
    out["omop.note_nlp"] = int(
        db.fetchval(
            "SELECT count(*) FROM note_nlp WHERE note_id IN (SELECT record_id FROM tb_record WHERE cdm_table = 'note' "
            "AND person_id = ANY(?))",
            (persons,),
        )
    )
    return out


def store_has(url: str, schema: str, table: str) -> bool:
    """Whether the store ``schema`` (less ``tb_prefix``) holds ``table`` on this box (D-683). Asked of the catalog,
    which answers every role, on a connection of its own as the service's login role: never over another store's
    connection, which works as that store's group role (D-378) and is refused every question about a schema it
    may not use. "No such store" is a clear false; any failure to ask raises and is the caller's to name."""
    import psycopg
    from tb_common.db import split_url

    dsn, prefix = split_url(url)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
        row = con.execute(
            "SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r', 'p')",
            (prefix + schema, table),
        ).fetchone()
    return row is not None


def _schema_url(env: WorkerEnv, schema: str, table: str) -> str | None:
    """The trial database's URL when ``schema.table`` exists on this box (a box without the store is not given one;
    the worker never creates a store it clears)."""
    url = str(env.register.db.url)
    return url if store_has(url, schema, table) else None


def clear_vec(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    url = _schema_url(env, "vec", "note_chunk")
    if url is None:
        return {"skipped": 1}
    from vec.store import VecStore

    out = {"chunks": 0, "embeddings": 0}
    with VecStore(url) as st:
        for pid in sorted(pids):
            for k, n in st.delete_patient(pid).items():
                out[k] += n
    return out


def verify_vec(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    url = _schema_url(env, "vec", "note_chunk")
    if url is None or not pids:
        return {}
    from tb_common.db import Database

    with Database.connect(url, "vec") as db:
        return {
            "vec.note_chunk": int(db.fetchval("SELECT count(*) FROM note_chunk WHERE pid = ANY(?)", (sorted(pids),)))
        }


def clear_pending(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    """T-723 (D-489): the pid map's staging (a held night's chart numbers and identities, not yet in the map). The
    opted-out patient's staged rows are deleted; a later night stages them again if the opt-out is lifted."""
    url = _schema_url(env, "pidmap", "pending")
    if url is None:
        return {"skipped": 1}
    from tb_common.db import Database

    with Database.connect(url, "pidmap") as db:
        return {"staged": int(db.execute("DELETE FROM pending WHERE pid = ANY(?)", (sorted(pids),)))}


def verify_pending(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    url = _schema_url(env, "pidmap", "pending")
    if url is None or not pids:
        return {}
    from tb_common.db import Database

    with Database.connect(url, "pidmap") as db:
        return {"pidmap.pending": int(db.fetchval("SELECT count(*) FROM pending WHERE pid = ANY(?)", (sorted(pids),)))}


def clear_profile(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    url = _schema_url(env, "profile", "tb_patient_profile")
    if url is None:
        return {"skipped": 1}
    from patient_profile.twin import ProfileStore

    st = ProfileStore(url)
    try:
        return {"erased": sum(st.erase(pid) for pid in sorted(pids))}
    finally:
        st.close()


def verify_profile(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    url = _schema_url(env, "profile", "tb_patient_profile")
    if url is None or not pids:
        return {}
    from tb_common.db import Database

    with Database.connect(url, "profile") as db:
        n = db.fetchval("SELECT count(*) FROM tb_patient_profile WHERE pid = ANY(?)", (sorted(pids),))
    return {"profile.tb_patient_profile": int(n)}


def run_once(env: WorkerEnv) -> dict[str, Any]:
    """One tick: the registry copied into the register, then every clear of the erasure registry
    (:func:`tb_common.erasure.clears`) run for the patients opted out now and its store read back. Returns counts
    (never a pseudonym) and writes them as one ``optout.worker`` audit event. A clear that raises, or whose verify
    finds a row left, is named in ``failed``."""
    from tb_common import erasure

    at = env.now.isoformat()
    out: dict[str, Any] = {"registry": None, "stores": {}, "left": {}, "failed": []}
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
    for c in erasure.clears():
        try:
            clear, verify = c.resolve()
            out["stores"][c.name] = clear(pids, env)
            left = {t: n for t, n in verify(pids, env).items() if n}
        except Exception as exc:  # one store does not hold up the others; it is retried next tick
            log.error("opt-out worker: store %s not cleared (%s)", c.name, type(exc).__name__)
            out["failed"].append(c.name)
            continue
        if left:  # the clear ran and the store still holds an opted-out patient: never reported as erased
            log.error("opt-out worker: store %s still holds opted-out patients after its clear", c.name)
            out["left"][c.name] = left
            out["failed"].append(c.name)
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
    """The box's OMOP store when it exists (dual write or the OMOP lake source), opened as the store itself; a box
    without one is not given one. Raises when the store is there and cannot be opened."""
    url = str(reg.db.url)
    if not store_has(url, "omop", "tb_record"):
        return None
    from omop import schema

    return schema.connect(url)


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
    not_opened: frozenset[str] = frozenset()
    try:
        try:
            omop = _omop_store(reg)
        except Exception as exc:  # D-683: one store that cannot be opened does not stop the tick; it is named
            log.error("opt-out worker: the OMOP store was not opened (%s)", type(exc).__name__)
            not_opened = frozenset({"omop"})
        env = WorkerEnv(
            register=reg, audit=orch.audit, now=now, lake=orch.services.lake, jobs=orch.db, omop=omop,
            not_opened=not_opened,
        )  # fmt: skip
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
        _failed(orch, list(out["failed"]), now)  # audited by name (never who) and the health line turns red
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


__all__ = [
    "STATUS",
    "WorkerEnv",
    "clear_candidates",
    "clear_omop",
    "clear_pool",
    "clear_profile",
    "clear_vec",
    "run_once",
    "start",
    "status",
    "tick",
    "verify_candidates",
    "verify_omop",
    "verify_pool",
    "verify_profile",
    "verify_vec",
]
