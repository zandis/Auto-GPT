"""Card H-26 (lane H, 2026-11-17): a stored run's compile report and its concepts' coverage, read offline (plan 8 V4
and V5).

``tools.public_accuracy.compile_report`` prints what the compile of a stored run did (protocols reaching SCREEN,
criteria by class, what went to a person and why), the ``qualifier_dropped`` flags of lane A2's #996 rule on today's
code by compiling again from the run's stored replies, and the concepts' coverage by the mapper with no model. The run
here is made up, in the records' real shape (launch P2b's ``built/gold`` and ``work/``): a synthetic protocol and
made-up replies, no patient data.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import compile_report

pytestmark = pytest.mark.nodb

JOB = "JOB-MADE-1"
RULESET = "RS-MADE"
LINES = [
    {"kind": "inclusion", "text": "Adults with a cough", "source_ref": "Inclusion criteria #1", "parent": None},
    {"kind": "exclusion", "text": "Women who are pregnant", "source_ref": "Exclusion criteria #1", "parent": None},
    {"kind": "exclusion", "text": "In pregnancy and lactation", "source_ref": "Exclusion criteria #2", "parent": None},
    {"kind": "exclusion", "text": "Unable to consent", "source_ref": "Exclusion criteria #3", "parent": None},
]
REPLY = [
    {"text": "Adults with a cough", "source_ref": "Inclusion criteria #1", "kind": "inclusion", "class": "mixed",
     "logic": {"domain": "condition", "concept": "cough"}, "note_question": "Does the patient have a cough?",
     "concept_candidates": [{"domain": "condition", "name": "cough"},
                            {"domain": "observation", "name": "made-up lab zz"}]},
    # the qualifier is a non-demographic concept: #996's rule holds the line
    {"text": "Women who are pregnant", "source_ref": "Exclusion criteria #1", "kind": "exclusion",
     "class": "structured", "logic": {"domain": "demographic", "sex": "female"},
     "concept_candidates": [{"domain": "condition", "name": "pregnancy"}]},
    # the same shape with the qualifiers drafted as demographic candidates (P2b, NCT01863628 EXC-06): the rule reads
    # only the non-demographic ones, so this line keeps its sex-only logic
    {"text": "In pregnancy and lactation", "source_ref": "Exclusion criteria #2", "kind": "exclusion",
     "class": "structured", "logic": {"domain": "demographic", "sex": "female"},
     "concept_candidates": [{"domain": "demographic", "name": "pregnancy"},
                            {"domain": "demographic", "name": "lactation"}]},
    {"text": "Unable to consent", "source_ref": "Exclusion criteria #3", "kind": "exclusion", "class": "human",
     "human_question": "Can the patient consent?", "concept_candidates": []},
]  # fmt: skip
SEX_ONLY = {"domain": "demographic", "quantifier": "any", "sex": "female", "valueset": "NONE"}  # as P2b stored it
STORED_DRAFT = [
    {"id": "RS-MADE-INC-01", "kind": "inclusion", "class": "mixed", "text": "Adults with a cough", "domain": "condition",
     "logic": {"domain": "condition", "quantifier": "any", "valueset": "VS_COUGH"}, "flags": []},
    {"id": "RS-MADE-EXC-01", "kind": "exclusion", "class": "structured", "text": "Women who are pregnant",
     "domain": "demographic", "logic": SEX_ONLY, "flags": ["needs_review"]},
    {"id": "RS-MADE-EXC-02", "kind": "exclusion", "class": "structured", "text": "In pregnancy and lactation",
     "domain": "demographic", "logic": SEX_ONLY, "flags": []},
    {"id": "RS-MADE-EXC-03", "kind": "exclusion", "class": "human", "text": "Unable to consent",
     "domain": "demographic", "logic": None, "flags": ["needs_review"]},
    {"id": "RS-MADE-EXC-04", "kind": "exclusion", "class": "human", "text": "A line the compile could not run",
     "domain": "condition", "logic": None, "flags": ["logic_invalid", "needs_review"]},
]  # fmt: skip


def _trace(prompt: str, role: str, job: str, inp: dict[str, Any], out: Any) -> dict[str, Any]:
    content = "INPUT:\n```json\n" + json.dumps(inp, indent=1) + "\n```"
    return {"attributes": {"tb.prompt": prompt, "tb.role": role, "tb.study_id": job}, "call_id": f"c-{job}",
            "prompt": [{"role": "system", "content": "made up"}, {"role": "user", "content": content}],
            "output": out if isinstance(out, str) else json.dumps(out), "ts": "2026-11-17T08:00:00+00:00"}  # fmt: skip


def make_run(root: Path) -> Path:
    d = root / "set"
    (d / "built" / "gold").mkdir(parents=True)
    (d / "work").mkdir()
    (d / "built" / "gold" / "ids.json").write_text(json.dumps({"set": "made", "patients": {}}))
    answers = {
        RULESET: {"ruleset": RULESET, "feas": "awaiting_approval", "approve": "done", "screen": "done",
                  "outcome": "screened", "draft": STORED_DRAFT},
        "RS-MADE-2": {"ruleset": "RS-MADE-2", "feas": "awaiting_approval", "approve": "done", "screen": "failed",
                      "outcome": "failed", "draft": []},
        "RS-MADE-3": {"ruleset": "RS-MADE-3", "feas": "failed", "approve": None, "screen": None, "outcome": "failed",
                      "draft": []},
    }  # fmt: skip
    (d / "work" / "answers.json").write_text(json.dumps(answers))
    inp = {"ruleset": RULESET, "language": "en", "criteria": LINES}
    traces = [
        _trace("ir_extract@4", "extract_criteria", JOB, inp, {"criteria": REPLY}),
        _trace("ir_extract@4", "extract_criteria", "JOB-MADE-2", {"ruleset": "RS-MADE-2", "criteria": []},
               "not json {"),
    ]  # fmt: skip
    (d / "work" / "raw-traces.json").write_text(json.dumps({"traces": traces}))
    return d


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("h26")
    d = make_run(root)
    made: dict[str, Any] = compile_report.report([d], root / "scratch", index_day=date(2026, 11, 17))["sets"]["made"]
    return made


def test_the_stored_compile_counts_protocols_classes_and_screen(run: dict[str, Any]) -> None:
    st = run["stored"]
    assert st["protocols"] == 3
    assert (st["reached_screen"], st["screened"], st["screen_failed"], st["failed_before_screen"]) == (2, 1, 1, 1)
    assert st["criteria"] == 5
    assert st["by_class"] == {"mixed": 1, "structured": 2, "human": 2}
    assert st["by_kind_class"]["exclusion human"] == 2


def test_why_a_criterion_went_to_a_person(run: dict[str, Any]) -> None:
    st = run["stored"]
    assert st["human"] == 2
    # EXC-03: the run's own ir_extract reply drafted it human; EXC-04: the compile's flag, needs_review left out
    assert st["human_why"] == {compile_report.BY_MODEL: 1, "logic_invalid": 1}
    assert st["human_only_reason"] == {compile_report.BY_MODEL: 1, "logic_invalid": 1}


def test_the_stored_drafts_lines_an_age_or_sex_alone_excludes_on(run: dict[str, Any]) -> None:
    st = run["stored"]
    assert st["qualifier_dropped"] == 0
    assert [e["id"] for e in st["exclusions_demographic_alone"]] == ["RS-MADE-EXC-01", "RS-MADE-EXC-02"]


def test_the_rule_of_996_on_todays_code_from_the_stored_replies(run: dict[str, Any]) -> None:
    rc = run["recompiled"]
    assert rc["status"] == {"compiled": 1, "not_rerun": 1}
    assert rc["not_rerun"][0]["ruleset"] == "RS-MADE-2"
    # only the line whose qualifier is a non-demographic candidate is held; the line whose qualifiers were drafted as
    # demographic candidates is not (what P2b's NCT01863628 EXC-06 shows)
    assert rc["qualifier_dropped"] == 1
    (line,) = rc["qualifier_dropped_lines"]
    assert line["text"] == "Women who are pregnant"
    assert (line["class_stored"], line["class_now"]) == ("structured", "human")
    assert "structured -> human" in rc["class_moved"]
    # the steps a recompile does not run never show among the flags read
    assert "equivalence_fail" not in rc["flags"]


def test_the_coverage_counts_mapped_unmapped_and_the_most_frequent(run: dict[str, Any]) -> None:
    cov = run["coverage"]
    assert cov["calls"] == 2
    assert cov["candidates"] == 5  # every candidate, the demographic ones included
    assert cov["concepts"] == 3  # cough, the made-up lab, pregnancy (condition)
    assert cov["by_domain"]["observation"] == [1, 0]
    assert cov["mapped"] + cov["unmapped"] == cov["concepts"]
    assert {"domain": "observation", "name": "made-up lab zz", "count": 1} in cov["top_unmapped"]
    assert sum(cov["by_source"].values()) == cov["mapped"]


def test_the_cli_refuses_a_scratch_folder_that_is_not_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "x").write_text("x")
    assert compile_report.main([str(tmp_path), "--scratch", str(tmp_path / "scratch"), "--no-recompile"]) == 2
    assert "not empty" in capsys.readouterr().err


def test_the_cli_prints_the_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = make_run(tmp_path)
    out = tmp_path / "r.json"
    assert compile_report.main([str(d), "--no-recompile", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "set made: 3 protocols; reached SCREEN 2" in text
    assert json.loads(out.read_text())["sets"]["made"]["recompiled"] is None


def test_a_diagnosis_drafted_as_an_encounter_is_counted_apart_as_the_compile_reads_it() -> None:
    from criteria_compiler.terminology.mapper import Terminology

    reply = {"criteria": [{"kind": "inclusion", "text": "made up", "concept_candidates": [
        {"domain": "encounter", "name": "invasive breast carcinoma"}, {"domain": "encounter", "name": "zz made up"}]}]}  # fmt: skip
    traces = {"traces": [_trace("ir_extract@4", "extract_criteria", "J", {"criteria": []}, reply)]}
    cov = compile_report.coverage([traces], Terminology(installed=Path("/nonexistent/terminology-none")))
    assert cov["by_domain"] == {"encounter": [2, 0]}
    assert cov["unmapped_refiled_as_condition"] == {"diagnoses": 1, "mapped_as_a_condition": 1}
