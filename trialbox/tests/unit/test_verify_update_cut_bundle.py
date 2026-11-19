"""A signed bundle cut short inside a member is refused by the command line: exit 1, one REJECTED line, no traceback,
nothing staged (H10G43-04)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tools.sign_bundle import build, keygen

ROOT = Path(__file__).resolve().parents[2]


def test_cut_bundle_exits_1_with_the_refusal(tmp_path: Path) -> None:
    priv, pub = keygen(tmp_path / "keys")
    payload = tmp_path / "model.bin"
    payload.write_bytes(b"\x01" * 20000)
    whole = tmp_path / "whole.tar"
    build(priv, "2026.11-cut", [("model", payload, "model.bin")], whole)
    data = whole.read_bytes()
    cut = tmp_path / "cut.tar"
    cut.write_bytes(data[: len(data) // 2])
    stage = tmp_path / "stage"
    run = subprocess.run(
        [sys.executable, str(ROOT / "tools/verify_update.py"), str(cut), "--pubkey", str(pub), "--stage", str(stage)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"},
        check=False,
    )
    assert run.returncode == 1, run.stderr
    assert run.stderr.startswith("REJECTED: a damaged or cut-short tar bundle:"), run.stderr
    assert "Traceback" not in run.stderr and run.stdout == ""
    assert not stage.exists()  # nothing staged
