"""The screening cadence (D-397, T-624, review LIFE-014).

* The weekly MICROBATCH screens new in-scope patients in every run, not on the first Monday of a month only; a
  patient a run already looked at since the study's last SCREEN (pool, SCREEN's excluded list, the previous
  micro-batch's record) is not screened again.
* After an ingest (``trigger=ingest``) only new patients booked in the window are screened; the pool is not
  re-checked, and nobody is mailed when nothing new turned up.
* The night budget: the micro-batch jobs of one night never evaluate more patients than
  ``TB_MICROBATCH_NIGHT_BUDGET``; the rest carry over and the run says so.
* :func:`orchestrator.scheduler.after_ingest` submits the after-ingest run for every study with a pool.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.scenarios import microbatch
from orchestrator.scenarios.evaluate import PatientVerdicts, row
from orchestrator.scenarios.screen import Scoped
from tb_common import prefilter
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence, JobMetrics

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
WED = date(2026, 10, 7)  # a Wednesday, not the first Monday of a month
FRI = "2026-10-09T10:00:00+09:00"
RECEIVED = datetime(2026, 10, 6, 18, 0, tzinfo=UTC)  # 03:00 on Wednesday in Tokyo


def _verdicts() -> list[CriterionVerdict]:
    out = []
    for c in GZQO.active():
        verdict: Any = "pending_human" if c.class_ == "human" else "pass"
        conf = 0.9 if c.class_ == "note" else None
        out.append(CriterionVerdict(id=c.id, verdict=verdict, evidence=Evidence(resource_refs=[], confidence=conf)))
    return out


def _pool_row(pid: str) -> dict[str, Any]:
    return {
        "pid": pid,
        "verdicts": [v.model_dump(mode="json") for v in _verdicts()],
        "version": GZQO.version,
        "tier": "high",
        "next_appointment": None,
        "practitioner_id": "D1",
        "department": "RHEU",
        "added_at": "2026-10-01T01:00:00+00:00",
        "last_eval": "2026-10-01T01:00:00+00:00",
        "job_id": "J-SCREEN",
    }


class _Box:
    """A fake orchestrator around one MICROBATCH job: pool, jobs, store, audit and the outputs it published."""

    def __init__(
        self,
        *,
        pool: list[str],
        booked: dict[str, str],
        scope: list[Scoped],
        options: dict[str, str] | None = None,
        budget: int = 2000,
        others: int = 0,
        excluded_at_screen: tuple[str, ...] = (),
    ) -> None:
        self.pool = [_pool_row(p) for p in pool]
        self.booked = booked  # pool pid -> next visit (in the window)
        self.scope = scope
        self.removed: list[str] = []  # the scope's patients the opt-out register removed (10E-12)
        self.evaluated: list[list[str]] = []  # each evaluate_scope call (the re-check)
        self.screened: list[str] = []  # the new-patient screen
        self.persisted: list[str] = []
        self.published: dict[str, bytes] = {}
        self.audit: list[tuple[str, dict[str, Any]]] = []
        self.delivered: list[list[str]] = []
        self.store = {"k-excl": json.dumps({"rows": [{"pid": p} for p in excluded_at_screen]}).encode()}
        screen_job = SimpleNamespace(
            job_id="J-SCREEN",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
            outputs=[SimpleNamespace(filename="excluded_GZQO_v1.json", minio_key="k-excl")],
        )
        other = SimpleNamespace(
            job_id="J-OTHER",
            run_date=WED,
            state="done",
            options={},
            received_at=RECEIVED,
            metrics=JobMetrics(patients_scoped=others),
            outputs=[],
        )
        self.job = SimpleNamespace(
            job_id="J-MB",
            ruleset="GZQO",
            options=dict(options or {}),
            received_at=RECEIVED,
            run_date=WED,
            metrics=None,
            requested_by="scheduler",
        )

        def find(*, type_: str | None = None, **kw: Any) -> list[Any]:
            if type_ == "SCREEN":
                return [screen_job]
            return [other, self.job] if type_ == "MICROBATCH" else []

        self.ctx = SimpleNamespace(
            job=self.job,
            update=self._update,
            state=lambda s: None,
            metrics=self._metrics,
            today=lambda: WED,
            publish=self._publish,
            store=SimpleNamespace(get=lambda key: self.store[key]),
            orch=SimpleNamespace(
                db=SimpleNamespace(pool=lambda rid: self.pool, find=find, locked=lambda name: nullcontext()),
                audit=SimpleNamespace(append=lambda ev, **kw: self.audit.append((ev, kw))),
            ),
            services=SimpleNamespace(
                lake=SimpleNamespace(snapshot=lambda: "2026-10-06", query=self._query), llm=None, verifier=None
            ),
            cfg=SimpleNamespace(
                env=SimpleNamespace(tz="Asia/Tokyo", microbatch_night_budget=budget),
                settings=SimpleNamespace(thresholds=None),
            ),
        )

    def _update(self, **kw: Any) -> Any:
        for k, v in kw.items():
            setattr(self.job, k, v)
        return self.job

    def _metrics(self, **kw: Any) -> None:
        self.job.metrics = JobMetrics.model_validate({**(self.job.metrics or JobMetrics()).model_dump(), **kw})
        rec = self.job.metrics.prefilter
        # 10E-12 (D-1259): every pre-filter record any test of this box writes adds up (in scope = drops + listed)
        assert rec is None or rec.in_scope == sum(getattr(rec, s) for s in prefilter.STAGES), rec

    def _publish(self, name: str, data: bytes, tag: str, to: list[str]) -> Any:
        self.published[name] = data
        return SimpleNamespace(filename=name, tag=tag)

    def _query(self, sql: str, params: list[Any], *a: Any, **kw: Any) -> Any:
        rows = [
            {"pid": p, "next_appt": datetime.fromisoformat(when).replace(tzinfo=None), "practitioner_id": "D1",
             "dept": "RHEU"}
            for p, when in sorted(self.booked.items())
            if p in params[0]
        ]  # fmt: skip
        return SimpleNamespace(to_pylist=lambda: rows)

    def run_screen(
        self, ctx: Any, rs: Any, run_date: date, snapshot: str, select: Any = None, scope: Any = None
    ) -> Any:
        self.scope_given = scope  # D-646: the weekly run hands the scope it counted in
        picked = select(list(self.scope if scope is None else scope))  # D-646: the scope may be handed in
        self.screened += [s.pid for s in picked]
        stamp = "2026-10-07T03:00:00+09:00"
        rows = [
            row(PatientVerdicts(s.pid, _verdicts(), "high", [], 0), s.next_appointment, "D1", "RHEU", stamp)
            for s in picked
        ]
        return SimpleNamespace(scoped=picked, rows=rows, judging=None)

    def evaluate_scope(self, ctx: Any, rs: Any, run_date: date, snap: str, scoped: list[Scoped], **kw: Any) -> Any:
        self.evaluated.append([s.pid for s in scoped])
        return {s.pid: PatientVerdicts(s.pid, [], "high", [], 0) for s in scoped}

    def deliver(self, ctx: Any, rs: Any, rows: list[Any], meta: Any, stem: str, **kw: Any) -> Any:
        self.delivered.append([r.pid for r in rows])
        return [], {}

    def persist(self, ctx: Any, rs: Any, rows: list[Any]) -> None:
        self.persisted += [r.pid for r in rows]

    def go(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        for name, fn in (
            ("require_open", lambda rs: None),
            ("require_approved", lambda ctx, rs, v: GZQO),
            ("drop_opted_out", lambda ctx, scoped: scoped),
            ("evaluate_scope", self.evaluate_scope),
            ("run_screen", self.run_screen),
            ("screen_scope_read", lambda ctx, rs, run_date, snapshot: (list(self.scope), list(self.removed))),  # D-1259
            ("persist_pool", self.persist),
            ("practitioners_of", lambda ctx, rs: ["D1"]),
            ("deliver_lists", self.deliver),
            ("report_meta", lambda *a, **kw: None),
            ("practitioner_names", lambda ctx: {}),
            ("small_cell", lambda ctx, rs: 0),
            ("recipients", lambda routing, by: ["pi@hospa.test"]),
        ):
            monkeypatch.setattr(microbatch, name, fn)
        from orchestrator.reports import screen_summary_pdf

        monkeypatch.setattr(screen_summary_pdf, "render", lambda *a, **kw: b"%PDF")
        return microbatch.run(self.ctx)  # type: ignore[arg-type]

    def budget_event(self) -> dict[str, Any]:
        return next(kw["detail"] for ev, kw in self.audit if ev == "microbatch.budget")


def _new(pid: str, when: str | None) -> Scoped:
    return Scoped(pid, when, "D1", "RHEU")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    monkeypatch.delenv("TB_SCREEN_JUDGE", raising=False)


def test_the_weekly_run_screens_new_patients_on_any_week(monkeypatch: pytest.MonkeyPatch) -> None:
    """LIFE-014: a Wednesday run (not the first Monday) screens the new in-scope patients and adds them to the pool;
    the pool is not screened again. D-642 (NEW-LIFE-4) changed the rest on purpose: the patient SCREEN excluded,
    still in scope, is screened again after the new ones (before, never until the next SCREEN: review LIFE-004)."""
    box = _Box(
        pool=["P-POOL"],
        booked={"P-POOL": "2026-10-08T09:00:00+09:00"},
        scope=[_new("P-POOL", None), _new("P-EXCL", FRI), _new("P-NEW", FRI), _new("P-LATER", None)],
        excluded_at_screen=("P-EXCL",),
    )
    out = box.go(monkeypatch)
    assert box.screened == ["P-NEW", "P-LATER", "P-EXCL"]  # new: nearest visit first, no visit last; then excluded
    assert box.evaluated == [["P-POOL"]]  # the pool's re-check
    assert {"P-POOL", "P-NEW", "P-LATER"} <= set(box.persisted)
    record = json.loads(box.published["new_screened_GZQO_v" + GZQO.version + ".json"])
    assert record["pids"] == ["P-EXCL", "P-LATER", "P-NEW"] and record["again"] == {"P-EXCL": WED.isoformat()}
    cl = json.loads(box.published["candidate_list_GZQO_v" + GZQO.version + ".json"])
    # the console's whole list; the stand-in screen lists everybody, so the one who came back is on it
    assert {r["pid"] for r in cl["rows"]} == {"P-POOL", "P-NEW", "P-LATER", "P-EXCL"}
    assert box.delivered == [["P-POOL", "P-EXCL", "P-NEW"]]  # the week's list: visits in the window
    assert "new patients screened: 2" in out.summary_md  # the new ones are still counted as two
    assert "Earlier excluded patients screened again: 1" in out.summary_md
    assert box.job.metrics.patients_scoped == 4  # the night budget counts the one screened again


def test_a_previous_micro_batch_record_is_not_screened_as_new(monkeypatch: pytest.MonkeyPatch) -> None:
    """Was "... is not screened again". D-642 (NEW-LIFE-4): P-A is in the earlier record and not in the pool, so
    that run excluded it; it is no new patient (it does not take a new patient's place), and it is screened again
    after them. One the earlier run listed (P-L, in the pool) is not screened again."""
    box = _Box(pool=["P-POOL", "P-L"], booked={}, scope=[_new("P-A", FRI), _new("P-B", FRI), _new("P-L", FRI)])
    box.store["k-prev"] = json.dumps({"pids": ["P-A", "P-L"]}).encode()
    box.job.options = {"seen_from": "k-excl,k-prev"}  # as a first run would have fixed it
    box.go(monkeypatch)
    assert box.screened == ["P-B", "P-A"]
    record = json.loads(box.published["new_screened_GZQO_v" + GZQO.version + ".json"])
    assert record["pids"] == ["P-A", "P-B", "P-L"]  # cumulative: the next run reads one record
    assert box.budget_event()["new_screened"] == 1 and box.budget_event()["excluded_rescreened"] == 1


def test_after_an_ingest_only_new_booked_patients_are_screened(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Tuesday-to-Friday case: a patient new in Tuesday's data, booked on Friday, is screened on the Wednesday
    run after the ingest; a new patient booked beyond the window or not booked waits for the weekly run."""
    box = _Box(
        pool=["P-POOL"],
        booked={"P-POOL": "2026-10-08T09:00:00+09:00"},
        scope=[_new("P-FRI", FRI), _new("P-FAR", "2026-12-01T10:00:00+09:00"), _new("P-NONE", None)],
        options={"trigger": "ingest"},
    )
    out = box.go(monkeypatch)
    assert box.screened == ["P-FRI"]
    assert box.evaluated == []  # no re-check after an ingest
    assert box.persisted == ["P-FRI"]  # the pool's rows are not touched
    assert box.delivered == [["P-FRI"]]  # the mail names the new candidate only
    cl = json.loads(box.published["candidate_list_GZQO_v" + GZQO.version + ".json"])
    assert [r["pid"] for r in cl["rows"]] == ["P-POOL", "P-FRI"]  # by visit: Thursday, Friday
    assert out.deliveries  # mailed


def test_after_an_ingest_with_nothing_new_nobody_is_mailed(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _Box(pool=["P-POOL"], booked={}, scope=[_new("P-POOL", FRI)], options={"trigger": "ingest"})
    out = box.go(monkeypatch)
    assert box.screened == [] and out.deliveries == [] and box.delivered == []
    assert any(n.startswith("candidate_list_") for n in box.published)  # the console's list is still refreshed


def test_the_night_budget_is_never_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Budget 5, another study's micro-batch used 2 this night: this job evaluates 3 patients (2 re-checks, then 1
    new patient, nearest visit first); the rest carry over, and the summary and the audit say how many."""
    pool = ["P1", "P2"]
    box = _Box(
        pool=pool,
        booked={p: "2026-10-08T09:00:00+09:00" for p in pool},
        scope=[_new(f"N{i}", f"2026-10-{10 + i}T10:00:00+09:00") for i in range(4)],
        budget=5,
        others=2,
    )
    out = box.go(monkeypatch)
    assert sum(len(e) for e in box.evaluated) + len(box.screened) == 3
    assert box.screened == ["N0"]
    assert box.job.metrics.patients_scoped == 3  # what the next micro-batch of the night counts
    assert box.job.options["night_left"] == "3"  # fixed for a resumed job and a re-run
    ev = box.budget_event()
    assert ev["left"] == 3 and ev["new_carried"] == 3 and ev["recheck_carried"] == 0
    assert "carried over to the next run" in out.summary_md


def test_an_exhausted_night_re_checks_the_nearest_visits_and_screens_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = ["P1", "P2", "P3"]
    box = _Box(
        pool=pool,
        booked={"P1": "2026-10-12T09:00:00+09:00", "P2": "2026-10-08T09:00:00+09:00", "P3": FRI},
        scope=[_new("N0", FRI)],
        budget=4,
        others=2,
    )
    box.go(monkeypatch)
    assert box.evaluated == [["P2", "P3"]]  # the two nearest visits
    assert box.screened == []
    assert "P1" not in box.persisted  # left out by the budget: its last evaluation stands
    ev = box.budget_event()
    assert ev["recheck_carried"] == 1 and ev["new_carried"] == 1


def test_no_budget_means_no_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _Box(pool=["P1"], booked={}, scope=[_new(f"N{i}", FRI) for i in range(5)], budget=0, others=10_000)
    box.go(monkeypatch)
    assert len(box.screened) == 5 and box.job.options["night_left"] == "-1"


def test_incident_0_is_a_re_check_only(monkeypatch: pytest.MonkeyPatch) -> None:
    box = _Box(pool=["P1"], booked={"P1": FRI}, scope=[_new("N0", FRI)], options={"incident": "0"})
    box.go(monkeypatch)
    assert box.screened == [] and box.evaluated == [["P1"]]


def test_a_re_run_does_not_count_its_own_new_patients_as_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """A re-run starts from the pool the original left: the rows the original added are this run's new patients."""
    box = _Box(pool=["P1"], booked={}, scope=[_new("N0", FRI)], options={"seen_from": "k-excl", "night_left": "-1"})
    added = _pool_row("N0") | {"job_id": "J-MB", "added_at": (RECEIVED + timedelta(minutes=5)).isoformat()}
    box.pool.append(added)
    box.go(monkeypatch)
    assert box.screened == ["N0"]


def test_the_budget_setting_is_declared() -> None:
    from tb_common.config import ConfigError, load_env

    env = load_env(dotenv=Path("/nonexistent"), environ={"TB_MICROBATCH_NIGHT_BUDGET": "300"})
    assert env.microbatch_night_budget == 300
    assert load_env(dotenv=Path("/nonexistent"), environ={}).microbatch_night_budget == 2000
    with pytest.raises(ConfigError):
        load_env(dotenv=Path("/nonexistent"), environ={"TB_MICROBATCH_NIGHT_BUDGET": "-1"})


# ---------------------------------------------------------------------------------------------- the scheduler
class _Orch:
    def __init__(self) -> None:
        self.scenarios = {"MICROBATCH": None}
        self.created: list[tuple[str, str | None, dict[str, str] | None]] = []
        self.db = SimpleNamespace(pool_rulesets=lambda: ["GZQO", "ADX"])
        self.audit = SimpleNamespace(append=lambda ev, **kw: None)

    def create(self, req: Any) -> None:
        self.created.append((req.type, req.ruleset, req.options))


def test_after_ingest_submits_a_micro_batch_for_every_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: "paused" if rid == "ADX" else "open")
    orch = _Orch()
    assert scheduler.after_ingest(orch) == ["GZQO"]  # type: ignore[arg-type]
    assert orch.created == [("MICROBATCH", "GZQO", {"trigger": "ingest"})]  # a paused study is held (D-386)


def test_after_the_timer_s_ingest_the_night_self_test_must_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timer's ingest (option timer=1) is followed only when the night's model self-test passed; an ingest
    asked for by hand is followed at once (as run_now starts a job without the gate)."""
    from orchestrator import scheduler

    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: "open")
    monkeypatch.setattr(scheduler, "night_gate", lambda orch: False)
    orch = _Orch()
    assert scheduler.after_ingest(orch, timed=True) == [] and orch.created == []  # type: ignore[arg-type]
    assert scheduler.after_ingest(orch) == ["GZQO", "ADX"]  # type: ignore[arg-type]
    monkeypatch.setattr(scheduler, "night_gate", lambda orch: True)
    assert scheduler.after_ingest(orch, timed=True) == ["GZQO", "ADX"]  # type: ignore[arg-type]


def test_the_timer_marks_its_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler

    added: dict[str, Any] = {}

    class _Sched:
        def __init__(self, **kw: Any) -> None:
            pass

        def add_job(self, fn: Any, trigger: str, id: str, args: Any = None, **kw: Any) -> None:
            added[id] = args

        def start(self) -> None:
            pass

    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", _Sched)
    monkeypatch.setattr("tb_common.config.schedule_on_demand", lambda settings, env: False)
    monkeypatch.setattr("orchestrator.night.advance", lambda orch: [])
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(settings=SimpleNamespace(schedule=None), env=SimpleNamespace(tz="Asia/Tokyo", extra={})),
        on_terminal=[],
    )
    scheduler.start(orch)
    # T-726 (D-492): the timer's ingest is also the start of the night's chain
    assert added["ingest"][1:] == ["INGEST", None, {"timer": "1", "chain": "1"}]


def test_a_passed_ingest_is_followed_by_the_micro_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import scheduler
    from orchestrator.scenarios import admin

    calls: list[Any] = []

    def follow(orch: Any, timed: bool = False) -> list[str]:
        calls.append((orch, timed))
        return []

    monkeypatch.setattr(scheduler, "after_ingest", follow)
    report = SimpleNamespace(snapshot=date(2026, 10, 6), passed=True, errors=[])
    orch = SimpleNamespace()
    ctx: Any = SimpleNamespace(
        services=SimpleNamespace(adapter=SimpleNamespace(run=lambda req: report)),
        state=lambda s: None,
        cfg=SimpleNamespace(settings=SimpleNamespace(data_source=SimpleNamespace(type="csv"))),
        job=SimpleNamespace(options={"timer": "1"}),
        update=lambda **kw: None,
        publish=lambda *a, **kw: None,
        orch=orch,
    )
    monkeypatch.setattr(admin, "dump", lambda r: {})
    admin.ingest(ctx)
    assert calls == [(orch, True)]
