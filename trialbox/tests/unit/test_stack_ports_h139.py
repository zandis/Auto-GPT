"""H-139 (the integrator's 7159714024): the compose tests take each port from the running test stack itself.

On the bench host a compose test got 401 from ``127.0.0.1:8016/run``, the adapter's default host port. A test that
takes a port from a constant or a variable may reach another stack on the same host, with its own keys. A port now
comes from the stack's compose files (which service and container port a ``TB_HOST_<NAME>_PORT`` publishes) and
from the engine (where the container of compose project ``trialbox-test`` publishes it). A port another project
holds is refused by name. The restore drill, which brings the stack up with ``make up-test``, addresses the same
project: its compose commands, the volumes it reads and removes, and the runbook's own ``docker compose`` lines.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import stack
from tools import restore_drill as rd

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]


def _row(name: str, project: str, service: str, ports: str) -> dict[str, object]:
    """One container as ``docker ps --format '{{json .}}'`` gives it."""
    labels = f"com.docker.compose.project={project},com.docker.compose.service={service},com.docker.compose.version=2"
    return {"Names": name, "Labels": labels, "Ports": ports}


CONFIG = {"ADAPTER": ("adapter", 8016), "LAKE": ("lake", 8013)}


def test_the_port_is_where_the_test_stacks_own_container_publishes_it() -> None:
    rows = [_row("trialbox-test-adapter-1", "trialbox-test", "adapter", "127.0.0.1:18016->8016/tcp"),
            _row("trialbox-test-lake-1", "trialbox-test", "lake", "127.0.0.1:8013->8013/tcp")]  # fmt: skip
    assert stack.port_of("ADAPTER", rows, CONFIG) == 18016  # a moved port is read, not assumed
    assert stack.port_of("LAKE", rows, CONFIG) == 8013


def test_another_projects_adapter_on_the_default_port_is_never_taken_for_the_test_stacks() -> None:
    """The bench's case: the test stack had no adapter on 8016, another stack on the host did."""
    rows = [_row("trialbox-adapter-1", "trialbox", "adapter", "127.0.0.1:8016->8016/tcp"),
            _row("trialbox-test-lake-1", "trialbox-test", "lake", "127.0.0.1:8013->8013/tcp")]  # fmt: skip
    with pytest.raises(stack.StackNotRunning) as exc:
        stack.port_of("ADAPTER", rows, CONFIG)
    said = str(exc.value)
    assert (
        "trialbox-test publishes no port for adapter:8016" in said and "trialbox-adapter-1 (project trialbox)" in said
    )


def test_a_host_port_another_project_also_publishes_is_refused() -> None:
    rows = [_row("trialbox-test-adapter-1", "trialbox-test", "adapter", "127.0.0.1:8016->8016/tcp"),
            _row("other-web-1", "other", "web", "[::]:8016->80/tcp")]  # fmt: skip
    with pytest.raises(
        stack.StackNotRunning, match=r"8016 of adapter is also published by other-web-1 \(project other\)"
    ):
        stack.port_of("ADAPTER", rows, CONFIG)


def test_no_engine_or_no_stack_is_said_plainly(tmp_path: Path) -> None:
    with pytest.raises(stack.StackNotRunning, match="publishes no port for lake:8013"):
        stack.port_of("LAKE", [], CONFIG)
    with pytest.raises(stack.StackNotRunning, match="could not be asked"):
        stack.running_containers((str(tmp_path / "no-such-engine"),))


def test_the_compose_files_say_which_service_and_container_port_each_variable_publishes() -> None:
    got = stack.published_by_config()
    assert got["ADAPTER"] == ("adapter", 8016) and got["LAKE"] == ("lake", 8013) and got["CONSOLE"] == ("console", 8090)
    named = set()
    for path in stack.COMPOSE_FILES:
        named |= set(re.findall(r"TB_HOST_([A-Z_]+)_PORT:-\d+\}:\d+", path.read_text(encoding="utf-8")))
    assert named and named <= set(got)


def test_no_port_constant_is_left_in_the_helpers() -> None:
    assert not hasattr(stack, "DEFAULT_PORTS")
    for rel in ("tests/stack.py", "tests/e2e/test_mail_compose.py", "tests/e2e/test_console_poc.py",
                "tests/integration/test_fhir_codesystems_compose.py",
                "tests/integration/test_valueset_store_compose.py", "tools/restore_drill.py"):  # fmt: skip
        code = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"https?://127\.0\.0\.1:\d", code), rel


def test_collecting_the_compose_tests_asks_no_engine(tmp_path: Path) -> None:
    """A port is read when a test runs, never at import: a collection (CI's ``--collect-only``) runs no engine."""
    marker = tmp_path / "engine-was-run"
    engine = tmp_path / "bin" / "docker"
    engine.parent.mkdir()
    engine.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    engine.chmod(0o755)
    mods = ["tests.e2e.test_mail_compose", "tests.e2e.test_console_poc", "tests.integration.test_compose_data",
            "tests.integration.test_compile_compose", "tests.integration.test_fhir_codesystems_compose",
            "tests.integration.test_valueset_store_compose", "tools.restore_drill"]  # fmt: skip
    env = {**os.environ, "PATH": f"{engine.parent}{os.pathsep}{os.environ.get('PATH', '')}",
           "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))}  # fmt: skip
    r = subprocess.run([sys.executable, "-c", f"import importlib\nfor m in {mods!r}: importlib.import_module(m)"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=300, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr[-2000:]
    assert not marker.exists()


# ------------------------------------------------------------------------------------------------- the restore drill
def test_the_restore_drill_addresses_the_stack_make_up_test_brings_up(monkeypatch: pytest.MonkeyPatch) -> None:
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(rf"^TEST_PROJECT := {re.escape(rd.TEST_PROJECT)}$", mk, re.M)
    assert stack.PROJECT == rd.TEST_PROJECT
    drill = rd.ComposeDrill.__new__(rd.ComposeDrill)
    ran: list[str] = []

    def sh(cmd: str, timeout: float | None = None, env: object = None) -> tuple[int, str]:
        ran.append(cmd)
        return 0, ""

    monkeypatch.setattr(drill, "sh", sh)
    drill.compose("down --volumes --remove-orphans")
    assert f"-p {rd.TEST_PROJECT} down" in ran[0]
    assert drill.vol("db-data").parent.name == f"{rd.TEST_PROJECT}_db-data"  # never trialbox_db-data, a box's own


def test_the_runbooks_compose_lines_reach_the_test_stack_whatever_the_caller_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "tbfullset")  # what the bench's runner exported
    rc, out = rd.shell('printf %s "$COMPOSE_PROJECT_NAME"', {})
    assert (rc, out) == (0, rd.TEST_PROJECT)


def _started_from(row: dict[str, object], *files: str) -> dict[str, object]:
    files_label = ",".join(f"/srv/tb/deploy/{f}" for f in files)
    return {**row, "Labels": f"{row['Labels']},com.docker.compose.project.config_files={files_label}"}


def test_the_poc_is_the_one_project_started_from_the_poc_file_never_a_guessed_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "trialbox")  # the box's own name: never taken on its word
    box = _started_from(_row("trialbox-console-1", "trialbox", "console", "127.0.0.1:8090->8090/tcp"),
                        "docker-compose.yml")  # fmt: skip
    poc = _started_from(_row("pocrun-console-1", "pocrun", "console", "127.0.0.1:18090->8090/tcp"),
                        "docker-compose.yml", "docker-compose.test.yml", stack.POC_FILE)  # fmt: skip
    monkeypatch.setattr(stack, "_poc", [])
    assert stack.poc_project(lambda: [box, poc]) == "pocrun"
    monkeypatch.setattr(stack, "_poc", [])
    with pytest.raises(stack.StackNotRunning, match="found: none"):
        stack.poc_project(lambda: [box])  # a box alone is never taken for the POC
    other = _started_from(_row("p2-console-1", "p2", "console", ""), stack.POC_FILE)
    with pytest.raises(stack.StackNotRunning, match="found: p2, pocrun"):
        stack.poc_project(lambda: [poc, other])
