"""TB-PLAN-04 step 4b, easy for novices (D-133): the safety fixes of the novice UX review
(``docs/reviews/2026-11-08-ux-review-novice.md``) and the pages that guard them."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from console.i18n import CATALOGUES
from fastapi.testclient import TestClient

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
)
from tests.console.test_step3 import _connect, b3  # noqa: F401 - the fixture is used by name

PW = "step-4b-password-0001"
A, B = "a" * 32, "b" * 32


def _user(b: dict[str, Any], name: str, role: str) -> TestClient:
    b["users"].create(name, role, PW, f"{name}@hospa.test")
    c, _ = login(b["app"], name, PW)
    return c


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = [json.loads(x) for f in sorted((b["dir"] / "audit").glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    return [e for e in out if e.get("event") == name]


def test_not_suitable_needs_a_reason_on_the_page_and_the_api_and_undo_restores(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-03: a tap with no reason used to record "other illness"; now it is refused, and Undo puts back the
    mark before (here: none)."""
    _done_screen(box["backend"], _ulid(961))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get(f"/studies/GZQO/week?pid={B}").text
    sel = page.split(f'<select id="reason-{B[:8]}"')[1][:300]
    assert " required " in sel and '<option value="">' in sel  # "Choose a reason" first, empty, required
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "not_suitable"})
    assert r.status_code == 400 and "Choose a reason first" in r.text and "<h1>" in r.text
    tok = pi.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    r = pi.post(f"/api/v1/studies/GZQO/patients/{B}/mark", json={"mark": "not_suitable"}, headers=hdr)
    assert r.status_code == 400 and r.json()["error"] == "mark.reason_needed"
    assert not _events(box, "console.pi_mark")  # nothing was recorded
    r = pi.post(
        f"/studies/GZQO/patients/{B}/mark",
        data={"csrf": _csrf(page), "mark": "not_suitable", "reason": "comorbidity", "back": "list:all"},
        follow_redirects=True,
    )
    # the panel shows this patient's real state (set aside) and offers Undo, not the next patient
    assert 'data-testid="undo"' in r.text and f'data-testid="reason-{B[:8]}"' in r.text
    assert 'data-testid="current-mark"' in r.text
    r = pi.post(
        f"/studies/GZQO/patients/{B}/mark",
        data={"csrf": _csrf(page), "mark": "undo", "back": "list:all"},
        follow_redirects=True,
    )
    assert r.status_code == 200 and "Undone" in r.text and f'data-testid="row-{B[:8]}"' in r.text
    marks = [e["detail"] for e in _events(box, "console.pi_mark")]
    assert [m["action"] for m in marks] == ["not_suitable", "withdrawn"] and marks[-1]["undo"] == "not_suitable"
    # Undo of a replacing mark puts the earlier mark back, with its reason
    for mk, extra in (("need_info", {}), ("not_suitable", {"reason": "unlikely"}), ("undo", {})):
        pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": mk, **extra})
    p = pi.get(f"/studies/GZQO/patients/{B}").text
    assert 'data-tone="warn"' in p.split('data-testid="current-mark"')[1][:200]


def test_contact_outcome_only_after_the_investigators_approach(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-36: the coordinator records a call only for a patient the investigator approved; the shared action
    refuses otherwise, so the page and /api/v1 refuse alike."""
    _done_screen(box["backend"], _ulid(962))
    crc = _user(box, "crc1", "coordinator")
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="outcome-wait"' in page and 'data-testid="outcomes"' not in page
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": _csrf(page), "outcome": "reached_booked"})
    assert r.status_code == 409 and "has not marked this patient" in r.text
    tok = crc.post("/api/v1/session", json={"username": "crc1", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    r = crc.post(f"/api/v1/studies/GZQO/patients/{A}/outcome", json={"outcome": "reached_booked"}, headers=hdr)
    assert r.status_code == 409 and r.json()["error"] == "outcome.wait_pi"
    assert not _events(box, "console.contact_outcome") and _events(box, "console.refused")
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    pp = pi.get(f"/studies/GZQO/patients/{A}").text
    pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(pp), "mark": "need_info"})
    r = crc.post(f"/api/v1/studies/GZQO/patients/{A}/outcome", json={"outcome": "reached_booked"}, headers=hdr)
    assert r.status_code == 409  # "need info" is not an approval
    pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(pp), "mark": "approach"})
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="outcomes"' in page
    r = crc.post(f"/api/v1/studies/GZQO/patients/{A}/outcome", json={"outcome": "reached_booked"}, headers=hdr)
    assert r.status_code == 200 and len(_events(box, "console.contact_outcome")) == 1


def test_one_time_password_never_in_a_url_and_readable(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-02."""
    c, csrf = login(box["app"], "admin", ADMIN_PW)
    r = c.post(
        "/ops/users",
        data={"csrf": csrf, "action": "add", "username": "newcrc", "role": "viewer"},  # D-719: aggregate
        follow_redirects=False,
    )
    loc = r.headers["location"]
    assert r.status_code == 303 and "pw" not in loc and "newcrc" not in loc
    page = c.get(loc).text
    pw = re.search(r'value="([^"]+)" data-testid="users-pw-field"', page)
    assert pw and re.fullmatch(r"([a-hj-km-np-z2-9]{4}-){4}[a-hj-km-np-z2-9]{4}", pw.group(1))
    groups = re.findall(r"<span>([a-z2-9]{4})</span>", page.split('class="otp"')[1].split("</p>")[0])
    assert "-".join(groups) == pw.group(1)  # shown in groups of four
    assert 'data-testid="handover"' in page and 'data-copy="otp-value"' in page
    assert pw.group(1) not in c.get("/ops/users").text  # shown once
    assert all(
        pw.group(1) not in json.dumps(e) for f in (box["dir"] / "audit").glob("*.jsonl") for e in [f.read_text()]
    )
    n, _ = login(box["app"], "newcrc", pw.group(1))  # and it works, typed as shown
    assert n.get("/home").status_code == 200


def test_unknown_study_answers_404_on_every_study_page(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-37: a mistyped study code used to render an empty set-up form and a week page."""
    crc = _user(box, "crc1", "coordinator")
    for path in ("setup", "week", "screening-log", "sources", "conflicts", "forms", "entry", "feasibility"):
        r = crc.get(f"/studies/NOPE-01/{path}", headers={"accept": "text/html"})
        assert r.status_code == 404, path
        assert "<h1>" in r.text and 'data-testid="problem-home"' in r.text and 'data-testid="problem-help"' in r.text
    assert crc.get("/studies/GZQO/setup").status_code == 200


def test_error_pages_have_a_heading_a_reason_and_three_ways_on(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-12."""
    crc = _user(box, "crc1", "coordinator")
    for path, status, heading in (("/no-such-page", 404, "Page not found"), ("/ops/users", 403, "another role")):
        r = crc.get(path, headers={"accept": "text/html"})
        assert r.status_code == status and heading in r.text
        for b in ("problem-home", "problem-back", "problem-help"):
            assert f'data-testid="{b}"' in r.text
    crc.post("/lang", data={"csrf": _csrf(crc.get("/home").text), "lang": "ja", "back": "/home"})
    r = crc.get("/no-such-page", headers={"accept": "text/html"})
    assert "ページが見つかりません" in r.text and "Not found" not in r.text


def test_sign_in_page_language_and_lockout_countdown(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-05: a language choice before sign-in; a locked account says until when and whom to ask."""
    c = TestClient(box["app"])
    page = c.get("/login?lang=zh-TW").text
    assert '<html lang="zh-TW">' in page and 'data-testid="login-lang"' in page and "管理者" in page
    tok = re.search(r'name="login_csrf" value="([^"]+)"', page)
    assert tok
    for _ in range(5):
        r = c.post("/login", data={"username": "admin", "password": "wrong-password!", "login_csrf": tok.group(1)})
        tok = re.search(r'name="login_csrf" value="([^"]+)"', r.text)
        assert tok
    assert r.status_code == 401 and 'data-testid="login-locked"' in r.text and "15 分鐘" in r.text
    real = box["users"].clock
    box["users"].clock = lambda: real() + timedelta(minutes=6)
    r = c.post("/login", data={"username": "admin", "password": "wrong-password!", "login_csrf": tok.group(1)})
    assert "還要鎖定 9 分鐘" in r.text  # the minutes left count down
    box["users"].clock = real
    # the language picked before sign-in is the session's language
    c2 = TestClient(box["app"])
    tok2 = re.search(r'name="login_csrf" value="([^"]+)"', c2.get("/login?lang=ja").text)
    assert tok2
    box["users"].create("nurse", "coordinator", PW, None)
    c2.post("/login", data={"username": "nurse", "password": PW, "login_csrf": tok2.group(1)})
    assert '<html lang="ja">' in c2.get("/home").text


def test_audit_trail_is_paged(box: dict[str, Any]) -> None:  # noqa: F811
    """Review F-07: the audit page held 300 events (130 phone screens)."""
    for i in range(120):
        box["audit"].append("console.login", actor=f"console:u{i}")
    box["users"].create("dpo", "privacy", ADMIN_PW, "dpo@hospa.test")  # D-451: the privacy office reads the trail
    c, _ = login(box["app"], "dpo", ADMIN_PW)
    p1 = c.get("/audit").text
    assert p1.count("<tr data-event=") == 50 and 'data-testid="audit-older"' in p1

    def older(page: str) -> str:  # the next page is a cursor, not a page number (D-451)
        m = re.search(r'href="([^"]+)" rel="next"', page)
        assert m
        return m.group(1).replace("&amp;", "&")

    p3 = c.get(older(c.get(older(p1)).text)).text
    assert "<tr data-event=" in p3 and 'data-testid="audit-older"' not in p3


def test_every_new_key_in_every_language() -> None:
    from console import i18n_4b

    assert set(i18n_4b.EN) == set(i18n_4b.JA) == set(i18n_4b.ZH)
    for lang in ("ja", "zh-TW"):  # D-133 glossary: one hospital word per concept on the clinic pages
        cat = CATALOGUES[lang]
        for word in ("ジョブ", "ルールセット", "コンパイル", "サインイン", "(?<!コント)ロール", "(?<!信)箱", "装置",
                     "工作(?![簿日天])", "規則集", "編譯", "贊助者", "權杖", "已納入"):  # fmt: skip
            # the intended-use statement (TB-IU-01 §1) is quoted as signed: 工作人員 there means staff, not a job
            bad = [k for k, v in cat.items() if re.search(word, v) and k != "footer.statement"]
            assert not bad, (lang, word, bad[:5])
        # review 2026-11-09 P-08 (D-143): one word per participant state, on the screening log and the lifecycle
        # pages alike (enrolled: 登録 / 已收案, the glossary's words), so the two exports agree in words too
        assert cat["registry.status.enrolled"] == cat["life.state.enrolled"], lang


def test_the_setup_page_says_what_trialbox_writes_to_redcap() -> None:
    """Review 2026-11-09 P-07 (D-143): "Nothing is ever written to REDCap" sat under the write-back switch."""
    for lang, never, write in (("en", "Nothing is ever written", "write-back is on"),
                               ("ja", "何も書き込みません", "書き戻しをオンにしたとき"),
                               ("zh-TW", "從不寫入", "開啟回寫")):  # fmt: skip
        text = CATALOGUES[lang]["rc.read.help"]
        assert never not in text and write in text, lang


def test_confirmations_and_excluded_page_words_in_every_language() -> None:
    """D-143: the wave-1b strings (P-04 page, P-10 confirmations) exist in en, ja and zh-TW with the same blanks."""
    from console import i18n_review

    assert set(i18n_review.EN) == set(i18n_review.JA) == set(i18n_review.ZH)
    for cat in (i18n_review.JA, i18n_review.ZH):
        for k, v in cat.items():
            assert sorted(re.findall(r"\{(\w+)\}", v)) == sorted(re.findall(r"\{(\w+)\}", i18n_review.EN[k])), k
            assert not v.isascii(), k
    assert CATALOGUES["ja"]["confirm.yes"] == "はい、実行します" and CATALOGUES["zh-TW"]["confirm.no"] == "否，返回"


def test_setup_is_one_form_and_reads_the_redcap_fields(b3: dict[str, Any]) -> None:  # noqa: F811
    """Review F-04 and F-11: one Save keeps every section; the REDCap fields are picked from the dictionary."""
    _connect(b3)
    b3["users"].create("crc4b", "coordinator", PW, "crc4b@hospa.test")
    c, csrf = login(b3["app"], "crc4b", PW)
    page = c.get("/studies/GZQO/setup").text
    assert page.count('data-testid="save-setup"') == 1 and "data-guard" in page
    form = {"csrf": csrf, "study_type": "trial", "cohort_kind": "enrolled", "consent_scope": "opt-in",
            "screening_prefix": "GZ-", "first_no": "960", "reasons": ["stage", "other"], "token_ref": "main"}  # fmt: skip
    r = c.post("/studies/GZQO/setup", data={**form, "action": "read"})
    assert r.status_code == 200 and 'data-testid="dict-read"' in r.text and 'data-testid="pick-consent_field"' in r.text
    assert 'value="GZ-"' in r.text and 'value="960"' in r.text  # what was typed is kept, nothing saved yet
    assert b3["svc"].store.settings("GZQO") is None
    assert '<option value="consent_date"' in r.text
    r = c.post(
        "/studies/GZQO/setup",
        data={
            **form,
            "action": "save",
            "project_id": "101",
            "link_field": "tb_screening_no",
            "consent_field": "consent_date",
            "enrol_field": "enrolled",
            "enrol_value": "1",
            "screenfail_field": "sf_reason",
            "subject_no_field": "subject_no",
        },
        follow_redirects=True,
    )
    assert 'data-testid="setup-saved"' in r.text and 'data-testid="link-on"' in r.text
    row = b3["svc"].store.settings("GZQO")
    assert row["screening_no_format"] == "GZ-" and row["consent_scope"] == "opt-in"  # both sections, one Save
    assert row["not_suitable_reasons"] == ["stage", "other"]
