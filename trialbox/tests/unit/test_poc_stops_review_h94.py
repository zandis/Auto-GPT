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

import json
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


# ------------------------------------------------------------------- H94-08 (part 2): every reader, the compose way
READERS = ("deploy/install.sh", "deploy/box-install.sh", "tools/apply_update.sh")


@pytest.mark.parametrize("rel", READERS)
def test_h94_08_no_reader_takes_only_the_exact_prefix(rel: str) -> None:
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):  # master's TB_ENV_SITE line stays (pinned), read over at once the compose way
        if "s/^TB_ENV=//p" in line:
            assert line.startswith("TB_ENV_SITE=") and lines[i + 1] == (
                'TB_ENV_SITE="$(tb_env_raw deploy/.env)"  # H94-08: as compose reads it (the line above is master\'s;'
                " tests pin its place)"
            ), f"{rel}:{i + 1}: a reader of TB_ENV that compose would contradict"


@pytest.mark.parametrize("form", FORMS)
def test_h94_08_the_shell_reader_gives_compose_s_value(tmp_path: Path, form: str) -> None:
    env = tmp_path / ".env"
    env.write_text(f"TB_ENV=VALIDATION\n{form}\n", encoding="utf-8")
    script = stop_prelude() + f"tb_env_of {str(env)!r}\n"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode == 0 and r.stdout.strip() == _compose_env(tmp_path) == "PRODUCTION", r.stderr


def test_h94_08_the_first_check_reads_an_exported_line(tmp_path: Path) -> None:
    """A re-run whose deploy/.env ends in an exported value none of the four: ENV-EARLY stops before anything is
    loaded (it read only ``TB_ENV=`` lines before, and took the earlier TEST)."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n", prewritten_env="TB_ENV=TEST\nexport TB_ENV=SOMETHING\n")
    r = box.install("--mode", "stub", "--yes")
    assert r.rc == 1 and "the environment 'SOMETHING' (TB_ENV in deploy/.env)" in r.err, r.text[-3000:]
    assert "update r1 loaded" not in r.out


def test_l3_a_caller_s_variable_never_keeps_the_list(tmp_path: Path) -> None:
    """box-install.sh hands the list on with install.sh's option --keep-poc-list; an exported TB_STOP_KEEP_LIST (an
    older form of it) is not read: the install empties the list as any install does."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n")
    first = box.install("--environment", "TEST", "--mode", "stub", "--yes", force=("memcaps",))
    assert first.rc == 0 and "install.sh/memcaps" in first.listed_keys(), first.text[-3000:]
    planted = box.install("--environment", "TEST", "--mode", "stub", "--yes", env={"TB_STOP_KEEP_LIST": "1"})
    assert planted.rc == 0 and planted.listed_keys() == set(), planted.text[-3000:]
    first = box.install("--environment", "TEST", "--mode", "stub", "--yes", force=("memcaps",))
    kept = box.install("--environment", "TEST", "--mode", "stub", "--keep-poc-list", "--yes")
    assert kept.rc == 0 and "install.sh/memcaps" in kept.listed_keys(), kept.text[-3000:]


# ------------------------------------------------------------- H94-09 (the integrator's ruling 7102087475, part 2)
def _settings_guard(tmp_path: Path, environment: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """The real deploy/settings_guard.sh on a box whose anchor rule cannot run (no python3 module for it here: the
    finish check fails) and whose site settings would not be mounted (the example would)."""
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / "site" / "compose.anchors.yml").write_text("services: {}\n", encoding="utf-8")
    (deploy / "settings.yaml").write_text("site: {id: SITE-A}\n", encoding="utf-8")
    (deploy / ".env").write_text(f"TB_ENV={environment}\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("TB_SETTINGS_FILE", "PYTHONPATH")}
    r = subprocess.run(["sh", str(ROOT / "deploy" / "settings_guard.sh"), str(deploy)], cwd=tmp_path, env=env,
                       capture_output=True, text=True, check=False, timeout=120)  # fmt: skip
    return r, deploy


def test_h94_09_on_a_poc_box_both_start_checks_warn_and_the_box_starts(tmp_path: Path) -> None:
    r, deploy = _settings_guard(tmp_path, "TEST")
    assert r.returncode == 0, r.stderr
    keys = {json.loads(ln)["key"] for ln in (deploy / "site" / "poc-stops.jsonl").read_text().splitlines() if ln}
    assert keys == {"settings_guard.sh/anchor-rule", "settings_guard.sh/example-settings"}, r.stderr


def test_h94_09_on_production_the_first_stops_with_master_s_words(tmp_path: Path) -> None:
    r, deploy = _settings_guard(tmp_path, "PRODUCTION")
    assert r.returncode == 1
    assert r.stderr.splitlines()[-1].startswith(
        "TrialBox REFUSED to start: the audit anchor folder it would give the console no longer passes the rule"
    ), r.stderr
    assert "PoC box" not in r.stderr and not (deploy / "site" / "poc-stops.jsonl").exists()


# ------------------------------------------- the lane H lead: every stop (5) of the KEK passphrase stays a stop, end to end
def _real_id(box: Box) -> None:
    """The KEK passphrase's checks compare owners with the user that runs the installer: the real id here (they run
    before anything is loaded or written, so no root step is reached)."""
    (box.tmp / "bin" / "id").write_text('#!/bin/sh\nexec /usr/bin/id "$@"\n', encoding="utf-8")


def _no_list_line(box: Box) -> bool:
    f = box.tmp / LISTED
    return not f.exists() or not f.read_text(encoding="utf-8").strip()


def test_kek_a_passphrase_in_the_environment_stops_a_poc_install(tmp_path: Path) -> None:
    box = Box(tmp_path / "b", env="TB_ENV=DEV\n")
    r = box.install("--environment", "DEV", "--mode", "stub", "--yes", env={"TB_KEK_PASSPHRASE": "synthetic-pass-h94"})
    assert r.rc == 2 and "TB_KEK_PASSPHRASE is set in the environment: refused" in r.err, r.text[-2000:]
    assert "synthetic-pass-h94" not in r.text and "update r1 loaded" not in r.out and _no_list_line(box)


@pytest.mark.parametrize("case", ["folder others can write", "link", "second name", "mode 0644"])
def test_kek_an_unsafe_passphrase_file_stops_a_poc_install(tmp_path: Path, case: str) -> None:
    box = Box(tmp_path / "b", env="TB_ENV=DEV\n")
    _real_id(box)
    folder = tmp_path / "pp"
    folder.mkdir(mode=0o700)
    real = folder / "kek.pass"
    real.write_text("synthetic-pass-h94\n", encoding="utf-8")
    real.chmod(0o600)
    given, said = real, ""
    if case == "folder others can write":
        folder.chmod(0o777)
        said = "can be written by others"
    elif case == "link":
        given = folder / "kek.link"
        given.symlink_to(real)
        said = "is a link"
    elif case == "second name":
        os.link(real, folder / "kek.second")
        said = "names (hard links), not one"
    else:
        real.chmod(0o644)
        said = "has mode 644, not 0600"
    r = box.install("--environment", "DEV", "--mode", "stub", "--kek-passphrase-file", str(given), "--yes")
    assert r.rc == 1 and said in r.err and "refused" in r.err, r.text[-2000:]
    assert "synthetic-pass-h94" not in r.text and "update r1 loaded" not in r.out and _no_list_line(box)


@pytest.mark.parametrize("case", ["mode 0644", "environment"])
def test_kek_seal_keys_refuses_the_same_on_its_own_and_seals_nothing(tmp_path: Path, case: str) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    pp = tmp_path / "pp"
    pp.mkdir(mode=0o700)
    f = pp / "kek.pass"
    f.write_text("synthetic-pass-h94\n", encoding="utf-8")
    f.chmod(0o644 if case == "mode 0644" else 0o600)
    env = {**os.environ, "TB_KEK_BACKEND": "passphrase"}
    if case == "environment":
        env["TB_KEK_PASSPHRASE"] = "synthetic-pass-h94"
    r = subprocess.run(["sh", str(ROOT / "deploy" / "hardening" / "seal_keys.sh"), "--secrets", str(secrets),
                        "--conf", str(tmp_path / "none.conf"), "--kek-passphrase-file", str(f)],
                       capture_output=True, text=True, env=env, check=False, timeout=60)  # fmt: skip
    assert r.returncode != 0 and "refused" in r.stderr, r.stderr
    assert not any(secrets.iterdir()) and "synthetic-pass-h94" not in r.stdout + r.stderr


def _seal_step() -> str:
    start = INSTALL.index('  seal() { TB_IMAGE="$IMAGE_PY" sh deploy/hardening/seal_keys.sh')
    return INSTALL[start : INSTALL.index('  PP_FILE=""; KP_FILE=""\n', start)]


def test_kek_the_install_s_seal_step_never_reaches_those_refusals(tmp_path: Path) -> None:
    """install.sh refuses the environment and reads and checks the operator's file itself (KEK-INPUT, before anything
    is loaded); its seal step then hands seal_keys.sh the checked value on stdin alone: never the file's name and never
    the environment, so seal_keys.sh's own refusals of them cannot be reached from it, and the helper after the seal
    step can only ever warn about a failure that is not (5)."""
    assert (
        INSTALL.index("\nkp_refuse_env\n")
        < INSTALL.index('if [ -n "$PP_FILE" ]; then kp_read_file "$PP_FILE"')
        < INSTALL.index(_seal_step())
    )
    deploy = tmp_path / "deploy"
    (deploy / "hardening").mkdir(parents=True)
    rec = tmp_path / "seal.rec"
    (deploy / "hardening" / "seal_keys.sh").write_text(
        f'printf "%s\\n" "$*" > {rec}; env | grep -c "^TB_KEK_.*PASSPHRASE=" >> {rec} || :; cat >> {rec}\n',
        encoding="utf-8",
    )
    script = ('die() { echo "install: $*" >&2; exit 1; }\nkp_remove_file() { :; }\nstop_or_warn() { exit 9; }\n'
              'KP_VALUE=synthetic-pass-h94; KP_FILE=/root/kek.pass; PP_KEEP=1; SEC_DIR=s; HB_CONF=c; IMAGE_PY=i\n'
              + _seal_step())  # fmt: skip
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False,
                       env={"PATH": os.environ["PATH"]})  # fmt: skip
    assert r.returncode == 0, r.stderr
    args, kek_env, value = rec.read_text(encoding="utf-8").splitlines()
    assert "--kek-passphrase-stdin" in args.split() and "--kek-passphrase-file" not in args and kek_env == "0"
    assert value == "synthetic-pass-h94"


# ------------------------------------------------------------------- the mutants of part 2 that survived a first run
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize(("args", "emptied"), [(("b.tar",), True), (("--firstrun",), False)])
def test_box_install_empties_the_list_when_a_box_install_starts(
    tmp_path: Path, args: tuple[str, ...], emptied: bool
) -> None:
    """box-install.sh's own lines are the run's: an install empties the list; --firstrun (the same install, finished)
    keeps it. The block as it stands in box-install.sh, run alone."""
    start = BOX_INSTALL.index("_clear=1\n")
    block = BOX_INSTALL[start : BOX_INSTALL.index("\n", BOX_INSTALL.index("|| rm -f --", start)) + 1]
    listed = tmp_path / "deploy" / "site" / "poc-stops.jsonl"
    listed.parent.mkdir(parents=True)
    listed.write_text('{"key": "box-install.sh/old"}\n', encoding="utf-8")
    script = f"TB_STOP_DEPLOY={str(tmp_path / 'deploy')!r}; TB_STOP_REHEARSAL=0\nset -- {' '.join(args)}\n{block}"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    assert listed.exists() is not emptied


def test_box_install_hands_its_list_on_to_install_sh() -> None:
    """install.sh run from box-install.sh keeps the lines box-install.sh wrote before it (--keep-poc-list, read by
    install.sh's own command line); test_l3_a_caller_s_variable_never_keeps_the_list shows install.sh's side."""
    call = BOX_INSTALL[
        BOX_INSTALL.index("  run_install() {") : BOX_INSTALL.index("\n  }\n", BOX_INSTALL.index("  run_install() {"))
    ]
    assert "--keep-poc-list" in call.split()


def test_an_update_reads_the_box_s_environment_as_compose_does(tmp_path: Path) -> None:
    """apply_update.sh's --no-backup on a box whose deploy/.env ends in an exported PRODUCTION line is the PRODUCTION
    refusal (H94-08), not a PoC box's warning."""
    from tests.unit.test_poc_stops_h94 import _apply_update

    r = _apply_update(tmp_path, "--no-backup", environment="VALIDATION\nexport TB_ENV=PRODUCTION")
    assert r.rc == 2 and "--no-backup on a PRODUCTION box needs --no-backup-reason" in r.err, r.text[-2000:]
    assert "PoC box" not in r.err


def test_a_warned_finish_check_mounts_and_signs_no_anchor(tmp_path: Path) -> None:
    """D-1091: a finish check that warns on a PoC box sets ANCHOR_UNSAFE: the anchor folders are neither mounted
    (anchors-compose is never asked) nor signed into by the nightly cron."""
    box = Box(tmp_path / "b", env="TB_ENV=TEST\n")
    r = box.install("--environment", "TEST", "--mode", "stub", "--yes", force=("anchor-gate",))
    assert r.rc == 0 and "install.sh/anchor-gate" in r.listed_keys(), r.text[-3000:]
    assert "anchors-compose" not in (box.tmp / "calls.log").read_text(encoding="utf-8")
    assert "audit-sign" not in (box.tmp / "cron" / "trialbox-retention").read_text(encoding="utf-8")


def test_the_real_servers_override_names_one_card_by_its_uuid() -> None:
    with pytest.raises(ValueError, match="not a card UUID"):
        rehearsal_real.override_text("0", {})


def test_bootstrap_stops_a_user_who_is_not_root(tmp_path: Path) -> None:
    b = tmp_path / "bin"
    b.mkdir()
    (b / "id").write_text(
        '#!/bin/sh\n[ "$1" = -u ] && { echo 4242; exit 0; }\nexec /usr/bin/id "$@"\n', encoding="utf-8"
    )
    (b / "id").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env["PATH"] = f"{b}:{env['PATH']}"
    r = subprocess.run(["bash", str(ROOT / "deploy" / "bootstrap.sh"), str(tmp_path / "b.tar"), "--pub", str(tmp_path / "k")],
                       capture_output=True, text=True, env=env, check=False, timeout=60)  # fmt: skip
    assert r.returncode == 1 and "run it as root" in r.stderr, r.stderr
