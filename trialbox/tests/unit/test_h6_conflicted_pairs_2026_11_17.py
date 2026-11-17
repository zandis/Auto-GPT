"""Card H-6 (lane H, 2026-11-17): a pair whose own labels contradict each other is set aside and listed (D-1064).

Key v2 marks a pair ``conflicted`` when its label is eligible while the same physicians' criterion labels for that
pair exclude the patient; it is never relabelled and key v1 keeps its bytes. The scorer reads the target without the
marked pairs, beside the figure with them, and lists each with what the box answered; a marked pair the box excluded on
a line the labels do not exclude on is a finding to trace. All data here is synthetic (made up in this file), apart
from the P1b slice of card H-4's tests (public SIGIR 2016, NCBI, ``eval/criterion_ml/LICENSE.NCBI``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_h2_answer_key_versions import REF, _en_bundle
from tools.public_accuracy import key, score, sets, site

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / "tests" / "fixtures" / "public_accuracy_p1b" / "replay_slice.json"
MANIFEST = ROOT / "eval" / "public_accuracy_key" / "MANIFEST.json"
SITE_KEY = b"synthetic-site-key-for-h6-tests"


def _pair(p: str, t: str, label: str, mrn: str) -> dict[str, Any]:
    return {"patient": p, "trial": t, "label": label, "mrn": mrn, "ruleset": f"R{t}", "stratum": f"x-{label}"}


def _crit(p: str, t: str, kind: str, label: str, text: str, mrn: str) -> dict[str, Any]:
    return {"patient": p, "trial": t, "kind": kind, "label": label, "text": text, "mrn": mrn, "ruleset": f"R{t}"}


PAIRS = [
    _pair("p1", "T1", "eligible", "1"),  # inclusion not included: conflicted
    _pair("p2", "T1", "eligible", "2"),  # exclusion excluded: conflicted
    _pair("p3", "T1", "eligible", "3"),  # labels agree: not marked
    _pair("p4", "T1", "would_consider", "4"),  # would consider: never marked (does not claim every criterion met)
    _pair("p5", "T1", "excluded", "5"),  # excluded with an excluding label: no conflict
    _pair("p6", "T1", "eligible", "6"),  # conflicted; the box leaves it open
]
CRITS = [
    _crit("p1", "T1", "inclusion", "not included", "Aged 40 years or older", "1"),
    _crit("p1", "T1", "exclusion", "not excluded", "Pregnancy", "1"),
    _crit("p2", "T1", "exclusion", "excluded", "Renal disease", "2"),
    _crit("p3", "T1", "inclusion", "included", "Aged 40 years or older", "3"),
    _crit("p4", "T1", "exclusion", "excluded", "Renal disease", "4"),
    _crit("p5", "T1", "exclusion", "excluded", "Renal disease", "5"),
    _crit("p6", "T1", "exclusion", "excluded", "Pregnancy", "6"),
]


# ---------------------------------------------------------------- the rule, read from the gold alone
def test_the_rule_marks_eligible_pairs_whose_own_criterion_labels_exclude() -> None:
    marks = key.conflicted(PAIRS, CRITS)
    assert [(m["patient"], m["trial"]) for m in marks] == [("p1", "T1"), ("p2", "T1"), ("p6", "T1")]
    assert marks[0]["excluding"] == [{"kind": "inclusion", "label": "not included", "text": "Aged 40 years or older"}]
    assert all(m["why"] == "D-1064" and m["label"] == "eligible" for m in marks)
    # one definition: the scorer's S1 reading is the key's
    assert score.criterion_says_excluded(CRITS) == key.criterion_says_excluded(CRITS)
    assert set(key.EXCLUDING) == score.BLOCK_RIGHT
    assert key.CONFLICT_LABELS == ("eligible",)
    assert key.MARKS_CONFLICTED == {"v1": False, "v2": True}


def test_the_p1b_slice_marks_the_infants_pair_by_the_same_rule() -> None:
    s = json.loads(SLICE.read_text(encoding="utf-8"))["sets"]["sigir"]
    marks = key.conflicted(s["pairs"], s["criteria"])
    assert [(m["patient"], m["trial"]) for m in marks] == [("sigir-201418", "NCT01260883")]
    assert marks[0]["excluding"][0]["text"].startswith("Renal or hepatic disease")


def test_the_manifest_lists_p1bs_six_marks_with_the_reason() -> None:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = m["versions"]["v2"]["launch_p1b_rows_that_change"]["sigir"]["conflicted"]
    assert [(r["patient"], r["trial"]) for r in rows] == [
        ("sigir-201410", "NCT02097186"),
        ("sigir-201413", "NCT00163709"),
        ("sigir-201418", "NCT01260883"),
        ("sigir-20142", "NCT00711399"),
        ("sigir-201425", "NCT00282269"),
        ("sigir-201429", "NCT00703417"),
    ]
    assert all(r["why"] == "D-1064" and r["label"] == "eligible" for r in rows)
    assert "finding to trace" in next(r for r in rows if r["patient"] == "sigir-201418")["p1b_box"]
    assert m["versions"]["v2"]["what"] == key.KEYS["v2"] and "conflicted" in key.KEYS["v2"]


# ---------------------------------------------------------------- the builder and key-diff
def _build(out: Path, version: str) -> Path:
    def placed(lo: Any, hi: Any, sex: Any, inc: Any) -> Any:
        return sets.placed_lines(lo, hi, sex, inc, version)

    b = _en_bundle(placed)
    # syn-3 is eligible for NCT90000003 (made up): its exclusion "Asthma" is labelled excluded, a conflict
    b.criteria.append(sets.CriterionGold("syn-3", "NCT90000003", "exclusion", "Asthma", "excluded", [0], "sigir-c"))
    site.build(b, out, ref=REF, key=version)
    return out


def test_a_v2_build_writes_the_marks_and_v1_writes_none(tmp_path: Path) -> None:
    v1, v2 = _build(tmp_path / "v1", "v1"), _build(tmp_path / "v2", "v2")
    assert not (v1 / "gold" / key.CONFLICTED_FILE).exists()
    marks = json.loads((v2 / "gold" / key.CONFLICTED_FILE).read_text(encoding="utf-8"))
    assert [(m["patient"], m["trial"]) for m in marks] == [("syn-3", "NCT90000003")]
    # never relabelled: the pair rows are the same bytes in both versions
    assert (v1 / "gold" / "pairs.jsonl").read_bytes() == (v2 / "gold" / "pairs.jsonl").read_bytes()
    assert key.conflicted_of(v1) == {"marks": None, "from": "key v1 marks no conflicted pair"}
    assert key.conflicted_of(v2)["marks"] == marks
    (v2 / "gold" / key.CONFLICTED_FILE).unlink()  # a v2 folder without the file: the same rule, computed
    got = key.conflicted_of(v2)
    assert got["marks"] == marks and got["from"].startswith("computed by the rule")


def test_key_diff_lists_the_conflicted_mark_as_a_v1_to_v2_difference(tmp_path: Path) -> None:
    v1, v2 = _build(tmp_path / "v1", "v1"), _build(tmp_path / "v2", "v2")
    d = key.diff(v1, v2)
    rows = [r for r in d["rows"] if r["why"].startswith("D-1064")]
    assert d["counts"]["conflicted"] == 1 and len(rows) == 1
    r = rows[0]
    assert (r["patient"], r["ruleset"], r["old"], r["new"]) == (
        "syn-3",
        "NCT90000003",
        "eligible",
        "eligible, conflicted",
    )
    assert "exclusion excluded: Asthma" in r["what"]


# ---------------------------------------------------------------- the scorer
def _answers() -> dict[str, Any]:
    def pid(mrn: str) -> str:
        return score.pid_of(mrn, SITE_KEY)

    draft = [
        {"id": "A", "kind": "inclusion", "text": "Aged 40 years or older", "logic": {"age": {"min": 40}}},
        {"id": "B", "kind": "exclusion", "text": "Renal disease"},
        {"id": "C", "kind": "exclusion", "text": "Pregnancy"},
        {"id": "D", "kind": "inclusion", "text": "Aged 2 months or older", "logic": {"age": {"min": 0.17}}},
    ]
    fail, ok, open_ = "fail", "pass", "pending_human"
    pats = {
        pid("1"): {"tier": "excluded", "verdicts": [{"id": "A", "verdict": fail}]},  # on the line the labels exclude
        pid("2"): {"tier": "excluded", "verdicts": [{"id": "D", "verdict": fail}]},  # on another line: a finding
        pid("3"): {"tier": "excluded", "verdicts": [{"id": "C", "verdict": fail}]},  # a real eligible lost
        pid("4"): {"tier": "review", "verdicts": [{"id": "B", "verdict": ok}]},
        pid("5"): {"tier": "excluded", "verdicts": [{"id": "B", "verdict": fail}]},
        pid("6"): {"tier": "review", "verdicts": [{"id": "C", "verdict": open_}]},
    }
    return {"RT1": {"screen": "done", "outcome": "screened", "draft": draft, "patients": pats}}


IDS = {"set": "sigir", "rulesets": {"T1": "RT1"}, "lang": {"RT1": "en"}}


def test_the_scorer_reads_the_target_without_the_marks_and_lists_each_with_the_boxs_answer() -> None:
    con = {"marks": key.conflicted(PAIRS, CRITS), "from": "test"}
    out = score.score_pairs(IDS, PAIRS, _answers(), SITE_KEY, CRITS, con)
    en = out["summary"]["en"]
    assert (en["eligible_lost"]["k"], en["eligible_lost"]["n"]) == (3, 4)  # the key as published (p1, p2, p3, p6)
    w = en["eligible_lost_without_conflicted"]
    assert (w["k"], w["n"]) == (1, 1) and en["conflicted_pairs"] == 3  # p3 alone
    rows = {r["patient"]: r for r in out["conflicted"]["pairs"]}
    assert set(rows) == {"p1", "p2", "p6"} and out["conflicted"]["from"] == "test"
    assert rows["p1"]["box"] == "excluded" and rows["p1"]["blocked_on"] == ["Aged 40 years or older"]
    assert rows["p1"]["on_an_excluding_line"] is True and rows["p1"]["on_another_line"] is False
    assert rows["p1"]["excluding"] == ["inclusion not included: Aged 40 years or older"]
    assert rows["p2"]["box"] == "excluded" and rows["p2"]["on_another_line"] is True
    assert rows["p6"]["box"] == "review" and rows["p6"]["left_open_on"] == ["Pregnancy"]
    assert rows["p6"]["on_an_excluding_line"] is None and rows["p6"]["on_another_line"] is False
    # the guard: an exclusion on a line the physicians did not label as excluding is listed, never set aside silently
    assert [(r["patient"], r["blocked_on"]) for r in out["conflicted_excluded_on_another_line"]] == [
        ("p2", ["Aged 2 months or older"])
    ]


def test_a_key_that_marks_nothing_keeps_the_report_as_it_was() -> None:
    out = score.score_pairs(IDS, PAIRS, _answers(), SITE_KEY, CRITS, {"marks": None, "from": "v1"})
    assert "conflicted" not in out and "eligible_lost_without_conflicted" not in out["summary"]["en"]
    assert out["label_conflicts"]["pairs"] == 3 and score.SCHEMA_VERSION == 3


def test_the_drivers_score_summary_names_the_conflicted_pairs(tmp_path: Path) -> None:
    from tools import box_run

    built = _build(tmp_path / "acc" / "sigir" / "built", "v2")
    (built.parent / "work").mkdir()
    (built.parent / "work" / "answers.json").write_text("{}", encoding="utf-8")
    summ = box_run.acc_score(tmp_path)["sigir"]["summary"]
    assert [(c["patient"], c["trial"], c["box"]) for c in summ["conflicted"]] == [
        ("syn-3", "NCT90000003", "not answered")
    ]
    assert summ["conflicted_excluded_on_another_line"] == []
