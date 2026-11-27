"""Standing release gates (release hygiene item 5): five scans of the tree in the release build, each measured
against a baseline that may only go down.

    python -m tools.supply_chain standing-gates --out build/standing-gates --src .. --rules .cache/code-rules

* **the code-pattern scanner** on ``trialbox/`` and the workflows, with the public rule set at a pinned commit
  (:data:`RULES_COMMIT`): its security folders for Python, Dockerfiles and shell (:data:`RULE_DIRS`), severity ERROR;
  comment pragmas are not honoured (``--disable-nosem``) and nothing is sent anywhere (``--metrics=off``);
* **two secret scanners** on the whole tree: the first with its inline allow comments not honoured
  (``--ignore-gitleaks-allow``), the second with no verification (no secret leaves the runner);
* **the platform-manifest scanner** on ``trialbox/deploy/platform``;
* **the Dockerfile linter** on every Dockerfile of the tree (:data:`DOCKERFILES`), its ignore pragmas not honoured.

Every tool is an image pinned by version and digest (:data:`IMAGES`), run with no network but the rule set's own
fetch (done before, by :func:`fetch_rules`). It reads a copy of the tracked files, mounted read-only (:func:`snapshot`:
the rule checkout and earlier reports are not in it), and a copy of the rule folders that matches :data:`RULES_DIGEST`.
No ignore file, no allow-list and no configuration file is given to any tool; :func:`ignore_files` names any such file
found in the tree, and it is counted as a finding. Each report is read in memory and only its rows (rule, file, line;
never matched text) are kept as JSON in ``--out``, with ``summary.md`` (a row per tool, its count and its counts by
rule) and ``index.json``.

What fails (the integrator's ruling 7213778687), :func:`failures`:

* a tool that did not run, or an ignore file in the tree;
* NEW findings, from the first day: a count of any rule above its line in the baseline (:data:`BASELINE`, counts by
  rule only, never matched text or a path). A rule the baseline does not name has a baseline of 0. The baseline may
  only go down: its test refuses an edit that raises a count;
* every finding of a tool from its date in :data:`BLOCKS_FROM`: the two secret scanners at once, the code-pattern
  scanner and the Dockerfile linter from 2026-12-17 (with D-1343). The platform-manifest scanner has no date: it stays
  on its baseline until the platform path it scans ships.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: from when every finding of a tool fails (the integrator's ruling 7213778687); a tool not named has no date
BLOCKS_FROM = {
    "secrets-a": dt.date(2026, 11, 27),
    "secrets-b": dt.date(2026, 11, 27),
    "code-patterns": dt.date(2026, 12, 17),
    "dockerfiles": dt.date(2026, 12, 17),
}
#: today's counts by rule of each tool; a count may only go down (tests/unit/test_standing_release_gates_hyg5.py)
BASELINE = Path(__file__).resolve().parents[2] / "deploy" / "security" / "standing-gates-baseline.json"
#: each tool's image, by version and by the digest of its multi-platform index (read from the registry 2026-11-27)
IMAGES = {
    "code-patterns": "semgrep/semgrep:1.187.0@sha256:0c8dfa7aa1ca8c50233ec9110e8cd88d139dedd603d56507493f74c6f4b3e062",
    "secrets-a": "zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f",
    "secrets-b": (
        "trufflesecurity/trufflehog:3.100.1@sha256:9c7a8325d43a4af2960d3f21d61a08981d8a1bf0542e007efa2e47097e386452"
    ),
    "platform": "bridgecrew/checkov:3.4.11@sha256:68da9ede242807850ab346b533dc1e4d2b00e15a9e6b4b595654d39c7f2e2566",
    "dockerfiles": "hadolint/hadolint:v2.12.0@sha256:30a8fd2e785ab6176eed53f74769e04f125afb2f74a6c52aef7d463583b6d45e",
}
TOOLS = tuple(IMAGES)
#: the public rule set of the code-pattern scanner, at one commit (2026-11-10); fetched by :func:`fetch_rules`
RULES_REPO = "https://github.com/semgrep/semgrep-rules"
RULES_COMMIT = "a5ad1714f00c9f7fde980cab0ea1d6dc6d414fd2"
RULE_DIRS = ("python/lang/security", "dockerfile/security", "bash/lang/security")
#: the digest of the files of :data:`RULE_DIRS` at :data:`RULES_COMMIT` (:func:`rules_digest`); the scanner reads a copy
#: that matches it, never the checkout
RULES_DIGEST = "84cd8c87f302b300f2fc04ba8ed8a6e2770dee870b5a486eb2b0d6ba515b96b6"
#: every tracked Dockerfile under ``trialbox/``, relative to it (the Makefile's HADOLINT_GATING and HADOLINT_REPORT);
#: :func:`tracked_dockerfiles` finds them and the test holds the two equal. The root ``Dockerfile`` and
#: ``.devcontainer/Dockerfile`` are the legacy tree, outside this scope
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
        ),
        "secrets-b": docker_run(
            IMAGES["secrets-b"], src, ["filesystem", "/src", "--no-verification", "--json", "--no-update"]
        ),
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
        ),
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
        ),
    }


def _loads(line: str) -> Any:
    try:
        return json.loads(line)
    except ValueError:
        return None


def _row(rule: Any, file: Any = "", line: Any = 0) -> dict[str, Any]:
    """A finding as kept: its rule, file and line, never the matched text."""
    return {"rule": str(rule or "?"), "file": str(file or ""), "line": int(line or 0)}


def parse(tool: str, text: str, log: str = "") -> tuple[list[dict[str, Any]], list[str]]:
    """(rows, errors) of one tool's report (``text``) and log (``log``), in memory: a row is (rule, file, line); the
    errors are the tool's own error fields, by kind and count and never its words. ``ValueError`` when ``text`` is not
    what the tool writes."""
    errors: list[str] = []
    if tool == "secrets-b":  # one JSON object per line, its own log lines among them (standard error too)
        docs = [json.loads(line) for line in text.splitlines() if line.strip()]
        docs += [d for d in map(_loads, log.splitlines()) if d is not None]
        docs = [d for d in docs if isinstance(d, dict)]
        rows = []
        for d in docs:
            if "DetectorName" in d:
                fs = ((d.get("SourceMetadata") or {}).get("Data") or {}).get("Filesystem") or {}
                rows.append(_row(d["DetectorName"], fs.get("file"), fs.get("line")))
        if not any(d.get("msg") == "finished scanning" for d in docs):  # silent when clean: only this line shows it ran
            errors.append("no completion line")
        if n := sum(d.get("level") == "error" for d in docs):
            errors.append(f"{n} log line(s) of level error")
        return rows, errors
    doc = json.loads(text)
    if tool == "code-patterns":
        rows = [_row(str(r["check_id"]).rsplit(".", 1)[-1], r.get("path"), (r.get("start") or {}).get("line"))
                for r in doc["results"]]  # fmt: skip
        if doc.get("errors"):
            errors.append(f"{len(doc['errors'])} scan error(s)")
    elif tool == "secrets-a":
        rows = [_row(r.get("RuleID"), r.get("File"), r.get("StartLine")) for r in doc]
    elif tool == "platform":
        reports = doc if isinstance(doc, list) else [doc]
        rows = [_row(c["check_id"], c.get("file_path"), (c.get("file_line_range") or [0])[0])
                for r in reports for c in r["results"]["failed_checks"]]  # fmt: skip
        if n := sum(int((r.get("summary") or {}).get("parsing_errors") or 0) for r in reports):
            errors.append(f"{n} parsing error(s)")
    elif tool == "dockerfiles":
        rows = [_row(r.get("code"), r.get("file"), r.get("line")) for r in doc]
    else:
        raise ValueError(f"unknown tool {tool!r}")
    return rows, errors


def count(tool: str, text: str) -> tuple[int, dict[str, int]]:
    """(findings, findings by rule) of one tool's JSON output; ``ValueError`` when it is not what the tool writes."""
    by = Counter(r["rule"] for r in parse(tool, text)[0])
    return sum(by.values()), dict(by)


def tracked_files(repo: Path) -> list[str]:
    """The files git tracks in ``repo``, relative to it."""
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True, text=True).stdout
    return [f for f in out.split("\0") if f]


def tracked_dockerfiles(repo: Path) -> list[str]:
    """Every tracked Dockerfile under ``trialbox/`` (``Dockerfile``, ``*.Dockerfile``, ``Dockerfile.*``, not a
    ``.dockerignore``), relative to ``trialbox/``."""
    pat = re.compile(r"trialbox/((?:.*/)?(?:Dockerfile|[^/]+\.Dockerfile|Dockerfile\.[^/]+))")
    found = (pat.fullmatch(f) for f in tracked_files(repo) if not f.endswith(".dockerignore"))
    return sorted(m.group(1) for m in found if m)


def snapshot(src: Path, dest: Path) -> Path:
    """Copy the tracked files of ``src`` into ``dest`` (outside the tree): the scanners read nothing else, so neither
    the rule checkout nor an earlier report is in what they scan."""
    for f in tracked_files(src):
        a, b = src / f, dest / f
        if a.is_dir() and not a.is_symlink():  # a submodule
            continue
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, b, follow_symlinks=False)
    return dest


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


def rules_digest(rules: Path) -> str:
    """One digest of the names and contents of the files of :data:`RULE_DIRS` under ``rules``."""
    h = hashlib.sha256()
    for d in RULE_DIRS:
        for p in sorted((rules / d).rglob("*")):
            if p.is_file():
                h.update(f"{p.relative_to(rules).as_posix()}\0".encode() + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def pinned(dest: Path, run: Runner = subprocess.run) -> Path:
    """A fresh copy, outside the tree, of the rule folders of the checkout in ``dest``: ``RuntimeError`` when it is not
    at :data:`RULES_COMMIT` or when the copy does not hash to :data:`RULES_DIGEST` (a rule edited in the checkout)."""
    head = run(["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if head != RULES_COMMIT:
        raise RuntimeError(f"the rule set in {dest} is at {head}, not the pinned {RULES_COMMIT}")
    copy = Path(tempfile.mkdtemp(prefix="rules-"))
    for d in RULE_DIRS:
        shutil.copytree(dest / d, copy / d, symlinks=True)
    if (got := rules_digest(copy)) != RULES_DIGEST:
        shutil.rmtree(copy, ignore_errors=True)
        raise RuntimeError(f"the rule files in {dest} hash to {got}, not the pinned {RULES_DIGEST}")
    return copy


def scan(
    src: Path,
    rules: Path,
    out: Path,
    run: Runner | None = None,
    *,
    baseline: dict[str, dict[str, int]] | None = None,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Run the five tools; write their reports, ``summary.md`` and ``index.json`` (with what fails) into ``out``; the
    record."""
    run = run or subprocess.run
    out.mkdir(parents=True, exist_ok=True)
    results: list[ToolResult] = []
    tree = Path(tempfile.mkdtemp(prefix="src-"))
    try:
        snapshot(src, tree)
        for tool, argv in commands(tree, rules).items():
            res = ToolResult(tool, IMAGES[tool], ran=False)
            results.append(res)
            try:
                got = run(argv, capture_output=True, text=True, check=False, timeout=3600)
            except (OSError, subprocess.SubprocessError) as exc:
                res.error = f"not run: {type(exc).__name__}"
                continue
            if got.returncode != 0:  # every tool is in report mode: only exit 0 is a run
                res.error = f"not run: exit {got.returncode}"
                continue
            try:  # the raw report is read here and dropped: only (rule, file, line) rows are kept
                rows, errors = parse(tool, got.stdout, got.stderr)
            except (ValueError, KeyError, TypeError, AttributeError):
                res.error = "not run: no report"
                continue
            if errors:
                res.error = f"not run: {'; '.join(errors)}"
                continue
            by = Counter(r["rule"] for r in rows)
            res.findings, res.by_rule, res.ran = len(rows), dict(by), True
            (out / f"{tool}.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        found = ignore_files(tree)
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    base = baseline if baseline is not None else load_baseline()
    record: dict[str, Any] = {"blocks_from": {k: v.isoformat() for k, v in BLOCKS_FROM.items()},
                              "rules_commit": RULES_COMMIT, "tools": [r.row() for r in results],
                              "ignore_files": found, "baseline": base}  # fmt: skip
    record["failures"] = failures(record, base, today or dt.date.today())
    (out / "index.json").write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(summary(record), encoding="utf-8")
    return record


def load_baseline(path: Path = BASELINE) -> dict[str, dict[str, int]]:
    """The baseline: ``{tool: {rule: count}}``; ``ValueError`` when it is anything else."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    counts = doc.get("counts") if isinstance(doc, dict) else None
    if not isinstance(counts, dict) or not set(counts) <= set(TOOLS):
        raise ValueError(f"{path.name}: 'counts' must map tools of {', '.join(TOOLS)} to counts by rule")
    for tool, by in counts.items():
        if not isinstance(by, dict) or not all(isinstance(k, str) and type(v) is int and v > 0 for k, v in by.items()):
            raise ValueError(f"{path.name}: {tool}: counts by rule must be positive whole numbers")
    return {str(t): {str(k): int(v) for k, v in by.items()} for t, by in counts.items()}


def summary(record: dict[str, Any]) -> str:
    lines = [
        "## Standing release gates (a count above its baseline fails; each tool's dates in BLOCKS_FROM)",
        "",
        "| Tool | Image | Findings | Baseline | By rule |",
        "| --- | --- | --- | --- | --- |",
    ]
    base = record.get("baseline") or {}
    for t in record["tools"]:
        rules = ", ".join(f"{k} {v}" for k, v in sorted(t["by_rule"].items(), key=lambda kv: (-kv[1], kv[0])))
        found = t["findings"] if t["ran"] else t["error"]
        lines.append(f"| {t['tool']} | `{t['image']}` | {found} | {sum(base.get(t['tool'], {}).values())} | "
                     f"{rules or '-'} |")  # fmt: skip
    if record["ignore_files"]:
        lines += ["", "Ignore files in the tree (each fails): " + ", ".join(record["ignore_files"])]
    if record.get("failures"):
        lines += ["", "**Fails:**", *(f"- {f}" for f in record["failures"])]
    return "\n".join(lines) + "\n"


def failures(record: dict[str, Any], baseline: dict[str, dict[str, int]], today: dt.date) -> list[str]:
    """What fails the release build: a tool not run, an ignore file, a count above its baseline, and every finding of
    a tool on or after its date in :data:`BLOCKS_FROM`."""
    out = [f"{t['tool']}: {t['error']}" for t in record["tools"] if not t["ran"]]
    for t in record["tools"]:
        if not t["ran"]:
            continue
        base = baseline.get(t["tool"], {})
        out += [f"{t['tool']}: {rule} {n}, above its baseline of {base.get(rule, 0)} (a new finding)"
                for rule, n in sorted(t["by_rule"].items()) if n > base.get(rule, 0)]  # fmt: skip
        since = BLOCKS_FROM.get(t["tool"])
        if since is not None and today >= since and t["findings"]:
            out.append(f"{t['tool']}: {t['findings']} finding(s); every finding fails from {since.isoformat()}")
    out += [f"ignore file in the tree: {f}" for f in record["ignore_files"]]
    return out
