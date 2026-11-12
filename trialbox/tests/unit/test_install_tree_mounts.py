"""OPS-004 (D-570): after an install from a bundle the shipped files under deploy/ are links into ../current
(tools/host_tree.py). A container that gets deploy/ alone sees them dangle: the box rehearsal stopped at
"No such file or directory: '/d/measured/serving_config.rtxpro6000.json'". Every container install.sh starts on
deploy/ also gets the release tree where those links point."""

from __future__ import annotations

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
    runs = [i for i, ln in enumerate(lines) if '"$ROOT/deploy:' in ln and "tree_args() {" not in ln]
    assert len(runs) >= 9
    for i in runs:
        assert "docker run" in lines[i], f"install.sh:{i + 1}: the mount is not on the command's first line"
        at = "/app/deploy" in lines[i]
        want = '${TREE_APP[@]+"${TREE_APP[@]}"}' if at else '${TREE_D[@]+"${TREE_D[@]}"}'
        assert want in lines[i], f"install.sh:{i + 1}: {lines[i].strip()[:90]}"
        assert lines[i - 1].strip() == "tree_args", f"install.sh:{i + 1}: tree_args is not the line before"


def test_the_host_checks_doctor_gets_the_tree_too(tmp_path: Path) -> None:
    """The review of #363: install.sh ends with check_host.sh, whose doctor container had the same dangling
    links (deploy/egress.py, the compose files)."""
    text = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    start = text.index('  TREE_MOUNT=""')
    block = text[start : text.index("\n", text.index("[ -d", start)) + 1]
    release = tmp_path / "releases" / "r1"
    release.mkdir(parents=True)
    (tmp_path / "current").symlink_to("releases/r1")
    script = f'set -eu\nROOT_DIR="{tmp_path}"\n{block}\nprintf "%s\\n" "$TREE_MOUNT"\n'
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=True).stdout.strip()
    assert out == f"{release}:/app/current:ro"
    script = f'set -eu\nROOT_DIR="{tmp_path}/none"\n{block}\nprintf "[%s]\\n" "$TREE_MOUNT"\n'
    assert subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False).stdout.strip() == "[]"
    run = text[text.index("if docker run --rm --network none --env-file") :]
    assert '${TREE_MOUNT:+-v "$TREE_MOUNT"}' in run[: run.index("python -m tools.trialbox doctor")]
