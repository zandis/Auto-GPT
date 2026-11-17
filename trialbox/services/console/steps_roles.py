"""STEPS-ROLE (D-877, the owner's D-1063): the boot tool that opens one account per person on a test box.

    python -m console.steps_roles NAME ROLE,ROLE,... [NAME ROLE,ROLE,...] [--hours N] [--studies A,B] [--flag-on]

Each NAME is opened with the product's own one-time enrolment code (``UserStore.open_by_code``: a random password
nobody sees; the holder chooses the password at /enrol). The first role is the account's own role; the others are the
extra roles it may act in (``users.extra_roles``). A person who holds investigator or coordinator is written on each
study's delegation log under the user name (sub-investigator, else CRC; all four study tasks), as the demo VM's boot
does, so the standing follows the person whatever role they act in. ``--flag-on`` switches ``steps.acting_role`` on
(audited, actor ``console:steps-roles``). Refused unless ``TB_ENV`` is DEV or TEST, and for a name that exists.

Prints one tab-separated line per person: name, roles, code, expiry (UTC). The codes are shown once: the caller keeps
them where only the person can read them. Synthetic accounts on a test box only."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tb_common.flags import test_box

ACTOR = "console:steps-roles"
LOG_ROLE = {"investigator": "sub_pi", "coordinator": "crc"}  # the delegation log's role for a person who holds it


def open_people(users: Any, team: Any, people: Sequence[tuple[str, Sequence[str]]], studies: Sequence[str],
                hours: int, now: datetime | None = None) -> list[tuple[str, tuple[str, ...], str, str]]:  # fmt: skip
    """Open each (name, roles): (name, roles, code, expiry) per person. ``users``: a ``UserStore``; ``team``: a
    ``TeamStore`` (or None: no delegation log). Refused (``SystemExit``) off a test box or for an existing name."""
    if not test_box():
        raise SystemExit("steps_roles: extra roles are for a test box only (TB_ENV DEV or TEST)")
    when = now or datetime.now(UTC)
    users.enrol_ttl = timedelta(hours=hours)
    out = []
    for name, roles in people:
        if not roles:
            raise SystemExit(f"steps_roles: {name} needs at least one role")
        if users.role_of(name):
            raise SystemExit(f"steps_roles: an account {name} exists already")
        code = users.open_by_code(name, roles[0], f"{name}@hospa.test", "steps-roles")
        users.grant_roles(name, list(roles[1:]), allowed=True)
        log_role = next((LOG_ROLE[r] for r in ("investigator", "coordinator") if r in roles), None)
        for study in studies if (team is not None and log_role) else ():
            team.add_entry(study, username=name, name=name, role=log_role, tasks=list(_tasks()),
                           start=when.date().isoformat(), end=None, training_day=when.date().isoformat(),
                           training_ref="steps mode (synthetic)", by="steps-roles", at=when.isoformat())  # fmt: skip
        expires = (when + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M UTC")
        out.append((name, tuple(roles), code, expires))
    return out


def _tasks() -> tuple[str, ...]:
    from console.teamstore import TASKS

    return tuple(TASKS)


def flag_on(audit_dir: Path, reason: str) -> None:
    """Switch ``steps.acting_role`` on, audited (``Flags.set`` refuses off a test box)."""
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    flags = Flags(audit=AuditLog(audit_dir))
    if flags.get("steps.acting_role", "off") != "on":
        flags.set("steps.acting_role", "on", ACTOR, reason)


def _people(args: list[str]) -> list[tuple[str, tuple[str, ...]]]:
    if not args or len(args) % 2:
        raise SystemExit("usage: python -m console.steps_roles NAME ROLE,ROLE,... [NAME ROLE,ROLE,...]")
    return [(args[i].strip().lower(), tuple(r.strip() for r in args[i + 1].split(",") if r.strip()))
            for i in range(0, len(args), 2)]  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m console.steps_roles", description=__doc__.split("\n\n")[0])
    ap.add_argument("people", nargs="+", help="NAME ROLE,ROLE,... pairs (the first role is the account's own)")
    ap.add_argument("--hours", type=int, default=24, help="how long each one-time code lasts (1 to 72)")
    ap.add_argument("--studies", default="", help="the studies whose delegation log names the person (comma list)")
    ap.add_argument("--flag-on", action="store_true", help="switch steps.acting_role on (audited)")
    ap.add_argument("--reason", default="steps mode: one sign-in per person (D-1063)", help="the flag's reason")
    a = ap.parse_args(argv)
    if not 1 <= a.hours <= 72:
        raise SystemExit("steps_roles: --hours must be 1 to 72 (TB_CONSOLE_ENROL_CODE_HOURS)")
    if not test_box():
        raise SystemExit("steps_roles: extra roles are for a test box only (TB_ENV DEV or TEST)")
    from console.auth import UserStore
    from console.teamstore import TeamStore

    people = _people(list(a.people))
    studies = [s.strip() for s in a.studies.split(",") if s.strip()]
    users, team = UserStore(), TeamStore() if studies else None
    try:
        rows = open_people(users, team, people, studies, a.hours)
    finally:
        users.close()
        if team is not None:
            team.close()
    if a.flag_on:
        flag_on(Path(os.environ.get("TB_AUDIT_DIR") or "/data/audit"), a.reason)
    for name, roles, code, expires in rows:
        print(f"{name}\t{'+'.join(roles)}\t{code}\t{expires}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
