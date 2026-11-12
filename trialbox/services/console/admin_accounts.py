"""The administrator's remaining screens after PR #66 (T-209c, D-406; review ROLE-021, ROLE-022, OPS-059).

* **Backup and update tiles** on the ``/admin`` health tab: the newest backup's age and level, the last key check
  of a backup (``backup-verify``, T-209a's ``backup_verified`` check) and the last check run from the console; the
  last update and how it ended, the bundles waiting and the rollback points kept. Both link to ``/admin/ops``.
* **Links to the orphan pages** (ROLE-021): the Accounts tile names the locked accounts and links to
  ``/ops/identity`` (unlock, enrolment code, authenticator reset) and ``/ops/flags``; each row of ``/ops/users``
  links to its row on ``/ops/identity``. An administrator unlocks a colleague in two clicks from ``/admin``.
* **The unused-account report** (OPS-059) on ``/admin/accounts``: every active account not used for
  :data:`UNUSED_DAYS` days (or never, counted from its creation), every end date within :data:`ENDING_DAYS` days
  (or passed), and every local account with no end date. The administrators' health mail carries the same list on
  Mondays (``console.notify``): user names, roles and dates only, never a patient.
* **End dates** (OPS-059): a local account other than an administrator gets an end date at most
  :data:`MAX_END_DAYS` days ahead; an empty one is set to that limit (:func:`end_date`). An administrator's end date
  is optional (a box must keep one administrator) but has the same limit. Accounts from the identity provider
  follow the directory.

Administrators only: anyone else gets 403 and a ``console.denied`` audit event.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request, Response

from console import admin_i18n
from console.auth import AuthError, Session, User, is_operator
from console.home import Helpers
from console.i18n import CATALOGUES, translate

UNUSED_DAYS = 60  # no session for this long: on the report (OPS-059)
ENDING_DAYS = 14  # an end date this close: on the report
MAX_END_DAYS = 365  # a local account's end date is at most twelve months ahead
MAIL_WEEKDAY = 0  # Monday: the health mail carries the report

for _lang, _cat in (("en", admin_i18n.EN), ("ja", admin_i18n.JA), ("zh-TW", admin_i18n.ZH)):
    CATALOGUES[_lang].update(_cat)


def end_date(role: str, expires: str | None, today: date, *, sso: bool = False) -> str | None:
    """The end date an account is saved with (D-406, OPS-059). ``expires`` is already checked as YYYY-MM-DD
    (``console.auth.scope_values``). Raises AuthError for a date beyond the limit."""
    if sso:
        return expires
    limit = today + timedelta(days=MAX_END_DAYS)
    if expires is None:
        return None if is_operator(role) else limit.isoformat()
    if date.fromisoformat(expires) > limit:
        raise AuthError(f"the end date is at most {MAX_END_DAYS} days ahead ({limit.isoformat()} at the latest)")
    return expires


def _instant(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def report(
    users: Iterable[User],
    activity: Mapping[str, tuple[str, str | None]],
    sso: Iterable[str],
    now: datetime,
    today: date,
) -> dict[str, Any]:
    """The unused-account report: one row per active account that is unused, ending or has no end date."""
    now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    idp = set(sso)
    rows = []
    for u in users:
        created, last = activity.get(u.username, ("", None))
        since = _instant(last) or _instant(created)
        idle = int((now - since).total_seconds() // 86400) if since else None
        unused = idle is None or idle >= UNUSED_DAYS
        left = (date.fromisoformat(u.expires) - today).days if u.expires else None
        ending = left is not None and left <= ENDING_DAYS
        no_end = u.username not in idp and not u.is_admin and not u.expires
        if unused or ending or no_end:
            rows.append(
                {
                    "username": u.username,
                    "role": u.role,
                    "last": last or "",
                    "idle_days": idle,
                    "never": last is None,
                    "expires": u.expires or "",
                    "days_left": left,
                    "unused": unused,
                    "ending": ending,
                    "no_end": no_end,
                    "idp": u.username in idp,
                }
            )
    return {
        "rows": rows,
        "unused": sum(r["unused"] for r in rows),
        "ending": sum(r["ending"] for r in rows),
        "no_end": sum(r["no_end"] for r in rows),
        "today": today.isoformat(),
    }


def mail_lines(rep: Mapping[str, Any], lang: str) -> list[str]:
    """The report as plain lines for the Monday health mail: user names, roles and dates only."""
    out = [translate(lang, "accounts.mail.title", days=UNUSED_DAYS, ending=ENDING_DAYS)]
    if not rep["rows"]:
        return [*out, translate(lang, "accounts.mail.none")]
    for r in rep["rows"]:
        why = []
        if r["unused"]:
            why.append(
                translate(lang, "accounts.never")
                if r["never"]
                else translate(lang, "accounts.idle", days=r["idle_days"] if r["idle_days"] is not None else "?")
            )
        if r["ending"]:
            why.append(translate(lang, "accounts.ends", day=r["expires"], days=r["days_left"]))
        if r["no_end"]:
            why.append(translate(lang, "accounts.no_end"))
        out.append(f"- {r['username']} ({translate(lang, 'role.' + r['role'])}): {'; '.join(why)}")
    return out


def register(app: FastAPI, h: Helpers) -> None:
    au = h.au

    def need_admin(request: Request) -> Session:
        sess = h.need(request)
        if not sess.user.is_admin:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def accounts_report() -> dict[str, Any]:
        us = h.users
        users = us.users()
        return report(users, us.activity(), [u.username for u in users if us.is_sso(u.username)], h.clock(),
                      h.today())  # fmt: skip

    h.accounts_report = accounts_report

    def admin_extra(sess: Session) -> dict[str, Any]:
        """The health tab's backup, update and account facts (the template's ``backup``, ``update``, ``acc``)."""
        st = h.ops_status() if h.ops_status is not None else None
        sm = h.ops_summary() if h.ops_summary is not None else None
        try:
            hl = h.health() if h.health is not None else None
        except Exception:  # the health must never take the admin page down
            hl = None
        checks = {c.name: c for c in hl.checks} if hl is not None else {}
        backup = None
        if sm is not None or checks:
            b, v = checks.get("backup"), checks.get("backup_verified")
            backup = {
                "level": b.level if b else ("red" if (sm or {}).get("backup_red") else "ok"),  # T-209a's check
                # the age pill: red after 36 hours, as on /admin/ops (D-178)
                "red": bool((sm or {}).get("backup_red")) if sm is not None else (b is not None and b.level == "red"),
                "newest": (sm or {}).get("newest_backup") or "",
                "age_h": (sm or {}).get("backup_age_h"),
                "verified_level": v.level if v else "",
                "verified_days": int(v.value) if v and v.value is not None else None,
                "last_check": (sm or {}).get("last_check") or None,
            }
        update = None
        if st is not None:
            ups = list(st.get("updates") or [])
            update = {
                "last": ups[0] if ups else None,
                "staged": len(st.get("incoming") or []),
                "points": len(st.get("rollback_points") or []),
            }
        us = h.users
        locked = [u.username for u in us.users() if us.locked_until(u.username, None) is not None]
        rep = accounts_report()
        return {
            "backup": backup,
            "update": update,
            "acc": {"locked": locked, "unused": rep["unused"], "ending": rep["ending"], "no_end": rep["no_end"]},
        }

    h.admin_extra = admin_extra

    @app.get("/admin/accounts")
    def accounts_page(request: Request) -> Response:
        sess = need_admin(request)
        return h.page(
            request,
            "admin_accounts.html",
            sess,
            rep=accounts_report(),
            unused_days=UNUSED_DAYS,
            ending_days=ENDING_DAYS,
            max_days=MAX_END_DAYS,
        )
