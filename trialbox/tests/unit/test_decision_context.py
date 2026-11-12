"""The decision context (T-708, D-477): one register read, one consent rule, one note-block decision per job.

The paths against each other are ``tests/property/test_path_independence.py`` (a real box). Here: the object itself
on a small DuckDB "lake" with a consent table, so the one rule's SQL runs for real.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from orchestrator.decision_context import (
    NO_CONTACT_ACTION,
    REFUSED_REASON,
    DecisionContext,
    decision_of,
    note_block_of,
)
from orchestrator.scenarios import case as case_mod
from orchestrator.scenarios import nav as nav_mod
from orchestrator.scenarios import screen as screen_mod
from orchestrator.scenarios.evaluate import PatientVerdicts
from tb_common import optout as optout_mod

from tests.judge_kit import note_criterion, ruleset

RUN = date(2026, 10, 5)
RS = ruleset([note_criterion("T-INC-02", "inclusion", "Gout flare", "Is a gout flare noted?")])

# (pid, status, contact_ok, date): the planted statements, in no particular order
CONSENT: list[tuple[str, str, bool | None, str | None]] = [
    ("P-REFUSED", "rejected", False, "2026-05-01"),
    ("P-NOCONTACT", "active", False, "2026-05-01"),
    ("P-OK", "active", True, "2026-05-01"),
    ("P-UNDATED", "active", True, "2026-05-01"),
    # an undated refusal: its date is unknown, so it cannot be shown to be older than the consent. The patient is
    # out on every path (the integrator's ruling on the review of T-708, until the owner decides)
    ("P-UNDATED", "rejected", False, None),
    ("P-UNDATEDOK", "active", True, None),  # an undated consent is the oldest statement: the dated refusal decides
    ("P-UNDATEDOK", "rejected", False, "2026-05-01"),
    ("P-ERROR", "active", True, "2026-04-01"),
    ("P-ERROR", "entered-in-error", False, "2026-06-01"),  # no statement
    ("P-LATER", "active", True, "2026-05-01"),
    ("P-LATER", "rejected", False, "2026-11-01"),  # after the run date: not yet said
    ("P-SAMEDAY", "active", True, "2026-07-01"),
    ("P-SAMEDAY", "rejected", False, "2026-07-01"),  # a tie of one day fails closed: the refusal
    ("P-NULLCONTACT", "active", None, "2026-07-01"),
    ("P-NULLCONTACT", "active", True, "2026-07-01"),  # same day, one does not say "contact allowed"
    ("P-WITHDRAWN", "active", True, "2026-03-01"),
    ("P-WITHDRAWN", "inactive", None, "2026-08-01"),
]


class Lake:
    """A lake of one table. ``consent=False``: the registry was never ingested (no table)."""

    def __init__(self, consent: bool = True) -> None:
        self.con = duckdb.connect(":memory:")
        self.queries = 0
        if consent:
            self.con.execute("CREATE TABLE consent (pid VARCHAR, status VARCHAR, contact_ok BOOLEAN, date DATE)")
            self.con.executemany("INSERT INTO consent VALUES (?, ?, ?, ?)", CONSENT)

    def snapshot(self) -> str:
        return "2026-10-05"

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        self.queries += 1
        return self.con.execute(sql, params or []).to_arrow_table()


def _ctx(lake: Any = None, llm: Any = None, verifier: Any = None) -> Any:
    audit: list[tuple[str, dict[str, Any]]] = []
    return SimpleNamespace(
        job=SimpleNamespace(job_id="J1", ruleset="T", options={}, received_at=datetime(2026, 10, 5, 1, tzinfo=UTC)),
        today=lambda: RUN,
        orch=SimpleNamespace(audit=SimpleNamespace(append=lambda ev, **kw: audit.append((ev, kw["detail"])))),
        services=SimpleNamespace(lake=lake if lake is not None else Lake(), llm=llm, verifier=verifier),
        cfg=SimpleNamespace(settings=SimpleNamespace(thresholds=None)),
        audited=audit,
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    for name in ("TB_DB_URL", "TB_SCREEN_JUDGE", "TB_MODEL_SWAP"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------------------------------------ consent: one rule
def test_the_latest_statement_on_or_before_the_run_date_decides() -> None:
    d = DecisionContext(_ctx())
    assert d.refused() == {"P-REFUSED", "P-SAMEDAY", "P-UNDATED", "P-UNDATEDOK"}
    assert d.no_contact() == {"P-REFUSED", "P-NOCONTACT", "P-SAMEDAY", "P-UNDATEDOK"}
    state = d.consent()
    assert state is not None
    assert state.contactable == {"P-OK", "P-ERROR", "P-LATER"}  # never a patient with an undated refusal
    assert "P-UNDATED" not in state.consenting  # and that consent does not lift the register's opt-out
    # after the later refusal's date the same rule says refused
    assert "P-LATER" in d.consent(date(2026, 11, 2)).refused  # type: ignore[union-attr]


def test_consent_is_read_once_per_job_and_day() -> None:
    lake = Lake()
    d = DecisionContext(_ctx(lake))
    d.refused(), d.no_contact(), d.consent(), d.uncounted()
    assert lake.queries == 1
    d.contactable(date(2026, 6, 30))
    assert lake.queries == 2


def test_a_lake_without_a_consent_table_has_no_statements_and_any_other_failure_stops() -> None:
    d = DecisionContext(_ctx(Lake(consent=False)))
    assert d.consent() is None and d.refused() == frozenset() and d.contactable(RUN) is None

    class Broken:
        def query(self, *a: Any, **kw: Any) -> Any:
            raise RuntimeError("lake query failed (500): Binder Error: column contact_ok not found in consent")

    with pytest.raises(RuntimeError):  # D-127: skipping consent would list patients who said no
        DecisionContext(_ctx(Broken())).refused()


def test_the_cascade_and_cohort_read_the_same_state() -> None:
    """COHORT's ``n_contactable`` is the context's ``contactable``; the cascade's S0 is given ``consent`` itself."""
    from orchestrator.scenarios import cohort

    ctx = _ctx()
    ctx.cfg.settings.registry_source = SimpleNamespace(type="fhir")
    assert cohort.contactable_pids(ctx, RUN) == {"P-OK", "P-ERROR", "P-LATER"}
    assert cohort.contactable_pids(ctx, date(2026, 7, 15)) == {"P-OK", "P-ERROR", "P-LATER", "P-WITHDRAWN"}
    ctx.cfg.settings.registry_source = None
    assert cohort.contactable_pids(ctx, RUN) is None


# ------------------------------------------------------------------------------------------------ the register
def test_the_register_is_read_as_of_the_jobs_receipt_once_and_now_each_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str | None] = []

    def register(url: str | None = None, as_of: str | None = None) -> frozenset[str]:
        calls.append(as_of)
        return frozenset({"P-A"}) if as_of else frozenset({"P-A", "P-B"})

    monkeypatch.setattr(optout_mod, "opted_out", register)
    ctx = _ctx()
    d = decision_of(ctx)
    assert d is decision_of(ctx)  # one per context
    assert d.register() == {"P-A"} and d.register() == {"P-A"}
    assert calls == ["2026-10-05T01:00:00+00:00"]
    assert d.drop(["P-A", "P-B", "P-C"], "screen.opt_out_removed") == {"P-A"}
    assert d.drop_now(["P-A", "P-B", "P-C"], "screen.opt_out_at_publish", where="list") == {"P-A", "P-B"}
    assert d.drop_now([], "screen.opt_out_at_publish", where="list") == frozenset()  # nobody asked: no read
    assert calls == ["2026-10-05T01:00:00+00:00", None]
    assert ctx.audited == [
        ("screen.opt_out_removed", {"removed": 1, "register": "optout"}),
        ("screen.opt_out_at_publish", {"removed": 2, "where": "list", "register": "optout"}),
    ]  # by count, never who


def test_counts_leave_out_the_register_and_refusals_lists_also_a_contact_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(optout_mod, "opted_out", lambda url=None, as_of=None: frozenset({"P-OPT"}))
    ctx = _ctx()
    d = decision_of(ctx)
    # OD-8; a contact denial is still counted; an undated refusal is a refusal
    assert d.uncounted() == {"P-OPT", "P-REFUSED", "P-SAMEDAY", "P-UNDATED", "P-UNDATEDOK"}
    everyone = ["P-OPT", "P-REFUSED", "P-NOCONTACT", "P-OK", "P-NEW"]
    assert d.off_lists(everyone, "nav.opt_out_removed") == {"P-OPT", "P-REFUSED", "P-NOCONTACT"}
    assert ctx.audited == [("nav.opt_out_removed", {"removed": 3, "register": "optout", "consent": 2})]


# ------------------------------------------------------------------------------------------------ the paths
def test_nav_leaves_out_the_register_refusals_and_contact_denials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(optout_mod, "opted_out", lambda url=None, as_of=None: frozenset({"P-OPT"}))
    scoped = [{"pid": p} for p in ("P-OPT", "P-REFUSED", "P-NOCONTACT", "P-OK", "P-UNDATED")]
    kept = nav_mod._without_opted_out(_ctx(), scoped)
    assert [r["pid"] for r in kept] == ["P-OK"]  # an undated refusal is off the list


def test_case_makes_no_sheet_for_a_refusal_but_one_for_a_contact_denial() -> None:
    from orchestrator.clients import StepFailed

    ctx = _ctx()
    with pytest.raises(StepFailed, match="opted out"):
        case_mod.refuse_opted_out(ctx, "P-REFUSED")
    case_mod.refuse_opted_out(ctx, "P-NOCONTACT")  # a reading aid for the PI: not a list (D-441)
    case_mod.refuse_opted_out(ctx, "P-OK")
    case_mod.refuse_opted_out(ctx, None)  # an uploaded chart without a chart number


def test_case_makes_no_sheet_when_the_patient_opts_out_while_the_job_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of T-708 (MED 2): the register is read again before the sheet is published. The evaluation can sit
    in an outage wait for hours (T-689); a patient who opted out meanwhile gets no sheet mailed."""
    import inspect

    from orchestrator.clients import StepFailed

    # at receipt nobody is on the register; now P-OK is
    monkeypatch.setattr(
        optout_mod, "opted_out", lambda url=None, as_of=None: frozenset() if as_of else frozenset({"P-OK"})
    )
    ctx = _ctx()
    case_mod.refuse_opted_out(ctx, "P-OK")  # received: a sheet may be made
    with pytest.raises(StepFailed, match="opted out"):
        case_mod.refuse_opted_out_now(ctx, "P-OK")
    case_mod.refuse_opted_out_now(ctx, "P-OTHER")
    case_mod.refuse_opted_out_now(ctx, None)
    assert ctx.audited == [("case.opt_out_at_publish", {"removed": 1, "register": "optout"})]  # by count
    src = inspect.getsource(case_mod.run)
    assert 0 < src.index("refuse_opted_out_now(ctx, subj.pid)") < src.index("ctx.publish(")  # before anything leaves


def test_the_v1_screen_applies_the_consent_rule_of_s0(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal is out of scope and never reaches the evaluator (no model reads the notes); a contact denial is
    evaluated and never listed; the reasons are the cascade's words."""
    asked: list[str] = []

    def evaluate_scope(ctx: Any, rs: Any, run_date: date, snap: str, scoped: list[Any], **kw: Any) -> Any:
        asked.extend(s.pid for s in scoped)
        return {s.pid: PatientVerdicts(s.pid, [], "high", [], 0) for s in scoped}

    monkeypatch.setattr(screen_mod, "evaluate_scope", evaluate_scope)
    scoped = [screen_mod.Scoped(p, None, None, None) for p in ("P-REFUSED", "P-NOCONTACT", "P-OK", "P-UNDATED")]
    res = screen_mod.screen_v1(_ctx(), RS, RUN, "2026-10-05", scoped, None)
    assert asked == ["P-NOCONTACT", "P-OK"]
    assert {p: pv.tier for p, pv in res.items()} == {
        "P-REFUSED": "excluded", "P-NOCONTACT": "excluded", "P-OK": "high", "P-UNDATED": "excluded",
    }  # fmt: skip
    assert res["P-REFUSED"].actions == [REFUSED_REASON] and res["P-NOCONTACT"].actions == [NO_CONTACT_ACTION]
    assert {v.verdict for v in res["P-REFUSED"].verdicts} == {"unknown"}  # nothing was evaluated


# ------------------------------------------------------------------------------------------------ the note-block
def _model(name: str) -> Any:
    return SimpleNamespace(model=name, base_url=f"http://{name}/v1", gateway=None, served_root=name)


def test_the_note_block_is_decided_once_and_can_only_be_withdrawn(monkeypatch: pytest.MonkeyPatch) -> None:
    judge: Any = SimpleNamespace(llm=_model("judge-a"), verifier=_model("verifier-b"))
    d = DecisionContext(_ctx())
    assert d.note_block(judge).may_block
    monkeypatch.setenv("TB_NOTE_BLOCK", "never")  # withdrawn during the job
    assert not d.note_block(judge).may_block
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")  # never granted again on this job
    nb = d.note_block(judge)
    assert not nb.may_block and nb.policy == "never"
    assert DecisionContext(_ctx()).note_block(judge).may_block  # the next job decides for itself


def test_one_model_never_excludes_and_a_caller_without_a_job_gets_the_rule() -> None:
    single: Any = SimpleNamespace(llm=_model("judge-a"), verifier=None)
    d = DecisionContext(_ctx())
    assert not d.note_block(single).may_block and not d.note_block(None).may_block
    assert not note_block_of(single).may_block
    pair: Any = SimpleNamespace(llm=_model("judge-a"), verifier=_model("verifier-b"))
    assert note_block_of(pair).may_block and note_block_of(pair, _ctx()).may_block


def test_the_threshold_is_the_rulesets_else_the_sites_else_the_default() -> None:
    """(Until the review of T-708 this test also read ``pins()`` and ``fingerprint()``: methods no path called.
    They are removed with the claim that the ruleset is read through the context; D-477 names what is left.)"""
    assert DecisionContext(_ctx()).threshold(RS) == 0.75
    assert not hasattr(DecisionContext, "fingerprint") and not hasattr(DecisionContext, "pins")
