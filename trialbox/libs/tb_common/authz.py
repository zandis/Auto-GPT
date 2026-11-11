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
# T-512 (D-349, owner answer Q-04, finding FIT-003): the runs an investigator may start in one study. THE ONE PLACE
# THIS RULE LIVES: a different answer is a change to this table. "pi" is the study's logged PI (or, before the study's
# delegation log names one, any investigator of the study); "run" is a sub-investigator the PI ticked for the ``run``
# task. The daily limits of ``daily_limit`` hold for them as for every requester. Two empty sets give D-146's old
# rule back (the investigator approves; never a run).
INVESTIGATOR_RUNS: dict[str, frozenset[str]] = {
    "pi": frozenset({"FEAS", "SCREEN", "CASE"}),
    "run": frozenset({"FEAS", "SCREEN", "CASE"}),
}
_INVESTIGATOR = frozenset({"APPROVE", "STATUS"})  # the investigator approves the criteria (D-108)
ROLE_COMMANDS: dict[str, frozenset[str]] = {
    "admin": _PREPARE,
    "coordinator": _PREPARE,
    # the orchestrator's job authorisation table: the most the role may start in any study; the console adds the
    # study's delegation log on top (``can_request``)
    "investigator": _INVESTIGATOR | INVESTIGATOR_RUNS["pi"] | INVESTIGATOR_RUNS["run"],
}


def role_allowed(role: str, command: str) -> bool:
    """True when a console account with ``role`` may start ``command`` (viewer and CRO accounts start nothing)."""
    return command.upper() in ROLE_COMMANDS.get(role, frozenset())


def can_request(role: str, command: str, *, is_pi: bool = False, tasks: frozenset[str] = frozenset()) -> bool:
    """May a console account with ``role`` start ``command`` in one study (T-512, D-349)? ``is_pi`` and ``tasks``
    are the account's standing in that study (the delegation log, ``study_tasks``). Administrators and coordinators
    by the role table; an investigator by :data:`INVESTIGATOR_RUNS`: the PI by "pi", a sub-investigator only with
    the ``run`` tick."""
    cmd = command.upper()
    if role != "investigator":
        return role_allowed(role, cmd)
    if cmd in _INVESTIGATOR:
        return True
    if is_pi:
        return cmd in INVESTIGATOR_RUNS["pi"]
    return "run" in tasks and cmd in INVESTIGATOR_RUNS["run"]


# D-147: the study tasks of the delegation log (ICH E6): see candidates, mark Approach, ask a treating doctor, enter
# data. The role table gives each role its tasks in a study; for an investigator the study's delegation log decides:
# the logged PI has every task, a sub-investigator the ones the PI ticked, an investigator not on a log that names a PI
# none. Before a study's log names a PI, every investigator of the study acts as its PI with ``investigator``'s row.
# T-512 (D-349): ``run`` lets a sub-investigator start the runs of INVESTIGATOR_RUNS["run"] ("screen" only shows them).
STUDY_TASKS: tuple[str, ...] = ("screen", "approach", "refer", "enter_data", "run")
# D-280 (OD-5, CR-023): the administrator has no study task; one patient or one job only through break-glass.
ROLE_STUDY_TASKS: dict[str, frozenset[str]] = {
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


def edc_role_may(role: str, action: str) -> bool:
    """The orchestrator's own check of an EDC action (D-162, review E-01): the most this console role could ever do
    in a study. The console adds the delegation log on top (``edc_allowed`` with the person's study tasks)."""
    inv = role == "investigator"
    tasks = study_tasks(role, log_names_pi=False, is_pi=inv, ticked=frozenset())
    return edc_allowed(role, action, tasks=tasks, is_pi=inv)


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


# D-178 (review J-09, J-14): the administrator's operations screens (backups, update and rollback, logs, secrets
# status, the network sheet, the version) and the account actions. One table for the pages and ``/api/v1``: a role
# not listed has none of these actions. The steward, PI, CRC, viewer and CRO roles have no operations rights.
ADMIN_ACTIONS: tuple[str, ...] = (
    "ops.view",  # read the operations pages: version, backups, update history, logs, secrets status, network sheet
    "ops.backup",  # ask for a backup now (the host runs ``trialbox backup``)
    "ops.backup_check",  # check the newest backups without the key (complete, copies equal)
    "ops.update_check",  # verify a staged update bundle (``apply_update.sh --dry-run``): nothing changes
    "ops.update_apply",  # apply a staged, signed bundle (backup first, automatic rollback on failure)
    "ops.logs",  # collect yesterday's service logs (``trialbox logs collect``)
    "ops.network",  # write the network sheet again (``tools/network_sheet.py``)
    "account.reset",  # a new one-time password for an account
    "account.disable",  # disable an account
    "account.enable",  # enable a disabled account again (the undo of disable)
)
ROLE_ADMIN_ACTIONS: dict[str, frozenset[str]] = {"admin": frozenset(ADMIN_ACTIONS)}


def admin_allowed(role: str, action: str) -> bool:
    """True when a console account with ``role`` may take the operations or account ``action``."""
    return action in ROLE_ADMIN_ACTIONS.get(role, frozenset())


# D-191 (independent plan review PR-17): the SAE register. Deny by default: a role or an action not listed here may do
# nothing. Everyone listed reads the register (pseudonym, screening number, dates, parties; never the AE term); only
# the study's coordinator records a report sent, a receipt or a follow-up, because the sent date is written to the AE
# form (the data core) and only the coordinator enters trial data. The investigator still acknowledges on the
# participant page (D-143). Viewer and CRO (sponsor, monitor) accounts see nothing.
SAE_ACTIONS: tuple[str, ...] = ("view", "record")
# D-280 (OD-5, CR-023): the administrator reads no SAE row (patient-level); break-glass covers one patient or job.
ROLE_SAE_ACTIONS: dict[str, frozenset[str]] = {
    "coordinator": frozenset({"view", "record"}),
    "investigator": frozenset({"view"}),
}


def sae_allowed(role: str, action: str) -> bool:
    """True only when the role table above grants ``action`` on the SAE register to ``role``."""
    return action in SAE_ACTIONS and action in ROLE_SAE_ACTIONS.get(role, frozenset())


# D-280 (owner decision OD-5, CR-029): break-glass. The administrator sees patient data only through a grant: a reason
# from this list plus a written note, one patient or one job, 60 minutes, then it ends by itself. The console signs a
# reveal under a grant with :data:`BREAK_GLASS_ROLE`, never with ``admin``; the orchestrator gives a chart number to
# that role only (``orchestrator.app.ID_ROLES``). Every use is audited and waits on the steward's review list.
BREAK_GLASS_REASONS: tuple[str, ...] = ("support", "data_fix", "optout_request", "incident", "audit_request", "other")
BREAK_GLASS_MINUTES = 60
BREAK_GLASS_NOTE_MIN = 10  # the written "why" every grant needs, in characters
BREAK_GLASS_ROLE = "breakglass"  # a signed role is a-z only (tb_common.service_auth)
BREAK_GLASS_REVIEW_DAYS = 7  # the steward reviews each use within a week (owner question Q-20)
