"""``tb_relay_adapter``: the only way messages reach Hermes (spec v4 §9.2, §9.6 item 10, HER-6, HER-7; S1-11).

channel-relay hands each message to this Hermes *platform plugin* after sender authentication, grammar diversion and
tokenisation. Against the pinned Hermes v0.22.2 plugin API (``register(ctx)``, read from the vendored source by
:mod:`integrations.hermes.contract`) the plugin registers:

* the gateway platform ``tb_relay`` (``ctx.register_platform``): an adapter whose :meth:`inject` accepts a relay
  envelope, re-checks it (:meth:`TbRelayAdapter.accept`) and feeds Hermes a ``MessageEvent`` whose session is the
  relay conversation; replies go back to the relay only (``TB_RELAY_REPLY_URL``, mTLS);
* the ``pre_gateway_dispatch`` hook: Hermes runs it unbounded and treats a raising callback as "allow", so
  :func:`pre_gateway_dispatch` never raises, enforces the 2 s budget itself and returns ``{"action": "skip"}`` for
  anything that is not a checked relay envelope (fail closed).

The relay reaches :meth:`inject` through the adapter's own listener (:class:`InjectListener`, started by
``connect``): HTTPS on ``TB_ADAPTER_LISTEN`` (``0.0.0.0:8444`` on ``hermes-net``) with a required client
certificate from the internal CA whose common name is ``channel-relay``; nothing else is accepted. The platform is
registered ``trusted_inbound``: the relay authenticated the sender and the directory decides who may write (HER-16),
so Hermes' own allowlists and pairing are not used, and ``pre_gateway_dispatch`` still drops anything that is not a
checked envelope. Replies and the end of each turn (``on_processing_complete``) go back to ``TB_RELAY_REPLY_URL``
over mTLS.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import ssl
import sys
import threading
import time
import types
import urllib.request
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger("tb_relay_adapter")

PLATFORM = "tb_relay"
HOOKS = ("pre_gateway_dispatch",)
DISPATCH_BUDGET_S = 2.0
_MARK = "tb_relay_envelope"
_SHARED = "tb_hermes_shared_context"
RELAY_PEER = "channel-relay"  # the only client certificate the inject listener accepts
MAX_ENVELOPE = 256 * 1024


class EnvelopeRefused(PermissionError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RelayEnvelope:
    conv: str
    msg_sha256: str
    channel: str
    assertion: str
    text: str


def shared_context() -> dict[str, dict[str, Any]]:
    """Process-wide store shared with ``tb_policy_audit`` (Hermes loads each plugin as its own module).

    ``senders``: relay conversation -> {assertion, channel}; ``sessions``: Hermes session id -> conversation.
    """
    mod = sys.modules.get(_SHARED)
    if mod is None:
        fresh = types.ModuleType(_SHARED)
        fresh.store = {"senders": {}, "sessions": {}}  # type: ignore[attr-defined]
        fresh.lock = threading.Lock()  # type: ignore[attr-defined]
        mod = sys.modules.setdefault(_SHARED, fresh)
    store: dict[str, dict[str, Any]] = mod.store
    return store


class TbRelayAdapter:
    """Envelope checks and reply path, independent of Hermes (unit-tested without the release)."""

    name = PLATFORM

    def __init__(self, reply: Callable[[str, str], None], clock: Callable[[], float] = time.monotonic) -> None:
        self.reply = reply  # (conv, text) -> back to channel-relay over mTLS
        self.clock = clock

    def accept(self, envelope: Mapping[str, Any]) -> RelayEnvelope:
        """Re-check one relay envelope: relay origin, assertion present, fields typed. Fails closed."""
        t0 = self.clock()
        try:
            if envelope.get("origin") != "channel-relay":
                raise EnvelopeRefused("not_from_relay")
            fields = {k: envelope.get(k) for k in ("conv", "msg_sha256", "channel", "assertion", "text")}
            if not all(isinstance(v, str) and v for v in fields.values()):
                raise EnvelopeRefused("envelope_incomplete")
            if str(fields["assertion"]).count(".") != 2:
                raise EnvelopeRefused("assertion_missing")
            if fields["channel"] == "line":
                raise EnvelopeRefused("line_never_reaches_hermes")  # profile tb-line: canned pointer at the relay
            env = RelayEnvelope(**{k: str(v) for k, v in fields.items()})
        except EnvelopeRefused:
            raise
        except Exception as e:  # any surprise blocks the dispatch
            raise EnvelopeRefused("adapter_error") from e
        if self.clock() - t0 > DISPATCH_BUDGET_S:
            raise EnvelopeRefused("dispatch_timeout")
        return env

    def send_outbound(self, conv: str, text: str) -> None:
        self.reply(conv, text)


def _skip(reason: str) -> dict[str, str]:
    return {"action": "skip", "reason": f"tb_relay_adapter:{reason}"}


def pre_gateway_dispatch(
    event: Any = None, clock: Callable[[], float] = time.monotonic, **_: Any
) -> dict[str, str] | None:
    """Hermes ``pre_gateway_dispatch`` hook (§9.6 item 10). ``None`` lets a checked relay message through."""
    t0 = clock()
    try:
        source = getattr(event, "source", None)
        platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", None))
        if platform != PLATFORM:
            return _skip("not_from_relay")
        raw = getattr(event, "raw_message", None)
        if not isinstance(raw, Mapping) or raw.get(_MARK) is not True:
            return _skip("not_injected_by_adapter")
        assertion = raw.get("assertion")
        if not isinstance(assertion, str) or assertion.count(".") != 2:
            return _skip("assertion_missing")
        if raw.get("conv") != getattr(source, "chat_id", None):
            return _skip("conversation_mismatch")
        if raw.get("channel") == "line":
            return _skip("line_never_reaches_hermes")
        if clock() - t0 > DISPATCH_BUDGET_S:
            return _skip("dispatch_timeout")
        return None
    except Exception:  # Hermes would treat a raise as "allow"
        return _skip("adapter_error")


def _post_reply(url: str, conv: str, text: str) -> None:
    _post_json(url, {"conv": conv, "text": text})


def _post_json(url: str, payload: Mapping[str, Any]) -> None:
    ctx = ssl.create_default_context(cafile=os.environ.get("TB_RELAY_CA") or None)
    if os.environ.get("TB_RELAY_CLIENT_CERT"):
        ctx.load_cert_chain(os.environ["TB_RELAY_CLIENT_CERT"], os.environ.get("TB_RELAY_CLIENT_KEY") or None)
    body = json.dumps(dict(payload)).encode()
    hdrs = {"content-type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")  # noqa: S310 (https checked by caller)
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:  # noqa: S310 (https URL from the deployment)
        resp.read()


def _peer_cn(sock: Any) -> str | None:
    cert = sock.getpeercert() if isinstance(sock, ssl.SSLSocket) else None
    subject: Any = (cert or {}).get("subject", ())
    for rdn in subject:
        for k, v in rdn:
            if k == "commonName":
                return str(v)
    return None


class InjectListener:
    """mTLS listener inside the Hermes container: ``POST /inject`` from channel-relay only.

    Each request is handed to ``inject`` on the gateway's event loop (``run_coroutine_threadsafe``); an envelope the
    adapter refuses gets ``403`` with the reason, an accepted one ``202`` (Hermes then answers asynchronously through
    ``TB_RELAY_REPLY_URL``). The TLS handshake runs in the connection's thread, never in ``accept``.
    """

    def __init__(
        self,
        address: tuple[str, int],
        context: ssl.SSLContext,
        loop: asyncio.AbstractEventLoop,
        inject: Callable[[Mapping[str, Any]], Coroutine[Any, Any, None]],
        peer: str = RELAY_PEER,
        timeout_s: float = DISPATCH_BUDGET_S * 5,
    ) -> None:
        listener = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _send(self, code: int, body: Mapping[str, Any]) -> None:
                data = json.dumps(dict(body)).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                if self.path != "/inject":
                    self._send(404, {"error": "not found"})
                    return
                try:
                    n = int(self.headers.get("content-length") or 0)
                    if not 0 < n <= MAX_ENVELOPE:
                        raise ValueError("size")
                    envelope = json.loads(self.rfile.read(n))
                    if not isinstance(envelope, dict):
                        raise ValueError("shape")
                except ValueError:
                    self._send(400, {"refused": "envelope_unreadable"})
                    return
                fut: Any = asyncio.run_coroutine_threadsafe(listener.inject(envelope), listener.loop)
                try:
                    fut.result(timeout=listener.timeout_s)
                except EnvelopeRefused as e:
                    self._send(403, {"refused": e.reason})
                    return
                except Exception as e:
                    logger.warning("tb_relay_adapter inject failed: %s", type(e).__name__)
                    self._send(503, {"refused": "adapter_error"})
                    return
                self._send(202, {"accepted": True})

            def log_message(self, format: str, *args: Any) -> None:
                logger.debug("inject %s", format % args)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def get_request(self) -> Any:
                sock, addr = self.socket.accept()
                sock.settimeout(15)
                return context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

            def finish_request(self, request: Any, client_address: Any) -> None:
                try:
                    request.do_handshake()
                except (ssl.SSLError, OSError):
                    return
                if _peer_cn(request) != peer:
                    logger.warning("tb_relay_adapter: refused a client certificate that is not %s", peer)
                    return
                super().finish_request(request, client_address)

        self.loop = loop
        self.inject = inject
        self.timeout_s = timeout_s
        self.server = Server(address, Handler)
        self._thread = threading.Thread(target=self.server.serve_forever, name="tb_relay_inject", daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def inject_context() -> ssl.SSLContext | None:
    """Server context for :class:`InjectListener` from ``TB_ADAPTER_CERT``/``TB_ADAPTER_KEY``/``TB_RELAY_CA``."""
    cert, key, ca = (os.environ.get(k, "") for k in ("TB_ADAPTER_CERT", "TB_ADAPTER_KEY", "TB_RELAY_CA"))
    if not (cert and key and ca):
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    ctx.load_verify_locations(ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _listen_address() -> tuple[str, int] | None:
    raw = os.environ.get("TB_ADAPTER_LISTEN", "")
    if not raw:
        return None
    host, _, port = raw.rpartition(":")
    return (host or "0.0.0.0", int(port))


def make_platform_adapter(base: type, platform_cls: Any, event_cls: Any, send_result_cls: Any) -> type:
    """Build the Hermes ``BasePlatformAdapter`` subclass for ``tb_relay`` from the release's own classes."""

    class TbRelayPlatformAdapter(base):  # type: ignore[misc]
        def __init__(self, config: Any) -> None:
            super().__init__(config=config, platform=platform_cls(PLATFORM))
            self._reply_url = os.environ.get("TB_RELAY_REPLY_URL", "")
            self._checker = TbRelayAdapter(self._reply_sync)

        def _reply_sync(self, conv: str, text: str) -> None:
            if not self._reply_url.startswith("https://"):
                raise RuntimeError("TB_RELAY_REPLY_URL (https, mTLS) not configured")
            _post_reply(self._reply_url, conv, text)

        async def connect(self, *, is_reconnect: bool = False) -> bool:
            """Open the inject listener (mTLS, ``channel-relay`` only). Without its settings nothing listens and
            no message can reach Hermes (fail closed)."""
            if getattr(self, "_listener", None) is not None:
                return True
            addr, ctx = _listen_address(), inject_context()
            if addr is None or ctx is None:
                logger.error("tb_relay_adapter: TB_ADAPTER_LISTEN/TB_ADAPTER_CERT/TB_ADAPTER_KEY/TB_RELAY_CA unset")
                return False
            self._listener: InjectListener | None = InjectListener(addr, ctx, asyncio.get_running_loop(), self.inject)
            self._listener.start()
            logger.info("tb_relay_adapter: inject listener on %s:%s (mTLS, %s only)", addr[0], addr[1], RELAY_PEER)
            return True

        async def disconnect(self) -> None:
            listener = getattr(self, "_listener", None)
            if listener is not None:
                await asyncio.to_thread(listener.stop)
                self._listener = None

        async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
            return {"name": chat_id, "type": "dm"}

        async def send(
            self, chat_id: str, content: str, reply_to: str | None = None, metadata: dict[str, Any] | None = None
        ) -> Any:
            try:
                await asyncio.to_thread(self._checker.send_outbound, chat_id, content)
            except Exception as e:  # never deliver anywhere but the relay
                return send_result_cls(success=False, error=f"relay reply failed: {type(e).__name__}")
            return send_result_cls(success=True, message_id=None)

        async def on_processing_complete(self, event: Any, outcome: Any) -> None:
            """End of one turn: tell the relay, so it can audit and send the last reply (FR-CONV-16)."""
            conv = getattr(getattr(event, "source", None), "chat_id", None)
            if not conv or not self._reply_url.startswith("https://"):
                return
            payload = {"conv": conv, "done": True, "outcome": str(getattr(outcome, "value", outcome))}
            try:
                await asyncio.to_thread(_post_json, self._reply_url, payload)
            except Exception as e:  # the relay times the turn out on its side
                logger.warning("tb_relay_adapter: turn-complete notice failed: %s", type(e).__name__)

        async def inject(self, envelope: Mapping[str, Any]) -> None:
            env = self._checker.accept(envelope)
            shared_context()["senders"][env.conv] = {"assertion": env.assertion, "channel": env.channel}
            source = self.build_source(chat_id=env.conv, chat_type="dm", user_id=env.conv, message_id=env.msg_sha256)
            raw = {_MARK: True, "conv": env.conv, "channel": env.channel, "assertion": env.assertion}
            await self.handle_message(
                event_cls(text=env.text, source=source, message_id=env.msg_sha256, raw_message=raw)
            )

    return TbRelayPlatformAdapter


def register(ctx: Any) -> None:
    """Hermes plugin entry point (``plugin.yaml`` + ``register(ctx)``, v0.22.2 plugin API)."""
    base = importlib.import_module("gateway.platforms.base")
    gw_config = importlib.import_module("gateway.config")
    event_mod = importlib.import_module("gateway.platforms.event")
    adapter_cls = make_platform_adapter(
        base.BasePlatformAdapter, gw_config.Platform, event_mod.MessageEvent, base.SendResult
    )
    ctx.register_platform(
        name=PLATFORM,
        label="TrialBox channel-relay",
        adapter_factory=adapter_cls,
        check_fn=lambda: True,
        trusted_inbound=True,  # senders are authenticated by channel-relay; the directory is the allowlist (HER-16)
    )
    ctx.register_hook("pre_gateway_dispatch", pre_gateway_dispatch)
    logger.info("tb_relay_adapter registered platform %s and pre_gateway_dispatch", PLATFORM)
