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
        {"path": "p.tar", "sha256": "f" * 64, "kind": "refdata"},
    ],
}


def _variants() -> list[dict[str, Any]]:
    out = [copy.deepcopy(GOOD)]
    for key in ("bundle_id", "created_at", "signer", "files"):
        m = copy.deepcopy(GOOD)
        del m[key]
        out.append(m)
    bad_edits: list[tuple[str, Any]] = [
        ("extra", 1),
        ("bundle_id", 3),
        ("description", 5),
        ("files", "x"),
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
        ("path", 7),
        ("extra", "x"),
    ]
    for key, value in file_edits:
        m = copy.deepcopy(GOOD)
        m["files"][0][key] = value
        out.append(m)
    m = copy.deepcopy(GOOD)
    del m["files"][1]["kind"]
    out.append(m)
    m = copy.deepcopy(GOOD)
    m["description"] = None
    out.append(m)
    return out


@pytest.mark.parametrize("manifest", _variants())
def test_stdlib_check_agrees_with_the_schema(manifest: dict[str, Any]) -> None:
    assert bool(vu._stdlib_schema_errors(manifest)) == bool(schema_errors("update_manifest", manifest))


def test_stdlib_check_reads_the_date() -> None:
    assert vu._stdlib_schema_errors({**GOOD, "created_at": "yesterday"}) == ["created_at is not a date-time"]


def test_verify_without_tb_contracts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    priv, pub = keygen(tmp_path / "keys")
    payload = tmp_path / "model.safetensors"
    payload.write_bytes(b"placeholder\n")
    bundle = tmp_path / "b.tar"
    build(priv, "2026.11-1", [("model", payload, "m/model.safetensors")], bundle)
    monkeypatch.setitem(sys.modules, "tb_contracts", None)  # import fails, as on the clean host
    m = vu.verify(bundle, pub, tmp_path / "stage")
    assert m["bundle_id"] == "2026.11-1" and (tmp_path / "stage" / "model" / "m" / "model.safetensors").is_file()
