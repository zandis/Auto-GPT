"""FastAPI app factory (``/healthz``, JSON errors, request logs), a typed inter-service client, and the one guard for
outbound calls a person or an outside document can steer (T-212d, D-450: :func:`guarded_client`)."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from tb_contracts import dump

from tb_common.logging import setup_logging

M = TypeVar("M", bound=BaseModel)
HealthCheck = Callable[[], dict[str, Any]]
RouteGate = Callable[[Request, str | None], Response | None]
VERSION = "1.0.0"


class ServiceError(RuntimeError):
    def __init__(self, service: str, status: int, detail: str) -> None:
        super().__init__(f"{service} returned {status}: {detail}")
        self.service = service
        self.status = status
        self.detail = detail


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
        except Exception:
            log.exception("unhandled error", extra={"path": request.url.path})
            return JSONResponse({"error": "internal error"}, status_code=500)
        if request.url.path != "/healthz":
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
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
                raise ServiceError(self.service, resp.status_code, resp.text[:2000])
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
