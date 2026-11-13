"""Context-aware budgets (T-603; deep review LLM-015, LLM-016, LLM-017, LLM-018, LLM-005 cut half, CR-004 flag half).

* The gateway gives each alias's context in ``GET /v1/models`` and refuses a request over it before dispatch
  (``prompt_too_long``, no other build).
* Per profile (8k, 16k, 32k) the longest prompt of each role, sized by its caller from that context — the judge's
  excerpts and full record, an uploaded chart, protocol extraction — is accepted by a stub that enforces the limit
  as vLLM does (``TB_STUB_CONTEXT``).
* A note over the budget is flagged on the candidate, not dropped in silence.
* The response cache keeps only complete answers and keys on ``max_tokens``; the truncation retry fits the context.

Synthetic data only.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from llm_stub.app import app as stub
from llm_stub.handlers import ir_extract
from orchestrator.scenarios.evaluate import FULL_RECORD_TOKENS, NoteJudge, _tokens, evaluate_patients
from registry.registry import Registry
from sitesetup import charts
from tb_common.audit import AuditLog
from tb_common.llm import LlmClient, LlmPromptTooLong, load_prompt, render
from tb_common.policy.classes import Environment
from tb_contracts import inline_schema
from tb_llm import CallLabels, GatewayClient, json_schema_format
from tb_llm.budget import SAFETY, estimate_messages, retry_max_tokens

from tests.judge_kit import note_criterion, ruleset
from tests.model_pins import promote_pins, release_registry
from tests.unit.test_gateway import _ir_body, _judge_body
from tests.unit.test_gateway_box_phi import _weights
from tests.unit.test_gateway_one_role_one_model import IR, JUDGE_HOST, VERIFIER_HOST, _gw
from tests.unit.test_screen_exclusion_pair import _NoStructured
from tools import pin_model

PROFILES = {"rtx5090": 8192, "gb10": 16384, "rtxpro6000": 32768}
LINE = "2026-10-01 経過良好。血圧 128/76、HbA1c 6.9 %。痛風発作なし。\n"
INDEX = date(2026, 10, 5)
# the stub's judge answers "met" on 治療反應良好 (llm_stub.handlers.judge), so the verifier is asked too
GOOD = note_criterion("T-INC-09", "inclusion", "Good response to treatment", "Is a good treatment response documented?")


class Recorder:
    """The real ``llm_stub`` behind the gateway's HTTP client: each upstream call's host and status."""

    def __init__(self) -> None:
        self.inner = TestClient(stub)
        self.log: list[tuple[str, int]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        r = self.inner.post(req.url.path, content=req.content, headers=dict(req.headers))
        self.log.append((req.url.host, r.status_code))
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _box(tmp_path: Path, gpu: str, monkeypatch: pytest.MonkeyPatch) -> tuple[Gateway, Recorder, TestClient]:
    """A PRODUCTION gateway with ``gpu``'s pair pinned as install does, in front of a stub that enforces the
    profile's context (``TB_STUB_CONTEXT``)."""
    _weights(tmp_path / "models")
    override = tmp_path / "site" / "registry.site.yaml"
    # T-012b (D-358): the synthetic folders are the expected release of a registry copy; install pins candidates,
    # promoted as a passing qualification record would
    folders = {build: tmp_path / "models" / d for build, _ep, _dv, d, *_ in pin_model.PROFILE_PAIRS[gpu]}
    release = release_registry(tmp_path, folders, monkeypatch)
    ok, lines = pin_model.install_pins(gpu, tmp_path / "models", override, {})
    assert ok, lines
    promote_pins(override)
    monkeypatch.setenv("TB_STUB_CONTEXT", str(PROFILES[gpu]))
    monkeypatch.setenv("TB_STEP_ID", "step-1")
    rec = Recorder()
    gw = Gateway(
        RoutingPolicy.load(),
        Registry.from_env({"TB_REGISTRY_OVERRIDE": str(override), "TB_REGISTRY_PATH": str(release)}),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=Environment.PRODUCTION),
        http=rec.client(),
        guard=Guard("^\\d{8}$"),
        step_confirm=lambda caller, study, step: True,
        env={"TB_GATEWAY_RETRY_DELAY_S": "0"},
    )
    return gw, rec, TestClient(create_app(gw))


def _client(app: TestClient, caller: str, alias: str) -> LlmClient:
    # an audit log, as LlmClient.from_config always gives one: the client's prompt fallback is audited (D-359)
    audit = AuditLog(Path(tempfile.mkdtemp(prefix="llm-audit-")))
    return LlmClient("", "", gateway=GatewayClient("http://gateway/v1", caller, http=app, model=alias), audit=audit)


class _Lake:
    """Forty long synthetic notes in the window: more than any profile's budget holds."""

    def __init__(self, n: int = 40, lines: int = 60) -> None:
        self.rows: list[dict[str, Any]] = [
            {
                "did": f"D{i:02d}",
                "d": date(2026, 9, 1 + i % 28),
                "type": "progress",
                "text": f"Note {i}. 治療反應良好。\n" + LINE * lines,
            }
            for i in range(n)
        ]

    def chunks_search(self, pid: str, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
        return [{"did": r["did"], "date": r["d"].isoformat(), "type": r["type"], "text": r["text"]} for r in self.rows][
            :k
        ]

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        rows = sorted(self.rows, key=lambda r: (r["d"], r["did"]), reverse=True)
        return SimpleNamespace(to_pylist=lambda: rows)


# ------------------------------------------------------------------------------------------------ the gateway
@pytest.mark.parametrize("gpu", list(PROFILES))
def test_the_gateway_gives_each_alias_its_profile_context(
    tmp_path: Path, gpu: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _rec, app = _box(tmp_path, gpu, monkeypatch)
    data = {m["id"]: m for m in app.get("/v1/models").json()["data"]}
    for alias in ("j-workhorse", "v-verifier"):
        assert data[alias]["context_length"] == data[alias]["max_model_len"] == PROFILES[gpu]
    assert data["x-external"]["context_length"] is None  # nothing routable records one
    gc = GatewayClient("http://gateway/v1", "orchestrator", http=app, model="j-workhorse")
    assert gc.context() == gc.context("v-verifier") == PROFILES[gpu]


def test_an_over_long_prompt_is_refused_before_dispatch_and_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gw, rec, _app = _box(tmp_path, "rtx5090", monkeypatch)
    body = _ir_body()
    body["max_tokens"] = 8192  # ir_extract's own max_tokens: prompt + answer is over 8,192
    res = gw.chat(IR, body)  # the protocol route allows fallback: still no other build
    assert (res.status, res.body["error"]["code"]) == (413, "prompt_too_long"), res.body
    assert "context of 8192" in res.body["error"]["message"] and rec.log == []
    body["max_tokens"] = 1024
    ok = gw.chat(IR, body)
    assert ok.status == 200 and rec.log == [(JUDGE_HOST, 200)]
    # control: the stub itself enforces the limit, as vLLM does
    over = {**_judge_body(), "model": "local/gemma-4-26b-a4b-nvfp4", "max_tokens": 8192}
    r = TestClient(stub).post("/v1/chat/completions", json=over, headers={"X-TB-Prompt-Id": "judge"})
    assert r.status_code == 400 and "maximum context length is 8192" in r.json()["message"]


# ------------------------------------------------------------------------------------------------ callers, per profile
@pytest.mark.parametrize("gpu", list(PROFILES))
def test_the_longest_prompt_of_each_role_is_accepted_on_each_profile(
    tmp_path: Path, gpu: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = PROFILES[gpu]
    _, rec, app = _box(tmp_path, gpu, monkeypatch)
    judge, verifier = _client(app, "orchestrator", "j-workhorse"), _client(app, "orchestrator", "v-verifier")
    nj = NoteJudge(lake=_Lake(), llm=judge, verifier=verifier, job_id="STUDY-1")  # type: ignore[arg-type]

    # the judge's full record and excerpts: filled to what the context leaves, never the fixed 28,000 tokens
    budget = nj.budget(GOOD, INDEX, FULL_RECORD_TOKENS)
    assert 0 < budget < context
    shown, left = nj._record("P", GOOD, INDEX)
    assert sum(_tokens(str(e["text"])) for e in shown) <= budget and left > 0 and len(shown) > 0
    for full in (True, False):
        r = nj.judge_patient("P", GOOD, INDEX, full=full)
        assert r.reason != "model_down" and nj.failures == 0, (full, r)

    # an uploaded chart of 60,000 characters of Japanese: read in parts sized from the context
    chart = (LINE * (charts.MAX_CHART_CHARS // len(LINE) + 1))[: charts.MAX_CHART_CHARS]
    parts = charts.chart_parts(chart, charts.part_budget(cast(Any, judge), "ja"))
    assert "".join(parts) == chart and len(parts) > 1
    before = len(rec.log)
    charts.extract(cast(Any, judge), chart, "ja")
    assert len(rec.log) - before == len(parts)  # one call per part, each accepted (below)

    # protocol extraction: its 8,192-token answer budget is cut to what fits beside the prompt
    criteria = [
        {"text": f"Age >= {18 + i} and HbA1c below {7 + i % 3}.{i % 10} %", "kind": "inclusion"} for i in range(40)
    ]
    ir = _client(app, "criteria-compiler", "j-workhorse").chat_json(
        "ir_extract", {"ruleset": "GZQO", "language": "en", "criteria": criteria}
    )
    assert ir.data

    assert rec.log and all(status == 200 for _, status in rec.log), rec.log  # the stub never said "too long"
    assert {h for h, _ in rec.log} == {JUDGE_HOST, VERIFIER_HOST}


def test_a_prompt_with_no_room_for_an_answer_is_not_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, rec, app = _box(tmp_path, "rtx5090", monkeypatch)
    judge = _client(app, "orchestrator", "j-workhorse")
    huge = [{"date": "2026-10-01", "note_type": "progress", "text": LINE * 300}]
    v = {"criterion_text": "x", "note_question": "x?", "index_date": "2026-10-05", "excerpts": huge}
    with pytest.raises(LlmPromptTooLong):
        judge.chat_json("judge", v)
    assert rec.log == []


# ------------------------------------------------------------------------------------------------ the flag
def test_a_note_over_the_budget_flags_the_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-004 flag half: the notes that did not fit are counted, the answer carries ``notes_over_budget`` and the
    candidate goes to review, never "high" on part of the record."""
    _, _rec, app = _box(tmp_path, "rtx5090", monkeypatch)
    nj = NoteJudge(
        lake=_Lake(),  # type: ignore[arg-type]
        llm=_client(app, "orchestrator", "j-workhorse"),
        verifier=_client(app, "orchestrator", "v-verifier"),
        job_id="STUDY-1",
    )
    r = nj.judge_patient("P", GOOD, INDEX, full=True)
    assert r.left_out > 0 and r.reason == "notes_over_budget", r
    rs = ruleset([GOOD])
    out = evaluate_patients(rs, ["P"], INDEX, _NoStructured(), nj, 0.0, only={GOOD.id}, all_candidates=True)
    v = out["P"].verdicts[0]
    assert out["P"].tier == "review" and v.evidence is not None and v.evidence.reason == "notes_over_budget"


# ------------------------------------------------------------------------------------------------ cache and retry
def _upstream(answers: list[tuple[str, str]]) -> tuple[httpx.Client, list[dict[str, Any]]]:
    """vLLM answering in turn ``(finish_reason, content)``; the last one repeats. Logs each request body."""
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        finish, content = answers[min(len(seen) - 1, len(answers) - 1)]
        return httpx.Response(
            200, json={"model": body["model"], "choices": [{"message": {"content": content}, "finish_reason": finish}]}
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


IR_OK = json.dumps(
    ir_extract({"ruleset": "GZQO", "language": "en", "criteria": [{"text": "Age >= 18", "kind": "inclusion"}]}),
    ensure_ascii=False,
)


def test_a_cut_off_answer_is_not_cached_and_the_retry_reaches_the_model(tmp_path: Path) -> None:
    """LLM-017 as the review ran it: first call cut off, the retry with four times the budget made one upstream call
    in total (a cache hit on the cut-off text). Now two, and a complete answer is cached."""
    http, seen = _upstream([("length", '{"ruleset": "GZ'), ("stop", IR_OK)])
    gw = _gw(tmp_path, http)
    body = {**_ir_body(), "max_tokens": 1024}
    first = gw.chat(IR, dict(body))
    assert first.body["tb"]["cache"] == "miss" and first.body["choices"][0]["finish_reason"] == "length"
    again = gw.chat(IR, dict(body))  # the same request: the cut-off answer was not kept
    assert again.body["tb"]["cache"] == "miss" and len(seen) == 2
    retry = gw.chat(IR, {**body, "max_tokens": 4096})
    assert retry.body["tb"]["cache"] == "miss" and len(seen) == 3
    hit = gw.chat(IR, {**body, "max_tokens": 4096})
    assert hit.body["tb"]["cache"] == "hit" and len(seen) == 3
    other = gw.chat(IR, {**body, "max_tokens": 2048})  # max_tokens is in the key
    assert other.body["tb"]["cache"] == "miss" and len(seen) == 4


def test_an_answer_outside_its_schema_is_not_cached(tmp_path: Path) -> None:
    http, seen = _upstream([("stop", '{"not": "the schema"}')])
    gw = _gw(tmp_path, http)
    for _ in range(2):
        res = gw.chat(IR, _ir_body())
        assert res.body["tb"]["cache"] == "miss"
    assert len(seen) == 2


def test_the_truncation_retry_fits_the_answering_alias_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM-018: the retry used to ask for up to 16,384 tokens, an HTTP 400 on an 8k or 16k model."""
    _, _rec, app = _box(tmp_path, "rtx5090", monkeypatch)
    sent: list[dict[str, Any]] = []
    calls = {"n": 0}

    def gateway(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            got = app.get("/v1/models")
            return httpx.Response(got.status_code, content=got.content)
        body = json.loads(req.content)
        sent.append(body)
        calls["n"] += 1
        finish = "length" if calls["n"] == 1 else "stop"
        content = json.dumps({"verdict": "unknown", "confidence": 0.5, "quote": None, "quote_date": None})
        return httpx.Response(
            200,
            json={
                "model": "x",
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "tb": {"alias": "j-workhorse", "call_id": "c", "expected_alias": "j-workhorse", "fallbacks": 0},
            },
        )

    def mock(req: httpx.Request) -> httpx.Response:
        r = gateway(req)
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})

    gc = GatewayClient("http://gateway/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(mock)))
    p = load_prompt("judge")
    # sized so that a retry of 4,096 does not fit an 8k context and a smaller one does (the assertions below hold
    # that); 170 lines before D-645 counted each digit of LINE as a token
    huge = [{"date": "2026-10-01", "note_type": "progress", "text": LINE * 140}]
    msgs = render(p, {"criterion_text": "x", "note_question": "x?", "index_date": "2026-10-05", "excerpts": huge})
    labels = CallLabels("D3", "screening", "STUDY-1", "s3_note_judgement", "judge", "judge@4", "step-1")
    gc.chat(
        msgs, labels, response_format=json_schema_format("judge", inline_schema(p.meta.output_schema)), max_tokens=1024
    )
    assert sent[0]["max_tokens"] == 1024 and len(sent) == 2
    assert estimate_messages(msgs) + sent[1]["max_tokens"] <= 8192 < estimate_messages(msgs) + 4096
    # no larger budget fits at all: the retry is not sent
    assert retry_max_tokens(8192, int(8192 * SAFETY) - 1000, 1024) is None
    assert retry_max_tokens(None, 10, 1024) == 4096 and retry_max_tokens(65536, 10, 8192) == 16384
