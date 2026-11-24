"""T-608 (D-445; deep review LLM-023, LLM-022, LLM-032, LLM-046): the gateway under load.

The acceptance test is a model server that never answers (a socket that accepts and stays silent) and 100 parallel
calls: no thread exhaustion (health answers at once, the threads stay bounded), the front desk hears ``model_busy`` in
under a second, and ``/readyz`` shows the open breaker. Every limit is scaled down so it runs in seconds. The other
tests cover one timeout budget, one retry on a dropped connection, the swap hold that names its service, the
``service`` field of audit records, the judge schema on the cascade path, the tools' "not measured" lists, the stub's
estimated token counts and the model key's two copies. All data is synthetic.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway.app import StartCheck, create_app
from gateway.core import Gateway, GatewayConfig
from gateway.load import INTERACTIVE_SLOT_WAIT_S, Breaker, LoadControl, record_slots
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from llm_stub.app import app as stub
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment
from tb_llm import CallLabels, GatewayClient, GatewayError
from tb_llm import timeouts as tt

from tests.unit.test_gateway import H, _judge_body, _records
from tests.unit.test_model_swap import CHAT_BODY, CHAT_H, JH, FakeVllm, _swap
from tests.unit.test_model_swap import _gw as _swap_gw
from tools.timing_bound import bound

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ a silent server
class Silent:
    """A model server that accepts connections and never answers."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(512)
        self.port = self.sock.getsockname()[1]
        self.conns: list[socket.socket] = []
        self.stop = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        self.sock.settimeout(0.1)
        while not self.stop.is_set():
            try:
                c, _ = self.sock.accept()
            except OSError:
                continue
            self.conns.append(c)  # held open, never read, never answered

    def close(self) -> None:
        self.stop.set()
        for c in self.conns:
            c.close()
        self.sock.close()


_SECONDS = {  # every limit of D-445, scaled down so the test runs in seconds
    "TB_GATEWAY_INTERACTIVE_TIMEOUT_S": 1.0,
    "TB_GATEWAY_UPSTREAM_READ_S": 2.0,
    "TB_GATEWAY_CALL_BUDGET_S": 3.0,
    "TB_GATEWAY_RETRY_DELAY_S": 0.01,
    "TB_GATEWAY_STALL_S": 0.5,
    "TB_GATEWAY_WATCH_S": 0.1,
}
# the branch tracer slows the loop that starts the 100 calls: every time limit grows by the coverage factor in a run
# that measures coverage (tools/timing_bound.py), so the breaker is no sooner open than the front desk's call; the
# counts are not times and stay
SCALED = {
    **{k: str(bound(v)) for k, v in _SECONDS.items()},
    "TB_GATEWAY_SLOTS": "16",
    "TB_GATEWAY_MAX_INFLIGHT": "64",
}


def _silent_gw(tmp_path: Path, port: int) -> Gateway:
    env = {"TB_EP_STUB_URL": f"http://127.0.0.1:{port}/v1", **SCALED}
    return Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=Environment.TEST),
        guard=Guard("^\\d{8}$"),
        env=env,
    )


FRONT = {**CHAT_H, "X-TB-Data-Class": "D0"}  # the front desk's classifier (an interactive role)
#: whose call asked the queue: set around the front desk's own requests (the context follows each request into its
#: worker thread); the 100 batch calls were created before it is set, so they carry the default
ASKER: contextvars.ContextVar[str] = contextvars.ContextVar("asker", default="batch")


def test_a_server_that_never_answers_100_parallel_calls(tmp_path: Path) -> None:
    silent = Silent()
    gw = _silent_gw(tmp_path, silent.port)
    app = create_app(gw)
    # what each call asked the endpoint's queue for (D-635: the test says what it means by orderings and by what the
    # gateway asked for, not by wall-clock bounds, which measured the runner: 1.06 s against 1.0 s on a loaded one)
    lane = gw.load.get("stub")
    waits: list[tuple[str, float]] = []
    real_acquire = lane.acquire

    def acquire(wait_s: float) -> int | None:
        waits.append((ASKER.get(), wait_s))
        return real_acquire(wait_s)

    def front_waits() -> list[float]:
        """What the front desk's own calls asked the queue for. A batch call whose worker thread starts late asks
        while the front desk's call is in flight too (job 135099756380: [2.99..., 0.5]); it is not the front desk's."""
        return [w for who, w in waits if who == "front"]

    async def front(c: httpx.AsyncClient) -> httpx.Response:
        token = ASKER.set("front")
        try:
            return await c.post("/v1/chat/completions", json=CHAT_BODY, headers=FRONT)
        finally:
            ASKER.reset(token)

    lane.acquire = acquire  # type: ignore[method-assign]
    stop = threading.Event()
    threading.Thread(target=gw.load.loop, args=(stop,), daemon=True).start()  # the lifespan's watch thread
    base_threads = threading.active_count()
    peak = {"threads": base_threads}

    async def run() -> dict[str, Any]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw", timeout=30) as c:
            t0 = time.monotonic()
            calls = [
                asyncio.create_task(c.post("/v1/chat/completions", json=_judge_body(), headers=H())) for _ in range(100)
            ]
            await asyncio.sleep(0.3)  # the calls are in flight now
            peak["threads"] = max(peak["threads"], threading.active_count())
            health = await c.get("/healthz")
            ready = await c.get("/readyz")
            hanging = sum(1 for call in calls if not call.done())  # health answered while calls still hang
            busy = await front(c)
            busy_waits = front_waits()
            opened_at = None
            while time.monotonic() - t0 < 10:
                r = (await c.get("/readyz")).json()
                peak["threads"] = max(peak["threads"], threading.active_count())
                if "stub" in r["breakers_open"]:
                    opened_at = time.monotonic() - t0
                    break
                await asyncio.sleep(0.05)
            after = await front(c)
            after_waits = front_waits()[len(busy_waits) :]
            done = await asyncio.gather(*calls)
            # the 100 are over; the breaker is still open: a batch call is not sent either
            batch_after = await c.post("/v1/chat/completions", json=_judge_body(), headers=H())
            return {
                "health": health,
                "ready": ready,
                "hanging": hanging,
                "busy": busy,
                "busy_waits": busy_waits,
                "opened_at": opened_at,
                "after": after,
                "after_waits": after_waits,
                "batch_after": batch_after,
                "done": done,
            }

    try:
        out = asyncio.run(run())
    finally:
        stop.set()
        silent.close()
    # no thread exhaustion: health answers at once while 100 calls hang; the threads stay bounded
    assert out["health"].status_code == 200 and out["ready"].status_code == 200
    assert out["hanging"] > 0, "health did not answer while calls were hanging"
    assert peak["threads"] - base_threads <= 64 + 8, peak
    # the front desk: model_busy after the short interactive wait for a slot, never the batch budget; and at once,
    # without queueing at all, once the breaker is open
    assert out["busy"].status_code == 503 and out["busy"].json()["error"]["code"] == "model_busy"
    assert out["busy_waits"] == [INTERACTIVE_SLOT_WAIT_S] and out["busy"].headers["retry-after"]
    assert float(SCALED["TB_GATEWAY_CALL_BUDGET_S"]) / 2 > INTERACTIVE_SLOT_WAIT_S
    # /readyz shows the open breaker (60 s on a box; scaled here: stall 0.5 s, watch 0.1 s)
    assert out["opened_at"] is not None  # within the loop's ten seconds
    assert out["after"].json()["error"]["code"] == "model_busy" and out["after_waits"] == []
    assert out["batch_after"].status_code == 503
    assert out["batch_after"].json()["error"]["code"] == "model_unavailable"
    # every call ended within its budget: refused at once, out of slots, or timed out; none answered
    codes = sorted({r.json()["error"].get("code", "") for r in out["done"]})
    assert {r.status_code for r in out["done"]} <= {502, 503}, codes
    assert "model_busy" in codes  # the calls beyond the thread limit were told at once
    ready = out["ready"].json()
    assert ready["max_in_flight"] == 64 and ready["endpoints"]["stub"]["slots"] == 16


def test_the_lifespan_starts_the_load_watch(tmp_path: Path) -> None:
    gw = _silent_gw(tmp_path, 9)
    with TestClient(create_app(gw)) as c:
        assert any(t.name == "gateway-load-watch" and t.is_alive() for t in threading.enumerate())
        assert c.get("/readyz").json()["status"] == "ready"


# ------------------------------------------------------------------------------------------------ one budget
def test_one_timeout_budget_across_the_three_layers(tmp_path: Path) -> None:
    assert tt.CALLER_TIMEOUT_S > tt.CALL_BUDGET_S > tt.UPSTREAM_READ_S + tt.RETRY_DELAY_S
    t = tt.caller_timeout({})
    assert t.read == tt.CALLER_TIMEOUT_S and t.connect == tt.CONNECT_S
    assert tt.caller_timeout({"TB_LLM_TIMEOUT_S": "60"}).read == 60
    assert GatewayClient("http://gw/v1", "x").http.timeout.read == tt.CALLER_TIMEOUT_S
    gw = Gateway(RoutingPolicy.load(), Registry.load(), AuditLog(tmp_path / "audit"), env={})
    assert gw.http.timeout.read == tt.UPSTREAM_READ_S and gw.http.timeout.connect == tt.CONNECT_S
    assert gw.call_budget_s == tt.CALL_BUDGET_S


def test_the_budget_stops_the_retry_and_cuts_each_attempt(tmp_path: Path) -> None:
    seen: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.extensions["timeout"]["read"])
        raise httpx.ConnectError("dropped", request=req)

    gw = _silent_gw(tmp_path, 9)
    gw.http = httpx.Client(transport=httpx.MockTransport(handler))
    gw.call_budget_s, gw.retry_delay_s = 1.3, 0.5  # one attempt fits, the retry (0.5 s + 1 s) does not
    res = gw.chat(H(), _judge_body())
    assert res.status == 502 and len(seen) == 1 and seen[0] <= 1.3, seen


# ------------------------------------------------------------------------------------------------ one retry
def _labels() -> CallLabels:
    return CallLabels("D0", "screening", "S-1", "s3_note_judgement", "judge", "judge@4")


@pytest.mark.parametrize(
    ("first", "tries"),
    [
        (httpx.ConnectError("refused"), 2),
        (httpx.RemoteProtocolError("dropped"), 2),
        (httpx.ReadError("reset"), 2),
        (httpx.ReadTimeout("slow"), 1),  # the gateway may still be working on it: never sent again
    ],
)
def test_tb_llm_sends_a_dropped_call_once_more_never_a_timed_out_one(
    first: Exception, tries: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tt, "RETRY_DELAY_S", 0.0)
    bodies: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(req.content)
        if len(bodies) == 1:
            first.request = req  # type: ignore[attr-defined]
            raise first
        tb = {"alias": "j", "expected_alias": "j", "fallbacks": 0, "call_id": "c"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "tb": tb})

    client = GatewayClient("http://gw/v1", "orchestrator", http=httpx.Client(transport=httpx.MockTransport(handler)))
    body = {"messages": [{"role": "user", "content": "x"}], "response_format": {"type": "json_schema"}}
    if tries == 1:
        with pytest.raises(GatewayError):
            client.complete(body, _labels())
    else:
        assert client.complete(body, _labels())["tb"]["alias"] == "j"
    assert len(bodies) == tries and len(set(bodies)) == 1  # the same body: the same role and build


def test_the_direct_path_of_tb_common_llm_retries_a_dropped_connection_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.llm import LlmClient

    monkeypatch.setattr(tt, "RETRY_DELAY_S", 0.0)
    n = {"posts": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["posts"] += 1
        if n["posts"] == 1:
            raise httpx.ConnectError("refused", request=req)
        r: httpx.Response = TestClient(stub).post(
            "/v1/chat/completions", content=req.content, headers=dict(req.headers)
        )
        return r

    llm = LlmClient("http://stub/v1", "trialbox-stub")
    llm.http = httpx.Client(transport=httpx.MockTransport(handler))
    from tests.unit.test_gateway import JUDGE_VARS

    res = llm.chat_json("judge_v4", JUDGE_VARS)
    assert res.data["verdict"] == "pass" and n["posts"] == 2


def test_dropped_says_which_errors_are_worth_one_more_try() -> None:
    assert tt.dropped(httpx.ConnectTimeout("x")) and tt.dropped(httpx.WriteError("x"))
    assert not tt.dropped(httpx.ReadTimeout("x")) and not tt.dropped(httpx.PoolTimeout("x"))
    assert not tt.dropped(ValueError("x"))


# ------------------------------------------------------------------------------------------------ breaker, slots
def test_the_breaker_opens_lets_one_through_and_closes() -> None:
    now = [0.0]
    b = Breaker(failures=3, open_s=10, clock=lambda: now[0])
    for _ in range(2):
        b.failure()
    assert b.allow() and b.state == "closed"
    b.failure()
    assert b.state == "open" and not b.allow()
    now[0] = 10.0
    assert b.allow() and b.state == "half_open" and not b.allow()  # one at a time
    b.failure()
    assert b.state == "open" and b.opens == 2
    now[0] = 20.0
    assert b.allow()
    b.cancel()  # not sent (no slot): another may try
    assert b.allow()
    b.success()
    assert b.state == "closed" and b.failures == 0


def test_a_stall_opens_the_breaker_only_when_the_server_does_not_answer() -> None:
    now = [0.0]
    alive = {"stub": True}
    lc = LoadControl(["stub"], {"TB_GATEWAY_STALL_S": "40"}, clock=lambda: now[0], probe=lambda n: alive[n])
    ep = lc.get("stub")
    ticket = ep.acquire(0)
    assert ticket is not None
    now[0] = 39.0
    assert lc.sweep() == []  # not stalled yet
    now[0] = 41.0
    assert lc.sweep() == [] and lc.open() == []  # stalled, but the server answers: slow, not dead
    alive["stub"] = False
    assert lc.sweep() == ["stub"] and lc.open() == ["stub"]
    assert lc.snapshot()["stub"]["reason"] == "stalled" and lc.snapshot()["stub"]["in_flight"] == 1
    ep.release(ticket)


def test_slots_come_from_the_serving_record(tmp_path: Path) -> None:
    rec = json.loads((ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json").read_text(encoding="utf-8"))
    assert record_slots(ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json") == {
        "serving": 16,
        "verifier": 16,
    }
    rec["servers"][0]["max_num_seqs"] = 4
    p = tmp_path / "record.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    lc = LoadControl(["serving", "verifier", "stub"], {"TB_SERVING_RECORD": str(p), "TB_GATEWAY_SLOTS": "7"})
    slots = {n: s["slots"] for n, s in lc.snapshot().items()}
    assert slots["stub"] == 7 and 4 in (slots["serving"], slots["verifier"])
    assert record_slots(tmp_path / "missing.json") == {} and record_slots(None) == {}


def test_an_interactive_call_without_a_slot_is_busy_at_once(tmp_path: Path) -> None:
    gw = _silent_gw(tmp_path, 9)
    gw.http = TestClient(stub)
    lane = gw.load.get("stub")
    held = [lane.acquire(0) for _ in range(lane.slots)]
    t = time.monotonic()
    res = gw.chat(FRONT, CHAT_BODY)
    assert res.status == 503 and res.body["error"]["code"] == "model_busy" and time.monotonic() - t < 1.0
    assert res.headers["Retry-After"] == "5"
    for tk in held:
        assert tk is not None
        lane.release(tk)
    assert gw.chat(FRONT, CHAT_BODY).status == 200


# ------------------------------------------------------------------------------------------------ the swap hold
def test_a_hold_belongs_to_its_service_and_no_call_wakes_across_it(tmp_path: Path) -> None:
    """Audit and PR #263 review: a doc-parser or criteria-compiler call put the judge to sleep during a hold."""
    fake = FakeVllm()
    sw = _swap(fake)
    gw = _swap_gw(tmp_path, fake, sw)
    act = gw.activate("orchestrator", "verifier", hold=True, service="orchestrator")
    assert act.status == 200 and sw.holder == "orchestrator" and act.body["holder"] == "orchestrator"
    ir = H(Caller="criteria-compiler", Role="extract_criteria", Purpose="protocol_ingest", Prompt="ir_extract@2",
           Data_Class="D1", Context_Of_Use="protocol_criteria_extraction")  # fmt: skip
    from tests.unit.test_gateway import _ir_body

    other = gw.chat(ir, _ir_body(), service="criteria-compiler")
    assert other.status == 503 and other.body["error"]["code"] == "model_busy"  # told at once, not "activate"
    own = gw.chat(JH, _judge_body(), service="orchestrator")
    assert own.status == 503 and own.body["error"]["code"] == "model_asleep"
    assert sw.active == "verifier" and sw.swaps == 1 and fake.sleeping["llm-service"]  # nothing woke
    assert not any(x.endswith("/chat/completions") for x in fake.log)
    # touch: only the holder's own calls keep the hold alive
    sw.held_until = time.monotonic() + 1.0
    sw.touch("criteria-compiler")
    assert sw.held_until < time.monotonic() + 2.0
    sw.touch("orchestrator")
    assert sw.held_until > time.monotonic() + 100
    rel = gw.release("orchestrator", service="orchestrator")
    assert rel.status == 200 and sw.holder == "" and not sw.held
    # no hold: the compiler's own route may wake its model (protocol compilation outside a screening run)
    ok = gw.chat(ir, _ir_body(), service="criteria-compiler")
    assert ok.status == 200 and sw.active == "serving" and sw.on_demand == 1
    swaps = [r["detail"] for r in _records(tmp_path) if r["event"] == "llm.gateway.swap"]
    assert [d["service"] for d in swaps] == ["orchestrator", "criteria-compiler"]
    assert swaps[1]["caller"] == "on-demand"
    (release,) = [r["detail"] for r in _records(tmp_path) if r["event"] == "llm.gateway.swap_release"]
    assert release["service"] == "orchestrator"


def test_a_hold_taken_meanwhile_wins_over_an_on_demand_wake() -> None:
    fake = FakeVllm()
    sw = _swap(fake)
    sw.activate("verifier", hold=True, holder="orchestrator")
    sw.held_until = 0.0  # lapsed
    sw.held_until = time.monotonic() + 60  # ... and taken again before the wake gets the lock
    assert sw.activate("serving", on_demand=True)["active"] == "verifier"
    assert not sw.ensure("serving") and sw.on_demand == 0


def test_a_failed_swap_and_a_start_check_refusal_name_the_service(tmp_path: Path) -> None:
    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    fake = FakeVllm()
    sw = _swap(fake)
    sw.http = httpx.Client(transport=httpx.MockTransport(down))
    sw.wake_timeout_s = 0.05
    gw = _swap_gw(tmp_path, fake, sw)
    assert gw.activate("orchestrator", "verifier", service="orchestrator").status == 502
    (failed,) = [r["detail"] for r in _records(tmp_path) if r["event"] == "llm.gateway.swap_failed"]
    assert failed["service"] == "orchestrator"
    flag = tmp_path / "weights_changed.json"
    flag.write_text(json.dumps({"lines": ["j-test-1: synthetic mismatch"]}), encoding="utf-8")
    sc = StartCheck(gw, {"TB_WEIGHTS_FLAG": str(flag)}, get=lambda url, key: (None, "down"))
    c = TestClient(create_app(gw, sc))
    r = c.post("/v1/chat/completions", json=_judge_body(), headers=H(Data_Class="D3"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "weights_changed"
    refused = [r["detail"] for r in _records(tmp_path) if r["event"] == "llm.gateway.refuse"]
    assert refused[-1]["reason"] == "weights_changed" and "service" in refused[-1]
    assert refused[-1]["caller"] == "orchestrator"


# ------------------------------------------------------------------------------------------------ judge schema


def test_the_cascade_judge_validates_the_answer_against_the_schema() -> None:
    from datetime import date

    from matching.cascade.judge import GatewayJudge

    class Res:
        def __init__(self, data: Any) -> None:
            self.data, self.call_id, self.build_sha, self.tokens_in, self.tokens_out = data, "c1", "b", 1, 1

    class Client:
        def __init__(self, data: Any) -> None:
            self.data = data

        def chat(self, *a: Any, **kw: Any) -> Res:
            return Res(self.data)

    kw: dict[str, Any] = {
        "role": "judge",
        "criterion_text": "x",
        "note_question": "gout flare?",
        "index_date": date(2026, 10, 5),
        "excerpts": [],
        "study_id": "S-1",
        "data_class": "D0",
        "step_id": "s",
        "purpose": "screening",
    }
    good = {"verdict": "pass", "confidence": 0.9, "quote": "q", "quote_date": "2026-10-01", "reason": "r"}
    j = GatewayJudge(Client(good))
    ok = j.judge(**kw)
    assert ok.verdict == "pass" and ok.refused is None, ok
    for bad in ({"verdict": "PASS!", "confidence": 0.9}, {"verdict": "pass", "confidence": "high"}, ["pass"], None):
        r = GatewayJudge(Client(bad)).judge(**kw)
        assert r.verdict == "unknown" and r.refused == "schema_invalid", bad


# ------------------------------------------------------------------------------------------------ the tools


def test_judge_eval_on_the_stub_says_it_is_a_wiring_test(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from tools import judge_eval

    items = (ROOT / "eval" / "qualification" / "judge_set.jsonl").read_text(encoding="utf-8").splitlines()[:5]
    p = tmp_path / "set.jsonl"
    p.write_text("\n".join(items) + "\n", encoding="utf-8")
    assert judge_eval.main(["--set", str(p), "--gateway-url", ""]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "stub wiring test" and any("by construction" in x for x in report["not_measured"])


def test_judge_eval_goes_through_a_gateway_with_a_model(tmp_path: Path) -> None:
    from tools.judge_eval import GatewayEval, evaluate

    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(tmp_path / "audit"),
        GatewayConfig(environment=Environment.TEST),
        http=TestClient(stub),
        guard=Guard("^\\d{8}$"),
        env={},
    )
    client = GatewayClient("http://gw/v1", "eval", http=TestClient(create_app(gw)))
    items = [json.loads(x) for x in (ROOT / "eval/qualification/judge_set.jsonl").read_text().splitlines()[:3]]
    report = evaluate(items, GatewayEval(client))
    assert report["n"] == 3
    calls = [r for r in _records(tmp_path) if r["event"] == "llm.gateway.call"]
    assert len(calls) == 3 and {r["actor"] for r in calls} == {"eval"}  # the gateway's sampling and audit applied
    assert all(r["detail"]["tokens_estimated"] for r in calls)  # LLM-046: the stub's counts are marked


def test_the_bakeoff_plan_says_what_it_does_not_measure() -> None:
    from tools import bakeoff

    p = bakeoff.plan(n=2, langs=["ja"])
    assert p["tokens"].startswith("estimate") and p["not_measured"] == bakeoff.NOT_MEASURED
    text = bakeoff.render(p, [])
    assert "not measured by this plan" in text and "(est.)" in text


def test_the_stub_counts_tokens_like_the_budget_and_says_they_are_estimates() -> None:
    from tb_llm.budget import estimate_messages

    msgs = [{"role": "user", "content": "診斷為急性痛風發作中。" * 20}]
    body = {"model": "trialbox-stub", "messages": msgs}
    from llm_stub.app import _completion

    usage = _completion(body, {"role": "assistant", "content": "{}"}, "stop")["usage"]
    assert usage["estimated"] is True and usage["prompt_tokens"] == estimate_messages(msgs)
    assert usage["prompt_tokens"] > len(msgs[0]["content"]) // 4 * 3  # CJK: about one token per character


# ------------------------------------------------------------------------------------------------ model key copy
def test_a_hand_changed_model_key_copy_is_refused_not_overwritten(tmp_path: Path) -> None:
    from tools.trialbox import svc_secrets as sx

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    env = deploy / ".env"
    env.write_text("TB_LLM_API_KEY=synthetic-key-one\n", encoding="utf-8")
    assert sx.ensure_model_key(deploy, env, None)  # made from .env's copy
    assert sx.model_key_path(deploy).read_text(encoding="utf-8").strip() == "synthetic-key-one"
    env.write_text("TB_LLM_API_KEY=synthetic-key-two\n", encoding="utf-8")  # changed by hand
    with pytest.raises(sx.SecretsError, match="differs"):
        sx.ensure_model_key(deploy, env, None)
    assert "synthetic-key-two" in env.read_text(encoding="utf-8")  # nothing was changed
    env.write_text("TB_LLM_API_KEY=\n", encoding="utf-8")  # an empty copy is filled from the file
    assert not sx.ensure_model_key(deploy, env, None)
    assert "synthetic-key-one" in env.read_text(encoding="utf-8")


def test_v1_roles_is_read_once() -> None:
    from tb_llm import client as cl

    cl._v1_roles.cache_clear()
    for _ in range(5):
        cl.v1_labels("judge", 4, phi=True, study_id="S-1", data_class="D0")
    assert cl._v1_roles.cache_info().misses == 1
