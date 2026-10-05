"""Signed offline updates (SPEC §10.1; Phase 8 DoD "apply_update.sh rejects tampered bundle"): a vendor-signed bundle
verifies and stages; every tampering variant is rejected; the shell entry point refuses a tampered bundle and
changes nothing; vendor rulesets install only when approved and above the compile gate."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.import_ruleset import ImportRefused, install
from criteria_compiler.repo import RulesetRepo

from tools.sign_bundle import build, keygen
from tools.verify_update import Rejected, verify

ROOT = Path(__file__).resolve().parents[2]


def _ruleset_zip(rid: str = "GOUT-COH", edit: dict[str, Any] | None = None) -> bytes:
    import yaml

    buf = io.BytesIO()
    src = ROOT / "rulesets" / rid
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                data = f.read_bytes()
                if edit and f.name == "manifest.yaml":
                    m = yaml.safe_load(data)
                    m.update(edit)
                    data = yaml.safe_dump(m, allow_unicode=True, sort_keys=False).encode()
                z.writestr(f"{rid}/{f.relative_to(src).as_posix()}", data)
    return buf.getvalue()


@pytest.fixture()
def vendor(tmp_path: Path) -> dict[str, Path]:
    priv, pub = keygen(tmp_path / "keys")
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "GOUT-COH-1.0.0.zip").write_bytes(_ruleset_zip())
    (payload / "model.safetensors").write_bytes(os.urandom(4096))
    (payload / "notes.txt").write_text("release notes\n", encoding="utf-8")
    bundle = tmp_path / "update.tar"
    build(
        priv,
        "2026.10-1",
        [
            ("ruleset", payload / "GOUT-COH-1.0.0.zip", "GOUT-COH-1.0.0.zip"),
            ("model", payload / "model.safetensors", "qwen/model.safetensors"),
            ("other", payload / "notes.txt", "notes.txt"),
        ],
        bundle,
        description="test bundle",
    )
    return {"priv": priv, "pub": pub, "bundle": bundle, "payload": payload, "tmp": tmp_path}


def _members(bundle: Path) -> dict[str, bytes]:
    with tarfile.open(bundle) as tf:
        out = {}
        for m in tf.getmembers():
            f = tf.extractfile(m)
            out[m.name] = f.read() if f else b""
        return out


def _write(path: Path, members: dict[str, bytes], extra: list[tarfile.TarInfo] | None = None) -> Path:
    with tarfile.open(path, "w:") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tf.addfile(info)
    return path


def test_valid_bundle_verifies_and_stages(vendor: dict[str, Path]) -> None:
    stage = vendor["tmp"] / "stage"
    m = verify(vendor["bundle"], vendor["pub"], stage)
    assert m["bundle_id"] == "2026.10-1" and len(m["files"]) == 3
    assert (stage / "model" / "qwen" / "model.safetensors").read_bytes() == (
        vendor["payload"] / "model.safetensors"
    ).read_bytes()
    assert (stage / "ruleset" / "GOUT-COH-1.0.0.zip").exists() and (stage / "manifest.json").exists()
    assert not list(stage.rglob("*.part"))


def _tamper(kind: str, v: dict[str, Path]) -> Path:
    mem = _members(v["bundle"])
    out = v["tmp"] / f"tampered-{kind}.tar"
    if kind == "payload":
        mem["files/notes.txt"] = b"release notes, edited\n"
    elif kind == "payload_same_size":
        data = bytearray(mem["files/qwen/model.safetensors"])
        data[100] ^= 0xFF
        mem["files/qwen/model.safetensors"] = bytes(data)
    elif kind == "manifest":
        m = json.loads(mem["manifest.json"])
        m["files"][2]["sha256"] = "0" * 64
        mem["manifest.json"] = json.dumps(m).encode()
    elif kind == "signature":
        mem["manifest.json.sig"] = base64.b64encode(b"\0" * 64) + b"\n"
    elif kind == "other_key":
        other_priv, _ = keygen(v["tmp"] / "other")
        build(other_priv, "x", [("other", v["payload"] / "notes.txt", "notes.txt")], out)
        return out
    elif kind == "extra_file":
        mem["files/evil.sh"] = b"#!/bin/sh\nrm -rf /\n"
    elif kind == "missing_file":
        del mem["files/notes.txt"]
    elif kind == "traversal":
        mem["../../etc/cron.d/x"] = b"* * * * * root sh\n"
    elif kind == "symlink":
        link = tarfile.TarInfo("files/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/shadow"
        return _write(out, mem, [link])
    return _write(out, mem)


@pytest.mark.parametrize(
    "kind",
    [
        "payload",
        "payload_same_size",
        "manifest",
        "signature",
        "other_key",
        "extra_file",
        "missing_file",
        "traversal",
        "symlink",
    ],
)
def test_tampered_bundles_are_rejected(kind: str, vendor: dict[str, Path]) -> None:
    stage = vendor["tmp"] / f"stage-{kind}"
    with pytest.raises(Rejected):
        verify(_tamper(kind, vendor), vendor["pub"], stage)
    assert not stage.exists() or not any(p.is_file() for p in stage.rglob("*"))  # nothing staged


def _apply(bundle: Path, pub: Path, tmp: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}",
        "TB_VENDOR_PUBKEY": str(pub),
        "TB_MODELS_DIR": str(tmp / "models"),
        "TMPDIR": str(tmp),
    }
    return subprocess.run(
        ["sh", str(ROOT / "tools/apply_update.sh"), str(bundle), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_apply_update_script(vendor: dict[str, Path]) -> None:
    ok = _apply(vendor["bundle"], vendor["pub"], vendor["tmp"])
    assert ok.returncode == 0, ok.stderr
    assert "verified:" in ok.stdout and "would apply" in ok.stdout and "qwen/model.safetensors" in ok.stdout
    bad = _apply(_tamper("payload_same_size", vendor), vendor["pub"], vendor["tmp"])
    assert bad.returncode == 1 and "REJECTED" in bad.stderr
    assert not (vendor["tmp"] / "models").exists()
    assert not list(vendor["tmp"].glob("tb-update.*"))  # staging removed


def test_ruleset_install(tmp_path: Path) -> None:
    repo = RulesetRepo(tmp_path / "repo")
    assert install(repo, _ruleset_zip(), "update:test") == "GOUT-COH/v1.0.0"
    assert (tmp_path / "repo" / "GOUT-COH" / "manifest.yaml").exists()
    assert "GOUT-COH/v1.0.0" in repo.tags()
    assert install(repo, _ruleset_zip(), "update:test") == "GOUT-COH/v1.0.0"  # idempotent
    with pytest.raises(ImportRefused, match="different content"):
        install(repo, _ruleset_zip(edit={"title": "changed"}), "update:test")
    with pytest.raises(ImportRefused, match="only approved"):
        install(repo, _ruleset_zip(edit={"status": "draft", "version": "1.0.1"}), "update:test")
    with pytest.raises(ImportRefused, match="below the compile gate"):
        install(repo, _ruleset_zip(edit={"version": "1.0.2", "equivalence": {"overall_pct": 90.0}}), "u")
