"""Release hygiene item 5: the standing release gates over the tree, measured against a baseline that only goes down.

Five scans in the release build: the code-pattern scanner with its rule set at a pinned commit, two secret scanners
(no verification), the platform-manifest scanner on ``deploy/platform`` and the Dockerfile linter on every tracked
Dockerfile under ``trialbox/``.
The integrator's ruling (7213778687): a count above the baseline fails from the first day; every finding of the secret
scanners fails now, of the code-pattern scanner and the linter from 2026-12-17; the platform scanner has no date; the
baseline may only go down. Checked with a fake runner, small fixtures and fixed dates: no Docker, no scanner, no
network.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.supply_chain import __main__ as sc_main
from tools.supply_chain import standing_gates as sg

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-images.yml"

FIXTURES = {
    "code-patterns": json.dumps(
        {
            "paths": {"scanned": ["trialbox/a.py"]},
            "results": [
                {"check_id": "python.lang.security.a.subprocess-shell-true"},
                {"check_id": "python.lang.security.b.use-defused-xml"},
                {"check_id": "python.lang.security.b.use-defused-xml"},
            ],
        }
    ),
    "secrets-a": json.dumps([{"RuleID": "generic-api-key"}]),
    "secrets-b": json.dumps({"DetectorName": "PrivateKey"}) + "\n" + json.dumps({"level": "info", "msg": "done"}),
    "platform": json.dumps(
        {
            "check_type": "kubernetes",
            "summary": {"passed": 0, "failed": 1},
            "results": {"failed_checks": [{"check_id": "CKV_K8S_21"}]},
        }
    ),
    "dockerfiles": json.dumps([{"code": "DL3008"}, {"code": "DL3008"}]),
}


DONE = json.dumps({"level": "info", "msg": "finished scanning"})  # the secret scanner's line when it is done
CLEAN = {"code-patterns": json.dumps({"results": [], "errors": [], "paths": {"scanned": ["trialbox/a.py"]}}),
         "secrets-a": "[]", "secrets-b": DONE,
         "platform": json.dumps({"check_type": "kubernetes", "summary": {"passed": 1, "failed": 0},
                                 "results": {"failed_checks": []}}), "dockerfiles": "[]"}  # fmt: skip
BASELINE_PATH = "trialbox/deploy/security/standing-gates-baseline.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True, text=True)  # fmt: skip


def _repo(root: Path, files: dict[str, str]) -> Path:
    """A git repository at ``root`` with ``files`` tracked."""
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    return root


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
    dockerfiles = ["demo/Dockerfile"]
    cmds = sg.commands(tmp_path / "src", tmp_path / "rules", dockerfiles)
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
    assert [a for a in cmds["dockerfiles"] if a.startswith("/src/")] == [f"/src/trialbox/{f}" for f in dockerfiles]
    for argv in cmds.values():  # no ignore file, baseline or configuration handed to any tool
        assert not any(re.search(r"ignore|baseline|allow|config-file|--skip-check|--exclude", a) for a in argv
                       if a not in ("--ignore-gitleaks-allow", "--disable-ignore-pragma")), argv  # fmt: skip


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


def _raised(base: dict[str, dict[str, int]], floor: dict[str, dict[str, int]] = FIRST_BASELINE) -> list[str]:
    """Each line of ``base`` above ``floor`` (the first baseline), or of a tool or rule it did not count."""
    return [f"{tool} {rule} {n}" for tool, by in base.items() for rule, n in by.items()
            if n > floor.get(tool, {}).get(rule, 0)]  # fmt: skip


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
    src = _repo(tmp_path / "src", {"trialbox/a.py": "x = 1\n"})
    monkeypatch.setattr(sg, "pinned", lambda d, run=None: d)
    leaks = {**FIXTURES, "secrets-b": FIXTURES["secrets-b"] + "\n" + DONE}
    base = ["standing-gates", "--src", str(src), "--rules", str(tmp_path / "r"), "--no-fetch", "--today", "2026-12-01",
            "--out"]  # fmt: skip
    real = subprocess.run
    for out, rc in ((CLEAN, 0), (leaks, 1)):
        fake = _Runner(dict(out))
        monkeypatch.setattr(subprocess, "run", lambda argv, f=fake, **kw: (real if argv[0] == "git" else f)(argv, **kw))
        assert sc_main.main([*base, str(tmp_path / f"o-{rc}")]) == rc
    reports = tmp_path / "o-1" / "reports"
    record = json.loads((reports / "index.json").read_text(encoding="utf-8"))
    assert {t["tool"]: t["findings"] for t in record["tools"]} == {
        "code-patterns": 3, "secrets-a": 1, "secrets-b": 1, "platform": 1, "dockerfiles": 2}  # fmt: skip
    assert "secrets-a: 1 finding(s); every finding fails from 2026-11-27" in record["failures"]
    summary = (reports / "summary.md").read_text(encoding="utf-8")
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


# --- the findings of the review of #1587 (SG-01 .. SG-07): each of these tests fails on the head it was written against


def _fake(out: dict[str, str], rc: dict[str, int] | None = None, err: dict[str, str] | None = None) -> sg.Runner:
    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        tool = _tool_of(argv)
        return subprocess.CompletedProcess(argv, (rc or {}).get(tool, 0), out[tool], (err or {}).get(tool, ""))

    return run


def _scan(tmp_path: Path, out: dict[str, str] | None = None, **kw: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n"})
    run = _fake({**CLEAN, **(out or {})}, **kw)
    return sg.scan(repo, tmp_path / "rules", tmp_path / "out", run, baseline={}, today=BEFORE)


def test_sg01_the_kept_reports_hold_rule_file_and_line_only_and_nothing_is_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "not-a-real-secret-0000"
    found = {"secrets-a": json.dumps([{"RuleID": "generic-api-key", "File": "a.py", "StartLine": 3, "Secret": secret}]),
             "secrets-b": json.dumps({"DetectorName": "PrivateKey", "Raw": secret, "SourceMetadata": {"Data": {
                 "Filesystem": {"file": "b.py", "line": 7}}}}) + "\n" + DONE}  # fmt: skip
    _scan(tmp_path, found, err={"secrets-a": secret, "secrets-b": secret})
    out = tmp_path / "out" / sg.REPORTS_DIR
    assert secret not in "".join(p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file())
    assert json.loads((out / "secrets-a.json").read_text(encoding="utf-8")) == [
        {"rule": "generic-api-key", "file": "a.py", "line": 3}]  # fmt: skip
    assert json.loads((out / "secrets-b.json").read_text(encoding="utf-8")) == [
        {"rule": "PrivateKey", "file": "b.py", "line": 7}]  # fmt: skip
    assert json.loads((out / "rows.json").read_text(encoding="utf-8")) == {
        tool: json.loads((out / f"{tool}.json").read_text(encoding="utf-8")) for tool in sg.TOOLS
    }
    shown = capsys.readouterr()
    assert secret not in shown.out + shown.err


def test_sg02_only_exit_zero_with_the_completion_line_is_a_run(tmp_path: Path) -> None:
    def ran(name: str, out: dict[str, str], **kw: dict[str, Any]) -> dict[str, bool]:
        return {t["tool"]: t["ran"] for t in _scan(tmp_path / name, out, **kw)["tools"]}

    assert all(ran("clean", {}).values())
    assert not ran("silent", {"secrets-b": ""})["secrets-b"]  # exit 0 and nothing printed: it never said it was done
    docker = ran("docker", {"secrets-b": ""}, rc={"secrets-b": 125}, err={"secrets-b": "docker: cannot start"})
    assert not docker["secrets-b"]
    assert not ran("exit1", {"secrets-a": "[]"}, rc={"secrets-a": 1})["secrets-a"]  # a report is not a run on exit 1
    assert ran("exit1b", {}, rc={"secrets-a": 1})["secrets-b"]  # one tool's failure leaves the others


def test_sg02_every_tool_is_in_report_mode(tmp_path: Path) -> None:
    flat = {t: " ".join(a) for t, a in sg.commands(tmp_path / "src", tmp_path / "rules", ["Dockerfile"]).items()}
    assert (
        "--exit-code 0" in flat["secrets-a"]
        and "--soft-fail" in flat["platform"]
        and "--no-fail" in flat["dockerfiles"]
    )
    assert not re.search(r"--error|--fail", flat["code-patterns"] + flat["secrets-b"])


def test_sg03_the_rule_files_are_hashed_and_a_copy_is_what_is_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", sg.RULES_DIGEST)
    rules = tmp_path / "rules"
    for d in sg.RULE_DIRS:
        (rules / d).mkdir(parents=True)
        (rules / d / "r.yaml").write_text("rules: []\n", encoding="utf-8")

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, sg.RULES_COMMIT + "\n", "")

    monkeypatch.setattr(sg, "RULES_DIGEST", sg.rules_digest(rules))
    copy = sg.pinned(rules, run=run)
    assert not copy.is_relative_to(rules) and sg.rules_digest(copy) == sg.RULES_DIGEST
    (rules / sg.RULE_DIRS[0] / "r.yaml").write_text("rules: [weakened]\n", encoding="utf-8")  # edited, HEAD unchanged
    with pytest.raises(RuntimeError, match="hash"):
        sg.pinned(rules, run=run)


def test_sg03_a_linked_rule_with_the_pinned_bytes_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rules = tmp_path / "rules"
    for d in sg.RULE_DIRS:
        (rules / d).mkdir(parents=True)
    rule = rules / sg.RULE_DIRS[0] / "rule.yaml"
    rule.write_text("rules: []\n", encoding="utf-8")
    monkeypatch.setattr(sg, "RULES_DIGEST", sg.rules_digest(rules))
    target = rule.rename(tmp_path / "target.yaml")
    try:
        rule.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"cannot create symlinks: {exc}")

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, sg.RULES_COMMIT + "\n", "")

    with pytest.raises(RuntimeError, match="symlink"):
        sg.pinned(rules, run=run)


def test_sg04_a_baseline_raised_over_the_base_branch_is_refused() -> None:
    platform = FIRST_BASELINE["platform"]
    on_base = {"platform": {**platform, "CKV_K8S_21": 40}}  # 41 on the first baseline, 40 after a fix, 41 again
    assert _raised({"platform": platform}, on_base) == ["platform CKV_K8S_21 41"]
    assert _raised(on_base, on_base) == [] and _raised({"platform": {**platform, "CKV_K8S_21": 39}}, on_base) == []


def _base_counts(base: str, repo: Path) -> dict[str, dict[str, int]] | None:
    """The baseline's counts on ``origin/<base>``; None when that branch has no baseline yet; ``RuntimeError`` (the
    check fails closed) when the branch cannot be read."""
    ref = f"origin/{base}"
    git = ["git", "-C", str(repo)]
    try:
        subprocess.run([*git, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=True, capture_output=True)
        listed = subprocess.run([*git, "ls-tree", "--name-only", ref, "--", BASELINE_PATH], check=True,
                                capture_output=True, text=True).stdout  # fmt: skip
        if not listed.strip():
            return None
        shown = subprocess.run([*git, "show", f"{ref}:{BASELINE_PATH}"], check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise RuntimeError(f"the base branch {ref} cannot be read: {type(exc).__name__}") from exc
    return json.loads(shown.stdout)["counts"]  # type: ignore[no-any-return]


def test_sg04_the_base_branch_is_read_or_the_check_fails_closed(tmp_path: Path) -> None:
    counts = {"platform": {"CKV_K8S_21": 40}}
    repo = _repo(tmp_path / "a", {BASELINE_PATH: json.dumps({"counts": counts})})
    _git(repo, "commit", "-qm", "x")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _base_counts("main", repo) == counts
    with pytest.raises(RuntimeError, match="cannot be read"):
        _base_counts("no-such-branch", repo)
    bare = _repo(tmp_path / "b", {"x": "1"})  # a base that has no baseline file yet (the branch that adds it)
    _git(bare, "commit", "-qm", "x")
    _git(bare, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert _base_counts("main", bare) is None


def test_sg04_the_baseline_is_not_raised_over_the_pull_requests_base_branch() -> None:
    base = os.environ.get("GITHUB_BASE_REF")
    if not base:
        pytest.skip("not a pull request run: no base branch is named (the unit shards fetch it for a pull request)")
    floor = _base_counts(base, ROOT.parent)
    assert floor is None or _raised(sg.load_baseline(), floor) == []


def test_sg04_the_unit_shards_fetch_the_base_branch() -> None:
    text = (ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml").read_text(encoding="utf-8")
    m = re.search(r"\n  unit-shard:\n(.*?)(?=\n  [a-z0-9-]+:\n)", text, re.S)
    assert m and "git fetch --depth=1 origin" in m.group(1) and "github.base_ref" in m.group(1)


def test_sg05_a_tools_own_error_fields_fail_the_gate(tmp_path: Path) -> None:
    errors = {
        "code-patterns": json.dumps(
            {**json.loads(CLEAN["code-patterns"]), "errors": [{"code": 3, "message": "Syntax error"}]}
        ),
        "platform": json.dumps(
            {
                "check_type": "kubernetes",
                "summary": {"passed": 1, "failed": 0, "parsing_errors": 1},
                "results": {"failed_checks": []},
            }
        ),
        "secrets-b": json.dumps({"level": "error", "msg": "could not read a file"}) + "\n" + DONE,
    }
    for tool, text in errors.items():
        rec = _scan(tmp_path / tool, {tool: text})
        assert not next(t for t in rec["tools"] if t["tool"] == tool)["ran"], tool
        assert any(f.startswith(f"{tool}: not run") for f in rec["failures"]), tool


def test_sg06_the_scanners_read_a_copy_of_the_tracked_files_outside_the_tree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n", "README": "r\n"})
    for stale in ("trialbox/build/standing-gates/old.json", "trialbox/.cache/code-rules/r.yaml"):  # not tracked
        (repo / stale).parent.mkdir(parents=True, exist_ok=True)
        (repo / stale).write_text("stale\n", encoding="utf-8")
    seen: list[tuple[Path, list[str]]] = []

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        mount = Path(next(a for a in argv if a.endswith(":/src:ro")).rsplit(":/src:ro", 1)[0])
        seen.append((mount, sorted(p.relative_to(mount).as_posix() for p in mount.rglob("*") if p.is_file())))
        return _fake(CLEAN)(argv, **kw)

    sg.scan(repo, tmp_path / "rules", tmp_path / "out", run, baseline={}, today=BEFORE)
    assert len(seen) == len(sg.TOOLS)
    for mount, files in seen:
        assert mount != repo and not mount.is_relative_to(repo)
        assert files == ["README", "trialbox/a.py"]
    assert not seen[0][0].exists()  # the copy is removed after the run


@pytest.mark.parametrize("subdir", ["", "reports"])
def test_sg10_an_unowned_nonempty_output_directory_is_refused(tmp_path: Path, subdir: str) -> None:
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n"})
    out = tmp_path / "out"
    sentinel = out / subdir / "keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep\n", encoding="utf-8")
    fake = _Runner(CLEAN)

    with pytest.raises(RuntimeError, match="refusing unowned") as exc:
        sg.scan(repo, tmp_path / "rules", out, fake, baseline={}, today=BEFORE)
    assert isinstance(exc.value, sg.OutputDirectoryError)
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert not fake.calls


def test_sg06_a_failed_rerun_removes_previous_reports(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n"})
    rules, out = tmp_path / "rules", tmp_path / "out"
    sg.scan(repo, rules, out, _fake(CLEAN), baseline={}, today=BEFORE)
    reports = out / sg.REPORTS_DIR
    assert (reports / "platform.json").is_file()

    rec = sg.scan(repo, rules, out, _fake(CLEAN, rc={"platform": 1}), baseline={}, today=BEFORE)
    assert "platform: not run: exit 1" in rec["failures"]
    assert not (reports / "platform.json").exists()


@pytest.mark.parametrize("failed_setup", ["rules", "baseline"])
def test_sg06_a_cli_setup_failure_invalidates_previous_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_setup: str
) -> None:
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n"})
    rules, out, baseline = (tmp_path / name for name in ("rules", "out", "baseline.json"))
    baseline.write_text('{"counts": {}}\n', encoding="utf-8")
    monkeypatch.setattr(sg, "fetch_rules", lambda dest: dest)
    real, fake = subprocess.run, _Runner(CLEAN)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (real if argv[0] == "git" else fake)(argv, **kw))
    args = ["standing-gates", "--src", str(repo), "--rules", str(rules), "--out", str(out),
            "--baseline", str(baseline)]  # fmt: skip
    assert sc_main.main(args) == 0
    assert list(out.rglob("summary.md"))
    assert list(out.rglob("index.json"))
    fake.calls.clear()

    def fail_fetch(dest: Path) -> Path:
        raise subprocess.CalledProcessError(1, ["git", "fetch"])

    if failed_setup == "rules":
        monkeypatch.setattr(sg, "fetch_rules", fail_fetch)
    else:
        baseline.unlink()
    assert sc_main.main(args) == 2
    assert not list(out.rglob("*.json"))
    assert not list(out.rglob("summary.md"))
    assert not fake.calls


def test_sg07_hadolint_receives_only_tracked_dockerfiles_under_trialbox(tmp_path: Path) -> None:
    names = ["trialbox/.Dockerfile", "trialbox/demo/Dockerfile", "trialbox/a/b.Dockerfile",
             "trialbox/deploy/docker/Dockerfile.worker", "trialbox/deploy/docker/jvm.Dockerfile.dockerignore",
             "Dockerfile"]  # fmt: skip
    repo = _repo(tmp_path / "repo", dict.fromkeys(names, ""))
    (repo / "trialbox/untracked.Dockerfile").write_text("", encoding="utf-8")
    fake = _Runner(CLEAN)
    sg.scan(repo, tmp_path / "rules", tmp_path / "out", fake, baseline={}, today=BEFORE)
    argv = next(call for call in fake.calls if _tool_of(call) == "dockerfiles")
    assert argv[argv.index("json") + 1 :] == [
        "/src/trialbox/.Dockerfile",
        "/src/trialbox/a/b.Dockerfile",
        "/src/trialbox/demo/Dockerfile",
        "/src/trialbox/deploy/docker/Dockerfile.worker",
    ]


@pytest.mark.parametrize(
    ("report", "error"),
    [
        ("[]", "no report"),
        ('{"results":{"failed_checks":[]}}', "no Kubernetes checks evaluated"),
        (
            '{"check_type":"kubernetes","summary":{"passed":0,"failed":0},"results":{"failed_checks":[]}}',
            "no Kubernetes checks evaluated",
        ),
    ],
)
def test_sg08_an_empty_checkov_report_fails_even_on_exit_zero(tmp_path: Path, report: str, error: str) -> None:
    rec = _scan(tmp_path, {"platform": report})
    assert not next(t for t in rec["tools"] if t["tool"] == "platform")["ran"]
    assert f"platform: not run: {error}" in rec["failures"]
    assert not (tmp_path / "out" / sg.REPORTS_DIR / "platform.json").exists()


@pytest.mark.parametrize("tool", ["secrets-a", "dockerfiles"])
def test_sg11_only_json_arrays_are_valid_reports(tmp_path: Path, tool: str) -> None:
    invalid = _scan(tmp_path / "invalid", {tool: "{}"})
    clean = _scan(tmp_path / "clean", {tool: "[]"})
    assert f"{tool}: not run: no report" in invalid["failures"]
    assert not next(t for t in invalid["tools"] if t["tool"] == tool)["ran"]
    assert next(t for t in clean["tools"] if t["tool"] == tool)["ran"]
    assert clean["failures"] == []


@pytest.mark.parametrize("baseline_fails", [False, True])
def test_sg09_the_pinned_rules_are_removed_after_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline_fails: bool
) -> None:
    rules = tmp_path / "rules"
    for d in sg.RULE_DIRS:
        (rules / d).mkdir(parents=True)
        (rules / d / "rule.yaml").write_text("rules: []\n", encoding="utf-8")

    def git_head(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, sg.RULES_COMMIT + "\n", "")

    def bad_baseline() -> dict[str, dict[str, int]]:
        raise ValueError("bad baseline")

    monkeypatch.setattr(sg, "RULES_DIGEST", sg.rules_digest(rules))
    monkeypatch.setattr(sg, "load_baseline", bad_baseline)
    copy = sg.pinned(rules, run=git_head)
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n"})

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert copy.is_dir()
        return _fake(CLEAN)(argv, **kw)

    if baseline_fails:
        with pytest.raises(ValueError, match="bad baseline"):
            sg.scan(repo, copy, tmp_path / "out", run, today=BEFORE)
    else:
        sg.scan(repo, copy, tmp_path / "out", run, baseline={}, today=BEFORE)
    assert not copy.exists()


def test_sg12_the_workflow_uploads_only_the_redacted_standing_gate_rows() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    uploads = {
        step["with"]["name"]: step["with"]["path"].splitlines()
        for job in jobs.values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    }
    assert uploads == {
        "standing-gates-rows": ["${{ steps.standing-gates.outputs.rows_dir }}/rows.json"],
        "image-gates-${{ strategy.job-index }}": [
            "trialbox/build/supply-chain",
            "trialbox/build/image-scan",
            "trialbox/dist/sbom",
        ],
        "image-gates-multiarch": ["trialbox/build/supply-chain-multiarch", "trialbox/dist/sbom"],
    }


@pytest.mark.parametrize("rerun", [False, True])
def test_sg13_an_abruptly_terminated_scan_leaves_reusable_output(tmp_path: Path, rerun: bool) -> None:
    repo = _repo(tmp_path / "repo", {"trialbox/a.py": "x = 1\n"})
    rules, out = tmp_path / "rules", tmp_path / "out"
    if rerun:
        sg.scan(repo, rules, out, _fake(CLEAN), baseline={}, today=BEFORE)

    script = """
import os
import sys
import tempfile
from pathlib import Path

from tools.supply_chain import standing_gates as sg

src, rules, out = map(Path, sys.argv[1:])
tempfile.tempdir = str(out.parent)
reports = out / sg.REPORTS_DIR
if reports.exists():
    unlink = Path.unlink

    def interrupt_cleanup(path, *args, **kwargs):
        unlink(path, *args, **kwargs)
        if path.parent == reports:
            os._exit(23)

    Path.unlink = interrupt_cleanup

sg.scan(src, rules, out, lambda *args, **kwargs: os._exit(23), baseline={})
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(repo), str(rules), str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 23, child.stderr
    assert (out / sg.REPORTS_DIR / sg._REPORTS_OWNER).is_file()
    rec = sg.scan(repo, rules, out, _fake(CLEAN), baseline={}, today=BEFORE)
    assert rec["failures"] == []


def test_sg14_a_suppressed_check_fails_even_when_another_check_passed(tmp_path: Path) -> None:
    report = {
        "check_type": "kubernetes",
        "summary": {"passed": 1, "failed": 0, "skipped": 1},
        "results": {"failed_checks": [], "skipped_checks": [{"check_id": "CKV_K8S_21"}]},
    }
    rec = _scan(tmp_path, {"platform": json.dumps(report)})
    assert "platform: not run: 1 skipped check(s)" in rec["failures"]


@pytest.mark.parametrize(
    "report",
    [
        {"results": {}},
        {"results": {}, "paths": {"scanned": ["trialbox/a.py"]}},
        {"results": [], "paths": {}},
        {"results": [], "paths": {"scanned": {}}},
    ],
)
def test_sg15_semgrep_requires_results_and_scanned_paths_arrays(tmp_path: Path, report: dict[str, Any]) -> None:
    invalid = _scan(tmp_path / "invalid", {"code-patterns": json.dumps(report)})
    clean = _scan(tmp_path / "clean")
    assert "code-patterns: not run: no report" in invalid["failures"]
    assert not next(t for t in invalid["tools"] if t["tool"] == "code-patterns")["ran"]
    assert not (tmp_path / "invalid" / "out" / sg.REPORTS_DIR / "code-patterns.json").exists()
    assert next(t for t in clean["tools"] if t["tool"] == "code-patterns")["ran"]
    assert clean["failures"] == []
