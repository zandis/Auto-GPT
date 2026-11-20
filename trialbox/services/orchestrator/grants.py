"""What the orchestrator reads for itself before it gives a chart number (T-716, D-484).

Until this card the console checked a break-glass grant and the delegation log and told the orchestrator the
result in a word (the role ``breakglass``; a standing). Now the orchestrator opens both stores:

* :func:`verify_grant`: the grant the assertion names is a row that is open now, is this person's, and covers this
  patient (a patient grant) or this job (a job grant) of this study;
* :func:`record_use`: the use is written by the orchestrator, when the chart number is given, so a reveal that never
  passed a console page is on the steward's review list too;
* :func:`log_standing`: the person's standing in the study from the delegation log (the PI the log names, the ticked
  tasks), read here; :func:`own_right` asks the matrix with it, as the console's one reveal path does.

The stores are the console's own classes (``console.breakglass_store.BreakGlassStore``,
``console.teamstore.TeamStore``): one schema, one reader of its rows' meaning. The orchestrator's database role is a
member of both schemas' groups (``30-service-roles.sh``); T-718 narrows that to SELECT on both and INSERT on
``breakglass.uses``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from tb_common.actor_v3 import Claim
from tb_common.authz import Standing, conditional, permit


class GrantRefused(PermissionError):
    """The grant an assertion names does not cover this chart number; ``why`` is the audit reason."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def username_of(sub: str) -> str:
    """The console account of a claim's ``sub`` (``console:crc`` -> ``crc``)."""
    return sub.partition(":")[2]


def verify_grant(claim: Claim, *, study: str, pid: str, job_id: str, now: datetime, url: str | None = None) -> Any:
    """The open grant row the claim names, when it covers ``pid`` of ``study`` or ``job_id``. Raises
    :class:`GrantRefused` otherwise; never trusts a field of the claim's ``grant`` but its id."""
    from console.breakglass_store import BreakGlassStore

    try:
        gid = int(str((claim.grant or {}).get("id")))
    except ValueError as exc:
        raise GrantRefused("no such grant") from exc
    try:
        store = BreakGlassStore(url)
        try:
            g = store.get(gid)
        finally:
            store.close()
    except Exception as exc:  # fail closed: a grant that cannot be read is no grant
        raise GrantRefused("the grant store cannot be read") from exc
    if g is None:
        raise GrantRefused("no such grant")
    if g.username != username_of(claim.sub):
        raise GrantRefused("another person's grant")
    if not g.active(now):
        raise GrantRefused("the grant is not open")
    if g.kind == "patient":
        if not g.covers(ruleset=study, pid=pid):
            raise GrantRefused("the grant is for another patient")
    elif not g.covers(job_id=job_id):
        raise GrantRefused("the grant is for another job")
    return g


def record_use(
    grant: Any, *, what: str, study: str, pid: str, job_id: str, now: datetime, url: str | None = None
) -> None:
    from console.breakglass_store import BreakGlassStore

    store = BreakGlassStore(url)
    try:
        store.used(grant.id, what=what, now=now, ruleset=study, pid=pid, job_id=job_id)
    finally:
        store.close()


def log_standing(username: str, study: str, today: date, url: str | None = None) -> Standing:
    """The account's standing in ``study`` as the delegation log has it today: the PI the log names (nobody while it
    names none, D-380), or the sub-investigator covering that PI today (9f-3, D-1383), and the tasks ticked for a
    sub-investigator. The one reading of the log, ``console.teamstore.log_rights``, as the console's."""
    from console.teamstore import TeamStore

    team = TeamStore(url)
    try:
        r = team.rights(study, username, today)
    finally:
        team.close()
    return Standing(is_pi=r.is_pi, tasks=r.ticked, log_names_pi=r.pi is not None)


def person_right(role: str, username: str, study: str, today: date, url: str | None = None) -> str:
    """Why this person may not receive a chart number of ``study`` by their own rights ("" when they may). The
    delegation log is read only for a role whose right it decides, so a coordinator's reveal needs no log; a log
    that cannot be read refuses (a box whose role script was not run again after the update: runbook §5, "Database
    roles after a restore")."""
    if not (conditional(role, "id.reveal") or conditional(role, "task.screen")):
        return own_right(role, Standing())
    try:
        standing = log_standing(username, study, today, url)
    except Exception:  # fail closed: no log, no right read from it
        return "the delegation log cannot be read"
    return own_right(role, standing)


def own_right(role: str, standing: Standing) -> str:
    """Why this role with this standing may not receive a chart number by its own rights ("" when it may): the
    ``id.reveal`` row, and for a role whose screening task the delegation log decides, that task in this study
    (the rule of ``console.reveal.RevealGate.own_basis``)."""
    if not permit(role, "id.reveal", standing).allowed:
        return "role"
    if conditional(role, "task.screen") and not permit(role, "task.screen", standing).allowed:
        return "delegation"
    return ""
