"""Card 10B-22 (D-1261): the role walk and the role x route matrix of the MEDIS master step at a site whose country
layer uses the master. Its three routes answer every column as their rows in ``route_actions_japan.yaml`` say (the
row of ``POST /site/codes``, ``site.setup``), with no unclear cell, and their matrix cells are those of
``POST /site/codes`` in the main table. The walks of a box outside the layer are as before: the routes are not
there (``test_matrix_role_walk``, ``test_role_route_matrix``). Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.console import test_role_route_matrix as rm
from tests.console.test_committee_walks_japan import JAPAN_ROWS, japan_box  # noqa: F401 - the fixture by name
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_matrix_role_walk import UNCLEAR, run_walk, unclear_now
from tools import role_walk as rw

MEDIS = "/site/codes/medis"
NEIGHBOUR = ("admin", "crc", "smo_in", "smo_out")


def test_the_role_walk_of_the_medis_step(japan_box: dict[str, Any], tmp_path: Path) -> None:  # noqa: F811
    declared = {**rw.load_declared(), **rw.load_declared(JAPAN_ROWS)}
    rows = rw.judge_declared(run_walk(japan_box, tmp_path), declared)
    ours = [r for r in rows if r["path"].startswith(MEDIS)]
    assert len(ours) == 3
    bad = {(r["method"], r["path"], n): c["verdict"] for r in ours for n, c in r["cells"].items()
           if c["verdict"] in (rw.ALLOWED_X, rw.REFUSED_X)}  # fmt: skip
    assert not bad, bad
    # the cells the walk cannot judge are those of the neighbour POST /site/codes (role_walk_unclear.txt): a
    # study-scoped coordinator's 404 (site-wide data, D-179) and the empty walk body refused with its code (422)
    assert unclear_now(ours) == {
        f"{m} {MEDIS}{tail} {n}"
        for m, tail, cols in (
            ("GET", "", ("smo_in", "smo_out")),
            ("POST", "/check", NEIGHBOUR),
            ("POST", "/load", NEIGHBOUR),
        )
        for n in cols
    }
    assert tuple(sorted(x.rsplit(" ", 1)[1] for x in UNCLEAR.read_text(encoding="utf-8").splitlines()
                                     if x.startswith("POST /site/codes "))) == NEIGHBOUR  # fmt: skip


def test_who_may_use_the_medis_step_is_who_may_post_the_codes_page(japan_box: dict[str, Any]) -> None:  # noqa: F811
    walked = [(m, p, c) for m, p, c in rm.walk(japan_box) if p.startswith(MEDIS)]
    got = rm.parse(rm.render(walked))
    main = rm.parse(rm.TABLE.read_text(encoding="utf-8"))
    assert len(got) == 3
    # Y: let in and answered; U: let in, then 503 (the test box has no study store for the codes page): both "let in"
    let_in = {k: ("Y" if v == "U" else v) for k, v in main[("POST", "/site/codes")].items()}
    for (method, path), cells in got.items():
        assert cells == let_in, (method, path, cells)
