"""The ASVS Level 2 checklist of card V-3 (plan 8, V9): counts and a check that it has not rotted.

The checklist is ``docs/plan/measurements/asvs-l2-checklist-2026-11-17/checklist.json`` (one object per requirement)
with ``findings.json`` beside it; the page is ``docs/plan/measurements/asvs-l2-checklist-2026-11-17.md``.

    python -m tools.asvs_checklist --table    # print the page's count table from the json
    python -m tools.asvs_checklist --check    # exit 1 when the page and the json disagree, or evidence is gone

``--check`` holds: the page's count table equals the json's counts; every evidence ``file:line`` names a file of this
tree with at least that many lines; every named test is a ``def`` in its file; verdicts and bases use the page's
words; every finding a requirement names is in ``findings.json`` and every finding is named by a requirement; a
"meets" names a file and a line. Line numbers are for the commit the json names.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "docs" / "plan" / "measurements" / "asvs-l2-checklist-2026-11-17"
PAGE = FOLDER.with_suffix(".md")
VERDICTS = ("meets", "does not meet", "partly", "not applicable", "not determined", "not assessed")
BASES = ("shown", "hypothesis", "not_run")
SEVERITIES = ("High", "Medium", "Low")
CHAPTERS = tuple(f"V{i}" for i in range(1, 15))
START, END = "<!-- counts:start -->", "<!-- counts:end -->"


def load(folder: Path = FOLDER) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checklist = json.loads((folder / "checklist.json").read_text(encoding="utf-8"))
    findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
    return list(checklist["requirements"]), list(findings["findings"])


def counts(reqs: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    out: dict[str, Counter[str]] = {ch: Counter() for ch in CHAPTERS}
    for r in reqs:
        out[r["chapter"]][r["verdict"]] += 1
    return out


def table(reqs: list[dict[str, Any]]) -> str:
    """The count table of the page: one row per chapter, one column per verdict, and the total."""
    c = counts(reqs)
    lines = ["| Chapter | " + " | ".join(VERDICTS) + " | lines |", "|---|" + "---|" * (len(VERDICTS) + 1)]
    for ch in CHAPTERS:
        lines.append(f"| {ch} | " + " | ".join(str(c[ch][v]) for v in VERDICTS) + f" | {sum(c[ch].values())} |")
    total = Counter[str]()
    for ch in CHAPTERS:
        total.update(c[ch])
    lines.append("| all | " + " | ".join(str(total[v]) for v in VERDICTS) + f" | {sum(total.values())} |")
    return "\n".join(lines)


def _line_ok(root: Path, ref: str) -> str:
    path, _, num = ref.rpartition(":")
    if not path or not num.isdigit():
        return f"{ref}: not file:line"
    f = root / path
    if not f.is_file():
        return f"{ref}: no such file"
    n = len(f.read_text(encoding="utf-8").splitlines())
    return "" if 1 <= int(num) <= n else f"{ref}: the file has {n} lines"


def _test_ok(root: Path, ref: str) -> str:
    path, sep, name = ref.partition("::")
    f = root / path
    if not sep or not f.is_file():
        return f"{ref}: no such test file"
    if not re.search(rf"^def {re.escape(name)}\(", f.read_text(encoding="utf-8"), re.M):
        return f"{ref}: no such test"
    return ""


def problems(root: Path = ROOT, folder: Path = FOLDER, page: Path = PAGE) -> list[str]:
    reqs, findings = load(folder)
    out: list[str] = []
    ids = [r["id"] for r in reqs]
    out += [f"{i}: listed twice" for i, n in Counter(ids).items() if n > 1]
    named: set[str] = set()
    for r in reqs:
        rid = r["id"]
        if r["chapter"] not in CHAPTERS:
            out.append(f"{rid}: chapter {r['chapter']!r}")
        if r["verdict"] not in VERDICTS:
            out.append(f"{rid}: verdict {r['verdict']!r}")
        if r["basis"] not in BASES:
            out.append(f"{rid}: basis {r['basis']!r}")
        if r["verdict"] == "meets" and not (r["file"] and r["line"]):
            out.append(f"{rid}: 'meets' with no file and line")
        refs = ([f"{r['file']}:{r['line']}"] if r["file"] else []) + list(r["also"])
        out += [f"{rid}: {p}" for p in (_line_ok(root, x) for x in refs) if p]
        out += [f"{rid}: {p}" for p in (_test_ok(root, t) for t in r["test"]) if p]
        if r["basis"] == "shown" and not r["test"]:
            out.append(f"{rid}: 'shown' names no test")
        if r["finding"]:
            named.add(r["finding"])
    fids = {f["id"] for f in findings}
    out += [f"{i}: named by the checklist, not in findings.json" for i in sorted(named - fids)]
    out += [f"{i}: in findings.json, named by no requirement" for i in sorted(fids - named)]
    for f in findings:
        if f["severity"] not in SEVERITIES or f["basis"] not in BASES:
            out.append(f"{f['id']}: severity or basis")
        if not re.fullmatch(r"V3-\d\d", f["id"]):
            out.append(f"{f['id']}: an id is V3-nn")
        out += [f"{f['id']}: {p}" for p in [_line_ok(root, f["place"])] if p]
        if f["test"]:
            out += [f"{f['id']}: {p}" for p in [_test_ok(root, f["test"])] if p]
        if f["basis"] == "shown" and not f["test"]:
            out.append(f"{f['id']}: 'shown' names no test")
    text = page.read_text(encoding="utf-8")
    if START not in text or END not in text:
        out.append(f"{page.name}: no count table between {START} and {END}")
    else:
        got = text.split(START, 1)[1].split(END, 1)[0].strip()
        if got != table(reqs):
            out.append(f"{page.name}: the count table differs from checklist.json (python -m tools.asvs_checklist "
                       "--table prints the right one)")  # fmt: skip
        for fid in sorted(fids):
            if fid not in text:
                out.append(f"{page.name}: finding {fid} is not on the page")
        for rid in ids:
            if f"| {rid} |" not in text:
                out.append(f"{page.name}: requirement {rid} has no row on the page")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--table", action="store_true", help="print the count table")
    ap.add_argument("--check", action="store_true", help="check the page and the evidence")
    args = ap.parse_args(argv)
    if args.table:
        print(table(load()[0]))
    if args.check:
        found = problems()
        for p in found:
            print(f"asvs-checklist: {p}", file=sys.stderr)
        if found:
            return 1
        print(f"asvs-checklist: OK ({len(load()[0])} lines, {len(load()[1])} findings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
