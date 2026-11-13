"""How long the box's nights took (NEW-B-20, D-661): ``<lake>/night_runs.json``.

One entry per night whose snapshot the lake still keeps: the snapshot's date, when the night's run started and
ended (the site's time, with its offset), whether it ended published (``finished``) and when each publish step
ended. Times and step names only: no patient data. The host's nightly backup copies the file beside the box's
other records, where ``tools.night_length`` reads it (the doctor's ``update_window`` line, D-606).

How many nights are kept is not a number of this file's: an entry goes when the lake's retention removes its
snapshot. A night run again replaces its entry.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from adapter.ndjson import list_snapshots

log = logging.getLogger("adapter")
RECORD = "night_runs.json"


def _read(lake_dir: Path) -> list[dict[str, Any]]:
    try:
        nights = json.loads((lake_dir / RECORD).read_text(encoding="utf-8"))["nights"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return []
    if not isinstance(nights, list):
        return []
    return [n for n in nights if isinstance(n, dict) and isinstance(n.get("snapshot"), str)]


def _write(lake_dir: Path, nights: list[dict[str, Any]]) -> None:
    tmp = lake_dir / f".{RECORD}.tmp"
    tmp.write_text(json.dumps({"nights": nights}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(lake_dir / RECORD)


def record(
    lake_dir: Path,
    snapshot: str,
    start: datetime,
    end: datetime,
    *,
    finished: bool,
    steps_at: Any = None,
) -> None:
    """Write the night's entry. Never raises, whatever the file or the publish record holds: a record that cannot
    be written must not fail a night that ran.

    **The first finished run of a night is the night's measure and stays** (``run``: which run of the night it
    was). A night run again by day (a steward's re-run, a held re-run of the served night) would otherwise put a
    daytime interval, or "not finished", in the place of the night's own times. An entry that is not finished is
    replaced by the next run."""
    try:
        kept = set(list_snapshots(lake_dir)) | {snapshot}
        before = _read(lake_dir)
        mine = next((n for n in before if n["snapshot"] == snapshot), None)
        nights = [n for n in before if n["snapshot"] in kept and n["snapshot"] != snapshot]
        runs = int(mine.get("run") or 1) if mine else 0
        if mine is not None and mine.get("finished") is True:
            nights.append(mine)
        else:
            steps = steps_at if isinstance(steps_at, dict) else {}
            nights.append(
                {
                    "snapshot": snapshot,
                    "start": start.isoformat(timespec="seconds"),
                    "end": end.isoformat(timespec="seconds"),
                    "finished": bool(finished),
                    "run": runs + 1,
                    "steps_at": {str(k): str(v) for k, v in steps.items()},
                }
            )
        _write(lake_dir, sorted(nights, key=lambda n: str(n["snapshot"])))
    except Exception as exc:
        log.warning("the night's length was not recorded (%s): %s", RECORD, type(exc).__name__)
