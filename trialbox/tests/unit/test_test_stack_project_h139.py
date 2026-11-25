"""H-139, item 7 (the integrator's 7151749260, ruled a): the compose test stack has its own project, ``trialbox-test``,
and `make up-test` refuses, plainly, when what the stack would take belongs to another project or program.

On the bench host the compose stage's tests reached services that answered 401 to a test stack's unauthenticated
calls. The base compose file names its project ``trialbox``, the name a box installed on the same host has.
"""

from __future__ import annotations

import io
import json
import re
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import failure_drill_box as fdb
from tools import test_stack_free as tsf

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
PROJECT = "trialbox-test"


def _make_var(name: str) -> str:
    m = re.search(rf"^{name} := (.+)$", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M)
    assert m, name
    return m.group(1)


def _recipe(target: str) -> str:
    m = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", (ROOT / "Makefile").read_text(encoding="utf-8"),
                  re.M)  # fmt: skip
    assert m, target
    return m.group(1)


# ------------------------------------------------------------------------------------------------ the project name
def test_the_test_stack_has_its_own_project_in_the_makefile_and_the_failure_drill() -> None:
    assert _make_var("TEST_PROJECT") == PROJECT
    assert " -p $(TEST_PROJECT) " in _make_var("COMPOSE_TEST")
    assert fdb.TEST_PROJECT == PROJECT
    argv = fdb.compose("ps")
    assert argv[argv.index("-p") + 1] == PROJECT


def test_the_rendered_test_stack_names_its_project_and_every_network_by_it(tmp_path: Path) -> None:
    """``docker compose -p trialbox-test`` (as COMPOSE_TEST runs it): the project and every fixed network name follow
    it (H-75's variable), so nothing of the stack is named as a box's."""
    (tmp_path / ".env").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run(["docker", "compose", "--project-directory", str(tmp_path), "-p", PROJECT,
                        "-f", str(DEPLOY / "docker-compose.yml"), "-f", str(DEPLOY / "docker-compose.test.yml"),
                        "--profile", "stub", "--profile", "test", "config", "--format", "json"],
                       capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr[-2000:]
    doc = json.loads(r.stdout)
    assert doc["name"] == PROJECT
    nets = [n["name"] for n in doc["networks"].values()]
    assert nets and all(n.startswith(f"{PROJECT}-") for n in nets), nets
    assert not any(s.get("container_name") for s in doc["services"].values())


def test_up_test_checks_what_it_would_take_before_it_starts() -> None:
    recipe = _recipe("up-test")
    prep, check, up = recipe.index("objects-dir"), recipe.index("tools.test_stack_free"), recipe.index("up -d --wait")
    assert prep < check < up
    assert "pipefail" in recipe and "config --format json" in recipe and "$(TEST_PROJECT)" in recipe


# ------------------------------------------------------------------------------------------------ the refusal
CONFIG = {"services": {"orchestrator": {"ports": [{"host_ip": "127.0.0.1", "published": "8010", "target": 8010}]},
                       "db": {"ports": [{"host_ip": "127.0.0.1", "published": "5433", "target": 5432}]},
                       "lake": {}}}  # fmt: skip


def _row(name: str, project: str | None, ports: str = "") -> dict[str, str]:
    labels = f"com.docker.compose.service=x,{tsf.PROJECT_LABEL}={project}" if project else "maintainer=synthetic"
    return {"Names": name, "Labels": labels, "Ports": ports}


def _all_free(addr: str, port: int) -> bool:
    return True


def test_a_box_of_another_project_on_a_port_the_stack_would_publish_is_refused_by_name() -> None:
    rows = [_row("trialbox-orchestrator-1", "trialbox", "127.0.0.1:8010->8010/tcp")]
    got = tsf.problems(CONFIG, rows, PROJECT, free=_all_free)
    assert got == ["container trialbox-orchestrator-1 (compose project 'trialbox') publishes 127.0.0.1:8010, which "
                   "the test stack would publish"]  # fmt: skip


def test_a_port_published_on_every_address_clashes_too() -> None:
    rows = [_row("other-db-1", "other", "0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp")]
    got = tsf.problems(CONFIG, rows, PROJECT, free=_all_free)
    assert len(got) == 2 and all("publishes" in g and ":5433" in g and "'other'" in g for g in got), got


def test_a_container_with_the_stacks_name_in_another_project_is_refused() -> None:
    rows = [_row(f"{PROJECT}-lake-1", "someone-else")]
    assert tsf.problems(CONFIG, rows, PROJECT, free=_all_free) == [
        f"container {PROJECT}-lake-1 (compose project 'someone-else') has the name a container of the test stack "
        "would get"
    ]


def test_the_stacks_own_containers_from_an_earlier_up_are_no_reason_to_refuse() -> None:
    rows = [_row(f"{PROJECT}-orchestrator-1", PROJECT, "127.0.0.1:8010->8010/tcp"),
            _row(f"{PROJECT}-db-1", PROJECT, "127.0.0.1:5433->5432/tcp")]  # fmt: skip

    def held(addr: str, port: int) -> bool:  # the ports are held, by the stack itself
        return False

    assert tsf.problems(CONFIG, rows, PROJECT, free=held) == []


def test_a_port_held_outside_docker_is_refused() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        config = {"services": {"console": {"ports": [{"host_ip": "127.0.0.1", "published": str(port)}]}}}
        assert tsf.problems(config, [], PROJECT) == [
            f"127.0.0.1:{port}, which the test stack would publish, is held by something that is not a container of "
            "the test stack"
        ]
    assert tsf.problems(config, [], PROJECT) == []  # once let go, it is free


def test_nothing_else_running_starts_the_stack(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(tsf, "running_containers", lambda: [])
    monkeypatch.setattr(tsf, "bindable", _all_free)
    assert tsf.main([PROJECT], stdin=io.StringIO(json.dumps(CONFIG))) == 0
    assert capsys.readouterr().err == ""


def test_the_refusal_is_said_plainly_and_nothing_starts(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(tsf, "running_containers",
                        lambda: [_row("trialbox-orchestrator-1", "trialbox", "127.0.0.1:8010->8010/tcp")])  # fmt: skip
    monkeypatch.setattr(tsf, "bindable", _all_free)
    assert tsf.main([PROJECT], stdin=io.StringIO(json.dumps(CONFIG))) == 1
    err = capsys.readouterr().err
    assert "was not started" in err and "trialbox-orchestrator-1" in err and "Stop that stack" in err


def test_a_configuration_that_cannot_be_read_starts_nothing(capsys: Any) -> None:
    assert tsf.main([PROJECT], stdin=io.StringIO("")) == 1
    assert "could not be read" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ H139-14: TEST always
def _pins() -> dict[str, str]:
    """The settings COMPOSE_TEST gives compose before its command, those with a plain value."""
    head = _make_var("COMPOSE_TEST").split("$(COMPOSE)")[0].split()
    return dict(a.split("=", 1) for a in head if "=" in a and "$(" not in a)


def _service_envs(tmp_path: Path, env: dict[str, str]) -> dict[str, dict[str, str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run(["docker", "compose", "--project-directory", str(tmp_path), "-p", PROJECT,
                        "-f", str(DEPLOY / "docker-compose.yml"), "-f", str(DEPLOY / "docker-compose.test.yml"),
                        "--profile", "stub", "--profile", "test", "config", "--format", "json"],
                       capture_output=True, text=True, timeout=120, check=False, env=env)  # fmt: skip
    assert r.returncode == 0, r.stderr[-2000:]
    return {n: dict(s.get("environment") or {}) for n, s in json.loads(r.stdout)["services"].items()}


def test_the_test_stack_is_test_and_d0_whatever_the_caller_exports(tmp_path: Path) -> None:
    """A caller whose shell exports the TB_ENV of the host's own box (and its data class) still starts a TEST stack:
    no caller's environment variable decides it. Without COMPOSE_TEST's settings the caller's value would reach
    every service that takes ${TB_ENV:-TEST}."""
    import os

    pins = _pins()
    assert pins.get("TB_ENV") == "TEST" and pins.get("TB_DATA_CLASS") == "D0", pins
    assert {"TB_ENV": "TEST", "TB_DATA_CLASS": "D0"}.items() <= fdb.compose_env().items()
    caller = {**os.environ, "TB_ENV": "PRODUCTION", "TB_DATA_CLASS": "D3"}
    pinned = _service_envs(tmp_path / "pinned", {**caller, **pins})
    envs = {n: e["TB_ENV"] for n, e in pinned.items() if "TB_ENV" in e}
    assert envs and set(envs.values()) == {"TEST"}, envs
    assert all(e.get("TB_DATA_CLASS", "D0") == "D0" for e in pinned.values())
    bare = _service_envs(tmp_path / "bare", caller)  # the gap the settings close
    assert any(bare[n].get("TB_ENV") == "PRODUCTION" for n in _takes_test())


def _takes_test() -> list[str]:
    """The services the test file gives ``TB_ENV: "${TB_ENV:-TEST}"``."""
    import yaml

    doc = yaml.safe_load((DEPLOY / "docker-compose.test.yml").read_text(encoding="utf-8"))
    return [n for n, s in (doc.get("services") or {}).items()
            if isinstance(s, dict) and "${TB_ENV:-TEST}" in json.dumps(s.get("environment") or {})]  # fmt: skip


def test_up_test_says_on_its_first_line_that_the_stack_is_test() -> None:
    first = _recipe("up-test").splitlines()[0]
    assert first.lstrip("\t").startswith("@echo") and "TB_ENV=TEST" in first and "TB_DATA_CLASS=D0" in first
