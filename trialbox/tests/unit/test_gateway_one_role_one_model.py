"""The gateway never answers one role with another role's model (T-601, D-333; deep review LLM-002, LLM-003, LLM-006,
LLM-004; builds on D-276).

* A failed build is tried once more on the same build (transport error, HTTP 5xx), then the call fails.
* Another alias answers only on a route that says ``fallback: any`` (left out: ``none``); a patient role never falls
  back, and its build is the one it named or the route's *declared* first build.
* An HTTP 400 or 404 from a model server ends the call: ``prompt_too_long`` or ``upstream_failed``, never another build.
* The response names the build (``tb.build_id``, ``X-TB-Build-Id``) and the fallbacks (``X-TB-Fallbacks``).
* ``tb_llm`` raises on an answer from an alias the call did not expect.
* The pair's build comparison (D-276) stays the last line: a mutation that removes it fails a test here.

The faults are injected in front of the real ``llm_stub`` app on the installed box's gateway (``test_gateway_box_phi``).
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from llm_stub.app import app as stub
from orchestrator.scenarios import evaluate
from orchestrator.scenarios.evaluate import NoteJudge
from tb_common.audit import AuditLog
from tb_common.llm import LlmClient
from tb_common.policy.classes import Environment
from tb_llm import CallLabels, GatewayClient, GatewayUnexpectedAlias, json_schema_format

from tests.unit.test_gateway import H, _ir_body, _judge_body, _pinned_registry
from tests.unit.test_gateway_box_phi import JUDGE_VARS, box  # noqa: F401  (pytest fixture)

ROOT = Path(__file__).resolve().parents[2]
EXCERPTS = JUDGE_VARS["excerpts"]
JUDGE_HOST, VERIFIER_HOST = "llm-service", "llm-verifier"
CONTEXT_400 = {
    "object": "error",
    "message": "This model's maximum context length is 8192 tokens. However, you requested 9000 tokens.",
    "type": "BadRequestError",
    "code": 400,
}


class FaultyStub:
    """The ``llm_stub`` app behind a transport that injects faults per host: ``down`` (HTTP 500 every time),
    ``flaky`` (HTTP 500 once, then the stub), ``refuse`` (connection refused), ``toolong`` (vLLM's HTTP 400 for a
    prompt over the context), ``bad`` (HTTP 400, another reason), ``gone`` (HTTP 404, a name not served)."""

    def __init__(self, faults: dict[str, str] | None = None) -> None:
        self.faults = dict(faults or {})
        self.log: list[str] = []
        self.inner = TestClient(stub)

    def handler(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        fault = self.faults.get(host, "")
        self.log.append(f"{host} {fault or 'ok'}")
        if fault == "flaky":
            self.faults[host] = ""
            return httpx.Response(500, json={"error": "flaky"})
        if fault == "down":
            return httpx.Response(500, json={"error": "internal server error"})
        if fault == "refuse":
            raise httpx.ConnectError("connection refused", request=req)
        if fault == "toolong":
            return httpx.Response(400, json=CONTEXT_400)
        if fault == "bad":
            return httpx.Response(400, json={"object": "error", "message": "invalid response_format", "code": 400})
        if fault == "gone":
            return httpx.Response(404, json={"object": "error", "message": "The model does not exist.", "code": 404})
        inner = self.inner.post(req.url.path, content=req.content, headers=dict(req.headers))
        return httpx.Response(inner.status_code, content=inner.content, headers={"content-type": "application/json"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def hits(self, host: str) -> int:
        return sum(1 for x in self.log if x.startswith(host + " "))


def _faulty(box_: Any, faults: dict[str, str]) -> tuple[Gateway, LlmClient, LlmClient, FaultyStub, Path]:
    gw, llm, verifier, tmp_path = box_
    fake = FaultyStub(faults)
    gw.http = fake.client()
    gw.retry_delay_s = 0.0
    return gw, llm, verifier, fake, tmp_path


def _gateway_calls(tmp_path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(x)
        for f in sorted((tmp_path / "audit").glob("*.jsonl"))
        for x in f.read_text(encoding="utf-8").splitlines()
        if '"llm.gateway.' in x
    ]


def _pair(llm: LlmClient, verifier: LlmClient) -> NoteJudge:
    return NoteJudge(lake=None, llm=llm, verifier=verifier, job_id="STUDY-1")


def _ask(nj: NoteJudge) -> Any:
    return nj.judge_excerpts(JUDGE_VARS["criterion_text"], JUDGE_VARS["note_question"], date(2026, 10, 5), EXCERPTS)


# ------------------------------------------------------------------------------------------------ fault injection
@pytest.mark.parametrize("fault", ["down", "refuse"])
def test_judge_down_is_unknown_and_a_failure_never_agreement(box: Any, fault: str) -> None:  # noqa: F811
    _gw, llm, verifier, fake, tmp_path = _faulty(box, {JUDGE_HOST: fault})
    nj = _pair(llm, verifier)
    r = _ask(nj)
    assert (r.predicate, r.reason) == ("unknown", "model_down") and nj.failures >= 1, (r, nj.failures)
    assert fake.hits(JUDGE_HOST) == 2  # tried once more on the same build
    assert fake.hits(VERIFIER_HOST) == 0  # the verifier build never stood in for the judge
    refused = [c for c in _gateway_calls(tmp_path) if c["event"] == "llm.gateway.refuse"]
    assert [c["detail"]["reason"] for c in refused] == ["upstream_failed"]
    assert refused[0]["detail"]["retries"] == 1 and refused[0]["detail"]["expected_alias"] == "j-workhorse"
    with pytest.raises(Exception, match="did not answer"):
        nj.calls = 0
        evaluate.check_judge(nj)


@pytest.mark.parametrize(
    ("fault", "code", "status"),
    [("toolong", "prompt_too_long", 413), ("bad", "upstream_failed", 502), ("gone", "upstream_failed", 502)],
)
def test_judge_400_or_404_ends_the_call_never_another_alias(box: Any, fault: str, code: str, status: int) -> None:  # noqa: F811
    gw, llm, verifier, fake, tmp_path = _faulty(box, {JUDGE_HOST: fault})
    res = gw.chat(H(Data_Class="D3", Step=""), _judge_body())
    assert (res.status, res.body["error"]["code"]) == (status, code), res.body
    assert res.headers["X-TB-Fallbacks"] == "0" and res.headers["X-TB-Retries"] == "0"
    assert fake.hits(JUDGE_HOST) == 1 and fake.hits(VERIFIER_HOST) == 0  # no retry, no other build
    nj = _pair(llm, verifier)
    r = _ask(nj)
    assert (r.predicate, r.reason) == ("unknown", "model_down") and nj.failures == 1
    assert fake.hits(VERIFIER_HOST) == 0
    assert all(c["model"] != "v-verifier" for c in _gateway_calls(tmp_path))


class _Recording:
    """An HTTP client that keeps the last response, so a test reads the gateway's headers behind ``tb_llm``."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.last: Any = None

    def post(self, *args: Any, **kw: Any) -> Any:
        self.last = self.inner.post(*args, **kw)
        return self.last


def test_a_judge_that_fails_once_is_answered_by_the_same_build(box: Any) -> None:  # noqa: F811
    gw, _llm, _verifier, fake, _tmp = _faulty(box, {JUDGE_HOST: "flaky"})
    http = _Recording(TestClient(create_app(gw)))  # through tb_llm and the gateway's HTTP app, to read the headers
    hdr = H(Data_Class="D3", Step="")
    labels = CallLabels("D3", "screening", "STUDY-1", "s3_note_judgement", "judge", "judge@4",
                        prompt_sha=hdr["X-TB-Prompt-Sha"])  # fmt: skip
    GatewayClient("http://gateway/v1", "orchestrator", http=http).complete(_judge_body(), labels)  # type: ignore[arg-type]
    res = http.last
    assert res is not None and res.status_code == 200, res
    tb = res.json()["tb"]
    assert (tb["alias"], tb["expected_alias"], tb["fallbacks"], tb["retries"]) == ("j-workhorse", "j-workhorse", 0, 1)
    assert res.headers["X-TB-Build-Id"] == tb["build_id"] and tb["build_id"]
    assert res.headers["X-TB-Build-Sha"] == tb["build_sha"] and res.headers["X-TB-Fallbacks"] == "0"
    assert res.headers["X-TB-Retries"] == "1" and fake.hits(JUDGE_HOST) == 2 and fake.hits(VERIFIER_HOST) == 0


def test_the_pair_answers_from_two_builds_when_both_are_up(box: Any) -> None:  # noqa: F811
    """Control for the cases above: the same box, no fault, a decided answer checked by the second build."""
    _gw, llm, verifier, _fake, tmp_path = _faulty(box, {})
    nj = _pair(llm, verifier)
    r = _ask(nj)
    assert nj.failures == 0 and r.reason != "model_down", r
    calls = [c for c in _gateway_calls(tmp_path) if c["event"] == "llm.gateway.call"]
    assert {c["model"] for c in calls} <= {"j-workhorse", "v-verifier"} and calls[0]["model"] == "j-workhorse"
    assert all(c["detail"]["fallbacks"] == 0 for c in calls)


# ------------------------------------------------------------------------------------------------ routes
def _gw(tmp_path: Path, http: httpx.Client, doc: dict[str, Any] | None = None) -> Gateway:
    return Gateway(
        RoutingPolicy(doc) if doc is not None else RoutingPolicy.load(),
        _pinned_registry(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=Environment.PRODUCTION),
        http=http,
        guard=Guard("^\\d{8}$"),
        step_confirm=lambda caller, study, step: True,
        env={"TB_GATEWAY_RETRY_DELAY_S": "0.001"},
    )


def _vllm(faults: dict[str, int | str]) -> tuple[httpx.Client, list[str]]:
    """Two vLLM servers answering a valid object under the served name asked for; a host in ``faults`` answers that
    HTTP status (or ``refuse``: connection refused) to every call."""
    log: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        log.append(host)
        fault = faults.get(host)
        if fault == "refuse":
            raise httpx.ConnectError("refused", request=req)
        if fault == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        if isinstance(fault, int):
            return httpx.Response(fault, json=CONTEXT_400 if fault == 400 else {"error": "x"})
        served = json.loads(req.content)["model"]
        content = json.dumps({"verdict": "pass", "confidence": 0.9, "quote": "q", "quote_date": "2026-10-01"})
        return httpx.Response(200, json={"model": served, "choices": [{"message": {"content": content}}]})

    return httpx.Client(transport=httpx.MockTransport(handler)), log


IR = H(Caller="criteria-compiler", Role="extract_criteria", Purpose="protocol_ingest", Prompt="ir_extract@2",
       Data_Class="D1", Context_Of_Use="protocol_criteria_extraction")  # fmt: skip


def test_a_route_that_allows_it_falls_back_and_says_so_and_tb_llm_refuses_it(tmp_path: Path) -> None:
    http, log = _vllm({JUDGE_HOST: 503})
    gw = _gw(tmp_path, http)
    res = gw.chat(IR, _ir_body())  # route protocol: fallback any
    assert res.status == 200 and res.body["tb"]["alias"] == "v-verifier", res.body
    assert res.headers["X-TB-Fallbacks"] == "1" and res.body["tb"]["expected_alias"] == "j-workhorse"
    assert log.count(JUDGE_HOST) == 2  # retried once before the next build
    app = TestClient(create_app(gw))
    labels = CallLabels("D1", "protocol_ingest", "STUDY-1", "protocol_criteria_extraction", "extract_criteria",
                        "ir_extract@2", "step-1", prompt_sha=IR["X-TB-Prompt-Sha"])  # fmt: skip
    body = _ir_body()
    strict = GatewayClient("http://gateway/v1", "criteria-compiler", http=app)
    with pytest.raises(GatewayUnexpectedAlias, match="v-verifier"):
        strict.complete(dict(body), labels)
    lenient = GatewayClient("http://gateway/v1", "criteria-compiler", http=app, allow_fallback=True)
    assert lenient.complete(dict(body), labels)["tb"]["alias"] == "v-verifier"
    named = GatewayClient("http://gateway/v1", "criteria-compiler", http=app, allow_fallback=True, model="j-workhorse")
    with pytest.raises(Exception, match="upstream_failed"):
        named.complete(dict(body), labels)  # the alias named must answer, allow_fallback or not


@pytest.mark.parametrize("status", [400, 404])
def test_400_or_404_never_falls_back_even_where_the_route_allows_it(tmp_path: Path, status: int) -> None:
    http, log = _vllm({JUDGE_HOST: status})
    res = _gw(tmp_path, http).chat(IR, _ir_body())
    want = "prompt_too_long" if status == 400 else "upstream_failed"
    assert res.body["error"]["code"] == want and log == [JUDGE_HOST], (res.body, log)


@pytest.mark.parametrize(("fault", "tries"), [(503, 2), (500, 2), ("refuse", 2), ("timeout", 1), (429, 1), (408, 1)])
def test_the_judge_role_never_gets_the_verifier_build_whatever_the_judge_server_does(
    tmp_path: Path, fault: int | str, tries: int
) -> None:
    http, log = _vllm({JUDGE_HOST: fault})
    res = _gw(tmp_path, http).chat(H(Data_Class="D3"), _judge_body())
    assert res.status == 502 and res.body["error"]["code"] == "upstream_failed", res.body
    assert log == [JUDGE_HOST] * tries  # a timeout is not tried again; nothing reaches the verifier build


def _routing() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    return doc


def test_a_route_that_says_nothing_does_not_fall_back(tmp_path: Path) -> None:
    doc = _routing()
    for r in doc["routes"]:
        if r["id"] == "protocol":
            r.pop("fallback")
    http, log = _vllm({JUDGE_HOST: 503})
    res = _gw(tmp_path, http, doc).chat(IR, _ir_body())
    assert res.body["error"]["code"] == "upstream_failed" and VERIFIER_HOST not in log
    shipped = RoutingPolicy.load()
    allowed = {r.id for r in shipped.routes if r.fallback == "any"}
    assert allowed == {"converse", "documents-d1", "protocol", "mapping", "aggregate", "ops"}
    patient = set(shipped.groups["patient"])
    assert not any(set(r.roles) & patient for r in shipped.routes if r.id in allowed)


def test_a_filtered_judge_build_never_makes_the_verifier_the_judge(tmp_path: Path) -> None:
    """Adversarial: a judge build dropped by a filter (here the serving endpoint is not for PRODUCTION) left the
    verifier build first in the list, and D-276 kept "the first alias left". Now the judge gets the route's declared
    first build or nothing."""
    doc = _routing()
    doc["endpoints"]["serving"]["environments"] = ["DEV"]
    http, log = _vllm({})
    gw = _gw(tmp_path, http, doc)
    res = gw.chat(H(Data_Class="D3"), _judge_body())
    assert res.status == 403 and res.body["error"]["code"] == "no_eligible_build", res.body
    assert log == []
    named = gw.chat(H(Data_Class="D3"), {**_judge_body(), "model": "v-verifier"})  # the verifier, by name: answers
    assert named.status == 200 and named.body["tb"]["alias"] == "v-verifier"


# ------------------------------------------------------------------------------------------------ tb_llm
def _answer(tb: dict[str, Any] | None, fallbacks_header: str = "0") -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = {"model": "m", "choices": [{"message": {"content": "{}"}}]}
        if tb is not None:
            body["tb"] = tb
        return httpx.Response(200, json=body, headers={"X-TB-Fallbacks": fallbacks_header})

    return handler


@pytest.mark.parametrize(
    ("tb", "header", "named", "allow", "raises"),
    [
        ({"alias": "j-workhorse", "expected_alias": "j-workhorse", "fallbacks": 0}, "0", "", False, False),
        ({"alias": "v-verifier", "expected_alias": "j-workhorse", "fallbacks": 1}, "1", "", False, True),
        ({"alias": "v-verifier", "expected_alias": "j-workhorse", "fallbacks": 1}, "1", "", True, False),
        ({"alias": "v-verifier", "fallbacks": 0}, "1", "", False, True),  # the header alone says another answered
        ({"alias": "v-verifier", "fallbacks": 0}, "0", "j-workhorse", True, True),  # named: always that alias
        ({"alias": "j-workhorse", "fallbacks": "x"}, "0", "", False, True),  # unreadable count: as a fallback
        (None, "0", "", True, True),  # no tb: not the gateway's answer
        ({"build_sha": "x"}, "0", "", True, True),  # no alias
    ],
)
def test_tb_llm_raises_on_an_unexpected_alias(
    tb: dict[str, Any] | None, header: str, named: str, allow: bool, raises: bool
) -> None:
    c = GatewayClient(
        "http://gw/v1",
        "orchestrator",
        http=httpx.Client(transport=httpx.MockTransport(_answer(tb, header))),
        model=named or None,
        allow_fallback=allow,
    )
    labels = CallLabels("D0", "screening", "S", "s3_note_judgement", "judge", "judge@4")
    body = {"messages": [{"role": "user", "content": "x"}], "response_format": json_schema_format("judge", {})}
    if raises:
        with pytest.raises(GatewayUnexpectedAlias):
            c.complete(body, labels)
    else:
        c.complete(body, labels)


# ------------------------------------------------------------------------------------------------ the layers
def _mutant_combine() -> Callable[..., Any]:
    """``tb_common.pair.combine`` with the build comparison (D-276) removed, as a mutation tool would remove it."""
    import tb_common.pair as pair

    src = Path(pair.__file__).read_text(encoding="utf-8")
    line = "    if set(first.served) & set(second.served):"
    assert src.count(line) == 1, "the build comparison moved: update this mutation"
    mod = types.ModuleType("tb_pair_mutant")
    sys.modules[mod.__name__] = mod  # dataclasses look their module up while the class is made
    try:
        exec(compile(src.replace(line, "    if False:"), "pair_mutant.py", "exec"), mod.__dict__)
    finally:
        sys.modules.pop(mod.__name__, None)
    return mod.combine  # type: ignore[no-any-return]


def _one_build_twice(box_: Any) -> Any:
    """The judge client misnamed as the verifier's build (``TB_GATEWAY_MODEL=v-verifier``): both answers come from
    one build through the real gateway; only the pair's build comparison can tell."""
    _gw, llm, verifier, _fake, _tmp = _faulty(box_, {})
    assert llm.gateway is not None
    llm.gateway.model = "v-verifier"
    return _ask(_pair(llm, verifier))


def test_the_build_comparison_catches_one_build_twice(box: Any) -> None:  # noqa: F811
    r = _one_build_twice(box)
    assert (r.predicate, r.reason) == ("unknown", "model_down"), r


def test_a_mutation_that_removes_the_build_comparison_fails_the_test_above(
    box: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluate, "combine", _mutant_combine())
    r = _one_build_twice(box)
    with pytest.raises(AssertionError):  # the assertion of the test above no longer holds: the mutant is killed
        assert (r.predicate, r.reason) == ("unknown", "model_down"), r


def test_each_layer_alone_keeps_a_judge_outage_from_being_an_agreement(
    box: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three layers stop the verifier build from answering for a judge that is down: the gateway (no fallback for a
    patient role), tb_llm (an unexpected alias raises) and the pair (one build twice is no answer). Remove any two:
    the third still gives ``unknown`` with a failure. Remove all three: agreement, which is the defect (LLM-002)."""

    def run(gateway: bool, client: bool, builds: bool) -> Any:
        with monkeypatch.context() as m:
            if not gateway:
                m.setattr(RoutingPolicy, "no_fallback", lambda self, route, role, ctx="": False)
            if not builds:
                m.setattr(evaluate, "combine", _mutant_combine())
            _gw, llm, verifier, _fake, _tmp = _faulty(box, {JUDGE_HOST: "down"})
            assert llm.gateway is not None and verifier.gateway is not None
            llm.gateway.allow_fallback = verifier.gateway.allow_fallback = not client
            nj = _pair(llm, verifier)
            return _ask(nj), nj.failures

    for layers in [(True, False, False), (False, True, False), (False, False, True)]:
        r, failures = run(*layers)
        assert (r.predicate, r.reason) == ("unknown", "model_down") and failures >= 1, (layers, r)
    r, failures = run(False, False, False)
    assert r.reason != "model_down" and failures == 0, r  # the defect, when every layer is gone


# ------------------------------------------------------------------------------------------------ doctor
def _doctor_env(tmp_path: Path, **over: str) -> dict[str, str]:
    from tests.unit.test_gateway_box_phi import _dotenv, _pin

    env = {**_dotenv(), "TB_GATEWAY_URL": "http://gateway:8020/v1", "TB_REGISTRY_OVERRIDE": str(_pin(tmp_path))}
    env.update(over)
    return {k: v for k, v in env.items() if v != ""}


def _judge_route(env: dict[str, str]) -> Any:
    from tools.trialbox import doctor

    return doctor.check_judge_route(doctor.DoctorInputs(env=env))


def test_doctor_passes_when_the_gateway_takes_the_judge_and_the_verifier(tmp_path: Path) -> None:
    c = _judge_route(_doctor_env(tmp_path))
    assert c.status == "PASS" and "judge j-workhorse" in c.detail and "verifier v-verifier" in c.detail, c
    assert _judge_route({"TB_ENV": "PRODUCTION"}).status == "PASS"  # the judge does not use the gateway
    poc = _judge_route(  # the stub box of deploy/poc.sh: D0, TEST, the stub's second served name as the verifier
        _doctor_env(tmp_path / "poc", TB_ENV="TEST", TB_DATA_CLASS="D0", TB_GATEWAY_VERIFIER_MODEL="stub-verifier")
    )
    assert poc.status == "PASS" and "judge trialbox-stub" in poc.detail and "verifier stub-verifier" in poc.detail, poc


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"TB_REGISTRY_OVERRIDE": "/nonexistent/registry.site.yaml"}, "no_eligible_build"),  # no pins
        ({"TB_TOPOLOGY": "B"}, "step_unconfirmed"),  # D3 with no step outside the box policy (D-142)
        ({"TB_GATEWAY_MODEL": "x-external"}, "class_route_mismatch"),  # a judge build not on the patient route
        ({"TB_GATEWAY_VERIFIER_MODEL": "f-frontdesk"}, "class_route_mismatch"),  # the verifier, the same way
        ({"TB_ENV": "VALIDATION"}, "step_unconfirmed"),  # the box policy is PRODUCTION only
    ],
)
def test_doctor_fails_when_the_gateway_would_refuse_the_judge(tmp_path: Path, over: dict[str, str], why: str) -> None:
    c = _judge_route(_doctor_env(tmp_path, **over))
    assert c.status == "FAIL" and why in c.detail, c


def test_doctor_warns_in_test_when_the_gateway_would_refuse_the_judge(tmp_path: Path) -> None:
    c = _judge_route(_doctor_env(tmp_path, TB_ENV="TEST"))  # D3 in TEST: refused, a box being set up
    assert c.status == "WARN" and "would refuse the judge" in c.detail, c
