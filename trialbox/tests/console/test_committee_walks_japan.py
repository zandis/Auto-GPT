"""10C-4 (D-1227): the role walk and the role x route matrix at a Japanese site, where the Japan profile adds the
committee page and its API twin. The walks of a box outside Japan (``test_matrix_role_walk``,
``test_role_route_matrix``) are as before this card: the routes are not there.

* The role walk (card V-2) walks every route as every column on a Japanese box and judges it against
  ``route_actions.yaml`` and ``route_actions_japan.yaml``: every route has its row, and the committee routes answer
  every column as their rows (copied from the study's IRB routes) say, with no unclear cell.
* The Japan table (``data/role_route_matrix_japan.md``, regenerated with ``TB_WRITE_ROLE_MATRIX=1``) is who may use
  the four routes, walked as ``test_role_route_matrix`` walks; it equals the IRB routes' rows of the main table.

Synthetic data only."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.console import test_role_route_matrix as rm
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_matrix_role_walk import run_walk, unclear_now
from tools import role_walk as rw

DATA = Path(__file__).parent / "data"
JAPAN_ROWS = DATA / "route_actions_japan.yaml"
JAPAN_TABLE = DATA / "role_route_matrix_japan.md"
COMMITTEE = "/committee"


@pytest.fixture
def japan_box(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The console's test box made at a Japanese site (the routes are added when the app is made)."""
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    monkeypatch.setenv("TB_SITE_ID", "SAMPLE-A")
    return dict(request.getfixturevalue("box"))


def test_the_role_walk_at_a_japanese_site(japan_box: dict[str, Any], tmp_path: Path) -> None:
    declared = {**rw.load_declared(), **rw.load_declared(JAPAN_ROWS)}
    rows = rw.judge_declared(run_walk(japan_box, tmp_path), declared)
    assert not rw.table_problems(rows, declared)  # every route has its row, every row its route
    ours = [r for r in rows if r["path"].endswith(COMMITTEE)]
    assert len(ours) == 4
    bad = {(r["method"], r["path"], n): c["verdict"] for r in ours for n, c in r["cells"].items()
           if c["verdict"] in (rw.ALLOWED_X, rw.REFUSED_X)}  # fmt: skip
    assert not bad, bad
    assert not {u for u in unclear_now(ours)}, unclear_now(ours)


def test_who_may_use_the_committee_routes_at_a_japanese_site(japan_box: dict[str, Any]) -> None:
    walked = [(m, p, c) for m, p, c in rm.walk(japan_box) if p.endswith(COMMITTEE)]
    got = rm.render(walked).replace("Role x route matrix", "Role x route matrix at a Japanese site (10C-4)")
    if os.environ.get("TB_WRITE_ROLE_MATRIX") == "1":
        JAPAN_TABLE.write_text(got, encoding="utf-8")
    assert rm.parse(got) == rm.parse(JAPAN_TABLE.read_text(encoding="utf-8"))
    main = rm.parse(rm.TABLE.read_text(encoding="utf-8"))
    for (method, path), cells in rm.parse(got).items():  # the same answers as the IRB route it mirrors
        assert cells == main[(method, path.replace(COMMITTEE, "/irb"))], (method, path)
