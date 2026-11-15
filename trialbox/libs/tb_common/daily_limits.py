"""D-507 (the owner's ruling of 2026-11-15): the daily limits are declared settings a VALIDATION box can lift;
PRODUCTION keeps today's values.

Two limits protect a box from runs and mail that read or reach everyone: the heavy jobs one sender may start in a day
(:data:`JOBS_DEFAULT`, D-146; ``tb_common.authz.daily_limit``) and the mails one recipient gets in a day
(:data:`MAIL_DEFAULT`, T-108c; the mail gateway). Each is a declared variable (``TB_JOBS_PER_SENDER_PER_DAY``,
``TB_MAIL_PER_RECIPIENT_PER_DAY``) that ``install.sh --answers`` can set; the jobs limit also keeps the site's
``settings.yaml`` values, which the variable overrides. 0 means no limit.

The one rule (:func:`applied`): on VALIDATION, TEST and DEV any value holds. On PRODUCTION, and on a site box with
``TB_ENV`` unset (``tb_common.config.environment_name``), a setting may lower a limit but never lift it: 0, or a value
above today's default, is not applied and today's value holds; :func:`refused_lifts` names it for ``doctor`` and the
services' logs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

JOBS_DEFAULT = 20  # heavy jobs one sender may start in 24 hours (D-146)
MAIL_DEFAULT = 200  # mails one recipient gets in 24 hours (T-108c)
JOBS_VAR = "TB_JOBS_PER_SENDER_PER_DAY"
MAIL_VAR = "TB_MAIL_PER_RECIPIENT_PER_DAY"
LIFTING = ("VALIDATION", "TEST", "DEV")  # the boxes on which a limit may be lifted (D-507)


def environment(env: Mapping[str, str]) -> str:
    from tb_common.config import environment_name

    return environment_name(env)


def may_lift(env: Mapping[str, str]) -> bool:
    return environment(env) in LIFTING


def applied(value: int, default: int, env: Mapping[str, str]) -> int:
    """The limit that holds for a set ``value`` (0 = no limit): any value where a lift is allowed; elsewhere the value
    only when it lowers the limit, else ``default``."""
    if may_lift(env):
        return value
    return value if 0 < value <= default else default


def _get(settings: Any, key: str) -> Any:
    """A field of the site's settings, as the services hold them (an object) or ``doctor`` does (a mapping)."""
    return settings.get(key) if isinstance(settings, Mapping) else getattr(settings, key, None)


def _int(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def jobs_per_sender(settings: Any, env: Mapping[str, str], command: str | None = None) -> int:
    """The heavy-job limit for ``command`` (0 = no limit): the declared variable, else the site file's per-type value,
    else its per-sender value, else :data:`JOBS_DEFAULT`; then :func:`applied`."""
    set_ = _int(env.get(JOBS_VAR))
    if set_ is None:
        per_type = dict(_get(settings, "rate_limits_per_day") or {})
        if command and command.upper() in per_type:
            set_ = int(per_type[command.upper()])
        else:
            raw = _get(settings, "rate_limit_per_sender_per_day")
            set_ = JOBS_DEFAULT if raw is None else int(raw)
    return applied(set_, JOBS_DEFAULT, env)


def mail_per_recipient(env: Mapping[str, str]) -> int:
    """The mail limit (0 = no limit): the declared variable, else :data:`MAIL_DEFAULT`; then :func:`applied`."""
    set_ = _int(env.get(MAIL_VAR))
    return applied(MAIL_DEFAULT if set_ is None else set_, MAIL_DEFAULT, env)


def refused_lifts(env: Mapping[str, str], settings: Any) -> list[str]:
    """The settings a box does not apply because they would lift a limit where that is not allowed (empty where it
    is), each as ``"<setting>: <value> (today's <default> holds)"``."""
    if may_lift(env):
        return []
    out = []
    jobs = _int(env.get(JOBS_VAR))
    if jobs is not None and not 0 < jobs <= JOBS_DEFAULT:
        out.append(f"{JOBS_VAR}: {jobs} (today's {JOBS_DEFAULT} holds)")
    raw = _get(settings, "rate_limit_per_sender_per_day")
    if jobs is None and raw is not None and not 0 < int(raw) <= JOBS_DEFAULT:
        out.append(f"rate_limit_per_sender_per_day: {raw} (today's {JOBS_DEFAULT} holds)")
    for cmd, n in sorted(dict(_get(settings, "rate_limits_per_day") or {}).items()):
        if jobs is None and not 0 < int(n) <= JOBS_DEFAULT:
            out.append(f"rate_limits_per_day.{cmd}: {n} (today's {JOBS_DEFAULT} holds)")
    mail = _int(env.get(MAIL_VAR))
    if mail is not None and not 0 < mail <= MAIL_DEFAULT:
        out.append(f"{MAIL_VAR}: {mail} (today's {MAIL_DEFAULT} holds)")
    return out
