"""The test stack's object folder is writable by the services and by the host's tests (D-972).

`make up-test` bind-mounts ``deploy/.objects`` into the test stack (``deploy/docker-compose.test.yml``,
``TB_HOST_OBJECTS_DIR``) so the integration tests read and write objects directly (D-121). The services run as uid
10001; the CI runner's tests run as the runner's user. A bucket folder the services made first (``attachments``,
mode 755, owner 10001) refused the host test its job folder: the nightly's compose job failed
``test_compile_and_approve_round_trip`` with ``PermissionError`` on ``deploy/.objects/attachments`` every night.
`make up-test` now makes the folder and every bucket of ``tb_common.objstore.BUCKETS`` before the stack starts, open
to both users. The folder holds the test stack's synthetic objects only; no box uses it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common.objstore import BUCKETS

ROOT = Path(__file__).resolve().parents[2]


def _recipe(target: str) -> str:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", text, re.M)
    assert m, f"no {target} target"
    return m.group(1)


def test_up_test_prepares_every_bucket_before_the_stack_starts() -> None:
    recipe = _recipe("up-test")
    prep, up = recipe.index("objects-dir"), recipe.index("up -d --wait")
    assert prep < up, "the folder must be ready before the services write into it"
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(r"^OBJECTS_BUCKETS := (.+)$", text, re.M)
    assert m and tuple(m.group(1).split()) == BUCKETS, "OBJECTS_BUCKETS is not tb_common.objstore.BUCKETS"


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
def test_the_prepared_folder_is_open_to_another_user(tmp_path: Path) -> None:
    """Run the recipe's preparation for real: every bucket exists and anyone may create a folder in it."""
    out = tmp_path / "objects"
    res = subprocess.run(
        ["make", "-s", "-C", str(ROOT), "objects-dir", f"OBJECTS_DIR={out}"],
        capture_output=True, text=True, check=False, env={**os.environ, "PY": sys.executable},
    )  # fmt: skip
    assert res.returncode == 0, res.stdout + res.stderr
    for bucket in BUCKETS:
        mode = (out / bucket).stat().st_mode & 0o7777
        assert mode & 0o777 == 0o777, f"{bucket}: mode {oct(mode)}, another user cannot write in it"
    assert (out.stat().st_mode & 0o777) == 0o777


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
def test_a_folder_left_by_another_user_is_said_plainly(tmp_path: Path) -> None:
    """A bucket the preparation cannot open (an earlier stack's, not this user's) stops `make up-test` by name."""
    out = tmp_path / "objects"
    (out / "attachments").mkdir(parents=True)
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "chmod").write_text("#!/bin/sh\necho 'chmod: Operation not permitted' >&2\nexit 1\n", encoding="utf-8")
    (fake / "chmod").chmod(0o755)
    res = subprocess.run(
        ["make", "-s", "-C", str(ROOT), "objects-dir", f"OBJECTS_DIR={out}"],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"},
    )  # fmt: skip
    assert res.returncode != 0
    assert "deploy/.objects" in res.stderr or str(out) in res.stderr
