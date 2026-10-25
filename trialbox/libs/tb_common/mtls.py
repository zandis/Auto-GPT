"""Mutual TLS for the internal service listeners (spec v4 §9.2, §9.3: frontdoor-mcp and channel-relay over mTLS).

Standard library only: :class:`MtlsHTTPServer` is a threaded ``http.server`` whose connections must present a client
certificate issued by the internal CA, with a common name on the listener's allowlist. The TLS handshake runs in the
connection's worker thread (``do_handshake_on_connect=False``), so a slow or hostile client never blocks ``accept``.
Handlers read the verified peer name from :attr:`JsonHandler.peer`.
"""

from __future__ import annotations

import json
import logging
import socket
import ssl
import threading
from collections.abc import Iterable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger("tb_common.mtls")

MAX_BODY = 1 << 20  # 1 MiB: MCP calls and relay envelopes are small
HANDSHAKE_TIMEOUT_S = 15.0


def server_context(cert: str, key: str, ca: str) -> ssl.SSLContext:
    """TLS 1.2+ server context that requires a client certificate from ``ca``."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    ctx.load_verify_locations(ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_context(cert: str, key: str, ca: str) -> ssl.SSLContext:
    """Client context that trusts only ``ca`` and presents ``cert``."""
    ctx = ssl.create_default_context(cafile=ca)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def peer_common_name(sock: ssl.SSLSocket) -> str | None:
    cert = sock.getpeercert()
    if not cert:
        return None
    subject: Any = cert.get("subject", ())
    for rdn in subject:
        for k, v in rdn:
            if k == "commonName":
                return str(v)
    return None


class MtlsHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server: TLS with a required client certificate and a common-name allowlist."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        context: ssl.SSLContext,
        allowed_peers: Iterable[str],
        state: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(address, handler)
        self.context = context
        self.allowed_peers = frozenset(allowed_peers)
        self.state: dict[str, Any] = dict(state or {})

    def get_request(self) -> tuple[socket.socket, Any]:
        sock, addr = self.socket.accept()
        sock.settimeout(HANDSHAKE_TIMEOUT_S)
        return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

    def finish_request(self, request: Any, client_address: Any) -> None:
        assert isinstance(request, ssl.SSLSocket)
        try:
            request.do_handshake()
        except (ssl.SSLError, OSError) as e:
            logger.warning("mTLS handshake refused from %s: %s", client_address[0], type(e).__name__)
            return
        cn = peer_common_name(request)
        if cn not in self.allowed_peers:
            logger.warning("mTLS peer %r is not allowed on this listener", cn)
            return
        self.RequestHandlerClass(request, client_address, self)  # type: ignore[arg-type]


class PlainHTTPServer(ThreadingHTTPServer):
    """Plain HTTP (health checks on loopback; the relay's transport intake on the internal network)."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], state: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(address, handler)
        self.state: dict[str, Any] = dict(state or {})


class JsonHandler(BaseHTTPRequestHandler):
    server_version = "trialbox"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    @property
    def peer(self) -> str | None:
        conn = self.connection
        return peer_common_name(conn) if isinstance(conn, ssl.SSLSocket) else None

    @property
    def state(self) -> dict[str, Any]:
        st: dict[str, Any] = getattr(self.server, "state", {})
        return st

    def read_body(self) -> bytes:
        n = int(self.headers.get("content-length") or 0)
        if n < 0 or n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n) if n else b""

    def read_json(self) -> Any:
        return json.loads(self.read_body() or b"null")

    def send_json(self, code: int, body: Any, headers: Mapping[str, str] | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def send_empty(self, code: int, headers: Mapping[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("content-length", "0")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s %s", self.address_string(), format % args)


def serve_in_thread(server: ThreadingHTTPServer, name: str) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, name=name, daemon=True)
    t.start()
    return t
