"""The orchestrator's study API for an in-process walk or scenario, signed as the person a call names (T-715f, D-799).

A walk (``tools.e2e_simple``) and a scenario (``tools.scenarios``) seed a study by calling the orchestrator's routes
directly, the way a person at the console would, and name that person with a ``by`` field. A changing route in stage
``refuse`` (``orchestrator/route_actors.yaml``) takes no such field: it takes a verified v3 assertion for its matrix
action. :func:`signed` wraps a backend's ``study_api`` so that such a call carries the assertion of the named person
(``console:<by>``, the coordinator by default) for the route's own action, and the ``by`` field is dropped. Other calls
pass unchanged.

The assertion is minted with this process's actor key, as the console mints one: on a box with no token (DEV, TEST,
where the walks run) the MAC is empty and only such a box accepts it. This is a tool of the in-process walks, never a
service: a deployed console signs only for a signed-in session (``console.actor``)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from tb_common import actor_v3

Api = Callable[..., Any]


def _actions() -> list[tuple[str, re.Pattern[str], str, int]]:
    from orchestrator.actor import walk
    from orchestrator.app import app

    out = []
    for method, path, stage, action, _ in walk(app):
        if stage != "refuse" or method in ("GET", "HEAD", "OPTIONS") or not isinstance(action, str):
            continue
        parts = path.split("/")
        at = next((parts.index(n) for n in ("{rs}", "{ruleset}") if n in parts), -1)
        out.append((method, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$"), action, at))
    return out


def signed(study_api: Api, *, by: str = "crc1", role: str = "coordinator") -> Api:
    """``study_api`` with each changing call to a refuse route signed as ``console:<by>`` (the body's own ``by``,
    when it names one, wins and is dropped)."""
    table = _actions()

    def api(method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
        clean = path.split("?", 1)[0]
        hit = next(((a, i) for m, rx, a, i in table if m == method.upper() and rx.match(clean)), None)
        if hit is None:
            return study_api(method, path, body, headers=headers)
        action, at = hit
        person = by
        if isinstance(body, dict) and "by" in body:
            body = dict(body)
            person = str(body.pop("by"))
        sub = person if person.startswith("console:") else f"console:{person}"
        study = clean.split("/")[at].upper() if at >= 0 else ""
        token = actor_v3.mint(sub=sub, role=role, action=action, method=method, path=path, body=body, study=study)
        return study_api(method, path, body, headers={**(headers or {}), actor_v3.HEADER: token})

    return api
