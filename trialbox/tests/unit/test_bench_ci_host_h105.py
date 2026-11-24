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
import stat
import subprocess
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
    """``source`` the script (it only defines its steps), then run ``body`` with its stand-ins."""
    text = f'set -euo pipefail\nsource "{script}"\n{body}\n'
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
        f'CNI_DIR="{cni}"; ETC="{etc}"; CNI_MARK="$ETC/made-cni-dir"\n'
        'install() { mkdir -p "${@: -1}"; }; get() { echo engine; }; as_tb() { return 0; }\n'
        "make_networks\n" + then
    )
    return _bash(INSTALL, body)


def test_the_install_makes_the_cni_folder_and_remove_takes_it_away_if_empty(tmp_path: Path) -> None:
    cni = tmp_path / "cni"
    got = _networks(tmp_path, cni, "")
    assert got.returncode == 0 and cni.is_dir() and (tmp_path / "etc" / "made-cni-dir").exists(), got.stderr
    remove = REMOVE_STAND_INS.format(root=tmp_path) + f'CNI_DIR="{cni}"\ncmd_remove\n'
    got = _bash(INSTALL, remove)
    assert got.returncode == 0 and not cni.exists(), got.stdout + got.stderr


def test_remove_leaves_a_cni_folder_it_did_not_make_or_that_holds_files(tmp_path: Path) -> None:
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    got = _networks(tmp_path, theirs, "")
    assert got.returncode == 0 and not (tmp_path / "etc" / "made-cni-dir").exists()
    remove = REMOVE_STAND_INS.format(root=tmp_path) + f'CNI_DIR="{theirs}"\ncmd_remove\n'
    assert _bash(INSTALL, remove).returncode == 0 and theirs.is_dir()
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
SETTINGS="$ETC/none"; CNI_MARK="$ETC/made-cni-dir"
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
