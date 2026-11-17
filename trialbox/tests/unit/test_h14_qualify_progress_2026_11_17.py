"""H-15's F2, fixed in lane H's driver: the qualification's progress line (``prog_qualify`` of
deploy/gcp/box-install-run.sh) counts a gate once when its result is printed ("qualify: <gate>: passed|failed",
tools/qualify.py), never the pair gate's 30-second heartbeat (D-838), and never more than there are gates."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.nodb,
    pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash"),
]

ROOT = Path(__file__).resolve().parents[2]
VM_SCRIPT = (ROOT / "deploy" / "gcp" / "box-install-run.sh").read_text(encoding="utf-8")
QSTEPS = re.search(r'^QSTEPS="([^"]+)"$', VM_SCRIPT, re.M)
FN = VM_SCRIPT[VM_SCRIPT.index("prog_qualify() {") : VM_SCRIPT.index("prog_line() {")]


def _line(tmp_path: Path, log: str) -> str:
    assert QSTEPS is not None
    (tmp_path / "step.log").write_text(log, encoding="utf-8")
    script = f'QSTEPS="{QSTEPS.group(1)}"\nSTEP_LOG="{tmp_path / "step.log"}"\n{FN}\nprog_qualify\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return r.stdout.strip()


GATES7 = "".join(
    f"qualify: {g}: passed\n"
    for g in ("pin", "serving_record", "licence", "schema", "longest_prompt", "log_marker", "canary")
)


def test_the_pair_gates_heartbeat_is_not_counted_as_a_gate(tmp_path: Path) -> None:
    log = GATES7 + "qualify: pair_gate: 12/40 items answered (30 s)\nqualify: pair_gate: 25/40 items answered (60 s)\n"
    assert _line(tmp_path, log) == "qualify gate pair_gate (25/40 items answered) (7 of 15 reported);"


def test_a_failed_gate_with_its_reason_counts_and_the_next_gate_is_named(tmp_path: Path) -> None:
    log = GATES7 + "qualify: pair_gate: 40/40 items answered (90 s)\nqualify: pair_gate: failed (3 of 40 disagree)\n"
    assert _line(tmp_path, log) == "qualify gate determinism (8 of 15 reported);"


def test_the_count_never_passes_the_number_of_gates(tmp_path: Path) -> None:
    assert QSTEPS is not None
    gates = QSTEPS.group(1).split()
    log = "".join(f"qualify: {g}: passed\n" for g in gates) * 2 + "qualify: pin: passed\nqualify: other: passed\n"
    assert _line(tmp_path, log) == f"qualify gate: every gate reported ({len(gates)} of {len(gates)});"
    assert _line(tmp_path, "") == f"qualify gate pin (0 of {len(gates)} reported);"
