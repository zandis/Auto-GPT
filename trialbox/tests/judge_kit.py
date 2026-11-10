"""Scripted judges, scripted models and a small note lake for the exclusion-path tests (D-276; review S-3).

The repository stub answers every note question the same way under every model name, so it can never disagree with
itself, be unsure, misquote or be down. The rules that keep a contested note answer from excluding a patient need
exactly those answers. This helper gives them, at three levels:

* :class:`ScriptedJudge`: a cascade ``JudgeClient`` whose reply is a function of the role and the question
  (the engine's own rules: confidence floor, quote check, S4, the excerpt budget);
* :class:`ScriptedModel`: an ``LlmClient`` stand-in (one model of a pair) that answers, misquotes, or raises like a
  model that is down or timed out (the pair rule through ``NoteJudge`` / ``OrchestratorJudge``);
* :func:`stub_client`: a real ``LlmClient`` over the in-process stub, by served name, including the stub's test
  personas (``llm_stub.handlers.PERSONAS``) and a transport that times out (the same rule over HTTP).

:func:`note_lake` builds a lake of a few patients with dated notes, and :func:`ruleset` a ruleset of note criteria on
top of one structured inclusion (age), as ``tests/unit/test_derived_scores.py`` does for scores. No database.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from embed_service.embedder import HashEmbedder
from fastapi.testclient import TestClient
from lake.client import LakeLocal
from lake.store import Lake
from llm_stub.app import app as stub_app
from matching.cascade.judge import JudgeReply
from tb_common.llm import LlmClient, LlmError, LlmResult
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------ cascade judge
def reply(
    verdict: str, confidence: float = 0.95, quote: str | None = None, quote_date: str | None = None
) -> JudgeReply:
    return JudgeReply(verdict, confidence, quote, quote_date, "scripted", call_id="c1", prompt="judge@test")


class ScriptedJudge:
    """``script(role, kw)`` gives the reply; ``kw`` are the cascade's keyword arguments (``excerpts``,
    ``criterion_text``, ...). Every call is kept in ``calls`` as ``(role, criterion_text)``."""

    def __init__(self, script: Callable[[str, dict[str, Any]], JudgeReply]) -> None:
        self.script = script
        self.calls: list[tuple[str, str]] = []

    def judge(self, *, role: str, **kw: Any) -> JudgeReply:
        self.calls.append((role, str(kw["criterion_text"])))
        return self.script(role, kw)


def quoting(verdict: str, sentence: str, confidence: float = 0.95) -> Callable[[str, dict[str, Any]], JudgeReply]:
    """A script: ``verdict`` with ``sentence`` quoted from the newest excerpt that holds it, under that note's date
    (so the quote verifies); ``unknown`` when no excerpt holds it."""

    def script(role: str, kw: dict[str, Any]) -> JudgeReply:
        for ex in kw["excerpts"]:
            if sentence in str(ex["text"]):
                return reply(verdict, confidence, sentence, str(ex["date"]))
        return reply("unknown", 0.5)

    return script


# ------------------------------------------------------------------------------------------------ pair models
class ScriptedModel:
    """One model of a pair. ``answer(variables)`` returns the judge prompt's JSON, or raises :class:`LlmError`
    (a model that is down or timed out). ``model`` is the name its answers are served under."""

    gateway = None

    def __init__(
        self,
        model: str,
        answer: Callable[[dict[str, Any]], dict[str, Any]],
        base_url: str = "",
        served: str | None = None,
    ) -> None:
        self.model = model  # the name the box is configured with
        self.served = model if served is None else served  # the name the server answers under
        self.served_root = self.served  # the weights it is served from (``tb_common.pair.served_root``)
        self.base_url = base_url or f"http://{model}/v1"
        self.answer = answer
        self.calls = 0

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        self.calls += 1
        data = self.answer(variables)
        return LlmResult(data, prompt_id, 4, self.served, "local", "i" * 64, "o" * 64, 100, 20, 1)


def says(verdict: str, quote: str | None, confidence: float = 0.9, quote_date: str | None = None) -> Callable[..., dict[str, Any]]:  # fmt: skip
    def answer(variables: dict[str, Any]) -> dict[str, Any]:
        d = quote_date
        if d is None and quote is not None:
            d = next((str(e["date"]) for e in variables["excerpts"] if quote in str(e["text"])), None)
        return {"verdict": verdict, "reason": "scripted", "confidence": confidence, "quote": quote, "quote_date": d}

    return answer


def down(variables: dict[str, Any]) -> dict[str, Any]:
    raise LlmError("LLM endpoint unreachable (local): scripted outage")


# ------------------------------------------------------------------------------------------------ the stub over HTTP
class _TimesOut:
    """An HTTP client whose every request times out, as ``httpx`` reports it."""

    def post(self, url: str, **kw: Any) -> httpx.Response:
        raise httpx.ReadTimeout("scripted time-out")

    get = post


def stub_client(model: str, timeout: bool = False) -> LlmClient:
    """``LlmClient`` on the in-process stub under the served name ``model`` (a persona name scripts the answer)."""
    c = LlmClient("http://stub/v1", model)
    c.http = _TimesOut() if timeout else _Stub(stub_app)  # type: ignore[assignment]
    return c


class _Stub(TestClient):
    """The in-process stub. ``TestClient`` warns about a per-request ``timeout``, which the box's own ``/models``
    look-up sets (``tb_common.pair``); in process there is nothing to time out."""

    def get(self, url: Any, **kw: Any) -> Any:
        kw.pop("timeout", None)
        return super().get(url, **kw)


# ------------------------------------------------------------------------------------------------ lake and ruleset
def _doc(pid: str, n: int, on: date, text: str) -> dict[str, Any]:
    return {
        "resourceType": "DocumentReference",
        "id": f"{pid}-d{n}",
        "subject": {"reference": f"Patient/{pid}"},
        "date": f"{on.isoformat()}T09:00:00+09:00",
        "type": {"text": "progress"},
        "content": [
            {"attachment": {"contentType": "text/plain", "data": base64.b64encode(text.encode("utf-8")).decode()}}
        ],
    }


def note_lake(tmp: Path, patients: dict[str, list[tuple[date, str]]], snapshot: str) -> LakeLocal:
    """A lake of adults (born 1960) with the given dated notes; a patient with an empty list has no note."""
    nd = tmp / "ndjson"
    nd.mkdir(parents=True)
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "female"} for p in patients]
    docs = [_doc(p, i, on, text) for p, notes in patients.items() for i, (on, text) in enumerate(notes, start=1)]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "DocumentReference.ndjson").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8"
    )
    (nd / "Condition.ndjson").write_text("", encoding="utf-8")
    Lake(tmp / "lake", "Asia/Tokyo").rebuild(snapshot, HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder(), "Asia/Tokyo")


AGE = CriterionIR.model_validate(
    {
        "id": "T-INC-01",
        "ruleset": "T",
        "kind": "inclusion",
        "class": "structured",
        "text": "Age 18 or older",
        "logic": {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}},
    }
)


def note_criterion(cid: str, kind: str, text: str, question: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {
            "id": cid,
            "ruleset": "T",
            "kind": kind,
            "class": "note",
            "text": text,
            "note_question": question,
            "logic": {"domain": "condition", "valueset": "VS_T"},
        }
    )


def ruleset(crits: list[CriterionIR], valuesets: dict[str, Any] | None = None) -> Ruleset:
    """``crits`` (the age inclusion first when no structured criterion is given) as an approved ruleset with its SQL."""
    if not any(c.class_ == "structured" for c in crits):
        crits = [AGE, *crits]
    vs = dict(valuesets or {})
    sql = SqlGenerator("T", "1.0.0", ValueSets("T", vs, Terminology())).render(
        [c for c in crits if c.class_ == "structured"]
    )
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "T", "library": None, "criteria": [c.id for c in crits]})
    return Ruleset(manifest=manifest, criteria=crits, valuesets=vs, sql=sql)
