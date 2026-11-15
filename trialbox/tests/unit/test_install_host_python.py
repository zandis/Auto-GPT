"""D-831: install.sh checks the host python3's modules before it loads anything, and a long load says it is alive.

On lane G's box the host python3 had no PyYAML: install.sh died with ModuleNotFoundError about 20 minutes in, at
anchors-compose and pre-start, after the bundle was loaded. The rehearsal host installs python3-yaml, so it never
met it. ``cryptography`` is left out on purpose: the host python3 may lack it (libs/tb_common/kek.py)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb

# the host modules install.sh runs with the host's python3 (python3 -m tools....)
HOST_MODULES = [
    "tools/trialbox/anchors.py",
    "tools/trialbox/prestart.py",
    "tools/trialbox/doctor.py",
    "tools/trialbox/svc_secrets.py",
    "tools/trialbox/memcaps.py",
    "tools/trialbox/pgsize.py",
    "tools/trialbox/bootwait.py",
    "tools/trialbox/db_secrets.py",
    "tools/trialbox/backup_schedule.py",
    "tools/trialbox/audit_heads.py",
    "tools/trialbox/selftest.py",
    "tools/images_lock.py",
    "tools/image_pins.py",
    "tools/tiers.py",
]
LOCAL = {"tools", "tb_common", "tb_contracts", "tb_llm", "gateway", "guard", "registry", "channels", "serving_config"}


def _block() -> str:
    start = INSTALL.index("# HOST-PYTHON (D-831)")
    return INSTALL[start : INSTALL.index("# ---- end of HOST-PYTHON", start)]


def _run(tmp: Path, python_body: str | None) -> subprocess.CompletedProcess[str]:
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    if python_body is not None:
        py = bindir / "python3"
        py.write_text("#!/bin/sh\n" + python_body, encoding="utf-8")
        py.chmod(0o755)
    script = 'set -euo pipefail\ndie() { echo "install: $*" >&2; exit 1; }\n' + _block() + "\necho reached-the-load\n"
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}/usr/bin:/bin"}
    if python_body is None:  # no python3 at all: only the shell's own tools
        env["PATH"] = str(bindir)
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env, check=False)


def test_a_host_python_without_yaml_stops_before_the_load_naming_the_package(tmp_path: Path) -> None:
    res = _run(tmp_path, 'case "$2" in *yaml*) exit 1 ;; esac\nexit 0\n')
    assert res.returncode == 1
    assert "python3-yaml" in res.stderr and "nothing was changed" in res.stderr
    assert "reached-the-load" not in res.stdout


def test_a_host_python_with_the_modules_goes_on(tmp_path: Path) -> None:
    res = _run(tmp_path, "exit 0\n")
    assert res.returncode == 0, res.stderr
    assert "reached-the-load" in res.stdout


def test_the_check_comes_before_the_bundle_is_loaded() -> None:
    assert INSTALL.index("# HOST-PYTHON (D-831)") < INSTALL.index('say "bundle: verify and load')


def test_every_top_level_import_of_the_host_modules_is_checked_or_standard() -> None:
    checked = {pair.split(":", 1)[0] for pair in _block().split('HOST_PY_MODULES="', 1)[1].split('"', 1)[0].split()}
    assert "yaml" in checked
    for rel in HOST_MODULES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in tree.body:  # top level only: a lazy import runs where it is needed
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in LOCAL or top == "__future__":
                    continue
                assert top in checked, f"{rel} imports {top} at the top: add it to HOST_PY_MODULES (D-831)"


def test_the_long_load_says_it_is_alive_and_is_not_buffered() -> None:
    load = INSTALL[INSTALL.index('say "bundle: verify and load') : INSTALL.index('docker image inspect "$IMAGE_PY"')]
    assert "--dry-run >/dev/null || die" not in load  # the verify step is no longer silent
    assert "alive " in load and "PYTHONUNBUFFERED=1" in load
    assert "| sed 's/^/    /'" not in load  # sed block-buffers into a pipe or a log; the shell prefixer does not
