"""The branches of ``orchestrator.scenarios.evaluate`` no other unit test walks (nightly branch coverage, safety core).

* the runtime engine is SQL only: any other ``TB_SCREEN_ENGINE`` is refused, an empty one is SQL (owner decision 3);
* an engine asked for no patients asks nothing;
* the CQL engine the bench uses (``tools/bench.py``) loads the approved Library only when fhir-store lacks that exact
  version, with FHIRHelpers when the translator jars are there and TB_Common when the ruleset has it (D-34);
* a note judge with no lake says so instead of reading nothing;
* through the gateway, an answer that names no build is no answer: ``unknown`` / ``model_down``, a failure (T-601);
* a criterion that is neither an inclusion nor an exclusion never decides the structured candidacy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.scenarios.evaluate import CqlEngine, NoteJudge, SqlEngine, engine_from_env, structured_candidate
from tb_common.reasons import Reason
from tb_contracts import PatientEvaluation

DAY = date(2026, 11, 1)
EXCERPTS = [{"date": "2026-10-01", "note_type": "progress", "text": "q", "did": "D1"}]


def test_the_runtime_engine_is_sql_and_nothing_else() -> None:
    with pytest.raises(ValueError, match="SQL is the only runtime engine"):
        engine_from_env("cql", None, object(), None)  # type: ignore[arg-type]
    assert isinstance(engine_from_env("", None, object(), "snap"), SqlEngine)  # type: ignore[arg-type]
    assert isinstance(engine_from_env(" SQL ", None, object(), None), SqlEngine)  # type: ignore[arg-type]


def test_an_engine_asked_for_no_patients_asks_nothing() -> None:
    class Untouchable:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"asked {name} for no patients")

    assert SqlEngine(Untouchable(), "snap").evaluate(Untouchable(), [], DAY, ["INC-01"]) == {}  # type: ignore[arg-type]
    assert CqlEngine(Untouchable()).evaluate(Untouchable(), [], DAY, ["INC-01"]) == {}  # type: ignore[arg-type]


@dataclass
class FakeFhir:
    """fhir-store as the CQL engine sees it: one Library lookup, a load, and the evaluation."""

    stored_version: str | None = None
    loaded: list[list[dict[str, Any]]] = field(default_factory=list)
    asked: list[tuple[str, list[str], list[str]]] = field(default_factory=list)
    base: str = "http://fhir-store/fhir"

    @property
    def client(self) -> Any:
        version = self.stored_version

        def get(url: str) -> Any:
            assert url == f"{self.base}/Library/TB-Lib"
            if version is None:
                return SimpleNamespace(status_code=404, json=lambda: {})
            return SimpleNamespace(status_code=200, json=lambda: {"version": version})

        return SimpleNamespace(get=get)

    def load(self, libs: list[dict[str, Any]], valuesets: Any) -> None:
        self.loaded.append(list(libs))

    def evaluate_many(self, library: str, pids: list[str], index_date: date, exprs: list[str]) -> list[Any]:
        self.asked.append((library, pids, exprs))
        return [PatientEvaluation(pid=p, index_date=index_date, engine="cql", results={}) for p in pids]


def _rs(common: bool) -> Any:
    cql = {"TB_Lib": "library TB_Lib version '1.0.0-b1'"}
    if common:
        cql["TB_Common"] = "library TB_Common version '1.0.0'"
    return SimpleNamespace(
        library="TB_Lib", library_version="1.0.0-b1", cql=cql, elm={}, valuesets={}, active=lambda: []
    )


def _names(libs: list[dict[str, Any]]) -> list[str]:
    return [lib["name"] for lib in libs]


def test_the_cql_engine_loads_nothing_when_fhir_store_has_this_version() -> None:
    fhir = FakeFhir(stored_version="1.0.0-b1")
    out = CqlEngine(fhir).evaluate(_rs(common=True), ["P1", "P2"], DAY, [])  # type: ignore[arg-type]
    assert sorted(out) == ["P1", "P2"] and fhir.loaded == []
    assert fhir.asked == [("TB_Lib", ["P1", "P2"], [])]


def test_the_cql_engine_loads_the_library_with_fhirhelpers_and_tb_common(monkeypatch: pytest.MonkeyPatch) -> None:
    import criteria_compiler.compile_cql.translator as translator

    monkeypatch.setattr(translator, "fhirhelpers_source", lambda: "library FHIRHelpers version '4.0.1'")
    fhir = FakeFhir(stored_version="0.9.0-b0")  # an older build of the library: loaded again
    CqlEngine(fhir).ensure_loaded(_rs(common=True))  # type: ignore[arg-type]
    assert [_names(libs) for libs in fhir.loaded] == [["FHIRHelpers", "TB_Common", "TB_Lib"]]


def test_the_cql_engine_without_translator_jars_loads_only_the_ruleset(monkeypatch: pytest.MonkeyPatch) -> None:
    import criteria_compiler.compile_cql.translator as translator

    def absent() -> str:
        raise FileNotFoundError("translator jars")

    monkeypatch.setattr(translator, "fhirhelpers_source", absent)
    fhir = FakeFhir(stored_version=None)
    CqlEngine(fhir).ensure_loaded(_rs(common=False))  # type: ignore[arg-type]
    assert [_names(libs) for libs in fhir.loaded] == [["TB_Lib"]]  # the compiler's FHIRHelpers copy is relied on


def test_a_note_judge_with_no_lake_says_so() -> None:
    judge = NoteJudge(lake=None, llm=SimpleNamespace(model="m"))  # type: ignore[arg-type]
    crit = SimpleNamespace(id="INC-01", text="t", note_question=None, logic=None)
    with pytest.raises(RuntimeError, match="no lake"):
        judge.excerpts("P1", crit, DAY)  # type: ignore[arg-type]


class GatewayNoBuild:
    """A gateway client whose answer names no build (T-601)."""

    model = "v-judge"
    gateway = "http://gateway"

    def __init__(self) -> None:
        self.calls = 0

    def chat_json(self, prompt: str, variables: dict[str, Any], job_id: str | None = None) -> Any:
        self.calls += 1
        data = {"predicate": "met", "confidence": 0.9, "reason": "r", "quotes": []}
        return SimpleNamespace(data=data, build_sha="", model="v-judge", tokens_in=1, tokens_out=1, output_sha="0" * 64)


def test_through_the_gateway_an_answer_that_names_no_build_is_no_answer() -> None:
    llm = GatewayNoBuild()
    judge = NoteJudge(lake=None, llm=llm)  # type: ignore[arg-type]
    r = judge.judge_excerpts("criterion", "question", DAY, EXCERPTS)
    assert llm.calls == 1
    assert (r.predicate, r.reason) == ("unknown", Reason.MODEL_DOWN.value)
    assert (judge.failures, judge.calls) == (1, 0) and judge.served == {}


def test_a_criterion_neither_inclusion_nor_exclusion_never_decides_candidacy() -> None:
    other = SimpleNamespace(id="X-01", class_="structured", kind="other")
    rs = SimpleNamespace(active=lambda: [other])
    ev = PatientEvaluation(pid="P1", index_date=DAY, engine="sql", results={"X-01": True})
    assert structured_candidate(rs, ev) is True  # type: ignore[arg-type]
