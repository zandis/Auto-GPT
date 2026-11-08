#!/usr/bin/env python3
"""Lint the TrialBox design set. Reports, never blocks (no gate).

Usage: python3 doclint.py [DESIGN_DIR] [--only 04,07,...]

Checks (review records 06*.md are skipped):
  T  table column counts: header vs separator vs every row
  I  ID resolution: FR/NFR/DR/IR cited anywhere resolve to TB-DS-01;
     BD-nn and N-nn resolve to TB-DS-00; SC-nn resolve to TB-DS-03
  V  version in each document's control table equals its row in TB-DS-00R
  G  stray tags: priority / release cells (columns Pri, Release, Build, Tag,
     Release gate) holding the retired M1 / M2 / C values ("(was M1)" is fine)
  P  stale phrases from superseded decisions (two sign-offs, S20 part 1/2,
     entry page, shadow mode outside definitions, RELEASE command)
  B  TB-DS-02 Annex B coverage: every TB-DS-01 requirement row has an Annex B
     row and the same build tag (regenerate with gen_trace.py --annex-b)
Change-history sections are skipped for G and P. Standard library only.
"""
import re, sys, pathlib, collections

STALE = [(r"two sign-?offs?", "two sign-offs (BD-13 one Approve)"),
         (r"S20 part [12]", "S20 part 1/2 (one page)"),
         (r"\bentry page\b", "entry page (header command field, F6-06)"),
         (r"\bshadow mode\b", "shadow mode (defined term only)")]
TAG_COLS = {"Pri", "Release", "Build", "Tag", "Release gate", "Build tag", "Rel"}
RETIRED = re.compile(r"^\**(M1|M2|C|C \(later\)|Must|Should|Could)\b(?!.*was)")

def cells(line):
    s = line.strip()
    if s.startswith("|"): s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"): s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]

def docs(d, only):
    for p in sorted(d.glob("*.md")):
        if p.name.startswith("06"):
            continue
        if only and not any(p.name.startswith(o) for o in only):
            continue
        yield p

def ids_from(path, pat):
    return set(re.findall(pat, path.read_text(encoding="utf-8"))) if path.exists() else set()

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = pathlib.Path(args[0] if args else pathlib.Path(__file__).resolve().parent.parent)
    only = []
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",")
    srs = (d / "01-SRS.md").read_text(encoding="utf-8")
    srs_ids = set(re.findall(r"^\| ((?:FR|NFR)-[A-Z0-9]+-\d+[a-z]?|(?:DR|IR)-\d+[a-z]?|AM-\d+) \|", srs, re.M))
    bd = ids_from(d / "00-baseline-decisions.md", r"\| (BD-\d+)\b") | ids_from(d / "00-baseline-decisions.md", r"\| (N-\d+) \|")
    sc = ids_from(d / "03-security-privacy.md", r"\| (SC-\d+) \|")
    reg = {}
    for line in (d / "00-document-register.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| [^|]+ \| [^|]+ \| `([^`]+)`[^|]* \| ([^|]+) \|", line)
        if m:
            reg[m.group(1)] = m.group(2).strip()
    total = collections.Counter()
    for p in docs(d, only):
        lines = p.read_text(encoding="utf-8").splitlines()
        issues = []
        in_code = in_hist = False
        header = None; ncol = 0
        for i, line in enumerate(lines, 1):
            if line.startswith("```"):
                in_code = not in_code; continue
            if in_code:
                continue
            if line.startswith("#"):
                in_hist = bool(re.search(r"change history", line, re.I)); header = None
            if line.startswith("|"):
                c = cells(line)
                nxt = lines[i] if i < len(lines) else ""
                if header is None and re.match(r"^\|\s*:?-{2,}", nxt):
                    header, ncol = c, len(c)
                elif re.match(r"^\|\s*:?-{2,}", line):
                    if len(c) != ncol:
                        issues.append(("T", i, f"separator has {len(c)} cells, header {ncol}"))
                elif header is not None:
                    if len(c) != ncol:
                        issues.append(("T", i, f"row has {len(c)} cells, header {ncol}"))
                    elif not in_hist:
                        for h, v in zip(header, c):
                            if h in TAG_COLS and RETIRED.match(v):
                                issues.append(("G", i, f"{h} = '{v[:30]}'"))
            else:
                header = None
            if not in_hist:
                for pat, why in STALE:
                    for m in re.finditer(pat, line, re.I):
                        ctx = line[max(0, m.start() - 60):m.end() + 40]
                        if re.search(r"was |superseded|older name|historical|defined as| means|not |no longer|no separate|replaces|replaced", ctx, re.I):
                            continue
                        issues.append(("P", i, why))
            for rid in re.findall(r"\b((?:FR|NFR)-[A-Z0-9]+-\d+[a-z]?|(?:DR|IR)-\d+[a-z]?)\b", line):
                if rid not in srs_ids and not re.search(r"\d[a-z]$", rid) and not any(x.startswith(rid) for x in srs_ids):
                    if p.name.startswith("01"):
                        continue
                    issues.append(("I", i, f"{rid} not in TB-DS-01"))
            for rid in re.findall(r"\b(BD-\d+)\b", line):
                if rid not in bd:
                    issues.append(("I", i, f"{rid} not in TB-DS-00"))
            for rid in re.findall(r"\b(SC-\d+)\b", line):
                if sc and rid not in sc and not p.name.startswith("03"):
                    issues.append(("I", i, f"{rid} not in TB-DS-03"))
        text = "\n".join(lines[:15])
        m = re.search(r"^\| Version \| ([0-9]+\.[0-9]+[a-z]?)", text, re.M)
        if p.name in reg and m and not reg[p.name].startswith(m.group(1)):
            issues.append(("V", 0, f"control table {m.group(1)} vs register {reg[p.name]}"))
        if p.name in reg and not m:
            issues.append(("V", 0, "no Version row in the first 15 lines"))
        by = collections.Counter(k for k, _, _ in issues)
        total.update(by)
        print(f"{p.name}: " + (", ".join(f"{k} {v}" for k, v in sorted(by.items())) or "clean"))
        for k, ln, msg in issues[:200]:
            print(f"  {k} {p.name}:{ln} {msg}")
    # B: Annex B coverage and tags
    p02 = d / "02-architecture.md"
    if p02.exists() and (not only or any("02".startswith(o) or o.startswith("02") for o in only)):
        t02 = p02.read_text(encoding="utf-8")
        b = {}
        if "## Annex B." in t02:
            blk = t02[t02.index("## Annex B."):t02.index("## Annex C.") if "## Annex C." in t02 else None]
            for line in blk.splitlines():
                c = cells(line)
                if len(c) >= 2 and re.match(r"^(FR|NFR|DR|IR)-", c[0]):
                    b[c[0]] = c[1].split()[0]
        srs_tag = {}
        hdr = None
        for line in srs.splitlines():
            if not line.startswith("|"):
                hdr = None; continue
            c = cells(line)
            if c and c[0] == "ID":
                hdr = c; continue
            if hdr and "Pri" in hdr and re.match(r"^((FR|NFR)-[A-Z0-9]+-\d+[a-z]?|(DR|IR)-\d+[a-z]?)$", c[0]) and c[0] not in srs_tag:
                pri = c[hdr.index("Pri")] if hdr.index("Pri") < len(c) else ""
                st = c[hdr.index("St")] if "St" in hdr and hdr.index("St") < len(c) else ""
                m = re.match(r"^\**(S[0-5]|H|L)\b", pri)
                srs_tag[c[0]] = "W" if st == "W" else (m.group(1) if m else pri.split()[0] if pri else "")
        bi = []
        for rid, tg in srs_tag.items():
            if rid not in b:
                bi.append(("B", 0, f"{rid} missing from Annex B"))
            elif b[rid] != tg:
                bi.append(("B", 0, f"{rid} tag {b[rid]} in Annex B vs {tg} in TB-DS-01"))
        total.update(k for k, _, _ in bi)
        print("02-architecture.md Annex B: " + (f"B {len(bi)}" if bi else f"clean ({len(b)} rows)"))
        for k, ln, msg in bi[:50]:
            print(f"  {k} 02-architecture.md: {msg}")
    print("TOTAL: " + (", ".join(f"{k} {v}" for k, v in sorted(total.items())) or "clean"))

if __name__ == "__main__":
    main()
