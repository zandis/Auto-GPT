"""D-140: the admin page shows the reference data's "data as of" date, and the sources page shows every source's
licence and the credit it asks for (generated from the pack manifest), in en, ja and zh-TW."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from console.i18n_step4 import EN, JA, ZH
from tb_common import refdata as rd

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, box, login  # noqa: F401 - fixture by name
from tools import refdata_fetch as rf

KEYS = [k for k in EN if k.startswith(("admin.refdata", "admin.attrib", "admin.notice_page"))]


def test_the_strings_exist_in_three_languages() -> None:
    assert len(KEYS) == 12
    for k in KEYS:
        assert JA[k] and ZH[k] and JA[k] != EN[k] and ZH[k] != EN[k]
    assert "{pack}" in JA["admin.refdata.asof"] and "{pack}" in ZH["admin.refdata.asof"]


def test_without_a_pack_the_tile_says_so(box: dict[str, Any]) -> None:  # noqa: F811
    c, _ = login(box["app"])
    page = c.get("/admin").text
    assert 'data-testid="tile-refdata"' in page and 'data-testid="refdata-none"' in page
    assert 'data-testid="notice-none"' in c.get("/admin/notice").text


def test_the_tile_and_the_sources_page(box: dict[str, Any], db_url: str, tmp_path: Path) -> None:  # noqa: F811
    tar = rf.build(rf.sample_raw(tmp_path / "raw"), tmp_path, "20261109", sample=True)
    with rd.opened(tar) as p, rd.RefStore(db_url) as st:
        st.load(p)
    c, _ = login(box["app"])
    page = c.get("/admin").text
    assert 'data-testid="refdata-asof">2026-11-09<' in page and "trialbox-refdata-20261109" in page
    assert "ClinicalTrials.gov, all studies" in page
    notice = c.get("/admin/notice").text
    m = rd.read_manifest(tmp_path / "trialbox-refdata-20261109")
    for s in m["sources"]:
        assert f'data-testid="notice-{s["id"]}"' in notice
    assert "U.S. National Library of Medicine" in notice and "Open Government Data License" in notice
    assert "出典：厚生労働省" in notice  # the MHLW credit as the licence asks for it
    viewer, _ = login(box["app"], "viewer", VIEWER_PW)
    assert viewer.get("/admin/notice").status_code == 403
