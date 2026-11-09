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


# D-146 (review J-01): a request made on the console is authorised by the signed-in person's role (the console's
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


# D-147: the study tasks of the delegation log (ICH E6): see candidates, mark Approach, ask a treating doctor, enter
# data. The role table gives each role its tasks in a study; for an investigator the study's delegation log decides:
# the logged PI has every task, a sub-investigator the ones the PI ticked, an investigator not on a log that names a PI
# none. Before a study's log names a PI, every investigator of the study acts as its PI with ``investigator``'s row.
STUDY_TASKS: tuple[str, ...] = ("screen", "approach", "refer", "enter_data")
ROLE_STUDY_TASKS: dict[str, frozenset[str]] = {
    "admin": frozenset({"screen"}),
    "coordinator": frozenset({"screen", "enter_data"}),
    "investigator": frozenset({"screen", "approach", "refer"}),  # until the study's log names its PI
}


def study_tasks(role: str, *, log_names_pi: bool, is_pi: bool, ticked: frozenset[str]) -> frozenset[str]:
    """The tasks a console account with ``role`` has in one study, given the study's delegation log."""
    if role != "investigator" or not log_names_pi:
        return ROLE_STUDY_TASKS.get(role, frozenset())
    return frozenset(STUDY_TASKS) if is_pi else frozenset(ticked) & frozenset(STUDY_TASKS)


# D-160: EDC prefill. Who may do what, on top of the study tasks above. The prefill path is data entry (the
# ``enter_data`` task: a coordinator, the PI, a sub-investigator the PI ticked for it); turning prefill on is the
# study PI's alone (they hold the sponsor's acknowledgement); turning it off is the PI's or an admin's (stop at once).
# A viewer, a CRO account and anyone without the task do nothing here.
EDC_ACTIONS: tuple[str, ...] = ("view", "map", "draft", "review", "sign", "send", "export", "switch_on", "switch_off")


def edc_allowed(role: str, action: str, *, tasks: frozenset[str], is_pi: bool) -> bool:
    """May an account with ``role`` (and these study tasks) take this EDC prefill ``action`` in one study?"""
    if action not in EDC_ACTIONS or role in ("viewer", "cro"):
        return False
    if action == "switch_on":
        return role == "investigator" and is_pi
    if action == "switch_off":
        return (role == "investigator" and is_pi) or role == "admin"
    if action == "view":
        return "enter_data" in tasks or (role == "investigator" and is_pi)
    return "enter_data" in tasks


# D-146 (review J-02): the daily per-sender limit protects the box from runs that read every patient. It counts only
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
