"""The Hermes serving path without the Hermes image (spec v4 §9.2-§9.4; S1-11).

Real sockets and real mTLS on loopback, certificates from ``deploy/hermes/prepare.py``:

* frontdoor-mcp's Streamable HTTP listener: client certificate required and allowlisted by CN; ``tools/list`` on the
  certificate alone; every ``tools/call`` needs the relay-minted assertion, carried in ``_tb_identity`` (added by
  ``tb_policy_audit``) or in headers (native engine), and the key never reaches the tool or its argument hash;
* the ``pre_tool_call`` decision endpoint (Hermes only, no rate budget);
* the SQL relay-token map shared by channel-relay and frontdoor-mcp (HER-12);
* channel-relay's Hermes edge (``/hermes/reply``) and :class:`HermesEngine`'s turn handling;
* ``tb_relay_adapter``'s inject listener (``channel-relay`` certificate only, refused envelopes get the reason);
* the stub model's deterministic tool-calling turn and the DEV/TEST profile render.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import itertools
import json
import ssl
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from channels.relay.hermes import FAILED_TEXT, HermesEngine, HermesReplies, MtlsHermesTransport
from channels.relay.listener import HermesReplyHandler
from cryptography.hazmat.primitives import serialization
from frontdoor_mcp.backends import LocalRegistryIndex, ReleaseIndex, StaticAggregates, StaticAtlas, StaticOps
from frontdoor_mcp.identity import AssertionSigner, AssertionVerifier, generate_relay_key
from frontdoor_mcp.listener import IDENTITY_KEY, NotStatedProtocol, make_listener, split_identity
from frontdoor_mcp.policy import Directory, OrchestratorPolicyContext, RateLimiter
from frontdoor_mcp.requests import RequestStore
from frontdoor_mcp.server import FrontDoorServer
from frontdoor_mcp.tokens import SqlRelayTokenMap, TokenRefused
from guard.guard import Guard
from llm_stub.agent import agent_turn
from orchestrator.db_pg import SqliteBackend, StepStore
from tb_common.audit import AuditLog
from tb_common.mtls import MtlsHTTPServer, client_context, serve_in_thread

from integrations.hermes import tb_relay_adapter as adapter

ROOT = Path(__file__).resolve().parents[2]
CRC = "crc1@hospa.test"
LOCK = ROOT / "integrations" / "hermes" / "hermes.lock"


def _prepare() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_hermes_prepare", ROOT / "deploy" / "hermes" / "prepare.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PREPARE = _prepare()


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """CA plus hermes / channel-relay / frontdoor-mcp / intruder certificates, written like prepare.py writes them."""
    d = tmp_path_factory.mktemp("pki")
    now = dt.datetime.now(dt.UTC)
    ca_key, ca = PREPARE.make_ca(now)
    (d / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    out = {"ca": str(d / "ca.pem")}
    for cn in ("hermes", "channel-relay", "frontdoor-mcp", "intruder"):
        key, cert = PREPARE.issue(ca_key, ca, cn, now, ("localhost",))
        (d / f"{cn}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (d / f"{cn}.key").write_bytes(PREPARE._key_pem(key))
        out[cn] = str(d / cn)
    return out


def _ctx(pki: dict[str, str], cn: str | None) -> ssl.SSLContext:
    if cn is None:
        return ssl.create_default_context(cafile=pki["ca"])
    return client_context(f"{pki[cn]}.pem", f"{pki[cn]}.key", pki["ca"])


def _post(
    url: str, body: Any, ctx: ssl.SSLContext, headers: Mapping[str, str] | None = None, method: str = "POST"
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json", **(headers or {})}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None


class Clock:
    t = 1_790_000_000.0

    def __call__(self) -> float:
        return self.t

    def dt(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.t, dt.UTC)


@pytest.fixture
def frontdoor(tmp_path: Path, pki: dict[str, str]) -> Iterator[dict[str, Any]]:
    clock = Clock()
    key = generate_relay_key()
    backend = SqliteBackend(":memory:")
    ids = itertools.count(1)
    alarms: list[tuple[str, str]] = []
    server = FrontDoorServer(
        verifier=AssertionVerifier(key.public_key(), clock),
        policy=OrchestratorPolicyContext(
            Directory.from_groups({"TB-CRC": [CRC]}, delegations={CRC: ["GZQO"]}), RateLimiter(clock)
        ),
        requests=RequestStore(backend, clock.dt, id_factory=lambda: f"T{next(ids):04d}"),
        audit=AuditLog(tmp_path / "audit"),
        tokens=SqlRelayTokenMap(backend, clock),
        registry=LocalRegistryIndex([]),
        protocol=NotStatedProtocol(),
        atlas=StaticAtlas(None, []),
        aggregates=StaticAggregates("none", {}),
        ops=StaticOps({}),
        releases=ReleaseIndex(),
        steps=StepStore(backend, "frontdoor", clock=clock.dt),
        guard=Guard("^\\d{8}$"),
        on_alarm=lambda reason, conv: alarms.append((reason, conv)),
    )
    fd = pki["frontdoor-mcp"]
    listener = make_listener(server, ("127.0.0.1", 0), cert=f"{fd}.pem", key=f"{fd}.key", ca=pki["ca"])
    serve_in_thread(listener, "fd-test")
    url = f"https://localhost:{listener.server_address[1]}"
    try:
        yield {
            "url": url,
            "signer": AssertionSigner(key, clock),
            "alarms": alarms,
            "audit": tmp_path / "audit",
            "backend": backend,
        }
    finally:
        listener.shutdown()
        listener.server_close()


def _records(audit: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines()]


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": args}}


# ------------------------------------------------------------------------------------------------ frontdoor-mcp
@pytest.mark.req("HER-15")
def test_split_identity_takes_the_argument_route_and_strips_it() -> None:
    msg = _call("tb.status", {"study": "GZQO", IDENTITY_KEY: {"assertion": "a.b.c", "conv": "c1"}})
    clean, assertion, conv = split_identity(msg, {"x-tb-assertion": "h.h.h", "x-tb-conv": "hc"})
    assert (assertion, conv) == ("a.b.c", "c1") and clean["params"]["arguments"] == {"study": "GZQO"}
    assert IDENTITY_KEY in msg["params"]["arguments"]  # the caller's message is not mutated
    assert split_identity(_call("tb.status", {}), {"x-tb-assertion": "h.h.h", "x-tb-conv": "hc"})[1:] == (
        "h.h.h",
        "hc",
    )
    bad = split_identity(_call("tb.status", {IDENTITY_KEY: "a.b.c"}), {"x-tb-assertion": "h.h.h"})
    assert bad[1:] == (None, None) and IDENTITY_KEY not in bad[0]["params"]["arguments"]


@pytest.mark.req("HER-15", "HER-8", "HER-14", "S1-11")
def test_listener_serves_mcp_over_mtls_and_needs_the_assertion_per_call(
    frontdoor: dict[str, Any], pki: dict[str, str]
) -> None:
    mcp, hermes = f"{frontdoor['url']}/mcp", _ctx(pki, "hermes")
    init = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}
    code, out = _post(mcp, init, hermes)
    assert code == 200 and out["result"]["protocolVersion"] == "2025-11-25"  # Hermes' SDK handshake revision
    assert _post(mcp, {"jsonrpc": "2.0", "method": "notifications/initialized"}, hermes)[0] == 202
    code, out = _post(mcp, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, hermes)
    assert code == 200 and "tb.submit_request" in [t["name"] for t in out["result"]["tools"]]
    assert _post(mcp, None, hermes, method="GET")[0] == 405

    # no assertion: refused and alarmed, whatever the certificate
    code, out = _post(mcp, _call("tb.status", {}), hermes)
    assert out["error"]["code"] == -32001 and frontdoor["alarms"] == [("assertion_missing", "")]
    # the per-turn assertion in _tb_identity (tb_policy_audit's modify directive)
    token = frontdoor["signer"].mint(sub=CRC, channel="email", conv="conv-9", msg="m-9")
    args = {"type": "FEAS", "study": "GZQO", "params": {}, "language": "en"}
    code, out = _post(
        mcp, _call("tb.submit_request", {**args, IDENTITY_KEY: {"assertion": token, "conv": "conv-9"}}), hermes
    )
    assert code == 200 and out["result"]["isError"] is False
    assert out["result"]["structuredContent"]["commands"] == ["FEAS GZQO scope=hospital lookback=24m"]
    # bound to its conversation: the same assertion for another conversation is refused
    code, out = _post(mcp, _call("tb.status", {IDENTITY_KEY: {"assertion": token, "conv": "conv-other"}}), hermes)
    assert out["error"]["code"] == -32001 and "assertion_conv" in out["error"]["message"]
    # the native engine's header route (channel-relay certificate)
    code, out = _post(
        mcp, _call("tb.status", {}), _ctx(pki, "channel-relay"), {"x-tb-assertion": token, "x-tb-conv": "conv-9"}
    )
    assert out["result"]["structuredContent"]["items"][0]["ticket_id"] == "T0001"

    calls = [r for r in _records(frontdoor["audit"]) if r["event"] in ("frontdoor.call.intent", "frontdoor.call")]
    from orchestrator.db_pg import canonical_json, sha256_text

    assert calls[0]["input_sha"] == sha256_text(canonical_json(args))  # the identity is not part of the arguments
    assert [r["detail"]["decision"] for r in calls] == ["intent", "allow", "intent", "allow"]
    assert [r["detail"]["user"] for r in calls] == [CRC] * 4


@pytest.mark.req("HER-5", "HER-15")
def test_listener_refuses_missing_and_unlisted_client_certificates(
    frontdoor: dict[str, Any], pki: dict[str, str]
) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    with pytest.raises((ssl.SSLError, urllib.error.URLError, ConnectionError)):
        _post(f"{frontdoor['url']}/mcp", body, _ctx(pki, None))
    with pytest.raises((ssl.SSLError, urllib.error.URLError, ConnectionError, OSError)):
        _post(f"{frontdoor['url']}/mcp", body, _ctx(pki, "intruder"))  # right CA, CN not on the allowlist


@pytest.mark.req("HER-1", "HER-15")
def test_policy_decide_is_hermes_only_and_spends_no_rate_budget(frontdoor: dict[str, Any], pki: dict[str, str]) -> None:
    url, token = (
        f"{frontdoor['url']}/policy/decide",
        frontdoor["signer"].mint(sub=CRC, channel="email", conv="c1", msg="m1"),
    )
    for _ in range(80):  # tb.status allows 60/h: decisions must not count
        code, out = _post(url, {"tool": "tb.status", "assertion": token, "conv": "c1"}, _ctx(pki, "hermes"))
        assert code == 200 and out == {"allow": True, "reason": "allow"}
    assert _post(url, {"tool": "tb.ops_read", "assertion": token, "conv": "c1"}, _ctx(pki, "hermes"))[1] == {
        "allow": False,
        "reason": "profile_not_allowed",
    }
    assert _post(url, {"tool": "tb.status", "conv": "c1"}, _ctx(pki, "hermes"))[1]["reason"] == "assertion_missing"
    assert _post(url, {"tool": "tb.status"}, _ctx(pki, "channel-relay"))[0] == 403


@pytest.mark.req("HER-12")
def test_sql_relay_tokens_bind_message_sender_conversation_and_expiry() -> None:
    clock = Clock()
    tokens = SqlRelayTokenMap(SqliteBackend(":memory:"), clock)
    t1 = tokens.mint(msg="m1", sender=CRC, conv="c1", kind="MRN", value="12345678")
    assert t1 == "[MRN-1]" and tokens.mint(msg="m1", sender=CRC, conv="c1", kind="MRN", value="12345678") == t1
    assert tokens.mint(msg="m1", sender=CRC, conv="c1", kind="MRN", value="87654321") == "[MRN-2]"
    assert tokens.resolve(t1, msg="m1", sender=CRC, conv="c1") == "12345678"
    for kw, reason in (
        ({"msg": "m2", "sender": CRC, "conv": "c1"}, "token_unknown"),
        ({"msg": "m1", "sender": "x@hospa.test", "conv": "c1"}, "token_binding"),
        ({"msg": "m1", "sender": CRC, "conv": "c2"}, "token_binding"),
    ):
        with pytest.raises(TokenRefused) as e:
            tokens.resolve(t1, **kw)
        assert e.value.reason == reason
    clock.t += 24 * 3600 + 1
    with pytest.raises(TokenRefused) as e:
        tokens.resolve(t1, msg="m1", sender=CRC, conv="c1")
    assert e.value.reason == "token_expired" and tokens.purge() == 2


# ------------------------------------------------------------------------------------------------ channel-relay
class FakeHermes:
    """Stands in for tb_relay_adapter + Hermes: answers each envelope through HermesReplies, like the real edge."""

    def __init__(self, replies: HermesReplies, texts: list[str], outcome: str = "success", on_inject: Any = None):
        self.replies, self.texts, self.outcome, self.on_inject = replies, texts, outcome, on_inject
        self.envelopes: list[Mapping[str, Any]] = []

    def inject(self, envelope: Mapping[str, Any]) -> None:
        self.envelopes.append(dict(envelope))

        def answer() -> None:
            if self.on_inject:
                self.on_inject(envelope)
            for t in self.texts:
                self.replies.deliver(str(envelope["conv"]), t)
            if self.outcome:
                self.replies.complete(str(envelope["conv"]), self.outcome)

        threading.Thread(target=answer).start()


def _assertion(conv: str = "conv-1") -> str:
    return AssertionSigner(generate_relay_key(), Clock()).mint(sub=CRC, channel="email", conv=conv, msg="sha256:m1")


@pytest.mark.req("S1-11", "HER-6", "FR-CONV-6")
def test_hermes_engine_turn_last_message_proposal_and_failures() -> None:
    replies = HermesReplies()
    open_tickets: list[str] = ["T-old"]
    fake = FakeHermes(
        replies, ["working on it", "I understand: ... Reply OK"], on_inject=lambda env: open_tickets.append("T-new")
    )
    eng = HermesEngine(LOCK, "TEST", transport=fake, replies=replies, open_proposals=lambda c, s: list(open_tickets))
    assert eng.available, eng.problems
    turn = eng.converse(text="feasible?", attachments=(), conv="conv-1", assertion=_assertion(), data_class="D0")
    assert turn.text == "I understand: ... Reply OK" and turn.proposal and turn.ticket_id == "T-new"
    env = fake.envelopes[0]
    assert env["origin"] == "channel-relay" and env["msg_sha256"] == "sha256:m1" and env["channel"] == "email"
    assert set(env) == {"origin", "conv", "msg_sha256", "channel", "assertion", "text"}  # text only, no attachments

    failed = HermesEngine(
        LOCK, "TEST", transport=FakeHermes(replies, ["Traceback: secret"], outcome="failure"), replies=replies
    )
    t2 = failed.converse(text="x", attachments=(), conv="conv-2", assertion=_assertion("conv-2"), data_class="D0")
    assert t2.text.startswith(FAILED_TEXT) and "secret" not in t2.text and t2.refused == "hermes_failure"
    slow = HermesEngine(
        LOCK, "TEST", transport=FakeHermes(replies, [], outcome=""), replies=replies, turn_timeout_s=0.2
    )
    t3 = slow.converse(text="x", attachments=(), conv="conv-3", assertion=_assertion("conv-3"), data_class="D0")
    assert t3.refused == "hermes_timeout"
    assert replies.deliver("conv-3", "late") is False  # a reply after the turn closed is never forwarded
    assert not HermesEngine(LOCK, "TEST").available  # no transport: the relay falls back to native


@pytest.mark.req("HER-6", "FR-CONV-16")
def test_relay_reply_edge_takes_hermes_only_and_open_turns_only(tmp_path: Path, pki: dict[str, str]) -> None:
    replies, audit = HermesReplies(), AuditLog(tmp_path / "audit")
    cr = pki["channel-relay"]
    srv = MtlsHTTPServer(
        ("127.0.0.1", 0),
        HermesReplyHandler,
        _server_ctx(cr, pki["ca"]),
        ("hermes",),
        state={"replies": replies, "audit": audit},
    )
    serve_in_thread(srv, "reply-test")
    url = f"https://localhost:{srv.server_address[1]}/hermes/reply"
    try:
        assert _post(url, {"conv": "c1", "text": "hi"}, _ctx(pki, "hermes"))[0] == 409
        turn = replies.open("c1")
        assert _post(url, {"conv": "c1", "text": "hi"}, _ctx(pki, "hermes")) == (200, {"accepted": True})
        assert _post(url, {"conv": "c1", "done": True, "outcome": "success"}, _ctx(pki, "hermes"))[0] == 200
        assert turn.done.is_set() and turn.texts == ["hi"] and turn.outcome == "success"
        with pytest.raises((ssl.SSLError, urllib.error.URLError, ConnectionError, OSError)):
            _post(url, {"conv": "c1", "text": "spoof"}, _ctx(pki, "channel-relay"))
        refusals = [r for r in _records(tmp_path / "audit") if r["event"] == "channel.hermes.reply.refuse"]
        assert len(refusals) == 1 and refusals[0]["detail"]["reason"] == "no_open_turn"
    finally:
        srv.shutdown()
        srv.server_close()


def _server_ctx(stem: str, ca: str) -> ssl.SSLContext:
    from tb_common.mtls import server_context

    return server_context(f"{stem}.pem", f"{stem}.key", ca)


# ------------------------------------------------------------------------------------------------ tb_relay_adapter
@pytest.mark.req("HER-6", "HER-7", "S1-11")
def test_adapter_inject_listener_accepts_only_channel_relay(pki: dict[str, str]) -> None:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    got: list[Any] = []
    checker = adapter.TbRelayAdapter(lambda conv, text: None)

    async def inject(envelope: Mapping[str, Any]) -> None:
        got.append(checker.accept(envelope))

    h = pki["hermes"]
    ctx = _server_ctx(h, pki["ca"])
    listener = adapter.InjectListener(("127.0.0.1", 0), ctx, loop, inject)
    listener.start()
    url = f"https://localhost:{listener.port}/inject"
    env = {
        "origin": "channel-relay",
        "conv": "c1",
        "msg_sha256": "m",
        "channel": "email",
        "assertion": "a.b.c",
        "text": "hello",
    }
    try:
        assert _post(url, env, _ctx(pki, "channel-relay")) == (202, {"accepted": True})
        assert _post(url, {**env, "assertion": "nope"}, _ctx(pki, "channel-relay")) == (
            403,
            {"refused": "assertion_missing"},
        )
        assert _post(url, {**env, "channel": "line"}, _ctx(pki, "channel-relay"))[1] == {
            "refused": "line_never_reaches_hermes"
        }
        with pytest.raises((ssl.SSLError, urllib.error.URLError, ConnectionError, OSError)):
            _post(url, env, _ctx(pki, "hermes"))  # only the relay may inject
        assert len(got) == 1 and got[0].conv == "c1"
    finally:
        listener.stop()
        loop.call_soon_threadsafe(loop.stop)


@pytest.mark.req("HER-7")
def test_contract_requires_the_serving_surface() -> None:
    from integrations.hermes.contract import HermesSurface, contract_problems

    problems = contract_problems(HermesSurface())
    assert "PlatformEntry lacks fields ['trusted_inbound']" in problems
    assert any("'modify' directives" in p for p in problems)
    assert any("on_processing_complete missing" in p for p in problems)


# ------------------------------------------------------------------------------------------------ stub + deploy
@pytest.mark.req("S1-11")
def test_stub_agent_turn_calls_front_door_tools_and_answers_from_wrapped_results() -> None:
    tools = [
        {"type": "function", "function": {"name": n}}
        for n in ("mcp__frontdoor__tb_status", "mcp__frontdoor__tb_submit_request")
    ]
    msg, finish = agent_turn(
        {
            "messages": [{"role": "user", "content": "How many patients could GZQO find over the last 3 years?"}],
            "tools": tools,
        }
    )
    call = msg["tool_calls"][0]["function"]
    assert finish == "tool_calls" and call["name"] == "mcp__frontdoor__tb_submit_request"
    assert json.loads(call["arguments"]) == {
        "type": "FEAS",
        "study": "GZQO",
        "params": {"lookback": "36m"},
        "language": "en",
    }
    msg, _ = agent_turn({"messages": [{"role": "user", "content": "status please"}], "tools": tools})
    assert msg["tool_calls"][0]["function"]["name"] == "mcp__frontdoor__tb_status"
    inner = json.dumps(
        {"restatement": "I understand.", "commands": ["FEAS GZQO lookback=36m"], "confirm_instruction": "Reply OK."}
    )
    wrapped = f"<untrusted_tool_result server=frontdoor>\n{json.dumps({'result': inner})}\n</untrusted_tool_result>"
    msg, finish = agent_turn({"messages": [{"role": "tool", "content": wrapped}], "tools": tools})
    assert finish == "stop" and msg["content"] == "I understand.\nFEAS GZQO lookback=36m\nReply OK."


@pytest.mark.req("HER-16", "S1-11")
def test_prepare_renders_dev_profile_and_directory_only(tmp_path: Path) -> None:
    assert PREPARE.main(["--out", str(tmp_path / "s"), "--env", "TEST", "--admin-email", "a@hospa.test"]) == 0
    out = tmp_path / "s"
    cfg = yaml.safe_load((out / "hermes-config.yaml").read_text())
    committed = yaml.safe_load((ROOT / "integrations/hermes/profiles/tb-staff/config.yaml").read_text())
    assert cfg["model"]["default"] == "f-frontdesk" and cfg["model"]["default_headers"]["X-TB-Data-Class"] == "D0"
    cfg["model"]["default"] = committed["model"]["default"]
    cfg["model"]["default_headers"]["X-TB-Data-Class"] = committed["model"]["default_headers"]["X-TB-Data-Class"]
    assert cfg == committed  # nothing else differs from the reviewed profile
    assert "a@hospa.test" in yaml.safe_load((out / "directory.yaml").read_text())["groups"]["TB-CRC"]
    assert not (out / "ca.key").exists() and (out / "relay.pub").exists()
    assert PREPARE.main(["--out", str(out), "--env", "PRODUCTION"]) == 2  # needs the directory-group export
    directory = tmp_path / "dir.yaml"
    directory.write_text(yaml.safe_dump({"groups": {"TB-Staff": ["s@hospa.test"]}}))
    assert PREPARE.main(["--out", str(out), "--env", "PRODUCTION", "--directory", str(directory)]) == 0
    assert not (out / "hermes-config.yaml").exists()  # production mounts the committed profile


def test_mtls_transport_requires_https() -> None:
    with pytest.raises(ValueError):
        MtlsHermesTransport("http://hermes:8444/inject", ssl.create_default_context())
