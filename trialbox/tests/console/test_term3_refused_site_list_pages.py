# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""E-TERM-3 (D-1048): the console says when a site code list was not read, and holds approval while it is not.

The compiler writes each table it could not read into the review workbook's ``terminology`` sheet (and refuses the
approval itself, ``tests/unit/test_term3_refused_site_list.py``). The approval page shows them in the page's language
and holds **Approve all** while one is a site list; a refused shipped table is a warning only. The administrator's
home shows a site list the box does not read now. The site list is SYNTHETIC.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.terminology import installed

from tests.console.test_console_app import STW_PW, box, login, review_book  # noqa: F401 - fixture by name
from tests.console.test_first_approval import NEW, _waiting
from tests.console.test_role_pages import _csrf, _user

REASON = "/data/terminology/site_dx.parquet: its sha256 differs from manifest.json; load it again"


def _with_sheet(book: bytes, rows: list[tuple[str, str]]) -> bytes:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(book))
    ws = wb.create_sheet("terminology")
    ws.append(["table", "reason", "blocks approval"])
    for table, reason in rows:
        ws.append([table, reason, "yes" if table.startswith("site_") else "no"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pi_named(b: dict[str, Any], n: int, refused: list[tuple[str, str]]) -> tuple[Any, str]:
    jid = _waiting(b, n)
    key = f"outputs/{jid}/review_{NEW}_v1.0.0_r1.xlsx"
    b["backend"].objects[key] = _with_sheet(b["backend"].objects[key], refused)
    pi = _user(b, "drsato", "investigator")
    b["users"].create("stw1", "steward", STW_PW, "stw1@hospa.test")
    stw, _ = login(b["app"], "stw1", STW_PW)
    log = stw.get(f"/studies/{NEW}/team")
    r = stw.post(f"/studies/{NEW}/team", data={"csrf": _csrf(log.text), "username": "drsato", "role": "pi",
                                               "start": "2026-01-01", "training_day": "2025-06-01"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    page = pi.get(f"/pilot/jobs/{jid}/approval")
    pi.post(f"/pilot/jobs/{jid}/approval/tick", data={"csrf": _csrf(page.text), "crit": f"{NEW}-INC-01"})
    return pi, jid


@pytest.fixture
def no_box_lists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    where = tmp_path / "terminology"
    monkeypatch.setenv(installed.DIR_ENV, str(where))
    return where


def test_a_refused_site_list_holds_approve_all_and_says_why(box: dict[str, Any], no_box_lists: Path) -> None:
    pi, jid = _pi_named(box, 981, [("site_dx", REASON)])
    page = pi.get(f"/pilot/jobs/{jid}/approval").text
    assert 'data-testid="term-refused-site_dx"' in page and "sha256 differs" in page
    assert 'data-testid="term-refused-blocks"' in page and 'data-testid="approve-term-refused"' in page
    assert '<button type="submit" data-testid="approve">' not in page  # held, not offered
    r = pi.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page), "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 409 and "site_dx" in r.text
    assert box["backend"].created == []  # nothing was sent to the compiler


def test_a_refused_shipped_table_is_a_warning_only(box: dict[str, Any], no_box_lists: Path) -> None:
    pi, jid = _pi_named(box, 982, [("icd10cm_index", "icd10cm_index.parquet: no line in manifest.json")])
    page = pi.get(f"/pilot/jobs/{jid}/approval").text
    assert 'data-testid="term-refused-icd10cm_index"' in page and "does not stop approval" in page
    assert 'data-testid="term-refused-blocks"' not in page
    r = pi.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page), "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and [q.type for q in box["backend"].created] == ["APPROVE"]


@pytest.mark.parametrize(("lang", "words"), [
    ("en", ("A code list was not read", "cannot be approved")),
    ("zh-TW", ("有代碼表未能讀取", "不能核准")),
    ("ja", ("読み込めなかったコード表があります", "承認できません")),
])  # fmt: skip
def test_the_approval_page_says_it_in_three_languages(box: dict[str, Any], no_box_lists: Path, lang: str,
                                                      words: tuple[str, ...]) -> None:  # fmt: skip
    pi, jid = _pi_named(box, 983, [("site_dx", REASON)])
    page = pi.get(f"/pilot/jobs/{jid}/approval").text
    pi.post("/lang", data={"csrf": _csrf(page), "lang": lang, "back": f"/pilot/jobs/{jid}/approval"})
    page = pi.get(f"/pilot/jobs/{jid}/approval").text
    for w in words:
        assert w in page, (lang, w)


def test_a_site_list_refused_on_the_box_shows_on_the_admin_home_and_the_approval_page(
    box: dict[str, Any],
    no_box_lists: Path,
    tmp_path: Path,
) -> None:
    src = tmp_path / "dx.csv"
    src.write_text("local_code,local_name,system,code,display\nZZ-DX-0001,hypertension,icd10cm,I10,\n",
                   encoding="utf-8")  # fmt: skip
    installed.install_site_list(src, no_box_lists, "dx")
    admin, _ = login(box["app"])
    assert 'data-testid="term-refused"' not in admin.get("/admin").text
    p = no_box_lists / "site_dx.parquet"
    p.write_bytes(p.read_bytes() + b"\0")
    home = admin.get("/admin").text
    assert 'data-testid="term-refused-site_dx"' in home and 'data-testid="term-refused-admin"' in home
    pi, jid = _pi_named(box, 984, [])  # compiled clean; the list was refused after the compile
    page = pi.get(f"/pilot/jobs/{jid}/approval").text
    assert 'data-testid="term-refused-site_dx"' in page and 'data-testid="term-refused-blocks"' in page
