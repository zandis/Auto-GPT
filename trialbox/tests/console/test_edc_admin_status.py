# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""E-EDCB-4 (D-1046): ``/admin/edc`` says how the connection to the owner's EDC stands, in en, zh-TW and ja.

The owner's brief (D-1060): the page shows whether the EDC's capabilities document can be read and whether the
``trialbox`` module is on, and the EDC's pending and dead-letter counts. The role check (``redcap.connection``) is
unchanged. The counts' shape is not in #813 or #895; until the integrator relays it, the page says the EDC did not
report them, and never guesses.
"""

from __future__ import annotations

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

    return httpx.Client(transport=httpx.MockTransport(handler))


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
