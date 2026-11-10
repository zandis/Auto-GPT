"""model-guard: the key on every call and a path allowlist in front of vLLM (D-177, ``services/model_guard``)."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import model_guard as mg
import pytest

KEY = "guard-key-0123456789"


class _Upstream(BaseHTTPRequestHandler):
    """Records what reaches it, as vLLM would see it; answers 200 to anything."""

    seen: ClassVar[list[tuple[str, str, str]]] = []

    def _any(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        _Upstream.seen.append((self.command, self.path, self.headers.get("Authorization", "")))
        data = json.dumps({"ok": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _any

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _start(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def guard(request: pytest.FixtureRequest) -> Iterator[int]:
    _Upstream.seen = []
    up = _start(_Upstream)
    g = mg.Guard(KEY, {"llm-service": ("127.0.0.1", up.server_address[1])}, admin=getattr(request, "param", False))
    gs = _start(mg.make_handler(g))
    yield gs.server_address[1]
    gs.shutdown()
    up.shutdown()


def _call(port: int, method: str, path: str, key: str | None = KEY, host: str = "llm-service:8000",
          body: bytes | None = b"{}") -> int:  # fmt: skip
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host, "Content-Type": "application/json"}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    c.request(method, path, body=body if method == "POST" else None, headers=headers)
    status = c.getresponse().status
    c.close()
    return status


def test_the_allowed_calls_pass_with_the_key_only(guard: int) -> None:
    for method, path in (("GET", "/v1/models"), ("POST", "/v1/chat/completions"), ("POST", "/v1/completions")):
        assert _call(guard, method, path, key=None) == 401
        assert _call(guard, method, path, key="wrong") == 401
        assert _call(guard, method, path) == 200
    assert [p for _, p, _ in _Upstream.seen] == ["/v1/models", "/v1/chat/completions", "/v1/completions"]
    assert all(a == f"Bearer {KEY}" for _, _, a in _Upstream.seen)  # vLLM checks it on /v1 too


def test_vllm_routes_that_skip_the_key_never_reach_it(guard: int) -> None:
    for path in ("/invocations", "/tokenize", "/detokenize", "/score", "/pooling", "/classify", "/collective_rpc",
                 "/reset_prefix_cache", "/v2/x", "/v1/chat/completions/", "//v1/models", "/v1/../invocations"):  # fmt: skip
        for key in (None, KEY):
            assert _call(guard, "POST", path, key=key) == 404, path
    for path in ("/metrics", "/server_info", "/version", "/docs", "/openapi.json"):
        assert _call(guard, "GET", path) == 404, path
    assert _call(guard, "GET", "/v1/models?x=1") == 404  # no query on /v1
    assert _Upstream.seen == []


def test_admin_paths_only_with_admin_and_the_key(guard: int) -> None:
    assert _call(guard, "POST", "/sleep?level=1") == 404
    assert _call(guard, "GET", "/is_sleeping") == 404
    assert _Upstream.seen == []


@pytest.mark.parametrize("guard", [True], indirect=True)
def test_admin_on_lets_the_sleep_swap_through_with_the_key(guard: int) -> None:
    assert _call(guard, "POST", "/sleep?level=1", key=None) == 401
    assert _call(guard, "POST", "/sleep?level=1") == 200
    assert _call(guard, "POST", "/wake_up") == 200
    assert _call(guard, "GET", "/is_sleeping") == 200
    assert _call(guard, "POST", "/collective_rpc") == 404
    assert [p for _, p, _ in _Upstream.seen] == ["/sleep?level=1", "/wake_up", "/is_sleeping"]


def test_health_is_open_and_hosts_must_match(guard: int) -> None:
    assert _call(guard, "GET", "/health", key=None) == 200
    assert _call(guard, "GET", "/healthz", key=None) == 200  # the guard's own
    assert _call(guard, "GET", "/v1/models", host="llm-verifier:8000") == 404
    assert _call(guard, "GET", "/v1/models", host="evil.example") == 404


def test_bad_body_length_is_refused(guard: int) -> None:
    c = http.client.HTTPConnection("127.0.0.1", guard, timeout=10)
    c.putrequest("POST", "/v1/chat/completions")
    c.putheader("Host", "llm-service")
    c.putheader("Content-Length", str(mg.MAX_BODY + 1))
    c.endheaders()
    assert c.getresponse().status == 400
    c.close()


def test_never_runs_open_and_routes_parse() -> None:
    with pytest.raises(ValueError, match="no key"):
        mg.build({"TB_GUARD_ROUTES": "llm-service=llm-service-vllm:8000"})
    with pytest.raises(ValueError, match="bad route"):
        mg.parse_routes("llm-service=nohostport")
    with pytest.raises(ValueError, match="no route"):
        mg.parse_routes("")
    g = mg.build({"TB_LLM_API_KEY": "k", "TB_GUARD_ROUTES": "llm-service=a:1, llm-verifier=b:2", "TB_GUARD_ADMIN": "1"})
    assert g.routes == {"llm-service": ("a", 1), "llm-verifier": ("b", 2)} and g.admin
