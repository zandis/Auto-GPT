"""Lind's metric on our whole system (card R1-L0; tools/public_accuracy/lind.py): the label mapping row by row, the
agreement over all (patient, criterion) pairs, overall, coded alone, notes alone and per language with the number of
pairs, the decided share and the false-block rate, and the gold's hash. Synthetic rows only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_h3_scorer_2026_11_17 import _tcga_built, _write
from tools.public_accuracy import lind, score, sets
from tools.public_accuracy import score as sc

MET, NOT_MET, UND = lind.MET, lind.NOT_MET, lind.UNDETERMINED


def _v(verdict: str, basis: str = "coded", reason: str = "", quote: str = "", **kw: Any) -> dict[str, Any]:
    return {"id": "c", "verdict": verdict, "basis": basis, "reason": reason, "quote": quote, **kw}


# -------------------------------------------------------------------------------------------------- the mapping
@pytest.mark.parametrize(
    ("kind", "row", "label"),
    [
        # a coded rule decides
        ("inclusion", _v("pass"), MET),
        ("inclusion", _v("fail"), NOT_MET),
        ("exclusion", _v("fail"), MET),  # an exclusion that fails: its condition is present
        ("exclusion", _v("pass"), NOT_MET),
        # the model pair agrees, with a quote
        ("inclusion", _v("pass", "pair", "note", "had gout"), MET),
        ("exclusion", _v("fail", "pair", "note", "pregnant"), MET),
        ("inclusion", _v("fail", "pair", "note", "no gout"), NOT_MET),
        # everything else is not determinable
        ("inclusion", _v("unknown"), UND),
        ("inclusion", _v("pending_human", "person"), UND),
        ("inclusion", _v("pass", "single", "single_model", "q"), UND),
        ("inclusion", _v("pass", "person"), UND),
        ("inclusion", _v("pass", "pair", "disagree", "q"), UND),
        ("inclusion", _v("pass", "pair", "suspected_diagnosis", "suspected gout"), UND),
        ("inclusion", _v("fail", "pair", "not_final", "q", final=False), UND),
        ("inclusion", _v("pass", "pair", "note", ""), UND),  # a note answer with no quote
        ("inclusion", _v("pass", "pair", "note", "   "), UND),
        ("inclusion", _v("pass", "coded", "data_gap"), UND),
        ("renewal", _v("pass"), UND),
        ("inclusion", None, UND),
    ],
)
def test_the_box_answer_maps_to_a_label_as_the_table_says(kind: str, row: dict[str, Any] | None, label: str) -> None:
    assert lind.box_label(kind, row) == label


def test_the_golds_labels_map_and_no_information_is_not_determinable() -> None:
    assert lind.gold_label("inclusion", "included") == MET
    assert lind.gold_label("inclusion", "not included") == NOT_MET
    assert lind.gold_label("exclusion", "excluded") == MET
    assert lind.gold_label("exclusion", "not excluded") == NOT_MET
    for kind in ("inclusion", "exclusion"):
        assert lind.gold_label(kind, "not enough information") == UND
        assert lind.gold_label(kind, "not applicable") == UND


# -------------------------------------------------------------------------------------------------- the agreement
def _crit(mrn: str, rs: str, kind: str, label: str, text: str) -> dict[str, Any]:
    return {"mrn": mrn, "ruleset": rs, "kind": kind, "label": label, "text": text}


def _case() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    ids = {"lang": {"E1": "en", "J1": "ja"}}
    crits = [
        _crit("a", "E1", "inclusion", "included", "Gout"),  # coded, box met: agrees
        _crit("b", "E1", "inclusion", "not included", "Gout"),  # coded, box met: disagrees
        _crit("c", "E1", "exclusion", "not excluded", "Pregnancy"),  # note, box fail (blocks): a false block
        _crit("a", "E1", "exclusion", "excluded", "Pregnancy"),  # note, box unknown vs gold met: disagrees
        _crit("d", "E1", "inclusion", "not enough information", "Gout"),  # gold not determinable, box coded met
        _crit("a", "J1", "inclusion", "included", "痛風"),  # ja, note, pair agrees
        _crit("b", "J1", "inclusion", "included", "痛風"),  # ja, patient not answered
        _crit("a", "Z9", "inclusion", "included", "Gout"),  # a protocol the box did not compile
    ]
    pid = {m: score.pid_of(m) for m in "abcd"}
    answers = {
        "E1": {
            "draft": [
                {"id": "i", "kind": "inclusion", "class": "structured", "text": "Gout"},
                {"id": "x", "kind": "exclusion", "class": "note", "text": "Pregnancy"},
            ],
            "patients": {
                pid["a"]: {"verdicts": [{**_v("pass"), "id": "i"}, {**_v("unknown", "pair"), "id": "x"}]},
                pid["b"]: {"verdicts": [{**_v("pass"), "id": "i"}]},
                pid["c"]: {"verdicts": [{**_v("fail", "pair", "note", "pregnant"), "id": "x"}]},
                pid["d"]: {"verdicts": [{**_v("pass"), "id": "i"}]},
            },
        },
        "J1": {
            "draft": [{"id": "j", "kind": "inclusion", "class": "note", "text": "痛風"}],
            "patients": {pid["a"]: {"verdicts": [{**_v("pass", "pair", "note", "痛風あり"), "id": "j"}]}},
        },
    }
    return ids, crits, answers


def test_agreement_overall_coded_notes_and_per_language_each_with_its_pairs() -> None:
    ids, crits, answers = _case()
    r = lind.score_lind(ids, crits, answers)
    # eight pairs; agreeing: (a,E1 inc), (a,J1 inc). Disagreeing: the other six
    assert (r["overall"]["pairs"], r["overall"]["agree"]) == (8, 2) and r["overall"]["agreement"] == 0.25
    # coded (structured) rows: E1 inclusions a, b, d: a agrees, b disagrees, d disagrees (gold not determinable)
    assert (r["coded"]["pairs"], r["coded"]["agree"]) == (3, 1)
    # note rows: E1 exclusions c and a, J1 inclusions a and b: J1 a agrees; c, a, b disagree
    assert (r["note"]["pairs"], r["note"]["agree"]) == (4, 1)
    assert r["unclassified_pairs"] == 1  # the protocol the box did not compile has no class
    en, ja = r["by_language"]["en"], r["by_language"]["ja"]
    assert (en["overall"]["pairs"], en["overall"]["agree"]) == (5, 1)
    assert (en["coded"]["pairs"], en["note"]["pairs"]) == (3, 2)
    assert (ja["overall"]["pairs"], ja["overall"]["agree"]) == (2, 1)
    assert (ja["coded"]["pairs"], ja["note"]["pairs"], ja["note"]["agree"]) == (0, 2, 1)
    assert r["by_language"]["?"]["overall"]["pairs"] == 1  # the language of the uncompiled protocol is not known


def test_a_not_determinable_answer_against_a_decided_gold_is_a_disagreement_and_the_reverse_too() -> None:
    ids, crits, answers = _case()
    c = lind.score_lind(ids, crits, answers)["confusion"]
    assert c["gold met / box not determinable"] >= 2  # (a, E1 exclusion) and the unanswered ja patient
    assert c["gold not determinable / box met"] == 1  # d: the gold had no information, the box said met
    assert sum(c.values()) == 8


def test_the_decided_share_and_the_false_block_are_reported_with_the_agreement() -> None:
    ids, crits, answers = _case()
    r = lind.score_lind(ids, crits, answers)
    # decided by the box (met or not met): a/E1 inc, b/E1 inc, c/E1 exc, d/E1 inc, a/J1: five of eight
    assert (r["decided_share"]["k"], r["decided_share"]["n"]) == (5, 8)
    # gold keeps the patient: inclusion met (a/E1, a/J1, b/J1, a/Z9) and exclusion not met (c): box says fail on c only
    assert (r["false_block"]["k"], r["false_block"]["n"]) == (1, 5)
    assert r["not_answered"] == {"patient not answered": 1, "not compiled": 1}


def test_the_mapping_is_declared_provisional_until_the_paper_is_read() -> None:
    r = lind.score_lind(*_case())
    assert r["provisional"] is True and "paper" in r["provisional_because"]
    assert UND in r["mapping"].values() and MET in r["mapping"].values()


def test_the_labels_hash_is_the_golds_alone_and_changes_with_a_label() -> None:
    ids, crits, answers = _case()
    h = lind.labels_sha256(crits)
    assert h == lind.score_lind(ids, crits, answers)["labels_sha256"] and len(h) == 64
    assert lind.labels_sha256(list(reversed(crits))) == h  # the order of the rows does not matter
    changed = [{**crits[0], "label": "not included"}, *crits[1:]]
    assert lind.labels_sha256(changed) != h
    answers["E1"]["patients"] = {}  # the answers are not in the hash
    assert lind.labels_sha256(crits) == h


def test_a_run_with_no_gold_rows_has_no_figure_and_no_division_by_zero() -> None:
    r = lind.score_lind({"lang": {}}, [], {})
    assert r["overall"]["pairs"] == 0 and r["overall"]["agreement"] is None and r["by_language"] == {}


def test_the_score_of_a_run_carries_the_figure_beside_the_others(tmp_path: Path) -> None:
    built, ids = _tcga_built(tmp_path)
    pid = {r: score.pid_of(ids["patients"][r]) for r in ("r1", "r2", "r3", "r4")}
    cid = "GM2TCGA-BRCA-INC-01"
    draft = [{"id": cid, "kind": "inclusion", "class": "mixed", "text": sets.TCGA_CRITERIA["TCGA-BRCA"]}]
    work = _write(
        tmp_path,
        {
            "Gm2TCGA-BRCA": {
                "screen": "done",
                "draft": draft,
                "patients": {
                    pid["r1"]: {"verdicts": [{**_v("pass"), "id": cid}]},  # gold included: met against met
                    pid["r2"]: {"verdicts": [{**_v("fail"), "id": cid}]},  # included in the gold: not met against met
                    pid["r3"]: {"verdicts": [{**_v("fail"), "id": cid}]},  # not included: not met, agrees
                    pid["r4"]: {"verdicts": [{**_v("unknown"), "id": cid}]},
                },
            },
            "Gm2TCGA-LUAD": {"outcome": "not_run_time_budget"},
        },
    )
    out = score.score(built, work)
    assert out["schema_version"] == sc.SCHEMA_VERSION == 6
    li = out["lind"]
    assert li["provisional"] is True and li["overall"]["pairs"] == 8  # 4 reports, 2 protocols
    assert out["criteria"]["rows_in_gold"] == li["overall"]["pairs"]  # the same gold rows, the same count
    assert li["not_answered"]["not compiled"] == 4  # the protocol that did not run
