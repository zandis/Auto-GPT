"""H-139 (the integrator's 7159714024): an escape check for unit tests that must stay inside their own folders.

On the bench host, which is a real box, the pure stage ran as an ordinary account. One key test reached the host's
real KEK file (``/run/trialbox/kek``), and an update test reached the host's Docker engine and the volumes of a
real stack. In CI neither exists, so both passed there. A test that gives the code its own run folder and a stub
engine calls :func:`watch` and asserts the list stays empty. Any look at or open of the host's run folder, an engine's
data root or socket, and any engine command not given by the test, is then a failure, not a pass that depends on the
host.

OCR 1498-2: a look is ``open``, ``os.open``, ``os.stat``, ``os.lstat``, ``os.listdir``, ``os.scandir``, ``os.access``
or a Unix socket's ``connect``. An engine command is an engine named anywhere in a command, as its program, after
``sudo``, ``env`` or ``bash -c``, or in a shell string, unless it is a stand-in under the test's own temporary folder.
"""

from __future__ import annotations

import builtins
import io
import os
import re
import socket
import subprocess
import tempfile
from typing import Any

import pytest

#: the host's own run folder, the engines' data roots and their sockets: a unit test never looks at these
HOST_PATHS = ("/run/trialbox", "/var/run/docker.sock", "/run/docker.sock", "/run/podman", "/var/run/podman",
              "/var/lib/docker", "/var/lib/containers")  # fmt: skip
ENGINES = ("docker", "podman")
_WORDS = re.compile(r"[^\s;&|()'\"`]+")


def _name(path: Any) -> str:
    try:
        return os.fsdecode(path) if isinstance(path, str | bytes | os.PathLike) else ""
    except (TypeError, ValueError):
        return ""


def _stand_in(word: str) -> bool:
    """A program under the test's own temporary folder (TB_TEST_ROOT, the run's temp folder): the test's stub."""
    roots = [r for r in (os.environ.get("TB_TEST_ROOT"), tempfile.gettempdir()) if r]
    return os.path.isabs(word) and any(os.path.realpath(word).startswith(os.path.realpath(r) + os.sep) for r in roots)


def engines_in(args: Any) -> list[str]:
    """Each engine a command names: its program, after a wrapper (``sudo``, ``env``, ``bash -c``), in a shell string."""
    parts = [args] if isinstance(args, str | bytes | os.PathLike) else list(args)
    found = []
    for part in parts:
        for word in _WORDS.findall(_name(part)):
            if os.path.basename(word) in ENGINES and not _stand_in(word):
                found.append(word)
    return found


def watch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the test reached of the host: each host path it looked at or opened, and each engine command it did not
    stub."""
    seen: list[str] = []
    real = {n: getattr(os, n) for n in ("open", "stat", "lstat", "listdir", "scandir", "access")}
    real_open, real_popen, real_connect = builtins.open, subprocess.Popen, socket.socket.connect

    def check(path: Any) -> None:
        name = _name(path)
        if name.startswith(HOST_PATHS):
            seen.append(name)

    def looked(fn_name: str) -> Any:
        fn = real[fn_name]

        def wrapper(path: Any = ".", *a: Any, **kw: Any) -> Any:
            check(path)
            return fn(path, *a, **kw)

        return wrapper

    def b_open(file: Any, *a: Any, **kw: Any) -> Any:
        check(file)
        return real_open(file, *a, **kw)

    def popen(args: Any, *a: Any, **kw: Any) -> Any:
        seen.extend(f"engine: {w}" for w in engines_in(args))
        return real_popen(args, *a, **kw)

    def connect(sock: socket.socket, address: Any) -> Any:
        if sock.family == socket.AF_UNIX:
            check(address)
        return real_connect(sock, address)

    for fn_name in real:
        monkeypatch.setattr(os, fn_name, looked(fn_name))
    monkeypatch.setattr(builtins, "open", b_open)
    monkeypatch.setattr(io, "open", b_open)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setenv("DOCKER_HOST", "unix:///nonexistent/h139-no-engine.sock")  # a real CLI reaches no engine
    monkeypatch.setenv("CONTAINER_HOST", "unix:///nonexistent/h139-no-engine.sock")
    return seen
