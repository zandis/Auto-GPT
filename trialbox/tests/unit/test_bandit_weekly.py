"""10G-39, D-1338: the weekly report-only bandit run (tools/bandit_weekly.py, trialbox-bandit-weekly.yml).

Bandit with no filter and --ignore-nosec reads past a planted `# nosec`; the report is SARIF 2.1.0 without code
excerpts; the run exits 0 on findings; the workflow is weekly, pinned, keeps the SARIF 90 days and runs on no train."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import bandit_weekly as BW

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-bandit-weekly.yml"

PLANTED = (
    "import subprocess\n\n\ndef f(cmd: str) -> None:\n    assert cmd\n    subprocess.call(cmd, shell=True)  # nosec\n"
)


def test_the_command_has_no_filter_and_reads_past_nosec() -> None:
    cmd = BW.bandit_command(["a.py"])
    assert "--ignore-nosec" in cmd
    assert not any(re.fullmatch(r"-l+|-i+|--severity-level.*|--confidence-level.*", a) for a in cmd)


def test_a_planted_nosec_is_reported_and_the_run_stays_green(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "planted.py").write_text(PLANTED, encoding="utf-8")
    out = tmp_path / "out"
    assert BW.main(["--root", str(root), "--out", str(out)]) == 0  # report only, whatever is found
    doc = json.loads((out / "bandit.json").read_text(encoding="utf-8"))
    found = {(r["test_id"], r["line_number"]) for r in doc["results"]}
    assert ("B602", 6) in found  # reported although the line is suppressed inline
    assert ("B101", 5) in found  # low severity: no filter
    assert all("code" not in r for r in doc["results"])
    sarif = json.loads((out / "bandit.sarif").read_text(encoding="utf-8"))
    run = sarif["runs"][0]
    assert sarif["version"] == "2.1.0" and run["tool"]["driver"]["name"] == "Bandit"
    hit = next(r for r in run["results"] if r["ruleId"] == "B602")
    assert hit["level"] == "error"
    assert hit["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "planted.py"
    assert hit["locations"][0]["physicalLocation"]["region"]["startLine"] == 6
    assert hit["properties"]["on_inline_suppression"] is True  # a line with an inline suppression
    assert "subprocess.call(cmd" not in (out / "bandit.sarif").read_text(encoding="utf-8")  # no code excerpt
    assert "| HIGH | 1 |" in (out / "summary.md").read_text(encoding="utf-8")


def test_sarif_levels_follow_severity() -> None:
    rows = [
        {"filename": "x.py", "line_number": n, "test_id": t, "test_name": t, "issue_severity": s,
         "issue_confidence": "HIGH", "issue_text": "t", "col_offset": 0}
        for n, (t, s) in enumerate([("B1", "HIGH"), ("B2", "MEDIUM"), ("B3", "LOW")], start=1)
    ]  # fmt: skip
    res = BW.to_sarif(rows, "1.9.4", set())["runs"][0]["results"]
    assert [r["level"] for r in res] == ["error", "warning", "note"]
    assert all(r["properties"]["on_inline_suppression"] is False for r in res)


def test_bandit_failing_is_an_error_not_a_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    def broken(root: Path, files: list[str]) -> dict[str, object]:
        raise BW.BanditError("bandit did not run")

    monkeypatch.setattr(BW, "run_bandit", broken)
    assert BW.main(["--root", str(tmp_path), "--out", str(tmp_path / "out")]) == 2


def _workflow() -> dict[Any, Any]:
    if not WORKFLOW.parent.is_dir():
        pytest.skip("no .github/workflows next to trialbox/ (a bundle, not the repository)")
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_the_workflow_is_weekly_and_runs_on_no_train() -> None:
    doc = _workflow()
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as true
    assert isinstance(on, dict)
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert len(on["schedule"]) == 1 and re.fullmatch(r"\d+ \d+ \* \* \d", on["schedule"][0]["cron"])


def test_the_workflow_reports_only_and_keeps_the_sarif_90_days() -> None:
    doc = _workflow()
    steps = doc["jobs"]["bandit"]["steps"]
    scan = next(s for s in steps if s.get("run") == "make bandit-weekly")
    assert scan["continue-on-error"] is True
    upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["with"]["retention-days"] == 90 and upload["if"] == "always()"
    assert upload["with"]["path"] == "trialbox/build/bandit-weekly"


def test_the_workflow_installs_nothing_unpinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else pytest.skip("no workflow")
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses), uses
    assert not re.search(r"pip install|uv pip|pipx|uv tool|--with\b", text)
    assert "make venv" in text  # bandit from uv.lock, with its hash
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    block = lock.split('name = "bandit"\n', 1)[1].split("[[package]]", 1)[0]
    assert 'version = "1.9.4"' in block and "sha256:" in block
