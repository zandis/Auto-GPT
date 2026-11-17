"""Card V-8: ``tools/audit_trail_check.py`` holds the page's generated tables to the json beside it, lists the
changing routes of a live app with included routers, and finds the audit writes in code. A planted fault fails."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI

from tools import audit_trail_check as atc


def _data() -> dict[str, Any]:
    return {n: json.loads((atc.DIR / f"{n}.json").read_text("utf-8")) for n in ("tamper", "routes", "findings")}


def test_the_committed_page_matches_its_json() -> None:
    assert atc.main(["--check"]) == 0


def test_a_changed_count_on_the_page_is_found(tmp_path: Path) -> None:
    page = atc.PAGE.read_text("utf-8")
    data = _data()
    assert atc.problems(page, data) == []
    planted = page.replace(f"Findings: {len(data['findings']['findings'])}.", "Findings: 99.", 1)
    assert planted != page
    assert any("findings" in p for p in atc.problems(planted, data))


def test_a_changed_json_is_found() -> None:
    data = _data()
    data["tamper"]["cases"][0]["cli_heads_ok"] = True  # a case now said to pass
    assert any("tamper" in p for p in atc.problems(atc.PAGE.read_text("utf-8"), data))


def test_a_missing_block_is_found() -> None:
    page = atc.PAGE.read_text("utf-8")
    cut = atc.BLOCK.sub(lambda m: "" if m.group(1) == "driven" else m.group(0), page)
    assert "block driven: missing from the page" in atc.problems(cut, _data())


def test_changing_routes_flattens_included_routers_and_finds_the_audit_call() -> None:
    r = APIRouter()

    @r.post("/inner")
    def inner() -> None:
        au: Any = None
        au.append("x.inner", actor="console:someone")

    app = FastAPI()

    @app.post("/outer")
    def outer() -> None:
        return None

    @app.get("/read")
    def read() -> None:
        return None

    app.include_router(r, prefix="/p")
    rows = {f"{x['method']} {x['path']}": x for x in atc.changing_routes(app)}
    assert set(rows) == {"POST /outer", "POST /p/inner"}
    assert rows["POST /p/inner"]["audit_call"] and rows["POST /outer"]["audit_call"] is None


def test_the_sweep_marks_free_text_and_masking(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "def f(au, note, mask_detail):\n"
        "    au.append('a.one', actor='x', detail={'note': note})\n"
        "    au.append('a.two', actor='x', detail=mask_detail({'note': note}))\n"
        "    au.append('a.three', actor='x', detail={'n': 1})\n",
        "utf-8",
    )
    rows = {r["event"]: r for r in atc.sweep(tmp_path)}
    assert rows["a.one"]["free"] == ["detail.note"] and not rows["a.one"]["masked"]
    assert rows["a.two"]["masked"]
    assert rows["a.three"]["free"] == []
