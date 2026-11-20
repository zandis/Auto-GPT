"""Observe actual model arguments and wire bodies, including the second opinion and the direct client."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import date
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from datacore.forms import Field
from edc.mapping import ItemMap
from edc.prefill import gateway_drafter
from lake.source import force
from matching.cascade.judge import GatewayJudge
from matching.cascade.s2b_semantic import Threshold, screen
from matching.registry_match.llm import ChatReply, call_model
from model_guard import COMPLETIONS, Guard, make_handler
from orchestrator.scenarios.case import ChartJudge, chart_excerpts
from orchestrator.scenarios.evaluate import NoteJudge
from sitesetup import charts
from tb_common import phi_guard
from tb_common.llm import LlmClient, LlmError
from tb_common.output_gate import OutputRefused
from tb_llm import CallLabels, GatewayClient, GatewayRefused

from tests.judge_kit import ScriptedJudge, ScriptedModel, note_lake, quoting, ruleset, says
from tests.unit.test_cascade_exclusion_rules import INC, SNAP, _run
from tests.unit.test_model_guard import KEY, _call, _start

pytestmark = pytest.mark.nodb
DAY = date(2026, 10, 1)
NOTES = [
    ("en", "Patient name: Robin Example. Acute gout flare.", "Robin Example", "Acute gout flare"),
    ("zh-TW", "姓名：陳美華，急性痛風發作。", "陳美華", "急性痛風發作"),
    ("ja", "氏名：山田 太郎\n急性痛風発作。", "山田 太郎", "急性痛風発作"),
]


class Capture:
    model = "synthetic"

    def __init__(self, term: str) -> None:
        self.seen: list[Any] = []
        self.term = term

    def answer(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(variables)
        return says("pass", self.term)(variables)

    def chat(self, messages: Any, labels: Any, **kw: Any) -> Any:
        self.seen.append(messages)
        return SimpleNamespace(
            data={"verdict": "unknown", "confidence": 0.4}, call_id="c", build_sha="b", tokens_in=1, tokens_out=1
        )

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        self.seen.append(variables)
        return {"facts": []}

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen.append(texts)
        return [[1.0] for _ in texts]

    def transport(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"verdict":"unknown","confidence":0}'}}],
                "tb": {"alias": "judge"},
            },
        )

    def registry(self, messages: list[dict[str, str]], *, json_mode: bool) -> ChatReply:
        self.seen.append(messages)
        return ChatReply("{}")


def exercise(path: str, c: Capture, lang: str, note: str) -> None:
    row = {"text": note, "date": DAY.isoformat(), "note_type": "progress", "did": "local", "extra": {"x": "hidden"}}
    kwargs: dict[str, Any] = {
        "criterion_text": "Evidence?",
        "note_question": "Evidence?",
        "index_date": DAY,
        "excerpts": [row],
    }
    if path in ("judge_pair", "case_chart"):
        nj = NoteJudge(
            None, cast(Any, ScriptedModel("first", c.answer)), verifier=cast(Any, ScriptedModel("second", c.answer))
        )
        if path == "judge_pair":
            nj.judge_excerpts(**kwargs)
        else:
            ChartJudge(nj, chart_excerpts(note, "sample.txt", DAY)).decide(INC, DAY)
    elif path == "cascade_gateway":
        GatewayJudge(c).judge(
            role="judge", study_id="s", data_class="D3", step_id="step", purpose="screening", **kwargs
        )
    elif path == "chart_facts":
        charts.extract(c, note, lang)
    elif path == "edc":
        gateway_drafter(c)(ItemMap("item"), Field("item", "form", "text", "Result"), [{**row, "id": "local"}])
    elif path == "registry":
        call_model(c.registry, [{"role": "user", "content": note}])
    elif path == "embedding":
        screen(c, "query", [note], Threshold(0.5, "public_prior", "all"))
    else:
        http = httpx.Client(transport=httpx.MockTransport(c.transport))
        if path == "direct":
            client = LlmClient("https://model.invalid", "judge")
            client.http = http
            client.chat_json("judge", {**kwargs, "index_date": DAY.isoformat()})
        else:
            gw = GatewayClient("https://model.invalid", "orchestrator", http=http)
            labels = CallLabels("D3", "screening", "s", "s3", "judge", "judge@4")
            gw.complete(
                {"messages": [{"role": "user", "content": note}], "response_format": {"type": "json_schema"}}, labels
            )


PATHS = (
    "judge_pair",
    "case_chart",
    "cascade_gateway",
    "chart_facts",
    "edc",
    "registry",
    "embedding",
    "direct",
    "gateway_client",
)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(("lang", "note", "name", "term"), NOTES)
def test_model_receives_clinical_terms_without_the_name(path: str, lang: str, note: str, name: str, term: str) -> None:
    c = Capture(term)
    exercise(path, c, lang, note)
    assert len(c.seen) == (2 if path in ("judge_pair", "case_chart") else 1)
    for payload in c.seen:
        sent = json.dumps(payload, ensure_ascii=False)
        assert all(part not in sent for part in name.split())
        assert term in sent and "hidden" not in sent


@pytest.mark.parametrize("path", PATHS)
def test_missing_analysis_never_calls_either_model(path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(phi_guard, "note_spans", None)
    lang, note, name, term = NOTES[0]
    c = Capture(term)
    with suppress(OutputRefused, GatewayRefused, LlmError):
        exercise(path, c, lang, note)
    assert c.seen == []
    audit = next(tmp_path.glob("*.jsonl")).read_text()
    assert "analysis_unavailable" in audit and name not in audit


@pytest.mark.parametrize("available", [True, False])
def test_cascade_engine_checks_the_actual_judge_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    _, note, name, term = NOTES[0]
    with force("legacy"):
        lake = note_lake(tmp_path, {"P-SYN": [(DAY, note)]}, SNAP)
    seen = []

    def answer(role: str, kw: dict[str, Any]) -> Any:
        seen.append(kw["excerpts"])
        return quoting("not_met", term)(role, kw)

    if not available:
        monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
        monkeypatch.setattr(phi_guard, "note_spans", None)
    with suppress(OutputRefused):
        _run(lake, ruleset([INC]), ["P-SYN"], ScriptedJudge(answer), embedder=None)
    if not available:
        assert "analysis_unavailable" in next((tmp_path / "audit").glob("*.jsonl")).read_text()
    assert bool(seen) == available
    for excerpts in seen:
        assert name not in str(excerpts) and term in str(excerpts)
        assert all("did" not in e for e in excerpts)


@pytest.mark.parametrize(("lang", "note", "name", "term"), NOTES)
def test_model_proxy_checks_the_wire_body(
    lang: str, note: str, name: str, term: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bytes] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            seen.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    upstream = _start(Upstream)
    proxy = _start(make_handler(Guard(KEY, {"llm-service": ("127.0.0.1", upstream.server_port)})))
    try:
        body = json.dumps({"prompt": note, "extra": {"text": "secret nested text"}}).encode()
        assert _call(proxy.server_port, "POST", COMPLETIONS, body=body) == 200
        assert len(seen) == 1 and set(json.loads(seen[0])) == {"prompt"}
        assert name not in json.loads(seen[0])["prompt"] and term in json.loads(seen[0])["prompt"]
        monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path))
        monkeypatch.setattr(phi_guard, "note_spans", lambda *a: None)
        assert _call(proxy.server_port, "POST", "/tokenize", body=body) == 422
        assert len(seen) == 1 and name not in next(tmp_path.glob("*.jsonl")).read_text()
    finally:
        for server in (proxy, upstream):
            server.shutdown()
            server.server_close()


@pytest.mark.parametrize(("lang", "note", "name", "term"), NOTES)
def test_gateway_dispatch_masks_and_audits_an_unavailable_analyser(
    lang: str, note: str, name: str, term: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_gateway import JUDGE_VARS, H, _gw, _judge_body

    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "refusal"))
    c = Capture(term)
    gw = _gw(tmp_path, http=httpx.Client(transport=httpx.MockTransport(c.transport)))
    body = _judge_body({**JUDGE_VARS, "excerpts": [{"text": note}]})
    gw.chat(H(), body)
    assert len(c.seen) == 1
    sent = json.dumps(c.seen, ensure_ascii=False)
    assert term in sent and all(part not in sent for part in name.split())
    monkeypatch.setattr(phi_guard, "note_spans", None)
    failure = gw.chat(H(), body)
    assert failure.status == 422 and len(c.seen) == 1
    record = next((tmp_path / "refusal").glob("*.jsonl")).read_text()
    assert "analysis_unavailable" in record and name not in record
