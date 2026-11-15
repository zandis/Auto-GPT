"""Scripted judges, scripted models and a small note lake for the exclusion-path tests (D-276; review S-3).

The repository stub answers every note question the same way under every model name, so it can never disagree with
itself, be unsure, misquote or be down. The rules that keep a contested note answer from excluding a patient need
exactly those answers. This helper gives them, at three levels:

* :class:`ScriptedJudge`: a cascade ``JudgeClient`` whose reply is a function of the role and the question
  (the engine's own rules: confidence floor, quote check, S4, the excerpt budget);
* :class:`ScriptedModel`: an ``LlmClient`` stand-in (one model of a pair) that answers, misquotes, or raises like a
  model that is down or timed out (the pair rule through ``NoteJudge`` / ``OrchestratorJudge``);
* :func:`stub_client`: a real ``LlmClient`` over the in-process stub, by served name, including the stub's test
  personas (``llm_stub.handlers.PERSONAS``) and a transport that times out (the same rule over HTTP);
* :class:`QuotingOracle` and :func:`quoting_pair` (T-705, D-459; also T-706): a pair of ``ScriptedModel`` whose
  answer is a function of the excerpts it is shown (a decisive sentence per criterion, :class:`Decisive`), with a
  verifier that agrees, disagrees, is unsure or is down.

:func:`note_lake` builds a lake of a few patients with dated notes, and :func:`ruleset` a ruleset of note criteria on
top of one structured inclusion (age), as ``tests/unit/test_derived_scores.py`` does for scores. No database.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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


# ------------------------------------------------------------------------------------------------ the quoting pair
# T-705 (path independence, D-459) and T-706 (judge in the loop): a pair whose answer depends only on the text it is
# shown. The interface is these four names; keep it small (other cards copy it).
#
#   oracle = QuotingOracle({"gout flare": [Decisive("Acute gout flare of the right toe.")],
#                           "infection": [Decisive("Active tuberculosis under treatment.")]})
#   judge, verifier = quoting_pair(oracle)                      # both read; the verifier agrees
#   judge, verifier = quoting_pair(oracle, verifier="disagree")  # ... or flips every answer it gives
#   judge, verifier = quoting_pair(oracle, verifier="down")      # ... or is down (LlmError on every call)
#   services.llm, services.verifier = judge, verifier            # or NoteJudge(lake, judge, verifier=verifier)
#   oracle.full(cid_or_text, notes)                              # what a reader of the whole record answers
@dataclass(frozen=True)
class Decisive:
    """One sentence that settles a criterion when the model is shown it. ``answer`` is the judge's predicate (the
    prompt's ``verdict``): ``pass`` = the record documents the criterion's condition, ``fail`` = it documents that the
    condition is absent. The quote is the sentence itself, under the date of the excerpt that holds it."""

    sentence: str
    answer: str = "pass"
    confidence: float = 0.95


class QuotingOracle:
    """What a careful reader answers from the excerpts it is shown, per criterion.

    ``rules`` maps a key to the criterion's decisive sentences, in order. A key matches a question when it is a
    substring (case-folded) of the criterion text or the note question. The first sentence (in rule order) found in
    any excerpt shown decides, quoted from the newest excerpt that holds it; when none is shown the answer is
    ``unknown`` at 0.5 with no quote. A question no key matches is ``unknown``. Every question is kept in ``asked``
    as ``(key or None, criterion_text, [excerpt texts])``, so a test can see what each path showed the model."""

    def __init__(self, rules: Mapping[str, Sequence[Decisive]]) -> None:
        self.rules = {k.casefold(): list(v) for k, v in rules.items()}
        self.asked: list[tuple[str | None, str, list[str]]] = []

    def key_of(self, criterion_text: str, note_question: str = "") -> str | None:
        hay = f"{criterion_text}\n{note_question}".casefold()
        return next((k for k in self.rules if k in hay), None)

    def decide(self, key: str | None, excerpts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """The judge prompt's JSON for ``excerpts`` (dicts with ``text`` and ``date``)."""
        for rule in self.rules.get(key or "", []):
            holding = [e for e in excerpts if rule.sentence in str(e.get("text") or "")]
            if holding:
                newest = max(holding, key=lambda e: str(e.get("date") or ""))
                return {"verdict": rule.answer, "reason": "quoting", "confidence": rule.confidence,
                        "quote": rule.sentence, "quote_date": str(newest.get("date") or "") or None}  # fmt: skip
        return {"verdict": "unknown", "reason": "quoting: not in the excerpts", "confidence": 0.5, "quote": None,
                "quote_date": None}  # fmt: skip

    def __call__(self, variables: dict[str, Any]) -> dict[str, Any]:
        """``ScriptedModel``'s ``answer``: reads the prompt's ``criterion_text``, ``note_question`` and ``excerpts``."""
        key = self.key_of(str(variables.get("criterion_text") or ""), str(variables.get("note_question") or ""))
        ex = list(variables.get("excerpts") or [])
        self.asked.append((key, str(variables.get("criterion_text") or ""), [str(e.get("text") or "") for e in ex]))
        return self.decide(key, ex)

    def full(self, criterion: str, notes: Sequence[Mapping[str, Any]]) -> str:
        """The predicate (``pass``/``fail``/``unknown``) a reader of every note in ``notes`` gives; ``criterion`` is
        a rule key or a criterion text."""
        key = criterion.casefold() if criterion.casefold() in self.rules else self.key_of(criterion)
        return str(self.decide(key, notes)["verdict"])


_FLIP = {"pass": "fail", "fail": "pass"}


def quoting_pair(
    oracle: QuotingOracle, verifier: str = "agree", only: Sequence[str] = ()
) -> tuple[ScriptedModel, ScriptedModel]:
    """``(judge, verifier)``: two models of different builds that both read through ``oracle``. ``verifier`` is what
    the second model does: ``agree`` (reads as the judge does), ``disagree`` (flips a ``pass``/``fail`` answer, same
    quote), ``unknown`` (never sure) or ``down`` (an outage on every call). ``only``: rule keys the verifier's
    behaviour applies to; it agrees on the others."""
    if verifier not in ("agree", "disagree", "unknown", "down"):
        raise ValueError(f"verifier {verifier!r}: agree, disagree, unknown or down")
    keys = {k.casefold() for k in only}

    def second(variables: dict[str, Any]) -> dict[str, Any]:
        key = oracle.key_of(str(variables.get("criterion_text") or ""), str(variables.get("note_question") or ""))
        ans = oracle.decide(key, list(variables.get("excerpts") or []))
        if verifier == "agree" or (keys and key not in keys):
            return ans
        if verifier == "down":
            raise LlmError("LLM endpoint unreachable (local): scripted verifier outage")
        if verifier == "unknown":
            return {**ans, "verdict": "unknown", "confidence": 0.5, "quote": None, "quote_date": None}
        return {**ans, "verdict": _FLIP.get(str(ans["verdict"]), ans["verdict"])}

    return ScriptedModel("judge-a", oracle), ScriptedModel("verifier-b", second)


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


def note_lake(
    tmp: Path,
    patients: dict[str, list[tuple[date, str]]],
    snapshot: str,
    conditions: list[dict[str, Any]] | None = None,
) -> LakeLocal:
    """A lake of adults (born 1960) with the given dated notes; a patient with an empty list has no note. ``conditions``:
    FHIR Condition resources (none by default)."""
    nd = tmp / "ndjson"
    nd.mkdir(parents=True)
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "female"} for p in patients]
    docs = [_doc(p, i, on, text) for p, notes in patients.items() for i, (on, text) in enumerate(notes, start=1)]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "DocumentReference.ndjson").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8"
    )
    (nd / "Condition.ndjson").write_text("".join(json.dumps(c) + "\n" for c in conditions or []), encoding="utf-8")
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
