"""The cascade's own exclusion-path rules, one test per rule (D-276; safety review S-3, S-10).

The review removed each of these rules in turn and every test stayed green: the stub judge always answers at
confidence 0.9 with a quote that verifies, the same under every model name. Here a scripted judge
(``tests/judge_kit.py``) gives the contested answers, on a small lake, with no database. Each test has a positive
control (the same patient *is* excluded when the answer is clean), so it fails when the rule is removed and also
when exclusion stops working.

Rule -> test (the mutation table is in the pull request of D-276):

* confidence floor (``_map``)                      -> test_a_not_met_below_the_confidence_floor_is_unknown
* unverified quote is unknown (``_map``, CAS-16)   -> test_a_not_met_whose_quote_does_not_verify_is_unknown
* S4 disagreement                                  -> test_a_second_opinion_that_differs_makes_the_pair_unknown
* no note in the window                            -> test_no_note_in_the_window_is_a_data_gap_never_an_exclusion
* S2b below, inclusion                             -> test_an_inclusion_below_the_semantic_threshold_is_unknown
* no embedder, never absence semantics             -> test_without_an_embedder_a_zero_hit_pair_goes_to_the_judge
* index sweep in SCREEN                            -> test_an_absent_index_condition_goes_to_review_in_a_screening_run
* consent table error                              -> test_a_consent_table_error_stops_the_run
* excerpt budget left evidence out (S-10)          -> test_not_met_is_not_final_when_the_budget_left_evidence_out
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from criteria_compiler.terminology.mapper import Concept, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.cascade import engine
from matching.cascade.engine import EXCERPT_TOKENS, CascadeConfig, CascadeResult, run_cascade
from matching.cascade.judge import JudgeReply, expected_tokens
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_common.reasons import code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

from tests.judge_kit import ScriptedJudge, note_criterion, note_lake, quoting, reply, ruleset

IDX = date(2026, 10, 5)
SNAP = "2026-10-05"
FLARE = "Acute gout flare of the right toe"
FILLER = "Routine follow-up, vitals stable, no change in plan.\n" * 75  # about 1,000 tokens
INC = note_criterion("T-INC-02", "inclusion", "Gout flare in the past year", "Did the patient have a gout flare?")
EXC = note_criterion("T-EXC-01", "exclusion", "Known HIV infection", "Does the patient have HIV infection?")
# R22-17 (D-1069; ruled on #639 7079180333): an inclusion "not met" from the notes no longer excludes, so the controls
# "a clean, sure not met excludes" are this note exclusion whose quote states its condition, with the inclusion case
# beside each asserting review
EXC_FLARE = note_criterion("T-EXC-03", "exclusion", "Gout flare in the past year", "Did the patient have a gout flare?")
LEXICON = {INC.id: ["flare"], EXC.id: ["hiv"], "T-INC-09": ["gout"], EXC_FLARE.id: ["flare"]}
PATIENTS: dict[str, list[tuple[date, str]]] = {
    "P-HIT": [(date(2026, 9, 20), f"{FLARE}\nColchicine started")],
    "P-NONE": [],
    "P-QUIET": [(date(2026, 9, 20), "Routine visit\nBlood pressure stable")],
    # six long notes, each with the evidence sentence: only two fit the excerpt budget
    "P-MANY": [(date(2026, 9, d), f"{FLARE}\n{FILLER} Visit {d}.") for d in range(1, 7)],  # distinct (D-905)
}


# the site codes its diagnoses in ICD-10-CM (one coded row, another condition): a gout code could be there (D-795)
CODED = [{"resourceType": "Condition", "id": "c-htn", "subject": {"reference": "Patient/P-HIT"},
          "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10"}]},
          "onsetDateTime": "2025-01-10"}]  # fmt: skip


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return note_lake(tmp_path_factory.mktemp("exclusion-rules"), PATIENTS, SNAP, CODED)


@pytest.fixture(scope="module")
def uncoded_lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return note_lake(tmp_path_factory.mktemp("exclusion-rules-uncoded"), PATIENTS, SNAP)


def _run(lake: Any, rs: Ruleset, pids: list[str], judge: Any, embedder: Any = "hash", **kw: Any) -> CascadeResult:
    cfg = CascadeConfig(
        study_id="T",
        run_date=IDX,
        lookback_months=36,
        index_mode="single",
        purpose="screening",
        step_id="t",
        snapshot=SNAP,
        population=pids,
        language="en",
        **{"note_block": True, "absence_semantics": False, "lexicon": LEXICON, **kw},
    )
    emb = HashEmbedder() if embedder == "hash" else embedder
    return run_cascade(lake, rs, cfg, judge=judge, embedder=emb, reviewer=None)


def _excluded_at_s3(res: CascadeResult, pid: str, cid: str) -> bool:
    t = res.traces[pid]
    return t.exit_stage == "S3" and t.tier == "excluded" and t.outcomes[cid].hard and t.exit_criterion == cid


def _kept_for_review(res: CascadeResult, pid: str, cid: str) -> bool:
    t = res.traces[pid]
    o = t.outcomes[cid]
    return t.exit_stage is None and t.tier == "potential:uncertain" and o.status == "unknown" and not o.hard


def _excludes_on_a_stated_flare(lake: Any, **kw: Any) -> bool:
    """The control: a clean, sure note answer that excludes (an exclusion whose quote states its condition)."""
    res = _run(lake, ruleset([EXC_FLARE]), ["P-HIT"], ScriptedJudge(quoting("pass", FLARE)), **kw)
    return _excluded_at_s3(res, "P-HIT", EXC_FLARE.id)


def _inclusion_not_met_reviewed(res: CascadeResult, rs: Ruleset, pid: str = "P-HIT") -> bool:
    """The inclusion case beside it: the same clean, sure "not met" on the note inclusion is a soft fail and review."""
    t = res.traces[pid]
    o = t.outcomes[INC.id]
    return (o.status, o.hard) == ("fail", False) and t.exit_stage is None and verdicts_of(rs, t).tier == "review"


class Orthogonal:
    """An embedder for which no sentence is near the question (cosine 0)."""

    model = "orthogonal-test"

    def embed(self, texts: list[str]) -> list[list[float]]:
        notes = {s for _, text in PATIENTS["P-QUIET"] for s in text.split("\n")}
        return [[0.0, 1.0] if t in notes else [1.0, 0.0] for t in texts]


# ------------------------------------------------------------------------------------------------ _map
def test_a_not_met_below_the_confidence_floor_is_unknown(lake: LakeLocal) -> None:
    rs = ruleset([INC])
    assert _excludes_on_a_stated_flare(lake, confidence_floor=0.75)  # control: a clean, confident answer does exclude
    sure = _run(lake, rs, ["P-HIT"], ScriptedJudge(quoting("fail", FLARE, 0.95)), confidence_floor=0.75)
    assert _inclusion_not_met_reviewed(sure, rs)
    unsure = _run(lake, rs, ["P-HIT"], ScriptedJudge(quoting("fail", FLARE, 0.74)), confidence_floor=0.75)
    assert _kept_for_review(unsure, "P-HIT", INC.id)
    assert unsure.traces["P-HIT"].outcomes[INC.id].reason == "abstained"
    assert verdicts_of(rs, unsure.traces["P-HIT"]).tier == "review"


@pytest.mark.parametrize(
    ("quote", "quote_date"),
    [
        ("A sentence that is in no note of this patient", "2026-09-20"),  # not in the excerpts
        (FLARE, "2026-09-19"),  # the right words under another day's date
        (None, None),  # no quote at all
    ],
)
def test_a_not_met_whose_quote_does_not_verify_is_unknown(lake: LakeLocal, quote: str | None, quote_date: str | None) -> None:  # fmt: skip
    rs = ruleset([INC])
    assert _excludes_on_a_stated_flare(lake)  # control
    assert _inclusion_not_met_reviewed(_run(lake, rs, ["P-HIT"], ScriptedJudge(quoting("fail", FLARE))), rs)
    res = _run(lake, rs, ["P-HIT"], ScriptedJudge(lambda role, kw: reply("fail", 0.95, quote, quote_date)))
    assert _kept_for_review(res, "P-HIT", INC.id)
    assert res.traces["P-HIT"].outcomes[INC.id].reason == "insufficient"
    assert verdicts_of(rs, res.traces["P-HIT"]).tier == "review"


# ------------------------------------------------------------------------------------------------ S4
def test_a_second_opinion_that_differs_makes_the_pair_unknown(lake: LakeLocal) -> None:
    rs = ruleset([INC])
    agree = _run(lake, rs, ["P-HIT"], ScriptedJudge(quoting("pass", FLARE)))
    assert agree.traces["P-HIT"].tier == "strong" and agree.metrics.pairs_judged == {"S3": 1, "S4": 1}

    def script(role: str, kw: dict[str, Any]) -> JudgeReply:
        return quoting("pass" if role == "judge" else "fail", FLARE)(role, kw)

    res = _run(lake, rs, ["P-HIT"], ScriptedJudge(script))
    o = res.traces["P-HIT"].outcomes[INC.id]
    assert (o.status, o.stage, o.reason) == ("unknown", "S4", "S3/S4 disagree")
    assert res.traces["P-HIT"].tier == "potential:uncertain"  # not a strong candidate, and not excluded
    assert res.stage("S4").detail["disagreements"] == 1


# ------------------------------------------------------------------------------------------------ S2 / S2b
def test_no_note_in_the_window_is_a_data_gap_never_an_exclusion(lake: LakeLocal) -> None:
    rs = ruleset([INC])
    judge = ScriptedJudge(quoting("fail", FLARE))
    res = _run(lake, rs, ["P-HIT", "P-NONE"], judge)
    assert _excludes_on_a_stated_flare(lake)  # control
    assert _inclusion_not_met_reviewed(res, rs)
    t = res.traces["P-NONE"]
    o = t.outcomes[INC.id]
    assert (o.status, o.stage, o.unknown_kind, o.hard) == ("unknown", "S2", "data_gap", False)
    assert t.exit_stage is None and t.tier == "potential:data_gap" and res.metrics.pairs_s2_no_notes == 1
    assert verdicts_of(rs, t).tier == "review"


def test_an_inclusion_below_the_semantic_threshold_is_unknown(lake: LakeLocal) -> None:
    """Feasibility (``absence_semantics``): nothing near the question in the notes. The exclusion criterion passes
    (absence), the inclusion is unknown and the patient stays (independent review 2026-10-27, finding 6)."""
    rs = ruleset([INC, EXC])
    judge = ScriptedJudge(quoting("fail", FLARE))
    res = _run(lake, rs, ["P-QUIET"], judge, embedder=Orthogonal(), absence_semantics=True)
    t = res.traces["P-QUIET"]
    inc, exc = t.outcomes[INC.id], t.outcomes[EXC.id]
    assert (inc.status, inc.stage, inc.unknown_kind, inc.hard) == ("unknown", "S2b", "uncertain", False)
    assert (exc.status, exc.stage) == ("pass", "S2b")
    assert t.exit_stage is None and t.tier == "potential:uncertain"
    assert res.metrics.pairs_s2b_below == 2 and judge.calls == []


def test_without_an_embedder_a_zero_hit_pair_goes_to_the_judge(lake: LakeLocal) -> None:
    """No semantic screen on the box: "nothing found" was never checked, so it is never taken as absence."""
    rs = ruleset([INC])
    judge = ScriptedJudge(quoting("pass", "Routine visit"))
    res = _run(lake, rs, ["P-QUIET"], judge, embedder=None, absence_semantics=True)
    assert ("judge", INC.text) in judge.calls
    assert res.metrics.pairs_s2b_below == 0 and res.metrics.pairs_s2b_above == 1
    assert res.traces["P-QUIET"].outcomes[INC.id].stage in ("S3", "S4")


def _index_ruleset() -> tuple[Ruleset, CriterionIR]:
    icd = "http://hl7.org/fhir/sid/icd-10-cm"
    c = CriterionIR.model_validate(
        {
            "id": "T-INC-09",
            "ruleset": "T",
            "kind": "inclusion",
            "class": "structured",
            "text": "Diagnosis of gout",
            "logic": {"domain": "condition", "valueset": "VS_GOUT"},
        }
    )
    vs = {"VS_GOUT": valueset("T", "VS_GOUT", "gout", [Concept(icd, "M10", "Gout")], "1.0.0")}
    return ruleset([c], vs), c


def test_an_absent_index_condition_goes_to_review_in_a_screening_run(lake: LakeLocal, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The study's own disease, not coded and not found in the notes. A feasibility count drops the patient
    (absence); a screening run (``absence_semantics=False``) keeps them for a person to check."""
    rs, c = _index_ruleset()
    monkeypatch.setattr(engine, "is_index_criterion", lambda crit: crit.id == c.id)
    kw: dict[str, Any] = {"embedder": Orthogonal(), "semantics": "affirmative"}
    feas = _run(lake, rs, ["P-QUIET"], None, absence_semantics=True, **kw)
    assert feas.traces["P-QUIET"].exit_stage == "S2b" and feas.traces["P-QUIET"].tier == "excluded"  # control
    res = _run(lake, rs, ["P-QUIET"], None, absence_semantics=False, **kw)
    t = res.traces["P-QUIET"]
    o = t.outcomes[c.id]
    assert t.exit_stage is None and (o.status, o.hard) == ("unknown", False) and "review" in o.reason
    assert t.tier == "potential:data_gap" and verdicts_of(rs, t).tier == "review"


def test_an_index_condition_no_row_can_carry_is_never_excluded_on_absence(
    uncoded_lake: LakeLocal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F11 (D-795): a site with no coded diagnosis at all. The notes are still read for the study's own disease, but
    finding nothing there is no absence: no code could have been there. Even a feasibility count keeps the patient."""
    from matching.carried import NOT_CARRIED

    rs, c = _index_ruleset()
    monkeypatch.setattr(engine, "is_index_criterion", lambda crit: crit.id == c.id)
    kw: dict[str, Any] = {"embedder": Orthogonal(), "semantics": "affirmative"}
    feas = _run(uncoded_lake, rs, ["P-QUIET"], None, absence_semantics=True, **kw)
    t = feas.traces["P-QUIET"]
    o = t.outcomes[c.id]
    assert t.exit_stage is None and (o.status, o.hard) == ("unknown", False) and NOT_CARRIED in o.reason
    assert t.tier != "excluded"


# ------------------------------------------------------------------------------------------------ S0
class _ConsentFails:
    """The lake, with the consent query failing as given."""

    def __init__(self, inner: Any, error: Exception) -> None:
        self.inner, self.error = inner, error

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        if "FROM consent" in sql:
            raise self.error
        return self.inner.query(sql, params, snapshot)


class _NoConsentTable(_ConsentFails):
    """A lake that has no consent table: the registry query fails and the lake answers 0 to "is there one"."""

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        from tb_common import lakeprobe

        if sql == lakeprobe.table_sql("consent"):
            import pyarrow as pa

            return pa.table({"n": [0]})
        return super().query(sql, params, snapshot)


def test_a_consent_table_error_stops_the_run(lake: LakeLocal) -> None:
    """Opt-outs are never skipped: only a lake with no consent table at all has none to apply (D-127). Whether
    it has none is asked of the lake (D-651): until then an error whose text said so was enough, on a lake that
    has the table, and the run went on with no opt-out applied."""
    rs = ruleset([INC])
    judge = ScriptedJudge(quoting("pass", FLARE))
    said = RuntimeError("Catalog Error: Table with name consent does not exist!")
    assert _run(_NoConsentTable(lake, said), rs, ["P-HIT"], judge).traces["P-HIT"].in_scope  # control: no table
    with pytest.raises(RuntimeError, match="Catalog Error"):  # the same words from a lake that has the table
        _run(_ConsentFails(lake, said), rs, ["P-HIT"], judge)
    with pytest.raises(RuntimeError, match="503"):
        _run(_ConsentFails(lake, RuntimeError("lake error 503: backend unavailable")), rs, ["P-HIT"], judge)


def test_on_a_production_box_a_lake_without_a_consent_table_stops_the_cascade(
    lake: LakeLocal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-654 (the owner's decision): the control above is a TEST box. On PRODUCTION a snapshot without the table
    was not built by this software, and the cascade does not run on it with no opt-out applied."""
    from tb_common.optout import NoRegistryTable

    rs = ruleset([INC])
    judge = ScriptedJudge(quoting("pass", FLARE))
    said = RuntimeError("Catalog Error: Table with name consent does not exist!")
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    with pytest.raises(NoRegistryTable, match="no consent table"):
        _run(_NoConsentTable(lake, said), rs, ["P-HIT"], judge)
    assert _run(lake, rs, ["P-HIT"], judge).traces["P-HIT"].in_scope  # a snapshot that has the table: as on any box


# ------------------------------------------------------------------------------------------------ S-10
def test_not_met_is_not_final_when_the_budget_left_evidence_out(lake: LakeLocal) -> None:
    """Six notes hold the evidence sentence and two fit the excerpt budget. Both models read the same two, so their
    "not met" says nothing about the other four: unknown, a person looks. A "met" answer still stands."""
    rs = ruleset([INC])
    seen: list[int] = []

    def fail(role: str, kw: dict[str, Any]) -> JudgeReply:
        seen.append(len(kw["excerpts"]))
        assert expected_tokens(kw["excerpts"]) - 300 <= EXCERPT_TOKENS
        return quoting("fail", FLARE)(role, kw)

    res = _run(lake, rs, ["P-HIT", "P-MANY"], ScriptedJudge(fail))
    assert _excludes_on_a_stated_flare(lake)  # control: every evidence note was shown
    assert _inclusion_not_met_reviewed(res, rs)
    assert sorted(seen) == [1, 2]  # P-MANY: two of six notes
    assert _kept_for_review(res, "P-MANY", INC.id)
    why = res.traces["P-MANY"].outcomes[INC.id].reason
    assert why.startswith("not judged: 4 note(s) of the window") and code_of(why, "unknown") == "notes_over_budget"
    assert verdicts_of(rs, res.traces["P-MANY"]).tier == "review"
    met = _run(lake, rs, ["P-MANY"], ScriptedJudge(quoting("pass", FLARE)))
    assert met.traces["P-MANY"].outcomes[INC.id].status == "pass"
    # T-603 (CR-004 flag half): the "met" answer stands, but the candidate carries the flag and is never "strong"
    assert met.traces["P-MANY"].notes_over_budget == [INC.id] and met.metrics.notes_over_budget == 1
    assert met.traces["P-MANY"].tier == "potential:uncertain"
    assert code_of(met.traces["P-MANY"].outcomes[INC.id].reason, "pass") == "notes_over_budget"


def test_an_exclusion_criterion_met_on_part_of_the_evidence_is_not_final_either(lake: LakeLocal) -> None:
    exc = note_criterion("T-EXC-02", "exclusion", "Gout flare in the past year", "Did the patient have a gout flare?")
    rs = ruleset([exc])
    kw: dict[str, Any] = {"lexicon": {exc.id: ["flare"]}}
    res = _run(lake, rs, ["P-HIT", "P-MANY"], ScriptedJudge(quoting("pass", FLARE)), **kw)
    assert _excluded_at_s3(res, "P-HIT", exc.id)
    assert _kept_for_review(res, "P-MANY", exc.id)


# ------------------------------------------------------------------------------- BENCH-2 §2: a demoter, never a veto
def _disputed(kept: str) -> Any:
    """The product pair's reply when the verifier answered otherwise: the plain rule's unknown, carrying the judge's
    own (never affirmed) answer as ``kept``."""

    def script(role: str, kw: dict[str, Any]) -> JudgeReply:
        k = quoting(kept, FLARE)(role, kw)
        ops = [{"role": "judge", "verdict": kept, "quote": k.quote, "quote_date": k.quote_date},
               {"role": "verifier", "verdict": "unknown", "quote": None, "quote_date": None}]  # fmt: skip
        return replace(reply("unknown", 0.0), reason="disagree", opinions=ops, kept=replace(k, affirmed=False))

    return script


def test_bench2_the_cascade_keeps_a_disputed_keep_flagged_and_never_excludes_on_a_disputed_answer(lake: Any) -> None:
    met = _run(lake, ruleset([INC]), ["P-HIT"], ScriptedJudge(_disputed("pass"))).traces["P-HIT"].outcomes[INC.id]
    assert met.status == "pass" and met.reason == "second_opinion_differs"
    assert [o["role"] for o in met.evidence[-1]["opinions"]] == ["judge", "verifier"]
    res = _run(lake, ruleset([EXC_FLARE]), ["P-HIT"], ScriptedJudge(_disputed("pass")))  # "present": not a keep
    o = res.traces["P-HIT"].outcomes[EXC_FLARE.id]
    assert o.status == "unknown" and o.reason == "disagree" and not _excluded_at_s3(res, "P-HIT", EXC_FLARE.id)
