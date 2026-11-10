"""gen_traceability: the traceability matrix of TB-PLAN-05 is generated from the plan's own tables, never typed twice.

    python tools/gen_traceability.py            # write docs/plan/25-traceability.csv from docs/plan/25-master-plan.md
    python tools/gen_traceability.py --check    # exit 1 when the CSV, the §5 "Plan" cells or the §3 totals are stale
    python tools/gen_traceability.py --write    # also rewrite the §5 "Plan" cells and the §3 totals table in the plan

Every run also checks the commitments register (T-641, REG-010): each promise sentence of the filed IRB amendments,
the hospital IT pack and the opt-out notice has a row in ``docs/validation/commitments.csv``, each row quotes its
source as it now reads, and a ``green`` row names code and a test that exist.

The plan (TB-PLAN-05 §7.4) names the rule: every work item carries a Trace cell (URS, RSK and TST ids); the
requirement tables carry an FS id per requirement; the test table carries the level per test. From those the script
derives one CSV row per (requirement, fs, risk, test, plan item) link, the "Plan" column of every requirement row and
the agent-session and review-hour totals per workstream. It also reports orphans: an id used but never defined, or
defined but never traced (independent review of 2026-11-09, PR-23 and PR-27).
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "plan" / "25-master-plan.md"
CSV = ROOT / "docs" / "plan" / "25-traceability.csv"
FIELDS = ["requirement", "fs", "risk", "test", "plan_item", "level", "status", "evidence"]
URS = re.compile(r"URS-[A-Z]+-\d+")
RSK = re.compile(r"RSK-\d+")
TST = re.compile(r"TST-[A-Z0-9]+-\d+")
WS = re.compile(r"WS-\d+\.\d+")
FS = re.compile(r"FS-\d+")
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*([SR])\b")
TOTALS_HEADER = "### Totals"


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


@dataclass
class Item:
    item: str
    trace: str
    gate: str
    sessions: float
    hours: float


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    urs_fs: dict[str, str] = field(default_factory=dict)  # URS id -> FS id
    urs_plan: dict[str, str] = field(default_factory=dict)  # URS id -> the "Plan" cell as written
    rsk: set[str] = field(default_factory=set)
    tst_level: dict[str, str] = field(default_factory=dict)
    engineer_hours: str = ""


def parse(text: str) -> Plan:
    plan = Plan()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        c = cells(line)
        head = c[0]
        if WS.fullmatch(head) and len(c) >= 8:
            size = c[5]
            sessions = sum(float(n) for n, kind in SIZE.findall(size) if kind == "S")
            hours = sum(float(n) for n, kind in SIZE.findall(size) if kind == "R")
            plan.items.append(Item(head, c[6], c[7], sessions, hours))
        elif URS.fullmatch(head) and len(c) >= 4:
            m = FS.search(c[2])
            plan.urs_fs[head] = m.group(0) if m else ""
            plan.urs_plan[head] = c[3]
        elif RSK.fullmatch(head):
            plan.rsk.add(head)
        elif TST.fullmatch(head) and len(c) >= 2:
            plan.tst_level[head] = c[1]
    return plan


def derive_urs_plan(plan: Plan) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {u: [] for u in plan.urs_fs}
    for it in plan.items:
        for u in URS.findall(it.trace):
            out.setdefault(u, []).append(it.item)
    return {u: sorted(set(v), key=ws_key) for u, v in out.items()}


def ws_key(ws: str) -> tuple[int, int]:
    a, b = ws[3:].split(".")
    return int(a), int(b)


def rows(plan: Plan) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for it in plan.items:
        reqs = URS.findall(it.trace) or ["-"]
        risks = RSK.findall(it.trace) or ["-"]
        tests = TST.findall(it.trace) or ["-"]
        for r in reqs:
            for k in risks:
                for t in tests:
                    key = (r, k, t, it.item)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(
                        {
                            "requirement": r,
                            "fs": plan.urs_fs.get(r, ""),
                            "risk": k,
                            "test": t,
                            "plan_item": it.item,
                            "level": plan.tst_level.get(t, "-"),
                            "status": "planned",
                            "evidence": f"gate: {it.gate}",
                        }
                    )
    return out


def orphans(plan: Plan) -> list[str]:
    used_urs = {u for it in plan.items for u in URS.findall(it.trace)}
    used_rsk = {k for it in plan.items for k in RSK.findall(it.trace)}
    used_tst = {t for it in plan.items for t in TST.findall(it.trace)}
    errs = []
    errs += [f"URS used but undefined: {u}" for u in sorted(used_urs - set(plan.urs_fs))]
    errs += [f"URS defined but traced by no item: {u}" for u in sorted(set(plan.urs_fs) - used_urs)]
    errs += [f"RSK used but undefined: {k}" for k in sorted(used_rsk - plan.rsk)]
    errs += [f"RSK defined but traced by no item: {k}" for k in sorted(plan.rsk - used_rsk)]
    errs += [f"TST used but undefined: {t}" for t in sorted(used_tst - set(plan.tst_level))]
    errs += [f"TST defined but traced by no item: {t}" for t in sorted(set(plan.tst_level) - used_tst)]
    errs += [f"URS without an FS id: {u}" for u, f in sorted(plan.urs_fs.items()) if not f]
    return errs


def totals(plan: Plan) -> list[tuple[str, float, float]]:
    per: dict[str, list[float]] = {}
    for it in plan.items:
        ws = it.item.split(".")[0]
        per.setdefault(ws, [0.0, 0.0])
        per[ws][0] += it.sessions
        per[ws][1] += it.hours
    return [(ws, v[0], v[1]) for ws, v in sorted(per.items())]


def fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else f"{n:g}"


def totals_table(plan: Plan, names: dict[str, str]) -> list[str]:
    lines = ["| Workstream | Agent sessions | Owner and reviewer hours |", "| --- | --- | --- |"]
    s_all = h_all = 0.0
    for ws, s, h in totals(plan):
        lines.append(f"| {ws} {names.get(ws, '')} | {fmt(s)} | {fmt(h)} |".replace("  |", " |"))
        s_all += s
        h_all += h
    hours = f"**{fmt(h_all)} owner and reviewer hours**{plan.engineer_hours}"
    lines.append(f"| **All** | **{fmt(s_all)} agent sessions** | {hours} |")
    return lines


def ws_names(text: str) -> dict[str, str]:
    """The workstream names from the '### WS-nn Name' headings."""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^### (WS-\d+) (.+)$", text, re.M)}


def rewrite(text: str, plan: Plan) -> str:
    """The §5 'Plan' cells from the Trace cells, and the §3 totals table from the Size cells."""
    derived = derive_urs_plan(plan)
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            c = cells(line)
            if URS.fullmatch(c[0]) and len(c) >= 4 and c[0] in derived:
                c[3] = ", ".join(derived[c[0]]) or "-"
                line = "| " + " | ".join(c) + " |"
        if line.strip() == TOTALS_HEADER:
            out.append(line)
            i += 1
            while i < len(lines) and not lines[i].startswith("|"):
                out.append(lines[i])
                i += 1
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            out.extend(totals_table(plan, ws_names(text)))
            continue
        out.append(line)
        i += 1
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------- commitments (T-641)
COMMITMENTS = ROOT / "docs" / "validation" / "commitments.csv"
COMMIT_FIELDS = [
    *("id", "source", "section", "quote", "promise", "status"),
    *("code", "test", "card", "correction", "finding"),
]
STATUSES = ("green", "amber", "red", "n/a")
# the promise text of each source: (file, first heading of the scope, the heading that ends it). Inside the scope a
# table row or a numbered list item is one promise unit; any other prose line is split into sentences.
PROMISE_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("docs/plan/sites/irb-amendment-cgmh.md", "### B.3 Content", "### B.5 Attachments"),
    ("docs/plan/sites/irb-amendment-japan.md", "### A.3 変更内容", "### A.5 添付"),
    ("docs/plan/sites/it-security-pack.md", "### A.1 What TrialBox is, in one paragraph", "## B. 日本語"),
    (
        "docs/plan/design/14-ethics-pack.md",
        "### 4.3 English",
        "## 5. Pilot validation protocol (summary for the committee)",
    ),
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])|(?<=。)")
TEST_REF = re.compile(r"^(?P<path>[\w./-]+\.py)::(?P<name>\w+)$")


def norm(s: str) -> str:
    """Markdown emphasis and code marks dropped, whitespace collapsed: the form a quote is matched in."""
    return re.sub(r"\s+", " ", s.replace("**", "").replace("*", "").replace("`", "")).strip()


def promise_units(text: str, start: str, end: str) -> list[str]:
    """The promise units between two headings. Table header rows, separators, headings and a line that is only a
    bold title are not promises."""
    lines = text.splitlines()
    try:
        a = next(i for i, ln in enumerate(lines) if ln.strip() == start)
    except StopIteration:
        return []
    b = next((i for i in range(a + 1, len(lines)) if lines[i].strip() == end), len(lines))
    scope = lines[a + 1 : b]
    units: list[str] = []
    for i, raw in enumerate(scope):
        ln = raw.strip()
        if ln.startswith(">"):
            ln = ln[1:].strip()
        if not ln or ln.startswith("#") or re.fullmatch(r"\*\*[^*]+\*\*", ln):
            continue
        if ln.startswith("|"):
            nxt = scope[i + 1].strip() if i + 1 < len(scope) else ""
            if re.fullmatch(r"\|[\s:|-]+\|", ln) or re.fullmatch(r"\|[\s:|-]+\|", nxt):
                continue  # a separator, or the header above one
            units.append(norm(" | ".join(cells(ln))))
        elif re.match(r"\d+\.\s", ln):
            units.append(norm(ln))
        else:
            units += [norm(s) for s in SENTENCE.split(ln) if norm(s)]
    return units


def commitment_errors(
    rows_: list[dict[str, str]], sources: tuple[tuple[str, str, str], ...] = PROMISE_SOURCES, root: Path = ROOT
) -> list[str]:
    """Problems with the register: a promise unit with no row, a row whose quote its source no longer holds, a status
    without the evidence it needs (green: code and a test that exist; amber: a card; red: a card and a correction)."""
    errs: list[str] = []
    seen: set[str] = set()
    texts: dict[str, str] = {}
    for r in rows_:
        rid, src, quote, status = r.get("id", ""), r.get("source", ""), norm(r.get("quote", "")), r.get("status", "")
        if not rid or rid in seen:
            errs.append(f"commitments: id missing or repeated: {rid!r}")
        seen.add(rid)
        if src not in texts:
            p = root / src
            texts[src] = norm(p.read_text(encoding="utf-8")) if p.is_file() else ""
        if not texts[src]:
            errs.append(f"commitments: {rid}: source {src!r} not found")
        elif not quote or quote not in texts[src]:
            errs.append(f"commitments: {rid}: the quote is not in {src} (the text changed: update the row)")
        if status not in STATUSES:
            errs.append(f"commitments: {rid}: status {status!r} is not one of {', '.join(STATUSES)}")
        if status == "green":
            if not r.get("code", "").strip() or not r.get("test", "").strip():
                errs.append(f"commitments: {rid}: green needs code and a test")
            for ref in filter(None, (t.strip() for t in r.get("test", "").split(";"))):
                m = TEST_REF.match(ref)
                f = root / m.group("path") if m else None
                body = f.read_text("utf-8") if m and f and f.is_file() else ""
                if not m or not re.search(rf"def {m.group('name')}\b", body):
                    errs.append(f"commitments: {rid}: test {ref!r} not found")
        if status in ("amber", "red") and not r.get("card", "").strip():
            errs.append(f"commitments: {rid}: {status} needs the card that finishes it")
        if status == "red" and not r.get("correction", "").strip():
            errs.append(f"commitments: {rid}: red needs the correction wording for the supplement")
    for src, start, end in sources:
        p = root / src
        units = promise_units(p.read_text(encoding="utf-8"), start, end) if p.is_file() else []
        if not units:
            errs.append(f"commitments: no promise text found in {src} between {start!r} and {end!r}")
        quotes = [norm(r.get("quote", "")) for r in rows_ if r.get("source") == src]
        for u in units:
            if not any(q and q in u for q in quotes):
                errs.append(f"commitments: a promise in {src} has no row: {u[:100]!r}")
    return errs


def tally(rows_: list[dict[str, str]]) -> list[tuple[str, int]]:
    return [(s, sum(r.get("status") == s for r in rows_)) for s in STATUSES]


def read_commitments(path: Path | None = None) -> tuple[list[dict[str, str]], list[str]]:
    path = path or COMMITMENTS
    if not path.is_file():
        return [], [f"{path} is missing"]
    with path.open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        head = list(rd.fieldnames or [])
        rows_ = list(rd)
    errs = [] if head == COMMIT_FIELDS else [f"commitments: header is {head}, expected {COMMIT_FIELDS}"]
    return rows_, errs


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    text = PLAN.read_text(encoding="utf-8")
    plan = parse(text)
    m = re.search(r"\*\*(\d+) agent sessions\*\* \| \*\*\d+(?:\.\d+)? owner and reviewer hours\*\*(.*?) \|", text)
    plan.engineer_hours = m.group(2) if m else ""
    errs = orphans(plan)
    commitments, cerrs = read_commitments()
    errs += cerrs + commitment_errors(commitments)
    new_csv = rows(plan)
    new_text = rewrite(text, plan)
    if "--write" in args:
        PLAN.write_text(new_text, encoding="utf-8")
        text = new_text
    elif new_text != text:
        errs.append("the §5 'Plan' cells or the §3 totals differ from the Trace and Size cells (run --write)")
    if "--check" in args:
        old = list(csv.DictReader(CSV.open(encoding="utf-8"))) if CSV.exists() else []
        if old != new_csv:
            errs.append(f"{CSV.relative_to(ROOT)} is stale (run without --check to regenerate)")
    else:
        with CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(new_csv)
    for e in errs:
        print(e)
    print(
        f"gen_traceability: {len(plan.items)} items, {len(plan.urs_fs)} requirements, {len(plan.rsk)} risks, "
        f"{len(plan.tst_level)} tests, {len(new_csv)} links; {len(commitments)} commitments "
        f"({', '.join(f'{n} {s}' for s, n in tally(commitments))}); "
        f"{'clean' if not errs else f'{len(errs)} problem(s)'}"
    )
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
