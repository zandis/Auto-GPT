"""9f-1 (D-1382, D-1391): the signed-in person's own delegation-log entries that are in force today.

One reader for the two pages that show them, the account page and the home page. It reads the person's own rows only
(``TeamStore.entries_for``): nobody else's entry is read, and it opens no route and shows no patient data."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
from typing import Any


def own_roles(team: Any, username: str, day: date, seen: Collection[str]) -> list[dict[str, Any]]:
    """One line per entry of ``username`` in force on ``day`` in a study of ``seen`` (study ids, upper case), with
    the ticked tasks (a sub-investigator's) and, from two weeks before the entry's last day, the days left (9f-4 a).
    ``team`` is the delegation store, or None where the box has none: then there is no line."""
    if team is None:
        return []
    return [
        {"rs": e.ruleset.upper(), "role": e.role, "tasks": e.tasks, "start": e.start, "end": e.end,
         "left": e.days_left(day)}
        for e in team.entries_for(username)
        if e.ruleset.upper() in seen and e.active_on(day)
    ]  # fmt: skip
