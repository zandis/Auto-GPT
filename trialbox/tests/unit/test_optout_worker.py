"""The opt-out worker v1 (T-206a, D-441). Synthetic pseudonyms only.

* The hospital registry (the lake's ``consent`` table) reaches the register: the latest statement decides, as for
  COHORT's ``n_contactable``; an opt-out the office typed is never lifted by the feed.
* One tick clears every store it knows: the candidate pool, open candidates (withdrawn; consented and enrolled
  kept, OD-8), OMOP (tombstoned with the reason ``opted out``, kept out of later loads, back only after a lift and a
  new load). A failing store does not hold up the others; the stores are the erasure registry's clears (T-727).
* After an opt-out (typed, or the registry's refusal) and one tick, no screening path lists the patient: SCREEN and
  MICROBATCH (``drop_opted_out``), NAV, CASE.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from tb_common.optout import REGISTRY_ACTOR, OptOutRegister, RegistryState, registry_rule, registry_state, sync_registry

A, B, C = "a1b2c3d4e5f60001", "a1b2c3d4e5f60002", "a1b2c3d4e5f60003"
T0 = "2026-11-01T09:00:00+00:00"
T1 = "2026-11-02T09:00:00+00:00"
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


class Lake:
    """An in-process lake with one ``consent`` table (DuckDB, as the lake runs it)."""

    def __init__(self, rows: list[tuple[str, str | None, bool | None, str | None]] | None) -> None:
        self.con = duckdb.connect()
        if rows is not None:
            self.con.execute("CREATE TABLE consent (consid VARCHAR, pid VARCHAR, status VARCHAR, contact_ok BOOLEAN, "
                             "date DATE)")  # fmt: skip
            for i, (pid, st, ok, d) in enumerate(rows):
                self.con.execute("INSERT INTO consent VALUES (?, ?, ?, ?, ?)", [f"c{i}", pid, st, ok, d])

    def snapshot(self) -> str:
        return "2026-11-02"

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        return self.con.execute(sql, params or []).to_arrow_table()


class Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))


class Jobs:
    """The two parts of the orchestrator's job store the worker uses: the pool and the candidate registry."""

    def __init__(self) -> None:
        self.pool = {("GZQO", A), ("GZQO", B), ("RA", A)}
        self.cands = {("GZQO", A): "contacted", ("GZQO", B): "candidate", ("RA", A): "enrolled"}
        self.sets: list[tuple[str, str, str, str]] = []

    def pool_remove(self, pids: list[str]) -> int:
        gone = {k for k in self.pool if k[1] in pids}
        self.pool -= gone
        return len(gone)

    def pool_count(self, pids: list[str]) -> int:
        return sum(1 for k in self.pool if k[1] in pids)

    def candidate_summaries(self) -> list[dict[str, Any]]:
        return [{"ruleset": rs} for rs, _ in self.cands]

    def candidates(self, rs: str) -> list[dict[str, Any]]:
        return [{"pid": p, "status": st} for (r, p), st in self.cands.items() if r == rs]

    def candidate_set(self, rs: str, pid: str, status: str, reason: str | None, by: str, *_: Any) -> None:
        self.cands[(rs, pid)] = status
        self.sets.append((rs, pid, status, by))


# ------------------------------------------------------------------------------------------------ the registry
def test_the_latest_registry_statement_decides() -> None:
    st = registry_rule([(A, "active", True), (A, "rejected", None), (B, "rejected", None), (B, "active", True),
                        (C, "active", False)])  # fmt: skip
    assert st == RegistryState(frozenset({A}), frozenset({C}), frozenset({B, C}))


def test_registry_state_reads_the_lake_with_the_cohort_rule() -> None:
    lake = Lake(
        [
            (A, "active", True, "2026-10-01"),
            (A, "rejected", None, "2026-10-20"),  # a later withdrawal ends the earlier consent
            (B, "rejected", None, None),  # undated: the oldest statement
            (B, "active", True, "2026-09-01"),
            (C, "active", True, "2026-10-01"),
            (C, "rejected", None, "2026-10-21"),
            (C, "entered-in-error", None, "2026-10-22"),  # no statement
            ("a1b2c3d4e5f60009", "rejected", None, "2026-12-01"),  # after the day asked
        ]
    )
    st = registry_state(lake, lake.snapshot(), "2026-11-02")
    assert st is not None and st.refused == {A, C}
    assert registry_state(Lake(None), "2026-11-02", "2026-11-02") is None  # no registry ingested: nothing to apply


def test_a_lake_that_fails_otherwise_is_not_read_as_no_refusals() -> None:
    class Broken(Lake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            raise RuntimeError("IO Error: the snapshot cannot be read")

    with pytest.raises(RuntimeError):
        registry_state(Broken(None), "2026-11-02", "2026-11-02")


def test_sync_adds_refusals_and_lifts_only_its_own(db_url: str) -> None:
    reg = OptOutRegister()
    reg.add(B, "paper", "", "console:office1", T0)  # typed at the office
    assert sync_registry(reg, RegistryState(frozenset({A, B}), frozenset()), T1) == (1, 0)
    assert reg.active() == {A, B}
    assert [(e.source, e.by) for e in reg.events(A)] == [("emr", REGISTRY_ACTOR)]
    assert sync_registry(reg, RegistryState(frozenset({A, B}), frozenset()), T1) == (0, 0)  # idempotent
    # the registry records an active consent for both: its own opt-out is lifted, the office's stays
    both = RegistryState(frozenset(), frozenset(), frozenset({A, B}))
    assert sync_registry(reg, both, "2026-11-03T09:00:00+00:00") == (0, 1)
    assert reg.active() == {B}
    reg.close()


# ------------------------------------------------------------------------------------------------ one tick
def _env(reg: OptOutRegister, **kw: Any) -> Any:
    from datacore.optout_worker import WorkerEnv

    return WorkerEnv(register=reg, audit=kw.pop("audit", Audit()), now=NOW, **kw)


def test_one_tick_clears_the_pool_and_withdraws_open_candidates(db_url: str) -> None:
    from datacore.optout_worker import ACTOR, run_once

    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    jobs, audit = Jobs(), Audit()
    out = run_once(_env(reg, jobs=jobs, audit=audit, lake=Lake([(B, "rejected", None, "2026-10-30")])))
    assert out["registry"] == {"added": 1, "lifted": 0} and out["opted_out"] == 2 and out["failed"] == []
    assert jobs.pool == set()
    assert jobs.cands == {("GZQO", A): "withdrawn", ("GZQO", B): "withdrawn", ("RA", A): "enrolled"}
    assert out["stores"]["candidate_registry"] == {"withdrawn": 2, "kept_consented_or_enrolled": 1}
    assert out["stores"]["omop"] == {"skipped": 1}
    assert {s[3] for s in jobs.sets} == {ACTOR}
    ((event, kw),) = audit.events
    assert event == "optout.worker" and A not in repr(kw) and B not in repr(kw)  # counts, never who
    again = run_once(_env(reg, jobs=jobs, lake=Lake([(B, "rejected", None, "2026-10-30")])))
    assert again["stores"]["candidate_pool"] == {"removed": 0}
    assert again["stores"]["candidate_registry"]["withdrawn"] == 0
    reg.close()


def _broken(pids: frozenset[str], env: Any) -> dict[str, int]:
    raise RuntimeError("store down")


def _later(pids: frozenset[str], env: Any) -> dict[str, int]:
    return {"cleared": len(pids)}


def _nothing_left(pids: frozenset[str], env: Any) -> dict[str, int]:
    return {"x.t": 0}


def _one_left(pids: frozenset[str], env: Any) -> dict[str, int]:
    return {"x.t": 1}


def _with_clears(monkeypatch: pytest.MonkeyPatch, *extra: Any) -> None:
    """The registry's clears plus ``extra`` (T-727: the worker runs what the erasure registry names)."""
    from tb_common import erasure

    real = erasure.clears
    monkeypatch.setattr(erasure, "clears", lambda: sorted([*real(), *extra], key=lambda c: c.name))


def test_a_failing_store_does_not_stop_the_others_and_a_store_can_be_added(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore import optout_worker as w
    from tb_common.erasure import Clear

    me = "tests.unit.test_optout_worker"
    _with_clears(monkeypatch, Clear("aaa_broken", f"{me}:_broken", f"{me}:_nothing_left", ""),
                 Clear("vectors", f"{me}:_later", f"{me}:_nothing_left", "T-206b"))  # fmt: skip
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    jobs = Jobs()
    out = w.run_once(_env(reg, jobs=jobs, lake=Lake(None)))
    assert out["failed"] == ["aaa_broken"] and out["registry"] is None
    assert out["stores"]["vectors"] == {"cleared": 1}  # the opted-out patient reached the added store
    assert ("GZQO", A) not in jobs.pool  # the stores after the broken one still ran
    assert out["stores"]["vec"] == {"skipped": 1} and out["stores"]["profile"] == {"skipped": 1}  # no store here
    reg.close()


def test_a_store_that_still_holds_the_patient_after_its_clear_fails_the_tick(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-727: every clear is read back; a row left is never reported as erased: it is named in ``failed``, audited
    (counts only) and the health line turns red."""
    from datacore import optout_worker as w
    from tb_common import metrics
    from tb_common.erasure import Clear

    me = "tests.unit.test_optout_worker"
    _with_clears(monkeypatch, Clear("leaky", f"{me}:_later", f"{me}:_one_left", ""))
    monkeypatch.setattr(w, "OptOutRegister", OptOutRegister)
    OptOutRegister().add(A, "paper", "", "console:office1", T0)
    audit = Audit()
    orch = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=audit,
                           services=SimpleNamespace(lake=None), db=Jobs())  # fmt: skip
    monkeypatch.setattr(w, "STATUS", {"every": 5, "started": NOW.isoformat(), "ok_at": None, "failed": []})
    out = w.tick(orch)
    assert out is not None and out["failed"] == ["leaky"] and out["left"] == {"leaky": {"x.t": 1}}
    assert ("optout.worker_failed", {"actor": w.ACTOR, "detail": {"failed": ["leaky"]}}) in audit.events
    assert A not in repr(audit.events)
    assert metrics.check_optout(w.status(), NOW).level == metrics.RED


def test_the_registry_failing_still_clears_by_the_register(db_url: str) -> None:
    from datacore.optout_worker import run_once

    class Broken(Lake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            raise RuntimeError("IO Error")

    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    jobs = Jobs()
    out = run_once(_env(reg, jobs=jobs, lake=Broken(None)))
    assert out["failed"] == ["registry"] and ("GZQO", A) not in jobs.pool
    reg.close()


def test_the_pool_of_the_job_store_loses_the_patient(db_url: str) -> None:
    from orchestrator.db import JobDB

    jdb = JobDB()
    row = {"pid": A, "tier": "high", "verdicts": []}
    jdb.pool_upsert("GZQO", "1", [row, {**row, "pid": B}], "J1", T0)
    jdb.pool_upsert("RA", "1", [row], "J2", T0)
    assert jdb.pool_remove([A]) == 2
    assert [r["pid"] for r in jdb.pool("GZQO")] == [B] and jdb.pool("RA") == []
    assert jdb.pool_remove([]) == 0


def test_the_interval_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker as w

    monkeypatch.delenv(w.MINUTES_ENV, raising=False)
    assert w.minutes() == 5
    monkeypatch.setenv(w.MINUTES_ENV, "0")
    orch = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")))
    assert w.minutes() == 0 and w.start(orch) is None
    with pytest.raises(RuntimeError, match="PRODUCTION"):  # review LOW-a: never off in PRODUCTION
        w.start(orch, production=True)
    monkeypatch.setenv(w.MINUTES_ENV, "often")
    assert w.minutes() == 5


# ------------------------------------------------------------------------------------------------ OMOP
def _batch(pids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"Patient": [], "Encounter": [], "Condition": []}
    for i, p in enumerate(pids):
        out["Patient"].append({"resourceType": "Patient", "id": p, "birthDate": "1960-01-0" + str(i + 1),
                               "gender": "female"})  # fmt: skip
        out["Encounter"].append({"resourceType": "Encounter", "id": f"e-{p}", "status": "finished",
                                 "class": {"code": "AMB"}, "subject": {"reference": f"Patient/{p}"},
                                 "period": {"start": "2026-10-01T09:00:00", "end": "2026-10-01T10:00:00"}})  # fmt: skip
        out["Condition"].append({"resourceType": "Condition", "id": f"c-{p}", "subject": {"reference": f"Patient/{p}"},
                                 "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "M10.0"}]},
                                 "onsetDateTime": "2026-09-01", "recordedDate": "2026-09-01",
                                 "encounter": {"reference": f"Encounter/e-{p}"}})  # fmt: skip
    return out


def _live(db: Any, pid: str) -> int:
    return int(
        db.fetchval(
            "SELECT count(*) FROM tb_record r JOIN tb_id_map m ON m.id_kind = 'person' AND m.source_id = ? "
            "AND (r.person_id = m.omop_id OR (r.cdm_table = 'person' AND r.record_id = m.omop_id)) "
            "WHERE r.status <> 'tombstoned'",
            (pid,),
        )
    )


def test_omop_withholds_at_once_keeps_out_on_load_and_a_lift_waits_for_the_next_load(db_url: str) -> None:
    from omop import schema
    from omop.load import OPTED_OUT, load_batch, withhold

    db = schema.connect(db_url)
    try:
        load_batch(db, "feed", "2026-10-04", _batch([A, B]), tz="Asia/Taipei")
        assert _live(db, A) == 3 and _live(db, B) == 3
        rep = withhold(db, [A])
        assert rep.as_dict() == {"withheld": 1, "released": 0, "tombstoned": 3}
        assert _live(db, A) == 0 and _live(db, B) == 3
        assert db.fetchval("SELECT count(*) FROM person WHERE person_source_value = ?", (A,)) == 0
        assert db.fetchval("SELECT count(*) FROM condition_occurrence") == 1
        reasons = db.fetchall("SELECT DISTINCT e.reason, e.actor FROM tb_record_event e WHERE e.event = 'tombstone'")
        assert reasons == [(OPTED_OUT, "optout-worker")]
        assert withhold(db, [A]).as_dict() == {"withheld": 0, "released": 0, "tombstoned": 0}  # idempotent
        nxt = load_batch(db, "feed", "2026-10-05", _batch([A, B]), tz="Asia/Taipei")
        assert nxt.restored == 0 and _live(db, A) == 0  # the feed still sends A: kept out
        # a lift releases the row only; the records come back with the next load, not before
        assert withhold(db, []).as_dict() == {"withheld": 0, "released": 1, "tombstoned": 0}
        assert _live(db, A) == 0
        back = load_batch(db, "feed", "2026-10-06", _batch([A, B]), tz="Asia/Taipei")
        assert back.restored == 3 and _live(db, A) == 3
    finally:
        db.close()


def test_a_load_tombstones_a_withheld_patient_the_worker_has_not_reached(db_url: str) -> None:
    from omop import schema
    from omop.load import OPTED_OUT, load_batch

    db = schema.connect(db_url)
    try:
        load_batch(db, "feed", "2026-10-04", _batch([A, B]), tz="Asia/Taipei")
        db.execute("INSERT INTO tb_withheld (pid, reason) VALUES (?, ?)", (A, OPTED_OUT))
        rep = load_batch(db, "feed", "2026-10-05", _batch([A, B]), tz="Asia/Taipei")
        assert rep.tombstoned == 3 and _live(db, A) == 0 and _live(db, B) == 3
        assert {r[0] for r in db.fetchall("SELECT reason FROM tb_record_event WHERE event = 'tombstone'")} == {
            OPTED_OUT
        }
    finally:
        db.close()


def test_the_tick_reaches_omop(db_url: str) -> None:
    from datacore.optout_worker import _omop_store, run_once
    from omop import schema
    from omop.load import load_batch

    reg = OptOutRegister()
    assert _omop_store(reg) is None  # a box without an OMOP store is not given one
    db = schema.connect(db_url)
    load_batch(db, "feed", "2026-10-04", _batch([A, B]), tz="Asia/Taipei")
    db.close()
    reg.add(A, "paper", "", "console:office1", T0)
    omop = _omop_store(reg)
    assert omop is not None
    out = run_once(_env(reg, omop=omop))
    assert out["stores"]["omop"]["tombstoned"] == 3 and _live(omop, A) == 0
    omop.close()
    reg.close()


# ------------------------------------------------------------------------------------------------ every path
def _ctx(received: datetime, audit: Audit) -> Any:
    job = SimpleNamespace(job_id="J1", ruleset="GZQO", received_at=received)
    return SimpleNamespace(job=job, orch=SimpleNamespace(audit=audit))


def test_after_one_tick_no_screening_path_lists_the_patient(db_url: str) -> None:
    """A typed opt-out (A) and a registry refusal (B), one tick, then a job received after it: SCREEN and MICROBATCH
    (``drop_opted_out``), NAV and CASE leave both out; C stays. The cascade's S0 also reads the registry itself."""
    from datacore.optout_worker import run_once
    from orchestrator.clients import StepFailed
    from orchestrator.scenarios import case, nav
    from orchestrator.scenarios.screen import Scoped, drop_opted_out

    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    run_once(_env(reg, jobs=Jobs(), lake=Lake([(B, "rejected", None, "2026-10-30")])))
    after = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
    audit = Audit()
    ctx = _ctx(after, audit)
    scoped = [Scoped(p, None, None, None) for p in (A, B, C)]
    assert [s.pid for s in drop_opted_out(ctx, scoped)] == [C]  # SCREEN, MICROBATCH
    assert [r["pid"] for r in nav._without_opted_out(ctx, [{"pid": p} for p in (A, B, C)])] == [C]
    for p in (A, B):
        with pytest.raises(StepFailed, match="opted out"):
            case.refuse_opted_out(ctx, p)
    case.refuse_opted_out(ctx, C)
    case.refuse_opted_out(ctx, None)
    kinds = [e for e, _ in audit.events]
    assert kinds == ["screen.opt_out_removed", "nav.opt_out_removed", "case.opt_out_refused", "case.opt_out_refused"]
    assert all(A not in repr(kw) and B not in repr(kw) for _, kw in audit.events)
    # a job received before the opt-out is read as the register stood then (D-82): a re-run stays identical
    before = _ctx(datetime(2026, 10, 1, tzinfo=UTC), Audit())
    assert [r["pid"] for r in nav._without_opted_out(before, [{"pid": p} for p in (A, B, C)])] == [A, B, C]
    reg.close()


# ------------------------------------------------------------------------------------------------ review fixes
def _with_consent(pids: list[str], statements: list[tuple[str, str, str]]) -> dict[str, list[dict[str, Any]]]:
    out = _batch(pids)
    out["Consent"] = [
        {"resourceType": "Consent", "id": f"k-{p}-{i}", "status": st, "patient": {"reference": f"Patient/{p}"},
         "dateTime": d, "provision": {"type": "deny" if st == "rejected" else "permit"}}
        for i, (p, st, d) in enumerate(statements)
    ]  # fmt: skip
    return out


def _omop_lake(db: Any) -> Lake:
    """The lake as an OMOP-built rebuild exports it (``lake.source=omop``): its consent table."""
    from omop.export import export_rows

    rows = export_rows(db)["consent"]
    return Lake([(r["pid"], r["status"], r["contact_ok"], str(r["date"]) if r["date"] else None) for r in rows])


def test_high1_the_feed_does_not_undo_its_own_opt_out_on_the_omop_lake(db_url: str) -> None:
    """Review HIGH-1: tick, rebuild, tick, load, rebuild, tick: the patient stays out. Before the fix the withheld
    patient's consent row was tombstoned with the rest, the OMOP-built lake had no refusal, the next tick lifted the
    opt-out and the next load restored the patient."""
    from datacore.optout_worker import _omop_store, run_once
    from omop import schema
    from omop.load import load_batch

    batch = _with_consent([A, B], [(A, "rejected", "2026-10-01")])
    db = schema.connect(db_url)
    load_batch(db, "feed", "2026-10-04", batch, tz="Asia/Taipei")
    reg = OptOutRegister()
    omop = _omop_store(reg)
    for night, snap in enumerate(("2026-10-05", "2026-10-06")):
        out = run_once(_env(reg, jobs=Jobs(), omop=omop, lake=_omop_lake(db)))
        assert out["registry"]["lifted"] == 0 and reg.active() == {A}, night
        assert _omop_lake(db).query("SELECT count(*) AS n FROM consent WHERE pid = $1", [A]).to_pylist()[0]["n"] == 1
        load_batch(db, "feed", snap, batch, tz="Asia/Taipei")
        assert _live(db, A) == 1 and _live(db, B) == 3  # only the consent statement of A is live
    assert omop is not None
    omop.close()
    db.close()
    reg.close()


def test_high1_med1_only_a_later_active_statement_lifts(db_url: str) -> None:
    reg = OptOutRegister()
    sync_registry(reg, RegistryState(frozenset({A}), frozenset()), T0)
    for latest in ("", "inactive", "proposed", "draft"):  # no row at all, or a latest that is not a consent
        st = registry_rule([(A, "rejected", None), *([(A, latest, None)] if latest else [])])
        assert sync_registry(reg, st, T1) == (0, 0) and reg.active() == {A}, latest
    st = registry_rule([(A, "rejected", None), (A, "active", True)])
    assert sync_registry(reg, st, T1) == (0, 1) and reg.active() == set()
    reg.close()


def test_high2_an_office_opt_out_after_the_registry_is_its_own_and_never_lifted(db_url: str) -> None:
    reg = OptOutRegister()
    sync_registry(reg, RegistryState(frozenset({A}), frozenset()), T0)
    audited: list[str] = []
    assert (
        reg.add(A, "paper", "", "console:office1", T1, before_commit=lambda: audited.append("console.opt_out")) is False
    )
    assert audited == ["console.opt_out"]  # the office's action left its event and its audit row
    assert [e.by for e in reg.events(A)] == [REGISTRY_ACTOR, "console:office1"]
    consenting = registry_rule([(A, "rejected", None), (A, "active", True)])
    assert sync_registry(reg, consenting, "2026-11-03T09:00:00+00:00") == (0, 0) and reg.active() == {A}
    assert reg.add(A, "emr", "", REGISTRY_ACTOR, T1) is False and len(reg.events(A)) == 2  # the feed's repeat: none
    # after a lift by the office, a new refusal from the registry is the registry's again
    reg.lift(A, "", "console:office1", "2026-11-04T09:00:00+00:00")
    sync_registry(reg, RegistryState(frozenset({A}), frozenset()), "2026-11-05T09:00:00+00:00")
    assert sync_registry(reg, consenting, "2026-11-06T09:00:00+00:00") == (0, 1)
    reg.close()


@pytest.mark.parametrize("order", [1, -1])
def test_med2_two_statements_on_one_day_are_read_fail_closed(order: int) -> None:
    rows: list[tuple[str, str | None, bool | None, str | None]] = [
        (A, "active", True, "2026-10-20"),
        (A, "rejected", None, "2026-10-20"),
        (B, "inactive", False, "2026-10-20"),
        (B, "active", True, "2026-10-20"),
    ]
    rows = rows[::order]
    st = registry_state(Lake(rows), "2026-11-02", "2026-11-02")
    assert st is not None and st.refused == {A} and B not in st.consenting and B in st.no_contact


class _Pool:
    def __init__(self) -> None:
        self.rows: list[str] = []

    def pool_upsert(self, rs: str, ver: str, rows: list[dict[str, Any]], job: str, at: str) -> None:
        self.rows += [r["pid"] for r in rows]


def test_med3_a_run_that_publishes_after_the_opt_out_drops_the_patient(db_url: str) -> None:
    """Review MED-3: a job received before the opt-out reads its scope as of then (D-82), but its pool and its
    mailed lists read the register again as it stands at publish."""
    from orchestrator.scenarios.screen import opted_out_now, persist_pool
    from tb_contracts import CandidateRow

    audit, pool = Audit(), _Pool()
    ctx = SimpleNamespace(
        job=SimpleNamespace(job_id="J1", ruleset="GZQO", received_at=datetime(2026, 10, 1, tzinfo=UTC)),
        orch=SimpleNamespace(audit=audit, db=pool, _now=lambda: NOW),
    )
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)  # after the job was received
    rs = SimpleNamespace(id="GZQO", version="1")
    rows = [CandidateRow.model_validate({"pid": p, "tier": "high", "criteria": [], "actions": []}) for p in (A, B)]
    persist_pool(ctx, rs, rows)  # type: ignore[arg-type]
    assert pool.rows == [B]
    assert opted_out_now(ctx, [B], "list") == frozenset()  # type: ignore[arg-type]
    assert audit.events == [("screen.opt_out_at_publish", {"job_id": "J1", "ruleset": "GZQO",
                                                          "detail": {"removed": 1, "where": "pool",
                                                                     "register": "optout"}})]  # fmt: skip
    reg.close()


def test_med4_an_opt_out_under_a_merged_chart_hides_the_surviving_pid(db_url: str) -> None:
    from tb_common.db import Database
    from tb_common.optout import opted_out

    pm = Database.connect(db_url, "pidmap")
    pm.execute("CREATE TABLE pid_alias (old_pid TEXT PRIMARY KEY, pid TEXT NOT NULL, reason TEXT NOT NULL, "
               "ticket TEXT NOT NULL, merged_at TEXT NOT NULL)")  # fmt: skip
    pm.execute("INSERT INTO pid_alias VALUES (?, ?, 'merge', 'T-1', ?)", (A, B, T0))
    pm.execute("INSERT INTO pid_alias VALUES (?, ?, 'merge', 'T-2', ?)", (B, C, T1))  # a chain
    pm.close()
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    assert opted_out() == {A, B, C} and reg.effective() == {A, B, C} and reg.active() == {A}
    reg.close()


def test_low_b_a_failing_tick_is_audited_and_turns_the_health_line_red(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore import optout_worker as w
    from tb_common import metrics

    class Down:
        def snapshot(self) -> str:
            raise RuntimeError("lake down")

    audit = Audit()
    orch = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=audit,
                           services=SimpleNamespace(lake=Down()), db=Jobs())  # fmt: skip
    monkeypatch.setattr(w, "STATUS", {"every": 5, "started": NOW.isoformat(), "ok_at": None, "failed": []})
    out = w.tick(orch)
    assert out is not None and out["failed"] == ["registry"] and w.status()["failed"] == ["registry"]
    assert metrics.check_optout(w.status(), NOW).level == metrics.RED
    monkeypatch.setattr(orch.services, "lake", None)
    w.tick(orch)
    st = w.status()
    assert st["failed"] == [] and st["ok_at"] is not None
    now = datetime.fromisoformat(st["ok_at"])
    assert metrics.check_optout(st, now).level == metrics.OK
    # an hour later (not ``replace(hour=...)``: that went 23 hours back between 23:00 and midnight, and the test
    # failed in that hour of the site's day)
    assert metrics.check_optout(st, now + timedelta(hours=1)).level == metrics.RED  # 60 min > 3 x 5
    assert metrics.check_optout({"every": 0}, now).level == metrics.RED
    monkeypatch.setattr(w, "OptOutRegister", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    assert w.tick(orch) is None
    assert audit.events[-1] == ("optout.worker_failed", {"actor": w.ACTOR, "detail": {"failed": ["register"]}})
    health = metrics.evaluate({}, None, now, optout=w.status())
    assert any(c.name == "optout_worker" and c.level == metrics.RED for c in health.checks)


def test_low_b_the_first_tick_runs_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker as w

    monkeypatch.setenv(w.MINUTES_ENV, "5")
    ran: list[int] = []
    monkeypatch.setattr(w, "tick", lambda orch: ran.append(1))
    orch = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")))
    sched = w.start(orch)
    assert sched is not None
    try:
        import time

        for _ in range(50):
            if ran:
                break
            time.sleep(0.1)
        assert ran, "the first tick waits for one interval"
    finally:
        sched.shutdown(wait=False)
