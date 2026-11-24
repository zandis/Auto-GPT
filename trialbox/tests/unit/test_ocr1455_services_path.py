"""OCR #1455 (1455-1, residual): code on python3's path that the bootstrap never compares runs under the signed
installer.

- deploy/box-install.sh runs its preflight as root with $ROOT/services on PYTHONPATH. The host tree holds no services/
  (tools/host_tree.py TOP_DIRS), so a services/ folder of a kept tree is never compared or moved aside, and a
  PYTHONPATH entry comes before the standard library.
- deploy/check_host.sh runs deploy/hardening/host_tier.py by path, so deploy/hardening/ is the first entry of its
  path; kept_diff looks for unsigned modules only under tools/ and libs/."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import host_tree, sign_bundle

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "deploy" / "bootstrap.sh"
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
BOX_PATH = re.search(r'PYTHONPATH="([^"]*)" timeout -k 5', BOX_INSTALL)
HOST_TIER = 'python3 "$ROOT_DIR/deploy/hardening/host_tier.py"'
SIGNED = ('#!/usr/bin/env bash\nROOT="$(cd "$(dirname "$0")/.." && pwd)"; ROOT_DIR="$ROOT"; cd "$ROOT"\n'
          f'PYTHONPATH="{BOX_PATH.group(1) if BOX_PATH else ""}" python3 -m tools.x\n'
          f'{HOST_TIER}\necho "signed installer ran"\n')  # fmt: skip
FILES = {"deploy/install.sh": SIGNED, "deploy/box-install.sh": SIGNED, "deploy/docker-compose.yml": "services: {}\n",
         "deploy/hardening/host_tier.py": "import argparse\n", "tools/__init__.py": "", "tools/x.py": "import json\n",
         "tools/host_tree.py": (ROOT / "tools" / "host_tree.py").read_text(encoding="utf-8")}  # fmt: skip


@pytest.mark.parametrize(("where", "name"), [("services", "json.py"), ("deploy/hardening", "argparse.py")],
                         ids=["services/ on the box installer's path", "deploy/hardening/ of a script run by path"])  # fmt: skip
def test_no_module_on_the_installers_python_path_that_the_release_lacks_ever_runs(
    tmp_path: Path, where: str, name: str
) -> None:
    if shutil.which("openssl") is None:
        pytest.skip("openssl")
    assert BOX_PATH and HOST_TIER in (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    src = tmp_path / "src"
    for f, text in FILES.items():
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        (src / f).write_text(text, encoding="utf-8")
        (src / f).chmod(0o755 if f.endswith(".sh") else 0o644)
    host = tmp_path / "trialbox-host.tar"
    host_tree.pack(src, host, list(FILES))
    (tmp_path / "usb").mkdir()
    bundle = tmp_path / "usb" / "trialbox-1.0.0.tar"
    sign_bundle.build(priv, "1.0.0", [("host", host, "trialbox-host.tar")], bundle, release_seq=3)
    opt = tmp_path / "opt" / "trialbox"
    env = {**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(opt)}
    run = ["bash", str(BOOT), str(bundle), "--pub", str(pub), "--box"]
    first = subprocess.run(run, capture_output=True, text=True, env=env, check=False, timeout=60)
    assert first.returncode == 0 and "signed installer ran" in first.stdout, first.stdout + first.stderr
    marker = tmp_path / "planted-ran"
    (opt / where).mkdir(parents=True, exist_ok=True)
    (opt / where / name).write_text(f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")
    got = subprocess.run(run, capture_output=True, text=True, env=env, check=False, timeout=60)
    assert got.returncode == 0 and "signed installer ran" in got.stdout, got.stdout + got.stderr
    assert not marker.exists(), "planted code ran under the signed installer: " + got.stdout + got.stderr
