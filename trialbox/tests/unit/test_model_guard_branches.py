"""model-guard's branches the suite did not reach (D-976).

The nightly's branch coverage of ``services/model_guard`` was 93.33 % against its baseline of 96.15 % (run 43912198355,
2026-11-16), after GUARD-TOKENIZE (D-739). These are the paths no test walked: an IPv6 literal as the Host, a body
length that is not a number, a model server that is not there, ``HEAD``, and where the model key comes from (the file
first, else the variable). No baseline is changed.
"""

from __future__ import annotations

import http.client
import socket
import threading
from pathlib import Path

import model_guard as mg

from tests.unit.test_model_guard import KEY, _call, guard  # noqa: F401  (the fixture)


def test_an_ipv6_literal_is_never_a_route(guard: int) -> None:  # noqa: F811
    assert _call(guard, "GET", "/v1/models", host="[::1]:8000") == 404
    assert _call(guard, "GET", "/v1/models", host="[llm-service]") == 404


def test_a_body_length_that_is_not_a_number_is_refused(guard: int) -> None:  # noqa: F811
    c = http.client.HTTPConnection("127.0.0.1", guard, timeout=10)
    c.putrequest("POST", "/v1/models")  # the length is checked before the path
    c.putheader("Host", "llm-service")
    c.putheader("Content-Length", "twelve")
    c.endheaders()
    assert c.getresponse().status == 400
    c.close()


def test_head_is_not_found(guard: int) -> None:  # noqa: F811
    c = http.client.HTTPConnection("127.0.0.1", guard, timeout=10)
    c.request("HEAD", "/v1/models", headers={"Host": "llm-service", "Authorization": f"Bearer {KEY}"})
    assert c.getresponse().status == 404
    c.close()


def test_a_model_server_that_is_not_there_is_a_502_with_its_kind_only() -> None:
    from http.server import ThreadingHTTPServer

    # the port stays bound and never listens for the whole test: it refuses, and no other test (xdist) can take it
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        g = mg.Guard(KEY, {"llm-service": ("127.0.0.1", int(held.getsockname()[1]))}, timeout=5)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), mg.make_handler(g))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("GET", "/v1/models", headers={"Host": "llm-service", "Authorization": f"Bearer {KEY}"})
            r = c.getresponse()
            body = r.read().decode()
            c.close()
        finally:
            srv.shutdown()
    assert r.status == 502
    assert "model server not reachable: ConnectionRefusedError" in body
    assert "127.0.0.1" not in body  # the kind of the error, never where it went


def test_the_key_file_comes_first(tmp_path: Path) -> None:
    f = tmp_path / "llm_api_key"
    f.write_text("from-the-file-0123\n", encoding="utf-8")
    assert mg.key_of({"TB_LLM_API_KEY_FILE": str(f), "TB_LLM_API_KEY": "from-the-variable"}) == "from-the-file-0123"


def test_an_unreadable_or_empty_key_file_falls_back_to_the_variable(tmp_path: Path) -> None:
    missing = tmp_path / "nothing-here"
    assert (
        mg.key_of({"TB_LLM_API_KEY_FILE": str(missing), "TB_LLM_API_KEY": "from-the-variable"}) == "from-the-variable"
    )
    empty = tmp_path / "empty"
    empty.write_text("\n", encoding="utf-8")
    assert mg.key_of({"TB_LLM_API_KEY_FILE": str(empty), "TB_LLM_API_KEY": "from-the-variable"}) == "from-the-variable"
    assert mg.key_of({"TB_LLM_API_KEY_FILE": str(missing)}) == ""  # no key at all: build() then refuses to start
