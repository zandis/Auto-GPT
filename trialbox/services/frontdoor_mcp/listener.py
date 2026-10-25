"""frontdoor-mcp network listener: MCP Streamable HTTP over mTLS (spec v4 §9.3, §9.4; HER-1, HER-8, HER-14, HER-15).

``python -m frontdoor_mcp.listener`` serves :class:`~frontdoor_mcp.server.FrontDoorServer` on ``:8443``:

* ``POST /mcp``: one JSON-RPC message per request (Streamable HTTP, JSON response mode; no SSE stream, no session
  id: the server is stateless). Notifications get ``202``. ``GET``/``DELETE`` get ``405``.
* ``POST /policy/decide``: the ``pre_tool_call`` decision ``tb_policy_audit`` asks for (Hermes only).
* ``GET /healthz`` on a separate plain-HTTP port bound to loopback (the container health check).

Every connection needs a client certificate from the internal CA whose common name is on ``TB_FRONTDOOR_CLIENTS``
(default ``hermes`` and ``channel-relay``). A certificate proves *which service* calls, never *for whom*.

**Per-call identity (HER-15).** The assertion that names the user rides with each call, bound to its conversation:

* from Hermes, inside the call's arguments as ``_tb_identity: {assertion, conv}``. Hermes' MCP client can send only
  static headers, so ``tb_policy_audit`` adds the current turn's relay-minted assertion with a ``pre_tool_call``
  ``modify`` directive (spec §9.4 "the plugin attaches the current turn's assertion to each tool call"). The listener
  removes the key before the server validates the arguments, so the tool contract and the argument hash are unchanged
  and the model never sees the field in the tool schema;
* from the native engine (channel-relay), in the ``X-TB-Assertion`` / ``X-TB-Conv`` headers.

A ``tools/call`` without a valid assertion is refused and alarmed by the server, whatever the certificate. Only
``tools/list`` is answered on the certificate alone (an MCP client lists tools when it connects, before any
conversation exists; the list is public by design, HER-8).
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from guard.guard import Guard
from orchestrator.db_pg import SqlBackend, StepStore, open_backend
from tb_common.audit import AuditLog
from tb_common.mtls import JsonHandler, MtlsHTTPServer, PlainHTTPServer, serve_in_thread, server_context
from tb_common.policy.classes import Environment
from tb_contracts.frontdoor import AskProtocolOut

from frontdoor_mcp.backends import LocalRegistryIndex, ReleaseIndex, StaticAggregates, StaticAtlas, StaticOps
from frontdoor_mcp.identity import AssertionVerifier
from frontdoor_mcp.policy import Directory, OrchestratorPolicyContext, RateLimiter
from frontdoor_mcp.requests import RequestStore
from frontdoor_mcp.server import INVALID_REQUEST, PARSE_ERROR, FrontDoorServer
from frontdoor_mcp.tokens import SqlRelayTokenMap

logger = logging.getLogger("frontdoor_mcp.listener")

IDENTITY_KEY = "_tb_identity"  # the argument tb_policy_audit adds (and only it may add)
ASSERTION_HEADER = "x-tb-assertion"
CONV_HEADER = "x-tb-conv"
DEFAULT_CLIENTS = ("hermes", "channel-relay")
HERMES = "hermes"


def split_identity(message: Any, headers: Mapping[str, str]) -> tuple[Any, str | None, str | None]:
    """``(message without _tb_identity, assertion, conv)``. The argument route wins over the header route."""
    assertion = headers.get(ASSERTION_HEADER) or None
    conv = headers.get(CONV_HEADER) or None
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return message, assertion, conv
    params = message.get("params")
    args = params.get("arguments") if isinstance(params, dict) else None
    if not isinstance(args, dict) or IDENTITY_KEY not in args:
        return message, assertion, conv
    msg = copy.deepcopy(message)
    ident = msg["params"]["arguments"].pop(IDENTITY_KEY)
    if isinstance(ident, dict):
        a, c = ident.get("assertion"), ident.get("conv")
        return msg, (a if isinstance(a, str) and a else None), (c if isinstance(c, str) and c else None)
    return msg, None, None  # a malformed identity is no identity: the server refuses and alarms


class FrontDoorHandler(JsonHandler):
    def _server(self) -> FrontDoorServer:
        srv: FrontDoorServer = self.state["frontdoor"]
        return srv

    def _lock(self) -> threading.Lock:
        lock: threading.Lock = self.state["lock"]
        return lock

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path.split("?", 1)[0] == "/mcp":
            self.send_empty(405, {"allow": "POST"})  # no server-initiated stream
            return
        self.send_json(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        self.send_empty(405, {"allow": "POST"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/mcp":
            self._mcp()
        elif path == "/policy/decide":
            self._decide()
        else:
            self.send_json(404, {"error": "not found"})

    def _mcp(self) -> None:
        try:
            message = self.read_json()
        except ValueError:
            self.send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "parse"}})
            return
        if isinstance(message, list):  # JSON-RPC batches are not part of Streamable HTTP since 2025-06-18
            self.send_json(
                400, {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "no batches"}}
            )
            return
        headers = {k.lower(): v for k, v in self.headers.items()}
        msg, assertion, conv = split_identity(message, headers)
        peer = self.peer
        client = "hermes" if peer == HERMES else "converse-native"
        with self._lock():
            out = self._server().handle(msg, assertion=assertion, conv=conv, client=client, peer=peer)
        if out is None:
            self.send_empty(202)
            return
        self.send_json(200, out)

    def _decide(self) -> None:
        if self.peer != HERMES:
            self.send_json(403, {"allow": False, "reason": "hermes_only"})
            return
        try:
            body = self.read_json()
        except ValueError:
            self.send_json(400, {"allow": False, "reason": "parse"})
            return
        if not isinstance(body, dict):
            self.send_json(400, {"allow": False, "reason": "body"})
            return
        tool, assertion, conv, sha = (body.get(k) for k in ("tool", "assertion", "conv", "args_sha256"))
        with self._lock():
            allow, reason = self._server().decide(
                str(tool or ""),
                assertion if isinstance(assertion, str) else None,
                conv if isinstance(conv, str) else None,
                str(sha or ""),
            )
        self.send_json(200, {"allow": allow, "reason": reason})


class HealthHandler(JsonHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok", "service": self.state.get("service", "")})
        else:
            self.send_json(404, {"error": "not found"})


def make_listener(
    frontdoor: FrontDoorServer,
    address: tuple[str, int],
    *,
    cert: str,
    key: str,
    ca: str,
    clients: tuple[str, ...] = DEFAULT_CLIENTS,
) -> MtlsHTTPServer:
    return MtlsHTTPServer(
        address,
        FrontDoorHandler,
        server_context(cert, key, ca),
        clients,
        state={"frontdoor": frontdoor, "lock": threading.Lock()},
    )


class NotStatedProtocol:
    """``tb.ask_protocol`` read side until the deployment wires ``GatewayProtocolAnswerer`` to the study sections."""

    def answer(self, study: str, question: str) -> AskProtocolOut:
        return AskProtocolOut(answer=None, citations=[], not_stated=True)


def store_url() -> str:
    url = os.environ.get("TB_CHANNELS_STORE", "")
    if url:
        return url
    pw = os.environ.get("POSTGRES_WF_PASSWORD") or os.environ.get("POSTGRES_PASSWORD") or ""
    host = os.environ.get("TB_WORKFLOW_DB_HOST", "workflow-db")
    return f"postgresql://trialbox:{pw}@{host}:5432/trialbox_wf"


def load_public_key(path: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError("the relay assertion key must be an EC P-256 public key")
    return key


def build_from_env(backend: SqlBackend | None = None) -> FrontDoorServer:
    clock = time.time
    env = Environment(os.environ.get("TB_ENV", "TEST"))
    backend = backend or open_backend(store_url())
    directory = Directory.from_file(Path(os.environ.get("TB_DIRECTORY_FILE", "/run/secrets/tb/directory.yaml")))
    return FrontDoorServer(
        verifier=AssertionVerifier(
            load_public_key(os.environ.get("TB_RELAY_PUBKEY", "/run/secrets/tb/relay.pub")), clock
        ),
        policy=OrchestratorPolicyContext(directory, RateLimiter(clock), environment=env),
        requests=RequestStore(backend, _now),
        audit=AuditLog(Path(os.environ.get("TB_AUDIT_DIR", "/data/audit")), os.environ.get("TB_TZ", "Asia/Taipei")),
        tokens=SqlRelayTokenMap(backend, clock),
        registry=LocalRegistryIndex([]),
        protocol=NotStatedProtocol(),
        atlas=StaticAtlas(None, []),
        aggregates=StaticAggregates("none", {}),
        ops=StaticOps({}),
        releases=ReleaseIndex(),
        steps=StepStore(backend, "frontdoor"),
        guard=Guard.from_settings(),
        on_alarm=lambda reason, conv: logger.error("SECURITY ALARM frontdoor %s conv=%s", reason, conv),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def main() -> None:
    logging.basicConfig(level=os.environ.get("TB_LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    frontdoor = build_from_env()
    secrets = os.environ.get("TB_SECRETS", "/run/secrets/tb")
    clients = tuple(c.strip() for c in os.environ.get("TB_FRONTDOOR_CLIENTS", ",".join(DEFAULT_CLIENTS)).split(","))
    listener = make_listener(
        frontdoor,
        ("0.0.0.0", int(os.environ.get("TB_FRONTDOOR_PORT", "8443"))),
        cert=os.environ.get("TB_TLS_CERT", f"{secrets}/frontdoor-mcp.pem"),
        key=os.environ.get("TB_TLS_KEY", f"{secrets}/frontdoor-mcp.key"),
        ca=os.environ.get("TB_TLS_CA", f"{secrets}/tb-ca.pem"),
        clients=tuple(c for c in clients if c),
    )
    health = PlainHTTPServer(
        ("127.0.0.1", int(os.environ.get("PORT", "8081"))), HealthHandler, state={"service": "frontdoor-mcp"}
    )
    serve_in_thread(health, "health")
    logger.info("frontdoor-mcp listening on :%s (mTLS; clients %s)", listener.server_address[1], clients)
    listener.serve_forever()


if __name__ == "__main__":
    main()
