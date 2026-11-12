#!/usr/bin/env python3
"""Regenerate the TB-DS-04 §6.2 requirements-to-test matrix from TB-DS-01.

Usage: python3 gen_trace.py [DESIGN_DIR] [--write] [--counts] [--annex-b]

--counts prints the build-tag counts of TB-DS-01 §3 (the TB-DS-20 §1 table) and exits.
--annex-b regenerates TB-DS-02 Annex B (requirement-level trace) instead of the
TB-DS-04 matrix: one row per SRS requirement, build tag from the SRS Pri cell,
containers / decisions / quality scenarios kept for rows already in the annex,
inherited from the root row for a split row (letter suffix) or its sibling, else
the most common entry for the ID prefix (the §10.3 area rule). With --write it
replaces the annex table and its header line.

Keeps the Test levels and Suite of every ID already in the matrix; adds a row
for each new SRS ID (levels and suite suggested from the most common values of
the same ID prefix, else TS-<AREA>); drops rows whose ID no longer exists in the
SRS (listed on stdout); recomputes the §6.3 count line. Without --write it only
prints what would change. Standard library only.
"""
import re, sys, collections, pathlib

ROW_ID = re.compile(r"^(FR|NFR)-[A-Z0-9]+-\d+[a-z]?$|^(DR|IR)-\d+[a-z]?$|^AM-\d+$")
DEFAULT_SUITE = {"FR-PLAT": "TS-PLAT", "FR-SYN": "TS-SYN"}
DEFAULT_LEVELS = {"FR-PLAT": "U I B", "FR-SYN": "U I"}
GROUP_TITLES = {  # used only for prefixes that have no heading in TB-DS-04 yet
    "FR-PLAT": "Platform functions", "FR-SYN": "Synthetic hospital",
}

def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]

def prefix(rid):
    if rid.startswith(("DR-", "IR-")):
        return rid.split("-")[0]
    if rid.startswith("AM-"):
        return "FR-AUTH"
    return "-".join(rid.split("-")[:2])

TAG = re.compile(r"^\**(S[0-5]|H|L)\b")

def pri_tag(raw, row=()):
    m = TAG.match(raw.strip())
    if m:
        return m.group(1)
    for c in row:  # misaligned row: take the first cell that looks like a tag
        m = TAG.match(c.strip())
        if m:
            return m.group(1)
    return raw.split()[0] if raw.strip() else ""

def gate(tag, st):
    if st == "W":
        return "Withdrawn"
    if tag == "S0":
        return "S0 (regression)"
    if re.fullmatch(r"S[1-5]", tag):
        return "step " + tag[1]
    if tag in ("H", "L"):
        return tag
    return tag or "?"

def read_srs(path):
    rows, header = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            header = None
            continue
        c = cells(line)
        if c and c[0] == "ID":
            header = c
            continue
        if header is None or re.match(r"^:?-{2,}", c[0] or "-"):
            continue
        if not ROW_ID.match(c[0]) or c[0].startswith("AM-"):
            continue
        if "Pri" not in header:
            continue
        get = lambda k: c[header.index(k)] if k in header and header.index(k) < len(c) else ""
        rows.append((c[0], pri_tag(get("Pri"), c[2:]), get("Ver"), get("St")))
    seen, out = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0]); out.append(r)
    return out

def read_matrix(text):
    start = text.index("### 6.2 Matrix")
    end = text.index("### 6.3 Coverage summary")
    block = text[start:end]
    keep, headings, cur = {}, collections.OrderedDict(), None
    for line in block.splitlines():
        m = re.match(r"^#### ((?:FR|NFR)-[A-Z0-9]+|DR|IR)\b(.*)$", line)
        if m:
            cur = m.group(1); headings[cur] = line
            continue
        if line.startswith("| ") and not line.startswith("| ID"):
            c = cells(line)
            rid = c[0].replace("†", "").strip()
            if ROW_ID.match(rid) and len(c) >= 7:
                keep[rid] = (c[4], c[5], "†" in c[0])
    return start, end, keep, headings

def annex_b(d, srs, srs_ver, write):
    p02 = d / "02-architecture.md"
    text = p02.read_text(encoding="utf-8")
    start = text.index("## Annex B.")
    end = text.index("## Annex C.")
    block = text[start:end]
    old = collections.OrderedDict()
    for line in block.splitlines():
        if line.startswith("| ") and not line.startswith("| Requirement"):
            c = cells(line)
            if len(c) >= 5 and ROW_ID.match(c[0]):
                old[c[0]] = (c[2], c[3], c[4])
    by_pref = collections.defaultdict(collections.Counter)
    for rid, v in old.items():
        by_pref[prefix(rid)][v] += 1
    def lookup(rid):
        if rid in old:
            return old[rid]
        root = re.sub(r"[a-z]$", "", rid)
        if root in old:
            return old[root]
        for sib in (root + "a", root + "b"):
            if sib in old:
                return old[sib]
        mc = by_pref[prefix(rid)].most_common(1)
        return mc[0][0] if mc else None
    rows, gaps = [], []
    for rid, tag, ver, st in srs:
        v = lookup(rid)
        if v is None:
            gaps.append(rid); v = ("—", "—", "—")
        t = "W (withdrawn)" if st == "W" else tag
        rows.append(f"| {rid} | {t} | {v[0]} | {v[1]} | {v[2]} |")
    added = [r[0] for r in srs if r[0] not in old]
    dropped = [r for r in old if r not in {x[0] for x in srs}]
    head = (f"Generated by `tools/gen_trace.py --annex-b` from TB-DS-01 v{srs_ver} §3 ({len(srs)} rows, all split IDs included) "
            "by the rule in this annex: each requirement is traced to the containers, decisions and quality scenarios of its area, "
            "as §10.3 assigns them, and carries its build tag from the SRS Pri cell. A split row (letter suffix) takes its root row's "
            "trace. Regenerate after every SRS version; `tools/doclint.py` check B reports any SRS ID missing here or carrying a "
            "different tag. A requirement whose area has no container would be listed under *Gaps*.")
    table = "\n".join(["| Requirement | Build tag | Containers | Decisions | Quality scenarios |",
                        "| --- | --- | --- | --- | --- |"] + rows)
    gap_line = "**Gaps:** " + (", ".join(gaps) if gaps else "none — every requirement area maps to at least one container.")
    new_block = f"## Annex B. Requirement-level trace (generated)\n\n{head}\n\n{table}\n\n{gap_line}\n\n---\n\n"
    print(f"Annex B: {len(rows)} rows from SRS v{srs_ver}; added {len(added)}; dropped {len(dropped)} {' '.join(dropped)}; gaps {len(gaps)}")
    if write:
        p02.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
        print("written", p02)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = pathlib.Path(args[0] if args else pathlib.Path(__file__).resolve().parent.parent)
    write = "--write" in sys.argv
    srs = read_srs(d / "01-SRS.md")
    if "--counts" in sys.argv:
        c = collections.Counter("withdrawn" if r[3] == "W" else r[1] for r in srs)
        for k in ["S0", "S1", "S2", "S3", "S4", "S5", "H", "L", "withdrawn"]:
            print(f"{k}\t{c.get(k, 0)}")
        print(f"total\t{len(srs)}")
        return
    if "--annex-b" in sys.argv:
        v = re.search(r"\| Version \| ([0-9.]+[a-z]?)", (d / "01-SRS.md").read_text(encoding="utf-8"))
        annex_b(d, srs, v.group(1) if v else "?", write)
        return
    p04 = d / "04-verification-operations.md"
    text = p04.read_text(encoding="utf-8")
    start, end, keep, headings = read_matrix(text)
    srs_ver = re.search(r"\| Version \| ([0-9.]+[a-z]?)", (d / "01-SRS.md").read_text(encoding="utf-8"))
    srs_ver = srs_ver.group(1) if srs_ver else "?"
    # suggestions per prefix
    lv, su = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    for rid, (l, s, _) in keep.items():
        lv[prefix(rid)][l] += 1; su[prefix(rid)][s] += 1
    groups = collections.OrderedDict()
    for rid, tag, ver, st in srs:
        groups.setdefault(prefix(rid), []).append((rid, tag, ver, st))
    added, out = [], []
    out.append("### 6.2 Matrix\n")
    out.append(f"Generated by `tools/gen_trace.py` from TB-DS-01 v{srs_ver} ({len(srs)} requirement rows, plus AM-01). "
               "Test levels and suite of existing rows are kept; rows marked † are new and carry suggested levels and suite "
               "(a split row takes its root row's; otherwise the most common for the ID prefix) until their suite is written. Release gate is derived from the SRS tag (§6.1).\n")
    order = list(headings.keys()) + [g for g in groups if g not in headings]
    for g in order:
        if g not in groups:
            continue
        head = headings.get(g) or f"#### {g} — {GROUP_TITLES.get(g, g.split('-')[-1].title())}"
        out.append(head + "\n")
        out.append("| ID | Pri | Ver | St | Test levels | Suite | Release gate |")
        out.append("| --- | --- | --- | --- | --- | --- | --- |")
        for rid, tag, ver, st in groups[g]:
            if rid in keep:
                l, s, dag = keep[rid]; mark = " †" if dag else ""
            elif re.sub(r"[a-z]$", "", rid) in keep:  # split row: inherit the root row's levels and suite
                l, s, _ = keep[re.sub(r"[a-z]$", "", rid)]; mark = " †"; added.append(rid)
            else:
                l = (lv[g].most_common(1) or [(DEFAULT_LEVELS.get(g, "U I E"), 0)])[0][0]
                s = (su[g].most_common(1) or [(DEFAULT_SUITE.get(g, "TS-" + g.split("-")[-1]), 0)])[0][0]
                mark = " †"; added.append(rid)
            out.append(f"| {rid}{mark} | {tag} | {ver} | {st} | {l} | {s} | {gate(tag, st)} |")
        if g == "FR-AUTH":
            l, s, _ = keep.get("AM-01", ("U I B", "TS-AUTH", False))
            out.append(f"| AM-01 | S0 | T | P | {l} | {s} | S0 (regression) |")
        out.append("")
    srs_ids = {r[0] for r in srs} | {"AM-01"}
    dropped = sorted(set(keep) - srs_ids)
    new_block = "\n".join(out) + "\n"
    # counts
    active = [r for r in srs if r[3] != "W"]
    cnt = collections.Counter(gate(r[1], r[3]) for r in active)
    order_g = ["S0 (regression)"] + [f"step {i}" for i in range(1, 6)] + ["H", "L"]
    count_line = (f"- Requirements traced: **{len(active)} active of {len(srs)} rows** from TB-DS-01 v{srs_ver}, plus AM-01 "
                  f"(generated by `tools/gen_trace.py`). No active requirement is untraced. By release gate: "
                  + ", ".join(f"{k} {cnt.get(k, 0)}" for k in order_g)
                  + (f", other {sum(v for k, v in cnt.items() if k not in order_g)}" if any(k not in order_g for k in cnt) else "")
                  + ".")
    print(f"SRS v{srs_ver}: {len(srs)} rows, {len(active)} active; kept {len(srs) - len(added)}; added {len(added)}: {' '.join(added)}")
    print("dropped (not in SRS):", " ".join(dropped) or "none")
    print(count_line)
    if write:
        new = text[:start] + new_block + text[end:]
        new = re.sub(r"^- Requirements traced: .*$", count_line.replace("\\", "\\\\"), new, count=1, flags=re.M)
        p04.write_text(new, encoding="utf-8")
        print("written", p04)

if __name__ == "__main__":
    main()
