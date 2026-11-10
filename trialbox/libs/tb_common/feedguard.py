"""How much of the hospital's data one night may remove (D-271).

A night whose feed would remove (nearly) all records of a kind is a missing or broken extract, not a hospital that
lost its patients overnight. The adapter (NDJSON snapshot against the last promoted one, every resource type) and the
OMOP loader (feed batch against the live records, every CDM table) refuse such a night; the box keeps serving the
previous snapshot.

* ``TB_FEED_MAX_DROP_PCT`` (default 20, 0..100): the share of a kind's records one night may remove. A removal of at
  most ``FLOOR`` records always passes (a small site deleting a few records is routine); removing every record of a
  kind never passes without an override.
* ``TB_FEED_DROP_OVERRIDE=<snapshot>: <reason>``: lets the night ``<snapshot>`` through (and only that night); the
  reason is recorded with the load (ingest audit, ``tb_load``). An override that names no snapshot is ignored.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

PCT_ENV = "TB_FEED_MAX_DROP_PCT"
OVERRIDE_ENV = "TB_FEED_DROP_OVERRIDE"
DEFAULT_PCT = 20.0
FLOOR = 5
# resource types the mapping writes on every night whatever the export holds (``static:`` rows): never evidence of data
STATIC_TYPES = frozenset({"Organization", "Practitioner", "PractitionerRole", "Location"})


class FeedGuardError(ValueError):
    """``TB_FEED_MAX_DROP_PCT`` is not a number from 0 to 100."""


def max_drop_pct() -> float:
    raw = (os.environ.get(PCT_ENV) or "").strip()
    if not raw:
        return DEFAULT_PCT
    try:
        pct = float(raw)
    except ValueError:
        raise FeedGuardError(f"{PCT_ENV}={raw!r}: give a number from 0 to 100") from None
    if not 0 <= pct <= 100:
        raise FeedGuardError(f"{PCT_ENV}={raw!r}: give a number from 0 to 100")
    return pct


def too_many(live: int, gone: int, pct: float) -> bool:
    """Whether removing ``gone`` of ``live`` records of one kind is more than one night may do."""
    if gone <= 0 or live <= 0:
        return False
    if gone >= live:
        return True
    return gone > FLOOR and gone * 100 > pct * live


def drops(live: Mapping[str, int], gone: Mapping[str, int], pct: float) -> list[str]:
    """The kinds whose removal is too large, as ``"<kind>: <gone> of <live>"``."""
    return [
        f"{k}: {gone.get(k, 0)} of {n}"
        for k, n in sorted(live.items())
        if k not in STATIC_TYPES and too_many(n, gone.get(k, 0), pct)
    ]


def override_for(snapshot: str) -> str:
    """The operator's reason for letting ``snapshot`` through, or "" (the override names another night, or none)."""
    raw = (os.environ.get(OVERRIDE_ENV) or "").strip()
    night, sep, reason = raw.partition(":")
    if not sep or night.strip() != snapshot or not reason.strip():
        return ""
    return reason.strip()
