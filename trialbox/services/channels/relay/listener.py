"""channel-relay service: the relay's network edges (spec v4 §3.4.1, §9.2; S1-10, S1-11, HER-6, FR-CONV-16).

``python -m channels.relay.listener`` runs :class:`~channels.relay.relay.ChannelRelay` with:

* **transport intake** (plain HTTP, internal network only, ``:8095``): ``POST /inbound/email`` (raw RFC 822 as the MX
  delivered it; DMARC from the pinned ``Authentication-Results``) and ``POST /inbound/teams`` (a Bot Framework
  activity; MS0 fake transport). The response is the :class:`RelayResult` after the reply left. ``GET /outbox/teams``
  lists the fake Teams transport's replies; email replies leave through SMTP (MailHog in the POC);
* **Hermes edge** (mTLS, ``:8443``, client certificate ``hermes`` only): ``POST /hermes/reply`` takes
  ``{conv, text}`` (one message Hermes sends) or ``{conv, done: true, outcome}`` (``tb_relay_adapter``'s
  ``on_processing_complete``) into :class:`~channels.relay.hermes.HermesReplies`;
* ``GET /healthz``.

Engines: ``hermes`` (``TB_HERMES_ADAPTER_URL``, mTLS with the relay's certificate) with ``native`` as the fallback
(``classify_intent`` through tb-gateway, front-door calls over mTLS with the assertion in headers). Grammar lines and
``OK`` go to deterministic intake and start orchestrator jobs (``POST /jobs``) without a model (FR-CONV-1).
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from frontdoor_mcp.identity import AssertionSigner
from frontdoor_mcp.policy import Directory
from frontdoor_mcp.requests import RequestStore
from frontdoor_mcp.tokens import SqlRelayTokenMap
from guard.guard import Guard
from mail_gateway.outbound import smtp_transport
from orchestrator.db_pg import open_backend
from tb_common.audit import AuditLog
from tb_common.mtls import (
    JsonHandler,
    MtlsHTTPServer,
    PlainHTTPServer,
    client_context,
    serve_in_thread,
    server_context,
)
from tb_common.policy.classes import Environment
from tb_common.ulid import new_ulid
from tb_llm import GatewayClient

from channels.base import ChannelError
from channels.config import ChannelsConfig
from channels.grammar import Line
from channels.native.email import EmailChannel
from channels.native.engine import NativeEngine
from channels.native.teams import FakeBotFramework, FakeTeamsTransport, TeamsChannel
from channels.relay.hermes import HermesEngine, HermesReplies, MtlsHermesTransport
from channels.relay.relay import ChannelRelay, Intake, RelayResult

logger = logging.getLogger("channels.relay.listener")
HERMES = "hermes"


class JobRefused(RuntimeError):
    pass


class OrchestratorJobs:
    """The orchestrator's workflow start for a deterministic line: the same ``JobCreate`` the mail gateway and the
    console build for that line (``console.proposals``), posted to ``POST /jobs``."""

    def __init__(self, url: str, timeout_s: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def start(self, line: Line, *, sender: str, ticket_id: str | None, refs: Mapping[str, str]) -> str:
        from console.proposals import ProposalError, job_create, propose

        try:
            prop = propose(line.text, "en", None)
            job = job_create(
                prop.line, sender, new_ulid(), f"channel-relay{f' ticket {ticket_id}' if ticket_id else ''}"
            )
        except ProposalError as e:
            raise JobRefused(str(e)) from e
        body = job.model_dump_json(exclude_none=True).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 (internal orchestrator URL from the deployment)
            f"{self.url}/jobs", data=body, headers={"content-type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                out = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise JobRefused(f"orchestrator refused the job (HTTP {e.code})") from e
        return str(out["job_id"])


class NativeFrontDoor:
    """The native engine's front-door call: MCP over mTLS (certificate ``channel-relay``), assertion in headers."""

    def __init__(self, url: str, context: ssl.SSLContext, timeout_s: float = 30.0) -> None:
        self.url = url
        self.context = context
        self.timeout_s = timeout_s

    def __call__(self, message: dict[str, Any], assertion: str, conv: str) -> dict[str, Any]:
        req = urllib.request.Request(  # noqa: S310 (https front door from the deployment)
            self.url,
            data=json.dumps(message).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "x-tb-assertion": assertion,
                "x-tb-conv": conv,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s, context=self.context) as resp:  # noqa: S310
            out: dict[str, Any] = json.loads(resp.read() or b"{}")
        return out


def _result(res: RelayResult) -> dict[str, Any]:
    return {k: v for k, v in res.__dict__.items() if v is not None}


class IntakeHandler(JsonHandler):
    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok", "service": "channel-relay", "engine": self.state["engine"]})
        elif self.path.split("?", 1)[0] == "/outbox/teams":
            self.send_json(200, {"sent": list(self.state["teams_out"].sent)})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/inbound/email", "/inbound/teams"):
            self.send_json(404, {"error": "not found"})
            return
        channel = path.rsplit("/", 1)[1]
        try:
            raw: Any = self.read_body() if channel == "email" else self.read_json()
        except ValueError:
            self.send_json(400, {"error": "unreadable body"})
            return
        relay: ChannelRelay = self.state["relay"]
        lock: threading.Lock = self.state["lock"]
        try:
            with lock:  # one turn at a time: the relay's thread map and the engines are not re-entrant
                res = relay.receive(channel, raw)
        except JobRefused as e:
            relay.audit.append("channel.job.refuse", actor="relay", detail={"channel": channel, "reason": str(e)})
            self.send_json(422, {"action": "refused", "reason": "job_refused"})
            return
        except (ChannelError, ValueError, KeyError) as e:
            logger.warning("inbound %s refused: %s", channel, type(e).__name__)
            self.send_json(400, {"action": "refused", "reason": type(e).__name__})
            return
        self.send_json(200, _result(res))


class HermesReplyHandler(JsonHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/hermes/reply" or self.peer != HERMES:
            self.send_json(404, {"error": "not found"})
            return
        try:
            body = self.read_json()
        except ValueError:
            self.send_json(400, {"error": "unreadable body"})
            return
        replies: HermesReplies = self.state["replies"]
        audit: AuditLog = self.state["audit"]
        conv = body.get("conv") if isinstance(body, dict) else None
        if not isinstance(conv, str) or not conv:
            self.send_json(400, {"error": "conv required"})
            return
        if body.get("done") is True:
            ok = replies.complete(conv, str(body.get("outcome") or "failure"))
        elif isinstance(body.get("text"), str):
            ok = replies.deliver(conv, body["text"])
        else:
            self.send_json(400, {"error": "text or done required"})
            return
        if not ok:  # Hermes wrote outside an open turn: never forwarded, always audited
            audit.append("channel.hermes.reply.refuse", actor=HERMES, detail={"conv": conv, "reason": "no_open_turn"})
            self.send_json(409, {"accepted": False})
            return
        self.send_json(200, {"accepted": True})


def _load_signing_key(path: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("the relay signing key must be an EC P-256 private key")
    return key


def build_from_env() -> dict[str, Any]:
    from frontdoor_mcp.listener import store_url

    secrets = os.environ.get("TB_SECRETS", "/run/secrets/tb")
    env = Environment(os.environ.get("TB_ENV", "TEST"))
    audit = AuditLog(Path(os.environ.get("TB_AUDIT_DIR", "/data/audit")), os.environ.get("TB_TZ", "Asia/Taipei"))
    backend = open_backend(store_url())
    requests = RequestStore(backend, lambda: datetime.now(UTC))
    tokens = SqlRelayTokenMap(backend, time.time)
    dir_path = Path(os.environ.get("TB_DIRECTORY_FILE", f"{secrets}/directory.yaml"))
    directory = Directory.from_file(dir_path)
    teams_ids: dict[str, str] = dict((yaml.safe_load(dir_path.read_text(encoding="utf-8")) or {}).get("teams") or {})
    guard = Guard.from_settings()
    cert, key, ca = (f"{secrets}/channel-relay.pem", f"{secrets}/channel-relay.key", f"{secrets}/tb-ca.pem")
    client_ctx = client_context(cert, key, ca)

    email = EmailChannel(
        smtp_transport(
            os.environ.get("TB_RELAY_SMTP_HOST", "mailhog"),
            int(os.environ.get("TB_RELAY_SMTP_PORT", "1025")),
            starttls=os.environ.get("TB_RELAY_SMTP_STARTTLS", "0") == "1",
        ),
        sender_address=os.environ.get("TB_RELAY_FROM", "trialbox@hospa.test"),
        lookup=lambda addr: p.sub if (p := directory.get(addr)) else None,
        authserv_id=os.environ.get("TB_RELAY_AUTHSERV_ID", "mx.hospa.test"),
        domain=os.environ.get("TB_RELAY_DOMAIN", "hospa.test"),
    )
    teams_out = FakeTeamsTransport()
    teams_tokens = {t for t in os.environ.get("TB_TEAMS_FAKE_TOKENS", "").split(",") if t}
    teams = TeamsChannel(
        teams_out,
        FakeBotFramework(os.environ.get("TB_TEAMS_TENANT", "tenant-1"), teams_tokens),
        lookup=teams_ids.get,
        guard=guard,
    )
    native = NativeEngine(
        GatewayClient(
            os.environ.get("TB_GATEWAY_URL", "http://gateway:8020/v1"),
            "converse-native",
            model=os.environ.get("TB_GATEWAY_MODEL") or None,
            timeout=120,
        ),
        NativeFrontDoor(os.environ.get("TB_FRONTDOOR_URL", "https://frontdoor-mcp:8443/mcp"), client_ctx),
        today=date.today,
    )
    replies = HermesReplies()
    adapter_url = os.environ.get("TB_HERMES_ADAPTER_URL", "")
    hermes = HermesEngine(
        Path(os.environ.get("TB_HERMES_LOCK", "/app/integrations/hermes/hermes.lock")),
        environment=env.value,
        transport=MtlsHermesTransport(adapter_url, client_ctx) if adapter_url else None,
        replies=replies,
        open_proposals=lambda conv, sender: [p.ticket_id for p in requests.open_in(conv, sender)],
        turn_timeout_s=float(os.environ.get("TB_HERMES_TURN_TIMEOUT", "180")),
    )
    if hermes.problems:
        logger.warning("Hermes engine unavailable: %s", "; ".join(hermes.problems))
    cfg = ChannelsConfig.from_settings({"channels": {"engine": os.environ.get("TB_CHANNELS_ENGINE", "native")}})
    relay = ChannelRelay(
        config=cfg,
        channels={"email": email, "teams": teams},
        engines={"native": native, "hermes": hermes},
        intake=Intake(requests, OrchestratorJobs(os.environ.get("TB_ORCH_URL", "http://orchestrator:8010"))),
        signer=AssertionSigner(_load_signing_key(f"{secrets}/relay-signing.key"), time.time),
        tokens=tokens,
        audit=audit,
        guard=guard,
        environment=env,
    )
    return {
        "relay": relay,
        "replies": replies,
        "audit": audit,
        "teams_out": teams_out,
        "engine": cfg.engine if hermes.available or cfg.engine == "native" else f"{cfg.engine}->native",
        "server_ctx": server_context(cert, key, ca),
    }


def main() -> None:
    logging.basicConfig(level=os.environ.get("TB_LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    box = build_from_env()
    hermes_edge = MtlsHTTPServer(
        ("0.0.0.0", int(os.environ.get("TB_RELAY_TLS_PORT", "8443"))),
        HermesReplyHandler,
        box["server_ctx"],
        (HERMES,),
        state={"replies": box["replies"], "audit": box["audit"]},
    )
    serve_in_thread(hermes_edge, "hermes-edge")
    intake = PlainHTTPServer(
        ("0.0.0.0", int(os.environ.get("PORT", "8095"))),
        IntakeHandler,
        state={**box, "lock": threading.Lock()},
    )
    logger.info(
        "channel-relay: intake :%s, Hermes edge :%s (mTLS), engine %s",
        intake.server_address[1],
        hermes_edge.server_address[1],
        box["engine"],
    )
    intake.serve_forever()


if __name__ == "__main__":
    main()
