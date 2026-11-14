# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""NEW-DOPS-1 (D-708): the data-operations pages show the rows of a night that hold a value the mapping could not
use (a hospital code that is not in the site's code table, a unit or status it could not read).

The adapter counts them every night (D-580) and the night's row keeps the count per table (never a code, never a
row). Until this card no page showed it: a lab analyte could be missing for every patient with nothing to see. The
night's page lists every table with its count, the largest first, and says where the codes are; the source's line
on ``/data-ops`` carries the total and links to that night. Synthetic data only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from console import dataops_page, i18n_dataops
from datacore.dataops import DataOps
from tb_common.audit import AuditLog
from tb_common.wording import check

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW, _user

AT = "2026-11-11T02:00:00+09:00"


def _night(b: dict[str, Any], snap: str, unmapped: Any, *, source: str = "csv") -> int:
    ops = DataOps()
    try:
        detail = {"counts": {"Observation": 10}, **({"unmapped": unmapped} if unmapped is not None else {})}
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.done", source=source,
                                    snapshot=snap, passed=True, held=False, by="adapter", at=AT, actor="adapter",
                                    detail=detail)  # fmt: skip
        return batch.id
    finally:
        ops.close()


def _steward(b: dict[str, Any]) -> Any:
    _user(b, "stwu", "steward")
    return login(b["app"], "stwu", PW)


def _section(page: str) -> str:
    m = re.search(r'<section class="card" data-testid="batch-unmapped">(.*?)</section>', page, re.S)
    assert m, "no section for the values the mapping could not use"
    return m.group(1)


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    """NEW-ARCH-3 (D-761): the page reads over the orchestrator's routes."""
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])


def test_the_nights_page_lists_every_table_with_its_count_the_largest_first(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10", {"medication": 3, "lab": 1200, "visit": 41})
    c, _ = _steward(box)
    sec = _section(c.get(f"/data-ops/batches/{bid}").text)
    rows = re.findall(r'<tr data-testid="unmapped" data-table="([^"]+)">.*?<td class="num">([\d,]+)</td>', sec, re.S)
    assert rows == [("lab", "1,200"), ("visit", "41"), ("medication", "3")]
    assert 'data-testid="unmapped-total">1,244<' in sec
    assert "unmapped_codes.json" in sec  # where the codes are: the night's folder, for whoever keeps the code table
    assert not check(sec)


def test_no_table_is_cut_and_equal_counts_are_in_the_order_of_their_names(box: dict[str, Any]) -> None:
    kept = {f"t{i:02d}": 5 for i in range(40)} | {"zz": 9}
    bid = _night(box, "2026-11-10", kept)
    c, _ = _steward(box)
    sec = _section(c.get(f"/data-ops/batches/{bid}").text)
    assert re.findall(r'data-table="([^"]+)"', sec) == ["zz", *(f"t{i:02d}" for i in range(40))]
    assert 'data-testid="unmapped-total">209<' in sec


def test_the_words_do_not_say_the_rows_were_left_out_or_that_a_code_is_the_cause() -> None:
    """D-580's counter also holds rows that were loaded without a value (a unit not read: D-590) and rows whose
    code the reference data could not be asked for (D-593), and counts a row once per such value."""
    en = i18n_dataops.EN
    for key in ("dataops.unmapped.title", "dataops.unmapped.mark", "dataops.unmapped.records"):
        assert "not loaded" not in en[key] and "record" not in en[key].lower() and "code" not in en[key], key
    said = en["dataops.unmapped.help"]
    assert "left out, or loaded without that value" in said and "counted twice" in said and "unit" in said


def test_a_night_with_none_has_no_section_and_no_mark(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10", None)
    c, _ = _steward(box)
    assert 'data-testid="batch-unmapped"' not in c.get(f"/data-ops/batches/{bid}").text
    assert 'data-testid="source-unmapped"' not in c.get("/data-ops").text


def test_the_sources_line_carries_the_total_and_links_to_the_night(box: dict[str, Any]) -> None:
    _night(box, "2026-11-09", {"lab": 7})  # an older night of the same source: not the one the line is about
    bid = _night(box, "2026-11-10", {"lab": 1200, "medication": 3})
    c, _ = _steward(box)
    page = c.get("/data-ops").text
    m = re.search(r'<a href="/data-ops/batches/(\d+)" data-testid="source-unmapped">([^<]+)</a>', page)
    assert m and int(m.group(1)) == bid and "1,203" in m.group(2), page[:400]
    assert page.count('data-testid="source-unmapped"') == 1


@pytest.mark.parametrize("kept", ["lab", ["lab"], {"lab": "many"}, {"lab": -4}, {"lab": True}, {"": 5}, {"lab": 0}])
def test_a_count_that_is_not_one_is_not_shown_and_breaks_no_page(box: dict[str, Any], kept: Any) -> None:
    assert dataops_page.unmapped_of({"unmapped": kept}) == []
    bid = _night(box, "2026-11-10", kept)
    c, _ = _steward(box)
    r = c.get(f"/data-ops/batches/{bid}")
    assert r.status_code == 200 and 'data-testid="batch-unmapped"' not in r.text
    assert c.get("/data-ops").status_code == 200


def test_a_tables_name_is_the_sites_own_text_and_is_written_as_text(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10", {'lab"><b>x</b>': 2})
    c, _ = _steward(box)
    page = c.get(f"/data-ops/batches/{bid}").text
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page


def test_the_api_answers_the_same_counts(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10", {"medication": 3, "lab": 1200})
    from fastapi.testclient import TestClient

    from tests.console.test_dataops_page import _bearer

    r = TestClient(box["app"]).get(f"/api/v1/data/batches/{bid}", headers=_bearer(box, "stwa", "steward"))
    assert r.status_code == 200, r.text[:200]
    got = r.json()
    assert got["unmapped"] == [{"table": "lab", "rows": 1200}, {"table": "medication", "rows": 3}]


@pytest.mark.parametrize(("lang", "title"), [("en", "could not use"), ("ja", "使えなかった"), ("zh-TW", "無法使用")])
def test_the_section_in_three_languages(box: dict[str, Any], lang: str, title: str) -> None:
    bid = _night(box, "2026-11-10", {"lab": 1200})
    c, csrf = _steward(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    sec = _section(c.get(f"/data-ops/batches/{bid}").text)
    assert title in sec and not check(sec)
    assert title in c.get("/data-ops").text
    cat = {"en": i18n_dataops.EN, "ja": i18n_dataops.JA, "zh-TW": i18n_dataops.ZH}[lang]
    assert {"dataops.unmapped.title", "dataops.unmapped.help", "dataops.unmapped.mark",
            "dataops.unmapped.table", "dataops.unmapped.records", "dataops.unmapped.total"} <= set(cat)  # fmt: skip
