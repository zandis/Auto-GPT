"""The one place the console says who acts (T-715, D-483).

Every call the console makes to a route of the orchestrator that takes a person carries a v3 assertion
(``tb_common.actor_v3``): the signed-in account, its role, the one study, its standing in that study from the
delegation log, the matrix action, the request and the body's hash. ``assert_for`` mints it, and asks the matrix
first (``Helpers.permit``, the question every page asks): the console cannot sign what it would refuse.

``tests/unit/test_actor_routes.py`` fails when ``actor_v3.mint`` is called anywhere else in ``services/console``.
"""

from __future__ import annotations

from typing import Any

from tb_common import actor_v3
from tb_common import service_auth as sa
from tb_common.authz import NO_STANDING

from console import s28

NIGHTLY = "service:console-nightly"  # the nightly REDCap read (rc_read): no session either
NOTIFY = "service:console-notify"  # the morning notices: no session (route_actors.yaml names what it may do)


def assert_for(
    h: Any, sess: Any, action: str, rid: str | None, method: str, path: str, body: Any = None
) -> dict[str, str]:
    """The header of one orchestrator call by the signed-in account of ``sess``: ``action`` (a row of the matrix)
    on study ``rid`` (None: the whole box), for exactly ``method path`` with ``body``. Refused (403, audited
    ``console.denied``) when the matrix does not allow it to this account with its standing in the study."""
    user = sess.user
    if not h.permit(user, action, rid).allowed:
        h.au.append("console.denied", actor=h.actor(sess), ruleset=rid or None, detail={"action": action})
        raise h.problem(403, "forbidden")
    standing = NO_STANDING
    if rid and h.stand is not None and user.sees_study(rid):
        standing = h.stand(user, rid).grant()
    token = actor_v3.mint(sub=h.actor(sess), role=user.role, action=action, method=method, path=path, body=body,
                          study=rid or "", standing=standing, session=sa.bound_session())  # fmt: skip
    return {actor_v3.HEADER: token}


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
