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
from datetime import date, datetime, timedelta

from tb_common.timeutil import add_months

_COMMON = {"attachments_days": 90, "outputs_days": 365, "logs_days": 365, "nightly_snapshots": 3,
           "month_end_snapshots_months": 36, "pool_months_after_ruleset": 24, "audit_years": 10}  # fmt: skip
DEFAULTS: dict[str, dict[str, int]] = {
    "jp": {**_COMMON, "mail_log_days": 5 * 365},
    "tw": {**_COMMON, "mail_log_days": 7 * 365},
}
OVERRIDABLE = ("attachments_days", "outputs_days", "logs_days", "mail_log_days")


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


def snapshots_to_keep(snapshots: Iterable[str], today: date, nightly: int = 3, month_end_months: int = 36) -> set[str]:
    """Keep the last ``nightly`` snapshots plus the last snapshot of each of the last ``month_end_months`` completed
    months (the month-end history FEAS/COHORT use; the current month is covered by the nightly ones). Snapshot names
    are ISO dates."""
    snaps = sorted(set(snapshots))
    keep = set(snaps[-nightly:]) if nightly > 0 else set()
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
