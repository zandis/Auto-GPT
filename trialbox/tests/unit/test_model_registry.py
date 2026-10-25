"""Model registry v0 (spec v4 §8.4, MOD-6, MOD-7; S1-07)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from gateway.policy import RoutingPolicy
from registry.app import create_app
from registry.cards import stale
from registry.registry import Registry, RegistryError, Status, check_served
from tb_common.policy.classes import Environment

ROOT = Path(__file__).resolve().parents[2]
REG = Registry.load(ROOT / "models" / "registry.yaml")


def _doc(*builds: dict[str, Any]) -> dict[str, Any]:
    base = {"serving": "vllm", "served": {"serving": "m"}, "licence": {"name": "t"}, "origin": {"developer": "t"}}
    return {"version": "t", "aliases": {"j": {}}, "builds": [{**base, "alias": "j", **b} for b in builds]}


@pytest.mark.req("S1-07")
def test_seed_entries_are_unpinned_candidates() -> None:
    names = {b.model_name for b in REG.builds}
    assert {"Nemotron 3 Nano", "Nemotron 3 Super", "Qwen3.5-35B-A3B", "gpt-oss-120b"} <= names
    for b in REG.builds:
        assert b.sha256 is None and not b.pinned  # no hash is invented before a verified download
        assert b.licence and b.origin and "quantisation" in b.__dataclass_fields__
        if b.serving != "stub":
            assert b.status == Status.CANDIDATE
    stub = REG.build("trialbox-stub-1")
    assert stub.serving == "stub" and stub.served["stub"] == "trialbox-stub"


@pytest.mark.req("S1-07", "MOD-7")
def test_unpinned_builds_route_only_as_stub_in_dev_test() -> None:
    for env in (Environment.DEV, Environment.TEST):
        assert REG.resolve("trialbox-stub", "stub", role="judge", env=env).served_name == "trialbox-stub"
    for env in (Environment.VALIDATION, Environment.PRODUCTION):
        with pytest.raises(RegistryError) as e:
            REG.resolve("trialbox-stub", "stub", role="judge", env=env)
        assert e.value.reason == "build_unpinned"
    with pytest.raises(RegistryError) as e:  # a candidate in DEV with no hash is still refused
        REG.resolve("j-workhorse", "openrouter", role="bakeoff", env=Environment.DEV)
    assert e.value.reason == "build_unpinned"
    with pytest.raises(RegistryError) as e:
        REG.resolve("no-such-alias", "serving", role="judge", env=Environment.DEV)
    assert e.value.reason == "alias_unknown"


@pytest.mark.req("MOD-7")
def test_status_rules_per_role_kind() -> None:
    sha = "ef" * 32
    reg = Registry(
        _doc(
            {"build_id": "r", "status": "retired", "sha256": sha},
            {"build_id": "q", "status": "qualified", "sha256": sha},
            {"build_id": "s", "status": "shadow", "sha256": sha},
            {"build_id": "c", "status": "champion", "sha256": sha},
        )
    )
    prod = Environment.PRODUCTION
    assert reg.resolve("j", "serving", role="judge", env=prod).build.build_id == "c"
    assert reg.resolve("j", "serving", role="shadow:judge", env=prod).build.build_id == "s"
    assert reg.resolve("j", "serving", role="bakeoff", env=prod).build.build_id == "q"
    only_retired = Registry(_doc({"build_id": "r", "status": "retired", "sha256": sha}))
    for env in Environment:
        with pytest.raises(RegistryError):
            only_retired.resolve("j", "serving", role="judge", env=env)
    with pytest.raises(ValueError, match="sha256"):
        Registry(_doc({"build_id": "x", "status": "champion", "sha256": "not-a-hash"}))
    with pytest.raises(ValueError, match="duplicate"):
        Registry(_doc({"build_id": "x", "status": "champion"}, {"build_id": "x", "status": "champion"}))


@pytest.mark.req("MOD-6", "S1-07")
def test_served_model_echo_check() -> None:
    res = REG.resolve("trialbox-stub", "stub", role="judge", env=Environment.TEST)
    check_served(res, "trialbox-stub")
    for wrong in ("trialbox-stub-2", "", None, "j-workhorse"):
        with pytest.raises(RegistryError) as e:
            check_served(res, wrong)
        assert e.value.reason == "served_model_mismatch"


@pytest.mark.req("MOD-8", "S1-07")
def test_cards_generated_and_routing_aliases_registered() -> None:
    assert stale(REG, ROOT / "models" / "cards") == []
    policy = RoutingPolicy.load(ROOT / "models" / "routing.yaml")
    aliases = {alias for r in policy.routes for alias, _ in r.builds}
    assert aliases <= set(REG.aliases)
    raw = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    assert all("url" not in str(b.get("served")) for b in raw["builds"])  # no endpoint addresses in the registry


def test_registry_app_lists_builds_without_addresses() -> None:
    http = TestClient(create_app(REG))
    body = http.get("/v1/builds").json()
    assert body["version"] == REG.version and len(body["builds"]) == len(REG.builds)
    assert "http" not in str(body)
    assert http.get("/v1/aliases/j-workhorse").json()["builds"]
    assert http.get("/v1/aliases/nope").status_code == 404
