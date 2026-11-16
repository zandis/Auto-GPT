"""D-833: install.sh run again with the bundle that is installed continues from where it stopped.

After the first load writes installed.json, a re-run died at the verify with "release_seq 1 is not above the
installed 1", although install.sh says "Re-running is safe" and advises a re-run after several stops. The very bundle
that is installed (same release_seq, same manifest sha256) is a repeat: the verifier passes it, and main_apply
answers "already installed; nothing to do". Another bundle under the same release_seq, an older one, or a key rotation
bundle is refused as before. The no-op test of main_apply never went through apply_update.sh --dry-run; this one
does."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import update_status as us
from tools.sign_bundle import build, keygen, rotation_for
from tools.verify_update import Rejected, verify

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


@pytest.fixture()
def v(tmp_path: Path) -> dict[str, Any]:
    priv, pub = keygen(tmp_path / "k1")
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "notes.txt").write_text("release notes\n", encoding="utf-8")
    return {"priv": priv, "pub": pub, "tmp": tmp_path, "payload": payload, "updates": tmp_path / "updates"}


def _bundle(v: dict[str, Any], bid: str = "B1", **kw: Any) -> Path:
    out: Path = v["tmp"] / f"{bid}-{len(list(v['tmp'].glob('*.tar')))}.tar"
    build(v["priv"], bid, [("other", v["payload"] / "notes.txt", "notes.txt")], out, **kw)
    return out


def _verify(v: dict[str, Any], bundle: Path, **kw: Any) -> dict[str, Any]:
    u = v["updates"]
    return verify(bundle, v["pub"], None, trust_file=u / "trust.json", installed_file=u / "installed.json", **kw)


def _installed_as(v: dict[str, Any], bundle: Path) -> dict[str, Any]:
    """installed.json as the first load writes it for ``bundle`` (Updater._record: release_seq, manifest_sha256)."""
    m = _verify(v, bundle)
    us.write_atomic(v["updates"] / us.INSTALLED, {"format": us.INSTALLED_FORMAT, "release_seq": m["release_seq"],
                    "bundle_id": m["bundle_id"], "manifest_sha256": m["manifest_sha256"], "state": {}})  # fmt: skip
    return m


def test_the_installed_bundle_again_is_a_repeat_not_a_downgrade(v: dict[str, Any]) -> None:
    b = _bundle(v, release_seq=1)
    first = _installed_as(v, b)
    again = _verify(v, b)
    assert again["repeat"] is True and again["downgrade"] is None
    assert again["manifest_sha256"] == first["manifest_sha256"]


def test_another_bundle_under_the_same_or_an_older_seq_is_still_refused(v: dict[str, Any]) -> None:
    _installed_as(v, _bundle(v, release_seq=2))
    with pytest.raises(Rejected, match="not above the installed 2"):
        _verify(v, _bundle(v, "OTHER", release_seq=2))  # same number, another manifest: not the installed bundle
    with pytest.raises(Rejected, match="not above the installed 2"):
        _verify(v, _bundle(v, "OLDER", release_seq=1))


def test_a_key_rotation_bundle_is_never_a_repeat(v: dict[str, Any]) -> None:
    _p2, pub2 = keygen(v["tmp"] / "k2")
    rot = _bundle(v, "ROT", release_seq=1, rotation=rotation_for(pub2))
    m = _installed_as(v, rot)
    us.write_atomic(v["updates"] / us.TRUST, m["trust_after"])  # what a completed apply writes
    with pytest.raises(Rejected):
        _verify(v, rot)


def test_apply_update_dry_run_passes_the_installed_bundle_again(v: dict[str, Any], tmp_path: Path) -> None:
    """Through the script install.sh runs first (`apply_update.sh BUNDLE --dry-run`), on a root of its own."""
    root = tmp_path / "root"
    (root / "deploy" / "updates").mkdir(parents=True)
    (root / "deploy" / "keys").mkdir()
    for name in ("tools", "libs"):
        (root / name).symlink_to(ROOT / name)
    pub = root / "deploy" / "keys" / "vendor_ed25519.pub"
    pub.write_bytes(Path(v["pub"]).read_bytes())
    b = _bundle(v, release_seq=1)
    v["updates"] = root / "deploy" / "updates"
    _installed_as(v, b)
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}",
           "TB_VENDOR_PUBKEY": str(pub), "TMPDIR": str(tmp_path)}  # fmt: skip
    run = subprocess.run(["sh", str(root / "tools" / "apply_update.sh"), str(b), "--dry-run"],
                         capture_output=True, text=True, env=env, check=False)  # fmt: skip
    assert run.returncode == 0, run.stderr
    assert "verified:" in run.stdout and '"repeat": true' in run.stdout
    other = _bundle(v, "OTHER", release_seq=1)
    refused = subprocess.run(["sh", str(root / "tools" / "apply_update.sh"), str(other), "--dry-run"],
                             capture_output=True, text=True, env=env, check=False)  # fmt: skip
    assert refused.returncode == 1 and "not above the installed 1" in refused.stderr
    assert json.loads((v["updates"] / us.INSTALLED).read_text())["release_seq"] == 1  # read only
