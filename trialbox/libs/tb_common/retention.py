"""Retention rules (SPEC §10.3) as pure functions, shared by the orchestrator's daily RETENTION job and the adapter's
snapshot pruning, and the install defaults per country (D-138).

**Per log type** (settings.yaml ``retention``; RUNBOOK §2 "Logs"):

* service logs (``logs_days``): the containers' JSON logs, size-capped by compose (50 MB x 5 per container) and
  collected every night on the host into ``TB_LOG_DIR/services/<day>/`` (``trialbox logs daily``), deleted after
  ``logs_days``. They hold pseudonyms only (``tb_common.logging`` scrubs IDs, phones and chart numbers).
* audit (``audit_years``): the hash-chained log is never deleted. Every night each closed day file is copied,
  compressed and verified, to ``TB_AUDIT_ARCHIVE_DIR`` (the hospital share); the box keeps its own copy.
* mail logs (``mail_log_days``): the mail gateway's intake and sent tables and the console's morning-mail log; the
  daily RETENTION job deletes older rows (an unfinished send is never deleted). The audit chain keeps every mail event.
* job outputs (``outputs_days``) and inbound attachments (``attachments_days``): the daily RETENTION job (D-78).
  A study's files are held while it runs (D-765) and, after the close, for the study's own period (D-779,
  :func:`held_after_close`): the trial office gives the years on the close form, prefilled with
  :data:`STUDY_YEARS_AFTER_CLOSE`.

**Defaults** (``DEFAULTS``, chosen at install from the site's country; every value can be changed in the answers).
Taiwan: 資通安全責任等級分級辦法 asks that logs be kept at least six months, and 醫療法 §70 keeps medical records
seven years; Japan: 医療情報システムの安全管理に関するガイドライン 第7.0版 asks for access logs kept and
reviewed with no fixed period, and 医師法 §24 keeps the 診療録 five years. So service logs one year in both
(twice the Taiwan minimum, and the year hospitals in both countries usually ask for), mail logs as long as the
medical record (five years in Japan, seven in Taiwan), and the audit chain ten years on the box and for ever in the
archive (the security review of 2026-11-08, §6 questions 5 and 25). These are defaults to discuss with the hospital's
information-security officer, not legal advice.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, tzinfo

from tb_common.timeutil import add_months

_COMMON = {"attachments_days": 90, "outputs_days": 365, "logs_days": 365, "nightly_snapshots": 3,
           "month_end_snapshots_months": 36, "pool_months_after_ruleset": 24, "audit_years": 10}  # fmt: skip
DEFAULTS: dict[str, dict[str, int]] = {
    "jp": {**_COMMON, "mail_log_days": 5 * 365},
    "tw": {**_COMMON, "mail_log_days": 7 * 365},
}
OVERRIDABLE = ("attachments_days", "outputs_days", "logs_days", "mail_log_days")
# D-779 (T-305c): how many years a closed study's files, pool and marks are kept after the close when the close names
# no period (a close recorded before the period was asked). Japan's 臨床研究法施行規則 keeps a study's records five
# years from its end; a sponsor's contract often asks longer, which the trial office gives per study (1 to 30). A
# default to discuss with the trial office, not legal advice.
STUDY_YEARS_AFTER_CLOSE = 5
STUDY_YEARS_MAX = 30


def kept_until(closed_at: str, years: int | None, zone: tzinfo | None = None) -> date:
    """D-779: the day a closed study's files stop being held: the close's own day plus ``years`` (the default when
    None). A close on 29 February ends on the 28th in a year with none. ``zone``: the site's, so the close's day is
    the site's (WALK-1, F-16: an instant stored in UTC is a day early in the evening UTC); None: the instant's own."""
    when = datetime.fromisoformat(closed_at)
    if zone is not None and when.tzinfo is not None:
        when = when.astimezone(zone)
    return add_months(when.date(), 12 * (years or STUDY_YEARS_AFTER_CLOSE))


def held_after_close(closed_at: str, years: int | None, now: datetime) -> bool:
    """D-779: whether a study closed at ``closed_at`` still holds its files on ``now``'s day; both days are read in
    ``now``'s zone (the site's, where ``now`` is the site's time)."""
    return now.date() < kept_until(closed_at, years, now.tzinfo)


def defaults_for(country: str, overrides: dict[str, object] | None = None) -> dict[str, int]:
    """The retention block for ``jp`` or ``tw``, with the site's own numbers where given (days, at least 1)."""
    if country not in DEFAULTS:
        raise ValueError(f"retention rules {country!r}: jp or tw")
    out = dict(DEFAULTS[country])
    for k in OVERRIDABLE:
        v = (overrides or {}).get(k)
        if v not in (None, ""):
            n = int(str(v))
            if n < 1:
                raise ValueError(f"{k} must be at least 1 day")
            out[k] = n
    return out


def site_own(overrides: dict[str, object] | None) -> dict[str, int]:
    """10K-1: the retention block of a site whose country has no rules here (neither ``jp`` nor ``tw``): each of
    :data:`OVERRIDABLE` must be given by the site; the rest (snapshots, the pool, the audit years) is the box's own
    and the same in both rule sets. Raises ``ValueError`` naming the days not given."""
    missing = [k for k in OVERRIDABLE if (overrides or {}).get(k) in (None, "")]
    if missing:
        raise ValueError(
            "no retention rules for this country in TrialBox (only jp and tw): answer retention_rules, or give "
            + ", ".join(missing)
        )
    out = dict(_COMMON)
    for k in OVERRIDABLE:
        n = int(str((overrides or {})[k]))
        if n < 1:
            raise ValueError(f"{k} must be at least 1 day")
        out[k] = n
    return out


def snapshots_to_keep(
    snapshots: Iterable[str],
    today: date,
    nightly: int = 3,
    month_end_months: int = 36,
    good: Iterable[str] | None = None,
) -> set[str]:
    """Keep the last ``nightly`` snapshots plus the last snapshot of each of the last ``month_end_months`` completed
    months (the month-end history FEAS/COHORT use; the current month is covered by the nightly ones). Snapshot names
    are ISO dates.

    ``good`` (T-611, DATA-001): the snapshots whose night passed. When given, only they count: the last ``nightly``
    good ones and each month's last good one are kept, so held nights never push a good snapshot out; a held night
    newer than the oldest kept good one stays for the steward, an older one goes."""
    every = sorted(set(snapshots))
    snaps = every if good is None else sorted(set(good) & set(every))
    keep = set(snaps[-nightly:]) if nightly > 0 else set()
    if good is not None and keep:
        keep |= {s for s in every if s > min(keep) and s not in snaps}
    this_month = today.replace(day=1)
    oldest = add_months(this_month, -month_end_months)
    by_month: dict[str, str] = {}
    for s in snaps:
        d = date.fromisoformat(s)
        if oldest <= d < this_month:
            by_month[s[:7]] = max(by_month.get(s[:7], s), s)
    keep |= set(by_month.values())
    return keep


def expired(last_modified: datetime, now: datetime, days: int) -> bool:
    return days > 0 and last_modified < now - timedelta(days=days)
