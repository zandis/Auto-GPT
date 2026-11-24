"""H-110 (a), the integrator's line 7126867935: a box installed from an older release is reinstalled by a newer
release's bootstrap with the newer installer's options. The kept tree's own installer (which answers
`install: unknown option --kek-passphrase-file`, rc 2) must never be the one that runs: the signed release's is."""

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
# release N-1's installer: its real option parser (the fixture names the commit), then a line that says it ran
N1_INSTALL = "#!/usr/bin/env bash\nset -euo pipefail\n" + (
    ROOT / "tests" / "fixtures" / "h110" / "install_n1_options.txt"
).read_text(encoding="utf-8")
# release N's installer: takes the passphrase file (as install.sh does now) and says which release ran it
N_INSTALL = (
    '#!/usr/bin/env bash\nset -euo pipefail\nPF=""\nwhile [ $# -gt 0 ]; do case "$1" in\n'
    '  --kek-passphrase-file) PF="$2"; shift ;;\n  -*) echo "install: unknown option $1" >&2; exit 2 ;;\n'
    "  *) ;;\nesac; shift; done\n"
    '[ -f "$PF" ] || { echo "install: no passphrase file" >&2; exit 2; }\n'
    'cd "$(dirname "$0")/.." && python3 -m tools.x && echo "release N installer ran"\n'
)
HOST_TREE = (ROOT / "tools" / "host_tree.py").read_text(encoding="utf-8")


def _release(tmp: Path, priv: Path, version: str, seq: int, files: dict[str, str]) -> Path:
    src = tmp / f"src-{version}"
    for name, text in files.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(text, encoding="utf-8")
        (src / name).chmod(0o755 if name.endswith(".sh") else 0o644)
    host = tmp / f"trialbox-host-{version}.tar"
    host_tree.pack(src, host, list(files))
    out = tmp / f"usb-{version}"
    out.mkdir()
    bundle = out / f"trialbox-{version}.tar"
    sign_bundle.build(priv, version, [("host", host, "trialbox-host.tar")], bundle, release_seq=seq)
    return bundle


def _boot(bundle: Path, pub: Path, opt: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(opt)}
    return subprocess.run(["bash", str(BOOT), str(bundle), "--pub", str(pub), *args], capture_output=True,
                          text=True, env=env, check=False, timeout=60)  # fmt: skip


def test_a_box_from_the_release_before_is_reinstalled_by_the_new_bootstrap(tmp_path: Path) -> None:
    if shutil.which("openssl") is None:
        pytest.skip("openssl")
    priv, pub = sign_bundle.keygen(tmp_path / "vendor")
    common = {"deploy/docker-compose.yml": "services: {}\n", "tools/__init__.py": "", "tools/host_tree.py": HOST_TREE}
    old = _release(tmp_path, priv, "0.9.0", 2, {**common, "deploy/install.sh": N1_INSTALL,
                                                "deploy/box-install.sh": N1_INSTALL,
                                                "tools/x.py": "X = 0\n", "tools/dropped.py": "D = 1\n"})  # fmt: skip
    new = _release(tmp_path, priv, "1.0.0", 3, {**common, "deploy/install.sh": N_INSTALL,
                                                "deploy/box-install.sh": N_INSTALL, "tools/x.py": "X = 1\n"})  # fmt: skip
    opt = tmp_path / "opt" / "trialbox"
    first = _boot(old, pub, opt)
    assert first.returncode == 0 and "release N-1 installer ran" in first.stdout, first.stdout + first.stderr
    # the old installer refuses the new option, as on the box the integrator's walk found
    refused = subprocess.run(["bash", str(opt / "deploy" / "install.sh"), "--kek-passphrase-file", "/x"],
                             capture_output=True, text=True, check=False, timeout=60)  # fmt: skip
    assert refused.returncode == 2 and "unknown option --kek-passphrase-file" in refused.stderr
    pf = tmp_path / "kek.pass"
    pf.write_text("synthetic passphrase\n", encoding="utf-8")
    pf.chmod(0o600)
    for box in ([], ["--box"]):
        got = _boot(new, pub, opt, *box, "--", "--kek-passphrase-file", str(pf))
        assert got.returncode == 0, got.stdout + got.stderr
        assert "release N installer ran" in got.stdout and "unknown option" not in got.stderr, got.stdout + got.stderr
    assert (opt / "deploy" / "install.sh").read_text(encoding="utf-8") == N_INSTALL
