"""The key-checking front of the on-box model servers (D-177): ``python -m model_guard``.

vLLM checks its API key only on paths under ``/v1`` (and ``/v2``, ``/inference``, ``/cohere``). Other routes answer
without it: the SageMaker ``POST /invocations`` (chat and pooling), ``/tokenize``, ``/detokenize``, ``/score``,
``/pooling``, ``/classify``, ``/metrics``, and with ``VLLM_SERVER_DEV_MODE`` ``/collective_rpc``, ``/sleep`` and more.
So the vLLM servers sit on their own internal network (``model-backend-net``), and this guard is the only thing on
``model-net`` that answers to their names (``llm-service``, ``llm-verifier``). It lets through, with the key only:

* ``GET /v1/models``, ``POST /v1/chat/completions``, ``POST /v1/completions``, and ``POST /tokenize`` (D-739: lane
  G's G-1 counts tokens on the shipped server; the key already opens chat completions, which do more than count);
* with ``TB_GUARD_ADMIN=1`` (the RTX 5090 profile's sleep swap): ``POST /sleep``, ``POST /wake_up``,
  ``GET /is_sleeping``;
* ``GET /health`` without the key (vLLM's own health answer, nothing else).

Everything else is 404 and is never forwarded. A call without the key, or with another, is 401. The upstream is
chosen by the request's host name (``TB_GUARD_ROUTES="llm-service=llm-service-vllm:8000,..."``); an unknown host is
404. The guard refuses to start without a key: the file ``TB_LLM_API_KEY_FILE`` names (a compose secret,
``deploy/secrets/model/llm.key``, D-437) or else ``TB_LLM_API_KEY``. ``trialbox secrets rotate --service model``
writes a new key and recreates the guard, so the old key is refused from then on. Standard library only, except
that each request line goes through the services' log scrubber (``tb_common.logging``, in the image; T-212d, D-450).
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

try:  # T-212d (D-450): the request line through the services' scrubber (chart numbers, secrets in a query)
    from tb_common.logging import redact as _redact
    from tb_common.logging import register_secret as _register_secret
    from tb_common.logging import site_rule_on as _site_rule_on
except ImportError:  # pragma: no cover - the image always has tb_common

    def _redact(text: str) -> str:
        return text

    def _register_secret(value: str) -> None:
        return None

    def _site_rule_on() -> str:
        return ""


MAX_BODY = 16 * 1024 * 1024
CHAT_COMPLETIONS = "/v1/chat/completions"
COMPLETIONS = "/v1/completions"
KEYED: dict[str, set[str]] = {
    "/v1/models": {"GET"},
    CHAT_COMPLETIONS: {"POST"},
    COMPLETIONS: {"POST"},
    "/tokenize": {"POST"},  # D-739: counts tokens; the key already opens chat completions, which do more
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
            raise GuardConfigError(f"bad route {part!r} (want name=host:port)")
        out[name.strip().lower()] = (host, int(port))
    if not out:
        raise GuardConfigError("no route (TB_GUARD_ROUTES)")
    return out


class GuardConfigError(ValueError):
    """The guard's own refusal of its settings at start (D-636): its sentence is printed for the operator. A
    ``ValueError`` from anywhere else is not one of these and is not printed as one."""


class Guard:
    def __init__(self, key: str, routes: Mapping[str, tuple[str, int]], admin: bool = False, timeout: float = 900):
        if not key:
            raise GuardConfigError("no key (TB_LLM_API_KEY): the model guard does not run open")
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
            sys.stderr.write(f"model-guard {_redact(format % args)}\n")

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
            outgoing = b""
            if path in KEYED and self.command == "POST":
                from tb_common.output_gate import OutputRefused, prepare_output

                purposes = {CHAT_COMPLETIONS: "chat", COMPLETIONS: "completion", "/tokenize": "tokenize"}
                try:
                    incoming = json.loads(body)
                except ValueError:
                    incoming = None
                try:
                    approved = prepare_output(purposes[path], "model", incoming)
                    outgoing = json.dumps(approved, ensure_ascii=False, allow_nan=False).encode()
                except OutputRefused as exc:
                    self._reply(422, {"error": exc.reason})
                    return
            headers = {"Content-Type": "application/json"}
            if rule == "keyed":
                headers["Authorization"] = f"Bearer {g.key}"
            headers["Content-Length"] = str(len(outgoing))
            headers["Host"] = f"{target[0]}:{target[1]}"
            conn = http.client.HTTPConnection(target[0], target[1], timeout=g.timeout)
            try:
                conn.request(self.command, self.path, body=outgoing or None, headers=headers)
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


def key_of(env: Mapping[str, str]) -> str:
    """The model key: the file ``TB_LLM_API_KEY_FILE`` names first (D-437), else ``TB_LLM_API_KEY``. A named file
    that cannot be read gives no key from it (the guard then needs the variable, or does not start)."""
    path = (env.get("TB_LLM_API_KEY_FILE") or "").strip()
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                got = fh.read().strip()
        except OSError:
            got = ""
        if got:
            return got
    return (env.get("TB_LLM_API_KEY") or "").strip()


def build(env: Mapping[str, str] | None = None) -> Guard:
    e = os.environ if env is None else env
    return Guard(
        key_of(e),
        parse_routes(e.get("TB_GUARD_ROUTES", "")),
        admin=e.get("TB_GUARD_ADMIN", "") == "1",
        timeout=float(e.get("TB_GUARD_TIMEOUT_S") or 900),
    )


def scrub_setup(key: str) -> None:
    """The request lines through the services' scrubber (T-212d, D-450): the key and the site's chart numbers."""
    _register_secret(key)
    _site_rule_on()


def main(argv: list[str] | None = None) -> int:
    try:
        g = build()
    except GuardConfigError as exc:  # D-636: the guard's own sentences only; another error fails with its trace
        print(f"model_guard: {exc}", file=sys.stderr)
        return 2
    scrub_setup(g.key)
    port = int(os.environ.get("PORT") or 8000)
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(g))
    srv.daemon_threads = True
    print(f"model_guard: {sorted(g.routes)} on :{port} (key required; admin {'on' if g.admin else 'off'})",
          file=sys.stderr, flush=True)  # fmt: skip
    srv.serve_forever()
    return 0


__all__ = ["ADMIN", "KEYED", "OPEN", "Guard", "build", "key_of", "main", "make_handler", "parse_routes"]
