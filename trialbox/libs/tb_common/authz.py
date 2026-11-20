"""Authorisation. Mailed commands (SPEC §10.1 "Users: none"): sender address + ``settings.permissions``. Console
accounts: one permission function, :func:`permit`, over the matrix ``authz_matrix.yaml`` (T-102a, D-366)."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path

import yaml
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


# ---------------------------------------------------------------------------------------------- the permission matrix
# T-102a (D-366): one permission function. ``authz_matrix.yaml`` (next to this file) holds every console role x every
# action as data; :func:`permit` is the only function that reads it. The helpers below it (``can_request``,
# ``role_allowed``, ``study_tasks``, ``edc_allowed``, ``edc_role_may``, ``sae_allowed``, ``admin_allowed``) and the role
# properties of ``console.auth.User`` are thin wrappers over ``permit``; their tables (``ROLE_COMMANDS``,
# ``INVESTIGATOR_RUNS``, ``ROLE_STUDY_TASKS``, ``ROLE_SAE_ACTIONS``, ``ROLE_ADMIN_ACTIONS``) are read from the matrix at
# import, for the callers that list them. ``study_tasks``, ``edc_allowed`` and ``edc_role_may`` are deprecated: a test
# fails when a new module calls them (``tests/unit/test_authz_matrix.py``); new code calls ``permit``.
MATRIX_PATH = Path(__file__).with_name("authz_matrix.yaml")
CONDITIONS: tuple[str, ...] = ("pi", "logged_pi", "logged_tick", "unlogged", "monitor")  # plus "task:<t>"
# D-147: the study tasks of the delegation log (ICH E6): see candidates, mark Approach, ask a treating doctor, enter
# data; T-512 (D-349): ``run`` lets a sub-investigator start the runs that say ``task:run`` ("screen" only shows them).
STUDY_TASKS: tuple[str, ...] = ("screen", "approach", "refer", "enter_data", "run")


class MatrixError(ValueError):
    """``authz_matrix.yaml`` breaks a rule of its header: the service does not start with a broken matrix."""


@dataclass(frozen=True)
class Standing:
    """An account's standing in one study, from the study's delegation log (the console reads it; ``permit`` only
    looks). ``is_pi``: the PI the study's log names (D-380, ROLE-008: while the log names none, nobody is PI);
    ``tasks``: the study tasks (for a ``task.*`` row, the ticks the PI gave); ``log_names_pi``: the log names a PI;
    ``monitor``: the account holds a monitor grant in the study today (FIT-002)."""

    is_pi: bool = False
    tasks: frozenset[str] = frozenset()
    log_names_pi: bool = True
    monitor: bool = False


NO_STANDING = Standing()
BEST_STANDING = Standing(is_pi=True, tasks=frozenset(STUDY_TASKS), log_names_pi=True)  # the most a role could have


@dataclass(frozen=True)
class Decision:
    """The answer of :func:`permit`: ``allowed`` and the ``basis`` it rests on (``role``, a condition such as ``pi``
    or ``task:run``, or why it was refused). Truthy when allowed. The caller writes it into its audit event."""

    allowed: bool
    role: str
    action: str
    basis: str

    def __bool__(self) -> bool:
        return self.allowed


Cell = bool | tuple[str, ...]


def load_matrix(path: Path = MATRIX_PATH) -> tuple[tuple[str, ...], dict[str, dict[str, Cell]]]:
    """Read and check the matrix: the role list, and per action one cell per role (total, known conditions only)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    roles = tuple(raw.get("roles") or ())
    if not roles or len(set(roles)) != len(roles):
        raise MatrixError("roles: a non-empty list without repeats")
    out: dict[str, dict[str, Cell]] = {}
    for action, row in (raw.get("actions") or {}).items():
        if not isinstance(row, dict) or not str(row.get("what") or "").strip():
            raise MatrixError(f"{action}: every action says what it is")
        cells = {k: v for k, v in row.items() if k != "what"}
        if set(cells) != set(roles):
            raise MatrixError(f"{action}: names {sorted(cells)}, the roles are {sorted(roles)} (the matrix is total)")
        out[action] = {}
        for role, v in cells.items():
            if isinstance(v, bool):
                out[action][role] = v
                continue
            if not isinstance(v, list) or not v:
                raise MatrixError(f"{action}.{role}: true, false or a list of conditions")
            for c in v:
                ok = c in CONDITIONS or (str(c).startswith("task:") and c[5:] in STUDY_TASKS)
                if not ok or (c == "logged_tick" and not action.startswith("task.")):
                    raise MatrixError(f"{action}.{role}: unknown condition {c!r}")
            out[action][role] = tuple(v)
    return roles, out


MATRIX_ROLES, MATRIX = load_matrix()
MATRIX_WHAT: dict[str, str] = {
    a: str(row["what"]).strip()
    for a, row in (yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8")).get("actions") or {}).items()
}


def _holds(cond: str, action: str, s: Standing) -> bool:
    if cond == "pi":
        return s.is_pi
    if cond == "logged_pi":
        return s.log_names_pi and s.is_pi
    if cond == "logged_tick":
        return s.log_names_pi and action.removeprefix("task.") in s.tasks
    if cond == "unlogged":
        return not s.log_names_pi
    if cond == "monitor":
        return s.monitor
    return cond.removeprefix("task:") in s.tasks


# ---------------------------------------------------------------------------------------------- the support session
# Card 10K-15 (D-1364, owner decision 99: no standing access for support; a support-session switch). While the
# hospital's administrator has a support session on (``console.support_session``), every action not named here is
# refused to every role, here, in the one permission function: a patient-level page or route asks ``permit`` (T-102c,
# D-425), so a new one is closed by construction, and a new action is closed until it is added to this list. The
# list holds the operations and account rows the administrator's support work needs, the switch itself, and the two
# rows that are restrictions, not rights (``report.aggregate_only``, ``report.sponsor_form``): refusing a restriction
# would widen what a viewer or CRO account sees, so they keep their answer. Nothing here is a patient-level row. A
# route that asks no row (``is_admin`` only) is not closed here: every route open during a session is pinned, with
# the roles it is open to, in ``OPEN_DURING_A_SESSION`` (tests/console/test_10k15_support_session.py).
SUPPORT_SESSION_MINUTES = 120  # it ends by itself 2 hours after it started (checked at every request)
# H5 of the review of aeb978e6 (D-1364): while a session runs the mail gateway holds every mail (sent once after the
# end) but those whose idempotency key the orchestrator gave this prefix: the serious adverse event copy to the
# office (safety mail is never delayed), the box's health mail and the account notice (no patient in either)
SUPPORT_MAIL_PREFIX = "tbmail-always-"
SUPPORT_SESSION_OPEN: frozenset[str] = frozenset({
    "support.session",
    "ops.view", "ops.backup", "ops.backup_check", "ops.update_check", "ops.update_apply", "ops.logs", "ops.network",
    "job.retry_scheduled", "command.STATUS",
    "account.reset", "account.disable", "account.enable", "account.confirm", "account.create.patient-data",
    "account.create.steward", "account.create.privacy", "account.create.admin", "account.create.aggregate",
    "site.setup", "redcap.connection", "restore.release", "dataops.view", "edc.switch_off",
    "report.aggregate_only", "report.sponsor_form",
})  # fmt: skip
if SUPPORT_SESSION_OPEN - set(MATRIX):
    raise MatrixError(f"SUPPORT_SESSION_OPEN names no row: {sorted(SUPPORT_SESSION_OPEN - set(MATRIX))}")
# the console sets this for one request (``console.support_session``); a process that never sets it (the
# orchestrator, a tool) answers as before. Default off: the console fails closed itself when it cannot read the state.
_SUPPORT_SESSION: ContextVar[bool] = ContextVar("tb_support_session", default=False)


def support_session_begin(on: bool) -> Token[bool]:
    """The request now running is under a support session (``on``) or not; the token goes to
    :func:`support_session_end`."""
    return _SUPPORT_SESSION.set(bool(on))


def support_session_end(token: Token[bool]) -> None:
    _SUPPORT_SESSION.reset(token)


def in_support_session() -> bool:
    """Is the request now running under a support session (every action outside ``SUPPORT_SESSION_OPEN`` refused)?"""
    return _SUPPORT_SESSION.get()


def session_on() -> bool:
    """The one question the console's data helpers ask before they hand a page patient-linked content (the review of
    aeb978e6, D-1364): a page that mixes staff content with patient-linked content is an open row, so the helpers
    that read patient task lists, notes, candidate lists, job pages, downloads and free-text reasons answer nothing
    while it is true, and the page shows its staff parts with a "closed during the support session" line. True for a
    console request under a support session, or one whose state could not be read (closed on doubt)."""
    return _SUPPORT_SESSION.get()


def permit(role: str, action: str, standing: Standing = NO_STANDING) -> Decision:
    """May a console account with ``role`` and this ``standing`` in the study take ``action``? Pure: reads the
    matrix (and the request's support-session mark) only, logs nothing. A role or an action not in the matrix is
    refused; during a support session so is every action outside ``SUPPORT_SESSION_OPEN`` (10K-15, D-1364)."""
    if role not in MATRIX_ROLES:
        return Decision(False, role, action, "unknown role")
    row = MATRIX.get(action)
    if row is None:
        return Decision(False, role, action, "unknown action")
    if _SUPPORT_SESSION.get() and action not in SUPPORT_SESSION_OPEN:
        return Decision(False, role, action, "support session")
    cell = row.get(role, False)
    if cell is True:
        return Decision(True, role, action, "role")
    if cell is False:
        return Decision(False, role, action, "role")
    for cond in cell:
        if _holds(cond, action, standing):
            return Decision(True, role, action, cond)
    return Decision(False, role, action, "standing")


def conditional(role: str, action: str) -> bool:
    """T-102c (D-425): is ``role``'s cell for ``action`` a list of conditions, so that the study's delegation log
    decides (the investigator's ``task.*`` rows, a CRO account's monitor grant)? A page that applies the log only where
    it applies asks this instead of naming a role. A role or an action not in the matrix: False."""
    return isinstance(MATRIX.get(action, {}).get(role), tuple)


def study_bound(role: str, prefix: str) -> bool:
    """T-102c (D-425): does any row starting with ``prefix`` hold for ``role`` only in some studies (a condition)?
    Such a role needs a study it sees before it is asked (an investigator starts no run without a study)."""
    return any(conditional(role, a) for a in MATRIX if a.startswith(prefix))


def _granted(cond: str) -> frozenset[str]:
    """The commands whose investigator cell names ``cond`` (T-512's two rows)."""
    return frozenset(a.removeprefix("command.") for a, row in MATRIX.items()
                     if a.startswith("command.") and isinstance(row["investigator"], tuple)
                     and cond in row["investigator"])  # fmt: skip


# D-146 (review J-01): a request made on the console is authorised by the signed-in person's role (the console's
# signed actor assertion carries it), not by a sender mailbox in settings.yaml. A mailed request keeps the mailbox rule
# above. The console checks the same rows before it asks (console.auth.User.can_request / can_approve).
COMMANDS: tuple[str, ...] = tuple(a.removeprefix("command.") for a in MATRIX if a.startswith("command."))
# T-512 (D-349, owner answer Q-04, finding FIT-003): the runs an investigator may start in one study, read from the
# matrix's ``command.*`` rows: "pi" is the study's PI, "run" (``task:run``) a sub-investigator the PI ticked for the
# ``run`` task. The daily limits of ``daily_limit`` hold for them as for every requester. Read-only: a different
# answer is a change to the matrix.
INVESTIGATOR_RUNS: dict[str, frozenset[str]] = {"pi": _granted("pi"), "run": _granted("task:run")}


def role_allowed(role: str, command: str) -> bool:
    """True when a console account with ``role`` may start ``command`` in some study (the orchestrator's job table:
    the best case, as the study's PI with every task; viewer and CRO accounts start nothing)."""
    return permit(role, f"command.{command.upper()}", BEST_STANDING).allowed


# the orchestrator's job authorisation table: the most the role may start in any study
ROLE_COMMANDS: dict[str, frozenset[str]] = {
    r: frozenset(c for c in COMMANDS if role_allowed(r, c))
    for r in MATRIX_ROLES
    if any(role_allowed(r, c) for c in COMMANDS)
}


def can_request(role: str, command: str, *, is_pi: bool = False, tasks: frozenset[str] = frozenset()) -> bool:
    """May a console account with ``role`` start ``command`` in one study (T-512, D-349)? ``is_pi`` and ``tasks``
    are the account's standing in that study (the delegation log, ``study_tasks``)."""
    return permit(role, f"command.{command.upper()}", Standing(is_pi=is_pi, tasks=frozenset(tasks))).allowed


def study_tasks(role: str, *, log_names_pi: bool, is_pi: bool, ticked: frozenset[str]) -> frozenset[str]:
    """Deprecated wrapper over ``permit`` (the ``task.*`` rows): the tasks a console account with ``role`` has in one
    study, given the study's delegation log. D-280 (OD-5, CR-023): the administrator has none."""
    s = Standing(is_pi=is_pi, tasks=frozenset(ticked), log_names_pi=log_names_pi)
    return frozenset(t for t in STUDY_TASKS if permit(role, f"task.{t}", s))


# the role rows before a study's log names a PI (D-380, ROLE-008: an investigator has none; nobody acts as PI)
ROLE_STUDY_TASKS: dict[str, frozenset[str]] = {
    r: t for r in MATRIX_ROLES if (t := study_tasks(r, log_names_pi=False, is_pi=False, ticked=frozenset()))
}


# D-160: EDC prefill. Who may do what, on top of the study tasks above: the ``edc.*`` rows. The prefill path is data
# entry (the ``enter_data`` task: a coordinator, the PI, a sub-investigator the PI ticked for it); turning prefill on
# is the study PI's alone (they hold the sponsor's acknowledgement); turning it off is the PI's or an admin's (stop at
# once). A viewer, a CRO account and anyone without the task do nothing here.
EDC_ACTIONS: tuple[str, ...] = ("view", "map", "draft", "review", "sign", "send", "export", "switch_on", "switch_off")


def edc_allowed(role: str, action: str, *, tasks: frozenset[str], is_pi: bool) -> bool:
    """Deprecated wrapper over ``permit`` (the ``edc.*`` rows): may an account with ``role`` (and these study tasks)
    take this EDC prefill ``action`` in one study?"""
    return (
        action in EDC_ACTIONS and permit(role, f"edc.{action}", Standing(is_pi=is_pi, tasks=frozenset(tasks))).allowed
    )


def edc_role_may(role: str, action: str) -> bool:
    """Deprecated wrapper: the orchestrator's own check of an EDC action (D-162, review E-01): the most this console
    role could ever do in a study. The console adds the delegation log on top (``edc_allowed``)."""
    inv = role == "investigator"
    tasks = study_tasks(role, log_names_pi=False, is_pi=inv, ticked=frozenset())
    return edc_allowed(role, action, tasks=tasks, is_pi=inv)


# D-146 (review J-02): the daily per-sender limit protects the box from runs that read every patient. It counts only
# these job types, each on its own; a case question, a consent draft, a status or an approval is never counted.
HEAVY_JOBS: tuple[str, ...] = ("FEAS", "SCREEN", "COHORT", "NAV", "MICROBATCH", "CALIBRATION")


def daily_limit(settings: Settings, command: str, env: Mapping[str, str] | None = None) -> int | None:
    """Jobs of type ``command`` one sender may start in 24 hours: for a heavy job type ``TB_JOBS_PER_SENDER_PER_DAY``
    when set (D-775), else ``rate_limits_per_day[command]`` when set, else ``rate_limit_per_sender_per_day`` for a
    heavy job type; None (no limit) for the others and for a limit of 0. ``env`` is the process environment when not
    given."""
    import os

    from tb_common.daily_limits import jobs_override

    cmd = command.upper()
    per_type = dict(settings.rate_limits_per_day or {})
    override = jobs_override(os.environ if env is None else env) if cmd in HEAVY_JOBS else None
    if override is not None:
        n = override
    elif cmd in per_type:
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


def admin_allowed(role: str, action: str) -> bool:
    """True when a console account with ``role`` may take the operations or account ``action`` (``permit``)."""
    return action in ADMIN_ACTIONS and permit(role, action).allowed


ROLE_ADMIN_ACTIONS: dict[str, frozenset[str]] = {
    r: a for r in MATRIX_ROLES if (a := frozenset(x for x in ADMIN_ACTIONS if admin_allowed(r, x)))
}


# D-191 (independent plan review PR-17): the SAE register. Deny by default: a role or an action not listed here may do
# nothing. Everyone listed reads the register (pseudonym, screening number, dates, parties; never the AE term); only
# the study's coordinator records a report sent, a receipt or a follow-up, because the sent date is written to the AE
# form (the data core) and only the coordinator enters trial data. The investigator still acknowledges on the
# participant page (D-143). Viewer and CRO (sponsor, monitor) accounts see nothing.
SAE_ACTIONS: tuple[str, ...] = ("view", "record")
# D-280 (OD-5, CR-023): the administrator reads no SAE row (patient-level); break-glass covers one patient or job.


def sae_allowed(role: str, action: str) -> bool:
    """True only when the matrix's ``sae.*`` rows grant ``action`` on the SAE register to ``role`` (``permit``)."""
    return action in SAE_ACTIONS and permit(role, f"sae.{action}").allowed


ROLE_SAE_ACTIONS: dict[str, frozenset[str]] = {
    r: a for r in MATRIX_ROLES if (a := frozenset(x for x in SAE_ACTIONS if sae_allowed(r, x)))
}


# D-280 (owner decision OD-5, CR-029): break-glass. The administrator sees patient data only through a grant: a reason
# from this list plus a written note, one patient or one job, 60 minutes, then it ends by itself. T-716 (D-484): the
# console signs a reveal under a grant with the account's own role and the grant's id; the orchestrator reads the
# grant row itself and writes the use (``orchestrator.grants``). ``breakglass`` is not a role any party accepts;
# :data:`BREAK_GLASS_ROLE` remains only as the label of a read under a grant in the console's own audit records.
# Every use is audited and waits on the steward's review list.
BREAK_GLASS_REASONS: tuple[str, ...] = ("support", "data_fix", "optout_request", "incident", "audit_request", "other")
BREAK_GLASS_MINUTES = 60
BREAK_GLASS_NOTE_MIN = 10  # the written "why" every grant needs, in characters
BREAK_GLASS_ROLE = "breakglass"  # an audit label (console.twin_api); never signed, never identifier authority
BREAK_GLASS_REVIEW_DAYS = 7  # the steward reviews each use within a week (owner question Q-20)


# ---------------------------------------------------------------------------------------------- D-380 (T-102b)
# FIT-002 (grant half): a monitor grant opens a study's *enrolled* subjects only, read-only. A candidate, a screen
# failure or a consented person who never enrolled stays closed; a withdrawn subject counts once it had an enrolment.
MONITOR_STATES: tuple[str, ...] = ("enrolled", "on_study", "completed")


def monitor_may_see(subject: dict[str, object]) -> bool:
    """May a monitor grant open this lifecycle subject (the data core's subject record, ``reply["subject"]``, not the
    whole reply: D-436)? Enrolled subjects only. A withdrawn subject counts once it had an enrolment: the day of its
    enrolment step (``enrolled``, as the data core's subject list gives it) or an ``enrolment`` date."""
    state = str(subject.get("state") or "")
    if state in MONITOR_STATES:
        return True
    when = subject.get("enrolment") or subject.get("enrolled_on") or subject.get("enrolled")
    return state == "withdrawn" and isinstance(when, str) and bool(when.strip())


# ROLE-018: the role descriptions on ``/ops/users`` are generated from the matrix, so a page never says more or less
# than the rows. Each right is an action's ``what``, with a mark when it holds only in some studies (a condition).
def role_rights(role: str) -> list[tuple[str, str, bool]]:
    """The actions a role may take somewhere: ``(action, what, conditional)``, in the matrix's order. A role not in
    the matrix has none."""
    if role not in MATRIX_ROLES:
        return []
    return [(a, MATRIX_WHAT[a], isinstance(row[role], tuple)) for a, row in MATRIX.items()
            if row[role] is True or isinstance(row[role], tuple)]  # fmt: skip
