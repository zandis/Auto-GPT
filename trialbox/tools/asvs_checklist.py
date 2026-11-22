"""The ASVS Level 2 checklist of card V-3 (plan 8, V9): the page's generated blocks and a check that nothing rotted.

The checklist is ``docs/plan/measurements/asvs-l2-checklist-2026-11-17/checklist.json`` (one object per requirement)
with ``findings.json`` beside it; the page is ``docs/plan/measurements/asvs-l2-checklist-2026-11-17.md``.

    python -m tools.asvs_checklist --table    # print the count table from the json
    python -m tools.asvs_checklist --write    # write the page's generated blocks from the json
    python -m tools.asvs_checklist --check    # exit 1 when the page and the json disagree, or evidence is gone

The page holds four generated blocks between ``<!-- name:start -->`` and ``<!-- name:end -->``: ``counts`` (per
chapter and verdict), ``summary`` (V2, V3 and V4 in full, the findings by severity), ``findings`` (the findings table)
and ``rows`` (the table of every line). ``--check`` holds: each block equals what the json gives, whole; every
evidence ``file:line`` names a file of this tree with at least that many lines; every named test is a ``def`` in its
file; verdicts and bases use the page's words; every finding a requirement names is in ``findings.json`` and every
finding is named by a requirement; a "meets" names a file and a line; a "shown" names a test. Line numbers are for
the commit the json names.
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
NAMES = {"V2": "Authentication", "V3": "Session management", "V4": "Access control"}
BLOCKS = ("counts", "summary", "findings", "rows")
ROWS_HEAD = "| ASVS | Lvl | Requirement (paraphrase) | Verdict | Basis | Evidence | Finding |"


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
    """The count table: one row per chapter, one column per verdict, and the total."""
    c = counts(reqs)
    lines = ["| Chapter | " + " | ".join(VERDICTS) + " | lines |", "|---|" + "---|" * (len(VERDICTS) + 1)]
    for ch in CHAPTERS:
        lines.append(f"| {ch} | " + " | ".join(str(c[ch][v]) for v in VERDICTS) + f" | {sum(c[ch].values())} |")
    total = Counter[str]()
    for ch in CHAPTERS:
        total.update(c[ch])
    lines.append("| all | " + " | ".join(str(total[v]) for v in VERDICTS) + f" | {sum(total.values())} |")
    return "\n".join(lines)


def summary(reqs: list[dict[str, Any]], findings: list[dict[str, Any]]) -> str:
    """The counts the verdict rests on: V2, V3 and V4 in full, and the findings by severity."""
    out = []
    for ch in ("V2", "V3", "V4"):
        rs = [r for r in reqs if r["chapter"] == ch]
        c = Counter(r["verdict"] for r in rs)
        parts = [f"{c['meets']} meets"]
        for v in ("does not meet", "partly"):
            ids = ", ".join(r["id"] for r in rs if r["verdict"] == v)
            parts.append(f"{c[v]} {v}" + (f" ({ids})" if ids else ""))
        parts += [f"{c['not applicable']} not applicable", f"{c['not determined']} not determined"]
        shown = sum(1 for r in rs if r["basis"] == "shown")
        out.append(f"- **{ch} {NAMES[ch]} ({len(rs)} lines):** " + ", ".join(parts)
                   + f"; {shown} of the {len(rs)} lines shown by a test that ran.")  # fmt: skip
    sev = Counter(f["severity"] for f in findings)
    shown_f = sum(1 for f in findings if f["basis"] == "shown")
    out.append(f"- **Findings:** {len(findings)}: " + ", ".join(f"{sev[s]} {s}" for s in SEVERITIES)
               + f"; {shown_f} shown by a test.")  # fmt: skip
    return "\n".join(out)


def findings_table(findings: list[dict[str, Any]]) -> str:
    lines = [
        "| Id | ASVS | Place | Expected | What happened | Severity | Lane | Basis | Full review |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in findings:
        test = ""
        if f["test"]:
            mark = " (xfail)" if f["test"].startswith("tests/console/test_asvs") else ""
            test = f" Test: `{f['test'].split('::')[1]}`{mark}."
        tail = f"{f['severity']} | {f['owner']} | {f['basis']} | {f['full_review']} |"
        lines.append(f"| {f['id']} | {f['asvs']} | `{f['place']}` | {f['expected']} | **{f['claim']}** "
                     f"{f['happened']}{test} | {tail}")  # fmt: skip
    return "\n".join(lines)


def rows(reqs: list[dict[str, Any]]) -> str:
    """The table of every line, one table per chapter."""
    out: list[str] = []
    chapter = None
    for r in reqs:
        if r["chapter"] != chapter:
            chapter = r["chapter"]
            out += [f"#### {chapter}", "", ROWS_HEAD, "|---|---|---|---|---|---|---|"]
        ev = ([f"`{r['file']}:{r['line']}`"] if r["file"] else []) + [f"`{a}`" for a in r["also"]]
        ev += [f"`{t.split('::')[1]}`" for t in r["test"]]
        note = r["note"] + (f" Delegated: {r['delegate']}." if r["delegate"] else "")
        note += " **Id to be checked.**" if r["id_check"] else ""
        text = r["requirement"] + (f" *{note.strip()}*" if note.strip() else "")
        out.append(f"| {r['id']} | {r['level']} | {text} | **{r['verdict']}** | {r['basis']} | "
                   f"{'; '.join(ev) or '-'} | {r['finding'] or ''} |")  # fmt: skip
        nxt = reqs.index(r) + 1
        if nxt == len(reqs) or reqs[nxt]["chapter"] != chapter:
            out.append("")
    return "\n".join(out).strip()


def blocks(reqs: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, str]:
    return {"counts": table(reqs), "summary": summary(reqs, findings), "findings": findings_table(findings),
            "rows": rows(reqs)}  # fmt: skip


def _marks(name: str) -> tuple[str, str]:
    return f"<!-- {name}:start -->", f"<!-- {name}:end -->"


def write(page: Path = PAGE, folder: Path = FOLDER) -> None:
    """Fill the page's generated blocks from the json (the markers must be on the page)."""
    reqs, findings = load(folder)
    text = page.read_text(encoding="utf-8")
    for name, body in blocks(reqs, findings).items():
        a, b = _marks(name)
        head, rest = text.split(a, 1)
        text = head + a + "\n" + body + "\n" + b + rest.split(b, 1)[1]
    page.write_text(text, encoding="utf-8")


def _line_ok(root: Path, ref: str) -> str:
    path, _, num = ref.rpartition(":")
    if not path or not num.isdigit():
        return f"{ref}: not file:line"
    if Path(path).is_absolute():
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
    for name, body in blocks(reqs, findings).items():
        a, b = _marks(name)
        if a not in text or b not in text:
            out.append(f"{page.name}: no {name} block between {a} and {b}")
        elif text.split(a, 1)[1].split(b, 1)[0].strip() != body.strip():
            out.append(f"{page.name}: the {name} block differs from the json (--write writes it)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--table", action="store_true", help="print the count table")
    ap.add_argument("--write", action="store_true", help="write the page's generated blocks from the json")
    ap.add_argument("--check", action="store_true", help="check the page and the evidence")
    args = ap.parse_args(argv)
    if args.table:
        print(table(load()[0]))
    if args.write:
        write()
    if args.check:
        found = problems()
        for p in found:
            print(f"asvs-checklist: {p}", file=sys.stderr)
        if found:
            return 1
        reqs, findings = load()
        print(f"asvs-checklist: OK ({len(reqs)} lines, {len(findings)} findings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
