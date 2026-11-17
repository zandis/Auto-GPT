"""STEPS-ROLE (D-877, the owner's D-1063): one sign-in per person on a test box, and the role it acts in.

On the test VM's steps mode (D-1062) a person walks a study from its first step in several roles. Instead of one
account per role, an account may hold extra roles (``users.extra_roles``, granted only at boot by
``console.steps_roles``), and the session carries the role it acts in:

* **One place.** ``UserStore.session`` resolves the request's role: while acting is on, the session's user carries the
  acting role, so every permission check (the matrix rows, the scope rules, the actor assertions the orchestrator
  reads) reads it exactly as it reads an account's own role. No other authorisation path exists. The user name stays,
  so the delegation log's standing (a person named PI is PI acting as investigator), the audit trail and the erasure
  records name the person.
* **The switch.** ``POST /role`` (with the CSRF token) sets the session's acting role to the account's own role or one
  of its extra roles; each switch is an audit event ``role.acting`` (user, from, to). The top bar shows the acting
  role and the select.
* **The gates.** Acting is on only while the audited flag ``steps.acting_role`` is on and the box is a test box
  (``TB_ENV`` DEV or TEST). With ``TB_ENV`` VALIDATION or PRODUCTION (unset is PRODUCTION) the flag cannot be set,
  extra roles cannot be granted, the switch is refused, and the console refuses to start with the flag on or any extra
  role on record. With the flag off an account with extra roles is its own role only.

Nothing here changes what any role may do."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from tb_common.flags import read, test_box

from console.i18n import CATALOGUES
from console.local_path import local_path

FLAG = "steps.acting_role"
#: the top bar's words (en, zh-TW, ja)
WORDS = {
    "en": {"acting.as": "acting as {role}", "acting.label": "Act as", "acting.apply": "Switch role"},
    "zh-TW": {"acting.as": "目前角色：{role}", "acting.label": "切換角色", "acting.apply": "切換"},
    "ja": {"acting.as": "{role}として操作中", "acting.label": "役割の切替", "acting.apply": "切替"},
}
AUDIT = "role.acting"


class ActingRefused(RuntimeError):
    """The console does not start: acting would be possible on a validation or production box."""


def env_allows(env: Mapping[str, str]) -> bool:
    """A test box: ``TB_ENV`` DEV or TEST."""
    return test_box(dict(env))


def on(env: Mapping[str, str], url: str | None = None) -> bool:
    """Whether a session may act in an extra role now: a test box with the flag on. A flag store that does not answer
    reads as off (the account is its own role)."""
    return env_allows(env) and read(FLAG, url) == "on"


def check_at_start(env: Mapping[str, str], users: Any, url: str | None = None) -> None:
    """Refuse to start on a validation or production box with the flag on or an extra role on record."""
    if env_allows(env):
        return
    if read(FLAG, url) == "on":
        raise ActingRefused(f"the flag {FLAG} is on, and TB_ENV is not DEV or TEST: switch it off before starting")
    if users.any_extra_roles():
        raise ActingRefused("an account holds extra roles (users.extra_roles), and TB_ENV is not DEV or TEST")


def roles_of(users: Any, sess: Any) -> list[str]:
    """The roles the session may switch to (its own first), or [] when acting is off or the account holds none."""
    if sess is None or not users.acting_on():
        return []
    extra = users.extra_roles(sess.user.username)
    if not extra:
        return []
    own = sess.acting_from or sess.user.role
    return [own, *[r for r in extra if r != own]]


for _lang, _words in WORDS.items():
    CATALOGUES[_lang].update(_words)


def register(app: FastAPI, h: Any, users: Any, env: Mapping[str, str]) -> None:
    @app.post("/role")
    def switch(request: Request, role: str = Form(""), csrf: str = Form(""), back: str = Form("/")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not env_allows(env) or role not in roles_of(users, sess):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": "/role", "to": role[:20]})
            raise h.problem(403, "forbidden")
        before, after = users.set_acting(sess, role)
        if before != after:
            h.au.append(AUDIT, actor=h.actor(sess), detail={"user": sess.user.username, "from": before, "to": after})
        return RedirectResponse(local_path(back, "/"), status_code=303)
