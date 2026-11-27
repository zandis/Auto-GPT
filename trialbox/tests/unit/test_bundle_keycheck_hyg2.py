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


def _stick(folder: Path, key: Path, body: bytes = b'{"bundle_id": "2026.11-1"}\n') -> dict[str, Path]:
    """A small stick signed as make_bundle.sh signs it: the manifest inside the bundle, the bootstrap, the sidecar."""
    folder.mkdir()
    bundle = folder / "out.tar"
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
        assert (_dist(kit) / name).is_file(), name
    assert not list(kit["tmp"].glob(".make_bundle-pending.*"))
    stick = {"bundle": _dist(kit) / "out.tar", "bootstrap": _dist(kit) / "trialbox-bootstrap.sh",
             "sums": _dist(kit) / "out.tar.sha256"}  # fmt: skip
    assert _check(_dist(kit) / "vendor_ed25519.pub", stick) == []
    assert (_dist(kit) / "vendor_ed25519.pub").read_bytes() == kit["pub"].read_bytes()
    hand_over = next(line for line in res.stdout.splitlines() if line.startswith("done: hand over"))
    assert "out.tar.sha256.sig" in hand_over


def test_make_bundle_refuses_a_mismatched_public_key_and_leaves_nothing(kit: dict[str, Any]) -> None:
    _, other_pub = keygen(kit["tmp"] / "other")
    res = _built(kit, "--pub", str(other_pub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "the stick's public key does not verify what it carries: refused" in res.stderr
    assert res.stderr.count("bundle_keycheck: ") == 3
    for name in STICK:
        assert not (_dist(kit) / name).exists(), name
    assert not list(kit["tmp"].glob(".make_bundle-pending.*"))


def test_make_bundle_takes_the_matching_public_key_from_pub(kit: dict[str, Any]) -> None:
    res = _built(kit, "--pub", str(kit["pub"]))
    assert res.returncode == 0, res.stdout + res.stderr
    assert (_dist(kit) / "vendor_ed25519.pub").read_bytes() == kit["pub"].read_bytes()


def test_a_missing_pub_file_is_refused_before_anything_is_built(kit: dict[str, Any]) -> None:
    res = _built(kit, "--pub", str(kit["tmp"] / "no-such.pub"))
    assert res.returncode == 2 and "no such public key" in res.stderr
    assert not (_dist(kit) / "out.tar").exists()


# ---------------------------------------------------------------------------------------------- the fix round (#1586)


def _dist(kit: dict[str, Any]) -> Path:
    """The fresh folder the helper's --out names: the release is published into it as one directory rename."""
    return kit["tmp"] / "release"


def _resign_sums(stick: dict[str, Path], key: Path, text: str) -> None:
    stick["sums"].write_text(text, encoding="utf-8")
    sign_file(key, stick["sums"])


def test_the_sidecar_is_read_once_and_parsed_from_the_bytes_that_were_verified(
    tmp_path: Path, keys: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:  # R4
    stick = _stick(tmp_path / "stick", keys["key"])
    reads: list[str] = []
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def read_bytes(self: Path) -> bytes:
        reads.append(self.name)
        return real_bytes(self)

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        reads.append(self.name)
        return real_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    assert _check(keys["pub"], stick) == []
    assert reads.count("out.tar.sha256") == 1, reads


def test_an_unreadable_sidecar_is_named_as_a_failure(tmp_path: Path, keys: dict[str, Path]) -> None:  # R4
    stick = _stick(tmp_path / "stick", keys["key"])
    stick["sums"].unlink()
    assert "out.tar.sha256: not readable (FileNotFoundError)" in _check(keys["pub"], stick)


def test_a_sidecar_that_is_not_text_is_a_line_not_a_traceback(tmp_path: Path, keys: dict[str, Path]) -> None:  # F5
    stick = _stick(tmp_path / "stick", keys["key"])
    stick["sums"].write_bytes(b"\xff\xfe not utf-8\n")
    sign_file(keys["key"], stick["sums"])
    assert "out.tar.sha256: not UTF-8 text" in _check(keys["pub"], stick)


def test_a_key_of_an_unsupported_kind_is_a_line_not_a_traceback(
    tmp_path: Path, keys: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:  # F5
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives import serialization

    def refuse(_data: bytes) -> None:
        raise UnsupportedAlgorithm("no such key kind")

    monkeypatch.setattr(serialization, "load_pem_public_key", refuse)
    found = _check(keys["pub"], _stick(tmp_path / "stick", keys["key"]))
    assert len(found) == 1 and "is not readable as Ed25519" in found[0]


def test_a_bad_line_followed_by_a_good_one_for_the_same_name_is_refused(
    tmp_path: Path, keys: dict[str, Path]
) -> None:  # R5
    stick = _stick(tmp_path / "stick", keys["key"])
    good = stick["sums"].read_text(encoding="utf-8")
    _resign_sums(stick, keys["key"], f"{'0' * 64}  out.tar\n{good}")
    assert "out.tar.sha256 lists out.tar more than once" in _check(keys["pub"], stick)


def test_an_entry_for_a_file_the_stick_does_not_carry_is_refused(tmp_path: Path, keys: dict[str, Path]) -> None:  # R5
    stick = _stick(tmp_path / "stick", keys["key"])
    good = stick["sums"].read_text(encoding="utf-8")
    _resign_sums(stick, keys["key"], f"{good}{'0' * 64}  extra.txt\n")
    assert "out.tar.sha256 lists extra.txt, which is not one of the three it covers" in _check(keys["pub"], stick)


def test_a_line_that_is_not_a_digest_and_a_name_is_refused(tmp_path: Path, keys: dict[str, Path]) -> None:  # R5
    stick = _stick(tmp_path / "stick", keys["key"])
    good = stick["sums"].read_text(encoding="utf-8")
    _resign_sums(stick, keys["key"], f"{good}not a line\n")
    assert "out.tar.sha256: line 4 is not '<sha256>  <name>'" in _check(keys["pub"], stick)


def test_the_files_hashed_are_the_paths_given_not_the_ones_beside_the_sidecar(
    tmp_path: Path, keys: dict[str, Path]
) -> None:  # R5
    mine = _stick(tmp_path / "mine", keys["key"])
    other = _stick(tmp_path / "second", keys["key"], body=b'{"bundle_id": "another"}\n')  # signed, but not mine
    found = kc.problems(keys["pub"], other["bundle"], mine["bootstrap"], mine["sums"])
    assert found == ["out.tar.sha256: out.tar does not match its line"]


def _blob(res: subprocess.CompletedProcess[str]) -> str:
    return res.stdout + res.stderr


def test_only_the_parsed_public_key_goes_on_the_stick(kit: dict[str, Any]) -> None:  # R1
    padded = kit["tmp"] / "padded.pub"
    padded.write_bytes(kit["pub"].read_bytes() + kit["key"].read_bytes())  # the public key, then the private one
    res = _built(kit, "--pub", str(padded))
    assert res.returncode == 0, _blob(res)
    shipped = (_dist(kit) / "vendor_ed25519.pub").read_text(encoding="utf-8")
    assert "PRIVATE" not in shipped and shipped == kit["pub"].read_text(encoding="utf-8")
    assert "PRIVATE" not in "".join(
        p.read_bytes().decode("latin-1") for p in _dist(kit).iterdir() if p.name != "out.tar"
    )


def test_a_private_key_given_as_pub_is_refused_before_anything_is_built(kit: dict[str, Any]) -> None:
    res = _built(kit, "--pub", str(kit["key"]))
    assert res.returncode == 2 and "make_bundle: --pub is not a public key" in res.stderr, _blob(res)
    assert not _dist(kit).exists() and not kit["log"].exists()


def test_pub_is_required_outside_a_rehearsal(kit: dict[str, Any]) -> None:  # F1
    res = _built({**kit, "pub": None})
    assert res.returncode == 2 and "make_bundle: --pub is required outside a --rehearsal" in res.stderr, _blob(res)
    assert not _dist(kit).exists() and not kit["log"].exists()  # refused before any image is touched


def test_a_rehearsal_may_leave_pub_out_and_derives_the_key(kit: dict[str, Any]) -> None:  # F1
    res = _built({**kit, "pub": None}, "--rehearsal")
    assert res.returncode == 0, _blob(res)
    assert (_dist(kit) / "vendor_ed25519.pub").read_bytes() == kit["pub"].read_bytes()


def test_an_out_folder_with_files_in_it_is_refused_and_left_alone(kit: dict[str, Any]) -> None:  # R2
    _dist(kit).mkdir()
    (_dist(kit) / "out.tar").write_bytes(b"the previous release")
    res = _built(kit)
    assert res.returncode == 2 and "make_bundle: --out's folder" in res.stderr, _blob(res)
    assert "must be absent or empty" in res.stderr
    assert [p.name for p in _dist(kit).iterdir()] == ["out.tar"]
    assert (_dist(kit) / "out.tar").read_bytes() == b"the previous release"
    assert not kit["log"].exists()


def test_an_empty_out_folder_is_published_into(kit: dict[str, Any]) -> None:  # R2
    _dist(kit).mkdir()
    res = _built(kit)
    assert res.returncode == 0, _blob(res)
    assert {p.name for p in _dist(kit).iterdir()} == set(STICK) | {"trialbox-bootstrap.sh", "trialbox-bootstrap.sh.sig"}


def _mv_shim(kit: dict[str, Any], fail: bool) -> Path:
    log = kit["tmp"] / "mv.log"
    shim = kit["bin"] / "mv"
    shim.write_text(
        f'#!/bin/sh\necho "$*" >> {log}\n' + ("exit 1\n" if fail else 'exec /bin/mv "$@"\n'), encoding="utf-8"
    )
    shim.chmod(0o755)
    return log


def test_the_release_is_published_by_one_rename_of_the_whole_folder(kit: dict[str, Any]) -> None:  # R2
    log = _mv_shim(kit, fail=False)
    res = _built(kit)
    assert res.returncode == 0, _blob(res)
    calls = log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1 and calls[0].endswith(str(_dist(kit))), calls


def test_a_rename_that_fails_leaves_no_half_set_and_no_pending_folder(kit: dict[str, Any]) -> None:  # R2
    _mv_shim(kit, fail=True)
    res = _built(kit)
    assert res.returncode == 1 and "could not be published into" in res.stderr, _blob(res)
    assert not _dist(kit).exists()
    assert not list(kit["tmp"].glob(".make_bundle-pending.*"))


def test_the_model_pack_rides_in_the_same_folder_and_is_published_with_it(kit: dict[str, Any]) -> None:  # R3
    pack = _dist(kit) / "trialbox-models-x.pack"
    res = _built(kit, "--model-pack-out", str(pack))
    assert res.returncode == 0, _blob(res)
    assert pack.is_file() and (_dist(kit) / "trialbox-models-x.pack.sha256").is_file()
    assert (_dist(kit) / "out.tar").is_file()


def test_a_refused_key_check_writes_no_model_pack(kit: dict[str, Any]) -> None:  # R3
    _, other_pub = keygen(kit["tmp"] / "other")
    res = _built(kit, "--pub", str(other_pub), "--model-pack-out", str(_dist(kit) / "trialbox-models-x.pack"))
    assert res.returncode == 1 and "the stick's public key does not verify what it carries" in res.stderr, _blob(res)
    assert not _dist(kit).exists()  # neither the software pack nor the model pack nor its checksum
    assert not list(kit["tmp"].glob(".make_bundle-pending.*"))


def test_a_model_pack_in_the_out_folder_is_refused_and_its_bytes_are_kept(kit: dict[str, Any]) -> None:  # R3
    _dist(kit).mkdir()
    pack = _dist(kit) / "trialbox-models-x.pack"
    pack.write_bytes(b"the earlier model pack")
    res = _built(kit, "--model-pack-out", str(pack))
    assert res.returncode == 2 and "must be absent or empty" in res.stderr, _blob(res)
    assert pack.read_bytes() == b"the earlier model pack"


def test_a_model_pack_out_not_beside_out_is_refused(kit: dict[str, Any]) -> None:  # R3
    res = _built(kit, "--model-pack-out", str(kit["tmp"] / "elsewhere" / "trialbox-models-x.pack"))
    assert res.returncode == 2 and "make_bundle: --model-pack-out must sit beside --out" in res.stderr, _blob(res)
    assert not _dist(kit).exists() and not (kit["tmp"] / "elsewhere").exists()


def test_the_rehearsal_compares_the_key_it_was_handed_and_does_not_replace_it() -> None:  # R6
    text = (ROOT / "tools/rehearse_box/rehearse.sh").read_text(encoding="utf-8")
    media = text[text.index("media() (") :]
    assert 'cp "$W/vendor/keys/vendor_ed25519.pub" "$MEDIA/linux/"' not in media
    assert 'cmp -s "$W/vendor/keys/vendor_ed25519.pub" "$MEDIA/linux/vendor_ed25519.pub"' in media
