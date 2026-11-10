"""``trialbox doctor`` for v4 (spec v4 §18.1; S1-16).

Done-when: doctor fails closed on a D3/D4 route outside the perimeter, a non-Secure cookie in PRODUCTION, or D3 data in DEV.
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
def test_default_install_passes() -> None:
    checks = doctor.run(inputs())
    assert doctor.ok(checks), doctor.render(checks)
    assert status(checks, "channel_engine").status == "PASS"
    assert status(checks, "secure_cookie").status == "WARN"  # DEV may serve http on localhost
    assert {c.name for c in checks} == {
        "topology",
        "env_class_ceiling",
        "routing_perimeter",
        "gateway_only_model_reach",
        "channel_engine",
        "secure_cookie",
        "publish_gate",
        "note_block",
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


@pytest.mark.req("S1-16")
@pytest.mark.parametrize(
    ("env", "want"), [("DEV", "WARN"), ("TEST", "WARN"), ("VALIDATION", "FAIL"), ("PRODUCTION", "FAIL")]
)
def test_secure_cookie_is_required_in_production(env: str, want: str) -> None:
    off = doctor.run(inputs(env={"TB_ENV": env, "TB_TOPOLOGY": "A", "TB_CONSOLE_SECURE_COOKIE": "0"}))
    assert status(off, "secure_cookie").status == want
    on = doctor.run(inputs(env={"TB_ENV": env, "TB_TOPOLOGY": "A", "TB_CONSOLE_SECURE_COOKIE": "1"}))
    assert status(on, "secure_cookie").status == "PASS"


@pytest.mark.req("S1-16")
@pytest.mark.parametrize(
    ("env", "value", "want"),
    [
        ("PRODUCTION", None, "PASS"),  # unset: the console makes the cookie Secure in PRODUCTION (D-192)
        ("PRODUCTION", "", "PASS"),  # the base compose file passes it empty
        ("PRODUCTION", "0", "FAIL"),  # an explicit off stays a FAIL (and the console refuses to start)
        ("PRODUCTION", "1", "PASS"),
        ("VALIDATION", None, "FAIL"),  # the console's default is Secure only in PRODUCTION
        ("VALIDATION", "", "FAIL"),
        ("TEST", "", "WARN"),
        ("DEV", None, "WARN"),
    ],
)
def test_secure_cookie_follows_the_console_default(env: str, value: str | None, want: str) -> None:
    from console.identity import IdentityConfigError, secure_cookie_default

    e = {"TB_ENV": env, "TB_TOPOLOGY": "A", **({} if value is None else {"TB_CONSOLE_SECURE_COOKIE": value})}
    assert status(doctor.run(inputs(env=e)), "secure_cookie").status == want
    try:  # the doctor and the console agree on what the console will do
        console_secure = secure_cookie_default(e, env)
    except IdentityConfigError:
        console_secure = False
    assert console_secure == (want == "PASS")


@pytest.mark.req("S1-16")
def test_hermes_engine_is_refused_with_its_removal_named() -> None:
    c = status(doctor.run(inputs(settings={"channels": {"engine": "hermes"}})), "channel_engine")
    assert c.status == "FAIL" and "D-121" in c.detail


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
    assert status(bad, "channel_engine").status == "FAIL"
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
def test_note_block_without_a_verifier_warns_in_test_and_fails_in_production() -> None:
    base = {"TB_TOPOLOGY": "A", "TB_GATEWAY_URL": "http://tb-gateway:8000"}
    warn = status(doctor.run(inputs(env={**base, "TB_ENV": "TEST"})), "note_block")
    assert warn.status == "WARN" and "never-exclude" in warn.detail
    fail = status(doctor.run(inputs(env={**base, "TB_ENV": "PRODUCTION"})), "note_block")
    assert fail.status == "FAIL"
    single = status(
        doctor.run(
            inputs(env={**base, "TB_ENV": "PRODUCTION", "TB_GATEWAY_VERIFIER_MODEL": "v", "TB_SCREEN_JUDGE": "single"})
        ),
        "note_block",
    )
    assert single.status == "FAIL" and "single" in single.detail
    ok = status(
        doctor.run(inputs(env={**base, "TB_ENV": "PRODUCTION", "TB_GATEWAY_VERIFIER_MODEL": "v"})), "note_block"
    )
    assert ok.status == "PASS"
    never = status(doctor.run(inputs(env={**base, "TB_ENV": "PRODUCTION", "TB_NOTE_BLOCK": "never"})), "note_block")
    assert never.status == "PASS"
    bad = status(doctor.run(inputs(env={**base, "TB_ENV": "DEV", "TB_NOTE_BLOCK": "sometimes"})), "note_block")
    assert bad.status == "FAIL"


def test_a_check_that_cannot_run_fails(tmp_path: Path) -> None:
    checks = doctor.run(inputs(routing_path=tmp_path / "missing.yaml"))
    assert status(checks, "routing_perimeter").status == "FAIL" and not doctor.ok(checks)


@pytest.mark.req("S1-16")
def test_check_host_runs_doctor() -> None:
    text = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    assert "tools.trialbox doctor" in text
