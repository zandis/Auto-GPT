"""H-139: whether Node Playwright is installed, checked once per test process.

The console's browser tests ask at import, inside a ``skipif``. When that check fails, the importing module is not
kept, so a result kept in it would be lost and the next module would ask again. On a host whose node was slow,
every xdist worker waited 60 s for each module. The result is kept here, in a module that always imports.

A node that does not answer within :data:`TIMEOUT_S` is not "not installed". It is one plain failure, the same each
time the check is asked, and never a skip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

TIMEOUT_S = 60
#: what the check found in this process: True or False, or the failure's text
FOUND: dict[str, bool | str] = {}


def node_playwright(cwd: Path) -> bool:
    """True when ``node -e "require('playwright')"`` succeeds in ``cwd``; False without node or Playwright."""
    if "found" not in FOUND:
        node = shutil.which("node")
        if node is None:
            FOUND["found"] = False
        else:
            try:
                r = subprocess.run([node, "-e", "require('playwright')"], cwd=cwd, capture_output=True,
                                   timeout=TIMEOUT_S, check=False)  # fmt: skip
                FOUND["found"] = r.returncode == 0
            except subprocess.TimeoutExpired:
                FOUND["found"] = (f"node did not answer require('playwright') within {TIMEOUT_S} s: the browser tests "
                                  "cannot run on this host until node answers")  # fmt: skip
    found = FOUND["found"]
    if isinstance(found, str):
        pytest.fail(found, pytrace=False)
    return found
