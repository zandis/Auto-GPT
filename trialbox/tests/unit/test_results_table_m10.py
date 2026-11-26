"""INT-M10 (min), item b: ``tools/results_table.py`` builds the acceptance results table from the proof files.

One test per refusal: a row with no evidence file, a row whose evidence names another commit (or none), a green whose
evidence has a failure, a green whose evidence passed nothing. And the counts: skips and strict xfails stand beside
each green, so a skipped proof is never read as green. Synthetic proof files only; no clock is read.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import results_table as rt

ROOT = Path(__file__).resolve().parents[2]
HEAD = "1" * 40
OTHER = "2" * 40


def _proof(
    folder: Path, criterion: str, result: str = "green", evidence: str | None = "ev.json", **counts: Any
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    proof: dict[str, Any] = {"schema": rt.PROOF_SCHEMA, "criterion": criterion, "title": f"criterion {criterion}",
                             "result": result}  # fmt: skip
    if evidence is not None:
        proof["evidence"] = f"evidence/{criterion}-{evidence}"
        ev = {"commit": counts.pop("commit", HEAD), "passed": 5, "failed": 0, "skipped": 0, "xfailed": 0,
              "xfail_strict": 0}  # fmt: skip
        ev.update(counts)
        for key in [k for k, v in ev.items() if v is None]:  # None: the evidence leaves that field out
            del ev[key]
        path = folder / proof["evidence"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ev), encoding="utf-8")
    p = folder / f"{criterion}.json"
    p.write_text(json.dumps(proof), encoding="utf-8")
    return p


def _refused(folder: Path) -> list[str]:
    with pytest.raises(rt.Refused) as exc:
        rt.build(folder, HEAD)
    return exc.value.reasons


def test_a_row_with_no_evidence_named_is_refused(tmp_path: Path) -> None:
    _proof(tmp_path, "1a", evidence=None)
    _proof(tmp_path, "1b")
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and reasons[0].startswith("1a: ") and "no evidence" in reasons[0], reasons


def test_a_row_whose_evidence_file_is_missing_is_refused(tmp_path: Path) -> None:
    _proof(tmp_path, "1a")
    (tmp_path / "evidence" / "1a-ev.json").unlink()
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and reasons[0].startswith("1a: ") and "no evidence file" in reasons[0], reasons


def test_a_row_whose_evidence_names_another_commit_is_refused(tmp_path: Path) -> None:
    _proof(tmp_path, "1a", commit=OTHER)
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and OTHER in reasons[0] and HEAD in reasons[0], reasons


def test_a_row_whose_evidence_names_no_commit_is_refused(tmp_path: Path) -> None:
    _proof(tmp_path, "1a", commit=None)
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and "names no commit" in reasons[0], reasons


def test_a_green_whose_evidence_has_a_failure_is_refused(tmp_path: Path) -> None:
    _proof(tmp_path, "1a", failed=1)
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and "1 failed" in reasons[0], reasons


def test_a_green_whose_every_test_skipped_is_refused(tmp_path: Path) -> None:
    _proof(tmp_path, "1a", passed=0, skipped=7)
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and "passed nothing" in reasons[0], reasons


def test_skips_and_strict_xfails_stand_beside_each_green(tmp_path: Path) -> None:
    _proof(tmp_path, "1a", passed=40, skipped=3, xfail_strict=2)
    _proof(tmp_path, "1b", passed=12)
    _proof(tmp_path, "2e", result="red", passed=1, failed=2)
    table = rt.render(rt.build(tmp_path, HEAD), HEAD)
    rows = {ln.split("|")[1].strip(): ln for ln in table.splitlines() if ln.startswith("| ") and "---" not in ln}
    assert "green, 3 skipped, 2 strict xfail" in rows["1a"], rows["1a"]
    assert "| 3 | 2 |" in rows["1a"], rows["1a"]
    assert "green |" in rows["1b"] and "skipped" not in rows["1b"].split("|")[3], rows["1b"]
    assert "red" in rows["2e"], rows["2e"]
    assert HEAD in table


def test_the_command_refuses_with_exit_2_and_writes_no_table(tmp_path: Path) -> None:
    proofs = tmp_path / "proofs"
    _proof(proofs, "1a", commit=OTHER)
    out = tmp_path / "table.md"
    log = tmp_path / "run.log"
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, "-m", "tools.results_table", "--proofs", str(proofs), "--commit", HEAD, "--out", str(out)],
            cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False, timeout=60,
        )  # fmt: skip
    assert proc.returncode == 2, log.read_text(encoding="utf-8")
    assert not out.exists()
    assert "1a: " in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("missing", ["failed", "skipped"])
def test_a_row_whose_evidence_leaves_out_a_count_is_refused(tmp_path: Path, missing: str) -> None:
    gone: dict[str, Any] = {missing: None}  # None: the evidence leaves the count out
    _proof(tmp_path, "1a", **gone)
    reasons = _refused(tmp_path)
    assert len(reasons) == 1 and reasons[0].startswith("1a: ") and repr(missing) in reasons[0], reasons


def test_a_title_with_a_pipe_and_a_line_break_stays_in_its_cell(tmp_path: Path) -> None:
    proof = _proof(tmp_path, "1a")
    data = json.loads(proof.read_text(encoding="utf-8"))
    data["title"] = "install | update\nthen restore"
    proof.write_text(json.dumps(data), encoding="utf-8")
    table = rt.render(rt.build(tmp_path, HEAD), HEAD)
    row = next(ln for ln in table.splitlines() if ln.startswith("| 1a "))
    cells = re.split(r"(?<!\\)\|", row)[1:-1]  # a GFM table splits on every pipe not escaped
    assert len(cells) == 8, row
    assert cells[1].strip() == "install \\| update then restore", row
