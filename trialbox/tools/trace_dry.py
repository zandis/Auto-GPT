"""trace_dry: a first, dry traceability table for plan 8's validation pack (card V-15).

    python -m tools.trace_dry --write                      # collect the test ids, read the results, write the table
    python -m tools.trace_dry --write --collection F       # use a saved `pytest --collect-only -q` output instead
    python -m tools.trace_dry --write --results a.xml ...  # junit xml files with real outcomes (pytest --junitxml)
    python -m tools.trace_dry --check                      # the page's generated blocks equal trace.json, and every
                                                           # test named in trace.json is in the committed collection

How it relates to ``tools/gen_traceability.py``: that tool reads the superseded plan TB-PLAN-05 and writes
``docs/plan/25-traceability.csv`` with the status "planned" on every row. It is not changed here. This tool reads the
same requirement ids, the second home of requirements (the SRS, TB-DS-01), the decisions, the collected test ids and
real junit results, and writes a measurement under ``docs/plan/measurements/traceability-dry-2026-11-17/``. When the
validation pack is built, the owner of the pack can fold the reading of results into one generator.

Rows: plan 8's twelve release criteria (a mapping to test files written by hand below, CRITERIA); the requirements
(URS of TB-PLAN-05, FR and NFR of TB-DS-01) with the tests that cite each id; the decisions with the tests that cite
each number; the safety-core tests that cite no requirement and no decision; the parts of the pack the generator
cannot yet produce (PACK). Outcomes come only from junit files: a test with no outcome there is "not run here".
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "plan" / "measurements" / "traceability-dry-2026-11-17"
PAGE = ROOT / "docs" / "plan" / "measurements" / "traceability-dry-2026-11-17.md"
PLAN8 = ROOT / "docs" / "plan" / "44-plan-8-2026-11-17.md"
URS_HOME = ROOT / "docs" / "plan" / "25-master-plan.md"
SRS_HOME = ROOT / "docs" / "plan" / "design" / "01-SRS.md"
REGISTRY = ROOT / "docs" / "decisions" / "REGISTRY.md"
LOG = ROOT / "docs" / "DECISIONS.md"
DEC_DIR = ROOT / "docs" / "decisions"
MUTATION = ROOT / "tools" / "mutation.toml"
TESTS = ROOT / "tests"
# Documents that name tests as proof (their test names are checked against the collection).
TRACE_DOCS = (
    "docs/plan/25-master-plan.md",
    "docs/plan/25-traceability.csv",
    "docs/plan/design/01-SRS.md",
    "docs/plan/design/04-verification-operations.md",
    "docs/plan/design/11-risk-management.md",
    *sorted(f"docs/validation/{p.name}" for p in (ROOT / "docs" / "validation").glob("*.md")),
)

URS = re.compile(r"\bURS-[A-Z]+-\d+\b")
FRS = re.compile(r"\bN?FR-[A-Z]+-\d+[a-z]?\b")
DEC = re.compile(r"\bD-0*(\d{1,4})\b")
TEST_FILE = re.compile(r"\b(test_\w+)\.py\b")
TEST_FUNC = re.compile(r"(?<![\w/.])(test_\w+)\b(?!\.py)")
NOT_RUN = "not run here"

# The heuristic for "a decision states a rule": these words in its text. It is a heuristic; the page samples it.
RULE_WORDS = re.compile(r"\b(must|never|refuses|is refused|only)\b", re.I)
# Safety relevance: groups of words; a decision's score is 3 per group named in its title + 1 per group in its text.
SAFETY_GROUPS = {
    "screening exclusion": r"exclu|eligib|unknown|screen",
    "PHI and masking": r"\bphi\b|mask|pseudonym|identifier|de-identif",
    "roles": r"\brole|matrix|permission|break-glass",
    "audit": r"\baudit",
    "erasure and opt-out": r"erasure|opt-out|opt out|withdraw",
    "EDC signing": r"\bsign|\bedc\b|redcap|delegation",
}

# Plan 8 section 3, mapped by hand to the test files that bear on each criterion. `rest` is what only a run outside
# the repository can show. `kind`: "tests" (tests bear on it), "outside" (no test; a run elsewhere), "untestable".
CRITERIA: dict[int, dict[str, Any]] = {
    1: {
        "files": "mutation",
        "rest": "the confirming launch on the GPU VM (V2) and the owner's carve on his PC (V3)",
        "bears": "the two safety invariants (unknown never excludes; a proposed fact never counts); not accuracy",
    },
    2: {
        "files": r"qualif",
        "rest": "a box installed from the signed bundle, GPU VM then reference workstation (V1)",
        "bears": "the qualify tool's logic on stubs; not a record for the real pair",
    },
    3: {
        "files": r"mutation|nightly",
        "rest": "three nightly runs in CI, under compose (V12, V19)",
        "bears": "the mutation and nightly tools; not three green nights",
    },
    4: {
        "files": r"backup|restore|rpo|rto",
        "rest": "the reference workstation (V10, V17)",
        "bears": "backup and restore logic on the test machine; not a timed restore on hardware",
    },
    5: {
        "files": r"windows|/test_p0_",
        "rest": "the owner's Windows PC (V10)",
        "bears": "the Windows installer's scripts and files; not the install on the PC",
    },
    6: {
        "files": r"edc|redcap|withdraw|signing",
        "rest": "lane E's REDCap container, the owner's EDC, CGRD on the owner's PC (V14, V15)",
        "bears": "drafting, signing and sending against stubs; not the round trip",
    },
    7: {
        "files": r"help|role_guide|journey",
        "rest": "people who have not used TrialBox (V13)",
        "kind": "untestable",
        "bears": "the help field and the role guides exist and link; not a person following them",
    },
    8: {
        "files": r"erasure|optout|opt_out|opted",
        "rest": "the compose box, every store (V7)",
        "bears": "opt-out and erasure in each store the tests build",
    },
    9: {
        "files": r"release|sbom|traceab|vuln|waiver",
        "rest": "the release candidate (V18, V9)",
        "bears": "the release tools and the old traceability generator; not a generated pack",
    },
    10: {
        "files": [
            "tests/console/test_role_route_matrix.py",
            "tests/console/test_role_route_matrix_acting.py",
            "tests/console/test_role_pages.py",
            "tests/console/test_one_sign_in_acting_role.py",
            "tests/e2e/test_life_cycle_walk.py",
            "tests/e2e/test_new_study_walk.py",
            "tests/e2e/test_role_walk.py",
            "tests/unit/test_authz_matrix.py",
            "tests/unit/test_role_paths.py",
            "tests/unit/test_demo_walks.py",
        ],
        "rest": "the compose box, three languages, phone width (V16, V8)",
        "bears": "the matrix test and the walks that run in process",
    },
    11: {
        "files": ["tests/unit/test_findings_register.py"],
        "rest": "the register itself, read at release (V20)",
        "bears": "the register tool; the register is not on master",
    },
    12: {
        "files": [],
        "rest": "a stranger with the kit, real hardware, the synthetic hospital (V20)",
        "kind": "untestable",
        "bears": "nothing in the repository",
    },
}

# The parts of the pack the generator cannot yet produce. `path` is checked for existence at --write.
PACK: list[dict[str, Any]] = [
    {
        "part": "IQ record",
        "path": "tools/trialbox/doctor.py",
        "command": "trialbox doctor (its output is not turned into a record)",
        "missing": "no command turns doctor's output and the release file into an IQ record; none is on file",
    },
    {
        "part": "OQ protocol and record",
        "path": "tools/acceptance.py",
        "command": "tools/acceptance.py; CI",
        "missing": "no OQ protocol; CI writes no junit for the unit suite, so no result is kept for a release",
    },
    {
        "part": "Risk file linked to tests",
        "path": "docs/plan/design/11-risk-management.md",
        "command": "none (by hand)",
        "missing": "hazards name suites (TS-SCR) and OQ ids, not test ids; two risk files on two id schemes",
    },
    {
        "part": "Part 11 and Electronic Signatures Act assessment",
        "path": "docs/validation/standards-position.md",
        "command": "none (by hand)",
        "missing": "the review's area K table is the only control-by-control reading",
    },
    {
        "part": "SBOM",
        "path": "tools/release.py",
        "command": "tools/release.py (in the release bundle)",
        "missing": "not written into docs/validation/release-records/ for a commit",
    },
    {
        "part": "Release record",
        "path": "docs/validation/release-records/README.md",
        "command": "none",
        "missing": "the folder holds a README only (review K, 5.8)",
    },
    {
        "part": "Results of nightly, compose and hardware activities",
        "path": ".github/workflows/trialbox-e2e.yml",
        "command": "make test-compose COMPOSE_JUNIT=...",
        "missing": "junit kept as a CI artifact only; never in the repository",
    },
    {
        "part": "Signatures and approvals",
        "path": "docs/validation/change-control.md",
        "command": "none",
        "missing": "no signed approval of any pack document",
    },
    {
        "part": "Model qualification record",
        "path": "eval/qualification/README.md",
        "command": "python -m tools.qualify",
        "missing": "no record for the shipped pair (review K-6)",
    },
]


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# ----------------------------------------------------------------------------------------------- collection, results


def parse_collection(text: str) -> dict[str, Any]:
    """`pytest --collect-only -q` output -> {"items": collected items, "files": {test file: sorted test names}}.

    Parameters are dropped from the names, so one name may stand for several collected items."""
    out: dict[str, set[str]] = defaultdict(set)
    items = 0
    for line in text.splitlines():
        if "::" not in line or not line.startswith("tests/"):
            continue
        items += 1
        path, _, name = line.strip().partition("::")
        out[path].add(name.split("[", 1)[0])
    return {"items": items, "files": {k: sorted(v) for k, v in sorted(out.items())}}


def run_collection() -> str:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
    ]
    env = {"PYTHONPATH": "libs:services:."}
    import os

    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, **env}, check=False)
    if done.returncode != 0:
        raise SystemExit(f"trace_dry: the collection failed ({done.returncode}); nothing written")
    return done.stdout


CASE = re.compile(r"<testcase\b([^>]*?)(?:/>|>(.*?)</testcase>)", re.S)
ATTR = re.compile(r'(\w+)="([^"]*)"')


def read_junit(paths: list[Path]) -> dict[str, str]:
    """junit xml -> {"<test file>::<name>": outcome}; outcome is passed, failed, error, skipped or xfailed.

    pytest's junit is read with a pattern, not an XML parser: it is our own output, and the scans refuse XML parsers
    on files from outside."""
    out: dict[str, str] = {}
    for p in paths:
        for m in CASE.finditer(p.read_text(errors="replace")):
            attrs = {k: html.unescape(v) for k, v in ATTR.findall(m.group(1))}
            body = m.group(2) or ""
            parts = attrs.get("classname", "").split(".")
            # classname is the module path (dots) plus any class names (capitalised)
            mod = [x for x in parts if not x[:1].isupper()]
            klass = [x for x in parts if x[:1].isupper()]
            node = "/".join(mod) + ".py::" + "::".join([*klass, attrs.get("name", "")])
            if "<failure" in body:
                outcome = "failed"
            elif "<error" in body:
                outcome = "error"
            elif '<skipped type="pytest.xfail"' in body:
                outcome = "xfailed"
            elif "<skipped" in body:
                outcome = "skipped"
            else:
                outcome = "passed"
            out[node] = outcome
    return out


# ----------------------------------------------------------------------------------------------- the sources


def criteria_from_plan() -> dict[int, dict[str, Any]]:
    rows = {}
    text = PLAN8.read_text()
    sec = text.split("## 3. The release criteria", 1)[1].split("\n## ", 1)[0]
    for line in sec.splitlines():
        m = re.match(r"^\| (\d+) \| (.+) \| ([^|]+) \|$", line)
        if m:
            title = re.search(r"\*\*(.+?)\*\*", m.group(2))
            rows[int(m.group(1))] = {
                "title": (title.group(1) if title else m.group(2)[:80]).rstrip("."),
                "activities": m.group(3).strip(),
            }
    return rows


def requirements() -> dict[str, str]:
    """Requirement id -> its home (one id may have two homes; the first wins and a duplicate is reported)."""
    out: dict[str, str] = {}
    for line in URS_HOME.read_text().splitlines():
        m = re.match(r"^\| (URS-[A-Z]+-\d+) \|", line)
        if m:
            out.setdefault(m.group(1), rel(URS_HOME))
    for line in SRS_HOME.read_text().splitlines():
        m = re.match(r"^\| (N?FR-[A-Z]+-\d+[a-z]?) \|", line)
        if m:
            out.setdefault(m.group(1), rel(SRS_HOME))
    return out


def merged_numbers() -> set[int]:
    out: set[int] = set()
    for line in REGISTRY.read_text().splitlines():
        m = re.match(r"^\| D-(\d+)(?:\.\.D-(\d+))? \| merged \|", line)
        if m:
            a = int(m.group(1))
            out.update(range(a, int(m.group(2) or a) + 1))
    return out


def decision_texts() -> dict[int, tuple[str, str, str]]:
    """number -> (title, text, place). Files win over the frozen log."""
    out: dict[int, tuple[str, str, str]] = {}
    for para in LOG.read_text().split("\n\n"):
        m = re.match(r"\*\*D-0*(\d+) (.+?)\*\*", para)
        if m:
            out[int(m.group(1))] = (m.group(2).rstrip("."), para, rel(LOG))
    for f in sorted(DEC_DIR.glob("D-*.md")):
        m = re.match(r"D-(\d+)-", f.name)
        if not m:
            continue
        text = f.read_text()
        head = text.splitlines()[0] if text else ""
        title = re.sub(r"^#\s*D-\d+\s*", "", head).strip()
        out[int(m.group(1))] = (title, text, rel(f))
    return out


def test_texts() -> dict[str, str]:
    return {rel(p): p.read_text(errors="replace") for p in sorted(TESTS.rglob("*.py"))}


def safety_tests() -> tuple[list[str], list[str]]:
    data = tomllib.loads(MUTATION.read_text())
    targets = sorted({t for x in data["target"] for t in x["tests"]})
    return targets, list(data["safety_core"]["files"])


def module_of(path: str) -> str:
    p = path.removesuffix(".py")
    for prefix in ("services/", "libs/"):
        p = p.removeprefix(prefix)
    return p.replace("/", ".")


def imports_module(text: str, mod: str) -> bool:
    parent, _, leaf = mod.rpartition(".")
    return bool(
        re.search(rf"^\s*(from {re.escape(mod)} import|import {re.escape(mod)}\b)", text, re.M)
        or (parent and re.search(rf"^\s*from {re.escape(parent)} import [^\n]*\b{leaf}\b", text, re.M))
    )


def files_for(spec: Any, collection: dict[str, list[str]], safety: list[str]) -> list[str]:
    if spec == "mutation":
        return [f for f in safety if f in collection]
    if isinstance(spec, list):
        return spec
    return [f for f in collection if re.search(spec, f.rsplit("/", 1)[-1] if "/" not in spec else f)]


# ----------------------------------------------------------------------------------------------- building


def outcomes_for(files: list[str], results: dict[str, str]) -> dict[str, Any]:
    count: Counter[str] = Counter()
    bad: list[str] = []
    run_files = 0
    for f in files:
        mine = {k: v for k, v in results.items() if k.startswith(f + "::")}
        if mine:
            run_files += 1
        count.update(mine.values())
        bad += sorted(f"{k} [{v}]" for k, v in mine.items() if v != "passed")
    return {"files": len(files), "files_run": run_files, "outcomes": dict(sorted(count.items())), "not_passed": bad}


def criterion_status(kind: str, files: list[str], o: dict[str, Any]) -> str:
    if kind == "untestable" and not files:
        return "not testable in the repository"
    if not files:
        return "no test; shown only by a run outside the repository"
    if o["files_run"] == 0:
        return "has tests; collected, result not run here"
    if any(k != "passed" for k in o["outcomes"]) or o["files_run"] < o["files"]:
        return "has tests, some xfail/skip/fail or not run"
    return "has passing tests that show part of it"


def dead_references(collection: dict[str, list[str]]) -> list[dict[str, Any]]:
    files = {f.rsplit("/", 1)[-1].removesuffix(".py") for f in collection}
    names = {n.rsplit("::", 1)[-1] for v in collection.values() for n in v}
    on_disk = {p.stem for p in TESTS.rglob("test_*.py")}
    out = []
    for doc in TRACE_DOCS:
        text = (ROOT / doc).read_text()
        for i, line in enumerate(text.splitlines(), 1):
            for m in TEST_FILE.finditer(line):
                if m.group(1) not in files:
                    out.append(
                        {
                            "doc": doc,
                            "line": i,
                            "name": m.group(1) + ".py",
                            "why": "file on disk, no test collected" if m.group(1) in on_disk else "no such test file",
                        }
                    )
            for m in TEST_FUNC.finditer(line):
                n = m.group(1)
                if n not in names and n not in files and n not in on_disk:
                    out.append({"doc": doc, "line": i, "name": n, "why": "no such test"})
    return out


def tst_resolution(collection: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Each TST id of TB-PLAN-05's test table: the test files its row names, and its links in the CSV."""
    stems = {f.rsplit("/", 1)[-1].removesuffix(".py"): f for f in collection}
    links = list(csv.DictReader((ROOT / "docs" / "plan" / "25-traceability.csv").read_text().splitlines()))
    out = []
    for line in URS_HOME.read_text().splitlines():
        m = re.match(r"^\| (TST-[A-Z0-9]+-\d+) \|", line)
        if m:
            named = sorted({x + ".py" for x in TEST_FILE.findall(line)})
            out.append(
                {
                    "id": m.group(1),
                    "named": named,
                    "collected": sorted(stems[n[:-3]] for n in named if n[:-3] in stems),
                    "csv_links": sum(row["test"] == m.group(1) for row in links),
                }
            )
    return out


def build(collection: dict[str, list[str]], results: dict[str, str], results_from: list[str]) -> dict[str, Any]:
    tests = test_texts()
    safety, core = safety_tests()
    plan = criteria_from_plan()
    crit_rows = []
    for n in sorted(plan):
        c = CRITERIA[n]
        files = files_for(c["files"], collection, safety)
        o = outcomes_for(files, results)
        crit_rows.append(
            {
                "criterion": n,
                "title": plan[n]["title"],
                "activities": plan[n]["activities"],
                "test_files": files,
                "tests_bear_on": c["bears"],
                "rest_shown_only_by": c["rest"],
                "results": o,
                "status": criterion_status(c.get("kind", "tests"), files, o),
            }
        )

    reqs = requirements()
    cites: dict[str, list[str]] = defaultdict(list)
    for path, text in tests.items():
        for rid in set(URS.findall(text)) | set(FRS.findall(text)):
            cites[rid].append(path)
    req_rows: list[dict[str, Any]] = [
        {"id": r, "home": h, "tests": sorted(cites.get(r, []))} for r, h in sorted(reqs.items())
    ]
    unknown_cited = sorted(set(cites) - set(reqs))

    dec_tests: dict[int, list[str]] = defaultdict(list)
    test_decs: dict[str, list[int]] = {}
    for path, text in tests.items():
        nums = sorted({int(x) for x in DEC.findall(text)})
        test_decs[path] = nums
        for n in nums:
            dec_tests[n].append(path)
    merged = merged_numbers()
    texts = decision_texts()
    uncited: list[dict[str, Any]] = []
    for n in sorted(merged & set(texts)):
        if n in dec_tests:
            continue
        title, text, place = texts[n]
        if not RULE_WORDS.search(text):
            continue
        groups_title = [g for g, rx in SAFETY_GROUPS.items() if re.search(rx, title, re.I)]
        groups_text = [g for g, rx in SAFETY_GROUPS.items() if re.search(rx, text, re.I)]
        score = 3 * len(groups_title) + len(groups_text)
        uncited.append(
            {"decision": f"D-{n}", "title": title[:110], "place": place, "score": score, "groups": groups_text}
        )
    uncited.sort(key=lambda r: (-r["score"], int(r["decision"][2:])))

    core_files = set(safety)
    for f, text in tests.items():
        if any(imports_module(text, module_of(c)) for c in core):
            core_files.add(f)
    untied = []
    for f in sorted(core_files):
        text = tests.get(f, "")
        if not (URS.search(text) or FRS.search(text) or test_decs.get(f)):
            untied.append(f)

    for p in PACK:
        p["exists"] = (ROOT / p["path"]).exists()

    dead = dead_references(collection)
    tst_rows = tst_resolution(collection)
    counts = {
        "collected_test_names": sum(len(v) for v in collection.values()),
        "collected_files": len(collection),
        "results_read": len(results),
        "results_outcomes": dict(sorted(Counter(results.values()).items())),
        "requirements": len(req_rows),
        "requirements_urs": sum(r["id"].startswith("URS") for r in req_rows),
        "requirements_srs": sum(not r["id"].startswith("URS") for r in req_rows),
        "requirements_with_tests": sum(bool(r["tests"]) for r in req_rows),
        "requirements_without_tests": sum(not r["tests"] for r in req_rows),
        "ids_cited_in_tests_not_defined": len(unknown_cited),
        "decisions_merged_with_text": len(merged & set(texts)),
        "decisions_cited_by_tests": len(set(dec_tests) & merged & set(texts)),
        "decisions_not_cited": len((merged & set(texts)) - set(dec_tests)),
        "decisions_rule_words_not_cited": len(uncited),
        "safety_core_test_files": len(core_files),
        "safety_core_tests_untied": len(untied),
        "dead_references": len(dead),
        "dead_reference_names": len({d["name"] for d in dead}),
        "tst_ids": len(tst_rows),
        "tst_ids_naming_a_collected_test": sum(bool(r["collected"]) for r in tst_rows),
        "csv_links": sum(r["csv_links"] for r in tst_rows),
        "csv_links_to_a_tst_naming_no_test": sum(r["csv_links"] for r in tst_rows if not r["collected"]),
    }
    return {
        "date": "2026-11-17",
        "commit": git_head(),
        "results_from": results_from,
        "counts": counts,
        "criteria": crit_rows,
        "requirements": req_rows,
        "ids_cited_in_tests_not_defined": unknown_cited,
        "decisions_uncited_top40": uncited[:40],
        "safety_core_untied": untied,
        "dead_references": dead,
        "tst_rows": tst_rows,
        "pack_cannot_yet": PACK,
        "heuristic": {
            "rule_words": RULE_WORDS.pattern,
            "safety_groups": SAFETY_GROUPS,
            "score": "3 per group in the title + 1 per group in the text",
        },
    }


def git_head() -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return done.stdout.strip()


# ----------------------------------------------------------------------------------------------- the page's blocks


def table(head: list[str], rows: list[list[Any]]) -> str:
    def cell(x: Any) -> str:
        return str(x).replace("|", "/").replace("\n", " ")

    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    lines += ["| " + " | ".join(cell(x) for x in r) + " |" for r in rows]
    return "\n".join(lines)


def blocks(trace: dict[str, Any], findings: list[dict[str, Any]], sample: list[dict[str, Any]]) -> dict[str, str]:
    c = trace["counts"]
    out: dict[str, str] = {}
    truly = sum(s["verdict"] == "no_test_found" for s in sample)
    out["sample"] = table(
        ["Decision", "Checked by hand", "Evidence"],
        [[s["decision"], s["verdict"].replace("_", " "), s["evidence"]] for s in sample],
    ) + (
        f"\n\nSampled: {len(sample)}. Truly without a test: {truly}. Precision of the heuristic "
        f'"no test cites it" as "no test": {truly}/{len(sample)}.'
    )
    out["verdict"] = table(
        ["#", "Criterion", "Status", "Test files (run here)", "Outcomes", "Shown only by"],
        [
            [
                r["criterion"],
                r["title"],
                r["status"],
                f"{r['results']['files']} ({r['results']['files_run']})",
                ", ".join(f"{k} {v}" for k, v in r["results"]["outcomes"].items()) or NOT_RUN,
                r["rest_shown_only_by"],
            ]
            for r in trace["criteria"]
        ],
    )
    out["provenance"] = (
        f"- Commit read: `{trace['commit']}`\n- Results read from: "
        + (", ".join(f"`{r}`" for r in trace["results_from"]) or "none")
        + "\n"
        + f"- Collected test items: {c.get('collected_items')}; test files: {c['collected_files']}; "
        + f"junit results read: {c['results_read']}"
    )
    out["counts"] = table(
        ["Count", "Value"],
        [
            [k.replace("_", " "), ", ".join(f"{a} {b}" for a, b in v.items()) if isinstance(v, dict) else v]
            for k, v in sorted(c.items())
        ],
    )
    out["not_passed"] = (
        "\n".join(f"- criterion {r['criterion']}: `{t}`" for r in trace["criteria"] for t in r["results"]["not_passed"])
        or "- none"
    )
    out["requirements"] = table(
        ["Home", "Requirements", "With a test that cites the id", "Without"],
        [
            [
                h,
                sum(r["home"] == h for r in trace["requirements"]),
                sum(r["home"] == h and bool(r["tests"]) for r in trace["requirements"]),
                sum(r["home"] == h and not r["tests"] for r in trace["requirements"]),
            ]
            for h in sorted({r["home"] for r in trace["requirements"]})
        ],
    )
    out["requirements_cited"] = (
        "\n".join(
            f"- {r['id']}: " + ", ".join(f"`{t}`" for t in r["tests"]) for r in trace["requirements"] if r["tests"]
        )
        or "- none"
    )
    out["decisions"] = table(
        ["#", "Decision", "Score", "Groups", "Title"],
        [
            [i, d["decision"], d["score"], ", ".join(d["groups"]), d["title"]]
            for i, d in enumerate(trace["decisions_uncited_top40"], 1)
        ],
    )
    out["untied"] = "\n".join(f"- `{f}`" for f in trace["safety_core_untied"]) or "- none"
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d in trace["dead_references"]:
        by_name[(d["name"], d["why"])].append(f"{d['doc']}:{d['line']}")
    out["dead"] = table(
        ["Name", "Why", "Where"], [[f"`{n}`", w, ", ".join(p)] for (n, w), p in sorted(by_name.items())]
    )
    out["tst"] = table(
        ["TST id", "Test files its row names", "Collected", "Links in the CSV"],
        [
            [r["id"], ", ".join(f"`{n}`" for n in r["named"]) or "none", len(r["collected"]), r["csv_links"]]
            for r in trace["tst_rows"]
            if r["named"] or r["csv_links"]
        ],
    )
    out["pack"] = table(
        ["Part", "Path", "Exists", "Command", "What is missing"],
        [
            [p["part"], f"`{p['path']}`", "yes" if p["exists"] else "no", p["command"], p["missing"]]
            for p in trace["pack_cannot_yet"]
        ],
    )
    out["findings"] = table(
        ["Id", "Severity", "Basis", "Lane", "Claim", "Place"],
        [[f["id"], f["severity"], f["basis"], f["lane"], f["claim"], f["place"]] for f in findings],
    )
    return out


BLOCK = re.compile(r"<!-- trace_dry:begin (\w+) -->\n(.*?)<!-- trace_dry:end \1 -->", re.S)


def render(page: str, new: dict[str, str]) -> str:
    seen = {m[0] for m in BLOCK.findall(page)}
    missing = set(new) - seen
    if missing:
        raise SystemExit(f"trace_dry: the page has no block for {sorted(missing)}")
    return BLOCK.sub(
        lambda m: f"<!-- trace_dry:begin {m.group(1)} -->\n{new[m.group(1)]}\n<!-- trace_dry:end {m.group(1)} -->", page
    )


# ----------------------------------------------------------------------------------------------- check


FINDING_KEYS = {"id", "date", "source", "severity", "claim", "lane", "basis", "place", "expected", "happened", "ruling"}


def check(out: Path = OUT, page: Path = PAGE) -> list[str]:
    errors: list[str] = []
    trace = json.loads((out / "trace.json").read_text())
    parsed = json.loads((out / "collection.json").read_text())
    collection = parsed["files"]
    findings = json.loads((out / "findings.json").read_text())
    sample = json.loads((out / "sample-check.json").read_text())
    top = {d["decision"] for d in trace["decisions_uncited_top40"]}
    for s in sample:
        if s["decision"] not in top:
            errors.append(f"sample {s['decision']}: not in the top 40 of trace.json")
        if s["verdict"] not in {"has_test", "no_test_found"}:
            errors.append(f"sample {s['decision']}: verdict {s['verdict']}")
        path = s["evidence"].split(" ", 1)[0]
        if s["verdict"] == "has_test" and not (ROOT / path).exists():
            errors.append(f"sample {s['decision']}: {path} is not on disk")
    # 1. the page's blocks equal what trace.json and findings.json give
    text = page.read_text()
    want = blocks(trace, findings, sample)
    have = {m[0]: m[1].rstrip("\n") for m in BLOCK.findall(text)}
    for name, body in want.items():
        if have.get(name) != body:
            errors.append(f"block {name}: the page differs from the json")
    # 2. the counts equal the rows
    c = trace["counts"]
    reqs = trace["requirements"]
    pairs = {
        "requirements": len(reqs),
        "requirements_with_tests": sum(bool(r["tests"]) for r in reqs),
        "requirements_without_tests": sum(not r["tests"] for r in reqs),
        "safety_core_tests_untied": len(trace["safety_core_untied"]),
        "dead_references": len(trace["dead_references"]),
        "collected_test_names": sum(len(v) for v in collection.values()),
        "collected_files": len(collection),
    }
    for k, v in pairs.items():
        if c.get(k) != v:
            errors.append(f"count {k}: {c.get(k)} in trace.json, {v} from its rows")
    # 3. every test named in trace.json is in the committed collection, and its file is on disk
    names = {f"{f}::{n}" for f, v in collection.items() for n in v}
    for r in trace["criteria"]:
        for f in r["test_files"]:
            if f not in collection:
                errors.append(f"criterion {r['criterion']}: {f} is not in the collection")
            elif not (ROOT / f).exists():
                errors.append(f"criterion {r['criterion']}: {f} is not on disk")
        for t in r["results"]["not_passed"]:
            node = t.rsplit(" [", 1)[0].split("[", 1)[0]
            if node not in names:
                errors.append(f"criterion {r['criterion']}: {node} is not in the collection")
    for r in reqs:
        for f in r["tests"]:
            if not (ROOT / f).exists():
                errors.append(f"requirement {r['id']}: {f} is not on disk")
    for f in trace["safety_core_untied"]:
        if not (ROOT / f).exists():
            errors.append(f"untied: {f} is not on disk")
    # 4. findings are complete
    for f in findings:
        if set(f) != FINDING_KEYS:
            errors.append(f"finding {f.get('id')}: fields {sorted(set(f) ^ FINDING_KEYS)}")
        if not re.fullmatch(r"V15-\d{2}", f.get("id", "")):
            errors.append(f"finding id {f.get('id')}")
        if f.get("basis") not in {"shown", "hypothesis", "not_run"}:
            errors.append(f"finding {f.get('id')}: basis {f.get('basis')}")
        if f.get("severity") not in {"High", "Medium", "Low"}:
            errors.append(f"finding {f.get('id')}: severity {f.get('severity')}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace_dry")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--collection", type=Path, help="a saved `pytest --collect-only -q` output")
    ap.add_argument("--results", type=Path, nargs="*", default=[], help="junit xml files")
    a = ap.parse_args(argv)
    if a.write:
        text = a.collection.read_text() if a.collection else run_collection()
        parsed = parse_collection(text)
        collection = parsed["files"]
        results = read_junit(a.results)
        trace = build(collection, results, [p.name for p in a.results])
        trace["counts"]["collected_items"] = parsed["items"]
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "collection.json").write_text(json.dumps(parsed, indent=0, sort_keys=True) + "\n")
        (OUT / "trace.json").write_text(json.dumps(trace, indent=1, sort_keys=True) + "\n")
        summary = {
            "from": [p.name for p in a.results],
            "outcomes": trace["counts"]["results_outcomes"],
            "not_passed": sorted(k + " " + v for k, v in results.items() if v != "passed"),
        }
        (OUT / "results-summary.json").write_text(json.dumps(summary, indent=1) + "\n")
        findings = json.loads((OUT / "findings.json").read_text()) if (OUT / "findings.json").exists() else []
        sample = json.loads((OUT / "sample-check.json").read_text()) if (OUT / "sample-check.json").exists() else []
        if PAGE.exists():
            PAGE.write_text(render(PAGE.read_text(), blocks(trace, findings, sample)))
        print(f"trace_dry: wrote {rel(OUT)}; {json.dumps(trace['counts'])}")
        return 0
    errors = check()
    for e in errors:
        print(f"trace_dry: {e}")
    print("trace_dry: " + ("clean" if not errors else f"{len(errors)} problem(s)"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
