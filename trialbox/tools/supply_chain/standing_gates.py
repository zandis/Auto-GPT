"""Standing release gates (release hygiene item 5): five scans of the tree in the release build, report-only until
a dated switch.

    python -m tools.supply_chain standing-gates --out build/standing-gates --src .. --rules .cache/code-rules

* **the code-pattern scanner** on ``trialbox/`` and the workflows, with the public rule set at a pinned commit
  (:data:`RULES_COMMIT`): its security folders for Python, Dockerfiles and shell (:data:`RULE_DIRS`), severity ERROR;
  comment pragmas are not honoured (``--disable-nosem``) and nothing is sent anywhere (``--metrics=off``);
* **two secret scanners** on the whole tree: the first with its inline allow comments not honoured
  (``--ignore-gitleaks-allow``), the second with no verification (no secret leaves the runner);
* **the platform-manifest scanner** on ``trialbox/deploy/platform``;
* **the Dockerfile linter** on every Dockerfile of the tree (:data:`DOCKERFILES`), its ignore pragmas not honoured.

Every tool is an image pinned by version and digest (:data:`IMAGES`), run with no network but the rule set's own
fetch (done before, by :func:`fetch_rules`), the tree mounted read-only. No ignore file, no allow-list and no
configuration file is given to any tool; :func:`ignore_files` names any such file found in the tree, and it is counted
as a finding. Each report is kept as JSON in ``--out`` with ``summary.md`` (a row per tool, its count and its counts
by rule) and ``index.json``.

Report-only until :data:`GATING_FROM` (the date is the integrator's to set: until then it is a placeholder, written
"date: by ruling" in the workflow): the command exits 0 whatever the findings, and a tool that does not run is
written into the summary. ``--fail-at any`` (the switch for that date) fails on any finding or any tool that did not
run.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: placeholder until the integrator's ruling (7213761934): report-only before it, ``--fail-at any`` from it
GATING_FROM = dt.date(2026, 12, 17)
#: each tool's image, by version and by the digest of its multi-platform index (read from the registry 2026-11-27)
IMAGES = {
    "code-patterns": "semgrep/semgrep:1.187.0@sha256:0c8dfa7aa1ca8c50233ec9110e8cd88d139dedd603d56507493f74c6f4b3e062",
    "secrets-a": "zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f",
    "secrets-b": "trufflesecurity/trufflehog:3.100.1@sha256:9c7a8325d43a4af2960d3f21d61a08981d8a1bf0542e007efa2e47097e386452",
    "platform": "bridgecrew/checkov:3.4.11@sha256:68da9ede242807850ab346b533dc1e4d2b00e15a9e6b4b595654d39c7f2e2566",
    "dockerfiles": "hadolint/hadolint:v2.12.0@sha256:30a8fd2e785ab6176eed53f74769e04f125afb2f74a6c52aef7d463583b6d45e",
}
TOOLS = tuple(IMAGES)
#: the public rule set of the code-pattern scanner, at one commit (2026-11-10); fetched by :func:`fetch_rules`
RULES_REPO = "https://github.com/semgrep/semgrep-rules"
RULES_COMMIT = "a5ad1714f00c9f7fde980cab0ea1d6dc6d414fd2"
RULE_DIRS = ("python/lang/security", "dockerfile/security", "bash/lang/security")
#: every Dockerfile of the tree, relative to ``trialbox/`` (the Makefile's HADOLINT_GATING and HADOLINT_REPORT)
DOCKERFILES = (
    "deploy/docker/python.Dockerfile",
    "deploy/docker/jvm.Dockerfile",
    "demo/Dockerfile",
    "deploy/docker/backup.Dockerfile",
    "deploy/docker/embed.Dockerfile",
    "deploy/docker/db.Dockerfile",
    "deploy/redcap-test/Dockerfile",
    "tools/rehearse_box/host.Dockerfile",
    "tools/bench_ci/runner.Dockerfile",
)
#: files by which a tool would accept or skip a finding without an argument; none may be in the tree
IGNORE_FILES = (
    ".semgrepignore",
    ".gitleaksignore",
    ".gitleaks.toml",
    "gitleaks.toml",
    ".checkov.yaml",
    ".checkov.yml",
    ".hadolint.yaml",
    ".hadolint.yml",
    "hadolint.yaml",
    ".trufflehogignore",
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass
class ToolResult:
    tool: str
    image: str
    ran: bool
    findings: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)
    error: str = ""

    def row(self) -> dict[str, Any]:
        return {"tool": self.tool, "image": self.image, "ran": self.ran, "findings": self.findings,
                "by_rule": dict(sorted(self.by_rule.items())), "error": self.error}  # fmt: skip


def docker_run(image: str, src: Path, args: Sequence[str], *, rules: Path | None = None) -> list[str]:
    """One tool's run: no network, the tree read-only at ``/src`` (and the rule set at ``/rules``), the image by
    digest."""
    argv = ["docker", "run", "--rm", "--network", "none", "-v", f"{src}:/src:ro", "-w", "/src"]
    if rules is not None:
        argv += ["-v", f"{rules}:/rules:ro"]
    return [*argv, image, *args]


def commands(src: Path, rules: Path) -> dict[str, list[str]]:
    """Each tool's command line; its JSON report goes to standard output."""
    code = ["semgrep", "scan", "--metrics=off", "--disable-version-check", "--disable-nosem", "--severity", "ERROR",
            "--json", *(a for d in RULE_DIRS for a in ("--config", f"/rules/{d}")), "trialbox", ".github"]  # fmt: skip
    return {
        "code-patterns": docker_run(IMAGES["code-patterns"], src, code, rules=rules),
        "secrets-a": docker_run(
            IMAGES["secrets-a"],
            src,
            [
                "dir",
                "/src",
                "--ignore-gitleaks-allow",
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                "/dev/stdout",
                "--exit-code",
                "0",
            ],
        ),  # fmt: skip
        "secrets-b": docker_run(
            IMAGES["secrets-b"], src, ["filesystem", "/src", "--no-verification", "--json", "--no-update"]
        ),  # fmt: skip
        "platform": docker_run(
            IMAGES["platform"],
            src,
            [
                "-d",
                "/src/trialbox/deploy/platform",
                "-o",
                "json",
                "--quiet",
                "--compact",
                "--soft-fail",
                "--skip-download",
            ],
        ),  # fmt: skip
        "dockerfiles": docker_run(
            IMAGES["dockerfiles"],
            src,
            [
                "hadolint",
                "--disable-ignore-pragma",
                "--no-fail",
                "-f",
                "json",
                *(f"/src/trialbox/{f}" for f in DOCKERFILES),
            ],
        ),  # fmt: skip
    }


def count(tool: str, text: str) -> tuple[int, dict[str, int]]:
    """(findings, findings by rule) of one tool's JSON output; ``ValueError`` when it is not what the tool writes."""
    if tool == "secrets-b":  # one JSON object per line
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        by = Counter(str(r.get("DetectorName") or "?") for r in rows if isinstance(r, dict) and "DetectorName" in r)
        return sum(by.values()), dict(by)
    doc = json.loads(text)
    if tool == "code-patterns":
        by = Counter(str(r["check_id"]).rsplit(".", 1)[-1] for r in doc["results"])
    elif tool == "secrets-a":
        by = Counter(str(r.get("RuleID") or "?") for r in doc)
    elif tool == "platform":
        reports = doc if isinstance(doc, list) else [doc]
        by = Counter(str(c["check_id"]) for r in reports for c in r["results"]["failed_checks"])
    elif tool == "dockerfiles":
        by = Counter(str(r.get("code") or "?") for r in doc)
    else:
        raise ValueError(f"unknown tool {tool!r}")
    return sum(by.values()), dict(by)


def ignore_files(src: Path) -> list[str]:
    """Every file in the tree by which a tool would accept or skip a finding (none may be there)."""
    return sorted(str(p.relative_to(src)) for name in IGNORE_FILES for p in src.rglob(name) if ".git" not in p.parts)


def fetch_rules(dest: Path, run: Runner = subprocess.run) -> Path:
    """The rule set at :data:`RULES_COMMIT` (a shallow fetch of that commit); refused when another commit came."""
    dest.mkdir(parents=True, exist_ok=True)
    for argv in (["git", "init", "-q", str(dest)], ["git", "-C", str(dest), "fetch", "-q", "--depth", "1", RULES_REPO,
                 RULES_COMMIT], ["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"]):  # fmt: skip
        run(argv, check=True, capture_output=True, text=True, timeout=600)
    return pinned(dest, run)


def pinned(dest: Path, run: Runner = subprocess.run) -> Path:
    """``dest`` when it holds the rule set at :data:`RULES_COMMIT`; ``RuntimeError`` naming the commit it holds."""
    head = run(["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if head != RULES_COMMIT:
        raise RuntimeError(f"the rule set in {dest} is at {head}, not the pinned {RULES_COMMIT}")
    return dest


def scan(src: Path, rules: Path, out: Path, run: Runner | None = None) -> dict[str, Any]:
    """Run the five tools; write their reports, ``summary.md`` and ``index.json`` into ``out``; the record."""
    run = run or subprocess.run
    out.mkdir(parents=True, exist_ok=True)
    results: list[ToolResult] = []
    for tool, argv in commands(src, rules).items():
        res = ToolResult(tool, IMAGES[tool], ran=False)
        try:
            got = run(argv, capture_output=True, text=True, check=False, timeout=3600)
        except (OSError, subprocess.SubprocessError) as exc:
            res.error = f"not run: {type(exc).__name__}"
            results.append(res)
            continue
        (out / f"{tool}.json").write_text(got.stdout, encoding="utf-8")
        try:
            res.findings, res.by_rule = count(tool, got.stdout)
            res.ran = True
        except (ValueError, KeyError, TypeError):
            res.error = f"not run: exit {got.returncode}, no report"
        results.append(res)
    found = ignore_files(src)
    record = {"gating_from": GATING_FROM.isoformat(), "date": "by ruling", "rules_commit": RULES_COMMIT,
              "tools": [r.row() for r in results], "ignore_files": found}  # fmt: skip
    (out / "index.json").write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(summary(record), encoding="utf-8")
    return record


def summary(record: dict[str, Any]) -> str:
    lines = [
        f"## Standing release gates (report-only until {record['gating_from']}, date: by ruling)",
        "",
        "| Tool | Image | Findings | By rule |",
        "| --- | --- | --- | --- |",
    ]
    for t in record["tools"]:
        rules = ", ".join(f"{k} {v}" for k, v in sorted(t["by_rule"].items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"| {t['tool']} | `{t['image']}` | {t['findings'] if t['ran'] else t['error']} | {rules or '-'} |")
    if record["ignore_files"]:
        lines += ["", "Ignore files in the tree (each is a finding): " + ", ".join(record["ignore_files"])]
    return "\n".join(lines) + "\n"


def failures(record: dict[str, Any]) -> list[str]:
    """What ``--fail-at any`` fails on: a finding of any tool, a tool that did not run, an ignore file."""
    out = [f"{t['tool']}: {t['error']}" for t in record["tools"] if not t["ran"]]
    out += [f"{t['tool']}: {t['findings']} finding(s)" for t in record["tools"] if t["ran"] and t["findings"]]
    out += [f"ignore file in the tree: {f}" for f in record["ignore_files"]]
    return out
