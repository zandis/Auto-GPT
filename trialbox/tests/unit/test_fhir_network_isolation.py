"""P2-03 (ASSESS-1-ADDENDUM D2): the FHIR store is isolated by network.

HAPI answers without authentication. On an installed box it sat on trialbox-net with every service, among them
doc-parser and embed-service, which read untrusted documents; a throwaway container on that network read Patient
resources with no token. Now the store is on its own internal network, fhir-net, and on nothing else; fhir-net is
joined only by the store, its database server and its three clients (the adapter loads it, the orchestrator and the
criteria compiler evaluate CQL on it; the compiler's container also runs the terminology load). A container that
shares no network with the store cannot open a connection to it: Docker routes nothing between its bridges, and an
internal one has no route out.

Checked in every stack a box or a developer runs, with the networks of a service merged as Compose merges them
(the union of every file's list, never the last file's alone, so an overlay cannot quietly put the store back).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_compose_limits import BASE, _active, _load
from tests.unit.test_container_hardening import HARDENING_STACKS

FHIR_NET = "fhir-net"
MEMBERS = frozenset({"fhir-store", "db", "adapter", "orchestrator", "criteria-compiler"})
# the services the audit named, and every other one of the box: none may share a network with the store
NEVER = frozenset({"doc-parser", "embed-service", "lake", "gateway", "console", "mail-gateway", "audit-writer",
                   "model-guard", "llm-service", "llm-verifier", "llm-stub", "caddy"})  # fmt: skip


def _names(nets: Any) -> set[str]:
    return set(nets) if isinstance(nets, (list, dict)) else set()


def _networks(stack: tuple[str, ...], profiles: tuple[str, ...]) -> dict[str, set[str]]:
    """service -> its networks in the stack (Compose's merge: the union of each file's list; no list = default)."""
    out: dict[str, set[str]] = {}
    active: dict[str, bool] = {}
    for name in stack:
        for svc, body in (_load(name).get("services") or {}).items():
            body = body or {}
            out.setdefault(svc, set()).update(_names(body.get("networks")))
            if "profiles" in body or svc not in active:
                active[svc] = _active(body, profiles)
    return {s: (n or {"default"}) for s, n in out.items() if active.get(s)}  # the &py anchor's list is in each body


@pytest.mark.parametrize(
    ("stack", "profiles"), HARDENING_STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x
)
def test_only_the_store_and_its_clients_share_a_network(stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    nets = _networks(stack, profiles)
    if "fhir-store" not in nets:
        return
    store = nets["fhir-store"] - {"host-net"}  # the developer stack's published port (docker-compose.test.yml)
    assert store == {FHIR_NET}, stack
    reach = {s for s, n in nets.items() if s != "fhir-store" and n & nets["fhir-store"] - {"host-net"}}
    assert reach <= MEMBERS, (stack, reach - MEMBERS)
    assert not reach & NEVER, stack
    assert {c for c in ("adapter", "orchestrator", "criteria-compiler", "db") if c in nets} <= reach, stack


def test_fhir_net_is_internal_and_named_per_project() -> None:
    net = _load(BASE)["networks"][FHIR_NET]
    assert net["internal"] is True
    assert net["name"] == "${COMPOSE_PROJECT_NAME:-trialbox}-fhir"


def test_doc_parser_and_embed_service_cannot_reach_the_store_in_the_base_stack() -> None:
    nets = _networks((BASE,), ("stub", "gpu"))
    for svc in ("doc-parser", "embed-service"):
        assert not nets[svc] & nets["fhir-store"], svc
