"""Channel abstraction and native engine (spec v4 §3.4, §9.2; S1-10).

Done-when (S1-10): on ``channels.engine: native``, 「這個試驗做得起來嗎」 plus a PDF yields a proposal, and ``OK``
starts FEAS. Also: grammar lines run deterministically without a model (FR-CONV-1), unknown senders never reach the
engine (FR-CONV-14), every turn is audited before the reply (FR-CONV-16), Teams is a fake transport without PHI and
without approvals (FR-UX-11), and an engine switch loses no request (FR-CONV-6).

``classify_intent`` runs through the real ``tb-gateway`` (TEST environment, D0, route ``dev-stub``) with a
deterministic stub upstream answering as the ``trialbox-stub`` build. No network.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import httpx
import pytest
from channels.config import ChannelsConfig, ChannelsConfigError
from channels.grammar import GrammarError, Line, parse_line
from channels.native.email import EmailChannel
from channels.native.engine import NativeEngine, detect_language
from channels.native.teams import FakeBotFramework, FakeTeamsTransport, TeamsChannel
from channels.relay.hermes import HermesEngine
from channels.relay.relay import ChannelRelay, Intake, strip
from fastapi.testclient import TestClient
from frontdoor_mcp.backends import LocalRegistryIndex, ReleaseIndex, StaticAggregates, StaticAtlas, StaticOps
from frontdoor_mcp.identity import AssertionSigner, AssertionVerifier, generate_relay_key
from frontdoor_mcp.policy import Directory, OrchestratorPolicyContext, RateLimiter
from frontdoor_mcp.requests import RequestStore
from frontdoor_mcp.server import FrontDoorServer
from frontdoor_mcp.tokens import RelayTokenMap
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from orchestrator.db_pg import SqliteBackend, StepStore
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology
from tb_llm import GatewayClient

ROOT = Path(__file__).resolve().parents[2]
CRC = "crc1@hospa.test"
AAD_CRC = "aad-0001"
PDF = (ROOT / "tests" / "fixtures" / "protocols" / "GZQO_protocol_v3.pdf").read_bytes()
T0 = 1_790_000_000.0


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> float:
        return self.t

    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.t, UTC)


def classify_stub(inp: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for the classify_intent model (keyword rules over the tokenised text)."""
    text: str = inp["text"]
    lang = inp["language"]
    study = next(iter(re.findall(r"\b[A-Z]{4}\b", text)), None)
    if re.search(r"做得起來|feasib|how many|何例", text, re.I):
        out: dict[str, Any] = {"type": "FEAS", "study": study, "language": lang}
        if "三年" in text or "3 years" in text:
            out["lookback_months"] = 36
        return out
    if "allowed" in text.lower():
        return {"type": "ASK", "study": study, "question": text[:200], "language": lang}
    return {"type": "UNKNOWN", "language": lang}


class Upstream:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            assert req.headers.get("x-tb-prompt-id") == "classify_intent"
            user = next(m["content"] for m in body["messages"] if m["role"] == "user")
            inp = json.loads(user.split("```json", 1)[1].split("```", 1)[0])
            self.inputs.append(inp)
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [{"message": {"role": "assistant", "content": json.dumps(classify_stub(inp))}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        return httpx.Client(transport=httpx.MockTransport(handler))


class Jobs:
    def __init__(self) -> None:
        self.started: list[tuple[Line, str, str | None, dict[str, str]]] = []

    def start(self, line: Line, *, sender: str, ticket_id: str | None, refs: Mapping[str, str]) -> str:
        self.started.append((line, sender, ticket_id, dict(refs)))
        return f"JOB-{len(self.started):04d}"


def build(tmp_path: Path, engine: str = "native", backend: SqliteBackend | None = None) -> dict[str, Any]:
    clock = Clock()
    key = generate_relay_key()
    signer = AssertionSigner(key, clock)
    directory = Directory.from_groups({"TB-CRC": [CRC]}, delegations={CRC: ["GZQO"]})
    backend = backend or SqliteBackend(":memory:")
    ids = itertools.count(1)
    requests = RequestStore(backend, clock.dt, id_factory=lambda: f"T{next(ids):04d}")
    tokens = RelayTokenMap(clock)
    audit = AuditLog(tmp_path / "audit")
    server = FrontDoorServer(
        verifier=AssertionVerifier(key.public_key(), clock),
        policy=OrchestratorPolicyContext(directory, RateLimiter(clock)),
        requests=requests,
        audit=audit,
        tokens=tokens,
        registry=LocalRegistryIndex([]),
        protocol=_NoProtocol(),
        atlas=StaticAtlas(None, []),
        aggregates=StaticAggregates("none", {}),
        ops=StaticOps({}),
        releases=ReleaseIndex(),
        steps=StepStore(backend, "frontdoor", clock=clock.dt),
        guard=Guard("^\\d{8}$"),
    )
    upstream = Upstream()
    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(tmp_path / "gw_audit"),
        GatewayConfig(topology=Topology.A, environment=Environment.TEST),
        http=upstream.client(),
        guard=Guard("^\\d{8}$"),
        env={},
    )
    gwc = GatewayClient("http://testserver/v1", "converse-native", http=TestClient(create_app(gw)))
    native = NativeEngine(
        gwc,
        lambda msg, assertion, conv: server.handle(msg, assertion=assertion, conv=conv, client="converse-native") or {},
        today=lambda: date(2026, 10, 19),
    )
    mails: list[tuple[str, list[str], bytes]] = []
    email = EmailChannel(
        lambda s, to, data: mails.append((s, to, data)),
        sender_address="trialbox@hospa.test",
        lookup=lambda addr: directory.get(addr).sub if directory.get(addr) else None,  # type: ignore[union-attr]
        authserv_id="mx.hospa.test",
        domain="hospa.test",
    )
    teams_out = FakeTeamsTransport()
    teams = TeamsChannel(
        teams_out,
        FakeBotFramework("tenant-1", {"tok-ok"}),
        lookup=lambda oid: CRC if oid == AAD_CRC else None,
        guard=Guard("^\\d{8}$"),
    )
    jobs = Jobs()
    cfg = ChannelsConfig.from_settings({"channels": {"engine": engine}})
    relay = ChannelRelay(
        config=cfg,
        channels={"email": email, "teams": teams},
        engines={"native": native, "hermes": HermesEngine(cfg.hermes_lock)},
        intake=Intake(requests, jobs),
        signer=signer,
        tokens=tokens,
        audit=audit,
        guard=Guard("^\\d{8}$"),
        environment=Environment.TEST,
    )
    return {
        "relay": relay,
        "mails": mails,
        "teams_out": teams_out,
        "jobs": jobs,
        "requests": requests,
        "upstream": upstream,
        "audit": tmp_path / "audit",
        "backend": backend,
    }


class _NoProtocol:
    def answer(self, study: str, question: str) -> Any:
        from tb_contracts.frontdoor import AskProtocolOut

        return AskProtocolOut(answer=None, citations=[], not_stated=True)


def mail(
    body: str,
    *,
    subject: str = "試驗評估",
    sender: str = CRC,
    dmarc: str = "pass",
    in_reply_to: str | None = None,
    pdf: bool = False,
) -> bytes:
    m = EmailMessage()
    m["Authentication-Results"] = f"mx.hospa.test; dmarc={dmarc} header.from=hospa.test"
    m["From"] = sender
    m["To"] = "trialbox@hospa.test"
    m["Subject"] = subject
    m["Message-ID"] = make_msgid(domain="hospa.test")
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(body)
    if pdf:
        m.add_attachment(PDF, maintype="application", subtype="pdf", filename="protocol.pdf")
    return m.as_bytes()


def records(audit: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text().splitlines()]


def last_reply(mails: list[tuple[str, list[str], bytes]]) -> tuple[str, str]:
    from email import message_from_bytes, policy

    msg = message_from_bytes(mails[-1][2], policy=policy.default)
    assert isinstance(msg, EmailMessage)
    body = msg.get_body(preferencelist=("plain",))
    assert body is not None
    return str(msg["Message-ID"]), str(body.get_content())


# ------------------------------------------------------------------------------------------------ done-when
@pytest.mark.req("S1-10", "FR-CONV-7", "FR-CONV-2", "HER-4")
def test_native_free_text_with_pdf_yields_proposal_and_ok_starts_feas(tmp_path: Path) -> None:
    box = build(tmp_path)
    res = box["relay"].receive("email", mail("這個試驗做得起來嗎\n\n-- \n王小明 CRC", pdf=True))
    assert res.action == "proposal" and res.engine == "native" and res.ticket_id
    reply_id, body = last_reply(box["mails"])
    assert "FEAS NEW scope=hospital lookback=24m" in body and "OK" in body
    assert box["jobs"].started == []  # a proposal never runs by itself
    seen = box["upstream"].inputs[-1]
    assert seen["attachments"] == [{"filename": "protocol.pdf", "content_type": "application/pdf"}]
    assert "王小明" not in seen["text"]  # the signature was stripped before the model saw anything

    ok = box["relay"].receive("email", mail("OK", subject="Re: 試驗評估", in_reply_to=reply_id))
    assert ok.action == "confirmed" and ok.ticket_id == res.ticket_id and ok.job_id == "JOB-0001"
    (line, sender, ticket, _refs) = box["jobs"].started[0]
    assert line.command == "FEAS" and line.study == "NEW" and line.params["lookback"] == "24m"
    assert sender == CRC and ticket == res.ticket_id
    p = box["requests"].get(res.ticket_id)
    assert p.state.value == "confirmed" and p.job_id == "JOB-0001"
    assert len(box["upstream"].inputs) == 1  # OK went through deterministic intake, not the model


@pytest.mark.req("FR-CONV-1", "FR-UX-10", "S1-10")
def test_grammar_lines_run_without_a_model(tmp_path: Path) -> None:
    box = build(tmp_path)
    res = box["relay"].receive("email", mail("please run", subject="FEAS GZQO lookback=36"))
    assert res.action == "line" and res.job_id == "JOB-0001"
    assert box["jobs"].started[0][0].command == "FEAS" and box["jobs"].started[0][0].study == "GZQO"
    bad = box["relay"].receive("email", mail("FEAS GZQO lookback=36 colour=blue", subject="hello"))
    assert bad.action == "grammar_error"
    _, body = last_reply(box["mails"])
    assert "unknown parameter" in body and "FEAS NEW" in body
    assert box["upstream"].inputs == []  # neither the line nor the malformed line reached the model


@pytest.mark.req("FR-CONV-14", "S1-10")
@pytest.mark.parametrize(("sender", "dmarc"), [("crc1@hospa.test", "fail"), ("stranger@evil.test", "pass")])
def test_unknown_or_unauthenticated_senders_never_reach_the_engine(tmp_path: Path, sender: str, dmarc: str) -> None:
    box = build(tmp_path)
    res = box["relay"].receive("email", mail("這個試驗做得起來嗎", sender=sender, dmarc=dmarc))
    assert res.action == "dropped" and box["mails"] == [] and box["upstream"].inputs == []
    assert records(box["audit"])[-1]["event"] == "channel.inbound.refuse"


@pytest.mark.req("FR-CONV-16", "FR-CONV-8", "HER-12")
def test_turns_are_audited_before_reply_and_identifiers_are_tokenised(tmp_path: Path) -> None:
    box = build(tmp_path)
    box["relay"].receive("email", mail("how many patients could we enrol for GZQO? see chart 12345678"))
    seen = box["upstream"].inputs[-1]
    assert "12345678" not in seen["text"] and "[MRN-1]" in seen["text"]
    turn = next(r for r in records(box["audit"]) if r["event"] == "channel.turn")
    d = turn["detail"]
    assert d["actor_type"] == "agent" and d["on_behalf_of"] == CRC and d["channel"] == "email"
    assert d["proposal_id"] and d["engine"] == "native"
    gw = [json.loads(x) for f in sorted((tmp_path / "gw_audit").glob("*.jsonl")) for x in f.read_text().splitlines()]
    assert gw[-1]["detail"]["class"] == "D0" and gw[-1]["detail"]["role"] == "classify_intent"  # TEST env: D0 only


@pytest.mark.req("FR-CONV-3", "S1-10")
def test_ok_binds_to_the_same_sender_and_open_proposal(tmp_path: Path) -> None:
    box = build(tmp_path)
    box["relay"].receive("email", mail("這個試驗做得起來嗎"))
    reply_id, _ = last_reply(box["mails"])
    none = box["relay"].receive("email", mail("OK", subject="Re: x"))  # not a reply to the proposal thread
    assert none.action == "grammar_error" and none.reason == "no_open_proposal"
    assert box["jobs"].started == []
    assert box["relay"].receive("email", mail("OK", subject="Re: x", in_reply_to=reply_id)).action == "confirmed"
    again = box["relay"].receive("email", mail("OK", subject="Re: x", in_reply_to=reply_id))
    assert again.reason == "no_open_proposal" and len(box["jobs"].started) == 1


# ------------------------------------------------------------------------------------------------ Teams (fake)
def activity(text: str, *, token: str = "tok-ok", oid: str = AAD_CRC, n: int = 1) -> dict[str, Any]:
    return {
        "type": "message",
        "id": f"act-{n}",
        "text": text,
        "from": {"aadObjectId": oid},
        "conversation": {"id": "teams-conv-1"},
        "tenantId": "tenant-1",
        "token": token,
    }


@pytest.mark.req("FR-UX-11", "S1-10")
def test_teams_fake_transport_proposes_but_never_approves_or_carries_phi(tmp_path: Path) -> None:
    box = build(tmp_path)
    out: FakeTeamsTransport = box["teams_out"]
    res = box["relay"].receive("teams", activity("How many patients could we get for GZQO?"))
    assert res.action == "proposal" and "FEAS GZQO scope=hospital lookback=24m" in out.sent[-1]["text"]
    ptr = box["relay"].receive("teams", activity("APPROVE G-0412 sha=4be1c2d9", n=2))
    assert ptr.action == "pointer" and "e-mail" in out.sent[-1]["text"].lower()
    phi = box["relay"].receive("teams", activity("is 12345678 eligible for GZQO", n=3))
    assert phi.action == "pointer" and phi.reason == "phi_on_no_phi_channel"
    assert all("12345678" not in s["text"] for s in out.sent)
    ok = box["relay"].receive("teams", activity("OK", n=4))
    assert ok.action == "confirmed" and box["jobs"].started[0][0].study == "GZQO"
    forged = box["relay"].receive("teams", activity("hello", token="forged", n=5))
    assert forged.action == "dropped"


# ------------------------------------------------------------------------------------------------ engine switch
@pytest.mark.req("FR-CONV-6", "OPS-02", "S1-11")
def test_engine_hermes_falls_back_to_native_and_switching_loses_no_request(tmp_path: Path) -> None:
    backend = SqliteBackend(":memory:")
    hermes_box = build(tmp_path / "h", engine="hermes", backend=backend)
    res = hermes_box["relay"].receive("email", mail("這個試驗做得起來嗎"))
    assert res.action == "proposal" and res.engine == "native"
    assert any(r["event"] == "channels.engine.fallback" for r in records(hermes_box["audit"]))
    reply_id, _ = last_reply(hermes_box["mails"])
    # the site switches to native mid-conversation: a new relay process, the same orchestrator store
    native_box = build(tmp_path / "n", engine="native", backend=backend)
    native_box["relay"].threads.update(hermes_box["relay"].threads)
    ok = native_box["relay"].receive("email", mail("OK", subject="Re: x", in_reply_to=reply_id))
    assert ok.action == "confirmed" and ok.ticket_id == res.ticket_id


# ------------------------------------------------------------------------------------------------ grammar
@pytest.mark.req("FR-UX-10", "S1-10")
@pytest.mark.parametrize(
    ("text", "cmd", "study"),
    [
        ("FEAS NEW scope=hospital lookback=24m deadline=2026-10-23", "FEAS", "NEW"),
        ("Re: FEAS GZQO lookback=36", "FEAS", "GZQO"),
        ("FEAS GZQO pid=P0001", "FEAS", "GZQO"),  # v1 subject grammar fallback
        ('ASK GZQO "prednisone 10 mg"', "ASK", "GZQO"),
        ("SCREEN GZQO scope=practitioners:P12345,P23456 cadence=weekly", "SCREEN", "GZQO"),
        ("STUDY GZQO recruiting", "STUDY", "GZQO"),
        ("CONFIRM P0156 P0203", "CONFIRM", None),
        ("REJECT P0177 R03", "REJECT", None),
        ("DEFER P0190 2026-11-17", "DEFER", None),
        ("STATE P0156 consented 2026-10-17", "STATE", None),
        ("ANSWERS 1Y 2N 3?", "ANSWERS", None),
        ("DIGEST weekly", "DIGEST", None),
        ("ok", "OK", None),
        ("STATUS", "STATUS", None),
        ("HELP", "HELP", None),
    ],
)
def test_grammar_lines_parse(text: str, cmd: str, study: str | None) -> None:
    line = parse_line(text)
    assert line is not None and line.command == cmd and line.study == study


@pytest.mark.req("FR-UX-10")
def test_grammar_rejects_malformed_lines_and_leaves_free_text_alone() -> None:
    for bad in (
        "FEAS",
        "REJECT P0177 R09",
        "STATE P0156 married",
        "DIGEST hourly",
        "ASK GZQO no quotes",
        "FEAS NEW deadline=Friday",
    ):
        with pytest.raises(GrammarError):
            parse_line(bad)
    for free in (
        "這個試驗做得起來嗎",
        "status of GZQO?",
        "ok thanks",
        "",
        "Feas for GZQO please",
        "FEAS for GZQO or RA-BIO?",  # stress test #20: a sentence that starts with a command word
        "STATUS of my requests?",
    ):
        assert parse_line(free) is None
    assert parse_line("APPROVE GZQO version=1.0.0") is not None and parse_line("APPROVE G-1 sha=ab").approval  # type: ignore[union-attr]


def test_strip_and_language_detection() -> None:
    text = "幫我看一下\u200b\n\n> old quoted\nOn Mon, X wrote:\nmore old"
    assert strip(text) == "幫我看一下"
    assert strip("hi\n-- \nsig") == "hi"
    assert detect_language("這個試驗做得起來嗎") == "zh-TW"
    assert detect_language("この試験、当院で何例くらい見込めますか？") == "ja"
    assert detect_language("How many patients?") == "en"
    assert detect_language("病人 s/p PCI，denied chest pain，Lab: normal") == "mixed"


@pytest.mark.req("S1-10")
def test_channels_config_fails_closed() -> None:
    assert ChannelsConfig.from_settings({}).engine == "native"  # Hermes installed disabled (OPS-02)
    for bad in ({"engine": "slack"}, {"fallback": "hermes"}, {"teams": {"mode": "live"}}, {"colour": 1}):
        with pytest.raises(ChannelsConfigError):
            ChannelsConfig.from_settings({"channels": bad})
