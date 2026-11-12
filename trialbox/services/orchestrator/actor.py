"""The acting person of an orchestrator route (T-715, D-483): one dependency.

``require_actor(action)`` on a route means: this call carries a verified v3 assertion (``tb_common.actor_v3``)
minted for exactly this action, this study (the route's ``{rs}``), this request (method, path, query) and this
body; and the matrix (``tb_common.authz.permit``) allows the action to the signed role with the signed standing.
The handler receives the claim and takes the audit actor from it (``who.name``); no field of the body names a
person. A refusal is HTTP 403 with a named reason and one ``actor.refused`` audit event.

``report_actor`` is the stage before that, for a router whose console calls are not signed yet: a changing call
without a valid v3 assertion is counted and logged, and let through. ``route_actors.yaml`` names every route
group's stage, and ``tests/unit/test_actor_routes.py`` holds the app to it.

The dependency reads the route's own template from the request, so it cannot be attached to the wrong path; and it
is ``async`` only to read the body's bytes, which FastAPI keeps for the handler's own model.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml
from fastapi import Depends, HTTPException, Request
from tb_common import actor_v3
from tb_common.authz import permit
from tb_common.service_auth import SAFE_METHODS, ActorError

log = logging.getLogger("orchestrator")
TABLE_PATH = Path(__file__).with_name("route_actors.yaml")
SCHEMA = "tb-orchestrator-actors/1"
STAGES = ("refuse", "report", "v2", "no_person")
PERSON_FIELDS = frozenset({"by", "signer", "approved_by"})  # request fields that name a person
#: changing calls that reached a `report` route without a valid v3 assertion: (route, reason) -> count
UNSIGNED: Counter[tuple[str, str]] = Counter()
_lock = threading.Lock()
_logged: set[str] = set()
_audit: Callable[[], Any] | None = None


def bind(audit: Callable[[], Any]) -> None:
    """Where refusals are recorded (the orchestrator's audit log, given by ``orchestrator.app``)."""
    global _audit
    _audit = audit


def load(path: Path = TABLE_PATH) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ValueError(f"{path.name}: not a {SCHEMA} table")
    stages = {s: list(doc.get(s) or []) for s in STAGES}
    seen: set[str] = set()
    for stage, groups in stages.items():
        for g in groups:
            if g in seen:
                raise ValueError(f"{path.name}: group {g} is in two stages")
            seen.add(g)
        if stage == "no_person" and not all(str((doc.get(stage) or {}).get(g) or "").strip() for g in groups):
            raise ValueError(f"{path.name}: every no_person group needs its reason")
    principals = {str(k): frozenset(str(a) for a in v or []) for k, v in (doc.get("principals") or {}).items()}
    return {**stages, "principals": principals}


TABLE = load()


def _template(request: Request) -> str:
    route = request.scope.get("route")
    return f"{request.method} {getattr(route, 'path', request.url.path)}"


def _target(request: Request) -> str:
    raw = request.scope.get("raw_path")
    path = raw.decode("ascii", "replace") if isinstance(raw, bytes) else request.url.path
    query = request.url.query
    return actor_v3.target_of(request.method, unquote(path) + (f"?{query}" if query else ""))


def _same_target(claimed: str, request: Request) -> bool:
    method, _, rest = claimed.partition(" ")
    path, sep, query = rest.partition("?")
    return actor_v3.target_of(method, unquote(path) + (sep + query if sep else "")) == _target(request)


def _refuse(request: Request, action: str, reason: str, who: str | None, study: str | None) -> HTTPException:
    if _audit is not None:
        _audit().append("actor.refused", actor=who, ruleset=study or None,
                        detail={"reason": reason, "route": _template(request), "action": action,
                                "caller": getattr(request.state, "tb_caller", None) or ""})  # fmt: skip
    return HTTPException(status_code=403, detail={"code": "ACTOR", "reason": reason,
                                                  "message": f"the signed-in person is refused: {reason}"})  # fmt: skip


def check(claim: actor_v3.Claim, action: str, study: str | None, service: bool = False) -> str:
    """Why this claim may not take ``action`` on ``study`` ("" when it may): the claim is for another action or
    another study, or the matrix refuses the signed role with the signed standing. A service principal passes only
    on a route that admits one, for an action its row of ``route_actors.yaml`` lists."""
    if claim.action != action:
        return "action"
    if (study or "") != claim.study:
        return "study"
    if claim.is_service:
        return "" if service and action in TABLE["principals"].get(claim.sub, frozenset()) else "principal"
    return "" if permit(claim.role, action, claim.standing()).allowed else "right"


def require_actor(action: str, *, service: bool = False) -> Any:
    """The dependency of a changing route: the verified person, allowed ``action`` on the route's study."""

    async def dep(request: Request) -> actor_v3.Claim:
        study = str(request.path_params.get("rs") or "").strip().upper() or None
        try:
            claim = actor_v3.verify(request.headers.get(actor_v3.HEADER))
        except ActorError as exc:
            raise _refuse(request, action, str(exc), None, study) from exc
        why = check(claim, action, study, service)
        if not why and not _same_target(claim.target, request):
            why = "request"
        if not why and claim.body != actor_v3.body_hash(await request.body()):
            why = "body"
        if why:
            raise _refuse(request, action, why, claim.sub, study)
        request.state.tb_actor = claim
        return claim

    dep.tb_actor_stage = "refuse"  # type: ignore[attr-defined]
    dep.tb_actor_action = action  # type: ignore[attr-defined]
    return Depends(dep)


async def _report(request: Request) -> None:
    if request.method.upper() in SAFE_METHODS:
        return
    assertion = request.headers.get(actor_v3.HEADER)
    reason = ""
    if not actor_v3.is_v3(assertion):
        reason = "no v3 assertion"
    else:
        try:
            claim = actor_v3.verify(assertion)
            if not _same_target(claim.target, request):
                reason = "request"
            elif claim.body != actor_v3.body_hash(await request.body()):
                reason = "body"
            else:
                request.state.tb_actor = claim
        except ActorError as exc:
            reason = str(exc)
    if reason:
        key = _template(request)
        with _lock:
            UNSIGNED[(key, reason)] += 1
            first = key not in _logged
            _logged.add(key)
        if first:  # once per route and process: the count is in UNSIGNED
            caller = getattr(request.state, "tb_caller", None) or ""
            log.warning("actor.unsigned", extra={"route": key, "reason": reason, "caller": caller})


_report.tb_actor_stage = "report"  # type: ignore[attr-defined]
report_actor = Depends(_report)


def _marked(calls: list[Any]) -> tuple[str, str]:
    for call in calls:
        stage = getattr(call, "tb_actor_stage", "")
        if stage:
            return stage, getattr(call, "tb_actor_action", "")
    return "", ""


def _calls(dependant: Any) -> list[Any]:
    out, stack = [], list(getattr(dependant, "dependencies", []) or [])
    while stack:
        d = stack.pop()
        out.append(d.call)
        stack += list(d.dependencies or [])
    return out


def _person_fields(route: Any) -> tuple[str, ...]:
    """The request fields of a route that name a person: in its body model, or a query parameter."""
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    for group in ("query_params", "body_params"):
        for f in getattr(dependant, group, []) or []:
            names.add(str(getattr(f, "name", "")))
            model = getattr(getattr(f, "field_info", None), "annotation", None)
            names |= set(getattr(model, "model_fields", {}) or {})
    return tuple(sorted(names & PERSON_FIELDS))


def walk(app: Any) -> list[tuple[str, str, str, str, tuple[str, ...]]]:
    """``(method, path template, stage, action, person fields)`` of every route of ``app``, included routers
    flattened with the dependencies of their ``include_router`` call (FastAPI keeps those on the include, not on
    the route). Stage "" when the route has neither dependency."""
    out: list[tuple[str, str, str, str, tuple[str, ...]]] = []

    def visit(routes: list[Any], prefix: str, inherited: list[Any]) -> None:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                ctx = getattr(r, "include_context", None)
                more = [getattr(d, "dependency", None) for d in getattr(ctx, "dependencies", None) or []]
                visit(list(inner.routes), prefix + str(getattr(ctx, "prefix", "") or ""), inherited + more)
                continue
            path, methods = getattr(r, "path", None), getattr(r, "methods", None)
            if not isinstance(path, str):
                continue
            stage, action = _marked(_calls(getattr(r, "dependant", None)) + inherited)
            for m in sorted(set(methods or ()) - {"HEAD"}) or ["GET"]:
                out.append((m.upper(), prefix + path, stage, action, _person_fields(r)))

    visit(list(app.routes), "", [])
    return out


def route_problems(app: Any, group_of: Callable[[str], str | None], table: dict[str, Any] | None = None) -> list[str]:
    """What is wrong with where the app's routes take their person from, against ``route_actors.yaml``. Empty when
    every changing route's group is in exactly one stage, its dependency is that stage's, a ``refuse`` route names
    a matrix action and takes no person from its request, and the table names no group without a changing route."""
    from tb_common.authz import MATRIX

    tbl = TABLE if table is None else table
    stage_of_group = {g: s for s in STAGES for g in tbl[s]}
    bad: list[str] = []
    changing_groups: set[str] = set()
    for method, path, stage, action, person in walk(app):
        key = f"{method} {path}"
        group = group_of(key) or ""
        changing = method not in SAFE_METHODS
        if changing:
            changing_groups.add(group)
        want = stage_of_group.get(group)
        if changing and want is None:
            bad.append(f"{key}: its group ({group or 'none'}) is in no stage of route_actors.yaml")
            continue
        if stage == "refuse":
            if want != "refuse":
                bad.append(f"{key}: has require_actor but its group ({group}) is not in stage refuse")
            if action not in MATRIX:
                bad.append(f"{key}: require_actor names {action!r}, which is not a row of the matrix")
            if person:
                bad.append(f"{key}: the request still names a person ({', '.join(person)})")
        elif changing and want == "refuse":
            bad.append(f"{key}: a changing route of a refuse group without require_actor")
        elif changing and want == "report" and stage != "report":
            bad.append(f"{key}: a changing route of a report group without report_actor")
        elif changing and want in ("v2", "no_person") and stage:
            bad.append(f"{key}: has a v3 dependency but its group ({group}) is in stage {want}")
    for group in sorted(set(stage_of_group) - changing_groups):
        bad.append(f"group {group}: in route_actors.yaml but it has no changing route")
    for who, actions in sorted(tbl["principals"].items()):
        bad += [f"principal {who}: {a!r} is not a row of the matrix" for a in sorted(actions) if a not in MATRIX]
    return bad


def assert_staged(app: Any, group_of: Callable[[str], str | None]) -> None:
    """Refuse to serve an app with a route whose person is unaccounted for (called once, at import)."""
    bad = route_problems(app, group_of)
    if bad:
        raise RuntimeError("route_actors.yaml and the routes disagree:\n  " + "\n  ".join(bad))
