"""H-139: whether Node Playwright is installed, checked once per test session, the xdist workers included.

The console's browser tests ask at import, inside a ``skipif``. On a host whose node was slow, every module asked
again in every xdist worker, and each one waited 60 s (the bench host: 112 workers). Now the first worker to ask runs
the check under a lock. It writes the answer to a file of this run (named by xdist's run id, under the test root), and
the other workers read it. The answer is also kept in this module for the rest of the process. This module always
imports, so the answer outlives an importing module whose import fails.

* node not found: False, so each browser test is skipped with its own reason, as before.
* node found, Playwright missing: False, as before.
* node found but no answer within :data:`TIMEOUT_S`: one plain failure naming node and the timeout, the same each
  time it is asked. Never a skip.

A run file is read only when it is this user's own and no one else may write it. Any other file is not trusted, and
the check runs again.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

TIMEOUT_S = 60
#: what the check found in this process: True or False, or the failure's text
FOUND: dict[str, bool | str] = {}


def _probe(cwd: Path) -> bool | str:
    node = shutil.which("node")
    if node is None:
        return False
    try:
        r = subprocess.run([node, "-e", "require('playwright')"], cwd=cwd, capture_output=True, timeout=TIMEOUT_S,
                           check=False)  # fmt: skip
    except subprocess.TimeoutExpired:
        return (f"node did not answer require('playwright') within {TIMEOUT_S} s ({node}): the browser tests cannot "
                "run on this host until node answers")  # fmt: skip
    return r.returncode == 0


def run_file() -> Path | None:
    """This run's shared answer, when xdist runs the session (its run id), under the test root; else None."""
    run = os.environ.get("PYTEST_XDIST_TESTRUNUID", "")
    if not re.fullmatch(r"[0-9a-f]{8,64}", run):
        return None
    root = os.environ.get("TB_TEST_ROOT") or tempfile.gettempdir()
    return Path(root) / f"tb-node-check-{run}.json"


def _trusted(f: Path) -> bool:
    try:
        st = os.lstat(f)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and not st.st_mode & 0o022


def shared(probe: Callable[[], bool | str], f: Path | None) -> bool | str:
    """``probe()``'s answer, run once for all the workers that share ``f`` (once per process without one)."""
    if f is None:
        return probe()
    lock = f.with_name(f.name + ".lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if _trusted(f):
            with contextlib.suppress(OSError, ValueError, KeyError):
                got = json.loads(f.read_text(encoding="utf-8"))["found"]
                if isinstance(got, bool | str):
                    return got
        found = probe()
        tmp = f.with_name(f.name + f".{os.getpid()}.tmp")
        with contextlib.suppress(OSError):
            tmp.unlink()
        wfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(wfd, "w", encoding="utf-8") as out:
            json.dump({"found": found}, out)
        os.replace(tmp, f)
        return found
    finally:
        os.close(fd)


def node_playwright(cwd: Path) -> bool:
    """True when ``node -e "require('playwright')"`` succeeds in ``cwd``; False without node or Playwright."""
    if "found" not in FOUND:
        FOUND["found"] = shared(lambda: _probe(cwd), run_file())
    found = FOUND["found"]
    if isinstance(found, str):
        pytest.fail(found, pytrace=False)
    return found
