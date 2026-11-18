"""Card 10A-2 (plan 10, Track A; review 15 section 2.3 finding 2): a mixed inclusion is never met on one of its parts
alone. In the stored P2b launch 6 of 81 mixed inclusions were answered "met, coded" on an age the line also tied to a
disease ("18 years or older with a clinical or genetic diagnosis of FAP"), the disease never asked. A mixed line's
coded part settles it only when that part is more than an age or a sex; otherwise the notes decide, and with no
answer from them the line is unknown, never met and never excluded. The cascade's own run of the same rule is in
``test_cascade_pipeline.py`` (it needs the synthetic lake)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from criteria_compiler.semantics import codes_settle, demographic_alone
from orchestrator.scenarios.evaluate import NoteJudge, NoteResult, coded_settles, evaluate_patients
from tb_common.ruleset import Ruleset
from tb_contracts import Atom, BoolExpr, CriterionIR, PatientEvaluation

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
INDEX = date(2026, 10, 5)
AGE = Atom.model_validate({"domain": "demographic", "valueset": "NONE", "quantifier": "any", "age": {"min": 18.0}})
FEMALE = Atom(domain="demographic", valueset="NONE", quantifier="any", sex="female")
GOUT = Atom(domain="condition", valueset="VS_GOUT", quantifier="any")


def _crit(kind: str, logic: Atom | BoolExpr, text: str, class_: str = "mixed") -> CriterionIR:
    base = next(c for c in GZQO.active() if c.id == "GZQO-INC-01")
    return base.model_copy(
        update={"kind": kind, "class_": class_, "logic": logic, "text": text, "note_question": f"Is it so: {text}?"}
    )


@pytest.mark.parametrize(
    ("logic", "text", "settles"),
    [
        (AGE, "18 years or older with a clinical or genetic diagnosis of FAP", False),
        (BoolExpr(op="and", args=[AGE, FEMALE]), "Women aged 18 or older with a symptomatic subdural hematoma", False),
        (FEMALE, "Women of childbearing potential with a negative pregnancy test", False),  # pregnancy: never sex
        (GOUT, "Diagnosis of gout", True),
        (BoolExpr(op="and", args=[AGE, GOUT]), "Adults with gout", True),
    ],
)
def test_a_mixed_inclusion_is_settled_by_its_codes_only_when_they_are_more_than_an_age_or_sex(
    logic: Atom | BoolExpr, text: str, settles: bool
) -> None:
    c = _crit("inclusion", logic, text)
    assert demographic_alone(c.logic) is not settles
    assert codes_settle(c) is settles
    ev = PatientEvaluation(pid="p", index_date=INDEX, engine="sql", results={c.id: True})
    assert coded_settles(c, ev) is settles


def test_the_rule_leaves_exclusions_and_structured_lines_alone() -> None:
    # a coded exclusion keeps D-98 (a coded hit settles it); the compiler's qualifier_dropped rule handles the
    # age-or-sex-alone exclusion before it runs. A structured line has no note part to ask
    assert codes_settle(_crit("exclusion", FEMALE, "Pregnant women"))
    assert codes_settle(_crit("inclusion", AGE, "Aged 18 years or older", class_="structured"))
    ev = PatientEvaluation(pid="p", index_date=INDEX, engine="sql", results={"GZQO-INC-01": None})
    assert not coded_settles(_crit("inclusion", GOUT, "Gout"), ev)  # silent codes never settle (D-98)


class _Engine:
    name = "sql"

    def __init__(self, answers: dict[str, dict[str, bool | None]]) -> None:
        self.answers = answers

    def evaluate(self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]) -> dict[str, PatientEvaluation]:
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

    def judge_patient(self, pid: str, c: Any, index_date: date, full: bool = False) -> NoteResult:
        self.asked.append((pid, c.id))
        return NoteResult(self.answer, self.conf, quote="note text", reason="from the notes")


@pytest.mark.parametrize(
    ("logic", "text"),
    [
        (AGE, "18 years or older with a clinical or genetic diagnosis of FAP"),
        (FEMALE, "Women of childbearing potential with a negative pregnancy test"),
    ],
)
def test_the_scenario_path_asks_the_notes_and_answers_unknown_when_they_are_silent(
    monkeypatch: pytest.MonkeyPatch, logic: Atom, text: str
) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    mixed = _crit("inclusion", logic, text)
    rs = replace(GZQO, criteria=[mixed if c.id == mixed.id else c for c in GZQO.criteria])
    eligible: dict[str, bool | None] = {
        c.id: c.kind == "inclusion" for c in rs.active() if c.class_ in ("structured", "mixed")
    }
    judge = _Judge("unknown", 0.2)
    res = evaluate_patients(rs, ["adult"], INDEX, _Engine({"adult": eligible}), judge, 0.75, workers=1)
    assert ("adult", mixed.id) in judge.asked  # the other part is asked, the age or sex true or not
    v = next(v for v in res["adult"].verdicts if v.id == mixed.id)
    assert v.verdict == "unknown"  # never met on the age or the sex
    assert res["adult"].tier != "excluded"  # and an unanswered part never excludes
