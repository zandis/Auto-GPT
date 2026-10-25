"""Routing policy property tests (spec v4 §8.5, LLM-4, LLM-12, PRIV-15; S1-06 done-criterion).

Exhaustive over every (role, class label, hardware profile, topology, environment, cloud opt-in, flags) of the
shipped ``models/routing.yaml``, plus every failure/fallback prefix of each candidate list, plus a seeded fuzz of
random (deliberately wrong) routing documents: no D3/D4 call ever gets a candidate outside the perimeter.
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path
from typing import Any

import pytest
import yaml
from gateway.policy import ALL_LABELS, Refusal, RoutingPolicy, parse_label, violations
from tb_common.policy.classes import Environment, Topology
from tb_contracts.dataclass import ClassLabel, D2Variant, DataClass

ROOT = Path(__file__).resolve().parents[2]
POLICY = RoutingPolicy.load(ROOT / "models" / "routing.yaml")
FLAG_SETS: tuple[frozenset[str], ...] = (frozenset(), frozenset({"sponsor_consent"}))


def _roles(policy: RoutingPolicy) -> list[str]:
    return [*policy.roles, *(f"shadow:{r}" for r in policy.roles), "unknown_role"]


def _all_candidates(policy: RoutingPolicy) -> list[tuple[str, ClassLabel, str, Topology, Environment, list[Any]]]:
    out = []
    for role, label, profile, topo, env, opt_in, flags in itertools.product(
        _roles(policy),
        ALL_LABELS,
        policy.profiles,
        Topology,
        Environment,
        (False, True),
        FLAG_SETS,
    ):
        try:
            _, cands = policy.candidates(role, label, topo, env, profile, cloud_opt_in=opt_in, flags=flags)
        except Refusal:
            continue
        out.append((role, label, profile, topo, env, cands))
    return out


ALL = _all_candidates(POLICY)


@pytest.mark.req("LLM-4", "LLM-12", "PRIV-15", "S1-06")
def test_no_d3_d4_route_leaves_the_perimeter() -> None:
    combos = len(_roles(POLICY)) * len(ALL_LABELS) * len(POLICY.profiles) * 3 * 4 * 2 * len(FLAG_SETS)
    assert combos > 10_000 and ALL  # the space is enumerated, and some calls are routable
    bad = [
        (role, label.tag, profile, topo, env, c.alias, c.endpoint.name)
        for role, label, profile, topo, env, cands in ALL
        for c in cands
        if label.data_class in (DataClass.D3, DataClass.D4) and c.endpoint.zone != "perimeter"
    ]
    assert bad == []
    # every fallback prefix: whatever fails first, the next candidate is still permitted (fallback = list order)
    for _, label, *_rest, cands in ALL:
        for k in range(len(cands)):
            rest = cands[k:]
            if label.data_class.rank >= 3:
                assert all(c.endpoint.zone == "perimeter" for c in rest)


@pytest.mark.req("LLM-12")
def test_dev_public_d0_only_and_guard_never_outside() -> None:
    for role, label, _profile, topo, env, cands in ALL:
        for c in cands:
            if c.endpoint.zone == "dev_public":
                assert label.data_class == DataClass.D0 and not label.special_category, (role, label.tag)
                assert env == Environment.DEV
            if POLICY.roles.get(role, {}).get("group") == "guard":
                assert c.endpoint.zone == "perimeter"
            if c.endpoint.zone == "external":
                assert topo == Topology.C  # topology C only (§7.2)
                assert label.data_class in (DataClass.D0, DataClass.D1, DataClass.D2)
            if label.d2_variant == D2Variant.KEYED:
                assert c.endpoint.zone == "tre"  # D2-K lives in Z-TRE only


@pytest.mark.req("LLM-12", "LLM-11")
def test_shipped_policy_lints_clean_and_external_routes_have_conditions() -> None:
    assert violations(POLICY) == []
    assert POLICY.version.startswith("routing-")
    for ep in POLICY.endpoints.values():
        if ep.zone in ("external", "dev_public"):
            assert {"processing_geography", "retention", "training_use"} <= set(ep.conditions)


@pytest.mark.req("LLM-2", "LLM-3")
def test_environment_ceiling_and_unknown_class_fail_closed() -> None:
    d3 = parse_label("D3")
    with pytest.raises(Refusal) as e:
        POLICY.candidates("judge", d3, Topology.A, Environment.DEV, "P-GB10")
    assert e.value.reason == "class_not_allowed_in_env"
    with pytest.raises(Refusal) as e:
        POLICY.candidates("bakeoff", d3, Topology.C, Environment.PRODUCTION, "P-GB10", cloud_opt_in=True)
    assert e.value.reason == "no_route"
    for bad in ("", "D5", "d3", "D3-K", "D2-X", None):
        with pytest.raises(Refusal):
            parse_label(bad)
    assert parse_label("D2").d2_variant == D2Variant.KEYED  # unqualified D2 is treated as the stricter variant
    assert parse_label("D1+sc").special_category


def _random_doc(rng: random.Random) -> dict[str, Any]:
    """A routing document with random rows, many of them wrong on purpose (D3/D4 on external endpoints...)."""
    doc: dict[str, Any] = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    eps = list(doc["endpoints"])
    for ep in doc["endpoints"].values():  # open every endpoint so only the class rule can stop a leak
        ep["g5_record"] = "fuzz"
        ep.pop("environments", None)
    roles = list(doc["roles"])
    tags = ["D0", "D1", "D2-K", "D2-L", "D3", "D4"]
    doc["routes"] = [
        {
            "id": f"fuzz-{i}",
            "roles": rng.sample(roles, k=rng.randint(1, 4)),
            "classes": rng.sample(tags, k=rng.randint(1, 4)),
            "topologies": rng.sample(["A", "B", "C"], k=rng.randint(1, 3)),
            "environments": rng.sample(["DEV", "TEST", "VALIDATION", "PRODUCTION"], k=rng.randint(1, 4)),
            "builds": [f"a{j}@{rng.choice(eps)}" for j in range(rng.randint(1, 4))],
        }
        for i in range(rng.randint(3, 12))
    ]
    return doc


@pytest.mark.req("LLM-4", "PRIV-15")
def test_fuzzed_policies_never_route_d3_d4_outside() -> None:
    rng = random.Random(4)
    leaks_in_file = 0
    for _ in range(150):
        policy = RoutingPolicy(_random_doc(rng))
        leaks_in_file += sum("D3/D4 outside" in v for v in violations(policy))
        for role, label, topo, env, opt_in in itertools.product(
            list(policy.roles)[:12], ALL_LABELS, Topology, Environment, (False, True)
        ):
            if label.data_class.rank < 3:
                continue
            try:
                _, cands = policy.candidates(role, label, topo, env, "P-GB10", cloud_opt_in=opt_in)
            except Refusal:
                continue
            assert all(c.endpoint.zone == "perimeter" for c in cands), (role, label.tag, topo, env)
    assert leaks_in_file > 0  # the fuzz did produce bad rows; the lookup filter stopped every one
