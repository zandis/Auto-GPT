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

import json
import logging
import os
import re
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
    #: D-685: the box's other OMOP stores, open, by schema name (``omop_<hash>``: a lake that is not the box's own)
    omop_more: dict[str, Any] = field(default_factory=dict)
    #: OMOP stores that opened and whose clear raised in this tick, by name (written by ``clear_omop``)
    not_cleared: list[str] = field(default_factory=list)


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


#: D-685: the names an OMOP store has (``omop.schema.schema_for``): the box's own, and one per other lake
OMOP_STORE = re.compile(r"omop(_[0-9a-f]{10})?")


def _omop_open(env: WorkerEnv) -> list[tuple[str, Any]]:
    """Every OMOP store open for this tick, the box's own first."""
    return ([("omop", env.omop)] if env.omop is not None else []) + sorted(env.omop_more.items())


def _omop_not_opened(env: WorkerEnv) -> list[str]:
    return sorted(n for n in env.not_opened if OMOP_STORE.fullmatch(n.split("@", 1)[0]))


def clear_omop(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    """D-685: the patient is withheld in every OMOP store the box holds. Every store that opened is tried, each on
    its own: one whose clear raises is named (``not_cleared``) and does not keep the later ones from being
    cleared. Then a store that failed, or one that is there and was not opened (D-683), fails the clear: failed,
    never "no store". The counts are sums over the stores (``withheld`` counts a patient once per store);
    ``stores`` says how many."""
    from omop import load

    stores = _omop_open(env)
    total: dict[str, int] = {}
    for name, db in stores:
        try:
            counts = load.withhold(db, pids, ACTOR).as_dict()
        except Exception as exc:
            log.error("opt-out worker: the OMOP store %s was not cleared (%s)", name, type(exc).__name__)
            env.not_cleared.append(name)
            continue
        for k, n in counts.items():
            total[k] = total.get(k, 0) + int(n)
    if env.not_cleared or _omop_not_opened(env):
        raise StoreNotOpened("omop")
    if not stores:
        return {"skipped": 1}
    if len(stores) > 1:
        total["stores"] = len(stores)
    return total


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
    """Rows left of an opted-out patient, per OMOP store (``<schema>.<table>``, D-685)."""
    if _omop_not_opened(env):
        raise StoreNotOpened("omop")
    if not pids:
        return {}
    out: dict[str, int] = {}
    for name, db in _omop_open(env):
        out.update(_verify_one_omop(name, db, pids))
    return out


def _verify_one_omop(name: str, db: Any, pids: frozenset[str]) -> dict[str, int]:
    persons = [
        int(r[0])
        for r in db.fetchall(
            "SELECT omop_id FROM tb_id_map WHERE id_kind = 'person' AND source_id = ANY(?)", (sorted(pids),)
        )
    ]
    out = {f"{name}.tb_withheld": len(pids - {str(r[0]) for r in db.fetchall("SELECT pid FROM tb_withheld")})}
    if not persons:
        return out
    for t in OMOP_BY_PERSON:
        out[f"{name}.{t}"] = int(db.fetchval(f"SELECT count(*) FROM {t} WHERE person_id = ANY(?)", (persons,)))
    out[f"{name}.tb_record"] = int(
        db.fetchval(
            "SELECT count(*) FROM tb_record WHERE status <> 'tombstoned' AND (person_id = ANY(?) OR "
            "(cdm_table = 'person' AND record_id = ANY(?))) AND coalesce(cdm_table, '') <> 'tb_consent'",
            (persons, persons),
        )
    )
    out[f"{name}.note_nlp"] = int(
        db.fetchval(
            "SELECT count(*) FROM note_nlp WHERE note_id IN (SELECT record_id FROM tb_record WHERE cdm_table = 'note' "
            "AND person_id = ANY(?))",
            (persons,),
        )
    )
    return out


def _catalog(url: str) -> tuple[Any, str]:
    """A connection for questions to the catalog, and the run's ``tb_prefix`` (D-683): the service's login role,
    no store's group role. The catalog answers every role."""
    import psycopg
    from tb_common.db import split_url

    dsn, prefix = split_url(url)
    return psycopg.connect(dsn, autocommit=True, connect_timeout=10), prefix


def store_has(url: str, schema: str, table: str) -> bool:
    """Whether the store ``schema`` (less ``tb_prefix``) holds ``table`` on this box (D-683). Asked of the catalog,
    which answers every role, on a connection of its own as the service's login role: never over another store's
    connection, which works as that store's group role (D-378) and is refused every question about a schema it
    may not use. "No such store" is a clear false; any failure to ask raises and is the caller's to name."""
    con, prefix = _catalog(url)
    with con:
        row = con.execute(
            "SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",  # any relation of the name: a view is not "no store"
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


# T-206b part 1 (D-798): the owed tables keyed by the pseudonym, each a plain delete of the patient's rows, in an
# order that deletes a referencing row before the row it references. The screening log's tables (marks, screening
# numbers, candidate events, REDCap records) are not here: LIFE-005 is frozen and OD-8 keeps a consented subject's.
# The adversarial review of D-798 kept four out: site.weekly_seen (the kept screening-log row's first-listed day),
# orch.submissions (NHI's send-once guard), team.candidate_views (the reveal cap's ledger) and tuned.tuned_patients (a
# reviewed week's sample would be drawn again); they stay on the owed list with why.
#: per store, per table: the count and the delete of the patients' rows (written out: no SQL is put together)
OWED_TABLES: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("site", (
        ("contact_outcomes", "SELECT count(*) FROM contact_outcomes WHERE pid = ANY(?)",
         "DELETE FROM contact_outcomes WHERE pid = ANY(?)"),
        ("excluded_review", "SELECT count(*) FROM excluded_review WHERE pid = ANY(?)",
         "DELETE FROM excluded_review WHERE pid = ANY(?)"),
    )),
    ("team", (
        ("approach_overrides", "SELECT count(*) FROM approach_overrides WHERE pid = ANY(?)",
         "DELETE FROM approach_overrides WHERE pid = ANY(?)"),
        ("referral_events", "SELECT count(*) FROM referral_events WHERE pid = ANY(?)",
         "DELETE FROM referral_events WHERE pid = ANY(?)"),
        ("referrals", "SELECT count(*) FROM referrals WHERE pid = ANY(?)", "DELETE FROM referrals WHERE pid = ANY(?)"),
    )),
    ("orch", (
        ("feedback", "SELECT count(*) FROM feedback WHERE pid = ANY(?)", "DELETE FROM feedback WHERE pid = ANY(?)"),
    )),
)  # fmt: skip


def _open(url: str, schema: str) -> Any:
    """The store's connection, each named here (the schemas the code opens are enumerated, D-378)."""
    from tb_common.db import Database

    if schema == "site":
        return Database.connect(url, "site")
    if schema == "team":
        return Database.connect(url, "team")
    if schema == "orch":
        return Database.connect(url, "orch")
    if schema == "derived":
        return Database.connect(url, "derived")
    raise ValueError(f"no owed table in store {schema!r}")


#: the derived store: the input links and conflicts of a score row go before the row (their foreign keys)
DERIVED = "derived"


def _derived(db: Any, pids: list[str], delete: bool) -> dict[str, int]:
    """The derived store's rows of ``pids``: counted, or deleted (counts). ``batch_run.failed_pids`` (a JSON list)
    loses the pseudonyms; the batch itself stays (it holds no other patient data)."""
    out: dict[str, int] = {}
    if delete:
        # a conflict carried from one of the patient's (always the patient's own): unlink before the delete
        db.execute("UPDATE conflict SET carried_from = NULL WHERE carried_from IN (SELECT id FROM conflict WHERE"
                   " pid = ANY(?)) AND NOT (pid = ANY(?))", (pids, pids))  # fmt: skip
        out["derived.input_link"] = db.execute(
            "DELETE FROM input_link WHERE row_id IN (SELECT id FROM score_row WHERE pid = ANY(?))", (pids,)
        )
        out["derived.conflict"] = db.execute("DELETE FROM conflict WHERE pid = ANY(?)", (pids,))
        out["derived.score_row"] = db.execute("DELETE FROM score_row WHERE pid = ANY(?)", (pids,))
    else:
        out["derived.input_link"] = int(db.fetchval(
            "SELECT count(*) FROM input_link WHERE row_id IN (SELECT id FROM score_row WHERE pid = ANY(?))", (pids,)
        ))  # fmt: skip
        out["derived.conflict"] = int(db.fetchval("SELECT count(*) FROM conflict WHERE pid = ANY(?)", (pids,)))
        out["derived.score_row"] = int(db.fetchval("SELECT count(*) FROM score_row WHERE pid = ANY(?)", (pids,)))
    gone = set(pids)
    n = 0
    for bid, raw in db.fetchall("SELECT id, failed_pids FROM batch_run WHERE failed_pids IS NOT NULL"):
        try:
            listed = [str(x) for x in json.loads(raw)]
        except (TypeError, ValueError):
            continue
        if gone & set(listed):
            n += 1
            if delete:
                left = [x for x in listed if x not in gone]
                db.execute("UPDATE batch_run SET failed_pids = ?, failed = GREATEST(COALESCE(failed, 0) - ?, 0)"
                           " WHERE id = ?", (json.dumps(left), len(listed) - len(left), bid))  # fmt: skip
    out["derived.batch_run"] = n
    return out


def _owed_tables(pids: frozenset[str], env: WorkerEnv, delete: bool) -> dict[str, int]:
    url = str(env.register.db.url)
    want = sorted(pids)
    out: dict[str, int] = {}
    for schema, tables in OWED_TABLES:
        here = [x for x in tables if store_has(url, schema, x[0])]
        if not here or not want:
            out.update({f"{schema}.{t}": 0 for t, _c, _d in here})
            continue
        with _open(url, schema) as db, db.transaction() as tx:  # one schema's deletes: all or none
            for t, count, drop in here:
                if delete:
                    out[f"{schema}.{t}"] = int(tx.execute(drop, (want,)) or 0)
                else:
                    out[f"{schema}.{t}"] = int(tx.fetchval(count, (want,)))
    if store_has(url, DERIVED, "score_row") and want:
        with _open(url, DERIVED) as db:
            if delete:
                with db.transaction() as tx:
                    out.update({k: int(v or 0) for k, v in _derived(tx, want, True).items()})
            else:
                out.update(_derived(db, want, False))
    return out


def clear_tables(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    """T-206b part 1 (D-798): the opted-out patients' rows of the owed tables keyed by the pseudonym go (counts by
    table, never who). A store this box does not have is left out; the worker never creates one."""
    return _owed_tables(pids, env, delete=True)


def verify_tables(pids: frozenset[str], env: WorkerEnv) -> dict[str, int]:
    """The rows of ``pids`` still in each owed table (and batches still naming one)."""
    return _owed_tables(pids, env, delete=False)


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
            if not snap:  # D-684: a lake with no snapshot yet has no registry to read: said, never passed over
                out["registry_not_read"] = "no snapshot"
            elif state is None:  # the lake's clear answer: this snapshot has no consent table
                out["registry_not_read"] = "no consent table"
            if state is not None:
                added, lifted = sync_registry(env.register, state, at)
                out["registry"] = {"added": added, "lifted": lifted}
        except Exception as exc:  # the register still applies; the next tick tries the registry again
            log.error("opt-out worker: the registry was not read (%s)", type(exc).__name__)
            out["failed"].append("registry")
    else:
        out["registry_not_read"] = "no lake"
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
    if env.not_opened:  # which stores: schema names, never a patient's
        out["not_opened"] = sorted(env.not_opened)
    if env.not_cleared:
        out["not_cleared"] = sorted(env.not_cleared)
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
    # the store's own database when the box names one (TB_OMOP_DB_URL, as the load reads it), else the register's
    url = os.environ.get("TB_OMOP_DB_URL") or str(reg.db.url)
    if not store_has(url, "omop", "tb_record"):
        return None
    from omop import schema

    return schema.connect(url)


def omop_store_names(url: str) -> list[str]:
    """D-685: every OMOP store the database holds, by schema name less ``tb_prefix``: a schema named as
    :data:`OMOP_STORE` that holds ``tb_record``. Asked of the catalog on a connection of its own (D-683)."""
    con, prefix = _catalog(url)
    with con:
        rows = con.execute(
            "SELECT n.nspname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'tb_record' AND left(n.nspname, %s) = %s",
            (len(prefix), prefix),
        ).fetchall()
    names = {str(r[0])[len(prefix) :] for r in rows}
    return sorted(n for n in names if OMOP_STORE.fullmatch(n))


def _omop_stores(reg: OptOutRegister) -> tuple[Any | None, dict[str, Any], frozenset[str]]:
    """The box's OMOP store, its other OMOP stores (open, by name) and the names of those that are there and
    could not be opened. Never raises: a store that fails is named, the others are still given."""
    from omop import schema

    not_opened: set[str] = set()
    box = None
    try:
        box = _omop_store(reg)
    except Exception as exc:  # D-683: one store that cannot be opened does not stop the tick; it is named
        log.error("opt-out worker: the OMOP store was not opened (%s)", type(exc).__name__)
        not_opened.add("omop")
    # the database the load writes to (TB_OMOP_DB_URL when the box names one) and the register's own: a store in
    # either holds the patient (the review: only the first was listed)
    first = os.environ.get("TB_OMOP_DB_URL") or str(reg.db.url)
    urls = [first] + ([str(reg.db.url)] if str(reg.db.url) != first else [])
    more: dict[str, Any] = {}
    for i, url in enumerate(urls):
        try:
            names = [n for n in omop_store_names(url) if i or n != "omop"]  # the first one's `omop` is the box's
        except Exception as exc:  # the catalog did not answer: no store can be called absent
            log.error("opt-out worker: the OMOP stores were not listed (%s)", type(exc).__name__)
            not_opened.add("omop")
            continue
        for name in names:
            key = name if not i and name not in more else f"{name}@register"
            try:
                if not store_has(url, name, "tb_record"):
                    continue  # gone since it was listed: opening it would make it (the worker makes no store)
                more[key] = schema.connect(url, name)
            except Exception as exc:
                log.error("opt-out worker: the OMOP store %s was not opened (%s)", key, type(exc).__name__)
                not_opened.add(key)
    return box, more, frozenset(not_opened)


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
    omop: Any | None = None
    more: dict[str, Any] = {}
    try:
        omop, more, not_opened = _omop_stores(reg)
        env = WorkerEnv(
            register=reg, audit=orch.audit, now=now, lake=orch.services.lake, jobs=orch.db, omop=omop,
            not_opened=not_opened, omop_more=more,
        )  # fmt: skip
        out = run_once(env)
    except Exception as exc:
        log.exception("opt-out worker tick failed: %s", type(exc).__name__)
        _failed(orch, ["tick"], now)
        return None
    finally:
        for db in (omop, *more.values()):
            if db is not None:
                db.close()
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
