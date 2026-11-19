"""When the box's last full night was (10B-20, D-1254): ``<lake>/full_nights.json``.

A delta night reads only a window, so some changes are not seen by it: a record the hospital re-files from one
patient to another, a chart merge followed by re-filing, an SS-MIX2 file back-filed with an old 発生日時 (D-1252
section D). The next **full** night reads everything and corrects them. This file says when that last was.

It holds the snapshot date of the last full night that completed (``last_full``) and the snapshot dates of the delta
nights that completed after it (``deltas``; the page says how many). A night *completes* when it ends published:
on its own run (:mod:`adapter.pipeline`), or when the steward accepts it while held (:func:`adapter.publish.
publish_held`). A night that fails, is refused, or ends held changes nothing. Dates only: no patient data.

A lake without the file (installed before this card) has no record: :func:`read` answers ``None`` and the page says
"not known", never a guess. The first completed delta night on such a lake writes ``last_full: null`` with that
night counted, so "not known" is said only once a delta night has run.

Written atomically (a temporary file, then a rename), beside the snapshots, as ``night_runs.json`` (D-661).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger("adapter")
RECORD = "full_nights.json"


def _day(value: Any) -> str | None:
    """``value`` when it is an ISO date, else None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat() if len(value) == 10 else None
    except ValueError:
        return None


def read(lake_dir: Path) -> dict[str, Any] | None:
    """The record as ``{"last_full": <date or None>, "deltas": [<dates>]}``; None when the lake has none, or when the
    file is not that shape (then nothing is said, and the next completed night writes it anew)."""
    try:
        raw = json.loads((lake_dir / RECORD).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError):
        log.warning("%s cannot be read; the page says nothing until a night completes", RECORD)
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("deltas"), list):
        return None
    last = raw.get("last_full")
    if last is not None and _day(last) is None:
        return None
    deltas = [_day(d) for d in raw["deltas"]]
    if any(d is None for d in deltas):
        return None
    return {"last_full": last, "deltas": sorted({str(d) for d in deltas})}


def said(lake_dir: Path) -> dict[str, Any] | None:
    """What a night's event carries for the data-operations page: ``{"last_full": <date or None>, "deltas": <n>}``,
    or None when the lake has no record."""
    rec = read(lake_dir)
    return None if rec is None else {"last_full": rec["last_full"], "deltas": len(rec["deltas"])}


def completed(lake_dir: Path, snapshot: str, *, full: bool) -> None:
    """A night of ``snapshot`` completed (it is published). A full night newer than the last (or the same night run
    again) becomes the last, and the delta nights it covers go; a delta night after the last full one is counted
    once (a night run again is not counted twice). An older night changes nothing. Never raises: a record that
    cannot be written must not fail a night that ran (it is logged)."""
    try:
        day = _day(snapshot)
        if day is None:
            return
        rec = read(lake_dir) or {"last_full": None, "deltas": []}
        last, deltas = rec["last_full"], set(rec["deltas"])
        if full:
            if last is not None and day < last:
                return
            last, deltas = day, {d for d in deltas if d > day}
        else:
            if last is not None and day <= last:
                return
            deltas.add(day)
        tmp = lake_dir / f".{RECORD}.tmp"
        tmp.write_text(json.dumps({"last_full": last, "deltas": sorted(deltas)}, indent=1) + "\n", encoding="utf-8")
        tmp.replace(lake_dir / RECORD)
    except Exception as exc:
        log.warning("the last full night was not recorded (%s): %s", RECORD, type(exc).__name__)
