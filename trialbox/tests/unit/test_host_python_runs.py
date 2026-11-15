"""D-832: the modules install.sh runs with the host's python3 run there: no PYTHONPATH, no site packages, PyYAML only
(HOST_PY_MODULES, D-831).

On a clean Ubuntu 24.04 host `python3 -m tools.trialbox.pgsize` (T-703, D-751) stopped the installer with
"No module named 'tb_common'": a lazy import, which a top-level scan does not see. Each command here runs for real
in a bare interpreter, so a lazy import of a module the host lacks fails the test."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from tools.trialbox import pgsize

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


@pytest.fixture()
def host_path(tmp_path: Path) -> Path:
    """A folder holding PyYAML alone: what the installer requires of the host's python3."""
    only = tmp_path / "host-site"
    only.mkdir()
    site = Path(sysconfig.get_paths()["purelib"])
    for name in ("yaml", "_yaml"):
        if (site / name).exists():
            (only / name).symlink_to(site / name)
    return only


def _host(host_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
    env["PYTHONPATH"] = str(host_path)
    # -S: no site packages (the venv's or the system's), -s: no user site; the module is found from ROOT, as install.sh
    return subprocess.run(
        [sys.executable, "-S", "-s", "-m", *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )


def test_the_bare_interpreter_has_no_project_dependency(host_path: Path) -> None:
    res = _host(host_path, "json.tool", "--help")
    assert res.returncode == 0
    probe = subprocess.run(
        [sys.executable, "-S", "-s", "-c", "import pydantic"],
        cwd=ROOT,
        env={"PYTHONPATH": str(host_path), "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode != 0  # the stand-in really lacks what the box image has


def test_pgsize_sizes_and_writes_on_the_host(host_path: Path, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TB_MEM_DB=8g\n", encoding="utf-8")
    res = _host(host_path, "tools.trialbox.pgsize", "--env-file", str(env_file), "--write")
    assert res.returncode == 0, res.stderr
    assert "ModuleNotFoundError" not in res.stderr
    assert "TB_PG_" in env_file.read_text(encoding="utf-8")


def test_memcaps_runs_on_the_host(host_path: Path, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TB_SITE_PATIENTS=1000\n", encoding="utf-8")
    res = _host(host_path, "tools.trialbox.memcaps", "--env-file", str(env_file), "--write")
    assert "ModuleNotFoundError" not in res.stderr, res.stderr
    assert res.returncode == 0, res.stderr


def test_bootwait_runs_on_the_host(host_path: Path) -> None:
    res = _host(host_path, "tools.trialbox.bootwait", "--deploy", "deploy")
    assert "ModuleNotFoundError" not in res.stderr, res.stderr
    assert res.returncode == 0, res.stderr


def test_the_compose_lock_check_anchors_and_secrets_run_on_the_host(host_path: Path, tmp_path: Path) -> None:
    """The other host steps that need no Docker: install.sh's image lock check, the anchor overlay, the secrets."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    runs = [
        ("tools.images_lock", "check-compose", "--files", "deploy/docker-compose.yml"),
        ("tools.trialbox", "anchors-compose", "--deploy", str(deploy)),
        ("tools.trialbox", "secrets", "init", "--deploy", str(deploy)),
    ]
    for args in runs:
        res = _host(host_path, *args)
        assert "ModuleNotFoundError" not in res.stderr, (args, res.stderr)
        assert res.returncode == 0, (args, res.stderr)


def test_the_lake_limit_default_is_the_declared_one() -> None:
    """pgsize keeps its own copy of the default (the host has no tb_common.config); it must not drift."""
    from tb_common.config import DECLARED

    assert DECLARED["TB_LAKE_QUERY_LIMITS"].default == pgsize.LAKE_QUERY_LIMITS_DEFAULT


def test_a_failed_sizing_stops_the_installer_with_its_message() -> None:
    """Under pipefail a failing `python3 ... | sed` ended the script before its `[ PIPESTATUS ] || die` line: the
    operator saw a traceback and no word on what to do. The die now hangs on the pipe itself."""
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    for module in ("tools.trialbox.memcaps", "tools.trialbox.pgsize"):
        at = text.index(f"python3 -m {module}")
        line = text[at : text.index("\n", at)]
        assert "|| die" in line, line
        assert "PIPESTATUS" not in text[at : at + 400]


def test_every_pipestatus_check_is_reached() -> None:
    """A `[ "${PIPESTATUS[0]}" ... ]` line runs only where `set +e` is in force: under set -e and pipefail the
    failing pipe ends the script first, silently (the TLS check had the same dead line). Inside a function, every
    call of the function must be under set +e."""
    lines = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8").splitlines()
    state, func, states, in_func = "-e", None, [], {}
    for line in lines:
        s = line.strip()
        if s.startswith("set +e"):
            state = "+e"
        elif s.startswith("set -e") or s.startswith("set -euo"):
            state = "-e"
        m = re.match(r"\s*([a-z_]+)\(\) \{\s*$", line)
        if m:
            func = m.group(1)
        elif func and s == "}":
            func = None
        states.append(state)
        in_func[len(states)] = func
    for n, line in enumerate(lines, 1):
        if "PIPESTATUS" not in line or line.strip().startswith("#"):
            continue
        func = in_func[n]
        if func is None:
            assert states[n - 1] == "+e", f"install.sh:{n} reads PIPESTATUS under set -e: it is never reached"
            continue
        calls = [i for i, other in enumerate(lines, 1) if re.match(rf"\s*{func}( |$)", other)]
        assert calls, f"install.sh:{n}: {func} is never called"
        for i in calls:
            assert states[i - 1] == "+e", f"install.sh:{i} calls {func} (PIPESTATUS at :{n}) under set -e"
