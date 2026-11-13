"""How long the box's nights took, for a tool on the host (NEW-B-20, D-661). Standard library only.

    from tools.night_length import night_runs
    night_runs(Path("deploy"))  # [{"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"}, ...]

The adapter records every night in its lake (``adapter.night_runs``); the host's nightly backup copies that file to
``deploy/site/night-length.json``. This reads the copy: the nights that ended published on their first run (a night
run again, by day, measures the re-run), oldest first, each with its start and end in the site's time with its
offset. **An empty list means "not measured"** (no night yet, no backup run yet, a host that cannot read the box's
volumes), never "the night takes no time".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

FILE = "night-length.json"


def night_runs(deploy: Path) -> list[dict[str, str]]:
    try:
        nights = json.loads((deploy / "site" / FILE).read_text(encoding="utf-8"))["nights"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return []
    out: list[tuple[datetime, dict[str, str]]] = []
    for n in nights if isinstance(nights, list) else []:
        if not isinstance(n, dict) or n.get("finished") is not True or n.get("run", 1) != 1:
            continue  # not published, or published only when run again: a re-run's times are not the night's
        try:
            start, end = datetime.fromisoformat(str(n["start"])), datetime.fromisoformat(str(n["end"]))
        except (KeyError, ValueError):
            continue
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            continue  # a time without its offset, or an end before its start, measures nothing
        out.append((start, {"start": str(n["start"]), "end": str(n["end"])}))
    return [run for _, run in sorted(out, key=lambda x: x[0])]
