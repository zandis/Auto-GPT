"""Routing policy for tb-gateway (spec v4 §8.5, LLM-11, LLM-12; S1-06).

Loads ``models/routing.yaml`` and answers *which candidates may serve this call*. Every candidate is checked with
:func:`tb_common.policy.classes.may_reach` (the single boundary rule, §7.2) and the environment ceiling
(:func:`check_env`) at lookup time, so a wrong row in the file cannot route D3/D4 outside the perimeter.
:func:`violations` lints the file itself; the shipped policy must have none.
"""

from __future__ import annotations

import fnmatch
import os
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


class Refusal(PermissionError):
    """A policy step refused the call. ``reason`` is the stable code returned with HTTP 403 and audited."""

    def __init__(self, reason: str, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status


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


@dataclass(frozen=True)
class Caller:
    name: str
    roles: tuple[str, ...]
    purposes: tuple[str, ...]
    # conversation engines only (FR-CONV-8): a D3 call on ``intake_role`` needs no study step (it precedes one)
    d3_intake_without_step: bool = False
    intake_role: str = ""


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
        self.routes: list[Route] = []
        for raw in doc.get("routes") or []:
            builds: list[tuple[str, str]] = []
            for item in raw.get("builds") or []:
                alias, _, ep = str(item).partition("@")
                if ep not in self.endpoints:
                    raise ValueError(f"routing: route {raw.get('id')} names unknown endpoint {ep!r}")
                builds.append((alias, ep))
            self.routes.append(
                Route(
                    id=str(raw["id"]),
                    roles=tuple(self._expand(raw.get("roles") or ())),
                    classes=tuple(raw.get("classes") or ()),
                    topologies=tuple(raw.get("topologies") or ()),
                    environments=tuple(raw.get("environments") or ()),
                    profiles=tuple(raw.get("profiles") or ()),
                    builds=tuple(builds),
                    external_requires=tuple(raw.get("external_requires") or ()),
                )
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
