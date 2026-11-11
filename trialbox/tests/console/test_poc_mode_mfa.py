"""PoC mode (D-424): the hosted PoC demo (``TB_DEMO_HOSTED=1``) may run with ``TB_CONSOLE_MFA=off``; VALIDATION and
PRODUCTION still refuse it, demo or not. Off on the demo writes ``console.mfa_off`` once at start-up and the sign-in
page says so in en, ja and zh-TW. The hosted-demo start-up script sets it off by default; ``tb-console-mfa=totp``
turns it back on."""

from __future__ import annotations

from pathlib import Path

import pytest
from console.app import ConsoleSettings, PilotRefused
from console.i18n import CATALOGUES
from console.identity import MFA_OFF_EVENT, IdentityConfigError, IdentitySettings
from fastapi.testclient import TestClient

from tests.console.test_identity import Clock, _app, _events
from tests.unit.test_poc_host import START, env, sh

__all__ = ["env"]  # the dry-run fixture of the PoC host tests

HOSTED = {"TB_DEMO_HOSTED": "1", "TB_CONSOLE_MFA": "off"}


@pytest.mark.parametrize("environment", ["PRODUCTION", "VALIDATION", "production"])
def test_off_is_refused_in_production_and_validation_even_on_the_demo(tmp_path: Path, environment: str) -> None:
    with pytest.raises(IdentityConfigError, match="TB_CONSOLE_MFA=off is refused"):
        IdentitySettings.from_env(HOSTED, environment, tmp_path)
    with pytest.raises((IdentityConfigError, PilotRefused)):  # the console's own config load refuses it too
        ConsoleSettings.from_env({**HOSTED, "TB_ENV": environment, "TB_CONSOLE_DIR": str(tmp_path / "c")})


def test_off_is_allowed_on_the_hosted_demo_only(tmp_path: Path) -> None:
    on_demo = IdentitySettings.from_env(HOSTED, "DEV", tmp_path)
    assert not on_demo.totp_required and on_demo.demo_mfa_off
    plain_dev = IdentitySettings.from_env({"TB_CONSOLE_MFA": "off"}, "DEV", tmp_path)
    assert not plain_dev.totp_required and not plain_dev.demo_mfa_off  # DEV as before, no banner
    demo_totp = IdentitySettings.from_env({"TB_DEMO_HOSTED": "1", "TB_CONSOLE_MFA": "totp"}, "DEV", tmp_path)
    assert demo_totp.totp_required and not demo_totp.demo_mfa_off  # turned back on


@pytest.mark.parametrize(("lang", "text"), [("en", "en"), ("ja", "ja"), ("zh-TW", "zh-TW")])
def test_banner_on_the_sign_in_page_and_one_audit_event(tmp_path: Path, lang: str, text: str) -> None:
    app, _, audit_dir = _app(tmp_path, Clock(), **HOSTED)
    page = TestClient(app).get(f"/login?lang={lang}").text
    assert 'data-testid="login-mfa-off"' in page
    assert CATALOGUES[text]["login.mfa_off_demo"] in page
    ev = [e for e in _events(audit_dir) if e["event"] == MFA_OFF_EVENT]
    assert len(ev) == 1 and ev[0]["actor"] == "console:start" and ev[0]["detail"]["hosted_demo"] is True


def test_no_banner_and_no_event_when_not_the_demo(tmp_path: Path) -> None:
    app, _, audit_dir = _app(tmp_path, Clock(), TB_CONSOLE_MFA="off")  # TEST, not the hosted demo
    assert 'data-testid="login-mfa-off"' not in TestClient(app).get("/login").text
    assert not [e for e in _events(audit_dir) if e["event"] == MFA_OFF_EVENT]


def test_the_banner_has_all_three_languages() -> None:
    assert CATALOGUES["en"]["login.mfa_off_demo"] == "Second factor is off on this demo box"
    assert len({CATALOGUES[x]["login.mfa_off_demo"] for x in ("en", "ja", "zh-TW")}) == 3


def test_the_startup_script_sets_off_by_default_and_totp_turns_it_back_on(env: dict[str, str]) -> None:
    out = sh(START, "--dry-run", env=env)
    assert "TB_DEMO_HOSTED=1" in out and "TB_CONSOLE_MFA=off" in out
    back_on = sh(START, "--dry-run", env={**env, "TB_MD_TB_CONSOLE_MFA": "totp"})
    assert "TB_CONSOLE_MFA=totp" in back_on and "TB_CONSOLE_MFA=off" not in back_on
    bad = sh(START, "--dry-run", env={**env, "TB_MD_TB_CONSOLE_MFA": "sms"}, ok=False)
    assert "tb-console-mfa must be totp or off" in bad
