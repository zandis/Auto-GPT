"""Secret scanning and a static security scan (T-654; deep review ENG-010, ENG-011): CI job ``security``.

``python -m tools.security_scan secrets`` runs detect-secrets over every file git tracks under trialbox/.
``python -m tools.security_scan sast`` runs bandit over the Python code that ships or runs on a box.
``python -m tools.security_scan ignores`` prints the reviewed findings of ``tools/security_scan_ignores.yaml``.

Both scanners come from uv.lock (the ``dev`` extra), pinned exactly. A scan exits 1 when it finds anything the
ignore file does not accept, and 2 when the scanner itself fails. It prints the file, the line and the rule, never the
matched text: detect-secrets reports only a hash of a secret, and bandit's code excerpt is not printed.

Rule tuning (each choice is here so that the job passes on master without hiding a class of real finding):

* secrets: the two entropy plugins and the keyword plugin are off. On master they gave 32,129 findings, every one a
  sha256 digest, a content hash of a golden file or synthetic patient, or a field name such as ``password_env``.
  The plugins for real key formats (private keys, cloud and service tokens, basic-auth URLs) stay on.
* sast: bandit reports medium and high severity at medium or high confidence. Low severity (assert, subprocess
  import, random) and low confidence (SQL text guesses) are what ruff's ``S`` rules cover in the lint job. tests/
  is not scanned by bandit (fake credentials, asserts and temporary folders are what tests do); the secret scan
  still reads it. Generated contracts are left out, as ruff leaves them out.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
IGNORES = ROOT / "tools" / "security_scan_ignores.yaml"

SECRET_PLUGINS_OFF = ("HexHighEntropyString", "Base64HighEntropyString", "KeywordDetector")
SAST_PATHS = ("libs", "services", "tools", "deploy", "eval")
SAST_EXCLUDE = ("libs/tb_contracts/generated",)
SCANS = ("secrets", "sast")
MIN_REASON = 10


class ScanError(Exception):
    """The scanner could not run, or its output was not what this tool reads."""


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    line: int


@dataclass(frozen=True)
class Ignore:
    path: str
    rule: str
    count: int
    reason: str


def load_ignores(path: Path, scan: str) -> list[Ignore]:
    """The accepted findings of one scan; refuses an entry without a path, a rule, a count of 1 or more, or a reason."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    rows = (data or {}).get(scan) or []
    out: list[Ignore] = []
    seen: set[tuple[str, str]] = set()
    for i, row in enumerate(rows):
        where = f"{path.name}: {scan}[{i}]"
        if not isinstance(row, dict):
            raise ScanError(f"{where}: not a mapping")
        p, rule, count, reason = row.get("path"), row.get("rule"), row.get("count"), row.get("reason")
        if not isinstance(p, str) or not p or not isinstance(rule, str) or not rule:
            raise ScanError(f"{where}: needs a path and a rule")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ScanError(f"{where}: count must be a whole number of 1 or more")
        if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON:
            raise ScanError(f"{where}: every ignore needs a reason")
        if (p, rule) in seen:
            raise ScanError(f"{where}: {p} {rule} is listed twice")
        seen.add((p, rule))
        out.append(Ignore(p, rule, count, reason.strip()))
    return out


def judge(findings: Iterable[Finding], ignores: Sequence[Ignore]) -> tuple[list[str], list[str]]:
    """(failures, notes): a (file, rule) with more findings than its ignore accepts fails; an ignore that accepts
    more than is found is a note (the code got better; lower the count)."""
    by_key: dict[tuple[str, str], list[int]] = {}
    for f in findings:
        by_key.setdefault((f.path, f.rule), []).append(f.line)
    allowed = {(i.path, i.rule): i.count for i in ignores}
    failures: list[str] = []
    for (path, rule), lines in sorted(by_key.items()):
        n_ok = allowed.get((path, rule), 0)
        if len(lines) > n_ok:
            at = ", ".join(str(n) for n in sorted(lines))
            failures.append(f"{path}: {rule}: {len(lines)} found, {n_ok} accepted (lines {at})")
    notes = [
        f"{i.path}: {i.rule}: the ignore accepts {i.count}, {len(by_key.get((i.path, i.rule), []))} found"
        for i in ignores
        if len(by_key.get((i.path, i.rule), [])) < i.count
    ]
    return failures, notes


def tracked_files(root: Path) -> list[str]:
    """The files git tracks under ``root`` (relative to it); every file below it when ``root`` is not in a repo."""
    proc = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=False, timeout=120)
    names = [n for n in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if n] if proc.returncode == 0 else []
    if not names:
        names = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    return sorted(n for n in names if (root / n).is_file() and not (root / n).is_symlink())


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScanError(f"{cmd[2]} did not run: {exc}") from exc


def scan_secrets(root: Path, files: Sequence[str] | None = None) -> list[Finding]:
    """detect-secrets over ``files`` (default: the tracked files), with the plugins of SECRET_PLUGINS_OFF off."""
    names = list(files) if files is not None else tracked_files(root)
    if not names:
        return []
    off = [a for p in SECRET_PLUGINS_OFF for a in ("--disable-plugin", p)]
    proc = _run([sys.executable, "-m", "detect_secrets", "scan", *off, *names], root)
    try:
        doc: dict[str, Any] = json.loads(proc.stdout)
        results: dict[str, list[dict[str, Any]]] = doc["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ScanError(f"detect-secrets failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}") from exc
    return [Finding(path, str(r["type"]), int(r["line_number"])) for path, rows in results.items() for r in rows]


def scan_sast(root: Path, paths: Sequence[str] = SAST_PATHS) -> list[Finding]:
    """bandit, medium severity and confidence and up, over ``paths`` that exist under ``root``."""
    targets = [p for p in paths if (root / p).exists()]
    if not targets:
        return []
    exclude = ",".join(str(root / e) for e in SAST_EXCLUDE)
    cmd = [sys.executable, "-m", "bandit", "-q", "-r", *targets, "-x", exclude, "-ll", "-ii", "-f", "json"]
    proc = _run(cmd, root)
    try:
        doc: dict[str, Any] = json.loads(proc.stdout)
        results: list[dict[str, Any]] = doc["results"]
        errors: list[dict[str, Any]] = doc["errors"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ScanError(f"bandit failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}") from exc
    if errors:
        raise ScanError(
            "bandit could not read: " + "; ".join(f"{e.get('filename')}: {e.get('reason')}" for e in errors)
        )
    out = []
    for r in results:
        path = os.path.relpath(os.path.join(root, r["filename"]), root)
        out.append(Finding(path, str(r["test_id"]), int(r["line_number"])))
    return out


def ignores_table(path: Path) -> str:
    """The ignore file as a Markdown table (for a pull-request body)."""
    lines = ["| Scan | File | Rule | Count | Reason |", "| --- | --- | --- | --- | --- |"]
    for scan in SCANS:
        for i in load_ignores(path, scan):
            lines.append(f"| {scan} | `{i.path}` | {i.rule} | {i.count} | {i.reason} |")
    return "\n".join(lines)


def run(scan: str, root: Path, ignores_path: Path) -> int:
    ignores = load_ignores(ignores_path, scan)
    findings = scan_secrets(root) if scan == "secrets" else scan_sast(root)
    failures, notes = judge(findings, ignores)
    allowed = {(i.path, i.rule): i.count for i in ignores}
    per_key = Counter((f.path, f.rule) for f in findings)
    accepted = sum(min(n, allowed.get(k, 0)) for k, n in per_key.items())
    for n in notes:
        print(f"note: {n}")
    for f in failures:
        print(f"FAIL {f}")
    counts = Counter(f.rule for f in findings)
    print(
        f"{scan}: {len(findings)} findings ({dict(sorted(counts.items()))}); "
        f"{accepted} in reviewed ignores; {len(failures)} file/rule pairs over their ignore"
    )
    if failures:
        print(f"{scan}: FAIL. Remove the finding, or add it to {ignores_path.name} with a reason.")
        return 1
    print(f"{scan}: PASS")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="security_scan", description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("scan", choices=[*SCANS, "ignores"])
    ap.add_argument("--root", type=Path, default=ROOT, help="the folder to scan (default: trialbox/)")
    ap.add_argument("--ignores", type=Path, default=IGNORES, help="the reviewed findings file")
    a = ap.parse_args(argv)
    try:
        if a.scan == "ignores":
            print(ignores_table(a.ignores))
            return 0
        return run(a.scan, a.root.resolve(), a.ignores)
    except ScanError as exc:
        print(f"{a.scan}: ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
