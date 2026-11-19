# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""10B-6 (D-1233): a night's page says which site profile read the night, and its coverage lines.

The adapter keeps the profile's id, version, digest and the coverage counts in the night's ``ingest.done`` event
(``adapter.site_profile.summary``); the data-operations page of that night shows them in en, ja and zh-TW, counts
and data-type names only, never a code. A night read without a profile has no section. Synthetic data only."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest
from console import dataops_page
from console.i18n import translate
from datacore.dataops import DataOps
from tb_common.audit import AuditLog
from tb_common.wording import check

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW, _user

AT = "2026-11-11T02:00:00+09:00"
PROFILE = {
    "id": "synthetic-jp-ss",
    "site_id": "jp-ss",
    "version": "1.0.0",
    "digest": "65710b353ff0b35549e5fda59ef3f136aee8f49d8c557d4c1fa8f20e25f53662",
    "types_declared": 17,
    "types_arrived": 16,
    "not_arrived": ["ADT-22"],
    "not_declared": ["OMD"],
    "unmapped_codes": 3,
    "unmapped_rows": 1204,
    "verify_rows": 68,
    "pending": "abcdef0123456789",
    "units_not_read_rows": 7,
}


def _night(b: dict[str, Any], profile: Any) -> int:
    ops = DataOps()
    try:
        detail = {"counts": {"Observation": 10}, **({"site_profile": profile} if profile is not None else {})}
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.done", source="ssmix2",
                                    snapshot="2026-11-10", passed=True, held=False, by="adapter", at=AT,
                                    actor="adapter", detail=detail)  # fmt: skip
        return batch.id
    finally:
        ops.close()


def _steward(b: dict[str, Any]) -> Any:
    _user(b, "stwp", "steward")
    return login(b["app"], "stwp", PW)


def _section(page: str) -> str:
    m = re.search(r'<section class="card" data-testid="batch-profile">(.*?)</section>', page, re.S)
    assert m, "no section for the site profile"
    return m.group(1)


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_nights_page_says_which_profile_read_it_and_its_coverage(box: dict[str, Any], lang: str) -> None:
    bid = _night(box, PROFILE)
    c, csrf = _steward(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = c.get(f"/data-ops/batches/{bid}").text
    assert 'name="viewport"' in page and "width=device-width" in page  # the phone's page (390 px)
    sec = _section(page)
    assert translate(lang, "dataops.profile.title") in sec
    assert "synthetic-jp-ss" in sec and "1.0.0" in sec and "65710b353ff0" in sec and str(PROFILE["digest"]) not in sec
    assert "ADT-22" in sec and "OMD" in sec and "1,204" in sec and ">68" not in sec and "68" in sec
    assert "style=" not in sec and "nowrap" not in sec
    # point 7 of the lane lead's check: the steward reads here that the site set-up store wins and the night cannot
    # apply it yet; and that a folder nobody loaded was not applied
    assert translate(lang, "dataops.profile.store_wins") in sec and 'data-testid="profile-store-wins"' in sec
    assert html.escape(translate(lang, "dataops.profile.pending", digest="abcdef012345"), quote=False) in sec
    assert translate(lang, "dataops.profile.units", n="7") in sec
    if lang == "en":
        assert not check(sec)
        assert "16 of 17 declared arrived" in sec


def test_the_api_gives_the_same_lines(box: dict[str, Any]) -> None:
    from fastapi.testclient import TestClient

    bid = _night(box, PROFILE)
    _user(box, "stwp", "steward")
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "stwp", "password": PW}).json()["token"]
    got = api.get(f"/api/v1/data/batches/{bid}", headers={"Authorization": f"Bearer {tok}"}).json()["site_profile"]
    assert got["id"] == "synthetic-jp-ss" and got["digest"] == "65710b353ff0" and got["verify_rows"] == 68


def test_a_night_read_without_a_profile_has_no_section(box: dict[str, Any]) -> None:
    bid = _night(box, None)
    c, _ = _steward(box)
    assert 'data-testid="batch-profile"' not in c.get(f"/data-ops/batches/{bid}").text


@pytest.mark.parametrize(
    "bad",
    ["x", {**PROFILE, "verify_rows": -1}, {**PROFILE, "unmapped_rows": "many"}, {**PROFILE, "id": ""},
     {**PROFILE, "not_arrived": "ADT-22"}, {**PROFILE, "types_declared": True}],
)  # fmt: skip
def test_a_record_of_another_shape_is_not_shown_and_breaks_no_page(box: dict[str, Any], bad: Any) -> None:
    assert dataops_page.site_profile_of({"site_profile": bad}) is None
    bid = _night(box, bad)
    c, _ = _steward(box)
    r = c.get(f"/data-ops/batches/{bid}")
    assert r.status_code == 200 and 'data-testid="batch-profile"' not in r.text


def test_a_type_name_is_written_as_text(box: dict[str, Any]) -> None:
    bid = _night(box, {**PROFILE, "not_declared": ['x"><b>y</b>']})
    c, _ = _steward(box)
    page = c.get(f"/data-ops/batches/{bid}").text
    assert "<b>y</b>" not in page and "&lt;b&gt;y&lt;/b&gt;" in page
