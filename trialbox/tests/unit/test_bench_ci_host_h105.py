"""H-105b: the walk's red on the bench host's first install (master 1fc6579e), each fault run, not read as text.

The walk found four faults the text tests passed: a scratch folder beside the user's home refused, an unbound
variable after "installed", the units' runtime folder (a system unit's ``%U`` is 0) and the proxy's network not seen
by the user's own engine; and the runbook did not say what a fresh host lacks. The install's steps are run here with
stand-ins for root's commands (install.sh, read with ``source``, only defines its steps); the real-host test
(``host_test.sh``) is run by the walk on the bench host, and its report's own parts are tested here.
"""

from __future__ import annotations

import os
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tools.bench_ci import launcher

ROOT = Path(__file__).resolve().parents[2]
BENCH_CI = ROOT / "tools" / "bench_ci"
INSTALL = BENCH_CI / "install.sh"
HOST_TEST = BENCH_CI / "host_test.sh"
UNITS = (BENCH_CI / "tb-bench-proxy.service", BENCH_CI / "tb-bench-runner@.service")
RUNBOOK = ROOT / "docs" / "runbook" / "13-bench-ci-runner.md"


def _bash(script: Path, body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """``source`` the script (it only defines its steps), then run ``body`` with its stand-ins. The settings folder
    (and with it the record of what install made) is a fresh temporary folder unless ``body`` names another."""
    with tempfile.TemporaryDirectory() as etc:
        pre = f'ETC="{etc}"; SETTINGS="$ETC/settings.env"; TOKEN="$ETC/token"; MADE="$ETC/made"\nchown() {{ :; }}\n'
        text = f'set -euo pipefail\nsource "{script}"\n{pre}{body}\n'
        return subprocess.run(["bash", "-c", text, "test", *args], check=False, capture_output=True, text=True)


# --- the install ends cleanly (the walk: "line 158: ctx: unbound variable", rc 1, after "installed") ------------

INSTALL_STAND_INS = """
need_root() { :; }; prerequisites() { :; }; make_user() { :; }; install_files() { :; }
make_networks() { :; }; start_units() { :; }
get() { echo "x"; }
curl() { : > "${@: -2:1}"; }   # the archive: an empty file where -o says
sha256sum() { cat > /dev/null; }
chown() { :; }; as_tb() { :; }
"""


def test_the_install_ends_with_no_unbound_variable_after_the_image_step() -> None:
    got = _bash(INSTALL, INSTALL_STAND_INS + "cmd_install\necho AFTER-INSTALL")
    assert got.returncode == 0, got.stderr
    assert "installed." in got.stdout and "AFTER-INSTALL" in got.stdout
    assert "unbound variable" not in got.stderr


def test_the_image_steps_build_folder_is_gone_after_it(tmp_path: Path) -> None:
    body = INSTALL_STAND_INS + f'mktemp() {{ mkdir "{tmp_path}/ctx"; echo "{tmp_path}/ctx"; }}\nbuild_image\n'
    got = _bash(INSTALL, body + "outer() { :; }\nouter\necho DONE")
    assert got.returncode == 0 and "DONE" in got.stdout, got.stderr
    assert not (tmp_path / "ctx").exists()


# --- the scratch folder: the user's home and what is in it are refused, a folder beside it is not -----------------


def _scratch(path: str) -> subprocess.CompletedProcess[str]:
    body = (
        "install() { :; }; chown() { :; }; chmod() { :; }\n"
        f'get() {{ [ "$1" = BENCH_SCRATCH ] && echo "{path}"; }}\n'
        "install_files\necho SCRATCH-OK"
    )
    return _bash(INSTALL, body)


@pytest.mark.parametrize("path", ["/var/lib/tb-bench-ci-scratch", "/var/lib/tb-bench2", "/var/lib/tb-bench-scratch"])
def test_a_scratch_folder_beside_the_users_home_is_taken(path: str) -> None:
    got = _scratch(path)
    assert got.returncode == 0 and "SCRATCH-OK" in got.stdout, got.stderr


@pytest.mark.parametrize("path", ["/var/lib/tb-bench", "/var/lib/tb-bench/scratch", "/", "/etc/ci"])
def test_the_users_home_and_roots_folders_are_refused_as_scratch(path: str) -> None:
    got = _scratch(path)
    assert got.returncode != 0 and "is not a folder of its own" in got.stderr


# --- the units name no runtime folder; each of the user's steps sets its own ----------------------------------------


def test_no_unit_names_a_runtime_folder_or_the_managers_user_id() -> None:
    for unit in UNITS:
        text = unit.read_text(encoding="utf-8")
        assert "%U" not in text and "XDG_RUNTIME_DIR" not in text, unit.name


def _someone_else() -> pwd.struct_passwd:
    return next(p for p in pwd.getpwall() if p.pw_uid not in (0, os.getuid()))


@pytest.fixture
def proxy_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The proxy command with stand-ins: the settings, the engine (its answers per sub-command) and exec."""
    user = _someone_else()
    calls: list[list[str]] = []
    answers: dict[str, int] = {"exists": 0, "create": 0}
    seen: dict[str, Any] = {}

    def run(args: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(args))
        return subprocess.CompletedProcess(args, answers.get(args[2], 0) if args[1] == "network" else 0)

    def execv(path: str, args: list[str]) -> None:
        seen["exec"] = (path, list(args))
        seen["env"] = dict(os.environ)
        raise SystemExit(0)

    settings = {"BENCH_ENGINE": "/usr/bin/engine", "BENCH_IMAGE": "tb-bench-runner:x", "BENCH_ALLOW_HOSTS": "a.test"}
    monkeypatch.setattr(launcher, "read_settings", lambda _p: settings)
    monkeypatch.setattr(launcher, "CNI_DIR", tmp_path)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(os, "execv", execv)
    monkeypatch.setattr(os, "geteuid", lambda: user.pw_uid)
    monkeypatch.setattr(os, "getuid", lambda: user.pw_uid)
    for key in launcher.ENGINE_ENV_DROPPED:  # restored after the test, whatever the step drops
        monkeypatch.delenv(key, raising=False)
    for key, value in {"XDG_RUNTIME_DIR": "/run/user/0", "HOME": "/nowhere", "XDG_DATA_HOME": "/elsewhere"}.items():
        monkeypatch.setenv(key, value)

    def go() -> int | None:
        try:
            return launcher.main(["proxy", "--settings", "/dev/null"])
        except SystemExit:
            return None

    return user, calls, answers, seen, go


def test_the_users_steps_use_its_own_runtime_folder_whatever_the_caller_set(proxy_step: Any) -> None:
    user, _, _, seen, go = proxy_step
    assert go() is None  # the engine was started
    env = seen["env"]
    assert env["XDG_RUNTIME_DIR"] == f"/run/user/{user.pw_uid}" and env["HOME"] == user.pw_dir
    assert "XDG_DATA_HOME" not in env


def test_the_proxy_makes_its_network_when_its_users_engine_does_not_see_it(proxy_step: Any) -> None:
    _, calls, answers, seen, go = proxy_step
    answers["exists"] = 1
    assert go() is None
    nets = [c[1:4] for c in calls if c[1] == "network"]
    assert nets == [["network", "exists", launcher.EGRESS_NET], ["network", "create", launcher.EGRESS_NET]]
    assert seen["exec"][1][seen["exec"][1].index("--network") + 1] == launcher.EGRESS_NET


def test_the_proxy_does_not_remake_a_network_it_sees(proxy_step: Any) -> None:
    _, calls, _, seen, go = proxy_step
    assert go() is None and "exec" in seen
    assert [c[2] for c in calls if c[1] == "network"] == ["exists"]


def test_the_proxy_stops_when_its_network_cannot_be_made(proxy_step: Any) -> None:
    _, _, answers, seen, go = proxy_step
    answers["exists"] = answers["create"] = 1
    assert go() == 1 and "exec" not in seen


def test_the_proxy_stops_before_the_engine_without_the_cni_folder(
    proxy_step: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reproduced on the distribution's engine 4.9.3 with netavark 1.4: without /var/lib/cni the engine mounts an
    empty folder over /var/lib while it sets up a rootless user's network, so the user's home (and its networks)
    vanish there: "network not found". The proxy says so instead of starting the engine."""
    _, calls, _, seen, go = proxy_step
    monkeypatch.setattr(launcher, "CNI_DIR", tmp_path / "cni")
    assert go() == 1 and calls == [] and "exec" not in seen
    assert "/cni is missing" in capsys.readouterr().err


def _networks(tmp_path: Path, cni: Path, then: str) -> subprocess.CompletedProcess[str]:
    etc = tmp_path / "etc"
    etc.mkdir(exist_ok=True)
    body = (
        f'CNI_DIR="{cni}"; ETC="{etc}"; MADE="$ETC/made"\n'
        'install() { mkdir -p "${@: -1}"; }; get() { echo engine; }; as_tb() { return 0; }\n'
        "make_networks\n" + then
    )
    return _bash(INSTALL, body)


def test_the_install_makes_the_cni_folder_and_remove_takes_it_away_if_empty(tmp_path: Path) -> None:
    cni = tmp_path / "cni"
    got = _networks(tmp_path, cni, "")
    made = (tmp_path / "etc" / "made").read_text(encoding="utf-8")
    assert got.returncode == 0 and cni.is_dir() and f"dir\t{cni}\n" in made, got.stderr
    remove = REMOVE_STAND_INS.format(root=tmp_path) + f'CNI_DIR="{cni}"\ncmd_remove\n'
    got = _bash(INSTALL, remove)
    assert got.returncode == 0 and not cni.exists(), got.stdout + got.stderr


def test_remove_leaves_a_cni_folder_it_did_not_make_or_that_holds_files(tmp_path: Path) -> None:
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    got = _networks(tmp_path, theirs, "")
    assert got.returncode == 0 and not (tmp_path / "etc" / "made").exists()
    remove = REMOVE_STAND_INS.format(root=tmp_path) + f'CNI_DIR="{theirs}"\ncmd_remove\n'
    got = _bash(INSTALL, remove)  # no record at all: nothing is deleted, and remove says so (exit 1)
    assert got.returncode == 1 and theirs.is_dir() and "nothing was deleted (no record)" in got.stdout
    ours = tmp_path / "ours"
    assert _networks(tmp_path, ours, "").returncode == 0
    (ours / "a-file").write_text("x", encoding="utf-8")
    got = _bash(INSTALL, REMOVE_STAND_INS.format(root=tmp_path) + f'CNI_DIR="{ours}"\ncmd_remove\n')
    assert got.returncode == 0 and ours.is_dir() and "is left: something else has put files in it" in got.stdout


HOST_TOOLS = [
    "systemctl",
    "loginctl",
    "runuser",
    "python3",
    "curl",
    "sha256sum",
    "useradd",
    "usermod",
    "userdel",
    "newuidmap",
    "newgidmap",
    "tar",
]


def test_the_install_stops_before_any_change_without_the_networks_helpers(tmp_path: Path) -> None:
    """A fresh host lacks the engine's network helpers: named, before anything is changed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for cmd in HOST_TOOLS:
        (bin_dir / cmd).symlink_to("/bin/true")
    body = f'PATH="{bin_dir}"; HELPER_DIRS=("{tmp_path}/none")\nprerequisites\necho NO-STOP'
    got = _bash(INSTALL, body)
    assert got.returncode == 1 and "NO-STOP" not in got.stdout
    assert "missing on this host: slirp4netns or pasta netavark aardvark-dns" in got.stderr
    (bin_dir / "pasta").symlink_to("/bin/true")
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    for helper in ("netavark", "aardvark-dns"):
        (helpers / helper).symlink_to("/bin/true")
    got = _bash(INSTALL, f'PATH="{bin_dir}"; HELPER_DIRS=("{helpers}")\nprerequisites')
    assert "missing on this host" not in got.stderr


REMOVE_STAND_INS = """
need_root() {{ :; }}; systemctl() {{ :; }}; id() {{ return 1; }}; sed() {{ :; }}; get() {{ :; }}
ETC="{root}/etc"; OPT="{root}/opt"; HOME_DIR="{root}/home-dir"; UNITS="{root}/units"; TOKEN="$ETC/token"
SETTINGS="$ETC/settings.env"; MADE="$ETC/made"
"""


def test_roots_steps_do_not_take_the_users_engine_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/77")
    monkeypatch.setattr(launcher, "read_settings", lambda _p: {"BENCH_LABEL": "tb-bench"})
    monkeypatch.setattr(launcher, "cleanup", lambda _s, _slot: 0)
    assert launcher.main(["cleanup", "--settings", "/dev/null", "--slot", "cpu-1"]) == 0
    assert os.environ["XDG_RUNTIME_DIR"] == "/run/user/77"


# --- the scripts the runbook runs by path can be run so ---------------------------------------------------------


def test_every_script_of_the_runner_is_executable() -> None:
    for script in sorted(BENCH_CI.glob("*.sh")):
        assert script.stat().st_mode & stat.S_IXUSR, script.name


# --- verify before the token step: the token's lines and the slots' say NOT RUN, never PASS ----------------------

VERIFY_STAND_INS = """
need_root() { :; }; as_tb() { return 1; }; as_tb_launcher() { return 0; }
systemctl() { return 0; }; id() { echo tb-bench; }
get() { case "$1" in BENCH_CPU_SLOTS) echo 1 ;; *) echo 0 ;; esac; }
"""


def test_verify_without_a_token_says_not_run_for_the_token_and_the_slots(tmp_path: Path) -> None:
    body = VERIFY_STAND_INS + f'TOKEN="{tmp_path}/token"\ncmd_verify "{tmp_path}"'
    got = _bash(INSTALL, body)
    lines = got.stdout.splitlines()
    assert got.returncode == 0, got.stdout
    assert sum(ln.startswith("NOT RUN ") for ln in lines) == 2
    assert not any("token file" in ln for ln in lines if ln.startswith(("PASS", "FAIL")))
    assert not any(ln.startswith("PASS tb-bench-runner@") for ln in lines)
    assert lines[-1] == "verify: 0 failure(s), 2 not run"


def test_verify_with_a_token_checks_the_token_and_the_slots(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("t\n", encoding="utf-8")
    body = VERIFY_STAND_INS + f'TOKEN="{token}"\ncmd_verify "{tmp_path}"'
    lines = _bash(INSTALL, body).stdout.splitlines()
    assert not any(ln.startswith("NOT RUN") for ln in lines)
    assert any(ln.endswith("the token file is root's, mode 0600") for ln in lines)
    assert "PASS tb-bench-runner@cpu-1.service runs" in lines


# --- the real-host test's report: counts, a failed step's lines, and no folder or host named ------------------------


def test_the_host_tests_report_names_no_folder_and_counts_each_result(tmp_path: Path) -> None:
    secret = "/srv/the-owners-datasets"
    body = (
        f'LOG="{tmp_path}"\nREDACT=("{secret}" "<folder 1>")\n'
        f'loud() {{ echo "cannot read {secret}"; return 3; }}\n'
        'step "a step that fails" loud\nstep "a step that passes" true\nresult NOT-RUN "a job"\n'
        'echo "counts $passes $fails $skipped"'
    )
    got = _bash(HOST_TEST, body)
    assert got.returncode == 0, got.stderr
    assert secret not in got.stdout
    assert "FAIL a step that fails (exit 3); its last lines:" in got.stdout
    assert "    | cannot read <folder 1>" in got.stdout
    assert "PASS a step that passes" in got.stdout and "NOT-RUN a job" in got.stdout
    assert got.stdout.rstrip().endswith("counts 1 1 1")


def test_the_host_test_runs_install_verify_and_remove_in_that_order_and_uses_no_token() -> None:
    text = HOST_TEST.read_text(encoding="utf-8")
    main = text[text.index("main() {") :]
    order = [main.index(s) for s in ('install.sh" install', 'install.sh" verify "$@"', 'install.sh" remove')]
    assert order == sorted(order)
    assert 'if [ -e "$TOKEN" ]; then' in main and 'install.sh" token' not in text
    assert '[ "$fails" = 0 ]' in main


def test_the_runbook_names_what_a_fresh_host_lacks_and_the_host_test() -> None:
    page = RUNBOOK.read_text(encoding="utf-8")
    assert "`uidmap` (`newuidmap`, `newgidmap`)" in page and "a fresh host lacks" in page
    assert "sudo trialbox/tools/bench_ci/host_test.sh FOLDER..." in page


# --- OCR 1466-2 (High): remove takes only what install recorded that it made ------------------------------------


def _remove(tmp_path: Path, extra: str = "") -> subprocess.CompletedProcess[str]:
    (tmp_path / "etc").mkdir(exist_ok=True)
    settings = tmp_path / "etc" / "settings.env"
    if not settings.exists():
        settings.write_text("BENCH_REPO=o/r\n", encoding="utf-8")
    return _bash(INSTALL, REMOVE_STAND_INS.format(root=tmp_path) + extra + "cmd_remove\n")


def test_a_planted_folder_of_another_owner_survives_install_and_remove(tmp_path: Path) -> None:
    """The settings name, by a slip, a folder another owner fills (the datasets): install refuses it, and remove, run
    after that failed install, leaves it whole."""
    data = tmp_path / "datasets"
    data.mkdir()
    (data / "study.csv").write_text("synthetic\n", encoding="utf-8")
    (tmp_path / "etc").mkdir()
    pick = f'get() {{ case "$1" in BENCH_SCRATCH) echo "{data}" ;; *) echo 0 ;; esac; }}\n'
    where = f'ETC="{tmp_path}/etc"; MADE="$ETC/made"; OPT="{tmp_path}/opt"; UNITS="{tmp_path}/units"\n'
    refused = _bash(INSTALL, where + "install() { :; }; chmod() { :; }\n" + pick + "install_files")
    assert refused.returncode != 0 and "in use by another owner" in refused.stderr, refused.stderr
    got = _remove(tmp_path, pick)
    assert (data / "study.csv").read_text(encoding="utf-8") == "synthetic\n", got.stdout + got.stderr
    assert f"scratch {data} is kept: install did not make it" in got.stdout


def test_remove_takes_a_scratch_folder_install_recorded(tmp_path: Path) -> None:
    scratch = tmp_path / "ci-scratch"
    (scratch / "tb-bench-cpu-1").mkdir(parents=True)
    pick = f'get() {{ case "$1" in BENCH_SCRATCH) echo "{scratch}" ;; *) echo 0 ;; esac; }}\n'
    got = _remove(tmp_path, pick + f'record_made dir "{scratch}"\n')
    assert got.returncode == 0 and not scratch.exists(), got.stdout + got.stderr
    assert not (tmp_path / "etc" / "made").exists()  # nothing is left, so the record goes too


def test_remove_without_a_record_deletes_nothing_and_says_so(tmp_path: Path) -> None:
    for d in ("opt", "units", "home-dir"):
        (tmp_path / d).mkdir()
    (tmp_path / "units" / "tb-bench-proxy.service").write_text("x", encoding="utf-8")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "token").write_text("t\n", encoding="utf-8")
    got = _remove(tmp_path)
    assert got.returncode == 1 and "nothing was deleted (no record)" in got.stdout
    assert "removed from this host" not in got.stdout
    for p in ("opt", "units/tb-bench-proxy.service", "home-dir", "etc/token"):
        assert (tmp_path / p).exists(), p


def test_remove_keeps_the_operators_settings(tmp_path: Path) -> None:
    """OCR 1466-8: the settings file is the operator's (filled by hand); remove keeps it."""
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.env").write_text("BENCH_REPO=o/r\n", encoding="utf-8")
    got = _remove(tmp_path, f'record_made dir "{tmp_path}/opt"\n')
    assert got.returncode == 0 and (tmp_path / "etc" / "settings.env").exists(), got.stdout + got.stderr


def test_the_record_is_written_before_the_thing_is_made_and_whole(tmp_path: Path) -> None:
    """A cut install leaves a line for a thing that is not there, never a thing with no line (OCR 1466-7); the record
    is root's own, written through a copy and a rename, one line per thing."""
    etc = tmp_path / "etc"
    etc.mkdir()
    cni = tmp_path / "cni"
    body = f'ETC="{etc}"; MADE="$ETC/made"; CNI_DIR="{cni}"\ninstall() {{ return 1; }}; get() {{ echo e; }}\n'
    got = _bash(INSTALL, body + "make_networks")
    assert got.returncode != 0 and not cni.exists()
    made = etc / "made"
    assert made.read_text(encoding="utf-8") == f"dir\t{cni}\n"
    assert stat.S_IMODE(made.stat().st_mode) == 0o600
    again = f'ETC="{etc}"; MADE="$ETC/made"\nrecord_made dir "{cni}"\nrecord_made user tb-bench\n'
    assert _bash(INSTALL, again).returncode == 0
    assert made.read_text(encoding="utf-8") == f"dir\t{cni}\nuser\ttb-bench\n"
    assert sorted(p.name for p in etc.iterdir()) == ["made"]  # no copy left behind


def test_an_empty_folder_of_another_owner_is_not_taken_as_scratch(tmp_path: Path) -> None:
    """OCR 1466-9: install handed an existing empty folder of any owner to the jobs' user, and remove deleted it."""
    empty = tmp_path / "empty"
    empty.mkdir()
    pick = f'get() {{ case "$1" in BENCH_SCRATCH) echo "{empty}" ;; *) echo 0 ;; esac; }}\n'
    got = _bash(INSTALL, "install() { :; }; chmod() { :; }\n" + pick + "install_files")
    assert got.returncode != 0 and "in use by another owner" in got.stderr and empty.is_dir()


# --- OCR 1466-1 (High), 1466-6, 1466-7: the host test's own paths -----------------------------------------------


def test_a_step_whose_name_holds_a_slash_is_run_and_the_test_goes_on(tmp_path: Path) -> None:
    body = (
        f'LOG="{tmp_path}"\n'
        f'step "the folder a/b is there" test -d "{tmp_path}"\n'
        'step "a/b fails" false\n'
        'echo "REACHED $passes $fails"'
    )
    got = _bash(HOST_TEST, body)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "PASS the folder a/b is there" in got.stdout
    assert "FAIL a/b fails (exit 1); its last lines:" in got.stdout
    assert got.stdout.rstrip().endswith("REACHED 1 1")


def _host_run(tmp_path: Path, install_rc: int, extra: str = "") -> tuple[subprocess.CompletedProcess[str], str]:
    """main with a stand-in install.sh that notes each command it is run with; root's id given; the host's own checks
    replaced where they would read the bench host."""
    fake = tmp_path / "src"
    fake.mkdir()
    marks = tmp_path / "marks"
    (tmp_path / "settings.env").write_text("x\n", encoding="utf-8")
    (fake / "install.sh").write_text(
        f'TOKEN="{tmp_path}/token"; SETTINGS="{tmp_path}/settings.env"; MADE="{tmp_path}/made"; UNITS="{tmp_path}"\n'
        "get() { return 1; }; as_tb() { :; }\n"
        'if [ "${BASH_SOURCE[0]}" = "$0" ]; then\n'
        f'  echo "$1" >> "{marks}"\n'
        f'  if [ "$1" = install ]; then {extra or ":"}; exit {install_rc}; fi\n'
        '  if [ "$1" = verify ]; then echo "NOT RUN the token"; echo "NOT RUN the slots"; fi\n'
        "fi\n",
        encoding="utf-8",
    )
    (fake / "install.sh").chmod(0o755)
    body = (
        f'SRC="{fake}"\n'
        'id() { if [ "$*" = -u ]; then echo 0; else command id "$@"; fi; }\n'
        "proxy_holds() { :; }; proxy_runtime_is_its_users() { :; }; proxy_container_runs() { :; }\n"
        "units_name_no_runtime_folder() { :; }; nothing_left() { :; }\n"
        f'mktemp() {{ command mktemp -d "{tmp_path}/logs.XXXXXX"; }}\n'
        f'main "{tmp_path}/a-folder"\n'
    )
    got = _bash(HOST_TEST, body)
    return got, marks.read_text(encoding="utf-8") if marks.exists() else ""


def test_the_host_test_never_runs_remove_after_a_failed_install(tmp_path: Path) -> None:
    got, marks = _host_run(tmp_path, install_rc=1)
    assert got.returncode == 1 and marks == "install\n", got.stdout + got.stderr
    assert "NOT-RUN the checks, verify and remove: the install failed" in got.stdout
    assert "0 passed, 1 failed, 1 not run" in got.stdout


def test_the_host_test_runs_install_verify_remove_and_counts_verifys_not_run_lines(tmp_path: Path) -> None:
    got, marks = _host_run(tmp_path, install_rc=0)
    assert marks == "install\nverify\nremove\n", got.stdout + got.stderr
    assert "PASS verify (its 2 NOT RUN line(s) counted as not run)" in got.stdout
    assert re.search(r"host test: \d+ passed, \d+ failed, 3 not run", got.stdout), got.stdout


def test_a_signal_ends_the_host_test_with_where_it_stopped_and_no_remove(tmp_path: Path) -> None:
    got, marks = _host_run(tmp_path, install_rc=0, extra="kill -s TERM $PPID; sleep 1")
    assert got.returncode == 130 and marks == "install\n", got.stdout + got.stderr
    assert "interrupted during: install" in got.stdout and "install.sh remove" in got.stdout


def test_the_units_check_fails_when_no_unit_was_laid_out(tmp_path: Path) -> None:
    """OCR 1466-6 (1): a failed install leaves no unit; "no unit names a runtime folder" must not pass then."""
    got = _bash(HOST_TEST, f'UNITS="{tmp_path}"\nunits_name_no_runtime_folder')
    assert got.returncode != 0 and "is not there" in got.stdout
    for unit in UNITS:
        shutil.copy(unit, tmp_path / unit.name)
    assert _bash(HOST_TEST, f'UNITS="{tmp_path}"\nunits_name_no_runtime_folder').returncode == 0


def test_nothing_left_reads_the_record_and_names_what_is_still_there(tmp_path: Path) -> None:
    still = tmp_path / "still"
    still.mkdir()
    record = tmp_path / "made.list"
    record.write_text(f"dir\t{still}\ndir\t{tmp_path}/gone\n", encoding="utf-8")
    got = _bash(HOST_TEST, f'nothing_left "{record}" none')
    assert got.returncode != 0 and f"left: {still}" in got.stdout and "gone" not in got.stdout
    record.write_text("", encoding="utf-8")
    assert "no record" in _bash(HOST_TEST, f'nothing_left "{record}" none').stdout


def test_the_report_names_no_checkout_operator_or_address(tmp_path: Path) -> None:
    """OCR 1466-5: bash's own lines carry the checkout's path, the engine's carry the job networks' addresses."""
    me = pwd.getpwuid(os.getuid())
    line = f"{ROOT}/tools/bench_ci/install.sh: line 9: x; {me.pw_dir}/y {me.pw_name} 10.231.5.2/24 fd00::2 11:12:28"
    body = f'hostname() {{ echo bench-host-x; }}\nSUDO_USER="{me.pw_name}"\nadd_redactions "{tmp_path}"\necho "{line}" | redact'
    got = _bash(HOST_TEST, body)
    assert got.returncode == 0, got.stderr
    out = got.stdout
    assert str(ROOT.parent) not in out and "10.231" not in out and "fd00" not in out, out
    assert "<checkout>/trialbox/tools/bench_ci/install.sh" in out and "11:12:28" in out
    if me.pw_name != "root":
        assert me.pw_dir not in out and f" {me.pw_name} " not in out
