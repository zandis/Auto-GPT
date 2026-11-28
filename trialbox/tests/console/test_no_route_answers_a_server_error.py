"""TRIAGE-1 G4 (RC9): no route answers a server error as any role. The role walk (``test_role_route_matrix``) walks
every console route as every role and compares the answers with the design table; a route that raised was written in
it as ``E`` and the table stayed equal to the walk after a regeneration (``TB_WRITE_ROLE_MATRIX=1``). This test holds
the class shut: the design table carries no ``E`` cell, and the walk itself answers none.

``U`` (503) stays the walk's word for a page whose service the walk's box does not run (no study store); the E2E's
fresh-box form (no EDC, no signature key, then a full disk) is the standing E2E gate's (G1) and the EDC pages' own
tests (P-12, P-14, P-24)."""

from __future__ import annotations

from typing import Any

from tests.console import test_role_route_matrix as rm
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name


def _errors(rows: dict[tuple[str, str], dict[str, str]]) -> list[str]:
    return [f"{m} {p} as {col}" for (m, p), cells in sorted(rows.items()) for col, c in cells.items() if c == "E"]


def test_the_design_table_carries_no_server_error() -> None:
    table = rm.parse(rm.TABLE.read_text(encoding="utf-8"))
    assert len(table) > 300
    assert _errors(table) == []


def test_the_walk_answers_no_server_error(box: dict[str, Any]) -> None:  # noqa: F811
    walked = {(m, p): cells for m, p, cells in rm.walk(box)}
    assert _errors(walked) == []
