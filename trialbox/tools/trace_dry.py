"""trace_dry: a first, dry traceability table for plan 8's validation pack (card V-15).

    python -m tools.trace_dry --write --out DIR --results r.xml [--collection C]  # write the measurement into DIR
    python -m tools.trace_dry --write --out DIR --results DIR/results-summary.json  # re-write from the kept outcomes
    python -m tools.trace_dry --write --out DIR --no-results                      # on purpose: no outcome at all
    python -m tools.trace_dry --check [--out DIR]          # internal consistency of the record (the unit test's check)
    python -m tools.trace_dry --check --live [--out DIR]   # also: today's tree still has every test the record names

``--write`` refuses to replace kept outcomes with nothing unless ``--no-results`` is given. ``--collection`` takes a
saved ``pytest --collect-only -q`` output; without it the tool collects. Only the files and test names the table names
are kept (``collection.json``). A criterion with its own measuring command (8: the erasure registry's owed list;
11: the findings register) is read from that command.

Three tools touch traceability (finding V15-10): ``tools/gen_traceability.py`` (the superseded plan's CSV, status
"planned"), ``tools/traceability.py`` (NEW-STD-3: ``@pytest.mark.req`` ids through TB-DS-01 Appendix D, with the
result of a CI run; an artifact, never in the repository) and this one, which reuses the second's Appendix D reader
and adds the criteria, the decisions, the ids in test text and kept results.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tools.traceability import _DS_ID, appendix

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
DS_ID = _DS_ID  # a TB-DS-01 requirement id, as tools/traceability.py reads it
MARK_REQ = re.compile(r"mark\.req\(([^)]*)\)", re.S)
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
        "note": "the withdrawal rule fails: test_v15_withdrawal_data_use.py, strict xfail, V15-06",
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
        "measure": "erasure_owed",
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
        "bears": "the matrix tests; the walks the criterion asks for need compose",
        "note": "no walk ran here: the skips are the e2e walks; the passes are matrix and in-process tests",
    },
    11: {
        "files": ["tests/unit/test_findings_register.py"],
        "rest": "the register itself, read at release (V20)",
        "bears": "the register tool; the register itself is read by its own command",
        "measure": "findings_register",
    },
    12: {
        "files": [],
        "rest": "a stranger with the kit, real hardware, the synthetic hospital (V20)",
        "kind": "untestable",
        "bears": "nothing in the repository",
    },
}

# The three tools on one subject (finding V15-10).
TOOLS: list[dict[str, str]] = [
    {
        "tool": "tools/gen_traceability.py",
        "reads": "TB-PLAN-05 (superseded): URS, RSK, TST ids",
        "writes": "docs/plan/25-traceability.csv, status 'planned' on every row",
        "runs": "CI job checks (warns only)",
    },
    {
        "tool": "tools/traceability.py (NEW-STD-3)",
        "reads": "@pytest.mark.req ids of a run's trace.jsonl, TB-DS-01 Appendix D",
        "writes": "traceability.csv/.md, summary.md: requirement, test, result of that run",
        "runs": "CI unit job, every PR; kept as the artifact 'traceability', never in the repository",
    },
    {
        "tool": "tools/trace_dry.py (V-15)",
        "reads": "plan 8 criteria, both requirement homes, mark.req via Appendix D, "
        "ids in test text, decisions, junit results, the criteria's own commands",
        "writes": "this measurement",
        "runs": "by hand",
    },
]

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
        "missing": "no OQ protocol; CI keeps per-test results of marked tests only as an artifact, tied to no release",
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
        m = re.match(r"^\| ([A-Z][A-Za-z0-9-]+) \|", line)
        if m and DS_ID.fullmatch(m.group(1)):
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


def criterion_status(kind: str, files: list[str], o: dict[str, Any], measure: dict[str, Any] | None = None) -> str:
    if measure and measure["verdict"] == "fails":
        return "fails today by its own command"
    if kind == "untestable" and not files:
        return "not testable in the repository"
    if not files:
        return "no test; shown only by a run outside the repository"
    if o["files_run"] == 0:
        return "has tests; collected, result not run here"
    if any(k != "passed" for k in o["outcomes"]) or o["files_run"] < o["files"]:
        return "has tests, some xfail/skip/fail or not run"
    return "has passing tests that show part of it"


def measure(name: str) -> dict[str, Any]:
    """A criterion's own measuring command, run now; its printed answer is kept (equal on the same tree)."""
    if name == "erasure_owed":
        sys.path[:0] = [str(ROOT / "libs"), str(ROOT / "services")]
        from tb_common import erasure

        n = len(erasure.owed())
        return {
            "command": "tb_common.erasure.owed()",
            "answer": f"{n} entries owed",
            "exit": 0,
            "verdict": "fails" if n else "passes",
        }
    if name == "findings_register":
        env = {**os.environ, "PYTHONPATH": "libs:services:."}
        counts = subprocess.run(
            [sys.executable, "-m", "tools.findings_register", "--counts"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        release = subprocess.run(
            [sys.executable, "-m", "tools.findings_register", "--check", "--release"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "command": "python -m tools.findings_register --counts; --check --release",
            "answer": counts.stdout.strip().splitlines()[0] if counts.stdout.strip() else counts.stderr.strip(),
            "exit": release.returncode,
            "verdict": "fails" if release.returncode else "passes",
        }
    raise ValueError(name)


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
                    why = "file on disk, no test collected" if m.group(1) in on_disk else "no such test file"
                    out.append({"doc": doc, "line": i, "name": m.group(1) + ".py", "why": why})
            for m in TEST_FUNC.finditer(line):
                n = m.group(1)
                if n not in names and n not in files and n not in on_disk:
                    out.append({"doc": doc, "line": i, "name": n, "why": "no such test"})
    return out


def tst_resolution(collection: dict[str, list[str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
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
    ids = {r["id"] for r in out}
    base = {
        "csv_rows": len(links),
        "csv_rows_with_no_test": sum(row["test"] in ("", "-") for row in links),
        "csv_rows_to_a_tst_id": sum(row["test"] in ids for row in links),
        "csv_rows_to_a_tst_naming_no_test": sum(row["test"] in ids for row in links if not stems_for(row, out)),
    }
    return out, base


def stems_for(row: dict[str, str], tst: list[dict[str, Any]]) -> list[str]:
    return next((r["collected"] for r in tst if r["id"] == row["test"]), [])


def marker_ids(text: str) -> set[str]:
    """The spec v4 ids of every ``mark.req(...)`` in a test file's text (read, not imported)."""
    out: set[str] = set()
    for m in MARK_REQ.finditer(text):
        out.update(re.findall(r"[\"']([^\"']+)[\"']", m.group(1)))
    return out


def build(
    collection: dict[str, list[str]], results: dict[str, str], results_from: list[str], commit: str
) -> dict[str, Any]:
    tests = test_texts()
    safety, core = safety_tests()
    plan = criteria_from_plan()
    crit_rows = []
    for n in sorted(plan):
        c = CRITERIA[n]
        files = files_for(c["files"], collection, safety)
        o = outcomes_for(files, results)
        m = measure(c["measure"]) if c.get("measure") else None
        crit_rows.append(
            {
                "criterion": n,
                "title": plan[n]["title"],
                "activities": plan[n]["activities"],
                "kind": c.get("kind", "tests"),
                "test_files": files,
                "tests_bear_on": c["bears"],
                "note": c.get("note", ""),
                "rest_shown_only_by": c["rest"],
                "measure": m,
                "results": o,
                "status": criterion_status(c.get("kind", "tests"), files, o, m),
            }
        )

    reqs = requirements()
    spec_map = appendix(SRS_HOME)
    by_text: dict[str, set[str]] = defaultdict(set)
    by_mark: dict[str, set[str]] = defaultdict(set)
    marks_seen: set[str] = set()
    marked_files: set[str] = set()
    for path, text in tests.items():
        for rid in set(URS.findall(text)) | set(DS_ID.findall(text)):
            by_text[rid].add(path)
        specs = marker_ids(text)
        if specs:
            marked_files.add(path)
        marks_seen |= specs
        for spec in specs:
            for ds in spec_map.get(spec, []):
                by_mark[ds].add(path)
    req_rows: list[dict[str, Any]] = [
        {"id": r, "home": h, "by_mark": sorted(by_mark.get(r, [])), "by_text": sorted(by_text.get(r, []))}
        for r, h in sorted(reqs.items())
    ]
    mapped = {ds for s in marks_seen for ds in spec_map.get(s, []) if ds not in ("Design", "Retired")}
    markers = {
        "spec_ids_in_markers": len(marks_seen),
        "spec_ids_not_in_appendix": sorted(s for s in marks_seen if s not in spec_map),
        "ds_ids_reached": len(mapped),
        "ds_ids_reached_among_requirements": len(mapped & set(reqs)),
        "files_with_markers": len(marked_files),
    }

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
        if not (URS.search(text) or DS_ID.search(text) or test_decs.get(f) or f in marked_files):
            untied.append(f)

    pack = [{**p, "exists": (ROOT / p["path"]).exists()} for p in PACK]
    dead = dead_references(collection)
    tst_rows, csv_base = tst_resolution(collection)
    counts = {
        "results_read": len(results),
        "requirements": len(req_rows),
        "requirements_urs": sum(r["id"].startswith("URS") for r in req_rows),
        "requirements_srs": sum(not r["id"].startswith("URS") for r in req_rows),
        "requirements_marked": sum(bool(r["by_mark"]) for r in req_rows),
        "requirements_cited_in_text": sum(bool(r["by_text"]) for r in req_rows),
        "requirements_marked_or_cited": sum(bool(r["by_mark"] or r["by_text"]) for r in req_rows),
        "requirements_neither": sum(not (r["by_mark"] or r["by_text"]) for r in req_rows),
        "decisions_merged_with_text": len(merged & set(texts)),
        "decisions_cited_by_tests": len(set(dec_tests) & merged & set(texts)),
        "decisions_not_cited": len((merged & set(texts)) - set(dec_tests)),
        "decisions_rule_words_not_cited": len(uncited),
        "safety_core_test_files": len(core_files),
        "safety_core_tests_untied": len(untied),
        "dead_references": len(dead),
        "tst_ids": len(tst_rows),
        "tst_ids_naming_a_collected_test": sum(bool(r["collected"]) for r in tst_rows),
        **csv_base,
        **{k: v for k, v in markers.items() if isinstance(v, int)},
    }
    return {
        "date": "2026-11-17",
        "commit": commit,
        "results_from": results_from,
        "counts": counts,
        "criteria": crit_rows,
        "requirements": req_rows,
        "markers": markers,
        "decisions_uncited_top40": uncited[:40],
        "safety_core_untied": untied,
        "dead_references": dead,
        "tst_rows": tst_rows,
        "pack_cannot_yet": pack,
        "tools": TOOLS,
        "heuristic": {
            "rule_words": RULE_WORDS.pattern,
            "safety_groups": SAFETY_GROUPS,
            "score": "3 per group in the title + 1 per group in the text",
        },
    }


def cut_collection(
    parsed: dict[str, Any], trace: dict[str, Any], results: dict[str, str], sample: list[dict[str, Any]]
) -> dict[str, Any]:
    """The collection kept with the measurement: only the files and test names the table names."""
    files: set[str] = set(trace["safety_core_untied"])
    for r in trace["criteria"]:
        files |= set(r["test_files"])
    for r in trace["requirements"]:
        files |= set(r["by_mark"]) | set(r["by_text"])
    for r in trace["tst_rows"]:
        files |= set(r["collected"])
    files |= {s["evidence"].split(" ", 1)[0] for s in sample if s["evidence"].startswith("tests/")}
    names: dict[str, set[str]] = {f: set() for f in files if f in parsed["files"]}
    for node in results:
        f, _, name = node.partition("::")
        if f in names:
            names[f].add(name.split("[", 1)[0])
    return {
        "items": parsed["items"],
        "files_total": len(parsed["files"]),
        "files": {f: sorted(v) for f, v in sorted(names.items())},
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


def blocks(
    trace: dict[str, Any],
    summary: dict[str, Any],
    collection: dict[str, Any],
    findings: list[dict[str, Any]],
    sample: list[dict[str, Any]],
) -> dict[str, str]:
    c = trace["counts"]
    out: dict[str, str] = {}

    def shown(r: dict[str, Any]) -> str:
        m = r["measure"]
        text = f"`{m['command']}`: {m['answer']}; exit {m['exit']}" if m else ""
        return "; ".join(x for x in (text, r["note"]) if x)

    out["verdict"] = table(
        ["#", "Criterion", "Status", "Test files (run here)", "Outcomes", "Own command; note", "Shown only by"],
        [
            [
                r["criterion"],
                r["title"],
                r["status"],
                f"{r['results']['files']} ({r['results']['files_run']})",
                ", ".join(f"{k} {v}" for k, v in r["results"]["outcomes"].items()) or NOT_RUN,
                shown(r),
                r["rest_shown_only_by"],
            ]
            for r in trace["criteria"]
        ],
    )
    out["provenance"] = (
        f"- Commit of the measurement: `{trace['commit']}`\n- Results read from: "
        + (", ".join(f"`{r}`" for r in trace["results_from"]) or "none")
        + f"\n- Collected test items: {collection['items']}; test files: {collection['files_total']}; "
        + f"per-test results kept: {len(summary['outcomes'])} ("
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(summary["outcomes"].values()).items()))
        + ")"
    )
    out["counts"] = table(["Count", "Value"], [[k.replace("_", " "), v] for k, v in sorted(c.items())])
    out["not_passed"] = (
        "\n".join(f"- criterion {r['criterion']}: `{t}`" for r in trace["criteria"] for t in r["results"]["not_passed"])
        or "- none"
    )
    homes = sorted({r["home"] for r in trace["requirements"]})
    rq = trace["requirements"]
    out["requirements"] = table(
        ["Home", "Requirements", "Marked (mark.req via Appendix D)", "Id in a test's text", "Either", "Neither"],
        [
            [
                h,
                sum(r["home"] == h for r in rq),
                sum(r["home"] == h and bool(r["by_mark"]) for r in rq),
                sum(r["home"] == h and bool(r["by_text"]) for r in rq),
                sum(r["home"] == h and bool(r["by_mark"] or r["by_text"]) for r in rq),
                sum(r["home"] == h and not (r["by_mark"] or r["by_text"]) for r in rq),
            ]
            for h in homes
        ],
    )
    out["requirements_cited"] = table(
        ["Requirement", "Marked by", "Cited in the text of"],
        [
            [
                r["id"],
                ", ".join(f"`{t}`" for t in r["by_mark"]) or "-",
                ", ".join(f"`{t}`" for t in r["by_text"]) or "-",
            ]
            for r in rq
            if r["by_mark"] or r["by_text"]
        ],
    )
    mk = trace["markers"]
    out["markers"] = (
        f"- Spec v4 ids in `mark.req` markers: {mk['spec_ids_in_markers']}, in {mk['files_with_markers']} test files\n"
        f"- TB-DS-01 ids they reach through Appendix D: {mk['ds_ids_reached']}; among this page's requirements: "
        f"{mk['ds_ids_reached_among_requirements']}\n- Marker ids Appendix D does not map: "
        + (", ".join(f"`{s}`" for s in mk["spec_ids_not_in_appendix"]) or "none")
    )
    out["decisions"] = table(
        ["#", "Decision", "Score", "Groups", "Title"],
        [
            [i, d["decision"], d["score"], ", ".join(d["groups"]), d["title"]]
            for i, d in enumerate(trace["decisions_uncited_top40"], 1)
        ],
    )
    truly = sum(s["verdict"] == "no_test_found" for s in sample)
    out["sample"] = table(
        ["Decision", "Checked by hand", "Evidence"],
        [[s["decision"], s["verdict"].replace("_", " "), s["evidence"]] for s in sample],
    ) + (
        f"\n\nSampled: {len(sample)}. Truly without a test: {truly}. Precision of the heuristic "
        f'"no test cites it" as "no test": {truly}/{len(sample)}.'
    )
    out["untied"] = "\n".join(f"- `{f}`" for f in trace["safety_core_untied"]) or "- none"
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d in trace["dead_references"]:
        by_name[(d["name"], d["why"])].append(f"{d['doc']}:{d['line']}")
    out["dead"] = (
        table(["Name", "Why", "Where"], [[f"`{n}`", w, ", ".join(p)] for (n, w), p in sorted(by_name.items())])
        if by_name
        else "None found."
    )
    out["tst"] = table(
        ["TST id", "Test files its row names", "Collected", "Rows in the CSV"],
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
    out["tools"] = table(
        ["Tool", "Reads", "Writes", "Runs in"],
        [[t["tool"], t["reads"], t["writes"], t["runs"]] for t in trace["tools"]],
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


def page_of(out: Path) -> Path:
    return out.parent / f"{out.name}.md"


def check(out: Path = OUT, page: Path | None = None, live: bool = False) -> list[str]:
    """Internal consistency only, unless ``live``: the measurement is a record of one commit, not of today's tree."""
    page = page or page_of(out)
    errors: list[str] = []
    trace = json.loads((out / "trace.json").read_text())
    coll = json.loads((out / "collection.json").read_text())
    collection = coll["files"]
    summary = json.loads((out / "results-summary.json").read_text())
    results: dict[str, str] = summary["outcomes"]
    findings = json.loads((out / "findings.json").read_text())
    sample = json.loads((out / "sample-check.json").read_text())
    # 1. each criterion's outcomes and status, recomputed from the kept per-test results
    for r in trace["criteria"]:
        o = outcomes_for(r["test_files"], results)
        if o != r["results"]:
            errors.append(f"criterion {r['criterion']}: its outcomes differ from results-summary.json")
        st = criterion_status(r["kind"], r["test_files"], o, r["measure"])
        if st != r["status"]:
            errors.append(f"criterion {r['criterion']}: status {r['status']!r}, the results give {st!r}")
    if trace["counts"]["results_read"] != len(results):
        errors.append("count results_read: differs from results-summary.json")
    # 2. the page's blocks equal what the json files give
    want = blocks(trace, summary, coll, findings, sample)
    have = {m[0]: m[1].rstrip("\n") for m in BLOCK.findall(page.read_text())}
    for name, body in want.items():
        if have.get(name) != body:
            errors.append(f"block {name}: the page differs from the json")
    # 3. the counts equal the rows
    c = trace["counts"]
    rq = trace["requirements"]
    pairs = {
        "requirements": len(rq),
        "requirements_marked": sum(bool(r["by_mark"]) for r in rq),
        "requirements_cited_in_text": sum(bool(r["by_text"]) for r in rq),
        "requirements_marked_or_cited": sum(bool(r["by_mark"] or r["by_text"]) for r in rq),
        "requirements_neither": sum(not (r["by_mark"] or r["by_text"]) for r in rq),
        "safety_core_tests_untied": len(trace["safety_core_untied"]),
        "dead_references": len(trace["dead_references"]),
        "tst_ids": len(trace["tst_rows"]),
        "tst_ids_naming_a_collected_test": sum(bool(r["collected"]) for r in trace["tst_rows"]),
    }
    for k, v in pairs.items():
        if c.get(k) != v:
            errors.append(f"count {k}: {c.get(k)} in trace.json, {v} from its rows")
    # 4. every test named is in the committed collection
    named: set[str] = set(trace["safety_core_untied"])
    for r in trace["criteria"]:
        named |= set(r["test_files"])
    for r in rq:
        named |= set(r["by_mark"]) | set(r["by_text"])
    for f in sorted(named - set(collection)):
        errors.append(f"{f} is not in the collection")
    for node in sorted(results):
        f, _, name = node.partition("::")
        if name.split("[", 1)[0] not in collection.get(f, []):
            errors.append(f"{node.split('[', 1)[0]} is not in the collection")
    top = {d["decision"] for d in trace["decisions_uncited_top40"]}
    for s in sample:
        if s["decision"] not in top:
            errors.append(f"sample {s['decision']}: not in the top 40 of trace.json")
        if s["verdict"] not in {"has_test", "no_test_found"}:
            errors.append(f"sample {s['decision']}: verdict {s['verdict']}")
        path = s["evidence"].split(" ", 1)[0]
        if s["verdict"] == "has_test" and path not in collection:
            errors.append(f"sample {s['decision']}: {path} is not in the collection")
    # 5. findings are complete
    for f in findings:
        if set(f) != FINDING_KEYS:
            errors.append(f"finding {f.get('id')}: fields {sorted(set(f) ^ FINDING_KEYS)}")
        if not re.fullmatch(r"V15-\d{2}", f.get("id", "")):
            errors.append(f"finding id {f.get('id')}")
        if f.get("basis") not in {"shown", "hypothesis", "not_run"}:
            errors.append(f"finding {f.get('id')}: basis {f.get('basis')}")
        if f.get("severity") not in {"High", "Medium", "Low"}:
            errors.append(f"finding {f.get('id')}: severity {f.get('severity')}")
    # 6. --live only: today's tree still has what the record names
    if live:
        for f in sorted(named | set(collection)):
            if not (ROOT / f).exists():
                errors.append(f"live: {f} is not on disk")
    return errors


def read_results(paths: list[Path]) -> tuple[dict[str, str], list[str]]:
    """(outcome per test, the junit files they came from); a kept summary names its own sources."""
    out: dict[str, str] = {}
    sources: set[str] = set()
    for p in paths:
        if p.suffix == ".json":
            kept = json.loads(p.read_text())
            out.update(kept["outcomes"])
            sources |= set(kept["from"])
        else:
            out.update(read_junit([p]))
            sources.add(p.name)
    return out, sorted(sources)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace_dry")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--live", action="store_true", help="with --check: also compare with today's tree")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--collection", type=Path, help="a saved `pytest --collect-only -q` output")
    ap.add_argument("--results", type=Path, nargs="*", default=[], help="junit xml files, or a results-summary.json")
    ap.add_argument("--no-results", action="store_true", help="write with no outcome at all, on purpose")
    ap.add_argument("--commit", default="", help="the commit the measurement is of (default: HEAD)")
    a = ap.parse_args(argv)
    out: Path = a.out
    if a.write:
        old = out / "results-summary.json"
        if not a.results and not a.no_results and old.exists() and json.loads(old.read_text())["outcomes"]:
            print(f"trace_dry: {old} holds outcomes; give --results (it may be that file) or --no-results")
            return 2
        results, sources = read_results(a.results)
        text = a.collection.read_text() if a.collection else run_collection()
        parsed = parse_collection(text)
        trace = build(parsed["files"], results, sources, a.commit or git_head())
        sample = json.loads((OUT / "sample-check.json").read_text())
        out.mkdir(parents=True, exist_ok=True)
        coll = cut_collection(parsed, trace, results, sample)
        summary = {"from": trace["results_from"], "outcomes": dict(sorted(results.items()))}
        (out / "collection.json").write_text(json.dumps(coll, indent=0, sort_keys=True) + "\n")
        (out / "trace.json").write_text(json.dumps(trace, indent=1, sort_keys=True) + "\n")
        (out / "results-summary.json").write_text(json.dumps(summary, indent=0, sort_keys=True) + "\n")
        page = page_of(out)
        if page.exists():
            findings = json.loads((out / "findings.json").read_text())
            page.write_text(render(page.read_text(), blocks(trace, summary, coll, findings, sample)))
        print(f"trace_dry: wrote {out}")
        return 0
    errors = check(out, live=a.live)
    for e in errors:
        print(f"trace_dry: {e}")
    print("trace_dry: " + ("clean" if not errors else f"{len(errors)} problem(s)"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
