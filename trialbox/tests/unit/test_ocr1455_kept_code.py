"""OCR #1455: code a kept tree holds outside what the bootstrap compares still runs under the signed installer."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tools import host_tree, sign_bundle

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "deploy" / "bootstrap.sh"
# a signed installer that does what deploy/install.sh does: cd to the tree, then python3 -m tools...
SIGNED = '#!/usr/bin/env bash\ncd "$(dirname "$0")/.." && python3 -m tools.x && echo "signed installer ran"\n'
FILES = {"deploy/install.sh": SIGNED, "deploy/box-install.sh": SIGNED, "deploy/docker-compose.yml": "services: {}\n",
         "tools/__init__.py": "", "tools/x.py": "import json\nX = 1\n",
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
    return {"pub": pub, "bundle": bundle, "opt": tmp_path / "opt" / "trialbox", "tmp": tmp_path}


def _boot(r: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(r["opt"])}
    return subprocess.run(["bash", str(BOOT), str(r["bundle"]), "--pub", str(r["pub"])], capture_output=True,
                          text=True, env=env, check=False, timeout=60)  # fmt: skip


def _plant_package(opt: Path, marker: Path) -> None:
    (opt / "json").mkdir()  # a package at the top named as a standard module: cwd comes first on sys.path
    (opt / "json" / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")


def _plant_cache(opt: Path, marker: Path) -> None:
    # bytecode in tools/__pycache__ (never compared): its header names the signed source's mtime and size, so the
    # host's python3 runs it in place of the signed tools/x.py
    evil = opt.parent / "evil.py"
    evil.write_text(f"open({str(marker)!r}, 'w').close()\nX = 1\n", encoding="utf-8")
    code = (
        "import importlib.util, py_compile, sys, os\n"
        "src, evil = sys.argv[1], sys.argv[2]\n"
        "st = os.stat(src)\n"
        "cache = importlib.util.cache_from_source(src)\n"
        "os.makedirs(os.path.dirname(cache), exist_ok=True)\n"
        "py_compile.compile(evil, cfile=cache, doraise=True)\n"
        "d = bytearray(open(cache, 'rb').read())\n"
        "d[8:12] = int(st.st_mtime).to_bytes(4, 'little')\n"
        "d[12:16] = (st.st_size & 0xFFFFFFFF).to_bytes(4, 'little')\n"
        "open(cache, 'wb').write(bytes(d))\n"
    )
    subprocess.run(["python3", "-c", code, str(opt / "tools" / "x.py"), str(evil)], check=True)  # the host's python3


@pytest.mark.parametrize("plant", [_plant_package, _plant_cache], ids=["a package at the top", "a bytecode cache"])
def test_no_code_a_kept_tree_holds_runs_under_the_signed_installer(
    release: dict[str, Path], plant: Callable[[Path, Path], None]
) -> None:
    assert _boot(release).returncode == 0
    marker = release["tmp"] / "planted-ran"
    plant(release["opt"], marker)
    got = _boot(release)
    assert not marker.exists(), "planted code ran as the installer: " + got.stdout + got.stderr


def _plant_linked_cache(opt: Path, marker: Path) -> None:
    # the cache folder is a link to a folder outside the tree that holds the planted bytecode
    out = opt.parent / "elsewhere" / "tools"
    out.mkdir(parents=True)
    (out / "x.py").write_bytes((opt / "tools" / "x.py").read_bytes())
    os.utime(
        out / "x.py", ns=(os.stat(opt / "tools" / "x.py").st_atime_ns, os.stat(opt / "tools" / "x.py").st_mtime_ns)
    )
    _plant_cache(out.parent, marker)
    shutil.rmtree(opt / "tools" / "__pycache__", ignore_errors=True)
    (opt / "tools" / "__pycache__").symlink_to(out / "__pycache__", target_is_directory=True)


def test_a_cache_folder_that_is_a_link_out_of_the_tree_never_runs(release: dict[str, Path]) -> None:
    assert _boot(release).returncode == 0
    marker = release["tmp"] / "planted-ran"
    _plant_linked_cache(release["opt"], marker)
    got = _boot(release)
    assert not marker.exists(), "planted code ran as the installer: " + got.stdout + got.stderr


@pytest.mark.parametrize("how", ["group-writable", "other-writable", "a link out of the tree"])
def test_a_signed_file_another_user_could_change_is_never_what_runs(release: dict[str, Path], how: str) -> None:
    """OCR 1455-1, part 3: the bytes checked are the bytes used. A signed file of the kept tree that is not root's
    alone, or a link to the same bytes outside the tree, is never kept: the release is brought in over it."""
    assert _boot(release).returncode == 0
    x = release["opt"] / "tools" / "x.py"
    if how == "a link out of the tree":
        out = release["tmp"] / "outside-x.py"
        out.write_bytes(x.read_bytes())
        x.unlink()
        x.symlink_to(out)
    else:
        x.chmod(0o664 if how == "group-writable" else 0o646)
    got = _boot(release)
    assert got.returncode == 0, got.stdout + got.stderr
    # LR-18: the release is staged and its installer, whose code is the staged tree's, runs; the kept file is
    # not what runs (it is the box's until the update step switches)
    staged = release["opt"] / "releases" / "1.0.0"
    assert "staged: the signed release" in got.stdout and f"running: {staged}/deploy/install.sh" in got.stdout
    assert "signed installer ran" in got.stdout, got.stdout
    used = staged / "tools" / "x.py"
    assert not used.is_symlink() and not used.stat().st_mode & 0o022
