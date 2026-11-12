"""DEMO-JA: what a Japanese viewer saw in English or saw wrong in the demo rehearsal of 2026-11-12. The account page
after TOTP enrolment, the pre-screen log's REDCap note, the data operations trail's event and author, the
feasibility population, the reference data sources and the IRB sentence's English original. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from console import i18n_demoja
from console.app import population_words
from console.screening_log import prescreen_rows
from fastapi.testclient import TestClient
from tb_common.wording import check

from tests.console.test_console_app import PILOT_ENV, VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_dataops_page import _night
from tests.console.test_identity import Clock, _app, _code, _code_page, _password
from tests.console.test_role_pages import PW, _user


def test_the_catalogue_has_every_key_in_every_language_and_no_forbidden_word() -> None:
    assert set(i18n_demoja.EN) == set(i18n_demoja.JA) == set(i18n_demoja.ZH)
    for lang, cat in (("en", i18n_demoja.EN), ("ja", i18n_demoja.JA), ("zh-TW", i18n_demoja.ZH)):
        for key, text in cat.items():
            assert text and not check(text), (lang, key)


def test_every_reference_source_has_a_name_in_each_language() -> None:
    from tools.refdata_fetch import SOURCES

    for s in SOURCES:
        assert i18n_demoja.EN[f"refdata.src.{s.id}"] == s.name  # the English name is the pack's own
        assert f"refdata.src.{s.id}" in i18n_demoja.JA and f"refdata.src.{s.id}" in i18n_demoja.ZH


def _totp_viewer(tmp_path: Path) -> TestClient:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, **PILOT_ENV, TB_CONSOLE_WORKSPACE="on", TB_CONSOLE_MFA="totp")
    c = TestClient(app, base_url="https://testserver")
    enrol = users.issue_enrol_code("viewer")
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    key, mfa = _code_page(c)
    assert key
    from console import totp

    assert _code(c, totp.totp(key, clock.unix()), mfa, enrol).status_code == 303
    return c


def test_after_totp_enrolment_the_account_page_says_two_step_sign_in_is_on(tmp_path: Path) -> None:
    import re

    c = _totp_viewer(tmp_path)
    page = c.get("/account").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)
    assert csrf
    c.post("/lang", data={"csrf": csrf.group(1), "lang": "ja", "back": "/account"})
    page = c.get("/account").text
    assert i18n_demoja.JA["account.totp_on"] in page
    assert "導入時に追加します" not in page  # "comes with the hospital installation": wrong once TOTP is on


def test_without_totp_the_account_page_keeps_the_later_line(box: dict[str, Any]) -> None:  # noqa: F811
    c = _user(box, "viewer2", "viewer")
    page = c.get("/account").text
    assert "Two-step sign-in comes with the hospital installation." in page
    assert i18n_demoja.EN["account.totp_on"] not in page


def test_the_prescreen_log_reads_the_redcap_note_in_the_page_language() -> None:
    mark = SimpleNamespace(pid="p" * 64, mark="approach", version="1.1.0", reason="", at="2026-11-10T07:00:00+00:00")
    reg = {mark.pid: SimpleNamespace(status="enrolled", reason="REDCap record 3")}
    (row,) = prescreen_rows([mark], {}, {}, reg, {}, set())
    assert row["reason_rc"] == ("3", "")


@pytest.mark.parametrize(
    ("lang", "want"),
    [
        ("ja", "病院全体：過去 36 か月に1回以上受診した患者"),
        ("zh-TW", "全院：過去 36 個月內至少就診一次的病人"),
        ("en", "whole hospital: patients with at least one visit in the last 36 months"),
    ],
)
def test_the_feasibility_population_is_in_the_page_language(lang: str, want: str) -> None:
    assert population_words(lang, "hospital: patients with ≥1 encounter in the last 36 months") == want
    dept = population_words(lang, "departments RHEU,FM: patients with ≥1 encounter in the last 12 months")
    assert "RHEU,FM" in dept and "12" in dept and "encounter" not in dept
    assert population_words(lang, "something else") == "something else"
    assert population_words(lang, "") == "–"


def test_the_data_operations_trail_names_the_event_and_the_adapter_in_japanese(box: dict[str, Any]) -> None:  # noqa: F811
    bid = _night(box, "2026-11-10")
    _user(box, "stwj", "steward")
    c, csrf = login(box["app"], "stwj", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    trail = c.get(f"/data-ops/batches/{bid}").text
    assert "夜間取り込み保留" in trail and "取り込み処理" in trail
    assert ">ingest.held<" not in trail and ">adapter<" not in trail
    assert 'title="ingest.held"' in trail  # the audit event's code stays on the cell for the auditor
    assert "取り込み処理" in c.get("/data-ops").text


def test_a_monitor_grant_says_which_field_is_missing_and_has_a_visit_field(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_console_app import name_pi

    _user(box, "mon9", "cro", affiliation="cro", studies="GZQO")
    _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    pi, csrf = login(box["app"], "drsato", PW)
    pi.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    form = pi.get("/studies/GZQO/team").text
    assert 'data-testid="add-visit"' in form and "モニタリング訪問の ID" in form
    assert "研修修了証（モニターの場合" not in form  # the training-certificate field is labelled for what it is
    grant = {"csrf": csrf, "username": "mon9", "role": "monitor", "start": "2026-01-01"}
    both = pi.post("/studies/GZQO/team", data=grant)
    assert (
        both.status_code == 400
        and "最終日と ID が必要です" in both.text
        and "この依頼は実行できませんでした" not in both.text
    )
    no_end = pi.post("/studies/GZQO/team", data={**grant, "visit": "MV-7"})
    assert no_end.status_code == 400 and "最終日が必要です" in no_end.text
    no_visit = pi.post("/studies/GZQO/team", data={**grant, "end": "2099-12-31"})
    assert no_visit.status_code == 400 and "ID が必要です" in no_visit.text
    ok = pi.post("/studies/GZQO/team", data={**grant, "end": "2099-12-31", "visit": "MV-7"}, follow_redirects=False)
    assert ok.status_code == 303
    assert "MV-7" in pi.get("/studies/GZQO/team").text  # the visit id is on the log entry
