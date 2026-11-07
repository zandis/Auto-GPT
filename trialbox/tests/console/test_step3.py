"""Build step 3 (D-109) in the console: S36 REDCap connection, S21 study set-up (three sections, saved in the
orchestrator's S-28 store through its API), Test link, Run now and the nightly read-back on the screening log."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from console import rc_read, s28
from console.backend import problem_of
from console.i18n import CATALOGUES
from console.i18n_step3 import EN, JA, ZH
from console.sitestore import StudySettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.study_api import router

from tests.console.test_console_app import ADMIN_PW, box, login  # noqa: F401 - the fixture is used by name
from tests.rc_kit import LINK_A, TOKEN_A, sim_edit, study_service

PW = "step-three-password-01"
AT = "2026-11-07T09:00:00+00:00"


@pytest.fixture
def b3(box: dict[str, Any], tmp_path: Path) -> Iterator[dict[str, Any]]:  # noqa: F811
    """The console box with the orchestrator's study API (a real S-28 store and registry) and a REDCap simulator."""
    with study_service(tmp_path / "orch") as (svc, sim, clock):
        api = FastAPI()
        api.include_router(router(lambda: svc))
        oc = TestClient(api)
        bk = box["backend"]

        def study_api(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
            r = oc.request(method, path, json=body) if body is not None else oc.request(method, path)
            if r.status_code >= 400:
                raise problem_of(r.status_code, r.text)
            return r.json()

        bk.study_api = study_api
        bk.registry_rows = svc.registry.rows  # the log shows the orchestrator's registry
        h = box["app"].state.helpers
        for n in (1, 2):  # GZQO-0901, GZQO-0902 (the simulator's project A carries these numbers)
            h.store.assign_screening_no("GZQO", f"{n:02x}" * 16, StudySettings(first_no=901), AT)
        for name, role in (("crc", "coordinator"), ("pi", "investigator")):
            box["users"].create(name, role, PW, f"{name}@hospa.test")
        yield {**box, "svc": svc, "sim": sim, "clock": clock, "h": h}


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _connect(b: dict[str, Any]) -> None:
    c, csrf = login(b["app"], "admin", ADMIN_PW)
    r = c.post("/admin/redcap", data={"csrf": csrf, "token_ref": "main", "url": "inproc://rc-sim-test",
                                      "token": TOKEN_A})  # fmt: skip
    assert r.status_code == 200 and "s36-saved" in r.text, r.text[:400]


def _link(b: dict[str, Any], c: TestClient, csrf: str, **over: str) -> Any:
    form = {k: v for k, v in LINK_A.items() if isinstance(v, str)}
    form.update({"csrf": csrf, "token_ref": "main", "project_id": "101",
                 "screenfail_choice_map": "1=inclusion, 2=exclusion, 3=consent_withdrawn, 9=other", **over})  # fmt: skip
    return c.post("/studies/GZQO/setup/redcap", data=form)


def test_s36_token_entered_once_masked_and_tested(b3: dict[str, Any]) -> None:
    c, csrf = login(b3["app"], "admin", ADMIN_PW)
    assert "s36.none" not in c.get("/admin/redcap").text
    r = c.post(
        "/admin/redcap", data={"csrf": csrf, "token_ref": "main", "url": "inproc://rc-sim-test", "token": "short"}
    )
    assert "RC-TOKEN" in r.text
    _connect(b3)
    page = c.get("/admin/redcap").text
    assert "••••8F90" in page and TOKEN_A not in page and 'type="password"' in page
    r = c.post("/admin/redcap/main/test", data={"csrf": csrf})
    assert "16.0.10" in r.text and "101" in r.text and "GZQO screening (simulated)" in r.text
    r = c.post("/admin/redcap", data={"csrf": csrf, "token_ref": "main", "url": "inproc://rc-sim-test", "token": ""})
    assert "s36-saved" in r.text  # an empty token keeps the stored one
    assert b3["svc"].store.token("main") == TOKEN_A
    crc, crc_csrf = login(b3["app"], "crc", PW)
    assert crc.get("/admin/redcap").status_code == 403
    assert crc.post("/admin/redcap", data={"csrf": crc_csrf, "url": "x"}).status_code == 403


def test_s21_sections_saved_in_the_orchestrator_store(b3: dict[str, Any]) -> None:
    c, csrf = login(b3["app"], "crc", PW)
    page = c.get("/studies/GZQO/setup").text
    for sec in ("setup-study", "setup-redcap", "setup-log", "setup-local"):
        assert f'data-testid="{sec}"' in page
    r = c.post("/studies/GZQO/setup/study", data={"csrf": csrf, "study_type": "trial", "cohort_kind": "enrolled",
                                                 "consent_scope": "opt-in"})  # fmt: skip
    assert r.status_code == 200 and 'data-testid="setup-entered"' in r.text
    r = c.post("/studies/GZQO/setup/log", data={"csrf": csrf, "screening_prefix": "GZ-", "first_no": "950",
                                               "reasons": ["comorbidity", "stage"]})  # fmt: skip
    row = b3["svc"].store.settings("GZQO")
    assert row["consent_scope"] == "opt-in" and row["screening_no_format"] == "GZ-" and row["screening_no_next"] == 950
    assert row["not_suitable_reasons"] == ["stage", "comorbidity"] and row["entered_by"] == "console:crc"
    conf = b3["h"].settings_of("GZQO")  # the list, numbers and reasons now read S-28
    assert conf.reasons == ("stage", "comorbidity") and conf.screening_prefix == "GZ-" and conf.first_no == 950
    assert b3["h"].store.assign_screening_no("GZQO", "ee" * 16, conf, AT) == "GZ-0950"
    r = c.post("/studies/GZQO/setup/log", data={"csrf": csrf, "first_no": "1"})
    assert "STUDY-FIELD" in r.text  # at least one reason


def test_s21_read_only_for_the_investigator(b3: dict[str, Any]) -> None:
    c, csrf = login(b3["app"], "pi", PW)
    page = c.get("/studies/GZQO/setup").text
    assert 'data-testid="setup-readonly"' in page and 'data-testid="save-study"' not in page
    r = c.post("/studies/GZQO/setup/study", data={"csrf": csrf, "study_type": "registry", "cohort_kind": "dynamic"})
    assert r.status_code == 403
    assert b3["svc"].store.settings("GZQO") is None


def test_link_checked_against_the_dictionary_then_run_now_updates_the_log(b3: dict[str, Any]) -> None:
    _connect(b3)
    c, csrf = login(b3["app"], "crc", PW)
    r = _link(b3, c, csrf, consent_field="icf_dt")
    assert "RC-LINK-FIELD" in r.text and "icf_dt" in r.text
    r = _link(b3, c, csrf)
    assert 'data-testid="link-on"' in r.text and 'data-testid="setup-saved"' in r.text
    r = c.post("/studies/GZQO/setup/redcap/test", data={"csrf": csrf})
    assert 'data-testid="test-result"' in r.text and "GZQO-0901" in r.text

    log = c.get("/studies/GZQO/screening-log").text
    assert 'data-testid="run-now"' in log and "S-0001" not in log
    r = c.post("/studies/GZQO/redcap-read", data={"csrf": csrf, "back": "log"})
    assert r.status_code == 200 and 'data-testid="read-done"' in r.text
    status = re.search(r'data-testid="status-GZQO-0901">([^<]+)', r.text)
    assert status and status.group(1).startswith("enrolled")
    assert "S-0001" in r.text and 'data-testid="rc-changes"' in r.text
    assert re.search(r'data-testid="status-GZQO-0902">screen failure', r.text)

    # the demo: change a status in the simulator, press Run now, see it in the log
    sim_edit(b3["sim"], 101, [{"record_id": "2", "sf_reason": "", "consent_date": "2026-11-07"}])
    r = c.post("/studies/GZQO/redcap-read", data={"csrf": csrf, "back": "log"})
    assert re.search(r'data-testid="status-GZQO-0902">consented', r.text)
    xlsx = c.get("/studies/GZQO/screening-log.xlsx")
    assert xlsx.status_code == 200


def test_duplicate_and_renamed_field_are_shown(b3: dict[str, Any]) -> None:
    _connect(b3)
    c, csrf = login(b3["app"], "crc", PW)
    _link(b3, c, csrf)
    sim_edit(b3["sim"], 101, [{"record_id": "3", "tb_screening_no": "GZQO-0901"}])
    r = c.post("/studies/GZQO/redcap-read", data={"csrf": csrf})
    assert 'data-testid="rc-dup"' in r.text and "RC-LINK-DUP" in r.text
    TestClient(b3["sim"]).post("/sim/metadata/rename", json={"project_id": 101, "old": "enrolled", "new": "enrol"})
    r = c.post("/studies/GZQO/redcap-read", data={"csrf": csrf})
    assert "RC-LINK-FIELD" in r.text and 'data-testid="link-off"' in r.text


def test_nightly_read_back(b3: dict[str, Any]) -> None:
    _connect(b3)
    c, csrf = login(b3["app"], "crc", PW)
    _link(b3, c, csrf)
    out = rc_read.run(b3["h"])
    assert out == [("GZQO", "2 rows, 2 changes, 0 duplicates, 0 conflicts, 0 not in TrialBox")]
    assert {e.status for e in b3["svc"].registry.rows("GZQO")} == {"enrolled", "screen_fail"}


def test_japanese_pages(b3: dict[str, Any]) -> None:
    _connect(b3)
    c, csrf = login(b3["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja"})
    assert "試験の設定" in c.get("/studies/GZQO/setup").text
    a, acsrf = login(b3["app"], "admin", ADMIN_PW)
    a.post("/lang", data={"csrf": acsrf, "lang": "ja"})
    assert "REDCap 接続" in a.get("/admin/redcap").text


def test_without_a_study_store_the_step2_settings_still_apply(box: dict[str, Any]) -> None:  # noqa: F811
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    c, csrf = login(box["app"], "crc", PW)
    assert not s28.has_api(box["backend"])
    page = c.get("/studies/GZQO/setup").text
    assert 'data-testid="setup-local"' in page
    r = c.post("/studies/GZQO/setup/study", data={"csrf": csrf, "study_type": "trial", "cohort_kind": "enrolled"})
    assert 'data-testid="setup-error"' in r.text


def test_step3_strings_in_three_languages() -> None:
    assert set(EN) == set(JA) == set(ZH)
    for cat in CATALOGUES.values():
        assert "rc.err.RC-LINK-DUP" in cat and "setup.title" in cat
