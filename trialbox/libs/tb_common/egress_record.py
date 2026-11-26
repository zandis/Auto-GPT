"""M3: the egress record (10G-49): one audit line per departure or refusal, no identifier and no content.

The audit log is the record (append-only, chained, signed): no second store. :func:`by_day` is the page's reading.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

EVENT = "egress.leave"
FIELDS = frozenset(("route", "destination", "kind", "items", "rule", "size", "sha256", "result", "reason"))


def write(audit: Any, *, actor: str, **fields: Any) -> None:
    """One line. ``items`` None is written as ``unknown``, never 0. A destination is a host, a mail domain or
    ``download``: never a person."""
    if set(fields) != FIELDS:
        raise ValueError("the egress record's fields are fixed")
    if "@" in str(fields["destination"]):
        raise ValueError("a destination names no person")
    detail = {**fields, "items": "unknown" if fields["items"] is None else fields["items"]}
    # the payload's hash stands where every audited file's does: two reads of one file that holds its own time differ
    # there and nowhere else
    audit.append(EVENT, actor=actor or "unknown", output_sha=detail.pop("sha256"), detail=detail)


def by_day(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Audit events as rows of day, route, result and reason with their counts, newest day first."""
    n: Counter[tuple[str, str, str, str]] = Counter()
    for e in events:
        if e.get("event") == EVENT:
            d = e.get("detail") or {}
            n[str(e.get("ts", ""))[:10], str(d.get("route")), str(d.get("result")), str(d.get("reason") or "")] += 1
    rows = [{"day": k[0], "route": k[1], "result": k[2], "reason": k[3], "count": v} for k, v in sorted(n.items())]
    return sorted(rows, key=lambda r: str(r["day"]), reverse=True)
