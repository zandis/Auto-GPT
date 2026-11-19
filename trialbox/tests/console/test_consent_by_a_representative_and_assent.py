"""10C-19 (JP-20, D-1232): consent by a representative (代諾者) and the participant's assent (アセント) on the consent
record, on the console over the orchestrator's real data-core and lifecycle API. All data is synthetic.

With the setting on (``TB_CONSENT_PROXY=on``; unset, on in Japan): a minor whose consent names no representative
warns, one in the study's assent ages with no assent warns, a declined assent is an alert and the consent form is not
taken as consent to proceed (only a step with a reason is), an adult is unaffected; the warnings show on the
participant's page, the participants list and the screening log, and the log's XLSX has five columns at the end. With
the setting off nothing of it shows. Every role records and reads the new items exactly as it records and reads the
consent form today."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console import screening_log
from console.auth import ROLES
from datacore import builtin, proxy_consent
from datacore.sponsor import LOG_COLUMNS
from openpyxl import load_workbook

from tests.console.test_cjk_layout import PHONE, SCRIPT, _node_playwright
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf
from tests.console.test_team_pages import _events


def _orch(lb: dict[str, Any], name: str) -> list[dict[str, Any]]:  # noqa: F811
    """The orchestrator's audit events called ``name``."""
    out = []
    for f in sorted(lb["audit"].directory.glob("*.jsonl")):
        out.extend(e for line in f.read_text().splitlines() if line and (e := json.loads(line)).get("event") == name)
    return out

ROOT = Path(__file__).resolve().parents[2]
CONSENT = {"ic_date": "2026-10-06", "ic_version": "v1", "ic_copy": "1"}


def _ready(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch, on: bool = True) -> tuple[Any, str, str, str]:  # noqa: F811
    monkeypatch.setenv(proxy_consent.ENV, "on" if on else "off")
    no, other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    for rec in (no, other):
        c.post(f"/studies/GZQO/subjects/{rec}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-10-01"})
    return c, csrf, no, other


def _lang(c: Any, csrf: str, lang: str) -> None:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})


def test_the_setting_follows_the_japan_profile() -> None:
    assert proxy_consent.is_on({"TB_TZ": "Asia/Tokyo"}) is True
    assert proxy_consent.is_on({"TB_TZ": "Asia/Taipei"}) is False
    assert proxy_consent.is_on({"TB_TZ": "Asia/Tokyo", proxy_consent.ENV: "off"}) is False
    assert proxy_consent.is_on({"TB_TZ": "Asia/Taipei", proxy_consent.ENV: "on"}) is True
    # off, the built-in forms are the forms before the card; on, the coded relation replaces the free text
    off = [f.name for f in builtin.fields()]
    on = [f.name for f in builtin.fields(proxy=True)]
    assert not set(proxy_consent.FIELDS) & set(off) and "ic_lar_relation" in off
    assert set(proxy_consent.FIELDS) <= set(on) and "ic_lar_relation" not in on
    consent = [n for n in on if n.startswith("ic_")]
    assert consent[-len(proxy_consent.FIELDS) :] == list(proxy_consent.FIELDS)  # at the end of the consent form


def test_a_minor_without_a_representative_warns(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    form = c.get(f"/studies/GZQO/entry?record={no}&form=tb_consent").text
    assert 'data-testid="proxy-form-note"' in form and "Never a name, address or contact" in form
    assert 'data-testid="f-ic_lar_rel-1"' in form and 'data-testid="f-ic_lar_relation"' not in form
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "0"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    w = re.search(r'<p class="warn" role="alert" data-testid="proxy-w-no_representative">([^<]+)<a href="([^"]+)"', page)
    assert w and "Age 15" in w.group(1) and "(18)" in w.group(1) and "form=tb_consent" in w.group(2)
    assert 'data-testid="proxy-w-no_assent"' in page  # 15 is in the default assent ages, 7 to 17
    assert 'data-state="consented"' in page and "Consent given by the participant" in page
    assert f'data-testid="proxy-{no}-no_representative"' in c.get("/studies/GZQO/subjects").text
    assert f'data-testid="proxy-{no}-no_representative"' in c.get("/studies/GZQO/screening-log").text
    for lang, word in (("ja", "代諾者が記録されていません"), ("zh-TW", "未記錄法定代理人")):
        _lang(c, csrf, lang)
        assert word in c.get(f"/studies/GZQO/subjects/{no}").text
    _lang(c, csrf, "en")
    # a representative (a parent) and the assent: no warning; the record names both, and who recorded the assent
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "1",
                                       "ic_assent_date": "2026-10-06"}, reason="the representative signed")  # fmt: skip
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert "proxy-w-" not in page
    assert "Consent given by a representative: parent (parental authority)" in page
    assert "assent obtained on 2026-10-06 (recorded by crc)" in page and "age 15 at consent" in page


def test_in_the_assent_ages_without_assent_warns(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "10", "ic_lar": "1", "ic_lar_rel": "2"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="proxy-w-no_assent"' in page and "proxy-w-no_representative" not in page
    assert "(7 to 17)" in page and "Consent given by a representative: guardian" in page
    # the protocol's ages, per study: assent from 12, majority 20; age 10 is now below the assent ages
    setup = c.get("/studies/GZQO/setup").text
    assert 'data-testid="setup-consent-ages"' in setup and "(the default)" in setup
    r = c.post("/studies/GZQO/setup/consent-ages",
               data={"csrf": _csrf(setup), "majority": "20", "assent_from": "12", "assent_to": "19"})  # fmt: skip
    assert r.status_code == 200 and "Age of majority 20; assent asked from age 12 to 19." in r.text
    assert _orch(lb, "life.consent_ages")[-1]["detail"] == {"old": [18, 7, 17], "new": [20, 12, 19]}
    assert "proxy-w-" not in c.get(f"/studies/GZQO/subjects/{no}").text
    bad = c.post("/studies/GZQO/setup/consent-ages",
                 data={"csrf": _csrf(setup), "majority": "18", "assent_from": "12", "assent_to": "18"})  # fmt: skip
    assert bad.status_code == 400 and "below the age of majority" in bad.text
    # no age on the consent form: the age at enrolment, in whole years, and the record says which
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "", "ic_lar": "1", "ic_lar_rel": "2"},
          reason="age moved to the enrolment form")  # fmt: skip
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-07", "en_eligible": "1", "en_age": "13"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert "age 13 at enrolment (whole years)" in page and 'data-testid="proxy-w-no_assent"' in page


def test_a_declined_assent_is_shown_and_not_taken_as_consent(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: E501, F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "0",
                                       "ic_assent_why": "3"})  # fmt: skip
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert re.search(r'<p class="error" role="alert" data-testid="proxy-w-assent_declined">The participant declined', page)
    assert 'data-state="contacted"' in page  # the consent form did not move the participant on
    assert 'data-testid="consent-missing"' not in page and "assent not obtained: declined" in page
    assert 'data-testid="go-consented-declined"' in page and 'data-testid="go-consented"' not in page
    # an enrolment does not imply it either: the participant is held, and the reason is the declined assent
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-07", "en_eligible": "1"})
    assert 'data-state="contacted"' in c.get(f"/studies/GZQO/subjects/{no}").text
    # the deliberate step: refused without a reason (logged), taken with one, kept in the trail
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "consented", "on_day": "2026-10-06"})
    assert r.status_code == 409 and "give the reason to proceed in the note" in r.text
    assert _orch(lb, "life.refused")[-1]["detail"]["why"] == "assent_reason"
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "consented", "on_day": "2026-10-06",
                                                         "note": "the ethics committee's ruling for this case"})  # fmt: skip
    assert r.status_code == 200 and 'data-state="enrolled"' in r.text  # consented, then the enrolment form stands
    step = [s for s in lb["dc"].db.fetchdicts("SELECT * FROM subject_step WHERE record = ?", (no,))
            if s["new"] == "consented"]  # fmt: skip
    assert step[-1]["source"] == "manual" and step[-1]["note"] == "the ethics committee's ruling for this case"
    manual = [e["detail"] for e in _orch(lb, "life.step") if e["detail"]["record"] == no and e["detail"].get("source")
              == "manual"]  # fmt: skip
    assert manual[-1]["steps"] == [["approached", "consented"]] and manual[-1]["source"] == "manual"
    assert 'data-testid="proxy-w-assent_declined"' in r.text  # still shown, prominently


def test_an_adult_is_unaffected(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "30", "ic_lar": "0"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert "proxy-w-" not in page and 'data-state="consented"' in page
    assert "Consent given by the participant" in page and "assent not recorded" in page


def _xlsx(c: Any) -> list[list[Any]]:
    r = c.get("/studies/GZQO/screening-log.xlsx")
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.content))["screening log"]
    return [list(row) for row in ws.iter_rows(values_only=True)]


def test_the_screening_log_export_has_five_columns_at_the_end(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: E501, F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "9",
                                       "ic_lar_other": "aunt", "ic_assent": "0", "ic_assent_why": "1"})  # fmt: skip
    rows = _xlsx(c)
    assert tuple(rows[0]) == (*LOG_COLUMNS, *screening_log.PROXY_COLUMNS)
    mine = next(r for r in rows[1:] if r[0] == no)
    assert mine[len(LOG_COLUMNS) :] == ["representative", "9", "0", "1", None]
    monkeypatch.setenv(proxy_consent.ENV, "off")
    rows = _xlsx(c)
    assert tuple(rows[0]) == LOG_COLUMNS and all(len(r) == len(LOG_COLUMNS) for r in rows)


def test_with_the_setting_off_nothing_shows(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Off, the forms, pages and exports carry nothing of the card. (The byte-for-byte comparison with master is in
    the pull request: the same pages rendered on master and here.)"""
    c, csrf, no, _ = _ready(lb, monkeypatch, on=False)
    form = c.get(f"/studies/GZQO/entry?record={no}&form=tb_consent").text
    assert "proxy-" not in form and 'data-testid="f-ic_lar_relation"' in form
    assert not any(f'data-testid="q-{n}"' in form for n in proxy_consent.FIELDS)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_lar": "0"})
    pages = [c.get(p).text for p in (f"/studies/GZQO/subjects/{no}", "/studies/GZQO/subjects",
                                     "/studies/GZQO/screening-log", "/studies/GZQO/setup")]  # fmt: skip
    assert not any("proxy-" in p or "consent-ages" in p or ' id="consent-record"' in p for p in pages)
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    one = c.get(f"/api/v1/studies/GZQO/subjects/{no}", headers={"Authorization": f"Bearer {tok}"}).json()
    assert "proxy" not in one["subject"]["consent"]
    assert "proxy" not in _orch(lb, "data.forms")[-1]["detail"]
    assert tuple(_xlsx(c)[0]) == LOG_COLUMNS


def test_each_role_records_and_reads_as_it_does_the_consent_form(lb: dict[str, Any],  # noqa: F811
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """Who can record and read consent today records and reads the new items; no role sees more."""
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "0"})
    seen: dict[str, tuple[Any, ...]] = {}
    for i, role in enumerate(ROLES):
        name = f"r{i}{role[:6]}"
        lb["users"].create(name, role, PW, f"{name}@hospa.test")
        if role == "cro":
            lb["users"].set_scope(name, affiliation="cro", studies="GZQO")
        rc, rcsrf = login(lb["app"], name, PW)
        p = rc.get(f"/studies/GZQO/subjects/{no}")
        reads_consent, reads_new = 'data-testid="consent-record"' in p.text, 'data-testid="proxy-record"' in p.text
        assert reads_consent == reads_new, role  # the record and its new items are read together, or neither
        assert reads_consent == ('data-testid="proxy-w-no_representative"' in p.text), role
        lst = rc.get("/studies/GZQO/subjects").text
        assert (f'data-testid="subject-{no}"' in lst) == (f'data-testid="proxy-{no}-no_representative"' in lst), role
        # recording: the old item and the new ones by the same route, refused or saved alike
        old = _save(rc, rcsrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "0", "ic_copy": "0"},
                    reason=f"{role} old")  # fmt: skip
        new = _save(rc, rcsrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "0", "ic_copy": "0",
                                                  "ic_assent": "1"}, reason=f"{role} new")  # fmt: skip
        stored = lb["dc"].record("GZQO", no).get("ic_assent") == "1"
        assert (old.status_code < 400) == (new.status_code < 400), role
        assert stored == (new.status_code < 400 and old.status_code < 400), role
        if stored:  # put it back for the next role
            _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "0", "ic_assent": ""},
                  reason="reset")  # fmt: skip
        # the study's ages: exactly who may change the contact rule
        setup = rc.get("/studies/GZQO/setup")
        token = _csrf(setup.text) if 'name="csrf"' in setup.text else rcsrf
        a = rc.post("/studies/GZQO/setup/contact", data={"csrf": token, "max_attempts": "3", "min_days": "1"})
        b = rc.post("/studies/GZQO/setup/consent-ages",
                    data={"csrf": token, "majority": "18", "assent_from": "7", "assent_to": "17"})  # fmt: skip
        assert (a.status_code < 400) == (b.status_code < 400), role
        assert ('data-testid="setup-contact-save"' in setup.text) == (
            'data-testid="setup-consent-ages-save"' in setup.text), role  # fmt: skip
        seen[role] = (p.status_code, reads_consent, old.status_code < 400, b.status_code < 400)
    assert seen["coordinator"] == (200, True, True, True)  # the one who records consent today records these
    assert seen["cro"][1] is False  # an aggregate-only account reads no participant's record, so none of these


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_the_form_and_the_record_fit_a_phone(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                                             tmp_path: Path) -> None:  # fmt: skip
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "0",
                                       "ic_assent_why": "3"})  # fmt: skip
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    for lang in ("en", "ja", "zh-TW"):
        _lang(c, csrf, lang)
        for name, path in (("form", f"/studies/GZQO/entry?record={no}&form=tb_consent"),
                           ("record", f"/studies/GZQO/subjects/{no}"), ("setup", "/studies/GZQO/setup")):  # fmt: skip
            text = c.get(path).text
            assert "proxy" in text or "consent-ages" in text
            f = f"proxy-{name}-{lang}.html"
            (out / f).write_text(text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
            pages.append({"file": f, "lang": lang, "width": PHONE[0], "height": PHONE[1], "checks": []})
    (out / "console.css").write_text(c.get("/static/console.css").text, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages, "shots": ""})],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("results"), r.stderr[-2000:])
