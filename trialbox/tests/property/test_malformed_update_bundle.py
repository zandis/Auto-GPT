"""Card 10G-43 (OT-5): the update bundle verifier on malformed bundles (``tools.verify_update.verify``).

``verify`` returns the manifest (and stages the payloads) or refuses with :class:`verify_update.Rejected` (exit 1,
nothing staged). Inputs: bytes that are no tar; a good signed bundle truncated or with one byte changed; tars of
generated members (names that leave the folder, links, directories, duplicates); and tars whose manifest is
**signed with the trusted test key** but generated (fields missing, of the wrong type, dates that are no dates), so
what is parsed after the signature is tried too. The key is made here for the test, in a temporary folder.
"""

from __future__ import annotations

import atexit
import base64
import copy
import io
import json
import shutil
import tarfile
import tempfile
from functools import cache
from pathlib import Path
from typing import Any

from hypothesis import example, given
from hypothesis import strategies as st

from tests.malformed_kit import SETTINGS, returns_or_refuses
from tools import verify_update as vu
from tools.sign_bundle import build, keygen


@cache
def _kit() -> tuple[Path, Path, bytes, dict[str, Any], dict[str, bytes]]:
    """(private key, public key, a good bundle's bytes, its manifest, its members) made once per run."""
    d = Path(tempfile.mkdtemp(prefix="tb-10g43-"))
    atexit.register(shutil.rmtree, d, True)  # the test key goes with the run
    priv, pub = keygen(d / "keys")
    payload = d / "model.safetensors"
    payload.write_bytes(b"placeholder\n")
    build(priv, "2026.11-1", [("model", payload, "m/model.safetensors")], d / "good.tar")
    data = (d / "good.tar").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}  # type: ignore[union-attr]
    return priv, pub, data, json.loads(members["manifest.json"]), members


def _sign(body: bytes) -> bytes:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(_kit()[0].read_bytes(), password=None)
    return base64.b64encode(key.sign(body)) + b"\n"  # type: ignore[union-attr,call-arg]


def _tar(members: list[tuple[str, str, bytes]]) -> bytes:
    """A tar of (name, kind, bytes); kind is file, dir, symlink or fifo."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tf:
        for name, kind, body in members:
            info = tarfile.TarInfo(name)
            info.type = {"file": tarfile.REGTYPE, "dir": tarfile.DIRTYPE, "symlink": tarfile.SYMTYPE,
                         "fifo": tarfile.FIFOTYPE}[kind]  # fmt: skip
            if kind == "symlink":
                info.linkname = "../../etc/passwd"
            info.size = len(body) if kind == "file" else 0
            tf.addfile(info, io.BytesIO(body) if kind == "file" else None)
    return buf.getvalue()


_JUNK = st.one_of(st.none(), st.booleans(), st.integers(-(2**70), 2**70), st.text(max_size=8),
                  st.sampled_from(["2026-13-45T00:00:00", "", "x", "../x", "9999-12-31T23:59:59+00:00"]),
                  st.lists(st.integers(), max_size=2), st.just({}))  # fmt: skip


@st.composite
def signed_manifests(draw: st.DrawFn) -> bytes:
    """The good bundle with its manifest changed (a field dropped, given junk, files listed wrong) and signed again,
    or replaced by signed bytes that are no JSON object."""
    _, _, _, manifest, members = _kit()
    m = copy.deepcopy(manifest)
    for _ in range(draw(st.integers(1, 3))):
        key = draw(st.sampled_from([*sorted(m), "rotation", "files"]))
        op = draw(st.sampled_from(["drop", "junk", "files"]))
        if op == "drop":
            m.pop(key, None)
        elif op == "junk":
            m[key] = draw(_JUNK)
        else:
            m["files"] = [{"path": draw(st.sampled_from(["m/model.safetensors", "../x", "/abs", "", "a\\b"])),
                           "kind": draw(st.sampled_from(["model", "host", "images", "x"])),
                           "sha256": draw(st.sampled_from(["0" * 64, "x"])), "size": draw(_JUNK)}]  # fmt: skip
    body = draw(st.one_of(st.just(json.dumps(m).encode()),
                          st.sampled_from([b"[]", b"null", b"1", b"{", b"\xff", b"\"x\""])))  # fmt: skip
    rest = [(n, "file", b) for n, b in members.items() if n not in ("manifest.json", "manifest.json.sig")]
    return _tar([("manifest.json", "file", body), ("manifest.json.sig", "file", _sign(body)), *rest])


@st.composite
def damaged(draw: st.DrawFn) -> bytes:
    """The good bundle with one byte changed (a cut one is H10G43-04, its own test below)."""
    data = _kit()[2]
    i = draw(st.integers(0, 10**6)) % len(data)  # not drawn from len(data): it is made once per run
    return data[:i] + bytes([data[i] ^ draw(st.integers(1, 255))]) + data[i + 1 :]


@st.composite
def truncated(draw: st.DrawFn) -> bytes:
    data = _kit()[2]
    return data[: draw(st.integers(0, 10**6)) % len(data)]


_NAMES = st.sampled_from(["manifest.json", "manifest.json.sig", "compat.json", "files/m/model.safetensors", "/abs",
                          "../up", "files/../x", "a\\b", "files/", "./manifest.json", "files//x"])  # fmt: skip
member_tars = st.lists(
    st.tuples(_NAMES, st.sampled_from(["file", "file", "dir", "symlink", "fifo"]), st.binary(max_size=40)), max_size=5
).map(_tar)


def _verify(data: bytes) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as d:
        bundle = Path(d) / "b.tar"
        bundle.write_bytes(data)
        return vu.verify(bundle, _kit()[1], Path(d) / "stage")


def test_the_good_bundle_verifies() -> None:
    """The base the properties change is itself accepted (else every refusal below would be trivially right)."""
    assert _verify(_kit()[2])["bundle_id"] == "2026.11-1"


@SETTINGS
@given(st.one_of(st.binary(max_size=600), damaged(), member_tars))
@example(b"")
@example(_tar([("manifest.json", "file", b"{}")]))
@example(_tar([("files", "symlink", b"")]))
def test_verify_returns_or_rejects_damaged_bundles(data: bytes) -> None:
    returns_or_refuses(lambda: _verify(data), (vu.Rejected,))


@SETTINGS
@given(signed_manifests())
def test_verify_returns_or_rejects_signed_manifests(data: bytes) -> None:
    returns_or_refuses(lambda: _verify(data), (vu.Rejected,))


@SETTINGS
@given(truncated())
@example(_tar([("a", "file", b"x")])[:512])
def test_h10g43_04_a_cut_bundle(data: bytes) -> None:
    returns_or_refuses(lambda: _verify(data), (vu.Rejected,))
