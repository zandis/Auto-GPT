"""Card 9c-9 (review 05, J5-5): "Ask" answers without the model. The console writes the answer itself from rules,
the readiness and the screening trail; no request from ``/ask`` or ``/api/v1/ask`` goes to ``POST /assist`` or to a
model client. Synthetic data only, on the set-up pages' box (``tests/console/test_site_setup_pages``)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sitesetup import help as site_help
from tb_common.crypto import pid_for_mrn

from tests.console import test_console_app, test_site_setup_pages
from tests.console.test_console_app import login

box = test_console_app.box  # the fixtures, by name
sb = test_site_setup_pages.sb
PW = test_site_setup_pages.PW
KEY = test_site_setup_pages.KEY


class _NoModel:
    """A model client that records every call and refuses it: Ask must never reach one."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat_json(self, prompt_id: str, *_a: Any, **_kw: Any) -> Any:
        self.calls.append(prompt_id)
        raise AssertionError(f"Ask reached the model (prompt {prompt_id})")


def _rigged(sb: dict[str, Any]) -> _NoModel:
    svc = sb["svc"]
    for no, text in site_help.PRACTICE_CHARTS:
        svc.add_chart("main", no, "pasted.txt", text.encode(), "crc", "ja", pasted=True)
    model = _NoModel()
    svc.llm = model
    sb["calls"].clear()
    return model


def test_ask_page_answers_next_why_and_help_with_no_model_call(sb: dict[str, Any]) -> None:
    model = _rigged(sb)
    c, csrf = login(sb["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/ask"})
    r = c.get("/ask", params={"q": "次に何をすればよいですか？", "study": "GZQO"})
    assert r.status_code == 200 and 'data-kind="next"' in r.text and "確認待ち" in r.text
    pid = pid_for_mrn(KEY, "10000005")
    r = c.get("/ask", params={"pid": pid, "q": "なぜリストにいるの？", "study": "GZQO"})
    assert r.status_code == 200 and 'data-kind="why"' in r.text
    for lang, q in (("en", "How does this page work?"), ("zh-TW", "下一步該做什麼？")):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/ask"})
        assert c.get("/ask", params={"q": q, "study": "GZQO"}).status_code == 200
    assert model.calls == []
    assert [p for _m, p in sb["calls"] if p == "/assist"] == []


def test_api_ask_answer_is_the_rule_written_draft_with_no_model_call(sb: dict[str, Any]) -> None:
    model = _rigged(sb)
    c = TestClient(sb["app"])
    r = c.post("/api/v1/session", json={"username": "crc", "password": PW, "lang": "en"})
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    ans = c.get("/api/v1/ask", params={"q": "What do I do next?", "study": "GZQO"}).json()
    assert ans["kind"] == "next" and ans["answer"] and ans["links"]
    help_ = c.get("/api/v1/ask", params={"q": "How does this page work?", "study": "GZQO"}).json()
    assert help_["kind"] == "help" and help_["answer"].startswith("Ask what to do next")
    assert model.calls == []
    assert [p for _m, p in sb["calls"] if p == "/assist"] == []
