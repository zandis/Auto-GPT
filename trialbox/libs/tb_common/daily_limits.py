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


def _heavy() -> tuple[str, ...]:
    from tb_common.authz import HEAVY_JOBS

    return HEAVY_JOBS


def site_jobs(settings: Any, env: Mapping[str, str], command: str) -> int:
    """The site's own limit for ``command`` (0 = none), from ``settings.yaml``: a heavy type's per-type value, else the
    per-sender value, else :data:`JOBS_DEFAULT`, through :func:`applied`. A type not counted by default (CASE,
    CONSENT, STATUS) has the per-type value the site gave it, as it is: any value is a new limit, never a lift."""
    cmd = command.upper()
    per_type = dict(_get(settings, "rate_limits_per_day") or {})
    if cmd not in _heavy():
        return int(per_type.get(cmd) or 0)
    if cmd in per_type:
        return applied(int(per_type[cmd]), JOBS_DEFAULT, env)
    raw = _get(settings, "rate_limit_per_sender_per_day")
    return applied(JOBS_DEFAULT if raw is None else int(raw), JOBS_DEFAULT, env)


def jobs_per_sender(settings: Any, env: Mapping[str, str], command: str = "FEAS") -> int:
    """The limit for ``command`` (0 = none). ``TB_JOBS_PER_SENDER_PER_DAY`` applies to the heavy types only. Where a
    lift is allowed it replaces the site's value; elsewhere it may only lower the site's own limit for that type (a
    site that lowered FEAS to 3 keeps 3 whatever the variable says)."""
    cmd = command.upper()
    site = site_jobs(settings, env, cmd)
    var = _int(env.get(JOBS_VAR))
    if cmd not in _heavy() or var is None:
        return site
    if may_lift(env):
        return var
    return var if 0 < var <= site else site


def mail_per_recipient(env: Mapping[str, str]) -> int:
    """The mail limit (0 = no limit): the declared variable, else :data:`MAIL_DEFAULT`; then :func:`applied`."""
    set_ = _int(env.get(MAIL_VAR))
    return applied(MAIL_DEFAULT if set_ is None else set_, MAIL_DEFAULT, env)


def malformed(env: Mapping[str, str]) -> list[str]:
    """The limit variables set to something that is not a whole number: they are ignored (the site's value and the
    defaults hold), and said (``doctor`` FAILs, the services log it)."""
    out = []
    for name in (JOBS_VAR, MAIL_VAR):
        raw = (env.get(name) or "").strip()
        if raw and _int(raw) is None:
            out.append(f"{name}: {raw[:20]!r} is not a whole number (ignored)")
    return out


def refused_lifts(env: Mapping[str, str], settings: Any) -> list[str]:
    """The settings a box does not apply because they would lift a limit where that is not allowed (empty where it
    is), each as ``"<setting>: <value> (... holds)"``; a malformed variable too (:func:`malformed`)."""
    out = malformed(env)
    if may_lift(env):
        return out
    raw = _get(settings, "rate_limit_per_sender_per_day")
    if raw is not None and not 0 < int(raw) <= JOBS_DEFAULT:
        out.append(f"rate_limit_per_sender_per_day: {raw} (today's {JOBS_DEFAULT} holds)")
    per_type = dict(_get(settings, "rate_limits_per_day") or {})
    for cmd, n in sorted(per_type.items()):
        if cmd.upper() in _heavy() and not 0 < int(n) <= JOBS_DEFAULT:
            out.append(f"rate_limits_per_day.{cmd}: {n} (today's {JOBS_DEFAULT} holds)")
    var = _int(env.get(JOBS_VAR))
    if var is not None:
        above = [c for c in _heavy() if not 0 < var <= site_jobs(settings, env, c)]
        if above:
            lowest = min(site_jobs(settings, env, c) for c in above)
            out.append(f"{JOBS_VAR}: {var} (the site's own limit holds, {lowest} for {', '.join(above)})")
    mail = _int(env.get(MAIL_VAR))
    if mail is not None and not 0 < mail <= MAIL_DEFAULT:
        out.append(f"{MAIL_VAR}: {mail} (today's {MAIL_DEFAULT} holds)")
    return out


def summary(settings: Any, env: Mapping[str, str]) -> str:
    """The limits that hold, for ``doctor``'s PASS line."""
    jobs = ", ".join(f"{c} {jobs_per_sender(settings, env, c) or 'no limit'}" for c in _heavy())
    return f"a sender a day: {jobs}; mail a recipient a day: {mail_per_recipient(env) or 'no limit'}"
