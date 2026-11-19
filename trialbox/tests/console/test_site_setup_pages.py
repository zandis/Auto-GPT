"""TB-PLAN-04 step 5b (D-131, D-132, D-135): the site set-up pages, their ``/api/v1`` routes and Ask TrialBox, on the
orchestrator's real set-up API (a real ``sitesetup`` store, the stub model, an in-process lake).

The path through the console: the readiness page (red) → a chart pasted → the proposed facts beside their quotes
→ one tap to confirm → the IT dump → the hospital codes mapped with one tap each → the messy list → the "please
check" answers → the disagreement → the readiness green. Roles, the three languages, the templates, the practice
site, the remote-help switch, and the assistant's read-only rule.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from console.backend import problem_of
from console.i18n_site import EN as S_EN
from console.i18n_site import JA as S_JA
from console.i18n_site import ZH as S_ZH
from embed_service.embedder import HashEmbedder
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lake.client import LakeLocal
from llm_stub.app import app as stub
from orchestrator.setup_api import router as setup_router
from sitesetup import help as site_help
from sitesetup.ocr import NoOcr
from sitesetup.service import SiteSetup
from sitesetup.store import SetupStore
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn
from tb_common.llm import LlmClient

from tests.actor3 import SignedClient
from tests.console.test_console_app import VIEWER_PW, box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.unit.test_site_setup import site_ruleset

PW = "site-setup-password-0001"
KEY = b"site-setup-console-key-0123456789ab"
NOW = datetime(2026, 11, 2, 0, 30, tzinfo=UTC)
TODAY = date(2026, 11, 2)


DOOR_EVENTS: list[dict[str, Any]] = []


def _door(request: Any, actions: tuple[str, ...], service: bool = False) -> Any:
    """T-719 (D-487): the real door (``orchestrator.identifiers.admit``) on these pages' router: a chart or a sheet
    turns chart numbers into pseudonyms, so the console's call must carry the signed person (`site.setup`). The
    cap's counter and the audit log are stand-ins; the decision is the product's."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from orchestrator import identifiers

    db = SimpleNamespace(take_limit=lambda *a, **k: True)
    audit = SimpleNamespace(append=lambda kind, **kw: DOOR_EVENTS.append({"kind": kind, **kw}))
    return identifiers.admit(request, None, db, audit, datetime.now(UTC), actions=actions, service=service)


@pytest.fixture
def sb(box: dict[str, Any], tmp_path: Path) -> Iterator[dict[str, Any]]:  # noqa: F811
    llm = LlmClient("http://stub/v1", "stub")
    llm.http = TestClient(stub)
    svc = SiteSetup(
        SetupStore(),
        tmp_path / "setup",
        LakeLocal(tmp_path / "main-lake", HashEmbedder()),
        llm,
        AuditLog(tmp_path / "orch-audit"),
        lambda: NOW,
        lambda: TODAY,
        lambda: KEY,
        ocr=NoOcr(),
        mrn_regex=r"^\d{8}$",
    )
    rs = site_ruleset()
    state = {"approved": True, "forms": 0, "real": False}
    api = FastAPI()
    api.include_router(
        setup_router(
            lambda: svc,
            lambda rid: {
                "id": rid,
                "exists": True,
                "approved": "1.0.0" if state["approved"] else None,
                "waiting": 0 if state["approved"] else 1,
                "approval_link": "/pilot/jobs/X/approval",
            },
            lambda rid: {"forms": state["forms"], "redcap": False},
            lambda rid: rs if state["approved"] else None,
            lambda: bool(state["real"]),
            _door,
        ),
    )  # T-715g (D-803): as orchestrator.app includes it, with no report stage (the routes refuse themselves)
    oc = SignedClient(api)  # the test's own calls (seeding)
    coc = SignedClient(api, strict=True)  # the console's calls: it signs them itself (review M3)
    calls: list[tuple[str, str]] = []

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        calls.append((method, path))
        kw: dict[str, Any] = {"headers": headers} if headers else {}  # T-715: the signed person goes with the call
        r = coc.request(method, path, json=body, **kw) if body is not None else coc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    box["backend"].study_api = study_api
    for name, role in (("crc", "coordinator"), ("pi", "investigator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    yield {**box, "svc": svc, "state": state, "calls": calls, "oc": oc}
    svc.store.close()


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _form(c: TestClient, path: str, data: dict[str, Any], files: dict[str, Any] | None = None) -> Any:
    page = c.get(
        path.split("#", maxsplit=1)[0] if path.startswith("/site") and "?" in path else "/site?ws=main&study=GZQO"
    )
    return c.post(path, data={"csrf": _csrf(page.text), "ws": "main", "study": "GZQO", **data}, files=files)


def _snapshot(svc: SiteSetup) -> str:
    out = {}
    for t in ("input", "fact", "local_code", "check_item", "fix", "setting", "published"):
        out[t] = [sorted(map(str, r.values())) for r in svc.store.db.fetchdicts(f"SELECT * FROM {t}")]
    return json.dumps(out, sort_keys=True)


def test_set_up_through_the_pages_to_green(sb: dict[str, Any]) -> None:
    c, _ = login(sb["app"], "crc", PW)
    r = c.get("/site?study=GZQO")
    assert r.status_code == 200 and 'data-testid="q-patients" data-state="red"' in r.text
    assert 'data-testid="miss-forms"' in r.text and 'data-testid="feas-needs-bulk"' in r.text
    # a chart pasted with its chart number: three taps (number, text, Read)
    no, text = site_help.PRACTICE_CHARTS[0]
    r = _form(c, "/site/charts", {"chart_no": no, "text": text})
    assert 'data-testid="chart-saved"' in r.text and no not in r.text
    r = c.get("/site/facts?study=GZQO")
    assert 'data-testid="quote-' in r.text and "尿酸 8.8 mg/dL" in r.text and "青木" not in r.text
    fids = re.findall(r'data-testid="confirm-(\d+)"', r.text)
    assert len(fids) >= 5
    page = c.get("/site?study=GZQO").text
    assert 'data-testid="miss-proposed"' in page and 'data-testid="miss-bulk"' in page
    # one tap confirms one fact
    r = c.post(f"/site/facts/{fids[0]}", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "action": "confirm"})
    assert 'data-testid="fact-done"' in r.text and f'data-testid="confirm-{fids[0]}"' not in r.text
    r = c.post(
        f"/site/facts/{fids[1]}",
        data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "action": "correct", "value": "1961-04-04"},
    )
    assert 'data-testid="fact-done"' in r.text
    for fid in fids[2:]:
        c.post(f"/site/facts/{fid}", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "action": "confirm"})
    # the IT dump and the PI's list, read from files
    dump_name, dump = site_help.practice_inputs()["dump"]
    r = c.post(
        "/site/sheets",
        data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "kind": "dump"},
        files={"file": (dump_name, dump, "text/csv")},
    )
    assert 'data-testid="sheet-done"' in r.text
    sheet_name, sheet = site_help.practice_inputs()["sheet"]
    r = c.post(
        "/site/sheets",
        data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "kind": "sheet"},
        files={"file": (sheet_name, sheet, "application/octet-stream")},
    )
    assert "氏名" in r.text and "山田" not in r.text and "青山" not in r.text  # the column is named, its names never
    # codes: each suggestion shows how sure it is (scenario run MAP-01)
    page = c.get("/site/codes?study=GZQO").text
    assert re.search(r'data-testid="confidence-[^"]+">[^<]*\d+%', page), page[-800:]
    # codes: one tap each on the suggestion; a code without one is typed
    for _ in range(12):
        page = c.get("/site/codes?study=GZQO").text
        todo = re.findall(r'data-testid="map-([^"]+)"', page)
        if not todo:
            break
        code = todo[0]
        form = re.search(rf'data-testid="map-{re.escape(code)}">(.*?)</form>', page, re.S)
        assert form
        hidden = dict(re.findall(r'name="(domain|system|code)" value="([^"]*)"', form.group(1)))
        use = re.search(r'name="use" value="([^"-][^"]*)"', form.group(1))
        data = {"csrf": _csrf(page), "ws": "main", "study": "GZQO", **hidden}
        data |= {"use": use.group(1)} if use else {"target": "I10"}
        r = c.post("/site/codes", data=data)
        assert 'data-testid="code-done"' in r.text, r.text[-500:]
    assert 'data-testid="codes-none"' in c.get("/site/codes?study=GZQO").text
    # please check: the suggested answer for each, except the ID column, which is left out
    for _ in range(10):
        page = c.get("/site/checks?study=GZQO").text
        ids = re.findall(r'data-testid="check-(\d+)" data-kind="([a-z_]+)"', page)
        if not ids:
            break
        cid, kind = ids[0]
        block = re.search(rf'data-testid="check-{cid}".*?</li>', page, re.S)
        assert block
        opts = re.findall(r'name="answer" value="([^"]+)"( class="secondary")?', block.group(0))
        answer = "drop" if kind == "chart_column" else next(o for o, sec in opts if not sec)
        c.post(f"/site/checks/{cid}", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "answer": answer})
    page = c.get("/site/checks?study=GZQO").text
    assert (
        'data-testid="checks-none"' in page and 'data-testid="fix-era"' in page and 'data-testid="fix-minguo"' in page
    )
    # new codes from the list's answers, then the disagreement
    for _ in range(6):
        page = c.get("/site/codes?study=GZQO").text
        todo = re.findall(r'data-testid="use-([^"]+)"', page)
        rest = re.findall(r'data-testid="map-other-([^"]+)"', page)
        if not rest:
            break
        code = (todo or rest)[0]
        form = re.search(rf'data-testid="map-{re.escape(code)}">(.*?)</form>', page, re.S)
        assert form
        hidden = dict(re.findall(r'name="(domain|system|code)" value="([^"]*)"', form.group(1)))
        use = re.search(r'name="use" value="([^"-][^"]*)"', form.group(1))
        c.post(
            "/site/codes",
            data={
                "csrf": _csrf(page),
                "ws": "main",
                "study": "GZQO",
                **hidden,
                **({"use": use.group(1)} if use else {"target": "I10"}),
            },
        )
    page = c.get("/site/people?study=GZQO").text
    keep = re.findall(r'name="keep" value="([^"]+)"', page)
    pid = pid_for_mrn(KEY, "10000002")
    assert keep == ["1971-05-06", "1971-06-05"] and f'data-testid="dis-{pid[:8]}-birth_date"' in page
    r = c.post(
        "/site/people/resolve",
        data={
            "csrf": _csrf(page),
            "ws": "main",
            "study": "GZQO",
            "pid": pid,
            "what": "birth_date",
            "keep": "1971-06-05",
        },
    )
    assert 'data-testid="people-done"' in r.text
    sb["state"]["forms"] = 7
    r = c.get("/site?study=GZQO")
    assert 'data-testid="site-overall" data-state="green"' in r.text, re.findall(r'data-testid="miss-[^"]+"', r.text)
    assert 'data-testid="feas-basis"' in r.text
    pc = c.get("/site/patients?study=GZQO").text
    assert f'data-testid="pc-{pid_for_mrn(KEY, "10000004")[:8]}" data-state="ready"' in pc
    assert f'data-testid="pc-{pid_for_mrn(KEY, "10000005")[:8]}" data-state="ready"' in pc  # no chart here: coded only
    # nothing on any page shows a chart number or a name
    for p in ("/site", "/site/facts", "/site/codes", "/site/checks", "/site/sheets", "/site/people", "/site/patients"):
        html = c.get(f"{p}?study=GZQO&show=confirmed").text
        assert not re.search(r"1000000[0-9]", re.sub(r'data-testid="[^"]*"', "", html)), p
        assert "青木" not in html and "青山" not in html, p


def test_every_page_in_three_languages_and_roles(sb: dict[str, Any]) -> None:
    name_pi(sb, "pi")  # D-380 (ROLE-008): the steward names the PI
    sb["svc"].add_chart(
        "main",
        *site_help.PRACTICE_CHARTS[1][:1],
        "pasted.txt",
        site_help.PRACTICE_CHARTS[1][1].encode(),
        "crc",
        "zh-TW",
        pasted=True,
    )
    pages = [
        "/site",
        "/site/start",
        "/site/start?step=2",
        "/site/start?step=5",
        "/site/charts",
        "/site/facts",
        "/site/codes",
        "/site/checks",
        "/site/sheets",
        "/site/people",
        "/site/patients",
        "/site/help",
        "/ask",
        "/ask?q=next",
        "/help?back=/site",
    ]
    for user in ("crc", "pi"):
        c, csrf = login(sb["app"], user, PW)
        for lang in ("en", "ja", "zh-TW"):
            c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/site"})
            for p in pages:
                r = c.get(p + ("&" if "?" in p else "?") + "study=GZQO")
                assert r.status_code == 200, (user, lang, p, r.status_code)
                assert not re.search(r"\b(site|ask)\.[a-z_]+\.[a-z_.]+\b", re.sub(r"<[^>]+>", " ", r.text)), (
                    user,
                    lang,
                    p,
                    re.findall(r"\b(?:site|ask)\.[a-z_]+\.[a-z_.]+\b", r.text)[:3],
                )
                assert f'<html lang="{lang}">' in r.text
    # the investigator reads; changes are the coordinator's and the administrator's
    pi, _ = login(sb["app"], "pi", PW)
    page = pi.get("/site/facts?study=GZQO").text
    assert 'data-testid="confirm-' not in page and 'data-testid="quote-' in page
    fid = sb["svc"].store.facts("main", "proposed")[0]["id"]
    r = pi.post(f"/site/facts/{fid}", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "action": "confirm"})
    assert r.status_code == 403
    v, _ = login(sb["app"], "viewer", VIEWER_PW)
    assert v.get("/site").status_code == 403 and v.get("/site/facts").status_code == 403
    assert v.get("/ask?q=next").status_code == 200  # the assistant answers every role, from what it may see


def test_templates_practice_site_and_remote_help(sb: dict[str, Any]) -> None:
    from openpyxl import load_workbook

    c, csrf = login(sb["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "zh-TW", "back": "/site/help"})
    x = c.get("/site/templates/candidates.xlsx")
    assert x.status_code == 200 and load_workbook(io.BytesIO(x.content)).worksheets[0]["A1"].value == "病歷號"
    page = c.get("/site/help").text
    r = c.post("/site/practice", data={"csrf": _csrf(page), "action": "load", "study": "GZQO"})
    assert "/site" in str(r.url) and "ws=practice" in str(r.url) and r.status_code == 200
    assert sb["svc"].store.inputs("practice") and not sb["svc"].store.inputs("main")
    r = c.post("/site/practice", data={"csrf": _csrf(page), "action": "reset", "study": "GZQO"})
    assert not sb["svc"].store.inputs("practice")
    # remote help: off by default; only an administrator switches it; with real data an approval is needed
    assert 'data-on="0"' in page and 'data-testid="remote-form"' not in page
    r = c.post("/site/remote", data={"csrf": _csrf(page), "on": "1"})
    assert r.status_code == 403
    a, acsrf = login(sb["app"])
    sb["state"]["real"] = True
    r = a.post("/site/remote", data={"csrf": acsrf, "on": "1"})
    assert 'data-testid="help-err"' in r.text and sb["svc"].store.setting("remote_help") != "on"
    r = a.post("/site/remote", data={"csrf": acsrf, "on": "1", "approved_by": "IT 部長 田中"})
    assert 'data-on="1"' in r.text and sb["svc"].store.setting("remote_help") == "on"
    r = a.post("/site/remote", data={"csrf": acsrf, "on": "0"})
    assert 'data-on="0"' in r.text


def test_codes_page_says_which_licensed_lists_are_loaded(sb: dict[str, Any]) -> None:
    """D-137: the hospital-codes page lists MEDIS, JLAC10 and YJ as loaded (version, codes, day) or not loaded, in
    the page's language; a loaded list's codes are suggested as the hospital's licensed list."""
    from adapter.licensed import TermStore

    c, csrf = login(sb["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/site/codes"})
    page = c.get("/site/codes?study=GZQO").text
    # D-1252: the MEDIS modifier table is a fourth licensed list (was 3)
    for kind in ("medis", "medis_modifier", "jlac10", "yj"):
        assert f'data-testid="code-list-{kind}" data-state="not_loaded"' in page
    assert page.count(S_JA["site.codes.list.not_loaded"]) == 4
    st = TermStore()
    try:
        sample = Path(__file__).resolve().parents[1] / "fixtures" / "licensed" / "medis_byomei_sample.txt"
        st.load("medis", sample.read_bytes(), version="2026.10", source=sample.name, by="admin")
    finally:
        st.close()
    page = c.get("/site/codes?study=GZQO").text
    assert 'data-testid="code-list-medis" data-state="loaded"' in page and "2026.10" in page
    assert S_JA["site.codes.list.medis"] in page and page.count(S_JA["site.codes.list.not_loaded"]) == 3  # was 2
    c.post("/lang", data={"csrf": csrf, "lang": "zh-TW", "back": "/site/codes"})
    assert S_ZH["site.codes.lists"] in c.get("/site/codes?study=GZQO").text
    c.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/site/codes"})
    assert S_EN["site.codes.lists"] in c.get("/site/codes?study=GZQO").text


def test_api_v1_charts_facts_codes_checks(sb: dict[str, Any]) -> None:
    c = TestClient(sb["app"])
    r = c.post("/api/v1/session", json={"username": "crc", "password": PW, "lang": "ja"})
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    no, text = site_help.PRACTICE_CHARTS[0]
    out = c.post("/api/v1/site/charts", json={"chart_no": no, "text": text}).json()
    assert out["facts"] >= 5 and no not in json.dumps(out)
    facts = c.get("/api/v1/site/facts").json()
    assert all(f["status"] == "proposed" and f["quote"] for f in facts)
    r = c.post(f"/api/v1/site/facts/{facts[0]['id']}", json={"action": "confirm"})
    assert r.json()["status"] == "confirmed"
    r = c.post("/api/v1/site/charts", json={"chart_no": "", "text": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SETUP-KEY"
    rd = c.get("/api/v1/site/readiness?study=GZQO").json()
    assert rd["questions"]["patients"]["state"] == "amber"
    ans = c.get("/api/v1/ask", params={"q": "次に何をすればよいですか？", "study": "GZQO"}).json()
    assert ans["kind"] == "next" and ans["answer"] and ans["links"]


def test_the_assistant_never_changes_anything(sb: dict[str, Any]) -> None:
    svc = sb["svc"]
    for no, text in site_help.PRACTICE_CHARTS:
        svc.add_chart("main", no, "pasted.txt", text.encode(), "crc", "ja", pasted=True)
    c, csrf = login(sb["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/ask"})
    before = _snapshot(svc)
    sb["calls"].clear()
    r = c.get("/ask", params={"q": "次に何をすればよいですか？", "study": "GZQO"})
    assert 'data-testid="ask-answer" data-kind="next"' in r.text and "確認待ち" in r.text
    pid = pid_for_mrn(KEY, "10000005")
    r = c.get("/ask", params={"pid": pid, "q": "なぜリストにいるの？", "study": "GZQO"})
    assert 'data-kind="why"' in r.text and "カルテから読み取った未確認の情報" in r.text  # the reason, in Japanese
    for lang, q in (("en", "What do I do next?"), ("zh-TW", "下一步該做什麼？")):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/ask"})
        r = c.get("/ask", params={"q": q, "study": "GZQO"})
        assert 'data-kind="next"' in r.text and r.status_code == 200
    writes = [(m, p) for m, p in sb["calls"] if m != "GET" and p != "/assist"]
    assert not writes, writes  # every read is a GET; the only POST is the model's phrasing, which writes nothing
    assert _snapshot(svc) == before
    # the phrasing route itself reads and writes nothing, even when the model is down
    svc.llm.http = None  # any model call fails
    out = sb["oc"].post("/assist", json={"question": "q", "lang": "ja", "draft": "下書き", "points": []}).json()
    assert out == {"answer": "下書き", "model": False} and _snapshot(svc) == before


def test_words_in_three_languages() -> None:
    assert set(S_EN) == set(S_JA) == set(S_ZH)
    for cat in (S_JA, S_ZH):  # D-133's glossary: none of the old words
        for word in (
            "ジョブ",
            "ルールセット",
            "コンパイル",
            "サインイン",
            "(?<!コント)ロール",
            "(?<!信)箱",
            "装置",
            "工作(?![簿日天])",
            "規則集",
            "編譯",
            "贊助者",
            "權杖",
        ):
            assert not [k for k, v in cat.items() if re.search(word, v)], word


def test_a_patients_fact_needs_a_role_that_sees_patient_data(sb: dict[str, Any]) -> None:
    """T-715g (D-803), its review (3): the administrator holds ``site.setup`` but not ``phi.view``; the orchestrator
    refuses an administrator's signed change of a fact, a chart or a person, as the console's page does."""
    from tests.actor3 import signed

    for path, body in (("/setup/main/facts/1", {"action": "confirm", "changes": {}}),
                       ("/setup/main/charts", {"chart_no": "10000001", "text": "synthetic", "lang": "en"}),
                       ("/setup/main/people/resolve", {"pid": "a" * 32, "what": "sex", "keep": "F"})):  # fmt: skip
        hdr = signed("site.setup", "", "POST", path, body, sub="console:admin", role="admin")
        r = sb["oc"].post(path, json=body, headers=hdr)
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "right", (path, r.text[:200])
