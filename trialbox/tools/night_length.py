"""How long the box's nights took, for a tool on the host (NEW-B-20, D-661). Standard library only.

    from tools.night_length import night_runs
    night_runs(Path("deploy"))  # [{"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"}, ...]

The adapter records every night in its lake (``adapter.night_runs``); the host's nightly backup copies that file to
``deploy/site/night-length.json``. This reads the copy: the nights that ended published on their first run (a night
run again, by day, measures the re-run), oldest first, each with its start and end in the site's time with its
offset. **An empty list means "not measured"** (no night yet, no backup run yet, a host that cannot read the box's
volumes), never "the night takes no time".

NEW-B-26 (D-667): ``start`` and ``end`` are the adapter's (the lake is published at ``end``). The box's night goes
on after that: the orchestrator derives, builds the twins and runs the night's screening, NAV and retention jobs.
When the orchestrator measured that work for the same night (``orchestrator.night_work``; the backup copies it into
the same file, key ``work``), the night's entry also carries ``work_start`` and ``work_end``. **A night without the
two keys: its work was not measured** (the chain did not end, a retry by day, a box without the scheduler), never
"no work after the publish".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

FILE = "night-length.json"


def night_runs(deploy: Path) -> list[dict[str, str]]:
    try:
        body = json.loads((deploy / "site" / FILE).read_text(encoding="utf-8"))
        nights = body["nights"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return []
    work: dict[str, dict[str, object] | None] = {}
    for w in _measured(body.get("work")):
        day = w.get("day")
        if isinstance(day, str):
            work[day] = None if day in work else w  # two answers for one night: neither is the night's
    out: list[tuple[datetime, dict[str, str]]] = []
    for n in _measured(nights):
        run = {"start": str(n["start"]), "end": str(n["end"])}
        snapshot = n.get("snapshot")
        mine = work.get(snapshot) if isinstance(snapshot, str) else None
        if mine is not None:
            run |= {"work_start": str(mine["start"]), "work_end": str(mine["end"])}
        out.append((datetime.fromisoformat(run["start"]), run))
    return [run for _, run in sorted(out, key=lambda x: x[0])]


def _measured(entries: object) -> list[dict[str, object]]:
    """The entries that measure a night: ended, on the night's first run, with a start and an end that carry their
    offsets and are in order."""
    out: list[dict[str, object]] = []
    for n in entries if isinstance(entries, list) else []:
        if not isinstance(n, dict) or n.get("finished") is not True or n.get("run", 1) != 1:
            continue  # not ended, or ended only when run again: a re-run's times are not the night's
        try:
            start, end = datetime.fromisoformat(str(n["start"])), datetime.fromisoformat(str(n["end"]))
        except (KeyError, ValueError):
            continue
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            continue  # a time without its offset, or an end before its start, measures nothing
        out.append(n)
    return out
