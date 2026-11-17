"""Card H-3 (lane H, 2026-11-17): the scorer scores tcga (the PoC-1 pathology figure) and counts the protocols that
fail before or in SCREEN as their own line (D-1107); a set with nothing screened or no verdict is "not scored", by
name (D-1108); S1 and S3/S4 read from the stored answers of launch P1b.

Synthetic data, except ``tests/fixtures/public_accuracy/p1b_sigir_outcomes.json``: launch P1b's stored job states and
errors of the SIGIR 2016 set (NCBI, eval/criterion_ml/LICENSE.NCBI), ids renamed, no patient in it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import score, sets, site

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
P1B = ROOT / "tests" / "fixtures" / "public_accuracy" / "p1b_sigir_outcomes.json"


# ---------------------------------------------------------------- tcga: the pathology figure
def _tcga_built(tmp: Path) -> tuple[Path, dict[str, Any]]:
    """Two of read_tcga's protocols over four made-up reports (two of each type), built for the box with the tag
    ``m2`` (ruleset ids ``Gm2TCGA-BRCA``, ``Gm2TCGA-LUAD``)."""
    b = sets.Bundle("tcga")
    types = {"r1": "TCGA-BRCA", "r2": "TCGA-BRCA", "r3": "TCGA-LUAD", "r4": "TCGA-LUAD"}
    for proj in ("TCGA-BRCA", "TCGA-LUAD"):
        b.trials[proj] = sets.Trial(proj, "en", f"Public test protocol: {proj}", [sets.TCGA_CRITERIA[proj]], [])
    for r, t in types.items():
        b.patients[r] = sets.Patient(r, "en", f"Made-up pathology report of type {t}.")
        for proj in ("TCGA-BRCA", "TCGA-LUAD"):
            lab = "included" if t == proj else "not included"
            b.criteria.append(sets.CriterionGold(r, proj, "inclusion", sets.TCGA_CRITERIA[proj], lab, stratum="tcga"))
            b.pairs.append(sets.Pair(r, proj, "eligible" if lab == "included" else "excluded", stratum="tcga"))
    mrn0, pi0, prefix = site.SET_OFFSETS["tcga"]
    site.build(b, tmp / "built", mrn0=mrn0, pi0=pi0, rs_prefix=prefix + "m2")
    ids = json.loads((tmp / "built" / "gold" / "ids.json").read_text(encoding="utf-8"))
    assert sorted(ids["rulesets"].values()) == ["Gm2TCGA-BRCA", "Gm2TCGA-LUAD"]
    return tmp / "built", ids


def _write(tmp: Path, answers: dict[str, Any]) -> Path:
    (tmp / "work").mkdir(exist_ok=True)
    (tmp / "work" / "answers.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    return tmp / "work"


def _v(cid: str, verdict: str) -> list[dict[str, Any]]:
    return [{"id": cid, "verdict": verdict}]


def test_tcga_scores_the_pathology_figure_as_three_named_numbers(tmp_path: Path) -> None:
    built, ids = _tcga_built(tmp_path)
    pid = {r: score.pid_of(ids["patients"][r]) for r in ("r1", "r2", "r3", "r4")}
    cid = "GM2TCGA-BRCA-INC-01"
    draft = [{"id": cid, "kind": "inclusion", "class": "mixed", "text": sets.TCGA_CRITERIA["TCGA-BRCA"]}]
    work = _write(tmp_path, {
        "Gm2TCGA-BRCA": {"feas": "awaiting_approval", "approve": "done", "screen": "done", "outcome": "screened",
                         "draft": draft, "patients": {
                             pid["r1"]: {"tier": "high", "verdicts": _v(cid, "pass")},
                             pid["r2"]: {"tier": "high", "verdicts": _v(cid, "pass")},
                             pid["r3"]: {"tier": "excluded", "verdicts": _v(cid, "fail")},
                             pid["r4"]: {"tier": "review", "verdicts": _v(cid, "unknown")}}},
        "Gm2TCGA-LUAD": {"outcome": "not_run_time_budget"},
    })  # fmt: skip
    out = score.score(built, work)
    assert out["schema_version"] == score.SCHEMA_VERSION and "not_scored_because" not in out
    p = out["pathology"]
    assert p["scored"] is True and p["protocols_screened"] == ["Gm2TCGA-BRCA"] and p["reports"] == 4
    assert (p["ineligible_excluded"]["k"], p["ineligible_excluded"]["n"]) == (1, 2)
    assert (p["wrong_exclusions"]["k"], p["wrong_exclusions"]["n"]) == (0, 1)
    assert (p["eligible_lost"]["k"], p["eligible_lost"]["n"]) == (0, 2)
    assert p["pairs_unanswered"] == 0  # the LUAD protocol's pairs are not the figure's: it did not screen
    assert out["protocols"]["screened"] == 1 and out["protocols"]["not_run_time_budget"] == 1
    assert out["protocols"]["attempted"] == 1 and out["protocols"]["fewer_than_one_in_ten_failed"] is True


def test_the_poc1_pathology_figure_comes_out_as_stated() -> None:
    """PoC-1 on b266f9b7: "on 500 public pathology reports the pair excluded 384 of 450, with 0 wrong exclusions,
    and lost 0 of 50 eligible patients" (BRCA screened, 1 of 10 protocols; 66 non-breast reports left open)."""
    rss = {f"TCGA-T{i}": f"Gm2TCGA-T{i}" for i in range(10)}
    ids = {"set": "tcga", "rulesets": rss, "lang": dict.fromkeys(rss.values(), "en")}
    mrns = [f"chart-{i}" for i in range(500)]
    pairs = [{"mrn": m, "ruleset": rs, "label": "eligible" if (i < 50) == (rs == "Gm2TCGA-T0") else "excluded"}
             for i, m in enumerate(mrns) for rs in rss.values()]  # fmt: skip
    pats = {}
    for i, m in enumerate(mrns):
        tier, verdict = ("high", "pass") if i < 50 else ("excluded", "fail") if i < 434 else ("review", "unknown")
        pats[score.pid_of(m)] = {"tier": tier, "verdicts": _v("c1", verdict)}
    answers = {"Gm2TCGA-T0": {"screen": "done", "outcome": "screened", "patients": pats}}
    p = score.score_pathology(ids, pairs, answers)
    assert p["figure"] == (
        "on 500 public pathology reports (1 of 10 protocols screened) the pair excluded 384 of 450, with 0 wrong "
        "exclusions, and lost 0 of 50 eligible patients"
    )
    assert p["ineligible_excluded"] == score.rate(384, 450) and p["eligible_lost"] == score.rate(0, 50)
    assert p["wrong_exclusions"] == score.rate(0, 384) and p["left_open"]["k"] == 66


def test_tcga_with_the_wrong_ruleset_prefix_is_not_scored_by_name(tmp_path: Path) -> None:
    """Launch P1b: tag m2 makes the id Gm2TCGA-BRCA; a run under G2TCGA-BRCA screened nothing of the set."""
    built, _ = _tcga_built(tmp_path)
    work = _write(tmp_path, {"G2TCGA-BRCA": {"screen": "done", "outcome": "screened", "patients": {}}})
    out = score.score(built, work)
    p = out["pathology"]
    assert p["scored"] is False and p["not_scored_because"].startswith("0 of 2 protocols screened")
    assert "G2TCGA-BRCA" in p["not_scored_because"] and "prefix" in p["not_scored_because"]
    assert out["not_scored_because"].startswith("0 of 2 protocols screened")
    assert out["protocols"]["answers_not_in_the_set"] == ["G2TCGA-BRCA"] and out["protocols"]["not_in_answers"] == 2


def test_a_set_that_did_not_run_or_gave_no_verdict_is_not_scored(tmp_path: Path) -> None:
    built, ids = _tcga_built(tmp_path)
    out = score.score(built, tmp_path / "no-work")  # no answers.json
    assert out["not_scored_because"] == "no answers.json: the set did not run"
    assert out["pathology"]["scored"] is False and out["protocols"]["not_in_answers"] == 2
    pid = score.pid_of(ids["patients"]["r1"])
    work = _write(tmp_path, {"Gm2TCGA-BRCA": {"screen": "done", "outcome": "screened",
                                              "patients": {pid: {"tier": "review", "verdicts": []}}}})  # fmt: skip
    out = score.score(built, work)
    assert "no verdict" in out["not_scored_because"] and out["pathology"]["scored"] is False


# ---------------------------------------------------------------- protocols that fail before SCREEN (D-1107)
def test_p1b_sigir_protocols_by_class_from_the_stored_outcomes() -> None:
    """P1b's record says "63 screened, 27 failed in FEAS, 2 approve failed, 1 FEAS timeout, 10 not run"; the stored
    states say 8 of the 27 passed FEAS and APPROVE and failed in SCREEN. Eight classes, 30 failures of 93 attempted."""
    fx = json.loads(P1B.read_text(encoding="utf-8"))
    ids = {"rulesets": {k: k for k in fx}}
    pr = score.score_protocols(ids, fx)
    assert (pr["in_set"], pr["screened"], pr["not_run_time_budget"], pr["attempted"]) == (103, 63, 10, 93)
    assert (pr["failed_before_screen"], pr["failed_in_screen"], pr["failed"]) == (22, 8, 30)
    assert pr["failed_by_class"] == {
        "feas_equivalence": 14, "feas_ir_extract": 4, "feas_cql_translate": 1, "feas_timeout": 1,
        "approve_failed": 2, "screen_reporting": 3, "screen_running": 4, "screen_judging": 1,
    }  # fmt: skip
    assert pr["failed_share"] == score.rate(30, 93) and pr["failed_before_screen_share"] == score.rate(22, 93)
    assert pr["fewer_than_one_in_ten_failed"] is False
    assert "not_run_time_budget" not in pr["classes"]  # a budget cut is not a failure


@pytest.mark.parametrize(
    ("answer", "want"),
    [
        (None, ("not_in_answers", "not_in_answers")),
        ({"outcome": "not_run_time_budget"}, ("not_run_time_budget", "not_run_time_budget")),
        ({"outcome": "compiled", "feas": "awaiting_approval"}, ("compiled", "compiled")),
        ({"feas": "failed", "feas_error": "equivalence: could not run"}, ("failed_before_screen", "feas_equivalence")),
        (
            {"feas": "failed", "feas_error": {"message": "x"}, "outcome": "failed"},
            ("failed_before_screen", "feas_no_step"),
        ),
        ({"feas": "failed", "outcome": "refused_by_tripwire"}, ("failed_before_screen", "feas_refused_by_tripwire")),
        ({"outcome": "refused_at_intake"}, ("failed_before_screen", "feas_refused_at_intake")),
        ({"feas": "done", "outcome": "feas_done"}, ("failed_before_screen", "feas_ended_done")),
        ({"feas": "compiling", "outcome": "timeout_feas"}, ("failed_before_screen", "feas_timeout")),
        (
            {
                "feas": "awaiting_approval",
                "approve": "failed",
                "approve_error": {"step": "load"},
                "outcome": "approve_failed",
            },
            ("failed_before_screen", "approve_failed"),
        ),
        (
            {"approve": "done", "outcome": "approve_refused_at_intake"},
            ("failed_before_screen", "approve_refused_at_intake"),
        ),
        ({"approve": "done", "outcome": "screen_refused_at_intake"}, ("failed_in_screen", "screen_refused_at_intake")),
        (
            {
                "approve": "done",
                "screen": "failed",
                "screen_error": {"step": "judging"},
                "outcome": "refused_by_gateway",
            },
            ("failed_in_screen", "screen_refused_by_gateway"),
        ),
        (
            {"approve": "done", "screen": "failed", "screen_error": {"step": "running"}},
            ("failed_in_screen", "screen_running"),
        ),
        ({"approve": "done", "screen": "done", "outcome": "screened"}, ("screened", "screened")),
        ({"feas": "awaiting_approval"}, ("unfinished", "feas_awaiting_approval")),
    ],
)
def test_protocol_status_reads_each_driver_outcome(answer: dict[str, Any] | None, want: tuple[str, str]) -> None:
    assert score.protocol_status(answer) == want


def test_pair_and_criterion_rates_account_for_protocols_that_never_screened() -> None:
    ids = {"lang": {"S1": "en", "S2": "en", "S3": "en"}, "rulesets": {"a": "S1", "b": "S2", "c": "S3"}}
    pairs = [{"mrn": "chart-a", "ruleset": "S1", "label": "eligible"},
             {"mrn": "chart-b", "ruleset": "S1", "label": "excluded"},
             {"mrn": "chart-a", "ruleset": "S2", "label": "eligible"},
             {"mrn": "chart-a", "ruleset": "S3", "label": "excluded"}]  # fmt: skip
    crits = [{"mrn": "chart-a", "ruleset": rs, "kind": "exclusion", "label": "not excluded", "text": "Pregnancy"}
             for rs in ("S1", "S2", "S3")]  # fmt: skip
    draft = [{"id": "e1", "kind": "exclusion", "text": "Pregnancy"}]
    answers = {
        "S1": {"screen": "done", "outcome": "screened", "draft": draft,
               "patients": {score.pid_of("chart-a"): {"tier": "high", "verdicts": _v("e1", "pass")}}},
        "S2": {"feas": "failed", "feas_error": {"step": "equivalence"}, "outcome": "failed"},
        "S3": {"outcome": "not_run_time_budget"},
    }  # fmt: skip
    s = score.score_pairs(ids, pairs, answers, crits=crits)["summary"]["en"]
    assert s["eligible_lost"]["n"] == 1 and s["pairs_in_gold"] == 4 and s["unanswered"]["k"] == 3
    assert s["unanswered_by_protocol"] == {"failed_before_screen": 1, "not_run_time_budget": 1,
                                           "screened, the patient not in its SCREEN": 1}  # fmt: skip
    assert "eligible_lost" in s["denominators"]
    c = score.score_criteria(ids, crits, answers)
    assert c["answered"] == 1 and c["rows_in_gold"] == 3
    assert c["not_answered_by_protocol"] == {"failed_before_screen": 1, "not_run_time_budget": 1}


# ---------------------------------------------------------------- S1, S3/S4 against P1b's cases
def test_s1_eligible_lost_on_the_line_the_criterion_labels_exclude() -> None:
    """P1b sigir: of the 4 eligible lost, 3 pairs' own criterion labels exclude, and on 2 the box blocked on that very
    line (the same text, or an age line where the label is on an age statement); the third was blocked on a wrong
    age line while the labels exclude on another criterion."""
    ids = {"lang": {"S1": "en", "S2": "en", "S3": "en", "S4": "en"}}
    pairs = [{"mrn": "chart-a", "ruleset": rs, "label": "eligible"} for rs in ("S1", "S2", "S3", "S4")]
    crits = [
        {"mrn": "chart-a", "ruleset": "S1", "kind": "inclusion", "label": "not included",
         "text": "patients presenting with shortness of breath that are over 40 years old"},
        {"mrn": "chart-a", "ruleset": "S2", "kind": "exclusion", "label": "excluded", "text": "Renal disease"},
        {"mrn": "chart-a", "ruleset": "S3", "kind": "exclusion", "label": "excluded", "text": "Respiratory distress"},
    ]  # fmt: skip
    age: dict[str, Any] = {
        "kind": "inclusion",
        "class": "structured",
        "logic": {"domain": "demographic", "age": {"min": 40}},
    }
    answers: dict[str, dict[str, Any]] = {
        "S1": {"draft": [{"id": "i1", "text": "Aged 40 years or older", **age}]},
        "S2": {"draft": [{"id": "i1", "text": "Aged 0.17 years or older", **age}]},
        "S3": {"draft": [{"id": "x3", "kind": "exclusion", "text": "Respiratory distress"}]},
        "S4": {"draft": [{"id": "i1", "text": "Aged 18 years or older", **age}]},
    }
    for a in answers.values():
        cid = a["draft"][0]["id"]
        a.update(screen="done", patients={score.pid_of("chart-a"): {"tier": "excluded", "verdicts": _v(cid, "fail")}})
    r = score.score_pairs(ids, pairs, answers, crits=crits)
    s = r["summary"]["en"]
    assert s["eligible_lost"]["k"] == 4 and s["eligible_lost_where_the_criterion_labels_exclude"] == 3
    assert s["eligible_lost_on_the_line_the_criterion_labels_exclude"] == 2
    assert {x["ruleset"]: x["agrees_on_the_line"] for x in r["label_conflicts"]["excluded"]} == {
        "S1": True, "S2": False, "S3": True}  # fmt: skip


def test_s3_s4_exclusions_on_lines_no_gold_row_judges_without_written_json() -> None:
    """P1b's gold has no written.json: jmed's 34 patients excluded on the coded "20歳以上" and sigir's age-line
    exclusions are counted from the answers (the drafts and the verdicts) alone."""
    ids = {"lang": {"MHT": "ja", "SP1": "en"}}
    crits = [{"mrn": m, "ruleset": "MHT", "kind": "exclusion", "label": "not excluded", "text": "高血圧症の既往がある患者"}
             for m in ("chart-a", "chart-b", "chart-c")]  # fmt: skip
    pairs = [{"mrn": "chart-d", "ruleset": "SP1", "label": "eligible"}]
    draft_j = [{"id": "inc", "kind": "inclusion", "class": "structured", "text": "20歳以上",
                "logic": {"domain": "demographic", "age": {"min": 20}}},
               {"id": "exc", "kind": "exclusion", "class": "mixed", "text": "高血圧症の既往がある患者"}]  # fmt: skip
    draft_s = [{"id": "age", "kind": "exclusion", "class": "structured", "text": "Age outside of range specified"}]
    answers = {
        "MHT": {"screen": "done", "draft": draft_j, "patients": {
            score.pid_of("chart-a"): {"tier": "excluded", "verdicts": _v("inc", "fail")},
            score.pid_of("chart-b"): {"tier": "excluded", "verdicts": _v("exc", "fail")},
            score.pid_of("chart-c"): {"tier": "high", "verdicts": _v("exc", "pass")}}},
        "SP1": {"screen": "done", "draft": draft_s, "patients": {
            score.pid_of("chart-d"): {"tier": "excluded", "verdicts": _v("age", "fail")}}},
    }  # fmt: skip
    r = score.score_unjudged(ids, pairs, crits, answers)
    assert r["patients_excluded"] == 2
    assert r["summary"]["ja"] == {
        "patients_excluded": 1,
        "gold criterion exclusion not excluded": 1,
        "on an age line": 1,
    }
    assert r["summary"]["en"] == {"patients_excluded": 1, "gold eligible": 1, "on an age line": 1}
    rows = {x["ruleset"]: x for x in r["rows"]}
    assert rows["MHT"]["line"] == "20歳以上" and rows["MHT"]["written_by_the_benchmark"] is None
    w = score.score_unjudged(ids, pairs, crits, answers, written={"MHT": ["20歳以上"]})
    assert {x["ruleset"]: x["written_by_the_benchmark"] for x in w["rows"]} == {"MHT": True, "SP1": False}
