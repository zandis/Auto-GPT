"""Which verified calling service may reach which orchestrator route (T-713, D-464; review 2026-11-12 trust F2, F7,
F12, card TR-2).

The service token tells the orchestrator which service called (``request.state.tb_caller``, D-138). Before this
module every accepted service reached every route: the mail gateway's token, which parses hostile mail, could enrol
or withdraw a subject, acknowledge an SAE or change study settings. Now ``route_callers.yaml`` (next to this file)
names every route of the app in one group and which service may reach which groups, and :class:`Gate` enforces it in
one place: ``make_app``'s ``route_gate``, called by the token middleware right after the token is verified, before
routing. A refusal is 403 with a named reason (``X-TB-Refusal``) and one audit event ``service.route_refused``
carrying the verified service.

* ``route_not_allowed``: the verified service has no group holding this route (or, for the mail gateway, the job
  type or the job is not its own);
* ``caller_unverified``: the old shared token (``legacy``) outside DEV and TEST, where nobody can tell which service
  called (D-437 did the same for the gateway);
* ``internal_principal``: ``POST /jobs`` naming ``scheduler`` or ``system`` as ``requested_by``. Those names skip the
  mailbox rules and the rate limit (``core.SYSTEM_SENDERS``), so only the in-process scheduler may use them.

The table decides which SERVICE may call a route, never which person; the routes that take the person from the body
are T-715's.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.routing import compile_path

TABLE_PATH = Path(__file__).with_name("route_callers.yaml")
SCHEMA = "tb-orchestrator-callers/1"
EVENT = "service.route_refused"
REFUSAL_HEADER = "X-TB-Refusal"
LEGACY = "legacy"  # tb_common.service_auth.LEGACY: the old shared token, no service identity
OPEN_ENVS = ("DEV", "TEST")  # tb_common.service_auth.OPEN_ENVS
NOT_ALLOWED = "route_not_allowed"
UNVERIFIED = "caller_unverified"
INTERNAL = "internal_principal"
_KEY = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/[^\s]*)$")
_OWN = ("", "mail")

log = logging.getLogger("orchestrator.callers")


class TableError(ValueError):
    """``route_callers.yaml`` is not a valid table: the orchestrator does not start on it."""


@dataclass(frozen=True)
class ServiceRow:
    """One calling service: the routes its groups hold, and the job rules of the mail gateway."""

    name: str
    groups: tuple[str, ...]
    routes: frozenset[str]
    job_types: frozenset[str] | None = None  # None: any job type the person's role or mailbox allows
    own_jobs: str = ""  # "mail": GET /jobs/{job_id} only for a job with a message_id
    in_process: bool = False
    principals: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Table:
    open: frozenset[str]
    groups: dict[str, tuple[str, ...]]
    services: dict[str, ServiceRow]

    def group_of(self, key: str) -> str | None:
        for name, keys in self.groups.items():
            if key in keys:
                return name
        return None

    def keys(self) -> frozenset[str]:
        return frozenset(k for keys in self.groups.values() for k in keys) | self.open

    @property
    def principals(self) -> frozenset[str]:
        """The internal principal names (``scheduler``, ``system``): an in-process row's, never from HTTP."""
        return frozenset(p for row in self.services.values() if row.in_process for p in row.principals)


def _strs(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
        raise TableError(f"{where}: a list of names")
    return tuple(x.strip() for x in raw)


def parse(doc: Any) -> Table:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise TableError(f"not a {SCHEMA} table")
    open_keys = _strs(doc.get("open"), "open")
    groups: dict[str, tuple[str, ...]] = {}
    seen: dict[str, str] = {k: "open" for k in open_keys}
    for name, raw in (doc.get("groups") or {}).items():
        keys = _strs(raw, f"group {name}")
        for k in keys:
            if not _KEY.match(k):
                raise TableError(f"group {name}: {k!r} is not 'METHOD /path'")
            if k in seen:
                raise TableError(f"{k} is in two groups ({seen[k]}, {name})")
            seen[k] = str(name)
        groups[str(name)] = keys
    services: dict[str, ServiceRow] = {}
    for name, raw in (doc.get("services") or {}).items():
        if not isinstance(raw, dict):
            raise TableError(f"service {name}: a mapping")
        gs = _strs(raw.get("groups"), f"service {name} groups")
        bad = sorted(set(gs) - set(groups))
        if bad:
            raise TableError(f"service {name} names unknown groups {bad}")
        own = str(raw.get("own_jobs") or "")
        if own not in _OWN:
            raise TableError(f"service {name}: own_jobs must be one of {_OWN}")
        in_process = bool(raw.get("in_process", False))
        principals = frozenset(_strs(raw.get("principals"), f"service {name} principals"))
        if principals and not in_process:
            raise TableError(f"service {name}: only an in-process row holds principal names")
        if in_process and gs:
            raise TableError(f"service {name}: an in-process row reaches no HTTP route")
        jt = raw.get("job_types")
        services[str(name)] = ServiceRow(
            name=str(name),
            groups=gs,
            routes=frozenset(k for g in gs for k in groups[g]),
            job_types=None if jt is None else frozenset(_strs(jt, f"service {name} job_types")),
            own_jobs=own,
            in_process=in_process,
            principals=principals,
        )
    return Table(frozenset(open_keys), groups, services)


def load(path: Path = TABLE_PATH) -> Table:
    try:
        return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as exc:
        raise TableError(f"{path}: {type(exc).__name__}") from exc


def route_templates(app: Any) -> Iterator[tuple[str, str]]:
    """``(method, path template)`` of every route of ``app`` in FastAPI's matching order, included routers flattened
    (FastAPI keeps them as one entry with the original router). ``HEAD`` is folded into ``GET``."""

    def walk(routes: list[Any], prefix: str) -> Iterator[tuple[str, str]]:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                ctx = getattr(r, "include_context", None)
                yield from walk(list(inner.routes), prefix + str(getattr(ctx, "prefix", "") or ""))
                continue
            path = getattr(r, "path", None)
            methods = getattr(r, "methods", None)
            if not isinstance(path, str):
                continue
            ms = sorted(set(methods or ()) - {"HEAD"}) or sorted(methods or ()) or ["GET"]
            for m in ms:
                yield m.upper(), prefix + path

    yield from walk(list(app.routes), "")


def environment() -> str:
    from tb_common.config import environment_name

    return environment_name(os.environ).upper()


class Gate:
    """The route gate of the orchestrator app (``make_app(route_gate=...)``) and the job rules its handlers ask."""

    def __init__(self, table: Table, audit: Callable[[], Any], env: Callable[[], str] = environment) -> None:
        self.table = table
        self._audit = audit
        self._env = env
        self._compiled: list[tuple[str, str, re.Pattern[str]]] | None = None

    # ---------------------------------------------------------------------------------------------- routes
    def bind(self, app: Any) -> None:
        """Compile the app's routes once, after the last router is included (the end of ``orchestrator.app``). A
        route added later, or under a mount, does not resolve and is refused for a named caller outside DEV and
        TEST."""
        self._compiled = [(m, t, compile_path(t)[0]) for m, t in route_templates(app)]

    def resolve(self, method: str, path: str) -> str | None:
        """The route key (``METHOD /template``) FastAPI will run for this request; None when no bound route
        matches."""
        if self._compiled is None:
            raise RuntimeError("the route gate is not bound to its app (Gate.bind)")
        m = "GET" if method.upper() == "HEAD" else method.upper()
        for rm, template, rx in self._compiled:
            if rm == m and rx.match(path):
                return f"{m} {template}"
        return None

    def decide(self, caller: str | None, key: str) -> tuple[str, str] | None:
        """``(reason, message)`` when ``caller`` may not reach the route ``key``; None when it may."""
        if key in self.table.open:
            return None
        if caller is None:  # the token layer runs open: no token on a DEV/TEST box (service_auth refuses elsewhere)
            return None
        if caller == LEGACY:
            if self._env() in OPEN_ENVS:
                return None
            return UNVERIFIED, (
                "the orchestrator cannot tell which service called (the old shared token): run "
                "`trialbox secrets init` or `trialbox secrets rotate` (D-138, D-464)"
            )
        row = self.table.services.get(caller)
        if row is None or key not in row.routes:
            return NOT_ALLOWED, f"service {caller} may not call {key}"
        return None

    def __call__(self, request: Request, caller: str | None) -> Response | None:
        method = request.method.upper()
        if method == "OPTIONS":
            return None
        key = self.resolve(method, request.url.path)
        if key is None:
            # no declared route: FastAPI's 404/405 only where nobody can be named anyway (an open box) or on a
            # synthetic DEV/TEST box; a named caller elsewhere is refused, so no-match is never "allowed"
            if caller is None or self._env() in OPEN_ENVS:
                return None
            key = f"{method} ?"  # in no row: a named service gets route_not_allowed, the shared token caller_unverified
        why = self.decide(caller, key)
        if why is None:
            return None
        self.record(caller, key, why[0])
        return JSONResponse({"detail": f"{why[0]}: {why[1]}"}, status_code=403, headers={REFUSAL_HEADER: why[0]})

    # ---------------------------------------------------------------------------------------------- jobs
    def job_start(
        self, caller: str | None, job_type: str, requested_by: str, message_id: str | None = None
    ) -> tuple[str, str] | None:
        """The rules of ``POST /jobs`` beyond the route: no internal principal from HTTP, from any caller (F7); the mail
        gateway starts only its mail commands, and only as a mailed job (a ``message_id``), so every job it starts is
        one it may read. The job ``POST /jobs`` answers with (a new one, or an existing one for a known ``job_id``)
        passes :meth:`job_read` too."""
        if requested_by in self.table.principals:
            return INTERNAL, f"{requested_by!r} is an internal principal; it starts jobs in process only"
        row = self.table.services.get(caller or "")
        if row is not None and row.job_types is not None and job_type not in row.job_types:
            return NOT_ALLOWED, f"service {caller} may not start {job_type}"
        if row is not None and row.own_jobs == "mail" and not (message_id or "").strip():
            return NOT_ALLOWED, f"service {caller} starts only jobs that came in by mail (a message_id)"
        return None

    def job_read(self, caller: str | None, message_id: str | None) -> tuple[str, str] | None:
        """``GET /jobs/{job_id}`` for a service that may read its own jobs only: the mail gateway's are the jobs that
        came in by mail (a ``message_id``)."""
        row = self.table.services.get(caller or "")
        if row is not None and row.own_jobs == "mail" and not (message_id or "").strip():
            return NOT_ALLOWED, f"service {caller} may read only the jobs that came in by mail"
        return None

    def refuse(self, caller: str | None, key: str, why: tuple[str, str]) -> HTTPException:
        """A handler's refusal under this table: audited like the gate's, raised by the caller."""
        self.record(caller, key, why[0])
        return HTTPException(status_code=403, detail=f"{why[0]}: {why[1]}", headers={REFUSAL_HEADER: why[0]})

    def record(self, caller: str | None, key: str, reason: str) -> None:
        """One audit event per refusal, with the verified service and the route template (never the raw path: it
        holds record keys and is the caller's to choose). A failed audit is logged; the call stays refused."""
        try:
            self._audit().append(EVENT, actor=f"service:{caller or '-'}",
                                 detail={"service": caller or "", "route": key, "reason": reason})  # fmt: skip
        except Exception:
            log.exception("refusal not audited: %s %s %s", caller, key, reason)
