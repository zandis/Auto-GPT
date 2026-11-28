"""Pool rows are bound to their criteria version and to the basis of each answer (T-707, D-476).

Review 2026-11-12 (``docs/reviews/2026-11-12-architecture/decision.md``):

* **H3, the amendment case.** A pool row stored under version N-1 was re-tiered under version N without the
  criteria the amendment added, could be ``high``, and was re-stamped. Now it is screened again in full (inside the
  night budget); a row the run does not reach is listed for review with nothing evaluated and keeps its stored
  version.
* **H1, the stored soft fail.** One model's "not met" was stored as a plain ``fail``; the next re-tier, with the
  pair allowed to exclude, excluded the patient. Now the verdict says ``final: false`` and never excludes later.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from matching.cascade.model import Outcome
from orchestrator.scenarios import evaluate, microbatch
from orchestrator.scenarios.evaluate import PatientVerdicts, not_final, row, tier
from orchestrator.scenarios.screen import Scoped
from orchestrator.scenarios.screen_cascade import verdict_of
from tb_contracts import CriterionVerdict, Evidence

from tests.unit.test_microbatch_cadence import FRI, GZQO, _Box, _pool_row, _verdicts

OLD = "0.0.1"  # the version before the amendment
NOTE = next(c for c in GZQO.active() if c.class_ == "note" and c.kind == "exclusion")
THU = "2026-10-08T09:00:00+09:00"
LIST = "candidate_list_GZQO_v" + GZQO.version + ".json"
PAIR = (
    SimpleNamespace(model="judge-a", base_url="http://a/v1", gateway=None, served_root="judge-a"),
    SimpleNamespace(model="verifier-b", base_url="http://b/v1", gateway=None, served_root="verifier-b"),
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    for name in ("TB_SCREEN_JUDGE", "TB_DB_URL", "TB_MODEL_SWAP"):
        monkeypatch.delenv(name, raising=False)


class Box(_Box):
    """The cadence test's box, with pool rows of an older version and a full screen that says ``review``."""

    def __init__(self, *, old: list[str], **kw: Any) -> None:
        super().__init__(**kw)
        for p in self.pool:
            if p["pid"] in old:
                p["version"] = OLD  # stored as fully matched (``high``) against the earlier version
        self.given: list[list[str]] = []

    def run_screen(self, ctx: Any, rs: Any, run_date: date, snapshot: str, select: Any = None,
                   scope: Any = None, given: list[Scoped] | None = None) -> Any:  # fmt: skip
        if given is None:
            return super().run_screen(ctx, rs, run_date, snapshot, select)
        self.given.append([s.pid for s in given])
        vs = _verdicts()
        vs[0] = CriterionVerdict(id=vs[0].id, verdict="unknown", evidence=Evidence(resource_refs=[]))
        rows = [row(PatientVerdicts(s.pid, vs, "review", [], 1), s.next_appointment, "D1", "RHEU",
                    "2026-10-07T03:00:00+09:00") for s in given]  # fmt: skip
        return SimpleNamespace(scoped=given, rows=rows, judging=None)

    def listed(self) -> dict[str, dict[str, Any]]:
        return {r["pid"]: r for r in json.loads(self.published[LIST])["rows"]}


# ------------------------------------------------------------------------------------------------ H3: the amendment
def test_a_pool_row_of_another_version_is_screened_again_not_re_tiered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Version N approved over a pool of version N-1: nobody is ``high`` on criteria they were never evaluated on.
    The old rows go through the full screen (the booked one first), not through the time-sensitive re-check, and
    their pool rows are replaced by the result."""
    box = Box(
        pool=["P-OLD-A", "P-OLD-B", "P-CUR"],
        old=["P-OLD-A", "P-OLD-B"],
        booked={"P-OLD-B": THU, "P-CUR": THU},
        scope=[],
        options={"incident": "0"},  # even with the new-patient screen off
    )
    out = box.go(monkeypatch)
    assert box.given == [["P-OLD-B", "P-OLD-A"]]  # the visit in the window first
    assert box.evaluated == [["P-CUR"]]  # the re-check: rows of the version in force only
    got = box.listed()
    assert got["P-OLD-A"]["tier"] == got["P-OLD-B"]["tier"] == "review"  # the full screen's answer, not the stored high
    assert got["P-CUR"]["tier"] == "high"
    assert set(box.persisted) == {"P-CUR", "P-OLD-A", "P-OLD-B"}
    assert box.delivered == [["P-CUR", "P-OLD-B"]]  # the week's list holds the re-screened booked patient
    ev = box.budget_event()
    assert (ev["rechecked"], ev["version_rescreened"], ev["version_carried"]) == (1, 2, 0)
    assert box.job.metrics.patients_scoped == 3
    assert "screened again" in out.summary_md


def test_a_row_the_budget_does_not_reach_waits_as_review_and_keeps_its_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The night budget leaves room for one re-screen: the other old row is on the list as ``review`` with every
    criterion not evaluated and the reason, is not written to the pool, and the run says how many wait."""
    box = Box(
        pool=["P-OLD-A", "P-OLD-B", "P-CUR"],
        old=["P-OLD-A", "P-OLD-B"],
        booked={"P-OLD-B": THU, "P-CUR": THU},
        scope=[Scoped("P-NEW", FRI, "D1", "RHEU")],
        budget=2,  # one re-check, one re-screen, nothing left for new patients
    )
    out = box.go(monkeypatch)
    assert box.given == [["P-OLD-B"]]
    assert box.screened == []  # the new patient carries over too
    got = box.listed()
    waiting = got["P-OLD-A"]
    assert waiting["tier"] == "review"
    assert {v["verdict"] for v in waiting["criteria"]} == {"unknown"}
    assert {v["evidence"]["reason"] for v in waiting["criteria"]} == {"not_evaluated"}
    assert waiting["n_unknown"] == len(waiting["criteria"]) > 0
    assert OLD in waiting["actions"][0] and GZQO.version in waiting["actions"][0]
    assert "P-OLD-A" not in box.persisted  # the pool row keeps version N-1 until it is screened again
    ev = box.budget_event()
    assert (ev["version_rescreened"], ev["version_carried"], ev["new_carried"]) == (1, 1, 1)
    assert "wait for the next weekly run" in out.summary_md


def test_the_after_ingest_run_lists_an_old_row_for_review_and_screens_nobody_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = Box(pool=["P-OLD-A", "P-CUR"], old=["P-OLD-A"], booked={"P-OLD-A": THU}, scope=[],
              options={"trigger": "ingest"})  # fmt: skip
    box.go(monkeypatch)
    assert box.given == [] and box.persisted == []
    got = box.listed()
    assert got["P-OLD-A"]["tier"] == "review" and got["P-OLD-A"]["n_unknown"] > 0
    assert got["P-CUR"]["tier"] == "high"


# ------------------------------------------------------------------------------------------------ H1: the soft fail
#: a quote that states the note exclusion's condition (a current gout flare). R22-16 (#639 7079180333): the input was
#: the placeholder "q", which states nothing and now goes to review on its own; the pinned "q" cases are below
FLARE = "Acute gout flare of the right first toe since yesterday."


def _note_fail(
    final: bool | None = None, confidence: float = 0.95, quote: str = FLARE, affirmed: bool | None = True
) -> CriterionVerdict:
    """``affirmed``: round 5 (#639 7115208555, 7115258794), both models affirmed the condition (judge v6); a row that
    does not say never excludes (pinned in the control below)."""
    return CriterionVerdict(
        id=NOTE.id,
        verdict="fail",
        evidence=Evidence(resource_refs=["DocumentReference/D1"], quote=quote, confidence=confidence, reason="note"),
        final=final,
        affirmed=affirmed,
    )


def test_the_cascade_stores_a_soft_fail_as_not_final() -> None:
    ev: list[dict[str, Any]] = [{"did": "D1", "quote": "q", "date": "2026-10-01"}, {"call_id": "c", "confidence": 0.95}]
    soft = verdict_of(Outcome(NOTE.id, "fail", "S3", hard=False, evidence=ev, reason="not_met (single model)"))
    hard = verdict_of(Outcome(NOTE.id, "fail", "S3", hard=True, evidence=ev, reason="not_met"))
    met = verdict_of(Outcome(NOTE.id, "pass", "S3", evidence=ev, reason="met"))
    assert (soft.verdict, soft.final) == ("fail", False)
    assert (hard.verdict, hard.final) == ("fail", True)  # it was allowed to exclude, and says so
    assert met.final is None
    coded = verdict_of(Outcome(NOTE.id, "fail", "S1", hard=True, reason="matching record"))
    assert coded.final is None and "final" not in coded.model_dump(mode="json", exclude_none=True)


def test_the_v1_evaluator_marks_a_note_fail_of_a_run_that_may_not_exclude() -> None:
    assert not_final(NOTE, _note_fail(), note_block=False).final is False
    assert not_final(NOTE, _note_fail(), note_block=True).final is True
    passed = CriterionVerdict(id=NOTE.id, verdict="pass", evidence=Evidence(resource_refs=[], confidence=0.9))
    assert not_final(NOTE, passed, note_block=False).final is None
    coded = next(c for c in GZQO.active() if c.class_ == "structured")
    fail = CriterionVerdict(id=coded.id, verdict="fail", evidence=Evidence(resource_refs=[]))
    assert not_final(coded, fail, note_block=False).final is None  # a coded answer is final whatever the pair


def test_a_fail_stored_as_not_final_never_excludes_at_a_later_tier() -> None:
    """The run of H1: stored under one model, re-tiered when the pair may exclude."""
    assert tier(GZQO, [_note_fail(final=False)], 0.75, note_block=True)[0] == "review"
    assert tier(GZQO, [_note_fail(final=True)], 0.75, note_block=True)[0] == "review"  # D-1072: a pair's answer too
    assert tier(GZQO, [_note_fail(final=True, affirmed=None)], 0.75, note_block=True)[0] == "review"  # round 5


def _retier(monkeypatch: pytest.MonkeyPatch, stored: CriterionVerdict, stored_tier: str) -> tuple[str, Any]:
    """One pool row of the version in force holding ``stored``; the weekly run with a pair that may exclude and no
    re-check of that criterion (no visit this week). (the tier the run gives, the verdict it lists or None)."""
    box = Box(pool=["P1"], old=[], booked={}, scope=[], options={"incident": "0"})
    box.pool[0]["tier"] = stored_tier
    box.pool[0]["verdicts"] = [
        (stored if v.id == NOTE.id else v).model_dump(mode="json", exclude_none=True) for v in _verdicts()
    ]
    box.ctx.services.llm, box.ctx.services.verifier = PAIR
    seen: list[Any] = []
    real = evaluate.row

    def spy(pv: Any, *a: Any, **kw: Any) -> Any:
        seen.append(pv)
        return real(pv, *a, **kw)

    monkeypatch.setattr(microbatch, "row", spy)
    box.go(monkeypatch)
    (pv,) = seen
    return pv.tier, next(v for v in pv.verdicts if v.id == NOTE.id)


def test_the_weekly_re_tier_never_excludes_on_a_stored_soft_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    pair: Any = SimpleNamespace(llm=PAIR[0], verifier=PAIR[1])
    assert evaluate.effective_note_block(pair)[0]  # the pair may exclude: the stored answer is what holds it back
    t, v = _retier(monkeypatch, _note_fail(final=False), "review")
    assert (t, v.final) == ("review", False)


def test_a_note_fail_stored_before_the_field_never_excludes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row stored before D-476 has no ``final``. Whether a pair gave its note fail cannot be read from the row,
    whatever its tier: it never excludes from here on, and the row says so. A fail written since, that was allowed
    to exclude (``final: true``), still does."""
    for stored_tier in ("review", "excluded"):
        t, v = _retier(monkeypatch, _note_fail(), stored_tier)
        assert (t, v.final) == ("review", False), stored_tier
    t, v = _retier(monkeypatch, _note_fail(final=True), "excluded")
    assert (t, v.final) == ("review", True)  # D-1072 (ring 0): a final pair's fail too, no longer excluded
    t, _ = _retier(monkeypatch, _note_fail(final=True, affirmed=None), "excluded")
    assert t == "review"  # round 5: a row that does not say both models affirmed it


def test_a_pairs_final_fail_on_a_quote_that_states_nothing_is_review_at_a_later_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old input of the two tests above, pinned (R22-16, #639 7079180333): the controls' pair's final fail on
    the placeholder quote "q", which states no condition, is review, at a later tier and in the weekly re-tier."""
    assert tier(GZQO, [_note_fail(final=True, quote="q")], 0.75, note_block=True)[0] == "review"
    t, _v = _retier(monkeypatch, _note_fail(final=True, quote="q"), "excluded")
    assert t == "review"


def test_an_old_excluded_row_whose_coded_exclusion_clears_is_not_excluded_on_one_models_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review's sequence (HIGH 1). A row stored before the field, tier ``excluded`` by a coded, time-sensitive
    criterion, also holds one model's note fail (no ``final``, confidence 0.95). Next week the pair may exclude and
    the re-check finds the coded criterion met. The patient must come back for review: no pair ever gave the note
    answer. Before the fix the row stayed ``excluded`` and was written back so."""
    coded = next(c for c in GZQO.active() if c.time_sensitive and c.class_ == "structured" and c.kind == "exclusion")
    box = Box(pool=["P1"], old=[], booked={"P1": THU}, scope=[], options={"incident": "0"})
    box.pool[0]["tier"] = "excluded"
    stored = {NOTE.id: _note_fail(), coded.id: CriterionVerdict(id=coded.id, verdict="fail",
                                                                evidence=Evidence(resource_refs=["Medication/1"]))}  # fmt: skip
    box.pool[0]["verdicts"] = [stored.get(v.id, v).model_dump(mode="json", exclude_none=True) for v in _verdicts()]
    box.ctx.services.llm, box.ctx.services.verifier = PAIR
    cleared = CriterionVerdict(id=coded.id, verdict="pass", evidence=Evidence(resource_refs=[]))
    box.evaluate_scope = lambda *a, **kw: {"P1": PatientVerdicts("P1", [cleared], "high", [], 0)}  # type: ignore[method-assign]
    box.go(monkeypatch)
    row_ = box.listed()["P1"]
    by = {v["id"]: v for v in row_["criteria"]}
    assert row_["tier"] == "review" and by[coded.id]["verdict"] == "pass"
    assert by[NOTE.id]["verdict"] == "fail" and by[NOTE.id]["final"] is False
    assert box.persisted == ["P1"]  # written back as review, saying whose answer the note fail is


def test_the_pool_row_helper_is_at_the_version_in_force() -> None:
    assert _pool_row("P")["version"] == GZQO.version != OLD
