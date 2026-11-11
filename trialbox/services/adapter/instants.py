"""One place where an inbound instant takes the site's offset (T-619a, STD-070).

The SQL engine reads a date-time's calendar date in the site zone (``lake.flatten``); CQL reads it in the value's own
offset (``date from``). For the adapter's own output the offsets are the site's, but a feed that states another one
(a FHIR bulk export in UTC, a CSV with ``Z`` time stamps) put an observation at 23:30 UTC on one day for CQL and on
the next for SQL. So every date-time with a time of day and an offset is written as the same instant in the site
zone before the snapshot is written: both engines then read the same day by construction. The instant never changes
(STD-015, T-616: the time and the instant are kept); only how its offset is written does. A date alone, or a
date-time without an offset, is left as it is (FHIR requires an offset with a time, so neither is an instant).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, tzinfo
from typing import Any

# a FHIR dateTime / instant with a time of day and an offset (or Z)
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$")


def site_instant(text: str, zone: tzinfo) -> str:
    """``text`` as the same instant in ``zone`` (``2026-04-07T23:30:00Z`` -> ``2026-04-08T07:30:00+08:00`` for
    Taipei); anything that is not a date-time with an offset, or already in the zone's offset, is returned as is."""
    m = _INSTANT.match(text)
    if not m:
        return text
    frac = m.group(2) or ""
    body = text[:-1] + "+00:00" if text.endswith("Z") else text
    if frac and len(frac) > 7:  # Python reads up to microseconds; FHIR allows more digits
        body = body.replace(frac, frac[:7], 1)
    try:
        when = datetime.fromisoformat(body)
    except ValueError:
        return text
    local = when.astimezone(zone)
    if local.utcoffset() == when.utcoffset():
        return text
    spec = "seconds" if not frac else ("milliseconds" if len(frac) <= 4 else "microseconds")
    if m.group(1) is None:
        spec = "minutes"
    return local.isoformat(timespec=spec)


def _walk(node: Any, zone: tzinfo) -> tuple[Any, int]:
    if isinstance(node, str):
        out = site_instant(node, zone)
        return out, int(out != node)
    if isinstance(node, dict):
        n = 0
        for k, v in node.items():
            node[k], d = _walk(v, zone)
            n += d
        return node, n
    if isinstance(node, list):
        n = 0
        for i, v in enumerate(node):
            node[i], d = _walk(v, zone)
            n += d
        return node, n
    return node, 0


def to_site_offset(resources: Iterable[dict[str, Any]], zone: tzinfo) -> int:
    """Rewrite, in place, every date-time with an offset in ``resources`` as the same instant in ``zone``. Returns how
    many values were rewritten (the ingest report shows it)."""
    total = 0
    for r in resources:
        _, n = _walk(r, zone)
        total += n
    return total
