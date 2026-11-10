"""The update manifest check without jsonschema (D-176): a clean site host verifies the first bundle with python3 and
cryptography only, because the image that has jsonschema is inside that bundle. Found by the box-install rehearsal."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
from tb_contracts import schema_errors

from tools import verify_update as vu
from tools.sign_bundle import build, keygen

GOOD: dict[str, Any] = {
    "bundle_id": "2026.11-1",
    "created_at": "2026-11-09T12:00:00Z",
    "signer": "vendor",
    "description": "release",
    "files": [
        {"path": "a.tar", "sha256": "0" * 64, "kind": "image", "size": 10},
        {"path": "p.tar", "sha256": "f" * 64, "kind": "refdata", "size": 0},
    ],
    "release_seq": 2,
    "min_installed_version": 0,
    "key_id": "ed25519:0123456789abcdef",
    "not_after": "2027-11-09T12:00:00Z",
    "compat_sha256": "a" * 64,
    "release_sha256": "b" * 64,
    "images_lock_sha256": "c" * 64,
    "rotation": {"add_key_id": "ed25519:fedcba9876543210", "add_public_key": "AAAA", "retire_key_id": None},
}

# manifest schema 1.2.0 (D-210): every required field, and the optional ones that the stdlib check also reads
REQUIRED = ("bundle_id", "created_at", "signer", "files", "release_seq", "min_installed_version", "key_id",
            "not_after", "compat_sha256")  # fmt: skip


def _variants() -> list[dict[str, Any]]:
    out = [copy.deepcopy(GOOD)]
    for key in REQUIRED:
        m = copy.deepcopy(GOOD)
        del m[key]
        out.append(m)
    bad_edits: list[tuple[str, Any]] = [
        ("extra", 1),
        ("bundle_id", 3),
        ("description", 5),
        ("files", "x"),
        ("bundle_id", "../up"),
        ("release_seq", 0),
        ("release_seq", True),
        ("release_seq", "2"),
        ("min_installed_version", -1),
        ("key_id", "ed25519:XYZ"),
        ("key_id", "rsa:0123456789abcdef"),
        ("compat_sha256", "A" * 64),
        ("release_sha256", "0" * 63),
        ("images_lock_sha256", 5),
        ("rotation", "x"),
        ("rotation", {"add_key_id": "ed25519:fedcba9876543210"}),
        ("rotation", {"add_key_id": "bad", "add_public_key": "AAAA"}),
        ("rotation", {"add_key_id": "ed25519:fedcba9876543210", "add_public_key": "AAAA", "retire_key_id": "x"}),
        ("rotation", {"add_key_id": "ed25519:fedcba9876543210", "add_public_key": "AAAA", "extra": 1}),
    ]
    for key, value in bad_edits:
        m = copy.deepcopy(GOOD)
        m[key] = value
        out.append(m)
    file_edits: list[tuple[str, Any]] = [
        ("sha256", "ABC"),
        ("sha256", "0" * 63),
        ("kind", "binary"),
        ("size", "10"),
        ("size", True),
        ("size", -1),
        ("path", ""),
        ("path", "x" * 401),
        ("path", 7),
        ("extra", "x"),
    ]
    for key, value in file_edits:
        m = copy.deepcopy(GOOD)
        m["files"][0][key] = value
        out.append(m)
    for key in ("kind", "size"):
        m = copy.deepcopy(GOOD)
        del m["files"][1][key]
        out.append(m)
    for key in ("description", "release_sha256", "images_lock_sha256", "rotation"):
        m = copy.deepcopy(GOOD)
        del m[key]
        out.append(m)
    m = copy.deepcopy(GOOD)
    m["description"] = None
    out.append(m)
    return out


@pytest.mark.parametrize("manifest", _variants())
def test_stdlib_check_agrees_with_the_schema(manifest: dict[str, Any]) -> None:
    assert bool(vu._stdlib_schema_errors(manifest)) == bool(schema_errors("update_manifest", manifest))


def test_stdlib_check_accepts_the_good_manifest() -> None:
    assert vu._stdlib_schema_errors(GOOD) == [] and not schema_errors("update_manifest", GOOD)


def test_stdlib_check_reads_the_date() -> None:
    assert vu._stdlib_schema_errors({**GOOD, "created_at": "yesterday"}) == ["created_at is not a date-time"]
    assert vu._stdlib_schema_errors({**GOOD, "not_after": "soon"}) == ["not_after is not a date-time"]


def test_verify_without_tb_contracts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    priv, pub = keygen(tmp_path / "keys")
    payload = tmp_path / "model.safetensors"
    payload.write_bytes(b"placeholder\n")
    bundle = tmp_path / "b.tar"
    build(priv, "2026.11-1", [("model", payload, "m/model.safetensors")], bundle)
    monkeypatch.setitem(sys.modules, "tb_contracts", None)  # import fails, as on the clean host
    m = vu.verify(bundle, pub, tmp_path / "stage")
    assert m["bundle_id"] == "2026.11-1" and (tmp_path / "stage" / "model" / "m" / "model.safetensors").is_file()
