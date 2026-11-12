"""gen_traceability: the traceability matrix of TB-PLAN-05 is generated from the plan's own tables, never typed twice.

    python tools/gen_traceability.py            # write docs/plan/25-traceability.csv from docs/plan/25-master-plan.md
    python tools/gen_traceability.py --check    # print what is stale as warnings; exit 0 (CI job `trace`)
    python tools/gen_traceability.py --strict   # as --check, but exit 1 when anything is stale
    python tools/gen_traceability.py --write    # also rewrite the §5 "Plan" cells and the §3 totals table in the plan
    python tools/gen_traceability.py --records  # print the record inventory section of a release record (T-643)

D-311: the matrix is a planning aid, not a merge gate, so ``--check`` only warns. The commitments-register check of
T-641 was removed; the register is archived in ``docs/plan/sites/archive/``.

The plan (TB-PLAN-05 §7.4) names the rule: every work item carries a Trace cell (URS, RSK and TST ids); the
requirement tables carry an FS id per requirement; the test table carries the level per test. From those the script
derives one CSV row per (requirement, fs, risk, test, plan item) link, the "Plan" column of every requirement row and
the agent-session and review-hour totals per workstream. It also reports orphans: an id used but never defined, or
defined but never traced (independent review of 2026-11-09, PR-23 and PR-27).

One more check (card T-643, REG-022, D-363): every table a store module creates (``CREATE TABLE`` in ``services/`` and
``libs/``) has a row in the store map of ``docs/validation/record-inventory.md``, and every row there still names a
table its module creates. ``--records`` prints the inventory's records table for the release record.
"""

from __future__ import annotations

import csv
import hashlib
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
INVENTORY = ROOT / "docs" / "validation" / "record-inventory.md"
STORE_DIRS = ("services", "libs")
CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)", re.I)
MAP_ROW = re.compile(r"^\| `([^`]+\.py)` \| ([^|]+) \| ([RO]-\d{2}) \|$", re.M)
ID_ROW = re.compile(r"^\| ([RO]-\d{2}) \| (.+) \|$", re.M)


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


def store_tables(root: Path = ROOT) -> dict[str, set[str]]:
    """``{module path: table names}`` for every non-test module under ``services/`` and ``libs/`` that creates one."""
    out: dict[str, set[str]] = {}
    for d in STORE_DIRS:
        for p in sorted((root / d).rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            if "/tests/" in rel or "/generated/" in rel or p.name.startswith("test_"):
                continue
            names = set(CREATE.findall(p.read_text(encoding="utf-8")))
            if names:
                out[rel] = names
    return out


def inventory_ids(text: str) -> dict[str, list[str]]:
    """``{R-nn or O-nn: the cells of its row}`` from §2 and §3 of the inventory."""
    return {m.group(1): cells(m.group(0))[1:] for m in ID_ROW.finditer(text)}


def inventory_map(text: str) -> list[tuple[str, set[str] | None, str]]:
    """The store map: ``(module, tables or None for a file store, id)`` per row."""
    out: list[tuple[str, set[str] | None, str]] = []
    for module, tables, rid in MAP_ROW.findall(text):
        names = None if tables.strip().startswith("files:") else set(re.findall(r"`([^`]+)`", tables))
        out.append((module, names, rid))
    return out


def inventory_gaps(text: str, tables: dict[str, set[str]], root: Path = ROOT) -> list[str]:
    """What the record inventory misses or names wrongly, one line each; empty when it matches the code."""
    errs: list[str] = []
    ids = inventory_ids(text)
    mapped: dict[tuple[str, str], str] = {}
    used: set[str] = set()
    for module, names, rid in inventory_map(text):
        used.add(rid)
        if rid not in ids:
            errs.append(f"record inventory: {module} maps to {rid}, which has no row")
        if not (root / module).is_file():
            errs.append(f"record inventory: {module} does not exist")
        for t in sorted(names or ()):
            if (module, t) in mapped:
                errs.append(f"record inventory: {module} table {t} is mapped twice")
            mapped[(module, t)] = rid
            if t not in tables.get(module, set()):
                errs.append(f"record inventory: {module} no longer creates table {t}")
    for module, names in sorted(tables.items()):
        for t in sorted(names - {t for (m, t) in mapped if m == module}):
            errs.append(f"record inventory: {module} creates table {t}, which has no row in the store map")
    for rid in sorted(set(ids) - used):
        errs.append(f"record inventory: {rid} has no row in the store map")
    return errs


def records_section(text: str, gaps: list[str]) -> str:
    """The record inventory section of a release record (``release-records/README.md`` item 9)."""
    ids = inventory_ids(text)
    recs = {k: v for k, v in ids.items() if k.startswith("R-")}
    by_class: dict[str, int] = {}
    for row in recs.values():
        by_class[row[1]] = by_class.get(row[1], 0) + 1
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    classes = ", ".join(f"{k} {n}" for k, n in sorted(by_class.items()))
    out = [
        "## Record inventory",
        "",
        f"`docs/validation/record-inventory.md` (sha256 {digest}): {len(recs)} records ({classes}), "
        f"{len(ids) - len(recs)} other stores; store map: {'complete' if not gaps else f'{len(gaps)} problem(s)'}.",
        "",
        "| Id | Record | Class | Keeper | Retention |",
        "| --- | --- | --- | --- | --- |",
    ]
    out += [f"| {k} | {v[0]} | {v[1]} | {v[3]} | {v[4]} |" for k, v in recs.items()]
    out += [f"- {g}" for g in gaps]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    inventory = INVENTORY.read_text(encoding="utf-8") if INVENTORY.exists() else ""
    gaps = inventory_gaps(inventory, store_tables()) if inventory else [f"{INVENTORY.name} is missing"]
    if "--records" in args:
        print(records_section(inventory, gaps), end="")
        return 1 if gaps else 0
    text = PLAN.read_text(encoding="utf-8")
    plan = parse(text)
    m = re.search(r"\*\*(\d+) agent sessions\*\* \| \*\*\d+(?:\.\d+)? owner and reviewer hours\*\*(.*?) \|", text)
    plan.engineer_hours = m.group(2) if m else ""
    errs = orphans(plan) + gaps
    new_csv = rows(plan)
    new_text = rewrite(text, plan)
    if "--write" in args:
        PLAN.write_text(new_text, encoding="utf-8")
        text = new_text
    elif new_text != text:
        errs.append("the §5 'Plan' cells or the §3 totals differ from the Trace and Size cells (run --write)")
    if "--check" in args or "--strict" in args:
        old = list(csv.DictReader(CSV.open(encoding="utf-8"))) if CSV.exists() else []
        if old != new_csv:
            errs.append(f"{CSV.relative_to(ROOT)} is stale (run without --check to regenerate)")
    else:
        with CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(new_csv)
    strict = "--strict" in args
    for e in errs:
        print(e if strict else f"warning: {e}")
    print(
        f"gen_traceability: {len(plan.items)} items, {len(plan.urs_fs)} requirements, {len(plan.rsk)} risks, "
        f"{len(plan.tst_level)} tests, {len(new_csv)} links; "
        f"{'clean' if not errs else f'{len(errs)} problem(s)'}"
    )
    return 1 if errs and strict else 0


if __name__ == "__main__":
    sys.exit(main())
