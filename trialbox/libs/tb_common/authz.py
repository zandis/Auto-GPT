"""Command authorisation (SPEC §10.1 "Users: none"): sender address + ``settings.permissions``."""

from __future__ import annotations

from tb_contracts import Settings


def norm(addr: str) -> str:
    return addr.strip().strip("<>").lower()


def group_members(settings: Settings, group: str) -> set[str]:
    al = settings.allowlist
    groups: dict[str, list[str]] = {
        "senders": list(al.senders),
        "physicians": list(al.physicians or []),
        "alliance_sites": list(al.alliance_sites or []),
        "reviewers": list(settings.reviewers or []),
    }
    if "@" in group:
        return {norm(group)}
    return {norm(a) for a in groups.get(group, [])}


def known_senders(settings: Settings) -> set[str]:
    out: set[str] = set()
    for g in ("senders", "physicians", "alliance_sites", "reviewers"):
        out |= group_members(settings, g)
    for groups in settings.permissions.values():
        for g in groups:
            if "@" in g:
                out.add(norm(g))
    return out


# commands without a ``permissions`` entry: the ``senders`` group, except these (a site file written before the command
# existed must not open it to every sender)
DEFAULT_GROUPS: dict[str, list[str]] = {"RELEASE": ["reviewers"]}


def allowed(settings: Settings, command: str, sender: str) -> bool:
    """True when ``sender`` may issue ``command``; commands without an entry default to :data:`DEFAULT_GROUPS`, else
    the ``senders`` group."""
    who = norm(sender)
    groups = settings.permissions.get(command) or DEFAULT_GROUPS.get(command) or ["senders"]
    return any(who in group_members(settings, g) for g in groups)


# D-144 (review J-01): a request made on the console is authorised by the signed-in person's role (the console's
# signed actor assertion carries it), not by a sender mailbox in settings.yaml. A mailed request keeps the mailbox rule
# above. The console checks the same roles before it asks (console.auth.User.can_request / can_approve).
_PREPARE = frozenset(
    {"FEAS", "SCREEN", "COHORT", "NAV", "MICROBATCH", "STATUS", "CANCEL", "CONSENT", "RELEASE", "CASE", "FEEDBACK"}
)
ROLE_COMMANDS: dict[str, frozenset[str]] = {
    "admin": _PREPARE,
    "coordinator": _PREPARE,
    "investigator": frozenset({"APPROVE", "STATUS"}),  # the investigator approves the criteria (D-108); never a run
}


def role_allowed(role: str, command: str) -> bool:
    """True when a console account with ``role`` may start ``command`` (viewer and CRO accounts start nothing)."""
    return command.upper() in ROLE_COMMANDS.get(role, frozenset())


# D-144 (review J-02): the daily per-sender limit protects the box from runs that read every patient. It counts only
# these job types, each on its own; a case question, a consent draft, a status or an approval is never counted.
HEAVY_JOBS: tuple[str, ...] = ("FEAS", "SCREEN", "COHORT", "NAV", "MICROBATCH", "CALIBRATION")


def daily_limit(settings: Settings, command: str) -> int | None:
    """Jobs of type ``command`` one sender may start in 24 hours: ``rate_limits_per_day[command]`` when set, else
    ``rate_limit_per_sender_per_day`` for a heavy job type; None (no limit) for the others and for a limit of 0."""
    cmd = command.upper()
    per_type = dict(settings.rate_limits_per_day or {})
    if cmd in per_type:
        n = int(per_type[cmd])
    elif cmd in HEAVY_JOBS:
        n = int(settings.rate_limit_per_sender_per_day or 20)
    else:
        return None
    return n if n > 0 else None
