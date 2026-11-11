# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""T-502 (D-328; REG-014, OPS-004, PLAN-019, REG-015): the PoC demonstration mode behind the audited flag ``demo.mode``.

The card's acceptance tests: a walk posts to every input and upload route with the flag on and every one is refused
(in the reader's language, audited, nothing stored); the banner is on every page in ja, zh-TW and en; one
``demo.ack`` per tester; a planted chart number in a demo field is reported by the scan of stored input."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from console import demo_guard as dg
from console import i18n_demo
from console.i18n import CATALOGUES
from fastapi.params import File as FileParam
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from tb_common import flags as fl

from tests.console.test_console_app import _done_case, _done_feas, box, login  # noqa: F401 - fixture by name
from tests.console.test_role_pages import _csrf
from tests.console.test_wording_walk import VALUES, _pages

PW = "demo-guard-password-0001"
LANGS = ("en", "ja", "zh-TW")
CATS = {"en": i18n_demo.EN, "ja": i18n_demo.JA, "zh-TW": i18n_demo.ZH}
TEMPLATES = Path(dg.__file__).resolve().parent / "templates"
ACCEPT = {k: "yes" for k in dg.REQUIRED}


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    yield
    fl.clear_cache()


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


def _demo_on(b: dict[str, Any]) -> None:
    """The owner switches demo mode on as the flag page does it: an audited change with a reason."""
    fl.Flags(audit=b["audit"]).set(dg.FLAG, "on", actor="console:admin", reason="T-502 test: the PoC demo")
    fl.clear_cache()


def _signed_in(b: dict[str, Any], name: str, role: str, lang: str = "en") -> tuple[TestClient, str]:
    """A tester signed in, the acknowledgement accepted, the page language chosen."""
    if name != "admin":
        b["users"].create(name, role, PW, f"{name}@hospa.test")
    c, csrf = login(b["app"], name, PW if name != "admin" else "correct-horse-battery-1")
    if dg.flag_on():
        r = c.post("/demo/ack", data={"csrf": csrf, "back": "/", **ACCEPT}, follow_redirects=False)
        assert r.status_code == 303, r.text
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c, csrf


# ---------------------------------------------------------------------------------------------- the flag
def test_the_flag_is_declared_off_by_default_and_changed_with_an_audit_event(box: dict[str, Any]) -> None:
    d = fl.DECLARED[dg.FLAG]
    assert d.default == "off" and d.values == ("off", "on") and d.seed_env == "TB_DEMO_MODE"
    assert fl.Flags().row(dg.FLAG) == "off" and not dg.flag_on()  # seeded off at create_app
    c, _ = login(box["app"])
    form = {"csrf": _csrf(c.get("/ops/flags").text), "name": dg.FLAG, "value": "on", "reason": "PoC demo opens"}
    r = c.post("/ops/flags", data={**form, "confirm": "yes", "old": "off"}, follow_redirects=False)
    assert r.status_code == 303
    fl.clear_cache()
    assert dg.flag_on()
    (ev,) = _events(box, "flag.set")
    assert ev["detail"]["flag"] == dg.FLAG and ev["detail"]["new"] == "on" and ev["actor"] == "console:admin"


def test_flag_off_changes_nothing(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    page = c.get("/home").text
    assert 'data-testid="demo-banner"' not in page and 'data-testid="demo-foot"' not in page
    assert c.get("/demo/ack").status_code == 404
    r = c.post("/pilot/case", data={"csrf": csrf, "ruleset": "GZQO"}, files={"charts": ("c.txt", b"synthetic")})
    assert dg.REFUSED not in r.text and "problem.h.demo.refused" not in r.text
    assert not _events(box, dg.REFUSED_EVENT) and not _events(box, dg.ACK_EVENT)


# ---------------------------------------------------------------------------------------------- the walk
def _upload_routes(app: Any) -> set[str]:
    """Every route that takes a file (a ``File()`` parameter) and every form of the templates that sends one or
    carries chart text (``multipart/form-data``, a file input), with their ``{rs}`` filled."""
    out: set[str] = set()
    for r in app.routes:
        if not (isinstance(r, APIRoute) and "POST" in (r.methods or set())):
            continue
        if any(isinstance(p.field_info, FileParam) for p in r.dependant.body_params):
            out.add(r.path)
    for t in TEMPLATES.glob("*.html"):
        for form in re.findall(r"<form\b[^>]*>.*?</form>", t.read_text(encoding="utf-8"), re.S):
            head = form.split(">", 1)[0]
            if 'enctype="multipart/form-data"' in head or 'type="file"' in form or "chart-text" in form:
                action = re.search(r'action="([^"]+)"', head)
                assert action, f"{t.name}: an upload form without an action"
                out.add(action.group(1))
    return {re.sub(r"{{\s*rs\s*}}|{rs}", "GZQO", p) for p in out}


def test_the_walk_finds_the_known_upload_and_paste_routes(box: dict[str, Any]) -> None:
    found = _upload_routes(box["app"])
    assert {"/pilot/protocol", "/pilot/consent", "/pilot/case", "/pilot/mailbox", "/site/charts", "/site/codes",
            "/site/sheets", "/studies/GZQO/forms/dictionary"} <= found  # fmt: skip
    for path in found:  # every one is a multipart form or a guarded route: refused in demo mode
        assert dg.guarded("POST", path, "multipart/form-data; boundary=x")


@pytest.mark.parametrize("lang", LANGS)
def test_every_upload_and_paste_route_is_refused_in_the_readers_language(box: dict[str, Any], lang: str) -> None:
    _demo_on(box)
    c, csrf = _signed_in(box, "admin", "admin", lang)
    jobs = len(box["backend"].jobs)
    routes = sorted(_upload_routes(box["app"]))
    number = str(4_417_239 * 10 + 1)  # built here: the repository scan stays clean
    planted = "chart no " + number + "\nsynthetic"  # never written to disk by the console
    for path in routes:
        r = c.post(path, data={"csrf": csrf, "ruleset": "GZQO", "text": planted, "chart_no": "A1"},
                   files={"file": ("chart.txt", planted.encode()), "charts": ("chart.txt", planted.encode())})  # fmt: skip
        assert r.status_code == 403, (path, r.status_code)
        assert 'data-testid="problem-page"' in r.text and CATS[lang]["demo.refused"] in r.text, path
        assert 'data-testid="demo-banner"' in r.text
    for path in [p for p in routes if any(g.match(p) for g in dg.GUARDED)]:  # pasted text, no file: refused too
        r = c.post(path, data={"csrf": csrf, "ruleset": "GZQO", "text": planted, "criteria": planted})
        assert r.status_code == 403 and CATS[lang]["demo.refused"] in r.text, path
    for path in ("/api/v1/site/charts", "/api/v1/studies/GZQO/forms/dictionary"):  # the JSON twins
        r = c.post(path, json={"chart_no": "A1", "text": planted, "csv": planted})
        assert r.status_code == 403 and r.json()["error"] == dg.REFUSED, path
    assert len(box["backend"].jobs) == jobs  # nothing was submitted
    refused = _events(box, dg.REFUSED_EVENT)
    assert len(refused) >= len(routes) and all(e["actor"] == "console:admin" for e in refused[: len(routes)])
    # the path only: never the content. The whole planted number, not a few of its digits: an event's hashes and
    # times hold digits too, and "4417" was found in one by chance (T-653)
    assert not any(number in json.dumps(e) or "chart no" in json.dumps(e) for e in refused)


def test_the_route_guard_call_refuses_on_its_own() -> None:
    """The guard call inside an upload route: refuses (and audits) even if the middleware were not in front."""
    written: list[tuple[str, dict[str, Any]]] = []
    au = SimpleNamespace(append=lambda event, **kw: written.append((event, kw)), directory=None)
    users = SimpleNamespace(session=lambda *a, **k: None)
    g = dg.DemoGuard(SimpleNamespace(au=au, users=users), read_flag=lambda: True)  # type: ignore[arg-type]
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(demo_guard=g)), method="POST",
                          url=SimpleNamespace(path="/pilot/case"), headers={}, cookies={})  # fmt: skip

    class Refusal(Exception):
        def __init__(self, status: int, key: str) -> None:
            super().__init__(status, key)

    with pytest.raises(Refusal) as e:
        dg.guard(req, Refusal)  # type: ignore[arg-type]
    assert e.value.args == (403, dg.REFUSED)
    assert written == [(dg.REFUSED_EVENT, {"actor": "console:-", "detail": {"path": "/pilot/case", "method": "POST"}})]
    g.read_flag = lambda: False
    dg.guard(req, Refusal)  # type: ignore[arg-type]  # off: nothing happens
    assert len(written) == 1


# ---------------------------------------------------------------------------------------------- the banner
@pytest.mark.parametrize("lang", LANGS)
def test_the_banner_is_on_every_page_in_three_languages(box: dict[str, Any], lang: str) -> None:
    _done_feas(box["backend"])
    _done_case(box["backend"])
    _demo_on(box)
    banner, foot = CATS[lang]["demo.banner"], CATS[lang]["demo.foot"]
    seen = 0
    for name, role in (("admin", "admin"), ("pi1", "investigator"), ("crc1", "coordinator")):
        c, _ = _signed_in(box, name, role, lang)
        paths = _pages(box["app"], VALUES)
        for job in list(box["backend"].jobs):
            paths += _pages(box["app"], {**VALUES, "job_id": job})
        for path in sorted(set(paths)):
            r = c.get(path)
            if "text/html" not in r.headers.get("content-type", ""):
                continue
            assert 'data-testid="demo-banner"' in r.text and banner in r.text, (name, path, r.status_code)
            assert 'data-testid="demo-foot"' in r.text and foot in r.text, (name, path)
            seen += 1
    assert seen > 60  # the walk reached the pages, not only refusals
    anon = TestClient(box["app"]).get("/login", headers={"accept-language": lang})
    assert CATS[lang]["demo.banner"] in anon.text  # before sign-in too


def test_the_catalogues_have_every_string_in_three_languages() -> None:
    assert set(i18n_demo.EN) == set(i18n_demo.JA) == set(i18n_demo.ZH)
    for lang in LANGS:
        assert set(i18n_demo.EN) <= set(CATALOGUES[lang]), lang
    for k in ("demo.banner", "demo.foot"):  # the non-device line in every language
        assert "not a medical device" in i18n_demo.EN[k].lower()
        assert "医療機器ではありません" in i18n_demo.JA[k] and "非醫療器材" in i18n_demo.ZH[k]


# ---------------------------------------------------------------------------------------------- the acknowledgement
def test_one_acknowledgement_per_tester(box: dict[str, Any]) -> None:
    _demo_on(box)
    stored = {"pi1": ("investigator", "ja"), "crc1": ("coordinator", "zh-TW")}
    for name, (role, lang) in stored.items():
        box["users"].create(name, role, PW, f"{name}@hospa.test")
        c, csrf = login(box["app"], name, PW)  # the first page after sign-in is the acknowledgement
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        r = c.get("/home", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/demo/ack?back=/home"
        page = c.get("/demo/ack?back=/home").text
        assert CATS[lang]["demo.ack.i2"] in page and dg.STATEMENT_VERSION in page
        assert (
            c.post("/pilot/request", data={"csrf": csrf}, follow_redirects=False)
            .headers["location"]
            .startswith("/demo/ack")
        )
        r = c.post("/demo/ack", data={"csrf": csrf, "back": "/home", "i1": "yes", "i2": "yes"})
        assert r.status_code == 400 and CATS[lang]["demo.ack.missing"] in r.text
        assert not [e for e in _events(box, dg.ACK_EVENT) if e["actor"] == f"console:{name}"]
        r = c.post("/demo/ack", data={"csrf": "wrong", "back": "/home", **ACCEPT}, follow_redirects=False)
        assert r.status_code == 400
        r = c.post("/demo/ack", data={"csrf": csrf, "back": "/home", **ACCEPT, "o2": "yes"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/home"
        r = c.get("/home")
        assert r.status_code == 200 and r.url.path != "/demo/ack"
        # a second visit and a second post write nothing
        assert c.get("/demo/ack", follow_redirects=False).status_code == 303
        c.post("/demo/ack", data={"csrf": csrf, "back": "/", **ACCEPT})
        c2, _ = login(box["app"], name, PW)  # a new session of the same account: not asked again
        r2 = c2.get("/home")
        assert r2.status_code == 200 and r2.url.path != "/demo/ack"
    acks = _events(box, dg.ACK_EVENT)
    assert sorted(e["actor"] for e in acks) == ["console:crc1", "console:pi1"]  # one per tester
    for e in acks:
        role, lang = stored[e["actor"].removeprefix("console:")]
        assert e["detail"] == {"role": role, "lang": lang, "version": dg.STATEMENT_VERSION,
                               "accepted": list(dg.REQUIRED), "recording": False, "quote": True}  # fmt: skip


def test_the_acknowledgement_is_asked_of_the_api_too_and_a_cro_account_can_give_it(box: dict[str, Any]) -> None:
    _demo_on(box)
    box["users"].create("api1", "coordinator", PW, "api1@hospa.test")
    c = TestClient(box["app"])
    tok = c.post("/api/v1/session", json={"username": "api1", "password": PW}).json()["token"]
    r = c.get("/api/v1/studies", headers={"authorization": f"Bearer {tok}"})
    assert r.status_code == 403 and r.json()["error"] == dg.ACK_NEED
    box["users"].create("cro1", "cro", PW, "cro1@hospa.test")
    cro, csrf = login(box["app"], "cro1", PW)
    assert 'data-testid="demo-ack"' in cro.get("/demo/ack").text
    r = cro.post("/demo/ack", data={"csrf": csrf, "back": "//elsewhere.test", **ACCEPT}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"  # only a local page to go back to
    assert [e["actor"] for e in _events(box, dg.ACK_EVENT)] == ["console:cro1"]


# ---------------------------------------------------------------------------------------------- the scan
def test_a_planted_chart_number_in_a_demo_field_is_reported_by_the_scan(
    box: dict[str, Any], db_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _done_feas(box["backend"])
    _demo_on(box)
    crc, csrf = _signed_in(box, "crc1", "coordinator")
    base = tmp_path / "baseline.txt"
    assert dg.main(["scan", "--db", str(box["dir"] / "console"), "--write-baseline", str(base)]) == 0
    assert dg.main(["scan", "--db", "--baseline", str(base), str(box["dir"] / "console")]) == 0
    planted = "seen in clinic, chart no " + str(4_417_239 * 10 + 1)  # built here: the repository scan stays clean
    r = crc.post("/studies/GZQO/profile", data={"csrf": csrf, "target_n": "8", "comment": planted})
    assert r.status_code == 200  # a free-text field is stored: the scan after the session is what finds it
    hits = dg.scan_stored([], db_url)
    found = [h for h in hits if h.pattern == "chart_number" and h.where.startswith("db:")]
    assert found, hits
    assert "44172391" not in str(found[0])  # masked, never the whole value
    capsys.readouterr()
    assert dg.main(["scan", "--db", "--baseline", str(base), str(box["dir"] / "console")]) == 2
    out = capsys.readouterr().out
    assert "chart_number" in out and "1 new hit(s)" in out
    (tmp_path / "upload").mkdir()  # a stored file is scanned too
    (tmp_path / "upload" / "note.txt").write_text(planted, encoding="utf-8")
    assert any(h.pattern == "chart_number" for h in dg.scan_stored([tmp_path / "upload"]))
