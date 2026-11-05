"""D-98: ``mixed`` criteria (codes decide when they can, the notes decide the rest) and the polarity check on
exclusion note questions at import."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from criteria_compiler.ir_extract.polarity import is_negated, positive
from criteria_compiler.ir_extract.postprocess import postprocess
from criteria_compiler.review import parse_review_xlsx, review_xlsx, rows
from criteria_compiler.terminology.mapper import Terminology
from openpyxl import load_workbook
from orchestrator.scenarios.evaluate import (
    NoteJudge,
    NoteResult,
    coded_settles,
    evaluate_patients,
    structured_candidate,
    tier,
)
from orchestrator.scenarios.review import check_split
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence, LlmExtractOutput, PatientEvaluation

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
INDEX = date(2026, 10, 5)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Does the patient have no history of tuberculosis?", "Does the patient have a history of tuberculosis?"),
        ("Is there no evidence of active infection?", "Is there evidence of active infection?"),
        ("Has the patient never received a biologic?", "Has the patient ever received a biologic?"),
        ("Is the patient free of malignancy?", "Does the patient have malignancy?"),
        (
            "Is the patient negative for hepatitis B surface antigen?",
            "Is the patient positive for hepatitis B surface antigen?",
        ),
        ("Is the patient not pregnant?", "Is the patient pregnant?"),
    ],
)
def test_negated_exclusion_questions_are_rewritten_to_the_positive(question: str, expected: str) -> None:
    assert is_negated(question)
    assert positive(question) == expected


def test_polarity_leaves_qualifiers_and_other_languages_to_the_reviewer() -> None:
    assert not is_negated("Does the patient have a history of tuberculosis?")
    assert (
        is_negated("Does the patient have active TB not treated?")
        and positive("Does the patient have active TB not treated?") is None
    )
    assert is_negated("患者に結核の既往はないか？") and positive("患者に結核の既往はないか？") is None
    assert is_negated("病人是否沒有結核病史？") and positive("病人是否沒有結核病史？") is None


def _extracted(*crits: dict[str, Any]) -> LlmExtractOutput:
    return LlmExtractOutput.model_validate({"criteria": list(crits)})


def _crit(kind: str, class_: str, question: str | None, text: str = "x") -> dict[str, Any]:
    c: dict[str, Any] = {
        "text": text,
        "kind": kind,
        "class": class_,
        "logic": {"domain": "condition", "concept": "tuberculosis", "quantifier": "any"},
        "concept_candidates": [{"domain": "condition", "name": "tuberculosis"}],
    }
    if question is not None:
        c["note_question"] = question
    return c


def test_postprocess_flags_and_rewrites_negated_exclusions_and_accepts_mixed() -> None:
    post = postprocess(
        "TB",
        _extracted(
            _crit("exclusion", "note", "Does the patient have no history of tuberculosis?"),
            _crit("exclusion", "mixed", "Is the patient not on dialysis for renal failure now?"),
            _crit("exclusion", "note", "Does the patient have active TB not treated?"),
            _crit("inclusion", "mixed", "Do the notes describe a prior gout flare?"),
            _crit("inclusion", "mixed", None),
            _crit("exclusion", "note", "Does the patient have a history of tuberculosis?"),
        ),
        Terminology(),
    )
    c1, c2, c3, c4, c5, c6 = post.criteria
    assert c1.note_question == "Does the patient have a history of tuberculosis?"
    assert c1.note_question_source == "Does the patient have no history of tuberculosis?"
    assert c1.flags is not None and {"needs_review", "negated_question_rewritten"} <= set(c1.flags)
    assert c2.note_question == "Is the patient on dialysis for renal failure now?" and "negated_question_rewritten" in (
        c2.flags or []
    )
    assert c3.flags is not None and "negated_question" in c3.flags and c3.note_question_source is None
    assert c4.class_ == "mixed" and c4.logic is not None and c4.note_question
    assert not {"negated_question", "negated_question_rewritten", "missing_note_question"} & set(c4.flags or [])
    assert c5.flags is not None and "missing_note_question" in c5.flags
    assert c6.note_question_source is None and "negated_question" not in (c6.flags or [])  # positive: untouched
    assert any("rewritten" in w for w in post.warnings) and any("could not be rewritten" in w for w in post.warnings)
    # the reviewer sees both forms and the mixed criterion's two halves in the workbook
    rs = rows(post.criteria, post.valuesets, None)
    assert "rewritten from the negated form" in rs[0]["summary"] and rs[3]["summary"].startswith("Coded data first")
    xlsx = review_xlsx("TB", "0.1.0", 1, "J", post.criteria, post.valuesets, None)
    wb = load_workbook(__import__("io").BytesIO(xlsx))
    ws = wb["review"]
    hdr = [c.value for c in ws[1]]
    r = ws[2]
    r[hdr.index("decision")].value = "edit"
    r[hdr.index("edited_class")].value = "mixed"
    buf = __import__("io").BytesIO()
    wb.save(buf)
    decisions, _ = parse_review_xlsx(buf.getvalue())
    assert decisions[0].edited_class == "mixed"


def _mixed_gzqo() -> Ruleset:
    """GZQO with INC-05 (≥2 flares, note) and EXC-11 (current flare, note) as mixed: both carry a coded proxy."""
    crits = [
        c.model_copy(update={"class_": "mixed"}) if c.id in ("GZQO-INC-05", "GZQO-EXC-11") else c for c in GZQO.criteria
    ]
    return replace(GZQO, criteria=crits)


class _Engine:
    name = "sql"

    def __init__(self, answers: dict[str, dict[str, bool | None]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def evaluate(self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]) -> dict[str, PatientEvaluation]:
        self.asked = list(ids)
        return {
            p: PatientEvaluation(
                pid=p, index_date=index_date, engine="sql", results={i: self.answers[p].get(i) for i in ids}
            )
            for p in pids
        }


class _Judge(NoteJudge):
    def __init__(self, answer: str, conf: float) -> None:
        super().__init__(SimpleNamespace(), SimpleNamespace(model="j"), "judge", verifier=SimpleNamespace(model="v"))  # type: ignore[arg-type]
        self.answer, self.conf = answer, conf
        self.asked: list[tuple[str, str]] = []

    def judge(self, pid: str, c: Any, index_date: date, full: bool = False) -> NoteResult:
        self.asked.append((pid, c.id))
        return NoteResult(self.answer, self.conf, quote="note text", reason="from the notes")


def test_mixed_criterion_is_settled_by_codes_or_handed_to_the_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    rs = _mixed_gzqo()
    structured_true = {c.id: True for c in rs.active() if c.class_ == "structured" and c.kind == "inclusion"}
    structured_true.update({c.id: False for c in rs.active() if c.class_ == "structured" and c.kind == "exclusion"})
    engine = _Engine(
        {
            "coded": {**structured_true, "GZQO-INC-05": True, "GZQO-EXC-11": False},  # codes settle INC-05
            "silent": {**structured_true, "GZQO-INC-05": None, "GZQO-EXC-11": None},  # notes decide both
            "flaring": {**structured_true, "GZQO-INC-05": True, "GZQO-EXC-11": True},  # coded exclusion present
        }
    )
    judge = _Judge("pass", 0.9)
    res = evaluate_patients(rs, ["coded", "silent", "flaring"], INDEX, engine, judge, 0.75, workers=1)
    assert "GZQO-INC-05" in engine.asked and "GZQO-EXC-11" in engine.asked  # mixed logic is compiled and run
    # coded: INC-05 settled by the codes (no model call), EXC-11 silent -> the model was asked once
    assert ("coded", "GZQO-INC-05") not in judge.asked and ("coded", "GZQO-EXC-11") in judge.asked
    inc05 = next(v for v in res["coded"].verdicts if v.id == "GZQO-INC-05")
    assert inc05.verdict == "pass" and (inc05.evidence is None or inc05.evidence.confidence is None)
    # silent: both mixed criteria went to the notes
    assert {("silent", "GZQO-INC-05"), ("silent", "GZQO-EXC-11")} <= set(judge.asked)
    # flaring: the coded exclusion drops the patient before any note is read
    assert res["flaring"].tier == "excluded" and not [a for a in judge.asked if a[0] == "flaring"]
    # a mixed inclusion the codes called false is still a candidate: the notes may show it
    ev = PatientEvaluation(pid="x", index_date=INDEX, engine="sql", results={**structured_true, "GZQO-INC-05": False})
    assert structured_candidate(rs, ev) is True
    assert coded_settles(rs.by_id()["GZQO-INC-05"], ev) is False


def test_mixed_verdict_from_the_notes_follows_the_note_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    rs = _mixed_gzqo()
    base = [
        CriterionVerdict(id=c.id, verdict="pass", evidence=Evidence(resource_refs=[]))
        for c in rs.active()
        if c.class_ == "structured"
    ]
    from_notes = CriterionVerdict(id="GZQO-EXC-11", verdict="fail", evidence=Evidence(resource_refs=[], confidence=0.6))
    from_codes = CriterionVerdict(id="GZQO-EXC-11", verdict="fail", evidence=Evidence(resource_refs=["Condition/1"]))
    monkeypatch.setenv("TB_NOTE_BLOCK", "never")
    assert tier(rs, [*base, from_notes], 0.75)[0] == "review"  # weak, and notes never block on this box
    assert tier(rs, [*base, from_codes], 0.75)[0] == "excluded"  # coded evidence is deterministic
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    strong = CriterionVerdict(id="GZQO-EXC-11", verdict="fail", evidence=Evidence(resource_refs=[], confidence=0.95))
    assert tier(rs, [*base, strong], 0.75, note_block=True)[0] == "excluded"
    assert tier(rs, [*base, strong], 0.75, note_block=False)[0] == "review"


def test_check_split_counts_mixed_criteria() -> None:
    html = (
        "<tr><td>I1</td><td>inclusion</td><td>structured</td></tr>"
        "<tr><td>I2</td><td>inclusion</td><td>mixed</td></tr>"
        "<tr><td>E1</td><td>exclusion</td><td>note</td></tr>"
        "<tr><td>E2</td><td>exclusion</td><td>human</td></tr>"
    )
    line = check_split(html)
    assert "4 criteria" in line and "**1** by the filter first" in line and "**1** by the model" in line
