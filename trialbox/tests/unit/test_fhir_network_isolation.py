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
from tools import network_sheet

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


CLIENTS = ("adapter", "orchestrator", "criteria-compiler", "db")
TEST_STACK = "docker-compose.test.yml"  # its harness publishes the store's port on fhir-host-net, the store alone on it


def check(stack: tuple[str, ...], nets: dict[str, set[str]]) -> None:
    """Every stack built on the base file runs the store and its four clients (a profile or an overlay that drops one
    fails here, it does not pass unchecked); the store is on fhir-net only, plus fhir-host-net in the test stack."""
    if BASE not in stack:
        assert "fhir-store" not in nets, stack
        return
    assert "fhir-store" in nets, stack
    assert set(CLIENTS) <= set(nets), (stack, set(CLIENTS) - set(nets))
    assert nets["fhir-store"] == ({FHIR_NET, "fhir-host-net"} if TEST_STACK in stack else {FHIR_NET}), stack
    reach = {s for s, n in nets.items() if s != "fhir-store" and n & nets["fhir-store"]}
    assert reach <= MEMBERS, (stack, reach - MEMBERS)
    assert not reach & NEVER, stack
    assert set(CLIENTS) <= reach, stack


@pytest.mark.parametrize(
    ("stack", "profiles"), HARDENING_STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x
)
def test_only_the_store_and_its_clients_share_a_network(stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    check(stack, _networks(stack, profiles))


PROD = (BASE, "docker-compose.secrets.yml")


@pytest.mark.parametrize(
    ("stack", "mutate"),
    [
        (PROD, lambda n: n["fhir-store"].add("fhir-host-net")),  # the test stack's published network in production
        (PROD, lambda n: n.pop("fhir-store")),  # the store behind a profile that is off
        (PROD, lambda n: n.pop("adapter")),  # a client behind a profile that is off
        (PROD, lambda n: n["orchestrator"].discard(FHIR_NET)),  # a client off fhir-net
        (PROD, lambda n: n["doc-parser"].add(FHIR_NET)),  # the audit's untrusted-document reader back on it
        ((BASE, TEST_STACK), lambda n: n["lake"].add("fhir-host-net")),  # another service on the published network
        (("docker-compose.testbench.yml",), lambda n: n.setdefault("fhir-store", {FHIR_NET})),  # a store unchecked
    ],
    ids=["host-net-in-prod", "store-off", "client-off", "client-off-net", "reader-on", "lake-on-host", "bench-store"],
)
def test_the_check_fails_each_way_the_store_could_escape_it(stack: tuple[str, ...], mutate: Any) -> None:
    """#1597 review r1 (R2, R3; L1, L2): each mutation of a clean stack's networks must fail the check."""
    nets = _networks(stack, ("stub", "test")) if BASE in stack else {}
    mutate(nets)
    with pytest.raises(AssertionError):
        check(stack, nets)


def test_fhir_net_is_internal_and_named_per_project() -> None:
    net = _load(BASE)["networks"][FHIR_NET]
    assert net["internal"] is True
    assert net["name"] == "${COMPOSE_PROJECT_NAME:-trialbox}-fhir"


def test_doc_parser_and_embed_service_cannot_reach_the_store_in_the_base_stack() -> None:
    nets = _networks((BASE,), ("stub", "gpu"))
    for svc in ("doc-parser", "embed-service"):
        assert not nets[svc] & nets["fhir-store"], svc


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_network_sheet_names_every_service_that_can_reach_the_store(lang: str) -> None:
    """#1597 review r1 (R4): hospital IT reads the store's peers from the sheet; db joins fhir-net too."""
    nets = _networks((BASE,), ("stub", "gpu"))
    peers = {s for s, n in nets.items() if s != "fhir-store" and n & nets["fhir-store"]}
    row = network_sheet.who(network_sheet.Service(name="fhir-store"), lang)
    assert {s for s in peers if s not in row} == set(), lang
