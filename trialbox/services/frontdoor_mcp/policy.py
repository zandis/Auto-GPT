"""The orchestrator policy context each front-door call runs in (spec v4 §9.3 steps 2–3, §9.4; HER-15 … HER-17).

* :class:`Directory` holds principals generated from directory groups (``TB-Staff``, ``TB-Research-Office``,
  ``TB-Admin`` …, HER-16) and their study delegations. It is never editable from Hermes configuration.
* :class:`RateLimiter` applies the per-user, per-tool default limits of §9.3 with an injected clock.
* :class:`OrchestratorPolicyContext` resolves roles and delegations for a verified assertion and checks the tool's
  tier, allowed roles, channel profile and rate limit. Every refusal carries a stable reason code.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from tb_common.policy.classes import Environment
from tb_contracts.frontdoor import IdentityAssertion, Tier, ToolSpec

Clock = Callable[[], float]

# directory group -> roles (HER-16: allowlists come from directory groups, refreshed at least daily)
GROUP_ROLES: dict[str, frozenset[str]] = {
    "TB-Staff": frozenset({"staff"}),
    "TB-CRC": frozenset({"staff", "crc"}),
    "TB-PI": frozenset({"staff", "pi"}),
    "TB-Research-Office": frozenset({"staff", "research_office"}),
    "TB-Steward": frozenset({"staff", "steward"}),
    "TB-Admin": frozenset({"admin"}),
}
# channel profile -> tools it may call (§9.2 profile table): tb-staff all but ops_read; tb-line none; tb-admin three
PROFILE_TOOLS: dict[str, frozenset[str]] = {
    "email": frozenset(
        {
            "tb.submit_request",
            "tb.status",
            "tb.ask_protocol",
            "tb.registry_search",
            "tb.atlas_describe",
            "tb.aggregate_query",
            "tb.resend_released_file",
        }
    ),
    "line": frozenset(),
    "admin_tui": frozenset({"tb.ops_read", "tb.status", "tb.atlas_describe"}),
}
PROFILE_TOOLS["teams"] = PROFILE_TOOLS["email"]


class PolicyRefused(PermissionError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    sub: str
    roles: frozenset[str]
    delegations: frozenset[str] = frozenset()
    address: str = ""
    language: str = "zh-TW"


class Directory:
    def __init__(self, principals: Iterable[Principal]) -> None:
        self._by_sub = {p.sub: p for p in principals}

    @classmethod
    def from_groups(
        cls,
        groups: Mapping[str, Iterable[str]],
        *,
        delegations: Mapping[str, Iterable[str]] | None = None,
        addresses: Mapping[str, str] | None = None,
    ) -> Directory:
        roles: dict[str, set[str]] = {}
        for group, members in groups.items():
            if group not in GROUP_ROLES:
                raise ValueError(f"unknown directory group {group!r}")
            for m in members:
                roles.setdefault(m, set()).update(GROUP_ROLES[group])
        dl = delegations or {}
        ad = addresses or {}
        return cls(
            Principal(sub, frozenset(r), frozenset(dl.get(sub, ())), ad.get(sub, sub))
            for sub, r in sorted(roles.items())
        )

    def get(self, sub: str) -> Principal | None:
        return self._by_sub.get(sub)


@dataclass
class RateLimiter:
    clock: Clock
    _calls: dict[tuple[str, str], deque[float]] = field(default_factory=dict)

    def allow(self, user: str, spec: ToolSpec) -> bool:
        window = 3600.0 if spec.per == "hour" else 86400.0
        now = self.clock()
        q = self._calls.setdefault((user, spec.name), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= spec.limit:
            return False
        q.append(now)
        return True


class OrchestratorPolicyContext:
    """Steps 2–3 of §9.3 for one deployment: who the caller is, what the tool needs, whether the limit allows it."""

    def __init__(
        self,
        directory: Directory,
        limiter: RateLimiter,
        *,
        environment: Environment = Environment.TEST,
        purpose: str = "intake",
    ) -> None:
        self.directory = directory
        self.limiter = limiter
        self.environment = environment
        self.purpose = purpose

    def principal(self, claims: IdentityAssertion) -> Principal:
        p = self.directory.get(claims.sub)
        if p is None:
            raise PolicyRefused("principal_unknown", "the assertion subject is not in the directory")
        return p

    def authorise(self, claims: IdentityAssertion, spec: ToolSpec, study: str | None) -> Principal:
        p = self.principal(claims)
        if spec.tier not in (Tier.T0, Tier.T1):  # defensive: the table has no other tier (HER-1)
            raise PolicyRefused("tier_not_allowed", f"{spec.name}: tier {spec.tier} is never served")
        if spec.name not in PROFILE_TOOLS.get(claims.channel, frozenset()):
            raise PolicyRefused("profile_not_allowed", f"{spec.name} is not in the {claims.channel} profile")
        if not (p.roles & set(spec.roles)):
            raise PolicyRefused("role_not_allowed", f"{spec.name} needs one of {', '.join(spec.roles)}")
        delegated = bool(study) and study in p.delegations
        if spec.delegation == "study" and not delegated:
            raise PolicyRefused("not_delegated", f"{spec.name} needs a delegation on the study")
        # PI and CRC see aggregates of their delegated studies only (§9.3)
        if spec.name == "tb.aggregate_query" and "research_office" not in p.roles and not delegated:
            raise PolicyRefused("not_delegated", "aggregates outside the research office need a delegated study")
        if not self.limiter.allow(p.sub, spec):
            raise PolicyRefused("rate_limited", f"{spec.name}: limit of {spec.limit} per {spec.per} reached")
        return p
