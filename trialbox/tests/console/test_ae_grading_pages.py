"""D-396 (T-619b): the forms page adds the built-in forms with an oncology study's CTCAE version, the AE entry then
offers grades 1 to 5 with that version, and the CDISC export downloads with the CDASH IE and DS rows; the strings in
three languages."""

from __future__ import annotations

import re
from typing import Any

from console.i18n import CATALOGUES
from console.i18n_cdash import EN, JA, ZH
from tb_common.wording import check_page

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_data_pages import PW, _api, dcb  # noqa: F401 - the fixture is used by name


def test_an_oncology_study_adds_the_forms_with_its_ctcae_version(dcb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf = login(dcb["app"], "crc", PW)
    page = c.get("/studies/GZQO/forms").text
    assert 'data-testid="builtin-ctcae"' in page and '<option value="5">CTCAE v5.0</option>' in page
    r = c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf, "ctcae": "5"})
    assert 'data-testid="dc-ctcae-added">CTCAE grading: CTCAE v5.0.' in r.text
    assert 'data-testid="field-ae_ctcae_grade"' in r.text and "Grade 5 (death related to the event)" in r.text
    calls = [b for m, p, b in dcb["calls"] if m == "POST" and p.endswith("/forms/builtin")]
    assert calls[-1]["ctcae"] == "5"
    r = c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf, "ctcae": "4.03"})  # not a CTCAE version
    assert "err=FORM-CTCAE" in str(r.url) or "FORM-CTCAE" in r.text
    # the plain forms again: no grade on the AE form
    r = c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    assert 'data-testid="field-ae_ctcae_grade"' not in r.text and 'data-testid="dc-ctcae-added"' not in r.text


def test_the_api_takes_the_version_and_the_cdisc_export_downloads(dcb: dict[str, Any]) -> None:  # noqa: F811
    api = _api(dcb, "crc")
    r = api.post("/api/v1/studies/GZQO/forms/builtin", json={"ctcae": "6.0"})
    assert r.status_code == 200 and r.json()["ctcae"] == "6", r.text
    c, _ = login(dcb["app"], "crc", PW)
    assert 'data-testid="export-cdisc"' in c.get("/studies/GZQO/forms").text
    r = c.get("/studies/GZQO/export.cdisc.odm.xml")
    assert r.status_code == 200 and "Form.cdash" in r.text and 'Name="AE.AETOXGR"' in r.text
    assert re.search(r'filename="GZQO_\d{8}\.cdisc\.odm\.xml"', r.headers["content-disposition"])
    assert "Form.cdash" not in c.get("/studies/GZQO/export.odm.xml").text


def test_every_key_in_three_languages_with_the_same_placeholders() -> None:
    assert set(EN) == set(JA) == set(ZH)
    for cat in (JA, ZH):
        for k, v in cat.items():
            assert sorted(re.findall(r"\{(\w+)\}", EN[k])) == sorted(re.findall(r"\{(\w+)\}", v)), k
    for lang, cat in CATALOGUES.items():
        assert all(k in cat for k in EN), lang
        assert not any(check_page(cat[k]) for k in EN), lang  # T-116: no verdict word
