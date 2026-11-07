"""User-facing times in the site's time zone (D-108 follow-up).

Stores keep UTC ISO timestamps (aware, or naive meaning UTC). Pages, the screening log and exports show them
in ``site.tz`` (which also sets ``env.tz``), so a mark made at 07:00 in Tokyo reads 07:00, not 22:00 the day before.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def site_zone(backend: object) -> ZoneInfo:
    """The site's time zone (site.tz, which also sets env.tz) for user-facing times; UTC if unknown."""
    cfg = getattr(backend, "cfg", None)
    site = getattr(getattr(getattr(cfg, "settings", None), "site", None), "tz", None)
    name = site or getattr(getattr(cfg, "env", None), "tz", None) or os.environ.get("TB_TZ") or "UTC"
    try:
        return ZoneInfo(str(name))
    except Exception:
        return ZoneInfo("UTC")


def local_time(value: object, tz: ZoneInfo, n: int = 16) -> str:
    """Show a stored ISO timestamp in the site's time zone (D-108 follow-up).

    Stored times are UTC (aware, or naive meaning UTC). n = 10 date, 16 minutes, 19 seconds.
    A plain date or anything unparseable is shown as stored.
    """
    if value is None or value == "":
        return ""
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    if len(text) <= 10:
        return text[:n]
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:n].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).isoformat(sep=" ")[:n]


def local_date(value: object, tz: ZoneInfo) -> str:
    """The site-local calendar date (YYYY-MM-DD) of a stored timestamp."""
    return local_time(value, tz, 10)
