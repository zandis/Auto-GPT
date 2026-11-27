"""Release hygiene item 5: the standing release gates over the tree, measured against a baseline that only goes down.

Five scans in the release build: the code-pattern scanner with its rule set at a pinned commit, two secret scanners
(no verification), the platform-manifest scanner on ``deploy/platform`` and the Dockerfile linter on every Dockerfile.
The integrator's ruling (7213778687): a count above the baseline fails from the first day; every finding of the secret
scanners fails now, of the code-pattern scanner and the linter from 2026-12-17; the platform scanner has no date; the
baseline may only go down. Checked with a fake runner, small fixtures and fixed dates: no Docker, no scanner, no
network.
"""

from __future__ import annotations

import datetime as dt
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
    ),
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


def test_the_rule_set_is_refused_at_another_commit(tmp_path: Path) -> None:
    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "0" * 40 + "\n" if "rev-parse" in argv else "", "")

    with pytest.raises(RuntimeError, match=sg.RULES_COMMIT):
        sg.fetch_rules(tmp_path / "rules", run=run)


#: the baseline as first recorded (2026-11-27, at the landing head: the integrator's ruling 7214660183). A line of the baseline file may go down, never
#: above this; raising one here is changing what this test asserts, which needs the integrator's ruling
FIRST_BASELINE = {
    "code-patterns": {"dangerous-os-exec-audit": 2, "dangerous-subprocess-use-audit": 134,
                      "dangerous-subprocess-use-tainted-env-args": 4, "missing-user": 1, "php-version-usage": 1,
                      "subprocess-shell-true": 2, "use-defused-xml": 18, "use-defused-xml-parse": 2},
    "dockerfiles": {"DL3006": 7, "DL3008": 4, "DL3010": 1, "DL3013": 1, "DL3015": 1, "DL4006": 2, "SC1091": 1,
                    "SC2046": 1, "SC2086": 4},
    "platform": {"CKV_K8S_11": 20, "CKV_K8S_14": 20, "CKV_K8S_21": 41, "CKV_K8S_22": 14, "CKV_K8S_23": 3,
                 "CKV_K8S_35": 14, "CKV_K8S_38": 2, "CKV_K8S_40": 4, "CKV_K8S_43": 20, "CKV_K8S_8": 14},
}  # fmt: skip
BEFORE, ON = dt.date(2026, 12, 16), dt.date(2026, 12, 17)


def _raised(base: dict[str, dict[str, int]]) -> list[str]:
    """Each line of ``base`` above the first baseline, or of a tool or rule it did not count."""
    return [f"{tool} {rule} {n}" for tool, by in base.items() for rule, n in by.items()
            if n > FIRST_BASELINE.get(tool, {}).get(rule, 0)]  # fmt: skip


def test_the_baseline_only_goes_down_and_holds_counts_by_rule_only() -> None:
    base = sg.load_baseline()
    assert _raised(base) == [], "a baseline line was raised: only the integrator's ruling may change the first baseline"
    counts = json.dumps(json.loads(sg.BASELINE.read_text(encoding="utf-8"))["counts"])
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+", r) for by in base.values() for r in by)
    assert "/" not in counts and ".py" not in counts and "Dockerfile" not in counts  # no path, no matched text


def test_a_raised_count_and_a_count_that_is_not_a_number_are_refused(tmp_path: Path) -> None:
    for bad in ({"counts": {"nobody": {"x": 1}}}, {"counts": {"platform": {"x": "1"}}}, {"counts": {"platform": {"x": 0}}},
                {"x": 1}):  # fmt: skip
        (tmp_path / "b.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            sg.load_baseline(tmp_path / "b.json")
    platform = FIRST_BASELINE["platform"]
    assert _raised({"platform": {**platform, "CKV_K8S_21": 42}}) == ["platform CKV_K8S_21 42"]
    assert _raised({"secrets-a": {"generic-api-key": 1}}) == ["secrets-a generic-api-key 1"]
    assert _raised({"platform": {**platform, "CKV_K8S_21": 40}}) == []  # going down is allowed


def _record(by_tool: dict[str, dict[str, int]], ran: tuple[str, ...] = sg.TOOLS) -> dict[str, Any]:
    tools = [{"tool": t, "ran": t in ran, "findings": sum(by_tool.get(t, {}).values()), "by_rule": by_tool.get(t, {}),
              "error": "" if t in ran else "not run: exit 1, no report"} for t in sg.TOOLS]  # fmt: skip
    return {"tools": tools, "ignore_files": []}


def test_a_new_finding_fails_from_the_first_day_and_the_baseline_does_not() -> None:
    assert sg.failures(_record(FIRST_BASELINE), FIRST_BASELINE, BEFORE) == []
    more = {**FIRST_BASELINE, "platform": {**FIRST_BASELINE["platform"], "CKV_K8S_21": 42}}
    assert sg.failures(_record(more), FIRST_BASELINE, BEFORE) == [
        "platform: CKV_K8S_21 42, above its baseline of 41 (a new finding)"]  # fmt: skip
    new_rule = {**FIRST_BASELINE, "code-patterns": {**FIRST_BASELINE["code-patterns"], "eval-injection": 1}}
    assert sg.failures(_record(new_rule), FIRST_BASELINE, BEFORE) == [
        "code-patterns: eval-injection 1, above its baseline of 0 (a new finding)"]  # fmt: skip


def test_the_secret_scanners_block_now_the_code_and_the_linter_from_the_date_the_platform_never() -> None:
    leaked = {**FIRST_BASELINE, "secrets-b": {"PrivateKey": 1}}
    got = sg.failures(_record(leaked), FIRST_BASELINE, dt.date(2026, 11, 27))
    assert "secrets-b: 1 finding(s); every finding fails from 2026-11-27" in got
    assert sg.failures(_record(FIRST_BASELINE), FIRST_BASELINE, BEFORE) == []
    on = sg.failures(_record(FIRST_BASELINE), FIRST_BASELINE, ON)
    assert [f.split(":")[0] for f in on] == ["code-patterns", "dockerfiles"]
    assert sg.failures(_record(FIRST_BASELINE), FIRST_BASELINE, dt.date(2030, 1, 1)) == on  # the platform: no date
    assert sg.BLOCKS_FROM["code-patterns"] == sg.BLOCKS_FROM["dockerfiles"] == ON and "platform" not in sg.BLOCKS_FROM


def test_a_tool_that_did_not_run_and_an_ignore_file_fail() -> None:
    rec = _record(FIRST_BASELINE, ran=tuple(t for t in sg.TOOLS if t != "secrets-a"))
    rec["ignore_files"] = [".gitleaksignore"]
    assert sg.failures(rec, FIRST_BASELINE, BEFORE) == ["secrets-a: not run: exit 1, no report",
                                                       "ignore file in the tree: .gitleaksignore"]  # fmt: skip


def test_the_command_writes_the_record_and_fails_on_what_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(sg, "pinned", lambda d, run=None: d)
    clean = {t: (json.dumps({"results": []}) if t == "code-patterns" else "[]") for t in sg.TOOLS}
    clean["secrets-b"], clean["platform"] = "", json.dumps({"results": {"failed_checks": []}})
    base = ["standing-gates", "--src", str(src), "--rules", str(tmp_path / "r"), "--no-fetch", "--today", "2026-12-01",
            "--out"]  # fmt: skip
    for out, rc in ((clean, 0), (FIXTURES, 1)):
        monkeypatch.setattr(subprocess, "run", _Runner(dict(out)))
        assert sc_main.main([*base, str(tmp_path / f"o-{rc}")]) == rc
    record = json.loads((tmp_path / "o-1" / "index.json").read_text(encoding="utf-8"))
    assert {t["tool"]: t["findings"] for t in record["tools"]} == {
        "code-patterns": 3, "secrets-a": 1, "secrets-b": 1, "platform": 1, "dockerfiles": 2}  # fmt: skip
    assert "secrets-a: 1 finding(s); every finding fails from 2026-11-27" in record["failures"]
    summary = (tmp_path / "o-1" / "summary.md").read_text(encoding="utf-8")
    assert "**Fails:**" in summary and "above its baseline" in summary


def test_the_workflow_step_blocks_and_keeps_its_summary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"- name: Standing release gates\n(.*?)(?=\n      - name:)", text, re.S)
    assert m, "no standing release gates step"
    step = m.group(1)
    assert "continue-on-error" not in step and "make standing-gates" in step and 'exit "$rc"' in step
    head = text[: m.start()].rsplit("\n\n", 1)[-1]
    assert "BLOCKING" in head and "2026-12-17" in head and "7213778687" in head
    assert "trialbox/build/standing-gates" in text
