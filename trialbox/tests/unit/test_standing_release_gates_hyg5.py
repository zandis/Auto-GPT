"""Release hygiene item 5: the standing release gates over the tree, report-only until a dated switch.

Five scans in the release build: the code-pattern scanner with its rule set at a pinned commit, two secret scanners
(no verification), the platform-manifest scanner on ``deploy/platform`` and the Dockerfile linter on every Dockerfile.
Checked here with a fake runner and small fixtures, no Docker, no scanner and no network: each tool is an image by
version and digest, run with no network and the tree read-only; no tool honours an inline ignore or an ignore file,
and none is in the tree; the command is report-only until the date and ``--fail-at any`` fails on any finding or any
tool that did not run; the workflow runs it report-only with that date written beside it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.supply_chain import __main__ as sc_main
from tools.supply_chain import standing_gates as sg

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-images.yml"

FIXTURES = {
    "code-patterns": json.dumps(
        {
            "results": [
                {"check_id": "python.lang.security.a.subprocess-shell-true"},
                {"check_id": "python.lang.security.b.use-defused-xml"},
                {"check_id": "python.lang.security.b.use-defused-xml"},
            ]
        }
    ),  # fmt: skip
    "secrets-a": json.dumps([{"RuleID": "generic-api-key"}]),
    "secrets-b": json.dumps({"DetectorName": "PrivateKey"}) + "\n" + json.dumps({"level": "info", "msg": "done"}),
    "platform": json.dumps({"check_type": "kubernetes", "results": {"failed_checks": [{"check_id": "CKV_K8S_21"}]}}),
    "dockerfiles": json.dumps([{"code": "DL3008"}, {"code": "DL3008"}]),
}


def _tool_of(argv: list[str]) -> str:
    return next(t for t, image in sg.IMAGES.items() if image in argv)


class _Runner:
    def __init__(self, out: dict[str, str]) -> None:
        self.out = out
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        tool = _tool_of(argv)
        return subprocess.CompletedProcess(argv, 0 if tool in self.out else 1, self.out.get(tool, "boom"), "")


def test_each_tool_is_an_image_by_version_and_digest_with_no_network_and_the_tree_read_only(tmp_path: Path) -> None:
    cmds = sg.commands(tmp_path / "src", tmp_path / "rules")
    assert set(cmds) == set(sg.TOOLS) == set(sg.IMAGES)
    for tool, argv in cmds.items():
        image = sg.IMAGES[tool]
        assert re.fullmatch(r"[a-z0-9./-]+:v?\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", image), image
        assert argv[:4] == ["docker", "run", "--rm", "--network"] and argv[4] == "none"
        assert f"{tmp_path / 'src'}:/src:ro" in argv and image in argv
    code = cmds["code-patterns"]
    assert {"--disable-nosem", "--metrics=off", "--disable-version-check"} <= set(code)
    assert code[code.index("--severity") + 1] == "ERROR"
    assert [code[i + 1] for i, a in enumerate(code) if a == "--config"] == [f"/rules/{d}" for d in sg.RULE_DIRS]
    assert "--ignore-gitleaks-allow" in cmds["secrets-a"] and "--no-verification" in cmds["secrets-b"]
    assert "--disable-ignore-pragma" in cmds["dockerfiles"]
    assert [a for a in cmds["dockerfiles"] if a.startswith("/src/")] == [f"/src/trialbox/{f}" for f in sg.DOCKERFILES]
    for argv in cmds.values():  # no ignore file, baseline or configuration handed to any tool
        assert not any(re.search(r"ignore|baseline|allow|config-file|--skip-check|--exclude", a) for a in argv
                       if a not in ("--ignore-gitleaks-allow", "--disable-ignore-pragma")), argv  # fmt: skip


def test_every_dockerfile_of_the_tree_is_linted() -> None:
    found = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*Dockerfile") if not {".venv", ".cache"} & set(p.parts)}
    assert found == set(sg.DOCKERFILES)


def test_no_ignore_file_is_in_the_tree_and_one_planted_is_found(tmp_path: Path) -> None:
    assert sg.ignore_files(ROOT.parent) == []
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / ".gitleaksignore").write_text("x\n", encoding="utf-8")
    assert sg.ignore_files(tmp_path) == ["a/.gitleaksignore"]


def test_counts_by_rule_of_each_tool() -> None:
    assert sg.count("code-patterns", FIXTURES["code-patterns"]) == (3, {"subprocess-shell-true": 1,
                                                                         "use-defused-xml": 2})  # fmt: skip
    assert sg.count("secrets-a", FIXTURES["secrets-a"]) == (1, {"generic-api-key": 1})
    assert sg.count("secrets-b", FIXTURES["secrets-b"]) == (1, {"PrivateKey": 1})
    assert sg.count("platform", FIXTURES["platform"]) == (1, {"CKV_K8S_21": 1})
    assert sg.count("dockerfiles", FIXTURES["dockerfiles"]) == (2, {"DL3008": 2})
    with pytest.raises(ValueError):
        sg.count("platform", "not json")


def test_report_only_until_the_date_and_fail_at_any_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(sg, "pinned", lambda d, run=None: d)
    clean = {t: (json.dumps({"results": []}) if t == "code-patterns" else "[]") for t in sg.TOOLS}
    clean["secrets-b"], clean["platform"] = "", json.dumps({"results": {"failed_checks": []}})
    base = ["standing-gates", "--src", str(src), "--rules", str(tmp_path / "r"), "--no-fetch", "--out"]
    for out, fail_at, rc in ((clean, "any", 0), (FIXTURES, "none", 0), (FIXTURES, "any", 1)):
        monkeypatch.setattr(sg.subprocess, "run", _Runner(dict(out)))
        assert sc_main.main([*base, str(tmp_path / f"o-{rc}-{fail_at}"), "--fail-at", fail_at]) == rc
    record = json.loads((tmp_path / "o-1-any" / "index.json").read_text(encoding="utf-8"))
    assert {t["tool"]: t["findings"] for t in record["tools"]} == {
        "code-patterns": 3, "secrets-a": 1, "secrets-b": 1, "platform": 1, "dockerfiles": 2}  # fmt: skip
    assert record["date"] == "by ruling" and record["gating_from"] == sg.GATING_FROM.isoformat()
    broken = dict(FIXTURES)
    del broken["platform"]
    rec = sg.scan(src, tmp_path / "r", tmp_path / "o-broken", run=_Runner(broken))
    assert "platform: not run: exit 1, no report" in sg.failures(rec)
    summary = (tmp_path / "o-broken" / "summary.md").read_text(encoding="utf-8")
    assert "date: by ruling" in summary and "not run" in summary


def test_the_rule_set_is_refused_at_another_commit(tmp_path: Path) -> None:
    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "0" * 40 + "\n" if "rev-parse" in argv else "", "")

    with pytest.raises(RuntimeError, match=sg.RULES_COMMIT):
        sg.fetch_rules(tmp_path / "rules", run=run)


def test_the_workflow_runs_it_report_only_with_the_date_beside_it() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"- name: Standing release gates \(report-only\)\n(.*?)(?=\n      - name:)", text, re.S)
    assert m, "no standing release gates step"
    step = m.group(1)
    assert "continue-on-error: true" in step and "make standing-gates" in step and "--fail-at" not in step
    head = text[: m.start()].rsplit("\n\n", 1)[-1]
    assert f"REPORT-ONLY until {sg.GATING_FROM.isoformat()}" in head and "date: by ruling" in head
    assert "trialbox/build/standing-gates" in text
