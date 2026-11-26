"""Red of lane G's frozen-commit run (#639, 2026-11-16): the criteria compiler answered HTTP 500 on FEAS and APPROVE,
11 times, compiling public protocols far messier than the eight shipped ones, and its own log was not kept (D-910).

* One criterion the model wrote that the compiler cannot run (an age-or-sex atom with neither, "not" of two things,
  "at least" with no count, a score on a diagnosis) is kept as a person's check at post-processing, so the approval's
  re-extraction of a reviewer's edit (which has no later demotion, unlike /compile) no longer fails on it. So is a
  criterion outside the IR, which raised unhandled.
* The approval's comparison of the compiled CQL and SQL calls the FHIR server and the lake; a refusal there was an
  unhandled error. It is a 422 with the step and a reason, by type and status (never the server's text).
* Every route answers: a compile error or an IR refusal is a 422 with its step and reason; anything else is a bug,
  a 500 with an error id, and the error's type and frames (never its text) go to the audit chain, which the box
  keeps, as well as the service's log.

Synthetic protocols, no model, no FHIR server.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import CompileError
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from pydantic import ValidationError
from tb_contracts import CriterionIR, LlmExtractOutput

STROKE = {"domain": "condition", "concept": "stroke", "quantifier": "any"}


def _line(text: str, logic: dict[str, Any], kind: str = "exclusion") -> dict[str, Any]:
    return {"kind": kind, "class": "structured", "text": text, "logic": logic,
            "concept_candidates": [{"name": "stroke", "domain": "condition"}]}  # fmt: skip


PROTOCOL = LlmExtractOutput.model_validate(
    {
        "criteria": [
            _line("History of stroke", STROKE),
            _line("Adults only", {"domain": "demographic"}, "inclusion"),  # the model gave no age and no sex
            _line("Neither stroke nor stroke", {"op": "not", "args": [STROKE, STROKE]}),
            _line("Two strokes", {**STROKE, "quantifier": "count>="}),  # "at least" with no count
        ]
    }
)


def test_a_criterion_that_cannot_run_is_a_persons_check_and_the_rest_compiles() -> None:
    post = pp.postprocess("T", PROTOCOL, Terminology(), "1.0.0")
    first, *bad = post.criteria
    assert first.class_ == "structured" and not first.flags
    for c in bad:
        assert c.class_ == "human" and c.human_question, c.id
        assert {"logic_invalid", "needs_review"} <= set(c.flags or []), c.id
        assert any(c.id in w and "person" in w for w in post.warnings), c.id
    sql = SqlGenerator("T", "1.0.0", ValueSets("T", post.valuesets, Terminology())).render(post.criteria)
    assert "()" not in sql and "C_T-INC-01" not in sql  # nothing of the demoted criteria goes to the SQL


def test_a_criterion_outside_the_ir_is_kept_for_a_person(monkeypatch: pytest.MonkeyPatch) -> None:
    real = CriterionIR.model_validate

    class Strict(CriterionIR):
        @classmethod
        def model_validate(cls, obj: Any, *a: Any, **k: Any) -> Any:
            if isinstance(obj, dict) and obj.get("text") == "Two strokes" and obj.get("class") == "structured":
                return real({"bad": "field"})  # the IR refuses it (raises ValidationError)
            return real(obj, *a, **k)

    monkeypatch.setattr(pp, "CriterionIR", Strict)
    post = pp.postprocess("T", PROTOCOL, Terminology(), "1.0.0")
    two = post.criteria[-1]
    assert (
        two.class_ == "human" and two.text == "Two strokes" and {"ir_invalid", "needs_review"} <= set(two.flags or [])
    )
    assert any("not a valid criterion" in w and "field" not in w.split("(")[0] for w in post.warnings)


# ------------------------------------------------------------------------------------------- the routes
class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **kw: Any) -> dict[str, Any]:
        self.events.append((event, kw))
        return {}


class _Raising:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.audit = _Audit()

    def compile(self, req: Any) -> Any:
        raise self.exc

    approve = compile

    def _audit(self, event: str, **kw: Any) -> None:
        self.audit.append(event, **kw)


def _post(monkeypatch: pytest.MonkeyPatch, exc: BaseException, path: str = "/compile") -> tuple[Any, _Raising]:
    from criteria_compiler import app as capp
    from fastapi.testclient import TestClient

    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    fake = _Raising(exc)
    monkeypatch.setattr(capp, "compiler", lambda: fake)
    body = (
        {"job_id": "J", "ruleset": "T", "parsed_doc_key": "k"}
        if path == "/compile"
        else {"job_id": "J", "ruleset": "T", "version": "1.0.0", "by": "pi", "decisions": []}
    )
    resp = TestClient(capp.app, raise_server_exceptions=False).post(path, json=body)
    return resp, fake


def _validation_error() -> ValidationError:
    try:
        CriterionIR.model_validate({"id": "T-EXC-01"})
    except ValidationError as exc:
        return exc
    raise AssertionError("no error")


def test_a_compile_error_or_an_ir_refusal_is_a_422_with_its_step(monkeypatch: pytest.MonkeyPatch) -> None:
    resp, _ = _post(monkeypatch, CompileError("'not' takes exactly one argument"))
    assert resp.status_code == 422 and resp.json()["detail"]["step"] == "compile"
    assert "exactly one" in resp.json()["detail"]["message"]
    resp, _ = _post(monkeypatch, _validation_error(), "/approve")
    detail = resp.json()["detail"]
    assert resp.status_code == 422 and detail["step"] == "approve" and "not valid here" in detail["message"]


def test_a_bug_is_a_500_with_an_id_and_its_trace_in_the_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    resp, fake = _post(monkeypatch, KeyError("a value that must never be shown"))
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["error"] == "internal error" and len(detail["error_id"]) == 16  # H-147: ids.log_safe_id
    assert "never be shown" not in resp.text
    [(event, kw)] = fake.audit.events
    d = kw["detail"]
    assert event == "compile.error" and d["error_id"] == detail["error_id"] and d["error"] == "KeyError"
    assert "test_compiler_answers_every_failure" in d["trace"] and "never be shown" not in d["trace"]


def test_the_comparison_refused_by_the_fhir_server_is_a_422(monkeypatch: pytest.MonkeyPatch) -> None:
    from criteria_compiler import service
    from tb_common.fhir import FhirEvalError

    class Fhir:
        def load(self, *a: Any) -> None:
            raise FhirEvalError("PUT ValueSet/VS_X: 400 patient 0123456789 is quoted here")

    comp = object.__new__(service.Compiler)
    comp.d = type("D", (), {"fhir": Fhir(), "lake": object(), "equivalence": None, "settings_thresholds": {}})()
    art = service.Artifacts(
        {"TB_Common": "", "L": ""}, {"FHIRHelpers": "{}", "TB_Common": "{}", "L": "{}"}, "", "L", "1", []
    )
    monkeypatch.setattr(service, "fhirhelpers_source", lambda: "")
    crit = pp.postprocess("T", PROTOCOL, Terminology(), "1.0.0").criteria[:1]
    with pytest.raises(service.CompileFailed) as got:
        comp._equivalence(crit, art, {}, date(2026, 10, 5), "seed")
    assert got.value.step == "equivalence" and "FhirEvalError" in str(got.value)
    assert "0123456789" not in str(got.value)  # never the server's text
