"""The weekly report-only bandit run (10G-39, OT-1 of review 21; D-1338): no filter, ``--ignore-nosec``, SARIF out.

``python -m tools.bandit_weekly --out build/bandit-weekly`` runs bandit (from uv.lock, pinned with its hash) over
every Python file git tracks under trialbox/, tests included, with no severity or confidence filter and with
``--ignore-nosec``, so the lines that carry a ``# nosec`` are reported like any other. It writes:

* ``bandit.sarif``  SARIF 2.1.0, one result per finding (rule, level from bandit's severity, confidence, file and
  line; never the code excerpt, as tools/security_scan.py prints none);
* ``bandit.json``   bandit's own JSON without the code excerpts;
* ``summary.md``    the counts by severity, by severity and confidence, and by rule, and how many findings sit on a
  line with an inline suppression (each such line is in tools/inline_suppressions.yaml, held by ``make lint``).

It is a report: it exits 0 whatever bandit finds, and 2 only when bandit itself cannot run or read a file. The gate
on trains stays ``make security-scan`` (medium and up, tools/security_scan_ignores.yaml), unchanged. Bandit's own
``-f sarif`` needs two packages that are not in uv.lock; this module writes the SARIF from bandit's JSON instead.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools import inline_suppressions

ROOT = Path(__file__).resolve().parents[1]
SEVERITIES = ("HIGH", "MEDIUM", "LOW")
LEVEL = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


class BanditError(Exception):
    """Bandit could not run, or its output was not what this module reads."""


def bandit_command(files: Sequence[str]) -> list[str]:
    """No ``-l``/``-i`` (every severity and confidence), ``--ignore-nosec``, JSON on stdout."""
    return [sys.executable, "-m", "bandit", "-q", "--ignore-nosec", "-f", "json", *files]


def run_bandit(root: Path, files: Sequence[str]) -> dict[str, Any]:
    if not files:
        return {"results": [], "errors": []}
    try:
        proc = subprocess.run(bandit_command(files), cwd=root, capture_output=True, text=True, check=False,
                              timeout=1800)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BanditError(f"bandit did not run: {exc}") from exc
    try:
        doc: dict[str, Any] = json.loads(proc.stdout)
        if not isinstance(doc["results"], list) or not isinstance(doc["errors"], list):
            raise TypeError("results and errors must be lists")
    except (ValueError, KeyError, TypeError) as exc:
        raise BanditError(f"bandit failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}") from exc
    if doc["errors"]:
        raise BanditError(
            "bandit could not read: " + "; ".join(f"{e.get('filename')}: {e.get('reason')}" for e in doc["errors"])
        )
    return doc


def _rel(root: Path, name: str) -> str:
    return os.path.relpath(os.path.join(root, name), root).replace(os.sep, "/")


def strip_code(doc: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Bandit's JSON with every code excerpt removed and paths relative to ``root``."""
    results = [{k: v for k, v in r.items() if k != "code"} | {"filename": _rel(root, r["filename"])}
               for r in doc["results"]]  # fmt: skip
    return {"generated_at": doc.get("generated_at"), "results": results, "errors": list(doc["errors"])}


def to_sarif(results: Sequence[Mapping[str, Any]], version: str, ledgered: set[tuple[str, int]]) -> dict[str, Any]:
    """SARIF 2.1.0: one run, one rule per bandit test id, one result per finding; ``ledgered`` (file, line) marks a
    finding on a line that carries an inline suppression (``make lint`` holds every such line to the ledger)."""
    rules: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for r in sorted(results, key=lambda r: (r["filename"], int(r["line_number"]), r["test_id"])):
        rid = str(r["test_id"])
        rules.setdefault(
            rid,
            {
                "id": rid,
                "name": str(r.get("test_name") or rid),
                "helpUri": str(r.get("more_info") or ""),
                "properties": {"tags": ["security"]},
            },
        )
        sev, conf = str(r["issue_severity"]).upper(), str(r["issue_confidence"]).upper()
        cwe = r.get("issue_cwe") or {}
        props: dict[str, Any] = {"issue_severity": sev, "issue_confidence": conf}
        if cwe.get("id"):
            props["cwe"] = f"CWE-{cwe['id']}"
        props["on_inline_suppression"] = (r["filename"], int(r["line_number"])) in ledgered
        region: dict[str, Any] = {"startLine": int(r["line_number"])}
        if r.get("col_offset") is not None:
            region["startColumn"] = int(r["col_offset"]) + 1
        out.append(
            {
                "ruleId": rid,
                "level": LEVEL.get(sev, "note"),
                "message": {"text": str(r.get("issue_text") or rid)},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": r["filename"], "uriBaseId": "TRIALBOX"},
                            "region": region,
                        }
                    }
                ],
                "properties": props,
            }
        )
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Bandit",
                        "version": version,
                        "informationUri": "https://github.com/PyCQA/bandit",
                        "rules": [rules[k] for k in sorted(rules)],
                    }
                },
                "originalUriBaseIds": {"TRIALBOX": {"uri": "trialbox/", "description": {"text": "trialbox/"}}},
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "commandLine": "bandit -q --ignore-nosec -f json <every tracked .py file>",
                    }
                ],
                "results": out,
            }
        ],
    }


def summary(results: Sequence[Mapping[str, Any]], version: str, ledgered: set[tuple[str, int]]) -> str:
    by_sev = Counter(str(r["issue_severity"]).upper() for r in results)
    by_pair = Counter((str(r["issue_severity"]).upper(), str(r["issue_confidence"]).upper()) for r in results)
    by_rule = Counter(str(r["test_id"]) for r in results)
    on_ledger = sum(1 for r in results if (r["filename"], int(r["line_number"])) in ledgered)
    lines = [
        f"# Bandit weekly (report only): {len(results)} findings",
        "",
        f"Bandit {version}, every tracked `.py` under trialbox/, no severity or confidence filter, `--ignore-nosec`.",
        f"{on_ledger} findings are on a line with an inline suppression (each in tools/inline_suppressions.yaml).",
        "This run gates nothing; the gate is `make security-scan`.",
        "",
        "| Severity | Findings | High confidence | Medium confidence | Low confidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in SEVERITIES:
        hi, med, lo = (by_pair[(s, c)] for c in SEVERITIES)
        lines.append(f"| {s} | {by_sev[s]} | {hi} | {med} | {lo} |")
    lines += ["", "| Rule | Findings |", "| --- | --- |"]
    lines += [f"| {k} | {n} |" for k, n in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0]))]
    return "\n".join(lines) + "\n"


def bandit_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("bandit")
    except PackageNotFoundError:
        return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bandit_weekly", description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "bandit-weekly", help="the report folder")
    ap.add_argument("--root", type=Path, default=ROOT, help="the folder to scan (default: trialbox/)")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    try:
        files = inline_suppressions.tracked_python(root)
        doc = strip_code(run_bandit(root, files), root)
        ledgered = {(s.path, s.line) for s in inline_suppressions.scan(root, files)}
    except (BanditError, inline_suppressions.LedgerError) as exc:
        print(f"bandit-weekly: ERROR {exc}", file=sys.stderr)
        return 2
    version = bandit_version()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "bandit.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    sarif = to_sarif(doc["results"], version, ledgered)
    (a.out / "bandit.sarif").write_text(json.dumps(sarif, indent=1) + "\n", encoding="utf-8")
    text = summary(doc["results"], version, ledgered)
    (a.out / "summary.md").write_text(text, encoding="utf-8")
    by_sev = Counter(str(r["issue_severity"]).upper() for r in doc["results"])
    print(
        f"bandit-weekly: {len(doc['results'])} findings in {len(files)} files "
        f"(HIGH {by_sev['HIGH']}, MEDIUM {by_sev['MEDIUM']}, LOW {by_sev['LOW']}); report only; written to {a.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
