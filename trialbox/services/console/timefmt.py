"""User-facing times in the site's time zone (D-108 follow-up).

Stores keep UTC ISO timestamps (aware, or naive meaning UTC). Pages, the screening log and exports show them
in ``site.tz`` (which also sets ``env.tz``), so a mark made at 07:00 in Tokyo reads 07:00, not 22:00 the day before.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


class SiteZoneError(ValueError):
    """The site's time zone is not set or is not a real zone: a configuration error, never a silent UTC (D-270)."""


def site_zone(backend: object) -> ZoneInfo:
    """The site's time zone (site.tz, which also sets env.tz) for user-facing times and the site's "today".

    A configured box always has one: ``tb_common.config.load`` refuses a settings file without a valid ``site.tz``.
    A name that is not a zone, or a configured backend with no zone at all, raises :class:`SiteZoneError` here (the
    console asks at start-up, so the box does not start) instead of reading UTC, which would move every date
    boundary by nine hours in Japan (D-270). Only a backend with no configuration at all (a test double) and no
    ``TB_TZ`` reads UTC.
    """
    cfg = getattr(backend, "cfg", None)
    site = getattr(getattr(getattr(cfg, "settings", None), "site", None), "tz", None)
    name = site or getattr(getattr(cfg, "env", None), "tz", None) or os.environ.get("TB_TZ")
    if not name:
        if cfg is None:
            return ZoneInfo("UTC")
        raise SiteZoneError("site.tz is not set: set site.tz in deploy/settings.yaml (for example Asia/Tokyo)")
    try:
        return ZoneInfo(str(name))
    except Exception as exc:
        raise SiteZoneError(f"site.tz={name!r} is not a valid IANA time zone (for example Asia/Tokyo)") from exc


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


def local_today(now: datetime, tz: ZoneInfo) -> date:
    """The site's calendar date at ``now`` (naive means UTC): what "today" is for a visit window (D-134)."""
    return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(tz).date()
