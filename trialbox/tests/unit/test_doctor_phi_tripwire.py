"""Card 9g-11 (D-1348; review 01 B1-P2): ``doctor`` fails when the gateway's PHI tripwire is off in PRODUCTION.

The check reads the setting by the gateway's own rule (``GatewayConfig.from_env``), so doctor and the gateway agree.
"""

from __future__ import annotations

import pytest

from tools.trialbox import doctor


def tripwire(env: dict[str, str]) -> doctor.Check:
    return doctor.check_phi_tripwire(doctor.DoctorInputs(env=env))


@pytest.mark.parametrize("value", ["off", "OFF", " off ", "0", "false", "no"])
def test_off_in_production_fails_with_how_to_turn_it_on(value: str) -> None:
    c = tripwire({"TB_ENV": "PRODUCTION", "TB_GATEWAY_PHI_TRIPWIRE": value})
    assert c.name == "phi_tripwire" and c.status == "FAIL"
    assert "the PHI tripwire is off in PRODUCTION" in c.detail
    assert "set TB_GATEWAY_PHI_TRIPWIRE=on in deploy/.env" in c.detail


def test_off_with_tb_env_unset_is_production_and_fails() -> None:
    # the gateway's rule: TB_ENV unset is PRODUCTION (D-127)
    assert tripwire({"TB_GATEWAY_PHI_TRIPWIRE": "off"}).status == "FAIL"


@pytest.mark.parametrize("env", ["DEV", "TEST", "VALIDATION"])
def test_off_elsewhere_is_a_warning(env: str) -> None:
    c = tripwire({"TB_ENV": env, "TB_GATEWAY_PHI_TRIPWIRE": "off"})
    assert c.status == "WARN" and f"off in {env}" in c.detail


@pytest.mark.parametrize("value", [None, "on", "1", "true", "yes", "", "maybe"])
@pytest.mark.parametrize("env", ["DEV", "TEST", "VALIDATION", "PRODUCTION"])
def test_on_passes(env: str, value: str | None) -> None:
    # unset, on, or a value that is neither: the gateway keeps the tripwire on
    e = {"TB_ENV": env, **({} if value is None else {"TB_GATEWAY_PHI_TRIPWIRE": value})}
    assert tripwire(e).status == "PASS"


def test_doctor_agrees_with_the_gateway() -> None:
    from gateway.core import GatewayConfig

    for value in ("off", "0", "on", "", "maybe"):
        gateway_on = GatewayConfig.from_env({"TB_GATEWAY_PHI_TRIPWIRE": value}).phi_tripwire
        assert (tripwire({"TB_ENV": "PRODUCTION", "TB_GATEWAY_PHI_TRIPWIRE": value}).status == "PASS") is gateway_on


def test_production_run_fails_on_it() -> None:
    env = {"TB_ENV": "PRODUCTION", "TB_TOPOLOGY": "A", "TB_TZ": "Asia/Taipei", "TB_GATEWAY_PHI_TRIPWIRE": "off"}
    checks = doctor.run(doctor.DoctorInputs(env=env, host_tz="Asia/Taipei"))
    assert next(c for c in checks if c.name == "phi_tripwire").status == "FAIL"
    assert not doctor.ok(checks)
