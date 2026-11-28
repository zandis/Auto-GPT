# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""E-EDCB-4 (D-1046): ``/admin/edc`` says how the connection to the owner's EDC stands, in en, zh-TW and ja.

The owner's brief (D-1060): the page shows whether the EDC's capabilities document can be read and whether the
``trialbox`` module is on, and the EDC's pending and dead-letter counts. The role check (``redcap.connection``) is
unchanged. The counts' shape is not in #813 or #895; until the integrator relays it, the page says the EDC did not
report them, and never guesses.
"""

from __future__ import annotations

import html
from typing import Any

import httpx
import pytest
from edc_backend import tools

from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name


def _edc(modules: list[str] | None, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/capabilities"
        assert request.headers["authorization"] == "Bearer tool-token"
        if modules is None:
            raise httpx.ConnectError("refused")
        return httpx.Response(status, json={"modules": [{"id": m} for m in modules]})

    return _guarded(handler)


def _guarded(handler: Any) -> httpx.Client:
    """The real guarded client of the tool door (P-13 review M5a), its connection replaced by ``handler``."""
    from tb_common.http import declared_client

    return declared_client("https://edc.example", inner=httpx.MockTransport(handler),
                           resolver=lambda host, port: ["10.20.30.40"])  # fmt: skip


@pytest.fixture
def edc_env(monkeypatch: pytest.MonkeyPatch, db_url: str) -> pytest.MonkeyPatch:
    monkeypatch.setenv("TB_EDC_TOOL_URL", "https://edc.example")
    monkeypatch.setenv("TB_EDC_TOOL_TOKEN", "tool-token")
    return monkeypatch


def test_the_status_reads_the_capabilities_and_the_module() -> None:
    on = tools.connection_status("https://edc.example", "tool-token", _edc(["core", "trialbox"]))
    assert (on["configured"], on["reachable"], on["module"]) == (True, True, True)
    assert on["pending"] is None and on["dead_letter"] is None  # not reported: never guessed
    off = tools.connection_status("https://edc.example", "tool-token", _edc(["core"]))
    assert (off["reachable"], off["module"]) == (True, False)
    down = tools.connection_status("https://edc.example", "tool-token", _edc(None))
    assert (down["reachable"], down["module"]) == (False, False) and "did not answer" in down["reason"]
    bad = tools.connection_status("https://edc.example", "tool-token", _edc(["trialbox"], status=401))
    assert bad["reachable"] is False
    unset = tools.connection_status("", "", _edc(["trialbox"]))
    assert unset["configured"] is False and unset["reachable"] is False


@pytest.mark.parametrize(("lang", "words"), [
    ("en", ("Connection", "reachable", "module is on", "not reported")),
    ("zh-TW", ("連線狀態", "可連線", "模組已開啟", "未回報")),
    ("ja", ("接続状態", "接続できます", "モジュールは有効", "報告されていません")),
])  # fmt: skip
def test_the_page_says_the_status_in_three_languages(
    box: dict[str, Any], edc_env: pytest.MonkeyPatch, lang: str, words: tuple[str, ...]
) -> None:
    edc_env.setattr(tools, "http_client", lambda: _edc(["trialbox"]))
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/admin/edc"})
    page = c.get("/admin/edc")
    assert page.status_code == 200
    assert 'data-testid="edc-status"' in page.text
    i = page.text.index('data-testid="edc-status"')
    section = page.text[i : page.text.index("</section>", i)]
    for w in words:
        assert w in section, (lang, w, section)


def test_the_page_says_when_the_edc_does_not_answer(box: dict[str, Any], edc_env: pytest.MonkeyPatch) -> None:
    edc_env.setattr(tools, "http_client", lambda: _edc(None))
    c, _ = login(box["app"])
    page = c.get("/admin/edc").text
    assert 'data-testid="edc-status-down"' in page and 'data-testid="edc-status-module-on"' not in page


def test_the_page_says_when_the_connection_is_not_set(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                                      db_url: str) -> None:  # fmt: skip
    monkeypatch.delenv("TB_EDC_TOOL_URL", raising=False)
    monkeypatch.delenv("TB_EDC_TOOL_TOKEN", raising=False)
    monkeypatch.delenv("TB_EDC_BACKEND", raising=False)
    c, _ = login(box["app"])
    assert 'data-testid="edc-status-unset"' in c.get("/admin/edc").text


def test_the_role_check_is_unchanged(box: dict[str, Any], edc_env: pytest.MonkeyPatch) -> None:
    edc_env.setattr(tools, "http_client", lambda: _edc(["trialbox"]))
    c, _ = login(box["app"], "viewer", VIEWER_PW)
    assert c.get("/admin/edc").status_code == 403


def _egress(tmp_path: Any) -> list[dict[str, Any]]:
    import json

    lines = [json.loads(x) for p in sorted((tmp_path / "audit").glob("*.jsonl")) for x in p.read_text().splitlines()]
    return [x["detail"] for x in lines if x["event"] == "egress.leave"]


def test_the_connection_check_leaves_by_its_own_edge_route(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                           tmp_path: Any) -> None:  # fmt: skip
    """P-13 ruling: the check goes through the egress edge as ``edc.tool``, to the configured host, never recorded
    on ``edc.write``."""
    edc_env.setattr(tools, "http_client", lambda: _edc(["trialbox"]))
    c, _ = login(box["app"])
    assert 'data-testid="edc-status-module-on"' in c.get("/admin/edc").text
    rows = _egress(tmp_path)
    assert [(r["route"], r["destination"], r["result"]) for r in rows] == [("edc.tool", "edc.example", "sent")]


def test_the_connection_check_cannot_reach_another_host(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                        tmp_path: Any) -> None:  # fmt: skip
    """P-13 ruling: a request of the check to any host but the configured EDC's is refused by the edge, before it is
    sent, and recorded as refused."""
    sent: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"modules": [{"id": "trialbox"}]})

    edc_env.setattr(tools, "http_client", lambda: _guarded(answer))
    edc_env.setattr(tools, "connection_status", lambda base, token, http: http.get("https://other.example/x").json())
    c, _ = login(box["app"])
    page = c.get("/admin/edc")
    assert page.status_code == 200 and sent == []
    assert [(r["route"], r["destination"], r["result"]) for r in _egress(tmp_path)] == [
        ("edc.tool", "other.example", "refused")
    ]


def test_a_metadata_address_is_recorded_refused_never_sent(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                           tmp_path: Any) -> None:  # fmt: skip
    """P-13 review M5: the guard checks the address before the edge records; the check's only row says refused."""
    edc_env.setenv("TB_EDC_TOOL_URL", "https://169.254.169.254")
    c, _ = login(box["app"])
    assert 'data-testid="edc-status-down"' in c.get("/admin/edc").text
    assert [(r["route"], r["destination"], r["result"], r["reason"]) for r in _egress(tmp_path)] == [
        ("edc.tool", "169.254.169.254", "refused", "metadata")
    ]


def test_a_client_without_the_guard_is_refused_never_sent(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                          tmp_path: Any) -> None:  # fmt: skip
    """P-13 review M5a: no egress guard on the client is no address check: fail closed, refused, nothing sent."""
    sent: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"modules": [{"id": "trialbox"}]})

    edc_env.setattr(tools, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(answer)))
    c, _ = login(box["app"])
    page = c.get("/admin/edc")
    assert page.status_code == 200 and 'data-testid="edc-status-down"' in page.text and sent == []
    assert [(r["route"], r["destination"], r["result"], r["reason"]) for r in _egress(tmp_path)] == [
        ("edc.tool", "edc.example", "refused", "no_guard")
    ]


@pytest.mark.parametrize("base", ["https://EDC.example", "https://édc.example", "https://a@edc.example:8443",
                                  r"https://edc.example\@evil.example", "https://edc.example."])  # fmt: skip
def test_the_named_host_is_the_host_the_client_declares_and_sends_to(monkeypatch: pytest.MonkeyPatch,
                                                                     base: str) -> None:  # fmt: skip
    """P-13 review M6: one reading of the address. The host the edge names is the one the guarded client declares and
    the one its request goes to."""
    from tb_common.http import declared_host, guard_of

    monkeypatch.setenv("TB_EDC_TOOL_URL", base)
    where = declared_host(tools.tool_base())
    guard = guard_of(tools.http_client())
    assert where is not None and guard is not None
    assert where[0] == httpx.Request("GET", tools.tool_base() + "/api/v1/capabilities").url.host
    assert (where[0].rstrip("."), where[1]) in guard.declared


@pytest.mark.parametrize("base", ["https://edc.example:abc", "https://[::1", "https://xn--a.example"])
def test_an_address_that_is_not_valid_says_so_and_nothing_leaves(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                                 tmp_path: Any, base: str) -> None:  # fmt: skip
    """P-13 review M6: an address the client cannot read is not read another way for the edge; the page answers."""
    edc_env.setenv("TB_EDC_TOOL_URL", base)
    c, _ = login(box["app"])
    page = c.get("/admin/edc")
    assert page.status_code == 200 and 'data-testid="edc-status-down"' in page.text
    assert "The EDC's tool URL is not a valid address" in html.unescape(page.text)  # M6b: the explanation itself
    assert _egress(tmp_path) == []


def _lan(handler: Any, base: str = "http://edc.lan") -> httpx.Client:
    """The tool door's real client for an ``http`` URL on the hospital LAN, on a production box."""
    from tb_common.http import declared_client

    return declared_client(base, inner=httpx.MockTransport(handler), env={"TB_ENV": "PRODUCTION"},
                           resolver=lambda host, port: ["10.20.30.40"] if host == "edc.lan" else ["93.184.216.34"])  # fmt: skip


def test_an_http_lan_tool_url_works_and_the_page_warns(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                       caplog: pytest.LogCaptureFixture) -> None:  # fmt: skip
    """P-13 review: plain http to the site's own declared EDC host is let through; the page and the log say so."""
    edc_env.setenv("TB_EDC_TOOL_URL", "http://edc.lan")

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"modules": [{"id": "trialbox"}]})

    edc_env.setattr(tools, "http_client", lambda: _lan(answer))
    c, _ = login(box["app"])
    with caplog.at_level("WARNING", logger="tb.egress"):
        text = html.unescape(c.get("/admin/edc").text)
    assert 'data-testid="edc-status-up"' in text and 'data-testid="edc-status-plain-http"' in text
    assert "is plain http" in text
    assert any("plain http" in r.getMessage() and "tool-token" not in repr(r.__dict__) for r in caplog.records)


def test_http_to_another_host_is_still_refused_before_any_call(box: dict[str, Any], edc_env: pytest.MonkeyPatch,
                                                               tmp_path: Any) -> None:  # fmt: skip
    edc_env.setenv("TB_EDC_TOOL_URL", "http://edc.lan")
    sent: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={})

    edc_env.setattr(tools, "http_client", lambda: _lan(answer))
    edc_env.setattr(tools, "connection_status", lambda base, token, http: http.get("http://other.example/x").json())
    c, _ = login(box["app"])
    assert c.get("/admin/edc").status_code == 200 and sent == []
    assert [(r["destination"], r["result"], r["reason"]) for r in _egress(tmp_path)] == [
        ("other.example", "refused", "http_outside_dev")
    ]


@pytest.mark.parametrize("base", ["http://127.0.0.1:8080", "https://localhost", "https://[::1]"])
def test_a_typed_loopback_or_reserved_url_is_not_declared(base: str) -> None:
    from tb_common.http import declared_client, guard_of

    guard = guard_of(declared_client(base, env={"TB_ENV": "PRODUCTION"}))
    assert guard is not None and guard.declared == set() and guard.http_ok == set()
