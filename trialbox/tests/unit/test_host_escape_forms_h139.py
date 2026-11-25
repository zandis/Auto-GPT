"""OCR 1498-2: each way a unit test can reach the host is recorded by ``tests.host_escape.watch``.

Every command here is run through ``true``, so the engine it names never runs. Every host path is only looked at, and
a socket is connected to a path that does not exist.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
from pathlib import Path

import pytest

from tests import host_escape

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize(("args", "shell"), [
    (["true", "docker", "info"], False),  # an engine as an argument
    (["true", "sudo", "docker", "info"], False),  # after sudo
    (["true", "env", "A=1", "podman", "ps"], False),  # after env
    (["true", "bash", "-c", "docker info"], False),  # inside bash -c
    ("true docker info", True),  # a shell string
    ("true && /usr/bin/docker volume ls", True),  # a path to the engine
])  # fmt: skip
def test_an_engine_named_anywhere_in_a_command_is_recorded(
    monkeypatch: pytest.MonkeyPatch, args: list[str] | str, shell: bool
) -> None:
    seen = host_escape.watch(monkeypatch)
    subprocess.run(args, shell=shell, check=False, capture_output=True)
    assert seen and all(s.startswith("engine: ") for s in seen), seen


def test_the_tests_own_stand_in_is_not_the_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    seen = host_escape.watch(monkeypatch)
    subprocess.run([str(stub), "info"], check=False, capture_output=True)
    assert seen == []


@pytest.mark.parametrize("look", ["listdir", "scandir", "access", "stat", "lstat"])
@pytest.mark.parametrize("path", ["/run/trialbox", "/var/lib/docker/volumes", "/var/lib/containers/storage"])
def test_a_look_at_a_host_folder_is_recorded(monkeypatch: pytest.MonkeyPatch, look: str, path: str) -> None:
    seen = host_escape.watch(monkeypatch)
    with contextlib.suppress(OSError):
        if look == "access":
            os.access(path, os.R_OK)
        elif look == "scandir":
            with os.scandir(path):
                pass
        else:
            getattr(os, look)(path)
    assert seen == [path]


def test_a_unix_socket_connect_to_a_host_path_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = host_escape.watch(monkeypatch)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s, contextlib.suppress(OSError):
        s.connect("/run/trialbox/h139-no-such.sock")
    assert seen == ["/run/trialbox/h139-no-such.sock"]


def test_paths_and_commands_of_the_tests_own_are_not_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = host_escape.watch(monkeypatch)
    os.listdir(tmp_path)
    os.access(tmp_path, os.R_OK)
    (tmp_path / "f").write_text("x", encoding="utf-8")
    subprocess.run(["true", "--project-directory", "deploy"], check=False)
    assert seen == []
