"""OPS-004 (D-570): after an install from a bundle the shipped files under deploy/ are links into ../current
(tools/host_tree.py). A container that gets deploy/ alone sees them dangle: the box rehearsal stopped at
"No such file or directory: '/d/measured/serving_config.rtxpro6000.json'". Every container install.sh starts on
deploy/ also gets the release tree where those links point."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb


def _function() -> str:
    start = INSTALL.index("tree_args() {")
    return INSTALL[start : INSTALL.index("\n}\n", start) + 3]


def _run(root: Path) -> list[str]:
    script = f'set -euo pipefail\nROOT="{root}"\n{_function()}\ntree_args\n' + (
        'printf "%s\\n" ${TREE_D[@]+"${TREE_D[@]}"} -- ${TREE_APP[@]+"${TREE_APP[@]}"}\n'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return r.stdout.splitlines()


def test_a_bundle_install_mounts_the_release_tree_where_the_links_point(tmp_path: Path) -> None:
    release = tmp_path / "releases" / "r 1"  # a space in the path: the arguments stay whole
    (release / "deploy" / "measured").mkdir(parents=True)
    (tmp_path / "current").symlink_to("releases/r 1")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "measured").symlink_to("../current/deploy/measured")
    out = _run(tmp_path)
    assert out == ["-v", f"{release}:/current:ro", "--", "-v", f"{release}:/app/current:ro"]
    # the link deploy/measured -> ../current/deploy/measured, seen from a mount of deploy/ at /d, is /current/...
    assert (tmp_path / "deploy" / "measured").readlink().as_posix() == "../current/deploy/measured"


def test_a_checkout_has_no_release_tree_and_gets_no_mount(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    assert _run(tmp_path) == ["--"]


def test_every_container_the_installer_starts_on_deploy_gets_the_tree() -> None:
    lines = INSTALL.splitlines()
    runs = [i for i, ln in enumerate(lines) if "docker run" in ln and '"$ROOT/deploy:' in ln]
    assert len(runs) >= 7
    for i in runs:
        at = "/app/deploy" in lines[i]
        want = '${TREE_APP[@]+"${TREE_APP[@]}"}' if at else '${TREE_D[@]+"${TREE_D[@]}"}'
        assert want in lines[i], f"install.sh:{i + 1}: {lines[i].strip()[:90]}"
        before = "\n".join(lines[max(0, i - 12) : i])
        assert re.search(r"^\s*tree_args\b", before, re.M) or "tree_args;" in lines[i], f"install.sh:{i + 1}"
