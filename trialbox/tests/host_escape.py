"""H-139 (the integrator's 7159714024): an escape check for unit tests that must stay inside their own folders.

On the bench host, which is a real box, the pure stage ran as an ordinary account. One key test reached the host's
real KEK file (``/run/trialbox/kek``), and an update test reached the host's Docker engine and the volumes of a
real stack. In CI neither exists, so both passed there. A test that gives the code its own run folder and a stub
engine calls :func:`watch` and asserts the list stays empty. Any look at or open of the host's run folder or of an engine
socket, and any engine command not given by the test, is then a failure, not a pass that depends on the host.
"""

from __future__ import annotations

import builtins
import io
import os
import subprocess
from typing import Any

import pytest

#: the host's own run folder and the engines' sockets: a unit test never opens these
HOST_PATHS = ("/run/trialbox", "/var/run/docker.sock", "/run/docker.sock", "/run/podman", "/var/run/podman")
ENGINES = ("docker", "podman")


def _name(path: Any) -> str:
    try:
        return os.fsdecode(path) if isinstance(path, str | bytes | os.PathLike) else ""
    except (TypeError, ValueError):
        return ""


def watch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the test reached of the host: each host path it looked at or opened, and each engine command it did not stub."""
    seen: list[str] = []
    real_os_open, real_open, real_popen = os.open, builtins.open, subprocess.Popen
    real_stat, real_lstat = os.stat, os.lstat

    def check(path: Any) -> None:
        name = _name(path)
        if name.startswith(HOST_PATHS):
            seen.append(name)

    def os_open(path: Any, *a: Any, **kw: Any) -> int:
        check(path)
        return real_os_open(path, *a, **kw)

    def stat(path: Any, *a: Any, **kw: Any) -> os.stat_result:  # a look before an open: is_file(), exists()
        check(path)
        return real_stat(path, *a, **kw)

    def lstat(path: Any, *a: Any, **kw: Any) -> os.stat_result:
        check(path)
        return real_lstat(path, *a, **kw)

    def b_open(file: Any, *a: Any, **kw: Any) -> Any:
        check(file)
        return real_open(file, *a, **kw)

    def popen(args: Any, *a: Any, **kw: Any) -> Any:
        argv = [args] if isinstance(args, str | bytes) else list(args)
        if argv and os.path.basename(_name(argv[0])) in ENGINES:
            seen.append(f"engine: {_name(argv[0])}")
        return real_popen(args, *a, **kw)

    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(builtins, "open", b_open)
    monkeypatch.setattr(io, "open", b_open)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setenv("DOCKER_HOST", "unix:///nonexistent/h139-no-engine.sock")  # a real CLI reaches no engine
    monkeypatch.setenv("CONTAINER_HOST", "unix:///nonexistent/h139-no-engine.sock")
    return seen
