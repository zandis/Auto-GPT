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
from typing import Any, ClassVar

import pytest
from criteria_compiler.semantics import codes_settle, demographic_alone, met_on_demographics
from orchestrator.scenarios.evaluate import NoteJudge, NoteResult, coded_settles, evaluate_patients
from tb_common.ruleset import Ruleset
from tb_contracts import Atom, BoolExpr, CriterionIR, PatientEvaluation

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
INDEX = date(2026, 10, 5)
AGE = Atom.model_validate({"domain": "demographic", "valueset": "NONE", "quantifier": "any", "age": {"min": 18.0}})
FEMALE = Atom(domain="demographic", valueset="NONE", quantifier="any", sex="female")
GOUT = Atom(domain="condition", valueset="VS_GOUT", quantifier="any")
NO_GOUT = Atom(domain="condition", valueset="VS_GOUT", quantifier="none")  # "no gout record"


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
    assert demographic_alone(c.logic) is not settles  # these five: the age or sex alone or with a disease
    assert codes_settle(c) is settles
    ev = PatientEvaluation(pid="p", index_date=INDEX, engine="sql", results={c.id: True})
    assert coded_settles(c, ev) is settles


def _b(op: str, *args: Atom | BoolExpr) -> BoolExpr:
    return BoolExpr(op=op, args=list(args))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("logic", "settles"),
    [
        # the lane J review: an "or" let the age through (codes_settle said yes while the age alone made it true)
        (_b("or", AGE, GOUT), False),
        (_b("or", AGE, _b("not", GOUT)), False),
        (_b("or", _b("and", AGE, FEMALE), GOUT), False),
        (_b("not", AGE), False),  # "under 18": an age alone, written negated
        (_b("and", AGE, _b("or", FEMALE, GOUT)), False),
        (_b("and", _b("or", AGE, GOUT), GOUT), True),  # gout is needed whatever the age
        (_b("and", AGE, _b("not", _b("not", GOUT))), True),
        (_b("or", _b("and", AGE, GOUT), _b("and", FEMALE, GOUT)), True),
        (_b("not", GOUT), True),  # no age or sex in it: D-98 as before
        # the second review: a "none" atom is true on an absent record, so it adds nothing to the age
        (_b("and", AGE, NO_GOUT), False),
        (_b("and", AGE, _b("not", NO_GOUT)), True),  # "not none": the record must be there
        (_b("or", _b("and", AGE, NO_GOUT), GOUT), False),
        (_b("and", AGE, NO_GOUT, GOUT), True),
        (_b("and", FEMALE, _b("or", NO_GOUT, GOUT)), False),
        (NO_GOUT, True),  # no age or sex in it: D-98 as before
    ],
)
def test_nestings_of_and_or_and_not(logic: BoolExpr, settles: bool) -> None:
    assert met_on_demographics(logic) is not settles
    assert codes_settle(_crit("inclusion", logic, "a line")) is settles
    assert codes_settle(_crit("exclusion", logic, "a line"))  # exclusions exactly as before


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


# ------------------------------------------------------------------- the other readers of a coded mixed answer
def _rs_with(c: CriterionIR) -> Ruleset:
    return replace(GZQO, criteria=[c if x.id == c.id else x for x in GZQO.criteria])


class _SqlEngine:
    values: ClassVar[dict[str, bool | None]] = {}

    def __init__(self, lake: Any) -> None:
        pass

    def evaluate(self, rs: Ruleset, pids: list[str], today: date, ids: list[str]) -> dict[str, PatientEvaluation]:
        return {p: PatientEvaluation(pid=p, index_date=today, engine="sql", results=dict(self.values)) for p in pids}


@pytest.mark.parametrize(
    ("logic", "coded", "verdict", "state"),
    [
        (AGE, True, "unknown", "needs"),  # was "met, coded" on the age alone
        (FEMALE, True, "unknown", "needs"),  # the pregnancy line kept as "female"
        (AGE, False, "unknown", "needs"),  # D-98: codes that do not show a mixed line leave it to the notes
        (GOUT, True, "met", "ready"),  # codes that cover the line still settle it
        (GOUT, False, "unknown", "needs"),  # was "not met": not eligible on silent codes
    ],
)
def test_the_site_patient_check_never_meets_a_mixed_inclusion_on_its_age_or_sex(
    monkeypatch: pytest.MonkeyPatch, logic: Atom, coded: bool, verdict: str, state: str
) -> None:
    from orchestrator.scenarios import evaluate
    from sitesetup import readiness

    c = _crit("inclusion", logic, "18 years or older with a clinical or genetic diagnosis of FAP")
    rs = _rs_with(c)
    others = {x.id: x.kind == "inclusion" for x in rs.active() if f'"C_{x.id}"' in rs.sql}
    monkeypatch.setattr(_SqlEngine, "values", {**others, c.id: coded})
    monkeypatch.setattr(evaluate, "SqlEngine", _SqlEngine)
    svc = SimpleNamespace(
        store=SimpleNamespace(facts=lambda ws: [{"pid": "P1"}], inputs=lambda ws, kind: []),
        lake=lambda ws: SimpleNamespace(snapshot=lambda: "s1"),
    )
    (p,) = readiness.patient_check(svc, "ws", rs, INDEX)  # type: ignore[arg-type]
    row = next(r for r in p["criteria"] if r["id"] == c.id)
    assert row["verdict"] == verdict and p["state"] == state
    assert row["reason"] == ("coded" if verdict == "met" else "not_evaluated")


class _Tables:
    def table(self, c: Any, rs_id: str) -> dict[tuple[int | None, str], Any]:
        return {(age, sex): age >= 18 for age in range(0, 111) for sex in ("male", "female", "")}


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"verdict": "pass", "basis": "coded"}, "not_evaluated"),  # P2b's "pass, coded" on the age: open now
        ({"verdict": "pass", "basis": "pair", "quote": "FAP confirmed"}, "pass"),  # the notes' answer stands
        ({"verdict": "pass", "basis": "single", "quote": "FAP confirmed"}, "pass"),  # a one-model note answer too
    ],
)
def test_the_replay_decides_such_a_line_as_the_engine_does(stored: dict[str, Any], expected: str) -> None:
    from tools.public_accuracy.rerun import Recompiled, rescreen

    c = _crit("inclusion", AGE, "18 years or older with a clinical or genetic diagnosis of FAP")
    rs = SimpleNamespace(sql=f'"C_{c.id}"', active=lambda: [c])
    draft = {"id": c.id, "kind": "inclusion", "class": "mixed", "text": c.text, "logic": AGE.model_dump()}
    answers = {"gzqo": {"draft": [draft], "patients": {"P1": {"verdicts": [{"id": c.id, **stored}]}}}}
    out = rescreen(answers, {"gzqo": Recompiled("GZQO", "compiled", rs=rs)}, _Tables(), {"P1": "M1"},  # type: ignore[arg-type]
                   {"M1": (40, "female")})  # fmt: skip
    (v,) = out.answers["gzqo"]["patients"]["P1"]["verdicts"]
    assert v["verdict"] == expected
    # the same line as a structured age line is still decided by the age table
    s = c.model_copy(update={"class_": "structured"})
    rs_s = SimpleNamespace(sql=f'"C_{s.id}"', active=lambda: [s])
    out = rescreen(answers, {"gzqo": Recompiled("GZQO", "compiled", rs=rs_s)}, _Tables(), {"P1": "M1"},  # type: ignore[arg-type]
                   {"M1": (40, "female")})  # fmt: skip
    assert out.answers["gzqo"]["patients"]["P1"]["verdicts"][0] == {
        "id": c.id, "verdict": "pass", "basis": "coded", "quote": None
    }  # fmt: skip


def test_the_candidate_workbook_says_the_notes_decide_such_a_line() -> None:
    import io

    from openpyxl import load_workbook
    from orchestrator.reports import candidate_xlsx

    from tests.unit.test_feas_unit import META as FEAS_META

    fap = _crit("inclusion", AGE, "18 years or older with a clinical or genetic diagnosis of FAP")
    gout = _crit("inclusion", GOUT, "Diagnosis of gout").model_copy(update={"id": "GZQO-INC-02"})
    rs = replace(GZQO, criteria=[{fap.id: fap, gout.id: gout}.get(c.id, c) for c in GZQO.criteria])
    wb = load_workbook(io.BytesIO(candidate_xlsx.render([], rs, FEAS_META, {}, {})))
    how = {str(r[0]): str(r[5]) for r in wb["criteria"].iter_rows(min_row=2, values_only=True)}
    assert how[fap.id].startswith("the notes: Is it so: 18 years") and "coded data first" not in how[fap.id]
    assert how[gout.id].startswith("coded data first: ")  # a line its codes settle reads as before
