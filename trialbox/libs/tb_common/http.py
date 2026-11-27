"""FastAPI app factory (``/healthz``, JSON errors, request logs), a typed inter-service client, and the one guard for
outbound calls a person or an outside document can steer (T-212d, D-450: :func:`guarded_client`)."""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import re
import socket
import time
import traceback
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from typing import Any, TypeVar, get_args
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.routing import Match, Mount, compile_path
from tb_contracts import dump

from tb_common.logging import setup_logging

M = TypeVar("M", bound=BaseModel)
HealthCheck = Callable[[], dict[str, Any]]
RouteGate = Callable[[Request, str | None], Response | None]
VERSION = "1.0.0"


class ServiceError(RuntimeError):
    def __init__(self, service: str, status: int, detail: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(f"{service} returned {status}: {detail}")
        self.service = service
        self.status = status
        self.detail = detail
        #: the refusal's response headers, lower-cased names (a 409 that names what is running: ``x-tb-run``)
        self.headers: dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}


#: error types whose text is written by a rule's author, or names the tag that was sent: the answer says the type
_OWN_TEXT = ("value_error", "assertion_error", "union_tag_invalid", "union_tag_not_found")
_PLACES = ("body", "query", "path", "header", "cookie")
_KEPT = ("[key]",)  # the framework's own mark for "a key of a mapping"


def _declared(tp: Any, seen: set[int], out: set[str]) -> None:
    """The field names and aliases of every model reachable from an annotation."""
    if id(tp) in seen:
        return
    seen.add(id(tp))
    fields = getattr(tp, "model_fields", None)
    if isinstance(fields, dict):
        for name, f in fields.items():
            out.add(name)
            out.update(a for a in (f.alias, f.validation_alias) if isinstance(a, str))
            _declared(f.annotation, seen, out)
    for arg in get_args(tp):
        _declared(arg, seen, out)


def _route_names(request: Request) -> set[str]:
    """Every name the route itself declares: its parameters and the fields of its models. Kept on the route."""
    route = request.scope.get("route")
    names = getattr(route, "_tb_declared", None)
    if names is None:
        names = set()
        dep = getattr(route, "dependant", None)
        todo = [dep] if dep is not None else []
        while todo:
            d = todo.pop()
            todo += list(getattr(d, "dependencies", ()) or ())
            for kind in ("path_params", "query_params", "header_params", "cookie_params", "body_params"):
                for prm in getattr(d, kind, ()) or ():
                    names.update(n for n in (prm.name, getattr(prm, "alias", None)) if isinstance(n, str))
                    _declared(getattr(prm.field_info, "annotation", None), set(), names)
        if route is not None:
            with contextlib.suppress(Exception):
                route._tb_declared = names
    return names


async def validation_answer(request: Request, exc: Exception) -> JSONResponse:
    """The 422 answer to a request of the wrong shape (NEW-TRUST-2, D-551): where it is wrong and why, never what
    was sent. The framework's own answer repeats the input (a body with a chart number came back with it), and a
    client that logs a refusal then logs it. So: no ``input`` and no ``ctx``; in the place (``loc``) only what the
    route declares (a parameter, a field of its models, a position), anything else as ``*`` (an extra key, a key
    of a mapping: the caller chose that text); and no message text for the error types whose text a rule's author
    writes or that name what was sent."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    names = _route_names(request)
    detail = []
    for e in errors:
        loc = [x if isinstance(x, int) or (i == 0 and x in _PLACES) or x in names or x in _KEPT else "*"
               for i, x in enumerate(e.get("loc") or ())]  # fmt: skip
        kind = str(e.get("type") or "")
        msg = "the value was refused by a rule of this field" if kind in _OWN_TEXT else e.get("msg")
        detail.append({"type": kind, "loc": loc, "msg": msg})
    return JSONResponse({"detail": detail}, status_code=422)


#: a failure a service recorded without expecting it: the error's type, a colon, some of the error's text
_RECORDED = re.compile(r"^((?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*):(?:\s|$)")


def kept_failure(detail: str) -> str:
    """What to keep of a failure another service recorded, in a record a person reads (D-557, D-700).

    A service's own sentence ("the source folder is empty", "night refused: ...") is kept: it is its word for the
    operator. A record that starts with ONE name and a colon (``"ConversionException: ..."``, ``"error: ..."``,
    ``"_Refused: ..."``, with or without a module path) is a failure it did not expect, written as the error's
    type and the error's own text (an engine quotes the value it could not cast): the name is kept, the service's
    log has the rest. No service writes a sentence of its own that starts with one word and a colon; one that did
    would be cut to that word, which fails safe. Applying it twice changes nothing."""
    text = str(detail or "").strip()
    kind = _RECORDED.match(text)
    return kind.group(1) if kind else text


TRACE_FRAMES = 30  # of each error of the chain, so that one line of the log stays a line
TRACE_CHAIN = 5


def trace_of(exc: BaseException) -> dict[str, str]:
    """An error for the log without its own text (D-557): ``error`` is its type, ``trace`` the frames it passed
    (file, line, function, the line of code) and the types of the errors it came from.

    An error's text is whatever its author put in it: a database error quotes its statement's values, a validation
    error prints its input, an f-string holds a value of the path. The log's scrubber knows the shapes of a chart
    number and a secret, not every value, so the text is left out and the type and the place are kept."""
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(parts) < TRACE_CHAIN:
        seen.add(id(cur))
        frames = "".join(traceback.format_tb(cur.__traceback__, limit=-TRACE_FRAMES))  # the last ones: where it broke
        parts.append(f"{frames}{type(cur).__name__}")
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    return {"error": type(exc).__name__, "trace": "\n-- raised while handling --\n".join(parts)}


NO_ROUTE = "(no route)"
MOUNT = "(mount)"


def route_of(request: Request) -> str:
    """The template of the route a request was for (``/studies/{rs}/records/{record}``), for the log (D-556).

    A path carries what the caller put in it (a record, a job, anything typed where an id belongs), so the log
    holds the route instead. Nothing here is built from the path that was sent: the template is the framework's
    own, with the prefix its router was included under. A request that reached a handler has its route in the
    scope; one that was answered before (a refused token, a method the route does not take) is matched against
    the app's routes, the routes of included routers too; a mounted application is named by its mount's path; a
    path of no route is written ``(no route)``."""
    scope = request.scope
    found = _included_template(scope) or _own_template(scope.get("route"))
    if found is not None:
        return found
    partial: str | None = None
    for template, match in _candidates(getattr(request.app.router, "routes", []), scope):
        if match == Match.FULL:
            return template
        partial = partial or template  # the route is there, the method is not its: named all the same
    return partial or NO_ROUTE


def _included_template(scope: Any) -> str | None:
    """The full template of a route of an included router (``/v1`` + ``/jobs/{job_id}``), which the framework keeps
    beside the route while it handles the request. The names are the framework's private ones, so a test pins that
    an included route is logged with its prefix (``tests/unit/test_access_log_route.py``)."""
    ctx = (
        (scope.get("fastapi") or {}).get("effective_route_context") if isinstance(scope.get("fastapi"), dict) else None
    )
    path = getattr(ctx, "path", None)
    return path if isinstance(path, str) and path else None


def _own_template(route: Any) -> str | None:
    path = getattr(route, "path", None)
    if not isinstance(path, str):
        return None
    if isinstance(route, Mount):  # a mounted application: its mount's path when that is a fixed one
        return (path or "/") if "{" not in path else MOUNT
    return path


def _candidates(routes: Any, scope: Any) -> Iterator[tuple[str, Match]]:
    """Every route of the app that the request's path fits, with how well (the method too, or the path only)."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):  # an included router: its routes, each with its full template
            for ctx in contexts():
                template = getattr(ctx, "path", None)
                if not isinstance(template, str) or not template:
                    continue
                try:
                    regex = compile_path(template)[0]
                except Exception as exc:
                    logging.getLogger("tb_common.http").debug("route_of: %s", type(exc).__name__)
                    continue
                if regex.match(scope.get("path") or ""):
                    methods = getattr(getattr(ctx, "original_route", None), "methods", None)
                    ok = methods is None or scope.get("method") in methods
                    yield template, Match.FULL if ok else Match.PARTIAL
            continue
        try:
            match, _ = route.matches(scope)
        except Exception as exc:  # a route that cannot judge this scope is not the route
            logging.getLogger("tb_common.http").debug("route_of: %s", type(exc).__name__)
            continue
        template = _own_template(route)
        if match != Match.NONE and template is not None:
            yield template, match


def make_app(
    service: str,
    checks: list[HealthCheck] | None = None,
    level: str = "INFO",
    lifespan: Any = None,
    service_token: bool = True,
    protect_reads: bool = False,
    route_gate: RouteGate | None = None,
) -> FastAPI:
    """Create a FastAPI app with ``GET /healthz`` and structured logging (optional ``lifespan`` context).

    ``service_token`` (default on; D-127, review F-11): every changing call must carry a
    ``X-TB-Service-Token`` (``tb_common.service_auth.authorize``), on every internal service, not only the
    orchestrator; with a token registry (D-138) only the callers of ``service_auth.CALLERS[service]``.
    ``protect_reads`` (D-130, plan v4 F4): reads need it too (the orchestrator, the lake, the mail gateway, the trace
    store). ``/healthz`` stays open for the compose health checks.
    ``route_gate`` (T-713, D-464): called right after the token is verified, with the request and the verified
    calling service (None on an open DEV/TEST box, ``legacy`` for the old shared token); a response it returns is the
    answer (a refusal), None lets the call through. One place per app decides which service reaches which route."""
    log = setup_logging(service, level)
    app = FastAPI(title=f"trialbox-{service}", version=VERSION, lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_answer)  # D-551: no value of the request
    health_checks = list(checks or [])
    app.state.health_checks = health_checks

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        detail: dict[str, Any] = {}
        ok = True
        for chk in app.state.health_checks:
            try:
                detail.update(chk())
            except Exception as exc:  # health must report, not raise
                ok = False
                detail[getattr(chk, "__name__", "check")] = f"error: {type(exc).__name__}"
        body = {
            "status": "ok" if ok else "degraded",
            "service": service,
            "version": VERSION,
            "checks": detail,
        }
        return JSONResponse(body, status_code=200 if ok else 503)

    if service_token:

        @app.middleware("http")
        async def require_service_token(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            from tb_common.config import environment_name
            from tb_common.service_auth import TOKEN_HEADER, authorize

            if request.url.path != "/healthz":
                # D-138: with a token registry the callee knows which service called and accepts only its callers
                refused, caller = authorize(
                    request.method,
                    request.headers.get(TOKEN_HEADER),
                    environment_name(os.environ),
                    protect_reads,
                    callee=service,
                )
                if refused is not None:
                    return JSONResponse({"detail": refused[1]}, status_code=refused[0])
                request.state.tb_caller = caller
                if route_gate is not None:
                    gated = route_gate(request, caller)
                    if gated is not None:
                        return gated
            return await call_next(request)

    @app.middleware("http")
    async def access_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # D-557: the error's type and where it was raised, not its own text
            log.error("unhandled error", extra={"path": route_of(request), **trace_of(exc)})
            return JSONResponse({"error": "internal error"}, status_code=500)
        if request.url.path != "/healthz":
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": route_of(request),  # the route, not what was sent in it (D-556)
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - t0) * 1000, 1),
                },
            )
        return response

    return app


class ServiceClient:
    """Small synchronous client that sends/receives contract models."""

    def __init__(
        self, base_url: str, service: str, timeout: float = 300.0, retries: int = 2, idempotent: bool = True
    ) -> None:
        """``idempotent=False`` (e.g. mail-gateway ``POST /send``): retry only when no connection was made, never
        after the request may have reached the service (5xx, read timeout) — a retry would send it twice."""
        self.base_url = base_url.rstrip("/")
        self.service = service
        self.retries = retries
        self.idempotent = idempotent
        self.client = httpx.Client(timeout=timeout)
        self.log = logging.getLogger(f"client.{service}")

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        from tb_common.service_auth import auth_headers, resign

        # D-114, D-127 (F-11): the box's service token goes to every TrialBox service
        token = auth_headers()
        headers = {**token, **(kw.pop("headers", None) or {})}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:  # D-447 (SEC-17): an actor assertion is accepted once, so a retry carries a new one
                headers = resign(headers)
            try:
                resp = self.client.request(method, f"{self.base_url}{path}", headers=headers, **kw)
            except httpx.TransportError as exc:
                last = exc
                if not self.idempotent and not isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
                    break  # it may have arrived
                time.sleep(min(2**attempt, 8))
                continue
            if resp.status_code >= 500 and attempt < self.retries and self.idempotent:
                time.sleep(min(2**attempt, 8))
                continue
            if resp.status_code >= 400:
                raise ServiceError(self.service, resp.status_code, resp.text[:2000], dict(resp.headers))
            return resp
        if last is not None and not isinstance(last, httpx.ConnectError | httpx.ConnectTimeout):
            raise ServiceError(self.service, 0, f"no answer (the request may have been processed): {last}")
        raise ServiceError(self.service, 0, f"unreachable: {last}")

    def post(self, path: str, body: BaseModel | dict[str, Any], response: type[M]) -> M:
        payload = dump(body) if isinstance(body, BaseModel) else body
        resp = self._request("POST", path, json=payload)
        return response.model_validate(resp.json())

    def post_raw(
        self, path: str, body: BaseModel | dict[str, Any], headers: dict[str, str] | None = None
    ) -> httpx.Response:
        payload = dump(body) if isinstance(body, BaseModel) else body
        return self._request("POST", path, json=payload, headers=headers or {})

    def get(self, path: str, response: type[M]) -> M:
        return response.model_validate(self._request("GET", path).json())

    def get_json(self, path: str) -> Any:
        return self._request("GET", path).json()

    def healthy(self) -> bool:
        try:  # /healthz is open on every service; no token needed
            return self.client.get(f"{self.base_url}/healthz", timeout=5).status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self.client.close()


# ------------------------------------------------------------------------------------------ SSRF guard (T-212d, D-450)
# Every outbound HTTP call whose address a person or an outside document can set goes through guarded_client(): the
# REDCap URL an administrator types (S36), the OIDC provider's discovery document and the endpoints it names, the
# public registry (ClinicalTrials.gov, live mode) and the NHI endpoint. The guard decides on the address the call is
# about to connect to, resolved at that moment, and the connection goes to exactly that address (the name stays in
# the Host header and the TLS server name), so a name that resolves to a public address when it is checked and to
# the box when it is used (DNS rebinding) cannot pass. Every redirect hop is checked again (the client asks the
# transport once per hop).

#: never a destination, declared or not: the cloud instance-metadata services (169.254.169.254 for AWS, GCP, Azure
#: and OpenStack, fd00:ec2::254 AWS IPv6, 100.100.100.200 Alibaba, 169.254.170.2 ECS task credentials, 192.0.0.192
#: Oracle classic)
METADATA_ADDRESSES = frozenset(
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "fd00:ec2::254", "100.100.100.200", "169.254.170.2", "192.0.0.192")
)
#: classes refused even when the destination is declared: nothing legitimate lives there
NEVER = ("metadata", "link_local", "unspecified", "multicast", "broadcast")
#: the classes that are not public and not NEVER: used only when the destination is declared
DECLARABLE = ("loopback", "private", "shared", "reserved")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SHARED = ipaddress.ip_network("100.64.0.0/10")
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")
CTGOV_HOST = ("clinicaltrials.gov", 443)  # deploy/egress.py CTGOV


class EgressRefused(httpx.ConnectError):
    """An outbound call the guard refused before any connection was made (so nothing was sent). ``reason`` is one of
    ``scheme``, ``http_outside_dev``, ``no_host``, ``odd_address``, ``does_not_resolve`` or an address class
    (``loopback``, ``private``, ``link_local``, ``metadata`` ...)."""

    def __init__(self, host: str, reason: str, detail: str, request: httpx.Request | None = None) -> None:
        super().__init__(f"egress refused ({reason}): {detail}", request=request)
        self.host = host
        self.reason = reason


def _unwrap(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """The IPv4 address an IPv6 spelling carries (IPv4-mapped, 6to4, Teredo client, NAT64), else ``ip`` itself."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
        if ip.teredo is not None:
            return ip.teredo[1]
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def address_class(addr: str) -> str:
    """``public`` for a global unicast address, else what it is: ``metadata``, ``loopback``, ``link_local``,
    ``private`` (the box's networks and the hospital LAN), ``shared`` (carrier NAT), ``unspecified``, ``multicast``,
    ``broadcast``, ``reserved``; ``invalid`` for something that is not an address."""
    try:
        raw = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return "invalid"
    ip = _unwrap(raw)
    if raw in METADATA_ADDRESSES or ip in METADATA_ADDRESSES:
        return "metadata"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_multicast:
        return "multicast"
    if isinstance(ip, ipaddress.IPv4Address) and ip == ipaddress.IPv4Address("255.255.255.255"):
        return "broadcast"
    if ip in _SHARED:
        return "shared"
    if isinstance(ip, ipaddress.IPv6Address) and ip in _SITE_LOCAL:
        return "private"
    if ip.is_private:
        return "private"
    if ip.is_reserved or not ip.is_global:
        return "reserved"
    return "public"


def _odd_ipv4(host: str) -> bool:
    """A host the C resolver reads as an IPv4 address although it is not written the usual way (``2130706433``,
    ``0x7f000001``, ``0177.0.0.1``, ``127.1``): never a legitimate destination, always refused."""
    try:
        packed = socket.inet_aton(host)
    except (OSError, ValueError):
        return False
    return host != socket.inet_ntoa(packed)


def _hostport(value: str, default_port: int) -> tuple[str, int] | None:
    if not value:
        return None
    if "://" in value:
        u = urlparse(value)
        if not u.hostname:
            return None
        return u.hostname.lower().rstrip("."), u.port or (443 if u.scheme == "https" else 80)
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        return value.lower().rstrip("."), default_port
    return host.strip("[]").lower().rstrip("."), int(port)


def declared_egress(service: str, env: Mapping[str, str] | None = None) -> set[tuple[str, int]]:
    """The destinations ``service`` is declared to reach: its rows of the box's egress table (``deploy/egress.py``,
    read from the same settings, without the gateway's model endpoints, which the gateway's own perimeter check
    governs, T-604). A test holds the two tables together."""
    e = os.environ if env is None else env
    out: set[tuple[str, int]] = set()
    if service == "mail-gateway":
        for host, port, dflt in (("SMTP_HOST", "SMTP_PORT", 587), ("IMAP_HOST", "IMAP_PORT", 993)):
            if e.get(host):
                out.add((e[host].lower().rstrip("."), int(e.get(port) or dflt)))
    if service == "criteria-compiler" and (e.get("TB_CTGOV_MODE") or "offline").lower() == "live":
        out.add(CTGOV_HOST)
    if service == "orchestrator":
        nhi = _hostport(e.get("NHI_TWPAS_BASE_URL") or "", 443)
        if nhi:
            out.add(nhi)
    for item in filter(None, (x.strip() for x in (e.get("EGRESS_EXTRA") or "").split(","))):
        svc, _, hp = item.partition("=")
        host, _, port = hp.rpartition(":")
        if svc.strip() == service and host and port.isdigit():
            out.add((host.strip().lower().rstrip("."), int(port)))
    return out


Resolver = Callable[[str, int], list[str]]


def resolve_now(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to at this moment (an address literal is itself)."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return []
    seen: list[str] = []
    for info in infos:
        a = str(info[4][0])
        if a not in seen:
            seen.append(a)
    return seen


class EgressGuard:
    """The rule (D-450). A call goes out only when:

    * the scheme is ``https`` (``http`` too with ``TB_ENV`` DEV or TEST);
    * the host is not an odd spelling of an IPv4 address and resolves now;
    * no address it resolves to is a metadata, link-local, unspecified, multicast or broadcast address;
    * an address that is not public (loopback, the box's own networks, the LAN, carrier NAT, reserved) is used only
      when the destination (host and port) is declared: on the egress table of the calling service, or named by the
      operator's own setting for this caller (``extra``, e.g. the OIDC issuer).
    """

    def __init__(
        self,
        service: str,
        extra: Iterable[tuple[str, int]] = (),
        env: Mapping[str, str] | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        from tb_common.config import environment_name

        e = os.environ if env is None else env
        self.service = service
        self.declared = declared_egress(service, e) | {(h.lower().rstrip("."), int(p)) for h, p in extra}
        self.environment = environment_name(e)
        self.resolver = resolver or resolve_now
        self.log = logging.getLogger("tb.egress")

    def _refuse(self, host: str, reason: str, detail: str, request: httpx.Request | None) -> EgressRefused:
        self.log.warning("egress refused", extra={"egress_host": host, "reason": reason, "caller": self.service})
        return EgressRefused(host, reason, detail, request)

    def check(self, url: httpx.URL | str, request: httpx.Request | None = None) -> str:
        """The address to connect to for ``url``; :class:`EgressRefused` when the call may not go out."""
        raw_host = (urlparse(str(url)).hostname or "").rstrip(".")
        if raw_host and _odd_ipv4(raw_host):
            why = f"{raw_host} is an IPv4 address written an unusual way"
            raise self._refuse(raw_host, "odd_address", why, request)
        try:
            u = httpx.URL(str(url))
        except httpx.InvalidURL as exc:
            raise self._refuse(raw_host, "bad_url", f"not a valid address ({exc})", request) from exc
        scheme = u.scheme.lower()
        host = (u.host or "").lower().rstrip(".")
        if scheme not in ("http", "https"):
            raise self._refuse(host, "scheme", f"{scheme}:// is not an HTTP address", request)
        if scheme == "http" and self.environment not in ("DEV", "TEST"):
            raise self._refuse(host, "http_outside_dev", f"http://{host} outside DEV and TEST (https only)", request)
        if not host:
            raise self._refuse(host, "no_host", "the address has no host", request)
        if _odd_ipv4(host):  # after httpx's own parsing too
            raise self._refuse(host, "odd_address", f"{host} is an IPv4 address written an unusual way", request)
        port = u.port or (443 if scheme == "https" else 80)
        declared = (host, port) in self.declared
        addrs = self.resolver(host, port)
        if not addrs:
            raise self._refuse(host, "does_not_resolve", f"{host} does not resolve", request)
        for a in addrs:
            cls = address_class(a)
            if cls in NEVER or cls == "invalid":
                raise self._refuse(host, cls, f"{host} resolves to {a} ({cls}): never a destination", request)
            if cls != "public" and not declared:
                raise self._refuse(
                    host, cls, f"{host}:{port} resolves to {a} ({cls}) and is not on the egress table of "
                    f"{self.service}", request,
                )  # fmt: skip
        return addrs[0]


class GuardedTransport(httpx.BaseTransport):
    """Checks every request (and so every redirect hop) with the guard, then connects to the address it checked."""

    def __init__(self, guard: EgressGuard, inner: httpx.BaseTransport | None = None, verify: Any = True) -> None:
        self.guard = guard
        self.inner = inner if inner is not None else httpx.HTTPTransport(verify=verify, trust_env=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        addr = self.guard.check(request.url, request)
        host = request.url.host
        ext = dict(request.extensions)
        if request.url.scheme == "https" and host != addr:
            ext["sni_hostname"] = host  # the certificate is checked against the name, not the address
        pinned = httpx.Request(
            request.method, request.url.copy_with(host=addr), headers=request.headers, stream=request.stream,
            extensions=ext,
        )  # fmt: skip
        return self.inner.handle_request(pinned)

    def close(self) -> None:
        self.inner.close()


def guarded_client(
    service: str | None = None,
    *,
    extra: Iterable[tuple[str, int]] = (),
    env: Mapping[str, str] | None = None,
    resolver: Resolver | None = None,
    inner: httpx.BaseTransport | None = None,
    verify: Any = True,
    timeout: Any = 30.0,
    follow_redirects: bool = False,
) -> httpx.Client:
    """The HTTP client for a call a person or an outside document can steer (D-450). ``service``: whose egress
    table applies (default ``TB_SERVICE_NAME``). The proxy variables of the environment are not used: a proxy would
    connect on the guard's behalf to whatever it is told."""
    e = os.environ if env is None else env
    guard = EgressGuard(service or e.get("TB_SERVICE_NAME") or "", extra, e, resolver)
    return httpx.Client(
        transport=GuardedTransport(guard, inner, verify), timeout=timeout, follow_redirects=follow_redirects,
        trust_env=False,
    )  # fmt: skip


def declared_client(url: str, service: str | None = None, **kw: Any) -> httpx.Client:
    """:func:`guarded_client` with ``url``'s own host and port declared, as the operator who set that URL declared it
    (P-13 ruling, the EDC tool door): a metadata or link-local address, any other host, or ``http`` outside DEV and
    TEST is still refused."""
    u = urlparse(url)
    extra = [(u.hostname, u.port or (443 if u.scheme == "https" else 80))] if u.hostname else []
    return guarded_client(service, extra=extra, **kw)
