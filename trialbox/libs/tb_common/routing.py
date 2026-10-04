"""Routing enforcement (SPEC §4.1, §5): ``phi`` outputs only to manifest list/referral recipients inside
``settings.internal_domains``; ``aggregate`` outputs may go anywhere routed by the manifest."""

from __future__ import annotations

from collections.abc import Iterable

from tb_contracts import Routing


class RoutingViolation(RuntimeError):
    pass


def domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].strip().lower().rstrip(">")


def is_internal(addr: str, internal_domains: Iterable[str]) -> bool:
    d = domain(addr)
    return any(d == x.lower() or d.endswith("." + x.lower()) for x in internal_domains)


def allowed_phi_recipients(routing: Routing | None, internal_domains: Iterable[str]) -> set[str]:
    if routing is None:
        return set()
    cands = set(routing.list_to or []) | set((routing.referral_to or {}).values())
    return {a.lower() for a in cands if is_internal(a, internal_domains)}


def check(tag: str, recipients: Iterable[str], routing: Routing | None, internal_domains: Iterable[str]) -> None:
    """Raise :class:`RoutingViolation` when ``recipients`` may not receive an output tagged ``tag``."""
    rcpts = [r.lower() for r in recipients]
    if not rcpts:
        raise RoutingViolation("no recipients")
    if tag == "phi":
        allowed = allowed_phi_recipients(routing, internal_domains)
        bad = [r for r in rcpts if r not in allowed]
        if bad:
            raise RoutingViolation(
                f"phi output may not be sent to {', '.join(bad)} (not an internal list/referral "
                f"recipient of this ruleset)"
            )
    elif tag != "aggregate":
        raise RoutingViolation(f"unknown output tag {tag!r}")


def check_gateway(tag: str, recipients: Iterable[str], internal_domains: Iterable[str]) -> list[str]:
    """Gateway-level rule (no manifest available): recipients outside internal domains get aggregate only."""
    if tag == "aggregate":
        return []
    return [r for r in recipients if not is_internal(r, internal_domains)]
