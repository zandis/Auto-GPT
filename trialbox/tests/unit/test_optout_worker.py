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
    assert st == RegistryState(frozenset({A}), frozenset({C}), frozenset({B, C}), frozenset({B}))


def test_registry_state_reads_the_lake_with_the_cohort_rule() -> None:
    lake = Lake(
        [
            (A, "active", True, "2026-10-01"),
            (A, "rejected", None, "2026-10-20"),  # a later withdrawal ends the earlier consent
            # undated: its date is unknown, so the dated consent cannot be shown to be later. The patient stays
            # refused (the ruling on the review of T-708, D-477; before: "the oldest statement", not refused)
            (B, "rejected", None, None),
            (B, "active", True, "2026-09-01"),
            (C, "active", True, "2026-10-01"),
            (C, "rejected", None, "2026-10-21"),
            (C, "entered-in-error", None, "2026-10-22"),  # no statement
            ("a1b2c3d4e5f60009", "rejected", None, "2026-12-01"),  # after the day asked
        ]
    )
    st = registry_state(lake, lake.snapshot(), "2026-11-02")
    assert st is not None and st.refused == {A, B, C} and B not in st.consenting
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
    # one hour later as a timedelta: replace(hour=h + 1) wraps back to the same day at 23:xx
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


# ------------------------------------------------------------------------------------------------ D-684: no snapshot
def test_a_lake_that_cannot_name_its_snapshot_is_a_failed_registry_and_the_clears_run(db_url: str) -> None:
    """A lake that does not answer (its client raises) is not "nothing to read": the tick names the registry as
    failed, and the stores are still cleared by the register."""
    from datacore.optout_worker import run_once

    class Down(Lake):
        def snapshot(self) -> str:
            raise ConnectionError("the lake does not answer")

    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    jobs, audit = Jobs(), Audit()
    out = run_once(_env(reg, jobs=jobs, lake=Down(None), audit=audit))
    assert out["failed"] == ["registry"] and out["registry"] is None
    assert ("GZQO", A) not in jobs.pool and "registry_not_read" not in out
    reg.close()


def test_a_lake_with_no_snapshot_yet_is_said_in_the_tick_not_passed_over(db_url: str) -> None:
    """A lake that answers "no snapshot" (a box before its first night) has no registry to read. That is not a
    failure, and it is not silent either: the tick's result and its audit event say the registry was not read
    and why, so a box that stays without a snapshot shows in every tick."""
    from datacore.optout_worker import run_once

    class Empty(Lake):
        def snapshot(self) -> Any:
            return None

    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    jobs, audit = Jobs(), Audit()
    out = run_once(_env(reg, jobs=jobs, lake=Empty(None), audit=audit))
    assert out["failed"] == [] and out["registry"] is None
    assert out["registry_not_read"] == "no snapshot"
    assert audit.events[-1][1]["detail"]["registry_not_read"] == "no snapshot"
    assert ("GZQO", A) not in jobs.pool
    reg.close()


def test_a_snapshot_without_a_consent_table_and_a_box_without_a_lake_are_said_too(db_url: str) -> None:
    """The review: two more ticks read no registry and said nothing. Not failures here (whether a PRODUCTION box
    refuses a snapshot without a consent table is the owner's open question); each is named in the tick."""
    from datacore.optout_worker import run_once

    reg = OptOutRegister()
    out = run_once(_env(reg, jobs=Jobs(), lake=Lake(None)))  # a snapshot, and no consent table in it
    assert (out["registry"], out["failed"], out["registry_not_read"]) == (None, [], "no consent table")
    out = run_once(_env(reg, jobs=Jobs()))  # no lake at all
    assert (out["registry"], out["failed"], out["registry_not_read"]) == (None, [], "no lake")
    out = run_once(_env(reg, jobs=Jobs(), lake=Lake([(B, "rejected", None, "2026-11-01")])))
    assert out["registry"] is not None and "registry_not_read" not in out  # a registry that was read
    reg.close()


# ------------------------------------------------------------------------------------------------ D-685: every OMOP store
SITE_STORE = "omop_0123456789"  # as omop.schema.schema_for names the store of a lake that is not the box's own


def _two_stores(db_url: str) -> None:
    from omop import schema
    from omop.load import load_batch

    for name in ("omop", SITE_STORE):
        db = schema.connect(db_url, name)
        load_batch(db, "feed", "2026-10-04", _batch([A, B]), tz="Asia/Taipei")
        db.close()


def test_the_worker_finds_every_omop_store_the_database_holds(db_url: str) -> None:
    from datacore.optout_worker import omop_store_names
    from omop import schema
    from tb_common.db import Database

    assert omop_store_names(db_url) == []
    _two_stores(db_url)
    with Database.connect(db_url, "omop_notastore") as other:  # a schema that only looks alike is not a store
        other.execute("CREATE TABLE tb_record (k INT)")
    with Database.connect(db_url, "omop_abcdef0123") as empty:  # the name of a store, and no store in it
        empty.execute("CREATE TABLE something_else (k INT)")
    assert omop_store_names(db_url) == ["omop", SITE_STORE]
    assert schema.schema_for(None) == "omop"


def test_a_patient_is_taken_out_of_every_omop_store_in_one_tick(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A practice site's own lake has its own OMOP store (``omop_<hash>``). The worker cleared the box's store
    only: an opted-out patient stayed live in the other, and the tick said nothing had failed."""
    from datacore import optout_worker as w
    from omop import schema

    monkeypatch.setenv("TB_DB_URL", db_url)
    _two_stores(db_url)
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    reg.close()
    orch = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=Audit(),
        services=SimpleNamespace(lake=Lake([])), db=Jobs(),
    )  # fmt: skip
    out = w.tick(orch)
    assert out is not None and out["failed"] == [], out
    assert out["stores"]["omop"]["tombstoned"] == 6 and out["stores"]["omop"]["stores"] == 2
    for name in ("omop", SITE_STORE):
        db = schema.connect(db_url, name)
        try:
            assert _live(db, A) == 0 and _live(db, B) > 0, name
            assert db.fetchval("SELECT count(*) FROM tb_withheld WHERE pid = ?", (A,)) == 1, name
        finally:
            db.close()


def test_one_omop_store_that_cannot_be_opened_is_named_and_the_others_are_cleared(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacore import optout_worker as w
    from omop import schema

    monkeypatch.setenv("TB_DB_URL", db_url)
    _two_stores(db_url)
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    reg.close()
    real = schema.connect

    def connect(url: str | None = None, name: str = "omop") -> Any:
        if name == SITE_STORE:
            raise RuntimeError(f"permission denied for {A}")
        return real(url, name)

    monkeypatch.setattr(schema, "connect", connect)
    orch = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=Audit(),
        services=SimpleNamespace(lake=Lake([])), db=Jobs(),
    )  # fmt: skip
    out = w.tick(orch)
    assert out is not None and out["failed"] == ["omop"]
    assert out["not_opened"] == [SITE_STORE]  # which store: a schema's name, never a patient's
    assert "omop" not in out["stores"] and A not in str(out) and A not in str(orch.audit.events)
    monkeypatch.undo()
    box, site = real(db_url, "omop"), real(db_url, SITE_STORE)
    try:
        assert _live(box, A) == 0  # the store that opened was cleared in the same tick
        assert _live(site, A) > 0  # the other is not reported as cleared
    finally:
        box.close()
        site.close()


def test_a_row_left_in_a_second_omop_store_fails_the_tick_by_that_stores_name(db_url: str) -> None:
    from datacore.optout_worker import verify_omop
    from omop import schema

    _two_stores(db_url)
    reg = OptOutRegister()
    box, site = schema.connect(db_url, "omop"), schema.connect(db_url, SITE_STORE)
    try:
        left = verify_omop(frozenset({A}), _env(reg, omop=box, omop_more={SITE_STORE: site}))
        assert left["omop.person"] == 1 and left[f"{SITE_STORE}.person"] == 1
        assert left["omop.tb_withheld"] == 1 and left[f"{SITE_STORE}.tb_withheld"] == 1
    finally:
        box.close()
        site.close()
        reg.close()


def test_the_worker_knows_every_name_an_omop_store_can_have() -> None:
    """A new kind of OMOP store fails here until the worker finds it: every name ``omop.schema.schema_for`` gives
    is one ``omop_store_names`` looks for, and every caller that opens a store names it with the box's own name
    or with ``schema_for`` (listed; a new caller fails until it is read)."""
    import ast
    from pathlib import Path

    from datacore.optout_worker import OMOP_STORE
    from omop import schema

    for path in (None, Path("/data/lake"), Path("/srv/practice/a/lake"), Path("relative/lake"), Path("/")):
        assert OMOP_STORE.fullmatch(schema.schema_for(path)), path
    root = Path(__file__).resolve().parents[2]
    callers: dict[str, list[str]] = {}
    for top in ("services", "tools", "libs"):
        for f in sorted((root / top).rglob("*.py")):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module == "omop.schema":
                    # the store is opened as `schema.connect(...)` everywhere, so this scan sees every opener
                    assert "connect" not in {a.name for a in node.names}, f
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "schema"):  # fmt: skip
                    name = node.args[1] if len(node.args) > 1 else None
                    callers.setdefault(str(f.relative_to(root)), []).append(ast.unparse(name) if name else "omop")
    assert callers == {
        "services/adapter/dual_write.py": ["name"],  # schema.schema_for(cfg.lake_dir)
        "services/criteria_compiler/terminology/resolver.py": ["omop"],
        "services/datacore/optout_worker.py": ["omop", "name"],  # the box's own, then every name it found
        "services/lake/source.py": ["schema.schema_for(lake_dir)"],
        "services/omop/__main__.py": ["omop"],
        "services/omop/catalogue_load.py": ["omop"],
        "services/orchestrator/app.py": ["omop"],  # NEW-ARCH-3 slice 2 (D-865): the clinical conflicts, the box's own
        "tools/backup_drill.py": ["omop"],
        "tools/codemap_release.py": ["omop"],
        "tools/omop_parity.py": ["schema.schema_for(lake_dir)"],
        # D-720/D-721: the drill's write paths: the box's own store as each service role, then a second lake's,
        # named by schema.schema_for(folder) (second_lake)
        # D-872: and the console refused the second lake's store
        "tools/role_paths.py": ["omop", "omop", "omop", "name", "name", "name", "omop", "name"],
        "tools/trialbox/omop_store.py": ["name"],  # D-721: name = schema.schema_for(lake_dir), made for the group
    }


# ------------------------------------------------------------------------------------------------ D-685: the review
def test_a_store_whose_clear_fails_does_not_keep_the_later_stores_from_being_cleared(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review: a withhold that raised in one store ended the loop, so a store that fails every tick starved
    every store after it. Each store is tried; the clear fails after all of them."""
    from datacore import optout_worker as w
    from omop import load, schema

    last = "omop_fedcba9876"
    _two_stores(db_url)
    db = schema.connect(db_url, last)
    load.load_batch(db, "feed", "2026-10-04", _batch([A, B]), tz="Asia/Taipei")
    db.close()
    real = load.withhold

    def withhold(store: Any, pids: Any, actor: str = "x") -> Any:
        if store.schema.endswith(SITE_STORE):
            raise RuntimeError(f"deadlock while withholding {A}")
        return real(store, pids, actor)

    monkeypatch.setattr(load, "withhold", withhold)
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    stores = {n: schema.connect(db_url, n) for n in ("omop", SITE_STORE, last)}
    try:
        out = w.run_once(_env(reg, omop=stores["omop"], omop_more={SITE_STORE: stores[SITE_STORE], last: stores[last]}))
        assert out["failed"] == ["omop"] and "omop" not in out["stores"] and A not in str(out)
        assert out["not_cleared"] == [SITE_STORE]
        assert (_live(stores["omop"], A), _live(stores[SITE_STORE], A), _live(stores[last], A)) == (0, 3, 0)
    finally:
        for s in stores.values():
            s.close()
        reg.close()


def test_omop_stores_in_both_databases_are_cleared_when_the_box_names_two(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review: with ``TB_OMOP_DB_URL`` only that database was listed; a store under the register's own URL
    kept the patient and the tick said nothing failed. Stood in for here by a second ``tb_prefix``."""
    from datacore import optout_worker as w
    from omop import schema
    from omop.load import load_batch

    other = db_url + ("&" if "?" in db_url else "?") + "tb_prefix=" if "tb_prefix=" not in db_url else db_url
    other = db_url.replace("tb_prefix=", "tb_prefix=second_") if "tb_prefix=" in db_url else other + "second_"
    for url, name in ((other, "omop"), (db_url, SITE_STORE)):
        db = schema.connect(url, name)
        load_batch(db, "feed", "2026-10-04", _batch([A, B]), tz="Asia/Taipei")
        db.close()
    monkeypatch.setenv("TB_DB_URL", db_url)
    monkeypatch.setenv("TB_OMOP_DB_URL", other)
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", T0)
    reg.close()
    orch = SimpleNamespace(
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), audit=Audit(),
        services=SimpleNamespace(lake=Lake([])), db=Jobs(),
    )  # fmt: skip
    out = w.tick(orch)
    assert out is not None and out["failed"] == [] and out["stores"]["omop"]["stores"] == 2
    for url, name in ((other, "omop"), (db_url, SITE_STORE)):
        db = schema.connect(url, name)
        try:
            assert _live(db, A) == 0, name
        finally:
            db.close()


def test_the_worker_never_makes_a_store_it_was_told_of(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The review: a store listed and gone before it was opened was made anew by opening it, and counted."""
    from datacore import optout_worker as w
    from tb_common.db import Database

    monkeypatch.setenv("TB_DB_URL", db_url)
    monkeypatch.setattr(w, "omop_store_names", lambda url: ["omop_0000000000"])
    reg = OptOutRegister()
    try:
        box, more, not_opened = w._omop_stores(reg)
        assert (box, more, not_opened) == (None, {}, frozenset())
    finally:
        reg.close()
    with Database.connect(db_url, "optout") as db:
        assert db.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname LIKE '%omop\\_0000000000'") == 0
