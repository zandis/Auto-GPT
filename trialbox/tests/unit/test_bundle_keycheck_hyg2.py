"""The release build's key check (hygiene item 2): the public key that goes on the stick beside the bundle must
verify the manifest's signature, the bootstrap's ``.sig`` and the ``.sha256.sig``, or ``tools/make_bundle.sh`` refuses
the build and leaves nothing on the stick. Every key here is a throwaway pair made in the test's own tmp folder."""

from __future__ import annotations

import base64
import hashlib
import io
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_release_bundle as rb
from tools import bundle_keycheck as kc
from tools.sign_bundle import keygen, sign_file

ROOT = Path(__file__).resolve().parents[2]
STICK = ("out.tar", "out.tar.sha256", "out.tar.sha256.sig", "trialbox-bootstrap.sh", "trialbox-bootstrap.sh.sig",
         "install", "vendor_ed25519.pub")  # fmt: skip


def _sign_raw(key: Path, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private = load_pem_private_key(key.read_bytes(), password=None)
    assert isinstance(private, Ed25519PrivateKey)
    return private.sign(data)


def _stick(folder: Path, key: Path) -> dict[str, Path]:
    """A small stick signed as make_bundle.sh signs it: the manifest inside the bundle, the bootstrap, the sidecar."""
    folder.mkdir()
    bundle = folder / "out.tar"
    body = b'{"bundle_id": "2026.11-1"}\n'
    with tarfile.open(bundle, "w:") as tf:
        for name, data in (("manifest.json", body), ("manifest.json.sig", base64.b64encode(_sign_raw(key, body)))):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    boot = folder / "trialbox-bootstrap.sh"
    boot.write_text("#!/bin/sh\necho bootstrap\n", encoding="utf-8")
    sign_file(key, boot)
    sums = folder / "out.tar.sha256"
    lines = [f"{hashlib.sha256((folder / n).read_bytes()).hexdigest()}  {n}"
             for n in ("out.tar", "trialbox-bootstrap.sh", "trialbox-bootstrap.sh.sig")]  # fmt: skip
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sign_file(key, sums)
    return {"bundle": bundle, "bootstrap": boot, "sums": sums}


def _check(pub: Path, stick: dict[str, Path]) -> list[str]:
    return kc.problems(pub, stick["bundle"], stick["bootstrap"], stick["sums"])


@pytest.fixture
def keys(tmp_path: Path) -> dict[str, Path]:
    key, pub = keygen(tmp_path / "keys")
    other_key, other_pub = keygen(tmp_path / "other")
    return {"key": key, "pub": pub, "other_key": other_key, "other_pub": other_pub}


def test_the_signing_key_s_public_half_verifies_all_three(tmp_path: Path, keys: dict[str, Path]) -> None:
    assert _check(keys["pub"], _stick(tmp_path / "stick", keys["key"])) == []


def test_another_public_key_verifies_none_of_the_three(tmp_path: Path, keys: dict[str, Path]) -> None:
    found = _check(keys["other_pub"], _stick(tmp_path / "stick", keys["key"]))
    assert len(found) == 3, found
    assert any("manifest.json.sig does not verify" in f for f in found)
    assert any("trialbox-bootstrap.sh.sig does not verify" in f for f in found)
    assert any("out.tar.sha256.sig does not verify" in f for f in found)


def test_a_tampered_sha256_is_refused(tmp_path: Path, keys: dict[str, Path]) -> None:
    stick = _stick(tmp_path / "stick", keys["key"])
    text = stick["sums"].read_text(encoding="utf-8")
    stick["sums"].write_text(text.replace(text[:8], "00000000", 1), encoding="utf-8")
    found = _check(keys["pub"], stick)
    assert "out.tar.sha256.sig does not verify out.tar.sha256 with vendor_ed25519.pub" in found
    assert "out.tar.sha256: out.tar does not match its line" in found


def test_a_changed_bootstrap_and_a_missing_sidecar_signature_are_refused(tmp_path: Path, keys: dict[str, Path]) -> None:
    stick = _stick(tmp_path / "stick", keys["key"])
    stick["bootstrap"].write_text("#!/bin/sh\necho changed\n", encoding="utf-8")
    (tmp_path / "stick" / "out.tar.sha256.sig").unlink()
    found = _check(keys["pub"], stick)
    assert "trialbox-bootstrap.sh.sig does not verify trialbox-bootstrap.sh with vendor_ed25519.pub" in found
    assert "out.tar.sha256.sig: not readable (FileNotFoundError)" in found
    assert "out.tar.sha256: trialbox-bootstrap.sh does not match its line" in found


def test_the_command_line_says_which_and_exits_1(tmp_path: Path, keys: dict[str, Path]) -> None:
    stick = _stick(tmp_path / "stick", keys["key"])
    args = ["--bundle", str(stick["bundle"]), "--bootstrap", str(stick["bootstrap"]), "--sums", str(stick["sums"])]
    good = subprocess.run([sys.executable, str(ROOT / "tools/bundle_keycheck.py"), "--pub", str(keys["pub"]), *args],
                          capture_output=True, text=True, check=False)  # fmt: skip
    assert good.returncode == 0, good.stderr
    bad = subprocess.run([sys.executable, str(ROOT / "tools/bundle_keycheck.py"), "--pub", str(keys["other_pub"]),
                          *args], capture_output=True, text=True, check=False)  # fmt: skip
    assert bad.returncode == 1 and bad.stderr.count("bundle_keycheck: ") == 3


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """test_release_bundle.py's kit, as it makes it: a stand-in docker, a throwaway key pair, a synthetic embedder."""
    from tests.unit.test_stub_box_embedder import _embedder, _registry
    from tools.pin_model import weight_manifest

    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(rb.FAKE_DOCKER.replace("PYTHON", sys.executable), encoding="utf-8")
    docker.chmod(0o755)
    priv, pub = keygen(tmp_path / "keys")
    models = tmp_path / "vendor-models"
    reg = _registry(tmp_path, weight_manifest(_embedder(models / "embedder")).sha256)
    monkeypatch.setenv("TB_RELEASE_REGISTRY", str(reg))
    return {"tmp": tmp_path, "bin": bindir, "key": priv, "pub": pub, "log": tmp_path / "docker.log",
            "models": models, "registry": reg}  # fmt: skip


def _built(kit: dict[str, Any], *extra: str) -> subprocess.CompletedProcess[str]:
    gates, sbom = rb._gate_record(kit["tmp"], [*rb.OWN, rb.BACKUP, rb.HAPI, rb.VLLM])
    return rb._make(kit, "--release-seq", "4", "--gates", str(gates), "--sbom-dir", str(sbom), *extra)


def test_make_bundle_signs_the_sidecar_and_checks_the_stick_key(kit: dict[str, Any]) -> None:
    res = _built(kit)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "bundle_keycheck: vendor_ed25519.pub verifies the manifest" in res.stdout
    for name in STICK:
        assert (kit["tmp"] / name).is_file(), name
    assert not list(kit["tmp"].glob(".make_bundle-pending.*"))
    stick = {"bundle": kit["tmp"] / "out.tar", "bootstrap": kit["tmp"] / "trialbox-bootstrap.sh",
             "sums": kit["tmp"] / "out.tar.sha256"}  # fmt: skip
    assert _check(kit["tmp"] / "vendor_ed25519.pub", stick) == []
    assert (kit["tmp"] / "vendor_ed25519.pub").read_bytes() == kit["pub"].read_bytes()
    hand_over = next(line for line in res.stdout.splitlines() if line.startswith("done: hand over"))
    assert "out.tar.sha256.sig" in hand_over


def test_make_bundle_refuses_a_mismatched_public_key_and_leaves_nothing(kit: dict[str, Any]) -> None:
    _, other_pub = keygen(kit["tmp"] / "other")
    res = _built(kit, "--pub", str(other_pub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "the stick's public key does not verify what it carries: refused" in res.stderr
    assert res.stderr.count("bundle_keycheck: ") == 3
    for name in STICK:
        assert not (kit["tmp"] / name).exists(), name
    assert not list(kit["tmp"].glob(".make_bundle-pending.*"))


def test_make_bundle_takes_the_matching_public_key_from_pub(kit: dict[str, Any]) -> None:
    res = _built(kit, "--pub", str(kit["pub"]))
    assert res.returncode == 0, res.stdout + res.stderr
    assert (kit["tmp"] / "vendor_ed25519.pub").read_bytes() == kit["pub"].read_bytes()


def test_a_missing_pub_file_is_refused_before_anything_is_built(kit: dict[str, Any]) -> None:
    res = _built(kit, "--pub", str(kit["tmp"] / "no-such.pub"))
    assert res.returncode == 2 and "no such public key" in res.stderr
    assert not (kit["tmp"] / "out.tar").exists()
