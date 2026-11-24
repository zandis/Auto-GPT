"""H-110 (OCR 1455-2 (A)): while the box runs, the rehearsal's work dir is root's (0755, rehearse.sh host_up), so a
host-side step that runs as the CI user may not make anything directly in it. The red of 04699392 (job 138393178803,
step 30 swapped-stream): the engine probe made its folder at the top of the work dir and got PermissionError. The
probe's folder is in the run folder, which this user made before host_up."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
REHEARSE = (ROOT / "tools" / "rehearse_box" / "rehearse.sh").read_text(encoding="utf-8")


def _function(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?^\}}\n", REHEARSE, re.S | re.M)
    assert m, name
    return m.group(0)


def test_the_engine_probe_makes_its_folder_where_the_ci_user_may(tmp_path: Path) -> None:
    """rehearse.sh's own swapped_stream, with a stand-in for the probe that refuses, as the kernel does for the CI
    user, a folder made directly in the work dir (root's while the box runs)."""
    w = tmp_path / "rehearse-box"
    (w / "run").mkdir(parents=True)  # made by this user in the media step, before host_up
    py = tmp_path / "py"
    py.write_text(
        "#!/bin/sh\n"
        'for a; do t="$a"; done\n'  # the probe's one argument, the folder it makes
        f'[ "$(dirname "$t")" != "{w}" ] || {{ echo "PermissionError: {w} is root\'s" >&2; exit 1; }}\n'
        'mkdir -p "$t"\n',
        encoding="utf-8",
    )
    py.chmod(0o755)
    script = f"W={w}\nROOT={ROOT}\nPY={py}\n" + _function("swapped_stream") + "swapped_stream\n"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in w.iterdir()) == ["run"]  # nothing made at the top, and the probe's folder removed


def test_host_up_makes_the_work_dir_roots_and_teardown_gives_it_back() -> None:
    """The ownership change the probe's place depends on: host_up chowns the work dir to root 0755 (never wider),
    and teardown gives it back on both of its paths (TB_REHEARSE_KEEP and the full teardown)."""
    up = _function("host_up")
    assert "chown 0:0 '$W' && chmod 0755 '$W'" in up
    down = _function("teardown")
    assert down.count("w_back") == 2
