"""T-302d (D-435): the screening log XLSX in the sponsor's columns (``?layout=sponsor``), the same rows and the same
permission question as the site's log. Synthetic data only."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

from datacore import sponsor as sp
from openpyxl import load_workbook
from orchestrator.sponsor_api import router as sponsor_router

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name

LAYOUT = {"sponsor": "Synthetic Pharma", "log": [{"from": "screening_no", "heading": "Subject ID"},
                                                 {"from": "status", "heading": "Subject Status",
                                                  "values": {"candidate": "Pre-screened"}}]}  # fmt: skip


def _rows(content: bytes, sheet: str) -> list[list[Any]]:
    return [list(r) for r in load_workbook(io.BytesIO(content))[sheet].iter_rows(values_only=True)]


def test_the_screening_log_in_the_sponsors_columns(lb: dict[str, Any]) -> None:  # noqa: F811
    lb["oc"].app.include_router(sponsor_router(lambda: SimpleNamespace(dc=lb["dc"])))
    crc, _ = login(lb["app"], "crc", PW)
    assert crc.get("/studies/GZQO/screening-log.xlsx?layout=sponsor").status_code == 404  # no layout saved yet
    assert crc.get("/studies/GZQO/screening-log.xlsx?layout=other").status_code == 404
    sp.Layouts(lb["dc"]).put("GZQO", LAYOUT, "crc", "2026-11-08T09:00:00+08:00")
    site = _rows(crc.get("/studies/GZQO/screening-log.xlsx").content, "screening log")
    assert site[0] == list(sp.LOG_COLUMNS)
    r = crc.get("/studies/GZQO/screening-log.xlsx?layout=sponsor")
    assert r.status_code == 200 and "screening_log_GZQO_sponsor.xlsx" in r.headers["content-disposition"]
    got = _rows(r.content, "screening log")
    assert got[0] == ["Subject ID", "Subject Status"]
    assert [x[0] for x in got[1:]] == [x[0] for x in site[1:]] and len(got) == len(site)
    assert {x[1] for x in got[1:]} == {"Pre-screened"}
    assert all(len(x) == 2 for x in got)  # the pseudonym and every column the sponsor did not name stay out
    assert "pre-screen log" not in load_workbook(io.BytesIO(r.content)).sheetnames


def test_the_log_page_links_the_sponsors_columns_once_a_layout_is_saved(lb: dict[str, Any]) -> None:  # noqa: F811
    """T-302c: the screening-log page links the XLSX in the sponsor's columns, only when a layout names them."""
    lb["oc"].app.include_router(sponsor_router(lambda: SimpleNamespace(dc=lb["dc"])))
    crc, _ = login(lb["app"], "crc", PW)
    page = crc.get("/studies/GZQO/screening-log").text
    assert 'data-testid="log-xlsx"' in page and 'data-testid="log-xlsx-sponsor"' not in page
    sp.Layouts(lb["dc"]).put("GZQO", LAYOUT, "crc", "2026-11-08T09:00:00+08:00")
    page = crc.get("/studies/GZQO/screening-log").text
    assert 'href="/studies/GZQO/screening-log.xlsx?layout=sponsor"' in page
