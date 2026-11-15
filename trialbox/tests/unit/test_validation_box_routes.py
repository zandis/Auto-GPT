"""VALIDATION-ROUTES (D-823), the owner's blockers 1 and 2 of 2026-11-15 (lane G's first real-model accuracy run).

1. A VALIDATION box with local models runs SCREEN on public or synthetic data. The screen's judge call is labelled D3
   and VALIDATION's ceiling is D2, so every call was refused. Now, in VALIDATION only, a D3 model call may go to the
   box's own model servers (perimeter endpoints) and nowhere else; the ceiling itself (what a VALIDATION box may
   hold, doctor, testbench, eval) stays D2, and D4 stays refused.
2. A box can qualify and promote the pair. VALIDATION routes the judge and verifier when they are candidate,
   qualified or champion (PRODUCTION: champion only, unchanged); qualify's own calls (class D0) have a route in
   VALIDATION. A record made there qualifies PRODUCTION (it does not depend on the environment), so the pair is
   promoted with it (pin_model --promote) and the box then runs PRODUCTION.

The probes are lane G's ``tools.box_run validation-check`` (#649): routing and registry files only."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from gateway.policy import Refusal, RoutingPolicy, parse_label
from registry import registry as rg
from tb_common.policy.classes import ENV_CEILING, Environment, Topology
from tb_contracts.dataclass import DataClass

ROOT = Path(__file__).resolve().parents[2]
VAL, PROD = Environment.VALIDATION, Environment.PRODUCTION

pytestmark = pytest.mark.nodb


@pytest.fixture(scope="module")
def pol() -> RoutingPolicy:
    return RoutingPolicy.load(ROOT / "models" / "routing.yaml")


def _route(pol: RoutingPolicy, role: str, tag: str, env: Environment, topology: Topology = Topology.A) -> list[str]:
    _, cands = pol.candidates(role, parse_label(tag), topology, env, "P-PRO6000")
    return [f"{c.alias}@{c.endpoint.name}:{c.endpoint.zone}" for c in cands]


def test_the_screen_judge_at_d3_routes_in_validation_to_the_box_only(pol: RoutingPolicy) -> None:
    got = _route(pol, "judge", "D3", VAL)
    assert got and all(c.endswith(":perimeter") for c in got), got
    assert got[0].startswith("j-workhorse@serving")
    for role in ("second_opinion", "abstract_field", "embed"):
        assert all(c.endswith(":perimeter") for c in _route(pol, role, "D3", VAL)), role


def test_validation_still_refuses_d4_and_keeps_its_d2_ceiling(pol: RoutingPolicy) -> None:
    with pytest.raises(Refusal) as exc:
        _route(pol, "judge", "D4", VAL)
    assert exc.value.reason == "class_not_allowed_in_env"
    assert ENV_CEILING[VAL] == DataClass.D2  # what a VALIDATION box may hold: doctor, testbench and eval unchanged


def test_a_d3_call_with_no_box_endpoint_on_its_route_is_refused_in_validation(pol: RoutingPolicy) -> None:
    """Protocol work never takes D3; a route whose builds are outside the box gives nothing in VALIDATION."""
    with pytest.raises(Refusal):
        _route(pol, "extract_criteria", "D3", VAL)


def test_qualify_s_calls_route_in_validation(pol: RoutingPolicy) -> None:
    assert _route(pol, "judge", "D0", VAL)[0].startswith("j-workhorse@serving")


def test_production_is_unchanged(pol: RoutingPolicy) -> None:
    assert all(c.endswith(":perimeter") for c in _route(pol, "judge", "D3", PROD))
    with pytest.raises(Refusal):
        _route(pol, "judge", "D0", PROD)  # qualify runs on a VALIDATION box (or in TEST), never on PRODUCTION
    assert rg._status_ok(rg.Status.CANDIDATE, "judge", PROD) is False
    assert rg._status_ok(rg.Status.QUALIFIED, "judge", PROD) is False
    assert rg._status_ok(rg.Status.CHAMPION, "judge", PROD) is True


@pytest.mark.parametrize("status", ["candidate", "qualified", "champion"])
def test_validation_routes_a_candidate_qualified_or_champion_pair(status: str) -> None:
    assert rg._status_ok(rg.Status(status), "judge", VAL) is True
    assert rg._status_ok(rg.Status(status), "second_opinion", VAL) is True


@pytest.mark.parametrize("status", ["retired", "suspended"])
def test_a_retired_or_suspended_build_routes_nowhere(status: str) -> None:
    assert rg._status_ok(rg.Status(status), "judge", VAL) is False


def test_the_shipped_pair_routes_in_validation() -> None:
    """Lane G's check: every RTX PRO 6000 judge and verifier build as the registry ships it."""
    reg = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    pair = {b["build_id"]: b["status"] for b in reg["builds"]
            if str(b["build_id"]).endswith("-rtxpro6000") and b.get("alias") in ("j-workhorse", "v-verifier")}  # fmt: skip
    assert len(pair) == 2 and all(rg._status_ok(rg.Status(s), "judge", VAL) for s in pair.values()), pair


# ------------------------------------------------------------------------------------------- review (D-823)
def test_front_desk_conversation_at_d3_stays_refused_in_validation(pol: RoutingPolicy) -> None:
    """Review: the exception is the screen's (patient roles and their vectors), never the front desk's text."""
    for role in ("classify_intent", "frontdesk_converse", "ops_explain"):
        with pytest.raises(Refusal) as exc:
            _route(pol, role, "D3", VAL)
        assert exc.value.reason == "class_not_allowed_in_env", role


def test_d3_in_validation_is_topology_a_only(pol: RoutingPolicy) -> None:
    """On topology B the perimeter is the tenant's router, not the box."""
    for topo in (Topology.B, Topology.C):
        with pytest.raises(Refusal):
            _route(pol, "judge", "D3", VAL, topo)


def test_every_role_qualify_probes_routes_at_d0_on_the_box(pol: RoutingPolicy) -> None:
    """Review: qualify's schema step sends every active prompt at D0 with that prompt's role."""
    from tb_llm.prompt_registry import default_registry

    v1 = yaml.safe_load((ROOT / "libs" / "tb_llm" / "v1_roles.yaml").read_text(encoding="utf-8")) or {}
    doc = yaml.safe_load((ROOT / "eval" / "qualification" / "schema_probes.yaml").read_text(encoding="utf-8")) or {}
    probes = doc.get("probes") or {}
    roles = set()
    for e in default_registry().active_set():
        lab = {**(v1.get(e.id) or {}), **((probes.get(e.id) or {}).get("labels") or {})}
        roles.add(str(lab.get("role") or ""))
    roles.discard("")
    assert roles
    for role in roles:
        got = _route(pol, role, "D0", VAL)
        assert got and all(c.endswith(":perimeter") for c in got), (role, got)


def test_guard_roles_keep_their_own_build_at_d0(pol: RoutingPolicy) -> None:
    assert _route(pol, "guard_policy", "D0", VAL) == ["g-guard@serving:perimeter"]


def test_the_box_model_addresses_are_checked_in_validation_as_in_production() -> None:
    from gateway.policy import perimeter_checked

    assert perimeter_checked(Topology.A, VAL) and perimeter_checked(Topology.A, PROD)
    assert not perimeter_checked(Topology.B, VAL)
