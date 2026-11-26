"""The integrator's review of #1455 at 57bc0542 (7186452446): H-1, H-2 (the bootstrap's kept-code check), R2 (a
re-stage never sets aside the release the box runs) and R3 (a compose file's path as written, links included)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import host_tree, sign_bundle

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "deploy" / "bootstrap.sh"
SIGNED = '#!/usr/bin/env bash\ncd "$(dirname "$0")/.." && python3 -m tools.x && echo "signed installer ran"\n'
FILES = {"deploy/install.sh": SIGNED, "deploy/box-install.sh": SIGNED, "deploy/docker-compose.yml": "services: {}\n",
         "deploy/hardening/check.py": "print('signed check')\n",
         "tools/__init__.py": "", "tools/x.py": "X = 1\n",
         "tools/host_tree.py": (ROOT / "tools" / "host_tree.py").read_text(encoding="utf-8")}  # fmt: skip


@pytest.fixture
def release(tmp_path: Path) -> dict[str, Path]:
    if shutil.which("openssl") is None:
        pytest.skip("openssl")
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    src = tmp_path / "src"
    for name, text in FILES.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(text, encoding="utf-8")
        (src / name).chmod(0o755 if name.endswith(".sh") else 0o644)
    host = tmp_path / "trialbox-host.tar"
    host_tree.pack(src, host, list(FILES))
    (tmp_path / "usb").mkdir()
    bundle = tmp_path / "usb" / "trialbox-1.0.0.tar"
    sign_bundle.build(priv, "1.0.0", [("host", host, "trialbox-host.tar")], bundle, release_seq=3)
    return {"pub": pub, "bundle": bundle, "host": host, "opt": tmp_path / "opt" / "trialbox", "tmp": tmp_path}


def _boot(r: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(r["opt"])}
    return subprocess.run(["bash", str(BOOT), str(r["bundle"]), "--pub", str(r["pub"])], capture_output=True,
                          text=True, env=env, check=False, timeout=60)  # fmt: skip


# ------------------------------------------------------------------------------------------------ H-1
def test_a_bare_bytecode_file_in_the_kept_tree_is_counted(release: dict[str, Path]) -> None:
    """A .pyc outside a cache folder is a module python3 imports with no source: the kept tree that holds one is
    not this release's, and the file is named."""
    assert _boot(release).returncode == 0
    (release["opt"] / "tools" / "evil.pyc").write_bytes(b"\x00" * 16)
    got = _boot(release)
    assert "tools/evil.pyc: not in the release" in got.stdout, got.stdout + got.stderr
    assert "already holds this release" not in got.stdout


# ------------------------------------------------------------------------------------------------ H-2
def test_unsigned_code_beside_a_signed_script_of_the_kept_tree_is_reported_after_the_stage(
    release: dict[str, Path],
) -> None:
    """A changed tree is staged; a module beside a signed script python3 runs by path (deploy/hardening) in the kept
    tree is named on the kept tree's own line (the "tops" check dropped it), and only the staged release runs."""
    assert _boot(release).returncode == 0
    (release["opt"] / "tools" / "x.py").write_text("X = 2\n", encoding="utf-8")  # the kept tree is not the release's
    for i in range(6):  # more than the first line's five
        (release["opt"] / "tools" / f"extra{i}.txt").write_text("x\n", encoding="utf-8")
    (release["opt"] / "deploy" / "hardening" / "json.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    got = _boot(release)
    assert got.returncode == 0 and "signed installer ran" in got.stdout, got.stdout + got.stderr
    nested = [ln for ln in got.stdout.splitlines() if "holds code beside its scripts" in ln]
    assert nested and "deploy/hardening/json.py: not in the release" in nested[0], got.stdout


# ------------------------------------------------------------------------------------------------ R2
def test_a_restage_never_sets_aside_the_release_the_box_runs(release: dict[str, Path]) -> None:
    opt = release["opt"]
    host_tree.install(release["host"], opt, "1.0.0")
    live = opt / "releases" / "1.0.0"
    (live / "tools" / "x.py").write_text("X = 2\n", encoding="utf-8")  # drifted
    with pytest.raises(host_tree.HostTreeError, match="the release the box runs"):
        host_tree.stage(release["host"], opt, "1.0.0")
    assert os.path.realpath(opt / "current") == os.path.realpath(live) and live.is_dir()
    assert not [p for p in (opt / "releases").iterdir() if p.name.startswith(".changed-")]


def test_a_drifted_release_the_box_does_not_run_is_still_staged_again(release: dict[str, Path]) -> None:
    opt = release["opt"]
    host_tree.stage(release["host"], opt, "1.0.0")
    (opt / "releases" / "1.0.0" / "tools" / "x.py").write_text("X = 2\n", encoding="utf-8")
    assert host_tree.stage(release["host"], opt, "1.0.0") is True
    assert (opt / "releases" / "1.0.0" / "tools" / "x.py").read_text(encoding="utf-8") == "X = 1\n"


# ------------------------------------------------------------------------------------------------ R3
def _guard(tmp: Path, compose: Path) -> subprocess.CompletedProcess[str]:
    deploy = tmp / "deploy"
    deploy.mkdir(exist_ok=True)
    (deploy / ".env").write_text(f"TB_ENV=TEST\nCOMPOSE_FILE={compose}\n", encoding="utf-8")
    (deploy / ".env").chmod(0o600)
    return subprocess.run(["sh", str(ROOT / "deploy" / "settings_guard.sh"), str(deploy)], capture_output=True,
                          text=True, check=False, timeout=60, env={"PATH": "/usr/bin:/bin"})  # fmt: skip


def test_a_compose_file_named_through_a_link_others_could_repoint_is_refused(tmp_path: Path) -> None:
    """The file the link resolves to is root's alone, but the link lies in a folder others can write: another user
    could point it elsewhere between this check and the start. The path as written is checked, links included."""
    good = tmp_path / "good"
    good.mkdir()
    (good / "extra.yml").write_text("services: {}\n", encoding="utf-8")
    good.chmod(0o755)
    (good / "extra.yml").chmod(0o644)
    open_dir = tmp_path / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    (open_dir / "extra.yml").symlink_to(good / "extra.yml")
    r = _guard(tmp_path, open_dir / "extra.yml")
    assert r.returncode == 1 and f"{open_dir} can be written by group or others" in r.stderr, r.stderr
    r = _guard(tmp_path, good / "extra.yml")  # the same file named directly
    assert r.returncode == 0 and "compose file" not in r.stderr, r.stderr


def test_a_compose_file_named_through_a_link_in_a_closed_folder_still_starts(tmp_path: Path) -> None:
    """An installed box names its compose file through the release's link (deploy/docker-compose.yml ->
    current/...): a link in folders no one else can write is not refused."""
    good = tmp_path / "good"
    good.mkdir()
    (good / "extra.yml").write_text("services: {}\n", encoding="utf-8")
    links = tmp_path / "links"
    links.mkdir()
    for d in (good, links):
        d.chmod(0o755)
    (links / "extra.yml").symlink_to(good / "extra.yml")
    r = _guard(tmp_path, links / "extra.yml")
    assert r.returncode == 0 and "compose file" not in r.stderr, r.stderr
