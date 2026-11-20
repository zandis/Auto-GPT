"""Card 10B-22 (D-1261): the MEDIS disease-name master step of site set-up, on the orchestrator's real set-up API.

* At a site whose country layer uses the master: the coordinator opens ``/site/codes/medis`` from the local codes,
  reads what it is with MEDIS's two links, hands over the zip, reads what the box found without loading anything,
  ticks the approval (their own name from their sign-in), chooses the same file again and loads it; the page then
  shows the loaded version and date. One ``terminology.load`` event (the approval and the counts, never a row).
* A refusal shows its code and reason; a load without the approval, or with another file than the one read, is
  refused before anything is sent; the loader's refusal is shown as the loader gave it, never a traceback.
* Who may open it: the set-up row (coordinator, administrator), answered as ``POST /site/codes`` answers the others.
* At a site whose layer does not use it: no route, no link, the orchestrator's routes answer 404.

The release is invented (``tests/medis_fixture.py``); the loader is #1238's (card 10B-2c)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from adapter import licensed

from tests import medis_fixture as fx
from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, box, login  # noqa: F401 - box: used by name
from tests.console.test_site_setup_pages import PW, sb  # noqa: F401 - the fixture is used by name

PAGE = "/site/codes/medis"


@pytest.fixture
def jp(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The set-up box made at a site whose country layer uses the master (the routes are added with the app)."""
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    return dict(request.getfixturevalue("sb"))


@pytest.fixture
def tw(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")
    return dict(request.getfixturevalue("sb"))


def _csrf(text: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', text)
    assert m
    return m.group(1)


def _check(c: Any, data: bytes) -> Any:
    page = c.get(PAGE)
    return c.post(f"{PAGE}/check", data={"csrf": _csrf(page.text)}, files={"file": ("byomei999.zip", data)})


def _load(c: Any, data: bytes, sha: str, approved: bool = True) -> Any:
    page = c.get(PAGE)
    form = {"csrf": _csrf(page.text), "sha256": sha, **({"approved": "yes"} if approved else {})}
    return c.post(f"{PAGE}/load", data=form, files={"file": ("byomei999.zip", data)})


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted((tmp_path / "orch-audit").glob("*")):
        if f.is_file():
            out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


def test_the_coordinator_reads_approves_and_loads_the_release(jp: dict[str, Any], tmp_path: Path) -> None:
    c, _ = login(jp["app"], "crc", PW)
    codes = c.get("/site/codes")
    assert 'data-testid="codes-medis"' in codes.text and f'href="{PAGE}"' in codes.text
    r = c.get(PAGE)
    assert r.status_code == 200 and 'data-state="not_loaded"' in r.text
    assert 'href="https://www2.medis.or.jp/stdcd/byomei/download2019.html"' in r.text
    assert 'href="https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html"' in r.text
    assert 'data-testid="medis-skip"' in r.text and "modifiers read as unknown" in r.text
    data = fx.release_zip()
    r = _check(c, data)
    assert r.status_code == 200 and 'data-testid="medis-found"' in r.text, r.text[-2000:]
    assert '<td data-testid="medis-version">9.99</td>' in r.text and 'data-testid="medis-approve"' in r.text
    assert "crc" in r.text  # the approval names the person from the sign-in
    sha = re.search(r'name="sha256" value="([0-9a-f]{64})"', r.text)
    assert sha
    assert licensed.status(jp["svc"].store.db.url)[0]["state"] == "not_loaded"  # reading loaded nothing
    assert not [e for e in _events(tmp_path) if e.get("event") == "terminology.load"]
    r = _load(c, data, sha.group(1))
    assert r.status_code == 200 and 'data-testid="medis-done"' in r.text, r.text[-2000:]
    assert 'data-state="loaded"' in r.text and "9.99" in r.text and "2026-06-01" in r.text
    ev = [
        e
        for e in _events(tmp_path)
        if e.get("event") == "terminology.load" and e["detail"].get("kind") == "medis_release"
    ]
    assert len(ev) == 1
    assert (
        ev[0]["actor"].removeprefix("console:") == "crc"
        and ev[0]["detail"]["approved"] is True
        and ev[0]["detail"]["version"] == "9.99"
    )
    assert ev[0]["output_sha"] == sha.group(1)
    text = json.dumps(ev[0], ensure_ascii=False)
    assert not any(name in text for _c, _n, name, *_ in fx.DISEASES)  # never a row of the release


def test_the_page_speaks_the_three_languages(jp: dict[str, Any]) -> None:
    from console.i18n_medis import EN, JA, ZH

    assert set(EN) == set(JA) == set(ZH)
    c, _ = login(jp["app"], "crc", PW)
    for lang, cat in (("ja", JA), ("zh-TW", ZH), ("en", EN)):
        c.post("/lang", data={"csrf": _csrf(c.get(PAGE).text), "lang": lang, "back": PAGE})
        r = c.get(PAGE)
        assert r.status_code == 200 and f'<html lang="{lang}">' in r.text
        assert cat["medis.title"] in r.text and cat["medis.not_loaded"] in r.text


def test_a_load_needs_the_approval_and_the_same_file(jp: dict[str, Any], tmp_path: Path) -> None:
    c, _ = login(jp["app"], "crc", PW)
    data = fx.release_zip()
    sha = re.search(r'name="sha256" value="([0-9a-f]{64})"', _check(c, data).text)
    assert sha
    r = _load(c, data, sha.group(1), approved=False)
    assert r.status_code == 422 and 'data-code="LIC-APPROVAL"' in r.text
    r = _load(c, fx.release_zip(version="V9.98"), sha.group(1))
    assert r.status_code == 422 and 'data-code="LIC-UPLOAD-CHANGED"' in r.text
    assert licensed.status(jp["svc"].store.db.url)[0]["state"] == "not_loaded"
    assert not [e for e in _events(tmp_path) if e.get("event") == "terminology.load"]


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"this is not a zip", "LIC-UPLOAD-ZIP"), (fx.release_zip(drop=("readme.txt",)), "LIC-RELEASE-MISSING")],
    ids=["not a zip", "the loader's refusal"],
)
def test_a_refusal_shows_its_code_and_reason_never_a_traceback(jp: dict[str, Any], data: bytes, code: str) -> None:
    c, _ = login(jp["app"], "crc", PW)
    r = _check(c, data)
    assert r.status_code == 422 and f'data-code="{code}"' in r.text
    assert "Traceback" not in r.text and 'File "' not in r.text


def test_a_file_over_the_cap_is_refused_before_it_is_sent(jp: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from sitesetup import medis_release

    monkeypatch.setattr(medis_release, "MAX_ZIP", 100)
    c, _ = login(jp["app"], "crc", PW)
    before = len(jp["calls"])
    r = _check(c, fx.release_zip())
    assert r.status_code == 422 and 'data-code="LIC-UPLOAD-SIZE"' in r.text
    assert not [(m, p) for m, p in jp["calls"][before:] if m == "POST" and p.startswith("/setup/terminology/medis")]


def test_only_the_set_up_row_opens_the_step(jp: dict[str, Any]) -> None:
    """The coordinator and the administrator (the matrix row ``site.setup``); the investigator and the viewer 403,
    as ``POST /site/codes`` answers them."""
    for user, pw, want in (("crc", PW, 200), ("admin", ADMIN_PW, 200), ("pi", PW, 403), ("viewer", VIEWER_PW, 403)):
        c, _ = login(jp["app"], user, pw)
        assert c.get(PAGE).status_code == want, user
        codes = c.get("/site/codes")
        assert ('data-testid="codes-medis"' in codes.text) is (want == 200 and codes.status_code == 200), user


def test_the_orchestrator_refuses_a_load_without_the_approval(jp: dict[str, Any]) -> None:
    import base64

    r = jp["oc"].post("/setup/terminology/medis/load", json={"b64": base64.b64encode(fx.release_zip()).decode()})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "LIC-APPROVAL"
    r = jp["oc"].post("/setup/terminology/medis/check", json={"b64": "not base64!"})
    assert r.status_code == 400


def test_where_the_layer_does_not_use_the_master_there_is_no_step(tw: dict[str, Any]) -> None:
    import base64

    c, _ = login(tw["app"], "crc", PW)
    assert c.get(PAGE).status_code == 404
    codes = c.get("/site/codes").text
    assert 'data-testid="codes-medis"' not in codes and PAGE not in codes
    r = tw["oc"].post("/setup/terminology/medis/check", json={"b64": base64.b64encode(fx.release_zip()).decode()})
    assert r.status_code == 404


def test_an_unsigned_call_to_the_orchestrator_is_refused(jp: dict[str, Any]) -> None:
    """The orchestrator's routes take the verified person for site.setup (``AS_SITE``, ``require_actor``), as the
    neighbouring set-up routes do; a direct call without the console's signed assertion is refused before anything is
    read or loaded."""
    import base64

    from fastapi.testclient import TestClient

    raw = TestClient(jp["oc"].app)  # no assertion
    body = {"b64": base64.b64encode(fx.release_zip()).decode(), "approved": True}
    for path in ("/setup/terminology/medis/check", "/setup/terminology/medis/load"):
        r = raw.post(path, json=body)
        assert r.status_code in (401, 403), (path, r.status_code)
    assert licensed.status(jp["svc"].store.db.url)[0]["state"] == "not_loaded"


def test_the_step_takes_the_set_up_pages_csrf(jp: dict[str, Any]) -> None:
    """Both changing routes refuse a form without the session's CSRF token, as POST /site/codes does."""
    c, _ = login(jp["app"], "crc", PW)
    before = len(jp["calls"])
    for tail, extra in (("/check", {}), ("/load", {"approved": "yes", "sha256": "0" * 64})):
        r = c.post(
            f"{PAGE}{tail}", data={"csrf": "not-the-token", **extra}, files={"file": ("x.zip", fx.release_zip())}
        )
        assert r.status_code == 400, tail
    assert not [(m, p) for m, p in jp["calls"][before:] if p.startswith("/setup/terminology/medis")]


def test_outside_the_layer_every_role_meets_an_absent_route(tw: dict[str, Any]) -> None:
    for user, pw in (("crc", PW), ("admin", ADMIN_PW), ("pi", PW), ("viewer", VIEWER_PW)):
        c, csrf = login(tw["app"], user, pw)
        assert c.get(PAGE).status_code == 404, user
        for tail in ("/check", "/load"):
            assert c.post(f"{PAGE}{tail}", data={"csrf": csrf}).status_code == 404, (user, tail)
    assert not [r for r in tw["app"].routes if getattr(r, "path", "").startswith(PAGE)]


# ------------------------------------------------------------------- the 複数分類コード beside a suggestion
DX_SYSTEM = "urn:hospital:dx-code"
MASTER_KEYS = {"ws", "domain", "system", "code", "display", "suggested_system", "suggested_code", "suggested_display",
               "method", "mapped_system", "mapped_code", "mapped_display", "mapped_by", "mapped_at", "confidence",
               "n"}  # fmt: skip  # GET /api/v1/site/codes's keys on master (local_code before version 3, and n)


def _codes_with(jp: dict[str, Any], also: list[str] | None, others: list[dict[str, str]] | None = None) -> None:
    sug = {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.2", "display": "テスト複分類病",
           "method": "licensed", "confidence": "1.00", **({"also": also} if also else {}),
           **({"candidates": others, "of": len(others) + 1} if others else {})}  # fmt: skip
    jp["svc"].store.put_local("main", "condition", DX_SYSTEM, "ZA17", "テスト複分類病", sug)


def test_the_codes_page_shows_the_further_codes_in_three_languages(jp: dict[str, Any]) -> None:
    from console.i18n_medis import EN, JA, ZH

    _codes_with(jp, ["N08.3"])
    c, csrf = login(jp["app"], "crc", PW)
    for lang, cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/site/codes"})
        page = c.get("/site/codes").text
        assert 'data-testid="also-ZA17"' in page and cat["site.codes.also"].replace("{codes}", "N08.3") in page
    v, _ = login(jp["app"], "pi", PW)  # the page's readers see it as they see the suggested code
    assert 'data-testid="also-ZA17"' in v.get("/site/codes").text


def test_without_further_codes_the_page_is_as_before_the_field(
    jp: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local codes page with this card's lines equals, byte for byte, the page rendered from the template without
    them, for a code with no further codes and one candidate: the lines add nothing then."""
    import re as _re

    import jinja2

    _codes_with(jp, None)
    c, _ = login(jp["app"], "crc", PW)
    tpl = (Path(__file__).resolve().parents[2] / "services" / "console" / "templates" / "site_codes.html").read_text(
        encoding="utf-8"
    )
    lines = [m.group(0) for m in _re.finditer(r"\{% if c\.(?:also|others) %\}.*?\{% endif %\}|\{% for o in c\.others %\}.*?"
                                              r"\{% endfor %\}", tpl)]  # fmt: skip
    assert len(lines) == 4  # the further codes; one of N; the further candidates; their buttons
    real = jinja2.FileSystemLoader.get_source

    def without(self: Any, env: Any, name: str) -> Any:
        src, fn, _up = real(self, env, name)
        if name == "site_codes.html":
            for line in lines:
                assert src.count(line) == 1
                src = src.replace(line, "")
        return src, fn, lambda: False  # read again next time

    def page() -> str:
        return _re.sub(r'(nonce|data-abs-left|data-idle-left)="[^"]*"', r'\1=""', c.get("/site/codes").text)

    monkeypatch.setattr(jinja2.FileSystemLoader, "get_source", without)
    before = page()
    monkeypatch.setattr(jinja2.FileSystemLoader, "get_source", real)
    page()  # the template read again as it is
    assert page() == before and "ZA17" in before


def test_the_api_twin_answers_as_before_with_and_without_the_field(jp: dict[str, Any]) -> None:
    from fastapi.testclient import TestClient

    c = TestClient(jp["app"])
    token = c.post("/api/v1/session", json={"username": "crc", "password": PW, "lang": "en"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    for also in (None, ["N08.3"]):
        _codes_with(
            jp, also, [{"code": "I10", "display": "テスト病乙", "method": "licensed_related"}] if also else None
        )
        rows = c.get("/api/v1/site/codes").json()
        assert rows and all(set(r) == MASTER_KEYS for r in rows), (also, sorted(rows[0]))
        assert "N08.3" not in json.dumps(rows) and "I10" not in json.dumps(rows)


def test_the_codes_page_offers_every_candidate_as_one_of_n(jp: dict[str, Any]) -> None:
    from console.i18n_medis import EN

    _codes_with(jp, None, [{"code": "I10", "display": "テスト病乙", "method": "licensed_related"}])
    c, _ = login(jp["app"], "crc", PW)
    page = c.get("/site/codes").text
    assert 'data-testid="of-ZA17"' in page and EN["site.codes.one_of"].replace("{n}", "2") in page
    assert 'data-testid="use-ZA17"' in page and 'data-testid="use-ZA17-I10"' in page  # each one a person can take
    related = EN["site.codes.method.licensed_related"].split(": ", 1)[1]  # the words after the apostrophe's escape
    assert 'data-testid="others-ZA17"' in page and related in page


def test_one_release_shows_one_fingerprint_and_a_second_load_is_asked_for(jp: dict[str, Any], tmp_path: Path) -> None:
    """The page, the audit and the store's status give the zip's SHA-256; loading the release in use again needs
    the person's "load it again"; the audit's detail names the fingerprint beside the version and the counts."""
    import hashlib

    c, _ = login(jp["app"], "crc", PW)
    data = fx.release_zip()
    sha = hashlib.sha256(data).hexdigest()
    _load(c, data, sha)
    st = next(s for s in licensed.status(jp["svc"].store.db.url) if s["kind"] == "medis")
    ev = [
        e
        for e in _events(tmp_path)
        if e.get("event") == "terminology.load" and e["detail"].get("kind") == "medis_release"
    ]
    assert st["sha256"] == sha == ev[0]["output_sha"] == ev[0]["detail"]["sha256"]
    again = _check(c, data)
    assert 'data-testid="medis-already"' in again.text and 'data-testid="medis-again"' in again.text
    r = _load(c, data, sha)  # without "load it again"
    assert r.status_code == 422 and 'data-code="LIC-ALREADY-LOADED"' in r.text
    page = c.get(PAGE)
    r = c.post(f"{PAGE}/load", data={"csrf": _csrf(page.text), "sha256": sha, "approved": "yes", "again": "yes"},
               files={"file": ("byomei999.zip", data)})  # fmt: skip
    assert r.status_code == 200 and 'data-testid="medis-done"' in r.text
    ev = [
        e
        for e in _events(tmp_path)
        if e.get("event") == "terminology.load" and e["detail"].get("kind") == "medis_release"
    ]
    assert len(ev) == 2 and ev[1]["detail"]["again"] is True
    other = fx.release_zip(version="V9.98")  # another release: no notice
    assert 'data-testid="medis-already"' not in _check(c, other).text
