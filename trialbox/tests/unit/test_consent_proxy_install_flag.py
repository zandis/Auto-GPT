"""P-23 (E2E R1): saving the consent-age rule was refused "consent by a representative is not recorded on this box"
and nothing said how a site turns it on. Integrator's ruling: it is an install flag, off by default, which the site
turns on (dementia trials need consent from a legally authorised representative).

``install.sh --consent-proxy on|off`` writes ``TB_CONSENT_PROXY`` (the setting ``datacore.proxy_consent`` reads); the
page's refusal names that option, in en, ja and zh-TW. The class (RC3): a feature the box can refuse for want of an
install choice says which choice."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")


def _block() -> str:
    start = INSTALL.index("# CONSENT-PROXY (E2E P-23")
    return INSTALL[start : INSTALL.index("# ---- end of CONSENT-PROXY", start)]


def _line(start: str) -> str:
    """install.sh's own line that begins with ``start`` (review R5 of #1572: the real one, not a copy)."""
    (line,) = [x for x in INSTALL.splitlines() if x.startswith(start)]
    return line + "\n"


def _function(name: str) -> str:
    """install.sh's own shell function ``name``, as written there."""
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", INSTALL, re.S | re.M)
    assert m, name
    return m.group(0)


def _parse(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """install.sh up to the end of its argument loop, run as deploy/install.sh of ``tmp``, with ``args``."""
    (tmp / "deploy" / "site").mkdir(parents=True, exist_ok=True)
    if not (tmp / "deploy" / "site" / "poc-stops.jsonl").exists():
        (tmp / "deploy" / "site" / "poc-stops.jsonl").write_text("{}\n", encoding="utf-8")
    head = INSTALL[: INSTALL.index("\nsay() {")] + '\necho "parsed CONSENT_PROXY=$CONSENT_PROXY"\n'
    (tmp / "deploy" / "install.sh").write_text(head, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    cmd = ["/bin/bash", str(tmp / "deploy" / "install.sh"), *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tmp, check=False)


def _run(tmp: Path, value: str | None, before: str = "TB_ENV=PRODUCTION\n") -> subprocess.CompletedProcess[str]:
    """The block with ``--consent-proxy value`` (None: the option not given)."""
    (tmp / "deploy").mkdir(exist_ok=True)
    (tmp / "deploy" / ".env").write_text(before, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        'die() { echo "install: $*" >&2; exit 1; }\n'
        + _line("envget() {")
        + _function("envset")
        + f'cd "{tmp}"\nCONSENT_PROXY="{value or ""}"\nCONSENT_PROXY_SET={int(value is not None)}\n'
        + _block()
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

    res = _run(tmp_path, None)
    assert res.returncode == 0 and "WARN" not in res.stdout + res.stderr
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION"]
    assert not proxy_consent.is_on({})


@pytest.mark.parametrize(("typed", "word"), [(" ON ", "on"), ("Off", "off"), ("on\t", "on")])
def test_the_value_is_trimmed_and_lower_cased(tmp_path: Path, typed: str, word: str) -> None:
    """Review B1/R1 of #1572 (CLINICAL TOLERANCE): what a site types is read, not refused for its case or spaces."""
    res = _run(tmp_path, typed, before="TB_ENV=PRODUCTION\nTB_CONSENT_PROXY=x\n")
    assert res.returncode == 0, res.stderr
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION", f"TB_CONSENT_PROXY={word}"]


@pytest.mark.parametrize("typed", ["yes", ""])
def test_another_word_or_none_keeps_the_site_s_setting_with_a_warning(tmp_path: Path, typed: str) -> None:
    """Review B1/R1 of #1572: the owner's ruling converts the refusal: the install goes on, the box keeps its setting,
    and a WARN says what was assumed and how to set it."""
    res = _run(tmp_path, typed, before="TB_ENV=PRODUCTION\nTB_CONSENT_PROXY=on\n")
    assert res.returncode == 0, res.stderr
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION", "TB_CONSENT_PROXY=on"]
    assert "WARN" in res.stderr and "stays on" in res.stderr and "--consent-proxy on" in res.stderr


@pytest.mark.parametrize("typed", ["yes", " "])
def test_another_word_or_none_on_a_box_without_the_setting_is_off_with_a_warning(tmp_path: Path, typed: str) -> None:
    from datacore import proxy_consent

    res = _run(tmp_path, typed)
    assert res.returncode == 0, res.stderr
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION"] and not proxy_consent.is_on({})
    assert "WARN" in res.stderr and "stays off" in res.stderr and "--consent-proxy on" in res.stderr


def test_the_setting_is_not_joined_to_a_last_line_without_its_newline(tmp_path: Path) -> None:
    """Review R3 of #1572: a .env whose last line has no newline kept that value and the setting apart."""
    res = _run(tmp_path, "on", before="TB_ENV=PRODUCTION\nTB_A=1")
    assert res.returncode == 0, res.stderr
    assert _env(tmp_path) == ["TB_ENV=PRODUCTION", "TB_A=1", "TB_CONSENT_PROXY=on"]


def test_envset_writes_the_whole_file_beside_it_and_renames_it(tmp_path: Path) -> None:
    """Review R2 of #1572: envset deleted the old value, then appended the new one: a stop between the two lost the
    setting. It writes the edited file next to .env with .env's mode and renames it over (the file is old or new)."""
    f = tmp_path / "deploy" / ".env"
    f.parent.mkdir()
    f.write_text("TB_A=1\nTB_B=2\n", encoding="utf-8")
    f.chmod(0o640)
    script = f'cd "{tmp_path}"\n{_function("envset")}envset TB_A 3 && envset TB_C "a b"\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    assert f.read_text(encoding="utf-8") == "TB_B=2\nTB_A=3\nTB_C=a b\n" and f.stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in f.parent.iterdir()) == [".env"]  # no temporary file left
    assert 'sed -i "/^$1=/d" deploy/.env' not in _function("envset")  # not deleted in place before the append


def test_envset_that_fails_before_the_rename_leaves_env_untouched(tmp_path: Path) -> None:
    """A failing first step (awk cannot read .env) must not let the printf make a partial copy that replaces it."""
    f = tmp_path / "deploy" / ".env"
    f.parent.mkdir()
    f.write_text("TB_A=1\nTB_B=2\n", encoding="utf-8")
    before = f.read_bytes()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "awk").write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    (bindir / "awk").chmod(0o755)
    script = f'cd "{tmp_path}"\nPATH="{bindir}:$PATH"\n{_function("envset")}envset TB_A 3\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode != 0
    assert f.read_bytes() == before
    assert sorted(p.name for p in f.parent.iterdir()) == [".env"]  # the temporary file is removed


def test_the_option_is_parsed_and_the_refusal_names_it() -> None:
    from console.refusals import UNTRANSLATED, localize_reason

    assert (
        '--consent-proxy) CONSENT_PROXY_SET=1; case "${2-}" in --*) ;; *) CONSENT_PROXY="${2-}"; [ $# -lt 2 ] || shift ;; esac ;;'
        in INSTALL
    )
    setup = (ROOT / "services" / "console" / "study_setup.py").read_text(encoding="utf-8")
    reason = "consent by a representative is not recorded on this box: turned on at install (--consent-proxy on)"
    assert f'"{reason}"' in setup
    for lang in ("ja", "zh-TW"):
        said = localize_reason(reason, lang)
        assert said not in ("", UNTRANSLATED[lang]) and "--consent-proxy on" in said


@pytest.mark.parametrize(
    ("args", "got"),
    [(("--consent-proxy", "yes"), "yes"), (("--consent-proxy", "ON"), "ON"), (("--consent-proxy",), "")],
)
def test_a_bad_or_missing_value_does_not_stop_the_install(tmp_path: Path, args: tuple[str, ...], got: str) -> None:
    """Review B1/R1 of #1572 (the owner's ruling, CLINICAL TOLERANCE): the value is read as given and the install goes
    on (the block keeps the site's setting and warns); a trailing --consent-proxy is not a silent exit."""
    res = _parse(tmp_path, "--yes", *args)
    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert f"parsed CONSENT_PROXY={got}\n" in res.stdout


def test_an_odd_value_with_check_keeps_the_poc_warning_record(tmp_path: Path) -> None:
    """The PoC warning record of an earlier run survives a --check run whose --consent-proxy value is odd (it warns and
    goes on): the arguments are parsed and the record's content is unchanged."""
    record = tmp_path / "deploy" / "site" / "poc-stops.jsonl"
    record.parent.mkdir(parents=True)
    known = '{"step": "earlier-run", "n": 1}\n'
    record.write_text(known, encoding="utf-8")
    res = _parse(tmp_path, "--check", "--consent-proxy", "yes")
    assert res.returncode == 0, (res.returncode, res.stdout, res.stderr)
    assert "parsed CONSENT_PROXY=yes\n" in res.stdout
    assert record.read_text(encoding="utf-8") == known


def test_a_missing_value_does_not_eat_the_next_option(tmp_path: Path) -> None:
    res = _parse(tmp_path, "--consent-proxy", "--frobnicate")
    assert res.returncode == 2 and "unknown option --frobnicate" in res.stderr


@pytest.mark.parametrize("word", ["on", "off"])
def test_on_and_off_are_read(tmp_path: Path, word: str) -> None:
    res = _parse(tmp_path, "--consent-proxy", word, "--yes")
    assert res.returncode == 0, res.stderr
    assert f"parsed CONSENT_PROXY={word}" in res.stdout


def test_no_later_step_of_the_install_writes_the_setting() -> None:
    """Review R3 of #1572: after the block, install.sh never names TB_CONSENT_PROXY: --consent-proxy is the last word."""
    after = INSTALL[INSTALL.index("# ---- end of CONSENT-PROXY") :]
    assert "TB_CONSENT_PROXY" not in after
