"""The key-checking front of the on-box model servers (D-177): ``python -m model_guard``.

vLLM checks its API key only on paths under ``/v1`` (and ``/v2``, ``/inference``, ``/cohere``). Other routes answer
without it: the SageMaker ``POST /invocations`` (chat and pooling), ``/tokenize``, ``/detokenize``, ``/score``,
``/pooling``, ``/classify``, ``/metrics``, and with ``VLLM_SERVER_DEV_MODE`` ``/collective_rpc``, ``/sleep`` and more.
So the vLLM servers sit on their own internal network (``model-backend-net``), and this guard is the only thing on
``model-net`` that answers to their names (``llm-service``, ``llm-verifier``). It lets through, with the key only:

* ``GET /v1/models``, ``POST /v1/chat/completions``, ``POST /v1/completions``;
* with ``TB_GUARD_ADMIN=1`` (the RTX 5090 profile's sleep swap): ``POST /sleep``, ``POST /wake_up``,
  ``GET /is_sleeping``;
* ``GET /health`` without the key (vLLM's own health answer, nothing else).

Everything else is 404 and is never forwarded. A call without the key, or with another, is 401. The upstream is
chosen by the request's host name (``TB_GUARD_ROUTES="llm-service=llm-service-vllm:8000,..."``); an unknown host is
404. The guard refuses to start without ``TB_LLM_API_KEY``. Standard library only.
"""

from __future__ import annotations

import hmac
import http.client
import json
import os
import sys
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY = 16 * 1024 * 1024
KEYED: dict[str, set[str]] = {
    "/v1/models": {"GET"},
    "/v1/chat/completions": {"POST"},
    "/v1/completions": {"POST"},
}
ADMIN: dict[str, set[str]] = {"/sleep": {"POST"}, "/wake_up": {"POST"}, "/is_sleeping": {"GET"}}
OPEN: dict[str, set[str]] = {"/health": {"GET"}}
HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "te", "trailer", "upgrade", "host"}


def parse_routes(text: str) -> dict[str, tuple[str, int]]:
    """``"llm-service=llm-service-vllm:8000,llm-verifier=llm-verifier-vllm:8000"`` -> {host: (upstream, port)}."""
    out: dict[str, tuple[str, int]] = {}
    for part in (p.strip() for p in text.split(",") if p.strip()):
        name, sep, target = part.partition("=")
        host, _, port = target.rpartition(":")
        if not sep or not name.strip() or not host or not port.isdigit():
            raise ValueError(f"bad route {part!r} (want name=host:port)")
        out[name.strip().lower()] = (host, int(port))
    if not out:
        raise ValueError("no route (TB_GUARD_ROUTES)")
    return out


class Guard:
    def __init__(self, key: str, routes: Mapping[str, tuple[str, int]], admin: bool = False, timeout: float = 900):
        if not key:
            raise ValueError("no key (TB_LLM_API_KEY): the model guard does not run open")
        self.key = key
        self.routes = dict(routes)
        self.admin = admin
        self.timeout = timeout

    def rule(self, method: str, path: str) -> str:
        """ "open", "keyed" or "" (refused) for this method and path (no query)."""
        if method in OPEN.get(path, set()):
            return "open"
        if method in KEYED.get(path, set()) or (self.admin and method in ADMIN.get(path, set())):
            return "keyed"
        return ""

    def authorised(self, header: str | None) -> bool:
        scheme, _, token = (header or "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(token.strip().encode(), self.key.encode())

    def upstream(self, host_header: str | None) -> tuple[str, int] | None:
        host = (host_header or "").strip().lower()
        if host.startswith("["):  # an IPv6 literal: never a route name
            return None
        return self.routes.get(host.rsplit(":", 1)[0] if ":" in host else host)


def make_handler(g: Guard) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "trialbox-model-guard"

        def log_message(self, format: str, *args: Any) -> None:  # one line per call, never a header or a body
            sys.stderr.write("model-guard %s\n" % (format % args))

        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self) -> None:
            path, _, query = self.path.partition("?")
            if self.command == "GET" and path == "/healthz":  # the guard's own health check
                self._reply(200, {"status": "ok"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                self.close_connection = True
                self._reply(400, {"error": "bad request body"})
                return
            body = self.rfile.read(length) if length else b""
            rule = g.rule(self.command, path)
            target = g.upstream(self.headers.get("Host"))
            if not rule or target is None or (query and path not in ADMIN):
                self._reply(404, {"detail": "Not Found"})
                return
            if rule == "keyed" and not g.authorised(self.headers.get("Authorization")):
                self._reply(401, {"error": "Unauthorized"})
                return
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            headers["Host"] = f"{target[0]}:{target[1]}"
            conn = http.client.HTTPConnection(target[0], target[1], timeout=g.timeout)
            try:
                conn.request(self.command, self.path, body=body or None, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
            except OSError as exc:
                self._reply(502, {"error": f"model server not reachable: {type(exc).__name__}"})
                return
            finally:
                conn.close()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle

        def do_HEAD(self) -> None:
            self._reply(404, {"detail": "Not Found"})

    return Handler


def build(env: Mapping[str, str] | None = None) -> Guard:
    e = os.environ if env is None else env
    return Guard(
        e.get("TB_LLM_API_KEY", ""),
        parse_routes(e.get("TB_GUARD_ROUTES", "")),
        admin=e.get("TB_GUARD_ADMIN", "") == "1",
        timeout=float(e.get("TB_GUARD_TIMEOUT_S") or 900),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        g = build()
    except ValueError as exc:
        print(f"model_guard: {exc}", file=sys.stderr)
        return 2
    port = int(os.environ.get("PORT") or 8000)
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(g))
    srv.daemon_threads = True
    print(f"model_guard: {sorted(g.routes)} on :{port} (key required; admin {'on' if g.admin else 'off'})",
          file=sys.stderr, flush=True)  # fmt: skip
    srv.serve_forever()
    return 0


__all__ = ["ADMIN", "KEYED", "OPEN", "Guard", "build", "main", "make_handler", "parse_routes"]
