"""H-94: the independent review of #1396 (7096812411) and the integrator's ruling on it (7096812799).

* H-1: the PoC rule reads ``TB_ENV`` in ``deploy/.env`` as compose reads it (``export``, blanks around the name, a
  comment; the last line wins), in install.sh's ``tb_poc_box`` and in ``tools/trialbox/stops.py`` alike, so a box
  whose services run PRODUCTION is never taken for a PoC box.
* H-2: ``ANCHOR_OK`` is the script's own: a caller's never skips the anchor folders' check.
* M-1: the fifth kept refusal (a secret where others can read it): a FAIL line of the host check about a secret's mode
  stays a FAIL on a PoC box.
* M-2: pre-start's rehearsal guard (kept refusal 3) runs on its own on a PoC box, so the warning never covers it.
* L-1 to L-4: master's first words on PRODUCTION when two faults meet; ``--environment`` read once, as the first
  check reads it; the list emptied when an install starts; the list made 0640 directly.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_poc_stops_bench_h94 import Box, stop_prelude
from tests.unit.test_poc_stops_h94 import PROD_SITE, _as_pattern, _master, _shell_poc
from tools import rehearsal_real
from tools.trialbox import stops

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
LISTED = Path("deploy") / "site" / "poc-stops.jsonl"


# ------------------------------------------------------------------------------------------- H-1: as compose reads it
def _compose_env(deploy: Path) -> str:
    """What the services get: the repository's model of compose's reading (tools/rehearsal_real.py env_file)."""
    return re.sub(r"[\"' \t\r]", "", rehearsal_real.env_file(deploy / ".env").get("TB_ENV", "")).upper()


FORMS = [  # a line after TB_ENV=VALIDATION: compose's last word is PRODUCTION
    "export TB_ENV=PRODUCTION",
    " TB_ENV=PRODUCTION",
    "TB_ENV =PRODUCTION",
    "TB_ENV = PRODUCTION",
    "\tTB_ENV\t=PRODUCTION",
    "export\tTB_ENV='PRODUCTION'",
    '  export   TB_ENV="production"',
    "TB_ENV=PRODUCTION # set by hospital IT",
]


@pytest.mark.parametrize("form", FORMS)
def test_a_production_line_in_any_form_compose_reads_is_production(tmp_path: Path, form: str) -> None:
    d = tmp_path / "deploy"
    d.mkdir()
    (d / ".env").write_text(f"TB_ENV=VALIDATION\nTB_HOST_PROFILE=poc\n{form}\n", encoding="utf-8")
    assert _compose_env(d) == "PRODUCTION"
    assert stops.recorded(d) == "PRODUCTION"
    assert not stops.poc_box(d) and not stops.poc_box(d, environment="VALIDATION")
    assert not _shell_poc(d, "", "0", {}) and not _shell_poc(d, "VALIDATION", "0", {})


LAST_WORDS = [  # (deploy/.env, what compose gives, PoC?)
    ("TB_ENV=PRODUCTION\nexport TB_ENV=VALIDATION\n", "VALIDATION", True),  # the last line wins, in any form
    ("TB_ENV=VALIDATION\n# TB_ENV=PRODUCTION\n", "VALIDATION", True),  # a comment is no line
    ("TB_ENV=VALIDATION\nTB_ENVIRONMENT=PRODUCTION\n", "VALIDATION", True),  # another name
    ("TB_ENV=VALIDATION # the rehearsal\n", "VALIDATION", True),
    ("TB_ENV=VALIDATION\nTB_ENV=BOGUS\n", "BOGUS", False),  # none of the four: cannot be told
]


@pytest.mark.parametrize(("dotenv", "compose", "poc"), LAST_WORDS)
def test_the_rule_and_compose_agree_on_the_last_word(tmp_path: Path, dotenv: str, compose: str, poc: bool) -> None:
    d = tmp_path / "deploy"
    d.mkdir()
    (d / ".env").write_text(dotenv, encoding="utf-8")
    assert _compose_env(d) == compose
    assert stops.poc_box(d) is poc and _shell_poc(d, "", "0", {}) is poc


def test_on_the_real_path_an_exported_production_line_stops_with_master_s_words(tmp_path: Path) -> None:
    """The real install.sh, its settings ending in ``export TB_ENV=PRODUCTION`` after a VALIDATION line: a forced
    converted point stops as on master, and nothing is listed."""
    (tmp_path / "feed").mkdir()
    site = f"TB_ENV=VALIDATION\n{PROD_SITE.split(chr(10), 1)[1]}TB_SOURCE_DIR={tmp_path / 'feed'}\n"
    box = Box(tmp_path / "b", env=site + "export TB_ENV=PRODUCTION\n")
    r = box.install("--mode", "stub", "--yes", force=("memcaps",))
    assert r.rc == 1, r.text[-4000:]
    assert re.fullmatch("install: " + _as_pattern(_master("the memory caps could not be sized")),
                        r.err.splitlines()[-1]), r.err[-2000:]  # fmt: skip
    assert "PoC box, H-94" not in r.err and not (box.tmp / LISTED).exists()


# --------------------------------------------------------------------------------------- H-2: ANCHOR_OK is the script's
def _anchor_block() -> str:
    start = INSTALL.index("# ANCHOR-MOUNT (D-638)")
    return INSTALL[start : INSTALL.index("\nfi\n", start) + 4]


@pytest.mark.parametrize("planted", ["0", "no", ""])
def test_a_caller_s_anchor_ok_never_skips_the_anchor_check_on_production(tmp_path: Path, planted: str) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_AUDIT_ANCHOR_TARGETS=relative/heads\n", encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp_path}"\ncd "$ROOT"\nIMAGE_PY=trialbox-py:test\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        + stop_prelude(deploy='"$ROOT/deploy"')
        + 'docker() { echo "docker $*" >&2; }\nCOMPOSE=(docker compose); FILES="$ROOT/deploy/docker-compose.yml"\n'
        + _anchor_block()
        + "\necho reached\n"
    )
    env = {**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'libs'}", "ANCHOR_OK": planted, "ANCHOR_UNSAFE": "0"}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 1 and "reached" not in r.stdout, r.stderr
    assert "relative/heads" in r.stderr and "no python3" not in r.stderr


def test_anchor_ok_is_set_by_the_script_before_its_first_read() -> None:
    first_read = INSTALL.index("$ANCHOR_OK")
    assert INSTALL.rindex("\nANCHOR_OK=1", 0, first_read) > INSTALL.index("# ANCHOR-MOUNT (D-638)")


# ------------------------------------------------------------------------------ M-1: a secret's mode stays a FAIL (5)
@pytest.mark.parametrize("environment", ["TEST", "PRODUCTION"])
def test_a_fail_line_about_a_secret_s_mode_stays_a_fail(tmp_path: Path, environment: str) -> None:
    """On a PoC box the other FAIL lines warn, the host check's line about deploy/.env's mode stays a FAIL and the
    install ends 1; on PRODUCTION master's FAIL lines and exit 1, word for word, and nothing more."""
    site = f"TB_ENV={environment}\n" + (PROD_SITE.split("\n", 1)[1] + f"TB_SOURCE_DIR={tmp_path}\n"
                                        if environment == "PRODUCTION" else "")  # fmt: skip
    r = Box(tmp_path / "b", env=site).install("--mode", "stub", "--yes", force=("env-mode",),
                                              env={"TB_BOX_DEFER_SEAL": "1"})  # fmt: skip
    assert r.rc == 1, r.text[-4000:]
    last = r.err.splitlines()[-1]
    if environment == "PRODUCTION":
        fails = [ln for ln in r.err.splitlines() if ln.startswith("install: FAIL: ")]
        assert "install: FAIL: the host check reported FAIL lines (above; docs/SECURITY.md)" in fails
        assert r.err.splitlines()[-len(fails) :] == fails, r.err[-2000:]
        assert "the host check: .env mode" not in r.err and "PoC box" not in r.err
    else:
        assert last == "install: FAIL: the host check: .env mode 644 (want 600, root-owned)", r.err[-2000:]
        assert "warning (PoC box, H-94): FAIL: the host check reported FAIL lines" in r.err
    assert "FAIL  .env mode 644" in r.out  # the host check's own lines are shown as before


def test_the_fifth_refusal_is_named_wherever_the_others_are() -> None:
    page = (ROOT / "docs" / "handover" / "poc-stops-h94-2026-11-23.md").read_text(encoding="utf-8")
    words = "a secret would be read from, or written to, a place others can read"
    for text in (INSTALL, stops.__doc__ or "", page):
        assert words in " ".join(text.replace("#", " ").split()), text[:200]
    assert re.search(r"exit 1 +# H-94 \(5\)", INSTALL)


# ------------------------------------------------------------------------------- M-2: the rehearsal guard is its own
def test_a_poc_box_never_warns_past_the_rehearsal_guard(tmp_path: Path) -> None:
    """A TEST box that ran the real model servers as a rehearsal but is no whole rehearsal box any more (its record,
    no mark): pre-start's own first check refuses, and on a PoC box the install stops there too (refusal 3), with
    pre-start's words, instead of warning and starting it."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n")
    site = box.deploy / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "rehearsal-real-servers.json").write_text('{"words": "rehearsal: stand-in"}\n', encoding="utf-8")
    r = box.install("--environment", "TEST", "--mode", "stub", "--yes")
    assert r.rc == 1, r.text[-4000:]
    assert "refused: this box ran the real model servers as a rehearsal" in r.text
    assert r.err.splitlines()[-1] == "install: a start-up step of this release failed (pre-start above)"
    assert "start-up step of this release failed (pre-start above)" not in "".join(
        ln for ln in r.err.splitlines() if "warning (PoC box" in ln
    )


def test_the_guard_runs_alone_only_on_a_poc_box_and_before_pre_start() -> None:
    at = INSTALL.index("python3 -m tools.rehearsal_real start --deploy")
    assert INSTALL.rindex("if tb_poc_box; then", 0, at) > INSTALL.rindex("\n", 0, at) - 200
    assert at < INSTALL.index("python3 -m tools.trialbox pre-start --deploy")
    assert re.search(r'\|\| die "a start-up step of this release failed \(pre-start above\)" +# H-94 \(3\)', INSTALL)


# ------------------------------------------------------------------------------------------------------- the Lows
def test_l1_on_production_the_override_s_words_come_first_as_on_master(tmp_path: Path) -> None:
    """--rehearsal-real-servers with both a caller's override and no python3 on a box that is not a PoC box (it
    records PRODUCTION): master's first refusal, the override's."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n", no=("python3",),
              prewritten_env="TB_ENV=PRODUCTION\n")  # fmt: skip
    probe = tmp_path / "probe.json"
    probe.write_text("{}\n", encoding="utf-8")
    r = box.install("--rehearsal", "--rehearsal-real-servers", "--gpu", "rtxpro6000", "--gpu-index", "1",
                    "--engine-probe", str(probe), "--yes", answers=False,
                    env={"TB_COMPOSE_OVERRIDE": str(tmp_path / "o.yml")})  # fmt: skip
    assert r.rc == 1, r.text[-4000:]
    assert "unset TB_COMPOSE_OVERRIDE" in r.err and "needs python3" not in r.err, r.err[-2000:]


@pytest.mark.parametrize("given", [" dev", "dev ", "'DEV'"])
def test_l2_the_environment_is_read_once_as_the_first_check_reads_it(tmp_path: Path, given: str) -> None:
    """An --environment the first check (ENV-EARLY) does not take is no PoC box either: it stops there, before
    anything is loaded or written, as on master."""
    d = tmp_path / "deploy"
    d.mkdir()
    assert not stops.poc_box(d, environment=given) and not _shell_poc(d, given, "0", {})
    r = Box(tmp_path / "b", env="TB_ENV=TEST\n").install("--environment", given, "--mode", "stub", "--yes")
    assert r.rc == 1 and "is not DEV, TEST, VALIDATION or PRODUCTION: nothing was loaded or written" in r.err
    assert "PoC box" not in r.err and "update r1 loaded" not in r.out


def test_l3_an_install_starts_with_an_empty_list(tmp_path: Path) -> None:
    """A point warned by one install and fixed before the next is not shown again: each install's list is its own;
    the run from the signed tree keeps what the first half wrote."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n")
    first = box.install("--environment", "TEST", "--mode", "stub", "--yes", force=("memcaps", "db-up"))
    assert first.rc == 0 and {"install.sh/memcaps", "install.sh/db-up"} <= first.listed_keys(), first.text[-3000:]
    second = box.install("--environment", "TEST", "--mode", "stub", "--yes")
    assert second.rc == 0 and second.listed_keys() == set(), second.text[-3000:]
    (box.tmp / LISTED).write_text('{"key": "k", "what": "w", "skipped": "", "at": "t", "by": "b"}\n', encoding="utf-8")
    checked = box.install("--check", answers=False)
    assert (box.tmp / LISTED).exists(), checked.text[-2000:]  # a run that only checks keeps it
    signed = os.readlink(box.tmp / "current")  # the run from the signed tree is the same install: it keeps it
    rerun = box.install("--environment", "TEST", "--mode", "stub", "--yes", env={"TB_INSTALL_SIGNED": signed})
    assert "k" in {e["key"] for e in rerun.listed()}, rerun.text[-2000:]


def test_l4_the_shell_list_is_made_0640_with_no_window(tmp_path: Path) -> None:
    d = tmp_path / "deploy"
    (d / "site").mkdir(parents=True)
    # no chmod after the write: the mode is the one it was made with, under the widest umask
    script = (
        stop_prelude(deploy=str(d), environment="TEST") + 'umask 000\nchmod() { :; }\nstop_or_warn k "" "a point"\n'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE((d / "site" / "poc-stops.jsonl").stat().st_mode) == 0o640
