"""OCR #1455 (1455-9): the compose copies never reuse the fd that holds the host's box lock.

#1452 takes the host lock (HOST-LOCK, H-106) on fd 6 and holds it to the install's end; the heartbeat's own comment
names fd 6 as that lock. `exec 6< file` on that fd closes the lock's open file, and the lock goes with it, so a second
box's install could start beside this one. Here a lock is held on fd 6 before install.sh's override lines and its
copy lines run; it must still be held after them."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.unit.test_external_pass_h110 import INSTALL

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize("fd", [6, 9], ids=["the host lock (fd 6)", "the install lock (fd 9)"])
def test_the_compose_copies_keep_the_lock_held_on_fd_6(tmp_path: Path, fd: int) -> None:
    root = tmp_path / "box"
    (root / "deploy" / "site").mkdir(parents=True)
    outside = tmp_path / "elsewhere" / "extra.yml"
    outside.parent.mkdir()
    outside.write_text("services: {}\n", encoding="utf-8")
    ovr = tmp_path / "elsewhere" / "override.yml"
    ovr.write_text("services: {}\n", encoding="utf-8")
    lock = tmp_path / "host.lock"
    a = INSTALL.index('NO_OVR="the compose override (not used)"')
    b = INSTALL.index('COMPOSE+=(--profile "$MODE")', a)
    c = INSTALL.index("# OCR 1455-2 (A), the integrator's ruling 7128436810: root's later starts")
    d = INSTALL.index("# the same file set for every later", c)
    script = (
        "set -euo pipefail\nstop_or_warn() { echo \"STOP $*\"; exit 1; }\nis_standins() { return 1; }\n"
        f"ROOT={root}\nCOMPOSE=(docker compose); FILES={outside}; MODE=stub\nTB_COMPOSE_OVERRIDE={ovr}\n"
        f"exec {fd}>>{lock}; flock -n {fd}\n"
        + INSTALL[a:b] + INSTALL[c:d]
        + f'if ( flock -n 3 ) 3>>{lock}; then echo "LOCK DROPPED"; else echo "LOCK HELD"; fi\n'
    )  # fmt: skip
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "LOCK HELD" in r.stdout, (r.stdout, r.stderr)
