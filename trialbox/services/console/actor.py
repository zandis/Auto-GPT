"""The one place the console says who acts (T-715, D-483).

Every call the console makes to a route of the orchestrator that takes a person carries a v3 assertion
(``tb_common.actor_v3``): the signed-in account, its role, the one study, its standing in that study from the
delegation log, the matrix action, the request and the body's hash. ``assert_for`` mints it, and asks the matrix
first (``Helpers.permit``, the question every page asks): the console cannot sign what it would refuse.

``tests/unit/test_actor_routes.py`` fails when ``actor_v3.mint`` is called anywhere else in ``services/console``.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from tb_common import actor_v3, patient_reads
from tb_common import service_auth as sa
from tb_common.authz import NO_STANDING

from console import s28

NIGHTLY = "service:console-nightly"  # the nightly REDCap read (rc_read): no session either
NOTIFY = "service:console-notify"  # the morning notices: no session (route_actors.yaml names what it may do)
#: T-719 (D-487): a page asks whether a running case's subject is on the opt-out register. The reader may be anyone
#: who sees the job and never sees the pseudonym, so the lookup is the console's, under this name, capped and logged
OPTOUT_CHECK = "service:console-optout-check"
#: T-715 refuse mode (the notices): the box's own mail, each sender under its own name and the one row it acts under
#: there (route_actors.yaml); the orchestrator takes from each only its own kinds. Fixed in the code that sends:
#: never a name or a row a session supplies
SAE_SYNC = "service:console-sae-sync"
ACCOUNTS = "service:console-accounts"
BREAKGLASS = "service:console-breakglass"
NOTICE_ACTION = {NOTIFY: "phi.view", SAE_SYNC: "sae.view", ACCOUNTS: "account.reset", BREAKGLASS: "breakglass.open"}


#: NEW-SEC-1 (D-717): the console's helpers and the signed-in session of this request, set by ``need`` (one value
#: per request: a context variable), so that every patient read a page makes is signed by its account
_READER: contextvars.ContextVar[tuple[Any, Any] | None] = contextvars.ContextVar("tb_console_reader", default=None)


def bind_reader(h: Any, sess: Any) -> None:
    """The account of this request signs the patient reads its pages make (:func:`read_headers`)."""
    _READER.set((h, sess))


@contextlib.contextmanager
def reading_as(principal: str) -> Iterator[None]:
    """Inside the block, the patient reads a timer makes are signed as ``principal`` (a service principal that
    ``route_actors.yaml`` lets read patient rows), and as nobody else after it: a timer's thread is used again."""
    token = _READER.set((None, principal))
    try:
        yield
    finally:
        _READER.reset(token)


def reading_for_a_person() -> bool:
    """True when a signed-in account of this request reads (a page), False for a timer or nobody (the D-717
    review: a mail round whose patient read is refused must not go on with an empty answer)."""
    bound = _READER.get()
    return bound is not None and bound[0] is not None


def may_read_any() -> bool:
    """D-1221: may the account of this request read patient rows at all (``phi.view`` in some study)? A timer, or no
    reader bound, answers True."""
    bound = _READER.get()
    if bound is None or bound[0] is None:
        return True
    h, sess = bound
    return bool(h.permit(sess.user, "phi.view", None).allowed)


def may_read(rid: str) -> bool:
    """D-1221: would :func:`read_headers` let the account of this request read patient rows of ``rid`` (``phi.view``
    in a study it sees)? Asked before a read a page may skip, so no refused read (and no ``console.denied``) is made.
    A timer's principal, or no reader bound, answers True: the orchestrator decides as before."""
    bound = _READER.get()
    if bound is None or bound[0] is None:
        return True
    h, sess = bound
    return bool(sess.user.sees_study(rid) and h.permit(sess.user, "phi.view", rid).allowed)


def read_headers(method: str, path: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    """``headers`` with the signed claim of a patient read (``tb_common.patient_reads``): ``phi.view`` on the
    path's study (none for a set-up route of the whole site) by the signed-in account of this request. Refused here
    (403, ``console.denied``) when the account may not see patient-level data in that study. A call that is not a
    patient read, or already carries a claim, is left as it is; with no account (a timer) nothing is added, and the
    orchestrator refuses the read."""
    out = dict(headers or {})
    hit = patient_reads.match(method, path)
    bound = _READER.get()
    if hit is None or actor_v3.HEADER in out or bound is None:
        return out
    h, sess = bound
    _, actions, study = hit
    rid = study or None
    if h is None:  # a timer's principal (reading_as): the orchestrator admits it only where the route says so
        out.update(assert_service(str(sess), actions[0], rid, method.upper(), path))
        return out
    # the first of the route's actions this account holds in that study (a monitor reads with its own row); none:
    # the first, which assert_for refuses and records
    action = next((a for a in actions if h.permit(sess.user, a, rid).allowed), actions[0])
    # the D-717 review: the account must see that study (an SMO or CRO account's scope); the claim names no study
    # list, so the orchestrator cannot tell this itself. The delegation log is the matrix's for each row that names
    # it; ``phi.view`` names none (an investigator's cell is ``true``), so it is not asked here (said in D-717)
    if rid and not sess.user.sees_study(rid):
        h.au.append("console.denied", actor=h.actor(sess), ruleset=rid, detail={"action": action, "why": "study"})
        raise h.problem(403, "forbidden")
    out.update(assert_for(h, sess, action, rid, method.upper(), path))
    return out


def assert_for(
    h: Any, sess: Any, action: str, rid: str | None, method: str, path: str, body: Any = None, *, grant: Any = None
) -> dict[str, str]:
    """The header of one orchestrator call by the signed-in account of ``sess``: ``action`` (a row of the matrix)
    on study ``rid`` (None: the whole box), for exactly ``method path`` with ``body``. Refused (403, audited
    ``console.denied``) when the matrix does not allow it to this account with its standing in the study."""
    user = sess.user
    # T-716 (D-484): under a break-glass grant the right is the grant, which the orchestrator reads itself; the
    # console signs the account's own role and the grant's id, and asks the row of who may hold a grant
    asked = "breakglass.open" if grant is not None else action
    if not h.permit(user, asked, rid).allowed:
        h.au.append("console.denied", actor=h.actor(sess), ruleset=rid or None, detail={"action": asked})
        raise h.problem(403, "forbidden")
    standing = NO_STANDING
    if rid and h.stand is not None and user.sees_study(rid):
        standing = h.stand(user, rid).grant()
        if standing.pi_rights is not None:  # 9f-3 (D-1383): the assertion names one action; a cover's allow-list
            standing = replace(standing, is_pi=standing.is_pi and action in standing.pi_rights, pi_rights=None)
    token = actor_v3.mint(sub=h.actor(sess), role=user.role, action=action, method=method, path=path, body=body,
                          study=rid or "", standing=standing, session=sa.bound_session(),
                          grant=None if grant is None else grant_claim(grant))  # fmt: skip
    return {actor_v3.HEADER: token}


def grant_claim(grant: Any) -> dict[str, Any]:
    """A break-glass grant as the assertion carries it. Only the id decides anything at the orchestrator; the rest
    is for the record."""
    return {"id": str(grant.id), "kind": grant.kind, "pid": grant.pid, "job_id": grant.job_id, "end": grant.ends_at}


def assert_service(
    principal: str, action: str, rid: str | None, method: str, path: str, body: Any = None
) -> dict[str, str]:
    """The header of a call no person makes (a console timer). The orchestrator admits a principal only on the
    routes that say so and only for the actions its row of ``route_actors.yaml`` lists."""
    token = actor_v3.mint(sub=principal, role=actor_v3.SERVICE_ROLE, action=action, method=method, path=path,
                          body=body, study=rid or "")  # fmt: skip
    return {actor_v3.HEADER: token}


def call(h: Any, sess: Any, action: str, rid: str | None, method: str, path: str, body: Any = None) -> Any:
    """The orchestrator's study API as the signed-in account (``s28.call`` with the assertion)."""
    return s28.call(h.bk, method, path, body, headers=assert_for(h, sess, action, rid, method, path, body))
