"""P-23 (E2E R1): saving the consent-age rule was refused "consent by a representative is not recorded on this box"
and nothing said how a site turns it on. Integrator's ruling: it is an install flag, off by default, which the site
turns on (dementia trials need consent from a legally authorised representative).

``install.sh --consent-proxy on|off`` writes ``TB_CONSENT_PROXY`` (the setting ``datacore.proxy_consent`` reads); the
page's refusal names that option, in en, ja and zh-TW. The class (RC3): a feature the box can refuse for want of an
install choice says which choice."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")


def _block() -> str:
    start = INSTALL.index("# CONSENT-PROXY (E2E P-23")
    return INSTALL[start : INSTALL.index("# ---- end of CONSENT-PROXY", start)]


def _run(tmp: Path, value: str, before: str = "TB_ENV=PRODUCTION\n") -> subprocess.CompletedProcess[str]:
    (tmp / "deploy").mkdir(exist_ok=True)
    (tmp / "deploy" / ".env").write_text(before, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'envset() { sed -i "/^$1=/d" deploy/.env && printf "%s=%s\\n" "$1" "$2" >> deploy/.env; }\n'
        f'cd "{tmp}"\nCONSENT_PROXY="{value}"\n' + _block()
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env, check=False)


def _env(tmp: Path) -> list[str]:
    return (tmp / "deploy" / ".env").read_text(encoding="utf-8").splitlines()


def test_the_site_turns_it_on_at_install(tmp_path: Path) -> None:
    from datacore import proxy_consent

    res = _run(tmp_path, "on")
    assert res.returncode == 0, res.stderr
    assert "TB_CONSENT_PROXY=on" in _env(tmp_path)
    values = dict(x.split("=", 1) for x in _env(tmp_path))
    assert proxy_consent.is_on(values)


def test_off_is_written_and_a_country_default_can_be_turned_off(tmp_path: Path) -> None:
    res = _run(tmp_path, "off", before="TB_ENV=PRODUCTION\nTB_CONSENT_PROXY=on\n")
    assert res.returncode == 0 and _env(tmp_path).count("TB_CONSENT_PROXY=off") == 1
    assert "TB_CONSENT_PROXY=on" not in _env(tmp_path)


def test_not_given_keeps_what_the_box_has_and_the_default_is_off(tmp_path: Path) -> None:
    from datacore import proxy_consent

    assert _run(tmp_path, "").returncode == 0
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION"]
    assert not proxy_consent.is_on({})


def test_another_word_is_refused(tmp_path: Path) -> None:
    res = _run(tmp_path, "yes")
    assert res.returncode != 0 and "--consent-proxy takes on or off" in res.stderr
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION"]


def test_the_option_is_parsed_and_the_refusal_names_it() -> None:
    from console.refusals import UNTRANSLATED, localize_reason

    assert '--consent-proxy) CONSENT_PROXY="${2:-}"; shift ;;' in INSTALL
    setup = (ROOT / "services" / "console" / "study_setup.py").read_text(encoding="utf-8")
    reason = "consent by a representative is not recorded on this box: turned on at install (--consent-proxy on)"
    assert f'"{reason}"' in setup
    for lang in ("ja", "zh-TW"):
        said = localize_reason(reason, lang)
        assert said not in ("", UNTRANSLATED[lang]) and "--consent-proxy on" in said
