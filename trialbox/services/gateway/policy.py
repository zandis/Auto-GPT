"""Routing policy for tb-gateway (spec v4 §8.5, LLM-11, LLM-12; S1-06).

Loads ``models/routing.yaml`` and answers *which candidates may serve this call*. Every candidate is checked with
:func:`tb_common.policy.classes.may_reach` (the single boundary rule, §7.2) and the environment ceiling
(:func:`check_env`) at lookup time, so a wrong row in the file cannot route D3/D4 outside the perimeter.
:func:`violations` lints the file itself; the shipped policy must have none.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import os
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from tb_common.policy.classes import Destination, Environment, PolicyError, Topology, check_env, may_reach
from tb_contracts.dataclass import ClassLabel, D2Variant, DataClass

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO / "models" / "routing.yaml"

ZONES: dict[str, Destination] = {
    "perimeter": Destination.PERIMETER,
    "tre": Destination.TRE,
    "external": Destination.EXTERNAL_MODEL,
    "dev_public": Destination.DEV_PUBLIC,
}
EXTERNAL_CONDITIONS = ("processing_geography", "retention", "training_use")
# token identities of tb_common.service_auth (OPERATOR, LEGACY), repeated so this module needs no tb_common import
OPERATOR = "operator"
LEGACY = "legacy"
SANDBOX_ENVS = ("DEV", "TEST")  # synthetic data only: a call without a service identity is believed (D-437)


def endpoint_key(name: str, env: Mapping[str, str] | None = None) -> str:
    """The value of an endpoint's key setting ``name`` (``api_key_env``): the file ``<name>_FILE`` names (a compose
    secret, D-437) first, else the variable itself; "" when neither gives one."""
    e = os.environ if env is None else env
    path = (e.get(f"{name}_FILE") or "").strip() if name else ""
    if path:
        try:
            got = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            got = ""
        if got:
            return got
    return (e.get(name) or "").strip() if name else ""


class Refusal(PermissionError):
    """A policy step refused the call. ``reason`` is the stable code returned with HTTP 403 and audited."""

    def __init__(self, reason: str, message: str, status: int = 403, upstream_kinds: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status
        # D-728: what the model servers did (``timeout``, ``retried``, ``busy``, ``open``, ``other``), sorted, when
        # the refusal came from them; empty for a refusal the gateway made before sending anything
        self.upstream_kinds = upstream_kinds


def parse_label(tag: str | None) -> ClassLabel:
    """``D0``…``D4``, ``D2-K``/``D2-L``, optional ``+sc`` suffix. Anything else is refused (fail closed)."""
    if not tag:
        raise Refusal("class_missing", "X-TB-Data-Class is required")
    t = tag.strip()
    sc = t.endswith("+sc")
    if sc:
        t = t[:-3]
    base, _, variant = t.partition("-")
    if base not in DataClass.__members__:
        raise Refusal("class_invalid", f"unknown data class {tag!r}")
    dc = DataClass(base)
    v: D2Variant | None = None
    if variant:
        if dc != DataClass.D2 or variant not in ("K", "L"):
            raise Refusal("class_invalid", f"unknown data class {tag!r}")
        v = D2Variant(variant)
    elif dc == DataClass.D2:
        v = D2Variant.KEYED  # an unqualified D2 is treated as the stricter keyed variant
    return ClassLabel(data_class=dc, d2_variant=v, special_category=sc)


@dataclass(frozen=True)
class Endpoint:
    name: str
    zone: str
    url_env: str = ""
    default_url: str = ""
    api_key_env: str = ""
    environments: tuple[str, ...] = ()
    g5_record: str | None = "builtin"
    conditions: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, float] = field(default_factory=dict)

    @property
    def destination(self) -> Destination:
        return ZONES[self.zone]

    def url(self, env: dict[str, str] | None = None) -> str:
        e = os.environ if env is None else env
        return (e.get(self.url_env) if self.url_env else None) or self.default_url

    def host_port(self, env: dict[str, str] | None = None) -> tuple[str, int] | None:
        u = urlparse(self.url(env))
        if not u.hostname:
            return None
        return u.hostname, u.port or (443 if u.scheme == "https" else 80)


@dataclass(frozen=True)
class Candidate:
    alias: str
    endpoint: Endpoint
    route_id: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class Route:
    id: str
    roles: tuple[str, ...]
    classes: tuple[str, ...]
    topologies: tuple[str, ...]
    environments: tuple[str, ...]
    profiles: tuple[str, ...]
    builds: tuple[tuple[str, str], ...]  # (alias, endpoint name)
    external_requires: tuple[str, ...] = ()
    # D-276 (review LLM-002): "none" = a failed build is an error, never another alias's answer; always so for the
    # ``patient`` roles (:meth:`RoutingPolicy.no_fallback`). T-601 (review LLM-003): "none" is also the default for
    # a route that does not say ``fallback: any``
    fallback: str = "none"


@dataclass(frozen=True)
class Caller:
    name: str
    roles: tuple[str, ...]
    purposes: tuple[str, ...]
    # conversation engines only (FR-CONV-8): a D3 call on ``intake_role`` needs no study step (it precedes one)
    d3_intake_without_step: bool = False
    intake_role: str = ""


@dataclass(frozen=True)
class BoxPhi:
    """``phi_on_box`` (D-142): D3 calls the box's own policy allows without a confirmed study step, because on an
    on-prem box the perimeter endpoints are the box itself. Only topology A and class D3 are accepted."""

    topologies: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    callers: tuple[str, ...] = ()

    def allows(self, caller: str, label: ClassLabel, topology: Topology, env: Environment) -> bool:
        return (
            caller in self.callers
            and label.tag.removesuffix("+sc") in self.classes
            and topology.value in self.topologies
            and env.value in self.environments
        )


def _match(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(value, p) for p in patterns)


class RoutingPolicy:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.version = str(doc.get("version") or "")
        if not self.version:
            raise ValueError("routing: missing version")
        self.profiles = tuple(doc.get("profiles") or ())
        self.sampling: dict[str, Any] = dict(doc.get("sampling") or {})
        self.purposes = tuple(doc.get("purposes") or ())
        self.roles: dict[str, dict[str, Any]] = {str(k): dict(v or {}) for k, v in (doc.get("roles") or {}).items()}
        self.groups: dict[str, list[str]] = {}
        for role, spec in self.roles.items():
            self.groups.setdefault(str(spec.get("group", "")), []).append(role)
        # D-276 (review R2-01): calls whose answers check one another (the consent explainer's draft, translation and
        # second-model check) never fall back either: a failed draft build answered by the checker checks itself
        self.no_fallback_contexts = frozenset(str(x) for x in doc.get("no_fallback_contexts") or ())
        self.endpoints: dict[str, Endpoint] = {}
        for name, raw in (doc.get("endpoints") or {}).items():
            zone = str(raw.get("zone"))
            if zone not in ZONES:
                raise ValueError(f"routing: endpoint {name} has unknown zone {zone!r}")
            self.endpoints[name] = Endpoint(
                name=name,
                zone=zone,
                url_env=str(raw.get("url_env") or ""),
                default_url=str(raw.get("default_url") or ""),
                api_key_env=str(raw.get("api_key_env") or ""),
                environments=tuple(raw.get("environments") or ()),
                g5_record=raw.get("g5_record", "builtin"),
                conditions=dict(raw.get("conditions") or {}),
                cost={k: float(v) for k, v in (raw.get("cost") or {}).items()},
            )
        self.callers: dict[str, Caller] = {}
        for n, c in (doc.get("callers") or {}).items():
            caller = Caller(
                str(n),
                tuple(c.get("roles") or ()),
                tuple(c.get("purposes") or ()),
                d3_intake_without_step=c.get("d3_intake_without_step") is True,
                intake_role=str(c.get("intake_role") or ""),
            )
            if caller.d3_intake_without_step and not (
                caller.intake_role in self.roles and caller.intake_role in caller.roles
            ):
                raise ValueError(f"routing: caller {n}: d3_intake_without_step needs one of its roles as intake_role")
            self.callers[caller.name] = caller
        box = dict(doc.get("phi_on_box") or {})
        self.box_phi = BoxPhi(
            topologies=tuple(str(x) for x in box.get("topologies") or ()),
            environments=tuple(str(x) for x in box.get("environments") or ()),
            classes=tuple(str(x) for x in box.get("classes") or ()),
            callers=tuple(str(x) for x in box.get("callers") or ()),
        )
        if set(self.box_phi.topologies) - {Topology.A.value} or set(self.box_phi.classes) - {DataClass.D3.value}:
            raise ValueError("routing: phi_on_box is for D3 on an on-prem box (topology A) only")
        unknown = [c for c in self.box_phi.callers if c not in self.callers]
        if unknown:
            raise ValueError(f"routing: phi_on_box names unknown callers {unknown}")
        # T-212b (D-437, CR-040): the caller names each verified service (the identity of its service token) may claim
        # in X-TB-Caller; "*" (any caller) only for the administrator's host token
        self.service_callers: dict[str, tuple[str, ...]] = {}
        for svc, names in (doc.get("service_callers") or {}).items():
            got = tuple(str(x) for x in names or ())
            if "*" in got and str(svc) != OPERATOR:
                raise ValueError(f"routing: service_callers {svc}: only {OPERATOR} may claim any caller")
            bad = [n for n in got if n != "*" and n not in self.callers]
            if bad:
                raise ValueError(f"routing: service_callers {svc} names unknown callers {bad}")
            self.service_callers[str(svc)] = got
        # the verified services that may wake, sleep and hold the one-GPU swap (/v1/serving/activate, release)
        self.serving_control = frozenset(str(x) for x in doc.get("serving_control") or ())
        bad_sc = sorted(self.serving_control - set(self.service_callers))
        if bad_sc:
            raise ValueError(f"routing: serving_control names services without service_callers {bad_sc}")
        self.routes: list[Route] = []
        for raw in doc.get("routes") or []:
            builds: list[tuple[str, str]] = []
            for item in raw.get("builds") or []:
                alias, _, ep = str(item).partition("@")
                if ep not in self.endpoints:
                    raise ValueError(f"routing: route {raw.get('id')} names unknown endpoint {ep!r}")
                builds.append((alias, ep))
            roles = tuple(self._expand(raw.get("roles") or ()))
            patient = set(self.groups.get("patient", []))
            fallback = str(raw.get("fallback") or "none")  # T-601: another alias answers only where a route says so
            if fallback not in ("none", "any"):
                raise ValueError(f"routing: route {raw.get('id')} fallback must be none or any, not {fallback!r}")
            # review R2-03: a route that serves any patient role may not say "any" (its patient roles never fall back
            # whatever it says: :meth:`no_fallback`)
            if raw.get("fallback") == "any" and set(roles) & patient:
                raise ValueError(f"routing: route {raw.get('id')} serves the patient group: fallback must be none")
            self.routes.append(
                Route(
                    id=str(raw["id"]),
                    roles=roles,
                    classes=tuple(raw.get("classes") or ()),
                    topologies=tuple(raw.get("topologies") or ()),
                    environments=tuple(raw.get("environments") or ()),
                    profiles=tuple(raw.get("profiles") or ()),
                    builds=tuple(builds),
                    external_requires=tuple(raw.get("external_requires") or ()),
                    fallback=fallback,
                )
            )

    def no_fallback(self, route: Route, role: str, context_of_use: str = "") -> bool:
        """Whether a failed build of this call is final (no other alias answers instead): the route says so, the
        role is in the ``patient`` group, whose answers decide about patients (D-276, review LLM-002), or the call's
        context of use is one whose answer a second model checks (``no_fallback_contexts``, review R2-01)."""
        return (
            route.fallback == "none"
            or role in self.groups.get("patient", [])
            or context_of_use in self.no_fallback_contexts
        )

    def _expand(self, roles: Any) -> list[str]:
        out: list[str] = []
        for r in roles:
            r = str(r)
            if r.startswith("@"):
                if r[1:] not in self.groups:
                    raise ValueError(f"routing: unknown role group {r}")
                out.extend(self.groups[r[1:]])
            else:
                out.append(r)
        return out

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> RoutingPolicy:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    # ------------------------------------------------------------------------------------------------ lookups
    def known_role(self, role: str) -> bool:
        if role.startswith("shadow:"):
            return role.removeprefix("shadow:") in self.roles
        return role in self.roles

    def check_claim(
        self, service: str | None, caller: str, environment: Environment, *, auth_open: bool = False
    ) -> None:
        """T-212b (D-437, CR-040): may the verified ``service`` (the token's identity, :mod:`tb_common.service_auth`)
        call as ``caller``? With no identity (no token on the box, or the old shared token) only DEV and TEST believe
        the header; everywhere else it is refused, as is a name outside ``service_callers``. ``auth_open``: the
        service-token layer runs open (no token configured, ``TB_ENV`` DEV or TEST: ``service_auth`` admits such a
        call nowhere else), so a call without an identity (``service`` None) is believed too."""
        if not service or service == LEGACY:
            if environment.value in SANDBOX_ENVS or (service is None and auth_open):
                return
            raise Refusal(
                "caller_unverified",
                f"the gateway cannot tell which service called as {caller!r} (no per-service token): run "
                "`trialbox secrets init` or `trialbox secrets rotate` (D-138, D-437)",
            )
        allowed = self.service_callers.get(service, ())
        if caller not in allowed and "*" not in allowed:
            raise Refusal("caller_unverified", f"service {service} may not call the gateway as {caller!r}")

    def check_caller(self, caller: str | None, role: str, purpose: str) -> Caller:
        if not caller or caller not in self.callers:
            raise Refusal("caller_unknown", f"caller {caller!r} is not on the gateway allowlist")
        c = self.callers[caller]
        if not self.known_role(role):
            raise Refusal("role_unknown", f"role {role!r} is not in the role table (§8.15)")
        if not _match(role, c.roles):
            raise Refusal("role_not_allowed", f"caller {caller} may not use role {role}")
        if not _match(purpose, self.purposes) or not _match(purpose, c.purposes):
            raise Refusal("purpose_not_allowed", f"caller {caller} may not use purpose {purpose!r}")
        return c

    def route(self, role: str, label: ClassLabel, topology: Topology, env: Environment, profile: str) -> Route | None:
        """The first route whose row matches; ``None`` when no row matches (the caller then refuses)."""
        tag = label.tag.removesuffix("+sc")
        for r in self.routes:
            if (
                _match(role, r.roles)
                and tag in r.classes
                and topology.value in r.topologies
                and env.value in r.environments
                and (not r.profiles or profile in r.profiles)
            ):
                return r
        return None

    def candidates(
        self,
        role: str,
        label: ClassLabel,
        topology: Topology,
        env: Environment,
        profile: str,
        *,
        cloud_opt_in: bool = False,
        flags: frozenset[str] = frozenset(),
    ) -> tuple[Route, list[Candidate]]:
        """Ordered candidates permitted for this call. Raises :class:`Refusal` with ``no_route`` when no row
        matches and ``class_route_mismatch`` when a row matches but none of its builds may receive the class."""
        try:
            check_env(label, env)
        except PolicyError as e:
            raise Refusal("class_not_allowed_in_env", str(e)) from e
        r = self.route(role, label, topology, env, profile)
        if r is None:
            raise Refusal("no_route", f"no route for role={role} class={label.tag} topology={topology} env={env}")
        out: list[Candidate] = []
        for alias, ep_name in r.builds:
            ep = self.endpoints[ep_name]
            if ep.environments and env.value not in ep.environments:
                continue
            if ep.zone in ("external", "dev_public") and not ep.g5_record:
                continue  # an unapproved external endpoint is never routable
            if ep.zone in ("external", "dev_public") and role in self.groups.get("guard", []):
                continue  # guard roles are never routed outside (LLM-12 c)
            requires = r.external_requires if ep.zone == "external" else ()
            if requires and not set(requires) <= flags:
                continue
            if not may_reach(label, ep.destination, topology, cloud_opt_in=cloud_opt_in):
                continue
            out.append(Candidate(alias, ep, r.id, requires))
        if not out:
            raise Refusal("class_route_mismatch", f"route {r.id} has no endpoint allowed for class {label.tag}")
        return r, out


# ------------------------------------------------------------------------------------------------ perimeter (T-604)
# Addresses a perimeter endpoint of an on-prem box (topology A) may have: the box's own (loopback) and the private
# ranges Docker gives its networks. A TEST-NET or any public address is outside the box (review LLM-036).
BOX_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)
Resolver = Callable[[str], list[str]]


def resolve_host(host: str) -> list[str]:
    """Every address ``host`` resolves to now (an address literal is itself); empty when it does not resolve."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        return sorted({str(ai[4][0]) for ai in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except (socket.gaierror, UnicodeError):
        return []


def box_address(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    return any(ip in net for net in BOX_NETWORKS if net.version == ip.version)


@dataclass(frozen=True)
class PerimeterAddress:
    """One perimeter endpoint as resolved now: its host, the addresses, and why it is not on the box ("" when it
    is)."""

    endpoint: str
    host: str
    addresses: tuple[str, ...]
    problem: str = ""


def perimeter_addresses(
    policy: RoutingPolicy, env: Mapping[str, str], environment: str, resolver: Resolver = resolve_host
) -> list[PerimeterAddress]:
    """Every perimeter endpoint open in ``environment`` whose URL is set, resolved now (T-604, review LLM-036).

    A host is on the box when every address it resolves to is a box address (:data:`BOX_NETWORKS`). A one-label
    name that does not resolve here is a compose service name (Docker's DNS answers it on the box networks only);
    any other name that does not resolve cannot be checked, which is a problem too (fail closed)."""
    out: list[PerimeterAddress] = []
    for name, ep in sorted(policy.endpoints.items()):
        if ep.zone != "perimeter" or (ep.environments and environment not in ep.environments):
            continue
        hp = ep.host_port(dict(env))
        if hp is None:
            continue
        host = hp[0]
        addrs = tuple(resolver(host))
        problem = ""
        if not addrs:
            if "." in host or ":" in host:
                problem = f"{name}: {host} does not resolve, so it cannot be shown to be on the box"
        else:
            outside = [a for a in addrs if not box_address(a)]
            if outside:
                problem = f"{name}: {host} resolves to {', '.join(outside)}, which is not a box address"
        out.append(PerimeterAddress(name, host, addrs, problem))
    return out


def perimeter_checked(topology: Topology, env: Environment) -> bool:
    """Where the perimeter must be the box itself: PRODUCTION on topology A (on topology B the perimeter is the
    tenant's serving router, which is not on the box)."""
    return topology == Topology.A and env == Environment.PRODUCTION


def perimeter_problems(
    policy: RoutingPolicy, env: Mapping[str, str], environment: str, resolver: Resolver = resolve_host
) -> list[str]:
    return [p.problem for p in perimeter_addresses(policy, env, environment, resolver) if p.problem]


# ------------------------------------------------------------------------------------------------ lint
ALL_LABELS: tuple[ClassLabel, ...] = tuple(
    ClassLabel(data_class=dc, d2_variant=v, special_category=sc)
    for dc in DataClass
    for v in ((D2Variant.KEYED, D2Variant.DELINKED) if dc == DataClass.D2 else (None,))
    for sc in (False, True)
)


def violations(policy: RoutingPolicy) -> list[str]:
    """Rows of the file itself that break §7.2 / LLM-12 before the lookup-time filter (must be empty)."""
    out: list[str] = []
    for r in policy.routes:
        for tag in r.classes:
            label = parse_label(tag)
            for alias, ep_name in r.builds:
                ep = policy.endpoints[ep_name]
                where = f"route {r.id}: {alias}@{ep_name} ({ep.zone}) for {tag}"
                if label.data_class in (DataClass.D3, DataClass.D4) and ep.zone != "perimeter":
                    out.append(f"{where}: D3/D4 outside the perimeter")
                if ep.zone == "dev_public" and label.data_class != DataClass.D0:
                    out.append(f"{where}: dev endpoint accepts D0 only")
                if ep.zone == "dev_public" and set(r.environments) - {"DEV"}:
                    out.append(f"{where}: dev endpoint outside DEV")
                if any(x in policy.groups.get("guard", []) for x in r.roles) and ep.zone != "perimeter":
                    out.append(f"{where}: guard role routed outside")
        for _alias, ep_name in r.builds:
            ep = policy.endpoints[ep_name]
            if ep.zone in ("external", "dev_public"):
                missing = [c for c in EXTERNAL_CONDITIONS if c not in ep.conditions]
                if missing:
                    out.append(f"route {r.id}: {ep_name} lacks attribute conditions {missing}")
    return out
