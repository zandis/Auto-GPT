"""9f-1 (D-1382, D-1391): the signed-in person's own delegation-log entries that are in force today.

One reader for the two pages that show them, the account page and the home page. It reads the person's own rows only
(``TeamStore.entries_for``): nobody else's entry is read, and it opens no route and shows no patient data."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date
from typing import Any


def own_roles(
    team: Any, username: str, day: date, seen: Collection[str], order: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """One line per entry of ``username`` in force on ``day`` in a study of ``seen`` (study ids, upper case), with
    the ticked tasks (a sub-investigator's) and, from two weeks before the entry's last day, the days left (9f-4 a).
    ``team`` is the delegation store, or None where the box has none: then there is no line. ``order`` (study ids, upper
    case) puts the lines in the order a page lists its studies; a study not in it, and the lines of one study, keep the
    log's order."""
    if team is None:
        return []
    lines = [
        {"rs": e.ruleset.upper(), "role": e.role, "tasks": e.tasks, "start": e.start, "end": e.end,
         "left": e.days_left(day)}
        for e in team.entries_for(username)
        if e.ruleset.upper() in seen and e.active_on(day)
    ]  # fmt: skip
    rank = {rs: i for i, rs in enumerate(order)}
    return sorted(lines, key=lambda ln: rank.get(ln["rs"], len(rank)))
