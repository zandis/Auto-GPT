"""``trialbox doctor`` for v4 (spec v4 §18.1; S1-16).

Done-when: doctor fails closed on a D3/D4 route outside the perimeter, an unpinned Hermes image, or D3 data in DEV.
Also: gateway-only model reach from ``deploy/egress.py``, channel engine and fallback, publish-gate state, and a
check that cannot run counts as a failure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import doctor
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "ab" * 32


def status(checks: list[doctor.Check], name: str) -> doctor.Check:
    return next(c for c in checks if c.name == name)


def inputs(**kw: Any) -> doctor.DoctorInputs:
    env = kw.pop("env", {"TB_ENV": "DEV", "TB_TOPOLOGY": "A"})
    return doctor.DoctorInputs(env=env, **kw)


@pytest.mark.req("S1-16", "OPS-02")
def test_default_install_passes_with_hermes_disabled() -> None:
    checks = doctor.run(inputs())
    assert doctor.ok(checks), doctor.render(checks)
    assert status(checks, "channel_engine").status == "PASS"
    assert status(checks, "hermes_pin").status == "WARN"  # disabled and unpinned is the install default
    assert {c.name for c in checks} == {
        "topology",
        "env_class_ceiling",
        "routing_perimeter",
        "gateway_only_model_reach",
        "channel_engine",
        "hermes_pin",
        "publish_gate",
        "registry_pins",
    }


@pytest.mark.req("S1-16", "PRIV-15", "LLM-4")
@pytest.mark.parametrize(("cls", "endpoint"), [("D3", "external_x"), ("D4", "openrouter"), ("D3", "openrouter")])
def test_fails_closed_on_d3_d4_route_outside_the_perimeter(tmp_path: Path, cls: str, endpoint: str) -> None:
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    alias = "x-external" if endpoint == "external_x" else "j-workhorse"
    doc["routes"].insert(
        0,
        {
            "id": "rogue",
            "roles": ["judge"],
            "classes": [cls],
            "topologies": ["A", "B", "C"],
            "environments": ["DEV", "TEST", "VALIDATION", "PRODUCTION"],
            "builds": [f"{alias}@{endpoint}"],
        },
    )
    rogue = tmp_path / "routing.yaml"
    rogue.write_text(yaml.safe_dump(doc), encoding="utf-8")
    checks = doctor.run(inputs(routing_path=rogue))
    c = status(checks, "routing_perimeter")
    assert c.status == "FAIL" and "outside the perimeter" in c.detail and "rogue" in c.detail
    assert not doctor.ok(checks)
    assert cli(["doctor", "--routing", str(rogue)]) == 1


def _lock(tmp_path: Path, **over: Any) -> Path:
    raw: dict[str, Any] = {
        "version": "v0.22.2",
        "tag": "v0.22.2",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "upstream_image": f"nousresearch/hermes-agent:v0.22.2@{DIGEST}",
        "upstream_digest": DIGEST,
        "mirror_image": f"registry.internal/hermes-agent@{DIGEST}",
        "mirror_digest": DIGEST,
        "verified": True,
    }
    raw.update(over)
    p = tmp_path / "hermes.lock"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return p


@pytest.mark.req("S1-16", "HER-18", "ENG-08")
def test_fails_closed_on_unpinned_hermes_when_engine_is_hermes(tmp_path: Path) -> None:
    # shipped lock: pinned v0.22.2, internal mirror pending -> DEV may run the upstream digest (WARN), PRODUCTION not
    shipped = doctor.run(inputs(settings={"channels": {"engine": "hermes"}}))
    c = status(shipped, "hermes_pin")
    assert c.status == "WARN" and "mirror" in c.detail
    prod = doctor.run(
        inputs(env={"TB_ENV": "PRODUCTION", "TB_TOPOLOGY": "A"}, settings={"channels": {"engine": "hermes"}})
    )
    c = status(prod, "hermes_pin")
    assert c.status == "FAIL" and "must not start" in c.detail and "mirror pending" in c.detail and not doctor.ok(prod)
    unpinned = _lock(tmp_path, commit_sha=None, upstream_digest=None)
    bad = doctor.run(inputs(settings={"channels": {"engine": "hermes", "hermes_lock": str(unpinned)}}))
    assert status(bad, "hermes_pin").status == "FAIL" and not doctor.ok(bad)
    pinned = _lock(tmp_path)
    ok = doctor.run(inputs(settings={"channels": {"engine": "hermes", "hermes_lock": str(pinned)}}))
    assert status(ok, "hermes_pin").status == "PASS"
    drift = doctor.run(
        inputs(
            settings={"channels": {"engine": "hermes", "hermes_lock": str(pinned)}},
            hermes_running_digest="sha256:" + "cd" * 32,
        )
    )
    assert status(drift, "hermes_pin").status == "FAIL"
    mutable = _lock(tmp_path, mirror_image="registry.internal/hermes-agent:v0.22.2")
    tag_only = doctor.run(inputs(settings={"channels": {"engine": "hermes", "hermes_lock": str(mutable)}}))
    assert status(tag_only, "hermes_pin").status == "FAIL"
    old = _lock(tmp_path, version="v0.21.5", tag="v0.21.5")
    below = doctor.run(inputs(settings={"channels": {"engine": "hermes", "hermes_lock": str(old)}}))
    assert "floor" in status(below, "hermes_pin").detail


@pytest.mark.req("S1-16", "ENG-16", "ENG-09")
def test_fails_closed_on_d3_data_in_dev() -> None:
    store = doctor.run(inputs(settings={"data_stores": [{"name": "research_db", "data_class": "D3"}]}))
    c = status(store, "env_class_ceiling")
    assert c.status == "FAIL" and "D3 data in DEV" in c.detail and not doctor.ok(store)
    env = doctor.run(inputs(env={"TB_ENV": "DEV", "TB_DATA_CLASS": "D3"}))
    assert status(env, "env_class_ceiling").status == "FAIL"
    test_env = doctor.run(inputs(env={"TB_ENV": "TEST"}, settings={"data_stores": [{"name": "x", "data_class": "D1"}]}))
    assert status(test_env, "env_class_ceiling").status == "FAIL"
    unknown = doctor.run(inputs(settings={"data_stores": [{"name": "x"}]}))
    assert status(unknown, "env_class_ceiling").status == "FAIL"
    prod = doctor.run(
        inputs(env={"TB_ENV": "PRODUCTION"}, settings={"data_stores": [{"name": "research_db", "data_class": "D3"}]})
    )
    assert status(prod, "env_class_ceiling").status == "PASS"


@pytest.mark.req("S1-16", "NFR-B9")
def test_gateway_only_model_reach() -> None:
    leak = doctor.run(inputs(env={"TB_ENV": "DEV", "EGRESS_EXTRA": "orchestrator=openrouter.ai:443"}))
    c = status(leak, "gateway_only_model_reach")
    assert c.status == "FAIL" and "only gateway may" in c.detail
    ok = doctor.run(inputs(env={"TB_ENV": "DEV", "EGRESS_EXTRA": "orchestrator=nhi.example.test:443"}))
    assert status(ok, "gateway_only_model_reach").status == "PASS"


@pytest.mark.req("S1-16")
def test_channel_engine_and_topology_checks() -> None:
    bad = doctor.run(inputs(settings={"channels": {"engine": "slack"}}))
    assert status(bad, "channel_engine").status == "FAIL" and status(bad, "hermes_pin").status == "FAIL"
    topo = doctor.run(inputs(env={"TB_ENV": "DEV", "TB_TOPOLOGY": "Z"}))
    assert status(topo, "topology").status == "FAIL"


@pytest.mark.req("S1-16", "DP-25")
def test_publish_gate_state(tmp_path: Path) -> None:
    wd = tmp_path / "dataplat"
    (wd / "gates").mkdir(parents=True)
    none = doctor.run(inputs(dataplat_workdir=wd))
    assert status(none, "publish_gate").status == "FAIL"  # nothing ever published
    (wd / "l5").mkdir()
    (wd / "l5" / "CURRENT.json").write_text(json.dumps({"snapshot_id": "snap-1"}), encoding="utf-8")
    (wd / "gates" / "000000_g1.json").write_text(json.dumps({"outcome": "PUBLISH"}), encoding="utf-8")
    assert status(doctor.run(inputs(dataplat_workdir=wd)), "publish_gate").status == "PASS"
    (wd / "gates" / "000001_g2.json").write_text(
        json.dumps({"outcome": "HOLD", "blocking_reasons": ["RECON_ROW_COUNT"]}), encoding="utf-8"
    )
    held = status(doctor.run(inputs(dataplat_workdir=wd)), "publish_gate")
    assert held.status == "WARN" and "RECON_ROW_COUNT" in held.detail and "snap-1" in held.detail


@pytest.mark.req("S1-16")
def test_a_check_that_cannot_run_fails(tmp_path: Path) -> None:
    checks = doctor.run(inputs(routing_path=tmp_path / "missing.yaml"))
    assert status(checks, "routing_perimeter").status == "FAIL" and not doctor.ok(checks)


@pytest.mark.req("S1-16")
def test_check_host_runs_doctor() -> None:
    text = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    assert "tools.trialbox doctor" in text
