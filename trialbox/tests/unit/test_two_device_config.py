"""The GB10 profile as data and the two-device configuration (T-214, D-373; OPS-063).

What runs on which device, what listens where, the memory limits against the profile, and the negative of the card:
a gateway listener on 0.0.0.0 on the Spark fails ``doctor --two-device``.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import two_device as td
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
ADDR, PEER = "10.20.0.2", "10.20.0.3"


class _ComposeLoader(yaml.SafeLoader):
    """safe_load plus compose's merge tags (!override, !reset), read as their plain value."""


def _plain(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)  # type: ignore[arg-type]


_ComposeLoader.add_constructor("!override", _plain)
_ComposeLoader.add_constructor("!reset", _plain)


def _compose(path: Path) -> dict[str, Any]:
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)  # a SafeLoader subclass
    assert isinstance(doc, dict)
    return doc


@pytest.fixture(scope="module")
def profile() -> dict[str, Any]:
    return td.load_profile()


def _link(role: str) -> dict[str, Any]:
    alias = "db" if role == "spark" else "gateway"
    return {
        "image": "trialbox-py:1.0.0",
        "command": ["python", "-m", "tools.two_device", "link"],
        "environment": {"TB_LINK_ROLE": role, "TB_LINK_ADDR": ADDR, "TB_LINK_PEER": PEER, "TB_LINK_PORT": "8443"},
        "ports": [{"mode": "ingress", "host_ip": ADDR, "target": 8443, "published": "8443", "protocol": "tcp"}],
        "volumes": [{"type": "bind", "source": "/srv/deploy/secrets/link", "target": "/run/secrets/tb_link"}],
        "networks": {"trialbox-net": {"aliases": [alias]}, "link-net": {}},
        "mem_limit": "1073741824",
    }


def _rendered(role: str, profile: dict[str, Any]) -> dict[str, Any]:
    """A device's config as ``docker compose config --format json`` renders it (mem_limit in bytes)."""
    limits = td.memory_limits(profile)
    services: dict[str, Any] = {}
    for name in profile["devices"][role]:
        if name == "link":
            services[name] = _link(role)
            continue
        svc: dict[str, Any] = {"image": "trialbox-py:1.0.0", "networks": {"trialbox-net": None}}
        if role == "spark":
            svc["mem_limit"] = str(int(limits[name] * 2**30))
        if name == "console":
            svc["ports"] = [{"host_ip": "127.0.0.1", "target": 8090, "published": "8090"}]
        services[name] = svc
    return {"name": "trialbox", "services": services}


# ------------------------------------------------------------------------------------------------ the profile
def test_the_profile_holds_together(profile: dict[str, Any]) -> None:
    assert td.profile_problems(profile) == []
    assert td.main(["profile"]) == 0


def test_every_number_is_marked_unmeasured(profile: dict[str, Any]) -> None:
    assert profile["status"] == "unmeasured" and profile["record"] is None
    assert profile["device"]["unified_memory_measured_gib"] is None
    assert all(v["measured_peak_gib"] is None for v in profile["memory"].values())
    assert {g["id"] for g in profile["decision_gate"]} == {
        "pair-serves", "screening-night", "profiles", "context", "embeddings", "operations", "reliability"
    }  # fmt: skip
    assert all(g["result"] is None for g in profile["decision_gate"])


def test_a_measured_value_on_an_unmeasured_profile_is_refused(profile: dict[str, Any]) -> None:
    p = copy.deepcopy(profile)
    p["memory"]["llm-service"]["measured_peak_gib"] = 39.5
    assert any("llm-service.measured_peak_gib has a value" in m for m in td.profile_problems(p))
    p = copy.deepcopy(profile)
    p["status"] = "measured"
    bad = td.profile_problems(p)
    assert any("is empty, but the profile says measured" in m for m in bad)
    assert any("record" in m for m in bad)


def test_the_limits_must_fit_the_unified_memory(profile: dict[str, Any]) -> None:
    p = copy.deepcopy(profile)
    p["memory"]["lake"]["limit_gib"] = 40
    assert any(m.startswith("one-device form") for m in td.profile_problems(p))
    p = copy.deepcopy(profile)
    p["memory"]["llm-service"]["limit_gib"] = 120
    bad = td.profile_problems(p)
    assert any(m.startswith("two-device form") for m in bad)


def test_the_two_devices_share_only_the_link(profile: dict[str, Any]) -> None:
    p = copy.deepcopy(profile)
    p["devices"]["spark"].append("db")
    assert any("on both devices: db" in m for m in td.profile_problems(p))
    p = copy.deepcopy(profile)
    p["devices"]["workstation"].remove("link")
    assert "devices.workstation has no link" in td.profile_problems(p)


def test_the_driver_hold_is_dated_and_retested(profile: dict[str, Any]) -> None:
    hold = profile["driver_hold"]
    assert hold["version"] == "580.142" and hold["decision"] == "D-373"
    assert hold["next_retest_by"] == hold["decided"] + dt.timedelta(days=hold["retest_every_days"])
    p = copy.deepcopy(profile)
    p["driver_hold"]["next_retest_by"] = hold["decided"] + dt.timedelta(days=90)
    assert any("later than decided" in m for m in td.profile_problems(p))
    assert td.driver_hold_overdue(profile, today=hold["next_retest_by"]) is None
    late = td.driver_hold_overdue(profile, today=hold["next_retest_by"] + dt.timedelta(days=1))
    assert late is not None and "580.142" in late


def test_the_gb10_profile_name_matches_the_serving_record_rule(profile: dict[str, Any]) -> None:
    from tools import serving_config

    assert serving_config.PROFILES["gb10"]["card"] in profile["device"]["card"]


# ------------------------------------------------------------------------------------------------ compose files
def test_every_gb10_service_has_the_profile_memory_limit(profile: dict[str, Any]) -> None:
    gb10 = _compose(DEPLOY / "docker-compose.gb10.yml")["services"]
    base = _compose(DEPLOY / "docker-compose.yml")["services"]
    limits = td.memory_limits(profile)
    assert set(base) <= set(gb10), "a service of the base file has no GB10 entry (no limit, no arm64 platform)"
    for name, svc in gb10.items():
        assert td._gib(svc.get("mem_limit")) == limits[name], name
        assert svc.get("platform") == "linux/arm64", name
    assert set(limits) == set(gb10) | {"link"}


@pytest.mark.parametrize("role", td.ROLES)
def test_the_two_device_files(role: str, profile: dict[str, Any]) -> None:
    doc = _compose(DEPLOY / "two-device" / f"docker-compose.{role}.yml")
    link = doc["services"]["link"]
    assert link["command"] == ["python", "-m", "tools.two_device", "link"]
    assert link["environment"]["TB_LINK_ROLE"] == role
    assert td._gib(link["mem_limit"]) == td.memory_limits(profile)["link"]
    assert link["read_only"] is True and link["cap_drop"] == ["ALL"] and "env_file" not in link
    (port,) = link["ports"]
    assert port.startswith("${TB_LINK_ADDR:?"), "the link publishes on the link address only"
    assert "/run/secrets/tb_link:ro" in link["volumes"][0]
    peer = td.peer_of(role)
    assert link["networks"]["trialbox-net"]["aliases"] == list(td.ROUTES[peer])
    assert doc["networks"]["link-net"].get("internal") is not True
    for name, svc in doc["services"].items():
        if name != "link":
            assert "ports" not in svc, f"{name} publishes a port in the {role} file"
    if role == "spark":
        assert doc["services"]["gateway"]["depends_on"] == {"link": {"condition": "service_healthy"}}
        assert link["platform"] == "linux/arm64"
    else:
        assert "gateway" not in doc["services"]["console"]["depends_on"]
        assert "link" in doc["services"]["console"]["depends_on"]


def test_the_routes_point_at_the_services_of_the_base_file() -> None:
    base = _compose(DEPLOY / "docker-compose.yml")["services"]
    assert "8020" in " ".join(base["gateway"]["command"])
    assert td.ROUTES == {"spark": {"gateway": ("gateway", 8020)}, "workstation": {"db": ("db", 5432)}}
    assert "db" in base


# ------------------------------------------------------------------------------------------------ compose_problems
@pytest.mark.parametrize("role", td.ROLES)
def test_a_correct_device_config_passes(role: str, profile: dict[str, Any]) -> None:
    assert td.compose_problems(role, _rendered(role, profile), profile) == []


def test_a_gateway_listener_on_every_address_of_the_spark_fails(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    cfg["services"]["gateway"]["ports"] = [{"host_ip": "0.0.0.0", "target": 8020, "published": "8020"}]
    bad = td.compose_problems("spark", cfg, profile)
    assert any(m.startswith("gateway: a listener on 0.0.0.0:8020 on the Spark") for m in bad), bad
    cfg["services"]["gateway"]["ports"] = ["8020:8020"]  # short syntax, no address: every address
    assert any("gateway: a listener on 0.0.0.0" in m for m in td.compose_problems("spark", cfg, profile))


def test_any_other_listener_on_the_spark_fails_even_on_one_address(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    cfg["services"]["model-guard"]["ports"] = [{"host_ip": "127.0.0.1", "target": 8000, "published": "8000"}]
    assert any("model-guard: a listener on 127.0.0.1:8000" in m for m in td.compose_problems("spark", cfg, profile))


def test_host_networking_on_the_spark_fails(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    cfg["services"]["gateway"]["network_mode"] = "host"
    assert any("gateway: network_mode host" in m for m in td.compose_problems("spark", cfg, profile))


@pytest.mark.parametrize("ip", ["", "0.0.0.0", "::", PEER])
def test_the_link_publishes_only_on_its_own_address(ip: str, profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    cfg["services"]["link"]["ports"][0]["host_ip"] = ip
    assert any(m.startswith("link: published on") for m in td.compose_problems("spark", cfg, profile))


def test_the_link_address_cannot_be_every_address(profile: dict[str, Any]) -> None:
    cfg = _rendered("workstation", profile)
    cfg["services"]["link"]["environment"]["TB_LINK_ADDR"] = "0.0.0.0"
    cfg["services"]["link"]["ports"][0]["host_ip"] = "0.0.0.0"
    bad = td.compose_problems("workstation", cfg, profile)
    assert any("TB_LINK_ADDR must be this device's address" in m for m in bad)


def test_the_repository_never_runs_on_the_spark(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    cfg["services"]["db"] = {"image": "trialbox-postgres:16-1", "mem_limit": "10737418240"}
    assert "db runs on the Spark (the Spark holds the gateway and the models only)" in td.compose_problems(
        "spark", cfg, profile
    )


def test_the_models_never_run_on_the_workstation(profile: dict[str, Any]) -> None:
    cfg = _rendered("workstation", profile)
    cfg["services"]["gateway"] = {"image": "trialbox-py:1.0.0"}
    assert "gateway runs on the workstation (it belongs on the Spark)" in td.compose_problems(
        "workstation", cfg, profile
    )


def test_a_missing_or_wrong_memory_limit_on_the_spark_fails(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    del cfg["services"]["llm-service"]["mem_limit"]
    cfg["services"]["llm-verifier"]["mem_limit"] = "64g"
    bad = td.compose_problems("spark", cfg, profile)
    assert "llm-service: no memory limit on the Spark (the profile says 42 GiB)" in bad
    assert "llm-verifier: memory limit 64 GiB, the profile says 32 GiB" in bad


def test_the_link_needs_its_role_peer_alias_and_certificates(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    link = cfg["services"]["link"]
    link["environment"]["TB_LINK_ROLE"] = "workstation"
    link["environment"]["TB_LINK_PEER"] = ""
    link["networks"]["trialbox-net"]["aliases"] = []
    link["volumes"] = []
    bad = td.compose_problems("spark", cfg, profile)
    assert "link: TB_LINK_ROLE is 'workstation', not spark" in bad
    assert "link: TB_LINK_PEER (the other device's address) is not set" in bad
    assert "link: does not answer to db on trialbox-net (the workstation's route)" in bad
    assert "link: the certificates (/run/secrets/tb_link) are not mounted" in bad
    del cfg["services"]["link"]
    assert "link is not in the spark config" in td.compose_problems("spark", cfg, profile)


def test_check_command_reads_a_rendered_file(tmp_path: Path, profile: dict[str, Any]) -> None:
    good = tmp_path / "spark.json"
    good.write_text(json.dumps(_rendered("spark", profile)), encoding="utf-8")
    assert td.main(["check", "--role", "spark", "--compose-config", str(good)]) == 0
    cfg = _rendered("spark", profile)
    cfg["services"]["gateway"]["ports"] = [{"host_ip": "0.0.0.0", "target": 8020, "published": "8020"}]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(cfg), encoding="utf-8")
    assert td.main(["check", "--role", "spark", "--compose-config", str(bad)]) == 1
    assert td.compose_config_for("spark", good, DEPLOY) == _rendered("spark", profile)
    assert td.compose_config_for("neither", None, DEPLOY) is None


# ------------------------------------------------------------------------------------------------ doctor --two-device
def test_doctor_two_device_passes_a_correct_spark(profile: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(td, "driver_hold_overdue", lambda _p, today=None: None)
    inp = doctor.DoctorInputs(env={"TB_LINK_ROLE": "spark"}, compose_config=_rendered("spark", profile))
    (c,) = doctor.run(inp, doctor.TWO_DEVICE)
    assert c.status == "PASS", c.detail


def test_doctor_two_device_fails_a_gateway_on_every_address(profile: dict[str, Any]) -> None:
    cfg = _rendered("spark", profile)
    cfg["services"]["gateway"]["ports"] = [{"host_ip": "0.0.0.0", "target": 8020, "published": "8020"}]
    inp = doctor.DoctorInputs(env={"TB_LINK_ROLE": "spark"}, compose_config=cfg)
    (c,) = doctor.run(inp, doctor.TWO_DEVICE)
    assert c.status == "FAIL" and "gateway: a listener on 0.0.0.0:8020 on the Spark" in c.detail
    assert not doctor.ok([c])


def test_doctor_two_device_warns_when_the_driver_retest_is_late(
    profile: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(td, "driver_hold_overdue", lambda _p, today=None: "driver 580.142 hold: re-test was due")
    inp = doctor.DoctorInputs(env={"TB_LINK_ROLE": "spark"}, compose_config=_rendered("spark", profile))
    (c,) = doctor.run(inp, doctor.TWO_DEVICE)
    assert c.status == "WARN" and "580.142" in c.detail
    inp = doctor.DoctorInputs(env={"TB_LINK_ROLE": "workstation"}, compose_config=_rendered("workstation", profile))
    assert doctor.run(inp, doctor.TWO_DEVICE)[0].status == "PASS"  # the driver is the Spark's


@pytest.mark.parametrize("env", [{}, {"TB_LINK_ROLE": "both"}])
def test_doctor_two_device_needs_a_role(env: dict[str, str], profile: dict[str, Any]) -> None:
    inp = doctor.DoctorInputs(env=env, compose_config=_rendered("spark", profile))
    (c,) = doctor.run(inp, doctor.TWO_DEVICE)
    assert c.status == "FAIL" and "TB_LINK_ROLE" in c.detail


def test_doctor_two_device_without_a_rendered_compose_fails() -> None:
    (c,) = doctor.run(doctor.DoctorInputs(env={"TB_LINK_ROLE": "spark"}), doctor.TWO_DEVICE)
    assert c.status == "FAIL" and "no rendered compose" in c.detail


def test_doctor_cli_two_device(tmp_path: Path, profile: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox.__main__ import main

    cfg = _rendered("spark", profile)
    cfg["services"]["gateway"]["ports"] = [{"host_ip": "0.0.0.0", "target": 8020, "published": "8020"}]
    f = tmp_path / "spark.json"
    f.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("TB_LINK_ROLE", "spark")
    monkeypatch.setattr(doctor, "CHECKS", ())  # only the new check: the others read the box
    assert main(["doctor", "--two-device", "--compose-config", str(f), "--json"]) == 1
