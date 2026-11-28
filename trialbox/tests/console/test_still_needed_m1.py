"""M1 (U5-5, D-1280): the page "Information still needed": every open item in three languages with its step, its state
and a field; the table of the install's questions; a filled item goes through the host's runner and leaves the list;
the administrator only; no setting name on the page, no value in the audit."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from console.app import create_app
from console.auth import UserStore
from console.i18n_stillneeded import EN, JA, ZH
from fastapi.testclient import TestClient
from tb_common import install_questions, site_needs
from tb_common.audit import AuditLog

from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, FakeBackend, login
from tests.unit.test_install_m1 import GIVEN, TYPED, _build, _hw, _prompt
from tools import settings_wizard
from tools.box import __main__ as box
from tools.box import ask
from tools.box import plan as bp

PATH = "/admin/still-needed"
PW = "operations-password-0001"
CATALOGUE = {"en": EN, "ja": JA, "zh-TW": ZH}


@pytest.fixture
def sn(tmp_path: Path) -> dict[str, Any]:
    deploy = tmp_path / "deploy"
    a, _ = box.owner_answers({**ask.four(_hw(), _prompt(TYPED), env={}), "environment": "VALIDATION"}, ())
    settings, env, _ = _build(bp.plan(a, _hw()), deploy)
    settings_wizard.write(settings, env, deploy / "settings.yaml", deploy / ".env")
    box.keep_answers(deploy, a)
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore()
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    users.create("coord", "coordinator", PW, "coord@hospa.test")
    app = create_app(
        {**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "console"), "TB_OPS_DIR": str(tmp_path / "ops"),
         "TB_OPS_RUNNER": "inline", "TB_OPS_DEPLOY": str(deploy)},
        backend=backend, audit=AuditLog(backend.audit_dir), users=users,
    )  # fmt: skip
    return {"app": app, "deploy": deploy, "audit": backend.audit_dir, "ops": tmp_path / "ops"}


def _items(html: str) -> dict[str, str]:
    return dict(re.findall(r'<article data-testid="sn-(\w+)" data-state="(\w+)"', html))


def _lang(c: TestClient, csrf: str, lang: str) -> None:
    c.post("/lang", data={"lang": lang, "csrf": csrf, "back": "/"}, follow_redirects=False)


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_every_open_item_is_listed_in_the_readers_language(sn: dict[str, Any], lang: str) -> None:
    c, csrf = login(sn["app"], "admin", ADMIN_PW)
    _lang(c, csrf, lang)
    html = c.get(PATH).text
    got = _items(html)
    assert set(got) == set(site_needs.BY_KEY), got  # four answers: every item is open
    assert got["mail_relay"] == "missing" and got["office_mailbox"] == "stand_in"
    for key in got:
        assert site_needs.BY_KEY[key].title[lang] in html.replace("&#39;", "'"), key
    assert CATALOGUE[lang]["stillneeded.intro"] in html and CATALOGUE[lang]["stillneeded.mail.off"] in html
    rows = re.findall(r'<tr data-testid="q-(\w+)" data-group="(\w+)"', html)
    assert rows == [(r["key"], r["group"]) for r in install_questions.table(lang)]
    assert not re.search(r"\bTB_[A-Z]|SMTP_HOST|IMAP_HOST|stillneeded\.", html)  # no setting name, no untranslated key


def test_the_three_catalogues_hold_the_same_keys_and_no_empty_text() -> None:
    assert set(EN) == set(JA) == set(ZH)
    assert all(v.strip() for cat in (EN, JA, ZH) for v in cat.values())
    assert not [k for k in EN if EN[k] == JA[k] or EN[k] == ZH[k]]


@pytest.mark.parametrize("item", ["site_name", "mail_relay", "office_mailbox"])
def test_filling_an_item_removes_it_and_lifts_its_gate(sn: dict[str, Any], item: str) -> None:
    c, csrf = login(sn["app"], "admin", ADMIN_PW)
    given = {"item": item, **GIVEN[item]}
    r = c.post(f"{PATH}/{item}", data={**given, "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"{PATH}?sent={item}"
    assert item not in _items(c.get(PATH).text)
    stand = site_needs.read_stand_ins(sn["deploy"])[0]
    assert item not in stand
    lines = [json.loads(x) for f in sn["audit"].glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
    done = [e for e in lines if e.get("event") == "console.site_needs"]
    assert done and all(v not in json.dumps(done, ensure_ascii=False) for v in GIVEN[item].values() if len(v) > 3)


def test_a_chart_number_typed_as_an_example_is_written_nowhere(sn: dict[str, Any]) -> None:
    c, csrf = login(sn["app"], "admin", ADMIN_PW)
    r = c.post(f"{PATH}/chart_number", data={"chartno_example": "00123456", "csrf": csrf}, follow_redirects=False)
    html = c.get(PATH).text
    assert r.status_code == 303 and "sn-failed-chart_number" in html  # no database to ask here: the host refuses
    files = [f for d in (sn["ops"], sn["audit"], sn["deploy"]) for f in d.rglob("*") if f.is_file()]
    assert "00123456" not in html and not any(b"00123456" in f.read_bytes() for f in files)


def test_an_answer_that_cannot_be_used_comes_back_with_the_reason(sn: dict[str, Any]) -> None:
    c, csrf = login(sn["app"], "admin", ADMIN_PW)
    r = c.post(f"{PATH}/office_mailbox", data={"sae_office_mailbox": "not an address", "csrf": csrf})
    assert r.status_code == 400 and 'id="sn-office_mailbox-sae_office_mailbox-err"' in r.text
    assert 'data-testid="sn-errors"' in r.text and 'href="#sn-office_mailbox-sae_office_mailbox"' in r.text
    assert EN["stillneeded.err.mail"] in r.text and 'value="not an address"' in r.text
    assert not list((sn["ops"] / "requests").glob("*.json")) if (sn["ops"] / "requests").is_dir() else True
    r = c.post(f"{PATH}/data_source", data={"source_kind": "csv", "source_dir": "/srv/not-there", "csrf": csrf})
    html = c.get(PATH).text
    assert 'data-testid="sn-failed-data_source"' in html and _items(html)["data_source"] == "stand_in"


def test_the_proposals_are_shown_and_never_applied_by_themselves(sn: dict[str, Any]) -> None:
    sn["ops"].mkdir(exist_ok=True)
    (sn["ops"] / "needs-proposals.json").write_text('{"smtp_host": "mail.hospa.test", "smtp_port": "25"}')
    c, _ = login(sn["app"], "admin", ADMIN_PW)
    html = c.get(PATH).text
    assert 'data-testid="sn-found-mail_relay"' in html and 'value="mail.hospa.test"' in html
    assert _items(html)["mail_relay"] == "missing"
    (sn["ops"] / "needs-proposals.json").write_text("not json")
    assert c.get(PATH).status_code == 200


def test_only_the_administrator_and_only_with_the_forms_token(sn: dict[str, Any]) -> None:
    c, csrf = login(sn["app"], "coord", PW)
    assert c.get(PATH).status_code == 403
    assert c.post(f"{PATH}/site_name", data={"site_name": "x", "csrf": csrf}).status_code == 403
    c, csrf = login(sn["app"], "admin", ADMIN_PW)
    assert c.post(f"{PATH}/site_name", data={"site_name": "x", "csrf": "no"}).status_code == 400
    assert c.post(f"{PATH}/backup_key", data={"csrf": csrf}).status_code == 404
    assert "site_name" in _items(c.get(PATH).text)
    assert 'data-testid="still-needed-link"' in c.get("/admin/ops").text
