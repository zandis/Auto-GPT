"""T-716 (D-484), review L1: the orchestrator reads the delegation log with its own copy of the rule
(``orchestrator.grants.log_standing``); the console's is ``console.team.standing``. This holds the two to each
other on the question the orchestrator asks: may this investigator receive a chart number by their own rights?
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from console.team import standing
from console.teamstore import TeamStore
from orchestrator import grants

DAY = date(2026, 11, 12)
RS = "GZQO"


def _entry(team: TeamStore, username: str, role: str, tasks: tuple[str, ...] = (), start: date = date(2026, 1, 1),
           end: date | None = None, rs: str = RS) -> None:  # fmt: skip
    team.add_entry(rs, username=username, name=username, role=role, tasks=tasks, start=start.isoformat(),
                   end=end.isoformat() if end else None, training_day="2025-06-01", training_ref=None,
                   by="stw-setup", at="2026-01-01T00:00:00+00:00")  # fmt: skip


CASES: dict[str, list[dict[str, Any]]] = {
    "the log names nobody": [],
    "the PI": [{"username": "drsato", "role": "pi"}],
    "another person is the PI": [{"username": "drkato", "role": "pi"}],
    "a PI whose entry ended yesterday": [{"username": "drsato", "role": "pi", "end": DAY - timedelta(days=1)}],
    "a PI whose entry starts tomorrow": [{"username": "drsato", "role": "pi", "start": DAY + timedelta(days=1)}],
    "the PI of another study": [{"username": "drsato", "role": "pi", "rs": "RA-BIO"}],
    "a sub-investigator with the screen tick": [
        {"username": "drkato", "role": "pi"}, {"username": "drsato", "role": "sub_pi", "tasks": ("screen",)}],
    "a sub-investigator without it": [
        {"username": "drkato", "role": "pi"}, {"username": "drsato", "role": "sub_pi", "tasks": ("refer",)}],
    "a sub-investigator whose PI left": [
        {"username": "drkato", "role": "pi", "end": DAY - timedelta(days=1)},
        {"username": "drsato", "role": "sub_pi", "tasks": ("screen",)}],
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_orchestrator_and_the_console_read_the_log_alike(case: str) -> None:
    team = TeamStore()  # the test's own trial database (tests/conftest.py)
    try:
        for e in CASES[case]:
            _entry(team, **e)
        user = SimpleNamespace(username="drsato", role="investigator", aggregate_only=False,
                               sees_study=lambda rs: True)  # fmt: skip
        mine = standing(team, user, RS, DAY).grant()  # type: ignore[arg-type]
    finally:
        team.close()
    theirs = grants.log_standing("drsato", RS, DAY)
    assert (theirs.is_pi, theirs.log_names_pi) == (mine.is_pi, mine.log_names_pi), case
    assert grants.own_right("investigator", theirs) == grants.own_right("investigator", mine), case
