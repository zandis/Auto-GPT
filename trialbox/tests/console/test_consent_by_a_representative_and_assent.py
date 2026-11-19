"""10C-19 (JP-20, D-1232): consent by a representative (代諾者) and the participant's assent (アセント) on the consent
record, on the console over the orchestrator's real data-core and lifecycle API. All data is synthetic.

With the setting on (``TB_CONSENT_PROXY=on``, which the box's plan writes for a Japanese site; unset is off): a minor whose consent names no representative
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
from datetime import timedelta
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
    out: list[dict[str, Any]] = []
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


def test_the_setting_follows_the_sites_country_not_its_zone() -> None:
    from tb_common import box_answers as ba
    from tb_common import site_country

    from tests.unit.test_box_plan import _hw
    from tools.box import plan as bp

    # never inferred from the zone: an installed Japanese box keeps today's behaviour until someone sets it
    assert proxy_consent.is_on({"TB_TZ": "Asia/Tokyo"}) is False
    assert proxy_consent.is_on({"TB_TZ": "Asia/Taipei", proxy_consent.ENV: "on"}) is True
    assert proxy_consent.is_on({proxy_consent.ENV: "off"}) is False
    # the Japan profile is the country's data (10K-1); the box's plan writes the setting for Japan only
    assert [c for c in site_country.COUNTRIES if site_country.defaults(c).consent_proxy] == ["jp"]
    raw = {
        "site_name": "Hospital A",
        "language": "ja",
        "box_name": "box1",
        "backup": {"kind": "later"},
        "owner": {"full_name": "Owner", "username": "owner", "email": "owner@hospa.test"},
        "source": "later",
    }
    jp, problems = ba.parse({**raw, "country": "jp", "tz": "Asia/Tokyo"})
    assert problems == [] and jp is not None and bp.plan(jp, _hw()).env_extra[proxy_consent.ENV] == "on"
    for extra in ({"country": "tw", "tz": "Asia/Taipei"}, {"tz": "Asia/Tokyo"}):  # Taiwan; no country at all
        a, problems = ba.parse({**raw, **extra})
        assert problems == [] and a is not None and proxy_consent.ENV not in bp.plan(a, _hw()).env_extra
    # off, the built-in forms are the forms before the card; on, the five items are added and the earlier free-text
    # relation stays (read only, never required); no free text is added
    off = [f.name for f in builtin.fields()]
    on = {f.name: f for f in builtin.fields(proxy=True)}
    assert not set(proxy_consent.FIELDS) & set(off) and "ic_lar_relation" in off
    assert set(proxy_consent.FIELDS) <= set(on) and not on["ic_lar_relation"].required
    assert all(on[n].kind != "text" for n in proxy_consent.FIELDS if n != "ic_age")  # codes and a date only
    assert on["ic_age"].kind == "integer"


def test_a_minor_without_a_representative_warns(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    form = c.get(f"/studies/GZQO/entry?record={no}&form=tb_consent").text
    assert 'data-testid="proxy-form-note"' in form and "Never a name, address or contact" in form
    assert 'data-testid="f-ic_lar_rel-1"' in form and "ic_lar_other" not in form
    assert re.search(r'id="f_ic_lar_relation"[^>]* disabled', form)  # the earlier free text: shown, never entered
    assert "TrialBox holds no date of birth" in form
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "15", "ic_lar": "0"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    w = re.search(
        r'<p class="warn" role="alert" data-testid="proxy-w-no_representative">([^<]+)<a href="([^"]+)"', page
    )
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
    # the /api/v1 twin: the same rule, the same right
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    api = c.post("/api/v1/studies/GZQO/setup/consent-ages", json={"majority": 18, "assent_from": 12, "assent_to": 17},
                 headers={"Authorization": f"Bearer {tok}"})  # fmt: skip
    assert api.status_code == 200 and api.json()["assent_from"] == 12
    lb["users"].create("viewer2", "viewer", PW, "viewer2@hospa.test")
    vtok = c.post("/api/v1/session", json={"username": "viewer2", "password": PW}).json()["token"]
    no_right = c.post("/api/v1/studies/GZQO/setup/consent-ages", json={"majority": 18, "assent_from": 7,
                      "assent_to": 17}, headers={"Authorization": f"Bearer {vtok}"})  # fmt: skip
    assert no_right.status_code == 403
    c.post("/studies/GZQO/setup/consent-ages",
           data={"csrf": _csrf(setup), "majority": "20", "assent_from": "12", "assent_to": "19"})  # fmt: skip
    bad = c.post("/studies/GZQO/setup/consent-ages",
                 data={"csrf": _csrf(setup), "majority": "18", "assent_from": "12", "assent_to": "18"})  # fmt: skip
    assert bad.status_code == 400 and "below the age of majority" in bad.text
    # no age at consent: a warning, never a guess from a later age (the enrolment age is never read)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "", "ic_lar": "1", "ic_lar_rel": "2"},
          reason="age not on the signed form")  # fmt: skip
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-07", "en_eligible": "1", "en_age": "18"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="proxy-w-no_age"' in page and "age at consent not recorded" in page
    assert "proxy-w-no_assent" not in page and "proxy-w-no_representative" not in page


@pytest.mark.parametrize(("majority", "lo", "hi"), [("30", "0", "29"), ("1", "0", "0"), ("18", "12", "18"),
                                                     ("18", "-1", "10"), ("15", "7", "14"), ("22", "7", "17")])  # fmt: skip
def test_the_ages_are_bounded(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                              majority: str, lo: str, hi: str) -> None:  # fmt: skip
    c, _, _, _ = _ready(lb, monkeypatch)
    setup = c.get("/studies/GZQO/setup").text
    r = c.post("/studies/GZQO/setup/consent-ages",
               data={"csrf": _csrf(setup), "majority": majority, "assent_from": lo, "assent_to": hi})  # fmt: skip
    assert r.status_code == 400 and not _orch(lb, "life.consent_ages")


def test_the_ages_are_whole_numbers_and_not_saved_while_off(lb: dict[str, Any],  # noqa: F811
                                                             monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, csrf, _, _ = _ready(lb, monkeypatch)
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    for body in ({"majority": "18", "assent_from": 7, "assent_to": 17}, {"majority": 18.5, "assent_from": 7,
                                                                         "assent_to": 17}):  # fmt: skip
        assert c.post("/api/v1/studies/GZQO/setup/consent-ages", json=body, headers=auth).status_code == 422
    # the orchestrator itself takes no text for a number either
    r = lb["oc"].put("/studies/GZQO/consent-ages", json={"majority": "18", "assent_from": 7, "assent_to": 17})
    assert r.status_code == 422
    monkeypatch.setenv(proxy_consent.ENV, "off")
    setup = c.get("/studies/GZQO/setup").text
    assert "consent-ages" not in setup
    r = c.post("/studies/GZQO/setup/consent-ages",
               data={"csrf": csrf, "majority": "18", "assent_from": "7", "assent_to": "17"})  # fmt: skip
    assert r.status_code == 409
    ok = {"majority": 18, "assent_from": 7, "assent_to": 17}
    assert c.post("/api/v1/studies/GZQO/setup/consent-ages", json=ok, headers=auth).status_code == 409
    assert lb["oc"].put("/studies/GZQO/consent-ages", json=ok).status_code == 409
    assert not _orch(lb, "life.consent_ages")


def test_the_ages_are_refused_without_the_right_or_the_page_token(lb: dict[str, Any],  # noqa: F811
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, _, _, _ = _ready(lb, monkeypatch)
    ok = {"majority": "18", "assent_from": "7", "assent_to": "17"}
    assert c.post("/studies/GZQO/setup/consent-ages", data={"csrf": "not-the-token", **ok}).status_code == 400
    lb["users"].create("viewer3", "viewer", PW, "viewer3@hospa.test")
    v, vcsrf = login(lb["app"], "viewer3", PW)
    path = "/studies/GZQO/setup/consent-ages"
    assert v.post(path, data={"csrf": vcsrf, **ok}).status_code == 403
    tok = c.post("/api/v1/session", json={"username": "viewer3", "password": PW}).json()["token"]
    r = c.post("/api/v1" + path, json={"majority": 18, "assent_from": 7, "assent_to": 17},
               headers={"Authorization": f"Bearer {tok}"})  # fmt: skip
    assert r.status_code == 403
    denied = [e["detail"]["action"] for e in _events(lb, "console.denied") if "consent-ages" in e["detail"]["action"]]
    assert denied == [path, "/api/v1" + path]  # the console refuses, and says so, before the orchestrator is asked
    assert not _orch(lb, "life.consent_ages")


def test_a_declined_assent_is_shown_and_not_taken_as_consent(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "0",
                                       "ic_assent_why": "3"})  # fmt: skip
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert re.search(
        r'<p class="error" role="alert" data-testid="proxy-w-assent_declined">The participant declined', page
    )
    assert 'data-state="contacted"' in page  # the consent form did not move the participant on
    assert 'data-testid="consent-missing"' not in page and "assent not obtained: declined" in page
    assert 'data-testid="go-consented-declined"' in page and 'data-testid="go-consented"' not in page
    assert 'data-testid="step-note-required"' in page and "Note (required, at least 10 characters" in page
    # an enrolment does not imply it either: the participant is held, and the reason is the declined assent
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-07", "en_eligible": "1"})
    assert 'data-state="contacted"' in c.get(f"/studies/GZQO/subjects/{no}").text
    # the deliberate step: refused without a reason (logged), taken with one, kept in the trail
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "consented", "on_day": "2026-10-06"})
    assert r.status_code == 409 and "choose why you go on" in r.text
    assert _orch(lb, "life.refused")[-1]["detail"]["why"] == "assent_reason"
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "consented", "on_day": "2026-10-06",
                                                         "proceed": "committee",
                                                         "note": "the ethics committee's ruling for this case"})  # fmt: skip
    assert r.status_code == 200 and 'data-state="enrolled"' in r.text  # consented, then the enrolment form stands
    step = [s for s in lb["dc"].db.fetchdicts("SELECT * FROM subject_step WHERE record = ?", (no,))
            if s["new"] == "consented"]  # fmt: skip
    assert step[-1]["source"] == "manual" and step[-1]["note"] == "the ethics committee's ruling for this case"
    assert step[-1]["reason"] == "committee"
    went = [e["detail"] for e in _orch(lb, "life.assent_proceed")]  # its own audit event, without the note
    assert went == [{"record": no, "to": "consented", "reason": "committee"}]
    assert 'data-testid="proxy-w-assent_declined"' in r.text  # still shown, prominently


def _later(lb: dict[str, Any], minutes: int = 5) -> None:  # noqa: F811
    lb["clock"]["now"] = lb["clock"]["now"] + timedelta(minutes=minutes)


def _state(c: Any, no: str) -> str:
    m = re.search(r'data-state="([a-z_]+)" data-testid="life-state"', c.get(f"/studies/GZQO/subjects/{no}").text)
    assert m
    return m.group(1)


def test_a_declined_assent_saved_after_the_consent_holds_every_later_step(lb: dict[str, Any],  # noqa: F811
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The order of the saves does not matter: consent first (the participant is consented), the assent declined in a
    later save, then an enrolment form: the participant stays consented until a person goes on with a reason."""
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1"})
    assert _state(c, no) == "consented"
    _later(lb)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "0",
                                       "ic_assent_why": "3"}, reason="the child said no")  # fmt: skip
    _later(lb)
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-07", "en_eligible": "1"})
    assert _state(c, no) == "consented"  # held: the enrolment form does not move the participant on
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="proxy-w-assent_declined"' in page and 'data-testid="step-note-required"' in page
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "enrolled", "on_day": "2026-10-07"})
    assert r.status_code == 409 and _orch(lb, "life.refused")[-1]["detail"]["why"] == "assent_reason"
    _later(lb)
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "enrolled", "on_day": "2026-10-07",
                                                         "proceed": "committee",
                                                         "note": "the committee's ruling, recorded on paper"})  # fmt: skip
    assert r.status_code == 200 and _state(c, no) == "enrolled"
    assert "step-note-required" not in c.get(f"/studies/GZQO/subjects/{no}").text  # a person went on: no hold


def test_a_re_consent_that_declines_holds_and_one_that_assents_frees(lb: dict[str, Any],  # noqa: F811
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, csrf, no, other = _ready(lb, monkeypatch)
    # a re-consent (rc1) whose assent is declined: the consent in force declines; the enrolment is held
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "1",
                                       "ic_assent_date": "2026-10-06"})  # fmt: skip
    _later(lb)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-10-07", "ic_version": "v2", "ic_copy": "1", "ic_age": "12",
                                       "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "0", "ic_assent_why": "3"}, "rc1")  # fmt: skip
    _later(lb)
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-08", "en_eligible": "1"})
    assert _state(c, no) == "consented"
    # no dead end: declined at the first consent, then a re-consent with the assent obtained moves the person on
    _save(c, csrf, other, "tb_consent", {**CONSENT, "ic_age": "9", "ic_lar": "1", "ic_lar_rel": "1",
                                          "ic_assent": "0", "ic_assent_why": "3"})  # fmt: skip
    assert _state(c, other) == "contacted"
    _later(lb)
    _save(c, csrf, other, "tb_consent", {"ic_date": "2026-10-09", "ic_version": "v2", "ic_copy": "1", "ic_age": "9",
                                          "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "1",
                                          "ic_assent_date": "2026-10-09"}, "rc1")  # fmt: skip
    assert _state(c, other) == "consented"
    page = c.get(f"/studies/GZQO/subjects/{other}").text
    assert "proxy-w-assent_declined" not in page and "go-consented-declined" not in page


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


def test_the_screening_log_export_has_five_columns_at_the_end(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "9",
                                       "ic_assent": "0", "ic_assent_why": "1"})  # fmt: skip
    rows = _xlsx(c)
    assert tuple(rows[0]) == (*LOG_COLUMNS, *screening_log.PROXY_COLUMNS)
    mine = next(r for r in rows[1:] if r[0] == no)
    assert mine[len(LOG_COLUMNS) :] == ["representative", "9", "0", "1", None]
    # the data-core exports: the five items after every other column; the earlier free-text relation is still there
    head = c.get("/studies/GZQO/export.csv").text.splitlines()[0].split(",")
    assert head[-len(proxy_consent.FIELDS) :] == list(proxy_consent.FIELDS) and "ic_lar_relation" in head
    odm = c.get("/studies/GZQO/export.odm").text
    assert 'ItemOID="ic_lar_relation"' in odm and 'ItemOID="ic_assent_date"' in odm
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


def test_every_refusal_of_the_ages_has_japanese_and_chinese_words() -> None:
    from console.refusals import UNTRANSLATED, localize_reason

    reasons = {proxy_consent.check_rule(*a) for a in ((30, 0, 29), ("18", 7, 17), (18, 12, 18))}
    reasons.add("consent by a representative is not recorded on this box")
    assert None not in reasons and len(reasons) == 4
    for r in reasons:
        for lang in ("ja", "zh-TW"):
            assert localize_reason(str(r), lang) not in ("", UNTRANSLATED[lang]), (r, lang)


DECLINE = {"ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "0", "ic_assent_why": "3"}
GO_ON = {"proceed": "investigator", "note": "the investigator's documented judgement"}


def _step(c: Any, csrf: str, no: str, to: str, **extra: str) -> Any:
    return c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": to, "on_day": "2026-10-10", **extra})


def test_a_later_re_consent_with_no_assent_entry_does_not_lift_the_hold(lb: dict[str, Any],  # noqa: F811
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    _later(lb)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-10-09", "ic_version": "v2", "ic_copy": "1", "ic_age": "12",
                                       "ic_lar": "1", "ic_lar_rel": "1"}, "rc1")  # fmt: skip
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    assert _state(c, no) == "contacted"
    assert not _orch(lb, "life.assent_proceed")


@pytest.mark.parametrize("now", ["1", ""])
def test_correcting_a_declined_answer_does_not_lift_the_hold(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                                                             now: str) -> None:  # fmt: skip
    """The simpler choice (D-1232): a correction is kept with its reason as every change is, and the hold stays until
    the reasoned step."""
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    _later(lb)
    fixed = {**CONSENT, **DECLINE, "ic_assent_why": now} if now else {**CONSENT, **DECLINE, "ic_assent": ""}
    if not now:
        fixed.pop("ic_assent_why")
    _save(c, csrf, no, "tb_consent", fixed, reason="typed the wrong reason")
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    assert _state(c, no) == "contacted"
    assert _step(c, csrf, no, "consented", **GO_ON).status_code == 200


def test_a_back_dated_consent_that_declines_holds(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1"})  # no assent entry
    assert _state(c, no) == "consented"
    _later(lb)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-10-05", "ic_version": "v1", "ic_copy": "1", **DECLINE}, "rc1")
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    assert _state(c, no) == "consented"


def test_switching_the_setting_off_does_not_release_a_recorded_decline(lb: dict[str, Any],  # noqa: F811
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    monkeypatch.setenv(proxy_consent.ENV, "off")
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    assert _state(c, no) == "contacted"
    assert _step(c, csrf, no, "consented").status_code == 409
    assert _step(c, csrf, no, "consented", **GO_ON).status_code == 200


def test_undoing_the_reasoned_step_restores_the_hold(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    _later(lb)
    assert _step(c, csrf, no, "consented", **GO_ON).status_code == 200
    assert _state(c, no) == "consented"
    _later(lb)
    r = c.post(f"/studies/GZQO/subjects/{no}/undo", data={"csrf": csrf, "note": "recorded by mistake"})
    assert r.status_code == 200 and _state(c, no) == "contacted"
    c.get("/studies/GZQO/subjects")  # a refresh derives again: the consent form does not put it back
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    assert _state(c, no) == "contacted"


def test_a_corrected_consent_date_after_the_reasoned_step_keeps_the_decision(lb: dict[str, Any],  # noqa: F811
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The hold is judged by when the decline was recorded, not by the consent's date: a later date correction
    never turns it back on."""
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    _later(lb)
    assert _step(c, csrf, no, "consented", **GO_ON).status_code == 200
    _later(lb)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE, "ic_date": "2026-10-04"}, reason="the signed date")
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-10-10", "en_eligible": "1"})
    assert _state(c, no) == "enrolled"


def test_the_reasoned_step_needs_a_code_and_a_real_note(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    assert _step(c, csrf, no, "consented", note="a long enough note, but no code").status_code == 409
    assert _step(c, csrf, no, "consented", proceed="not-a-code", note="a long enough note").status_code == 409
    r = _step(c, csrf, no, "consented", proceed="other", note=".")
    assert r.status_code == 409 and "at least 10 characters" in r.text
    assert [e["detail"]["why"] for e in _orch(lb, "life.refused")][-3:] == ["assent_reason", "assent_reason",
                                                                             "assent_note"]  # fmt: skip
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="step-proceed"' in page and 'minlength="10" required' in page
    assert _state(c, no) == "contacted" and not _orch(lb, "life.assent_proceed")


def test_the_earlier_free_text_relation_takes_no_new_value_on_any_route(lb: dict[str, Any],  # noqa: F811
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """With the setting on, no route writes ``ic_lar_relation``: the orchestrator's form save, its data entry, a
    sheet import, and the console on a study whose built-in forms were added before the setting was on."""
    monkeypatch.setenv(proxy_consent.ENV, "off")
    no, _ = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})  # the forms as before the card
    c.get("/studies/GZQO/subjects")
    monkeypatch.setenv(proxy_consent.ENV, "on")
    name = "Hanako Example, the aunt"  # synthetic: a name where only a relation code may go
    form = c.get(f"/studies/GZQO/entry?record={no}&form=tb_consent").text
    assert re.search(r'id="f_ic_lar_relation"[^>]* disabled', form)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_lar": "1", "ic_lar_relation": name})
    oc = lb["oc"]
    r1 = oc.post(f"/studies/GZQO/entry/{no}", json={"form": "tb_consent", "values": {**CONSENT, "ic_lar": "1",
                                                                                     "ic_lar_relation": name}})  # fmt: skip
    r2 = oc.put(f"/studies/GZQO/data/{no}", json={"values": {"ic_lar_relation": name}})
    r3 = oc.post("/studies/GZQO/import/sheet", json={"csv": f"record_id,rel\n{no},{name}\n",
                                                     "columns": {"record_id": "record_id", "rel": "ic_lar_relation"}})  # fmt: skip
    assert (r1.status_code, r2.status_code, r3.status_code) == (409, 409, 409)
    assert "ic_lar_relation" not in lb["dc"].record("GZQO", no)
    assert name not in c.get("/studies/GZQO/export.csv").text


# ---------------------------------------------------------------------------------------------- the third review (a-g)
def _put(lb: dict[str, Any], no: str, event: str, values: dict[str, str]) -> Any:  # noqa: F811
    return lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": event, "values": values, "reason": "probe"})


def test_a_correcting_an_older_consents_date_past_the_decline_does_not_lift(lb: dict[str, Any],  # noqa: F811
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_date": "2026-11-03", "ic_age": "12", "ic_lar": "1",
                                       "ic_lar_rel": "1", "ic_assent": "1", "ic_assent_date": "2026-11-03"})  # fmt: skip
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-05", "ic_version": "v2", "ic_copy": "1", **DECLINE}, "rc1")
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-08", "en_eligible": "1"})
    before = _state(c, no)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_date": "2026-11-07", "ic_age": "12", "ic_lar": "1",
                                       "ic_lar_rel": "1", "ic_assent": "1", "ic_assent_date": "2026-11-07"},
          reason="the signed date")  # fmt: skip
    assert _state(c, no) == before == "consented"  # held where it stood; the correction moved nothing
    assert not _orch(lb, "life.assent_proceed")


def test_b_correcting_the_declining_consents_own_date_does_not_lift(lb: dict[str, Any],  # noqa: F811
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    c, csrf, no, other = _ready(lb, monkeypatch)
    for rec in (no, other):
        _save(c, csrf, rec, "tb_consent", {**CONSENT, "ic_date": "2026-11-03", "ic_age": "12", "ic_lar": "1",
                                            "ic_lar_rel": "1", "ic_assent": "1", "ic_assent_date": "2026-11-03"})  # fmt: skip
        _save(c, csrf, rec, "tb_consent", {"ic_date": "2026-11-05", "ic_version": "v2", "ic_copy": "1", **DECLINE},
              "rc1")  # fmt: skip
        _save(c, csrf, rec, "tb_enrolment", {"en_date": "2026-11-08", "en_eligible": "1"})
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-01", "ic_version": "v2", "ic_copy": "1", **DECLINE}, "rc1",
          reason="the signed date")  # fmt: skip
    assert _put(lb, other, "rc1", {"ic_date": "2026-11-01"}).status_code == 200
    c.get("/studies/GZQO/subjects")
    assert _state(c, no) == _state(c, other) == "consented"


def test_c_a_visit_event_is_never_a_consent(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-08", "en_eligible": "1"})
    r = _put(lb, no, "v1", {"ic_date": "2026-11-07", "ic_assent": "1"})
    assert r.status_code == 200, r.text
    c.get("/studies/GZQO/subjects")
    assert _state(c, no) == "contacted"


def test_d_an_undated_decline_holds(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, "ic_age": "12", "ic_lar": "1", "ic_lar_rel": "1", "ic_assent": "1",
                                       "ic_assent_date": "2026-10-06"})  # fmt: skip
    assert _state(c, no) == "consented"
    assert _put(lb, no, "rc1", {"ic_assent": "0", "ic_assent_why": "3"}).status_code == 200  # no ic_date at all
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-08", "en_eligible": "1"})
    c.get("/studies/GZQO/subjects")
    assert _state(c, no) == "consented"


ZERO_WIDTH = "\u200b" * 12


def test_e_a_note_of_invisible_characters_is_no_note(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from tb_common.visible_text import visible

    assert visible(ZERO_WIDTH) == "" and visible("ㅤ" * 12 + " ﻿") == ""
    assert visible("the committee's ruling") == "the committee's ruling"  # a real note is unchanged
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    assert _step(c, csrf, no, "consented", proceed="committee", note=ZERO_WIDTH).status_code == 409
    r = lb["oc"].post(f"/studies/GZQO/subjects/{no}/step", json={"to": "consented", "reason": "committee",
                                                                  "note": ZERO_WIDTH})  # fmt: skip
    assert r.status_code == 409 and r.json()["detail"]["why"] == "assent_note"
    assert _state(c, no) == "contacted"


def test_f_a_new_decline_after_the_reasoned_step_holds_again(lb: dict[str, Any],  # noqa: F811
                                                             monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The order is the store's, not the clock's: here everything happens in the same second."""
    c, csrf, no, _ = _ready(lb, monkeypatch)
    _save(c, csrf, no, "tb_consent", {**CONSENT, **DECLINE})
    assert _step(c, csrf, no, "consented", **GO_ON).status_code == 200
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-10-07", "ic_version": "v2", "ic_copy": "1", **DECLINE}, "rc1")
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-08", "en_eligible": "1"})
    assert _state(c, no) == "consented"
    assert _step(c, csrf, no, "enrolled").status_code == 409


def test_g_no_source_writes_the_earlier_relation(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from datacore import sync
    from datacore.store import DataError

    c, _, no, _ = _ready(lb, monkeypatch)
    dc, name = lb["dc"], "Hanako Example, the aunt"  # synthetic
    r = lb["oc"].put("/studies/GZQO/sources/redcap", json={"token_ref": "main", "field_map": {
        "rel": "ic_lar_relation"}, "owned": ["ic_lar_relation"]})  # fmt: skip
    assert r.status_code == 409 and r.json()["detail"]["fields"] == ["ic_lar_relation"]

    class Old:  # a mapping made while the setting was off
        name = "redcap"

        def fields(self) -> list[str]:
            return ["ic_lar_relation", "ic_version"]

        def pull(self) -> list[sync.Row]:
            return [sync.Row(no, "", {"ic_lar_relation": name, "ic_version": "v1"})]

        def push(self, rows: list[sync.Row]) -> dict[str, str]:
            return {}

    sync.sync(dc, "GZQO", Old(), "redcap", "2026-11-08T00:00:00+00:00", push=False)
    cid = dc.add_conflict("GZQO", no, "", "ic_lar_relation", "redcap", "redcap", None, name, "2026-11-08T00:00:00Z")
    with pytest.raises(DataError) as e:
        sync.resolve(dc, int(cid or 0), "theirs", "crc", "2026-11-08T00:00:01+00:00")
    assert e.value.code == "DATA-READONLY" and dc.conflict(int(cid or 0))["resolved"] is None
    with pytest.raises(DataError):  # the last door, whatever path calls it
        dc.write("GZQO", no, "", "ic_lar_relation", name, "x", "2026-11-08T00:00:02+00:00", "trialbox")
    assert "ic_lar_relation" not in dc.record("GZQO", no)
    assert name not in c.get("/studies/GZQO/export.csv").text
