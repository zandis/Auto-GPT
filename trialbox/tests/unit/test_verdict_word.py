"""One model's "not met" is never printed, listed or counted as "not met" (review of T-709; D-478).

``matching.decision.answer_of`` decides for a run. Everything that reads a verdict afterwards (the console's fit
line and "why" answer, the two workbooks, the "excluded patients and why" document, the feasibility attrition)
asks ``tb_common.verdict_word.shown_of``, and a test below fails when new code outside the two functions compares
a verdict to "fail" on its own.
"""

from __future__ import annotations

import ast
import io
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openpyxl import load_workbook
from tb_common.reasons import LABELS, Reason
from tb_common.ruleset import Ruleset
from tb_common.verdict_word import held_back, shown_of
from tb_contracts import CandidateRow, CriterionVerdict, Evidence, NavRow

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
NOTE_INC = next(c.id for c in GZQO.active() if c.class_ == "note" and c.kind == "inclusion")
NOTE_EXC = next(c.id for c in GZQO.active() if c.class_ == "note" and c.kind == "exclusion")
CODED_EXC = next(c.id for c in GZQO.active() if c.class_ == "structured" and c.kind == "exclusion")

SINGLE = {"verdict": "fail", "basis": "single", "final": False}
PAIR = {"verdict": "fail", "basis": "pair", "final": True}


def _v(cid: str, **kw: Any) -> CriterionVerdict:
    ev = Evidence(resource_refs=["DocumentReference/D1"], quote="q", quote_date="2026-10-01", confidence=0.95)
    return CriterionVerdict(id=cid, evidence=ev, **kw)


# ------------------------------------------------------------------------------------------------- the function
@pytest.mark.parametrize(
    ("verdict", "shown"),
    [
        (SINGLE, ("unknown", "single_model")),
        ({"verdict": "fail", "basis": "single", "final": True}, ("unknown", "single_model")),  # a forged final
        ({"verdict": "fail", "basis": "pair", "final": False}, ("unknown", "not_final")),  # the gate was shut
        ({"verdict": "fail", "final": False}, ("unknown", "not_final")),  # stored by T-707, before the basis
        (PAIR, ("fail", None)),
        ({"verdict": "fail", "basis": "coded"}, ("fail", None)),
        ({"verdict": "fail", "basis": "person"}, ("fail", None)),
        ({"verdict": "pass", "basis": "single"}, ("pass", None)),
        ({"verdict": "unknown"}, ("unknown", None)),
        ({"verdict": "pending_human"}, ("pending_human", None)),
    ],
)
def test_the_word_shown_for_a_stored_verdict(verdict: dict[str, Any], shown: tuple[str, str | None]) -> None:
    assert shown_of(verdict) == shown
    model = CriterionVerdict(id="X", **verdict)
    assert shown_of(model) == shown  # the model and its JSON read alike
    assert held_back(model) == shown[1]


def test_both_reasons_have_their_words_in_every_language() -> None:
    for code in (Reason.SINGLE_MODEL.value, Reason.NOT_FINAL.value):
        assert set(LABELS[code]) == {"en", "ja", "zh-TW"} and all(LABELS[code].values())


# ------------------------------------------------------------------------------------------------- the console
def test_the_fit_line_does_not_say_not_met_on_one_models_answer() -> None:
    from console.studies import CriterionMeta, fit_facts

    crit = {
        "I1": CriterionMeta("I1", "inclusion", "note", "RA diagnosis"),
        "I2": CriterionMeta("I2", "inclusion", "note", "Active disease"),
        "E1": CriterionMeta("E1", "exclusion", "note", "Current flare"),
    }
    ev = {"quote": "q", "quote_date": "2026-10-01"}
    fit = fit_facts(
        [
            {"id": "I1", **SINGLE, "evidence": ev},
            {"id": "I2", **PAIR, "evidence": ev},
            {"id": "E1", **SINGLE, "evidence": ev},
        ],
        crit,
    )
    assert fit.not_met == ["Active disease"]  # the pair's answer only
    assert fit.open == ["RA diagnosis", "Current flare"]  # one model's answers: open points
    assert fit.note_exclusion == []  # and not "an exclusion found in the notes"


def test_the_why_answer_lists_one_models_answer_as_open_with_its_reason() -> None:
    from console.site_pages import trail_rows

    rows = trail_rows(
        [
            {"id": "I1", **SINGLE, "evidence": {"reason": "note"}},
            {"id": "I2", **PAIR, "evidence": {"reason": "note"}},
            {"id": "I3", "verdict": "unknown", "evidence": {"reason": "low_confidence"}},
        ],
        {"I1": "RA diagnosis", "I2": "Active disease", "I3": "Age"},
    )
    assert rows == [
        {"label": "RA diagnosis", "verdict": "unknown", "reason": "single_model"},
        {"label": "Active disease", "verdict": "fail", "reason": "note"},
        {"label": "Age", "verdict": "unknown", "reason": "low_confidence"},
    ]


# ------------------------------------------------------------------------------------------------- the workbooks
def _cells(data: bytes, sheet: str, column: str) -> list[Any]:
    ws = load_workbook(io.BytesIO(data))[sheet]
    head = [c.value for c in ws[1]]
    i = head.index(column)
    return [r[i].value for r in ws.iter_rows(min_row=2) if r[1].value in ("P1", "P2")]


def test_the_candidate_workbook_does_not_write_fail_for_one_models_answer() -> None:
    from orchestrator.reports import candidate_xlsx

    from tests.unit.test_feas_unit import META

    rows = [
        CandidateRow(pid="P1", tier="review", criteria=[_v(NOTE_EXC, verdict="fail", basis="single", final=False)],
                     actions=[]),
        CandidateRow(pid="P2", tier="excluded", criteria=[_v(NOTE_EXC, verdict="fail", basis="pair", final=True)],
                     actions=[]),
    ]  # fmt: skip
    data = candidate_xlsx.render(rows, GZQO, META, {}, {})
    assert _cells(data, "candidates", f"C_{NOTE_EXC}") == ["unknown", "fail"]


def test_the_nav_workbook_does_not_write_fail_for_one_models_answer() -> None:
    from orchestrator.reports import nav_xlsx

    from tests.unit.test_feas_unit import META

    name = nav_xlsx.SHEETS[0]
    rows = [
        NavRow(pid="P1", criteria=[_v(NOTE_INC, verdict="fail", basis="single", final=False)], missing=[]),
        NavRow(pid="P2", criteria=[_v(NOTE_INC, verdict="fail", basis="pair", final=True)], missing=[]),
    ]
    data = nav_xlsx.render({n: (rows if n == name else []) for n in nav_xlsx.SHEETS}, GZQO, META, {}, {}, {})
    title = load_workbook(io.BytesIO(data)).sheetnames[0]
    assert _cells(data, title, f"C_{NOTE_INC}") == ["unknown", "fail"]


# ------------------------------------------------------------------------------------------------- excluded, and why
def test_the_excluded_document_names_only_the_answers_that_excluded() -> None:
    """A coded exclusion beside one model's note "not met": the page "Excluded patients and why" names the coded
    criterion; the note answer excluded nobody and is not listed as a reason."""
    from orchestrator.scenarios.screen import ScreenRun, excluded_doc

    coded = CriterionVerdict(id=CODED_EXC, verdict="fail", basis="coded", evidence=Evidence(resource_refs=["C/1"]))
    row = CandidateRow(
        pid="P1", tier="excluded", actions=[],
        criteria=[coded, _v(NOTE_EXC, verdict="fail", basis="single", final=False)],
    )  # fmt: skip
    ctx: Any = SimpleNamespace(
        services=SimpleNamespace(lake=SimpleNamespace(query=lambda *a, **k: SimpleNamespace(to_pylist=list)))
    )
    run = ScreenRun(GZQO, date(2026, 10, 5), "2026-10-05", [], {}, [row], [], [], 7, None)
    (out,) = excluded_doc(ctx, run)["rows"]
    assert [c["id"] for c in out["criteria"]] == [CODED_EXC]


# ------------------------------------------------------------------------------------------------- the attrition
def test_the_attrition_keeps_a_patient_whose_only_no_is_one_models() -> None:
    """A soft "not met" of a note stage (CAS-7: not allowed to exclude) is an open cell of the state matrix, so the
    patient stays in the final pool; a hard one leaves it."""
    from deliverables.analytics import final_pool, state_matrix
    from matching.cascade.model import Outcome, PatientTrace

    def trace(pid: str, hard: bool) -> PatientTrace:
        t = PatientTrace(pid, date(2026, 10, 5))
        t.outcomes = {"S": Outcome("S", "pass", "S1"), "N": Outcome("N", "fail", "S3", hard=hard)}
        return t

    traces = {"SOFT": trace("SOFT", False), "HARD": trace("HARD", True)}
    res: Any = SimpleNamespace(
        applied=["S"], note_criteria=["N"], human_criteria=[], traces=traces, in_scope=lambda: list(traces.values())
    )
    sm = state_matrix(res)
    assert sm.get("SOFT", "N") == "unknown:uncertain" and sm.get("HARD", "N") == "fail"
    assert final_pool(sm, res) == ["SOFT"]


# ------------------------------------------------------------------------------------------------- the guard
#: Code that may read a verdict's word on its own: where the rule lives, what writes the word, and what reads a
#: word that already went through the rule. Each with its reason.
ALLOWED: dict[str, str] = {
    "libs/tb_common/verdict_word.py": "the rule for a stored verdict",
    "services/matching/decision.py": "the rule for a run",
    "services/matching/cascade/engine.py": "the cascade's own stages: an Outcome carries `hard`, read with it",
    "services/deliverables/analytics.py": "the state matrix: reads an Outcome with `hard` (a soft fail is open)",
    "services/orchestrator/scenarios/evaluate.py": "writes the word: note_verdict, not_final",
    "services/orchestrator/scenarios/screen_cascade.py": "writes the word, `final` and the basis from an Outcome",
    "services/orchestrator/scenarios/microbatch.py": "reads a stored row to stamp `final: false` on an old fail",
    "services/orchestrator/scenarios/screen.py": "which patients have a coded exclusion (never a note answer)",
    "services/orchestrator/scenarios/case.py": "CASE: the word is the one answer_of gave (its own rows)",
    "services/orchestrator/reports/case_html.py": "prints the word CASE passed through answer_of",
    "services/console/site_pages.py": "reads trail_rows, whose words went through shown_of",
}
#: Comparisons that are not a patient's criterion verdict, or that ask only "was it decided", each named.
OTHER: dict[str, str] = {
    "services/adapter/governance.py": "an equivalence check of a mapping (its own verdict)",
    "services/adapter/pipeline.py": "an equivalence check of a mapping (its own verdict)",
    "libs/tb_contracts/landing.py": "an equivalence check of a mapping (its own verdict)",
    "services/omop/__main__.py": "a data-quality check's status",
    "services/llm_stub/handlers.py": "the shape of a model's answer",
    "services/console/recorded_opinions.py": "the shape of a recorded opinion",
    "services/console/coded_view.py": "whether a coded answer was decided at all (met or not met alike)",
    "services/matching/coded_values.py": "which records to show beside a decided coded answer (met or not met alike)",
    "libs/tb_common/reasons.py": "the label of a reason for a decided answer (met or not met alike)",
}


def _reads_a_fail(tree: ast.AST) -> list[int]:
    """Lines that compare a verdict or a status with "fail", or index a map by a verdict's word."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            parts = [node.left, *node.comparators]
            words = [p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, str)]
            words += [
                e.value
                for p in parts
                if isinstance(p, ast.Tuple | ast.Set | ast.List)
                for e in p.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            src = ast.unparse(node)
            if "fail" in words and ("verdict" in src or "status" in src):
                out.append(node.lineno)
            continue
        index: ast.AST | None = None
        if isinstance(node, ast.Subscript):
            index = node.slice
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            index = node.args[0] if node.args and not isinstance(node.args[0], ast.Constant) else None
        if index is not None:
            src = ast.unparse(index)
            if src.endswith(".verdict") or src in ("verdict", "r['verdict']", "v['verdict']"):
                out.append(node.lineno)
    return sorted(out)


def _stray() -> dict[str, list[int]]:
    hits: dict[str, list[int]] = {}
    for d in ("services", "libs"):
        for p in sorted((ROOT / d).rglob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if "/tests/" in rel or p.name.startswith("test_") or "/.venv/" in rel:
                continue
            lines = _reads_a_fail(ast.parse(p.read_text(encoding="utf-8")))
            if lines:
                hits[rel] = lines
    return hits


def test_no_code_outside_the_rule_reads_a_fail_on_its_own() -> None:
    stray = {rel: lines for rel, lines in _stray().items() if rel not in ALLOWED and rel not in OTHER}
    assert not stray, (
        'a verdict is compared with "fail" outside the one rule (use matching.decision.answer_of for a run, '
        f"tb_common.verdict_word.shown_of for a stored verdict): {stray}"
    )


def test_the_guards_lists_hold_no_stale_line() -> None:
    hits = _stray()
    stale = sorted(rel for rel in {**ALLOWED, **OTHER} if rel not in hits)
    assert not stale, f"no longer compared there: remove the line(s) {stale}"
