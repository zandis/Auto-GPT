"""doclint: the repository's documents stay eight, and every link and path in them resolves (TB-PLAN-04 step 9, D-139).

    python tools/doclint.py            # exit 0 unless a set, head or gone problem; part of `make lint`
    python tools/doclint.py --strict   # link and path problems fail too

Checks, on the eight documents and the handover sheets (``docs/handover/*.md``):

* **set**   exactly the eight documents of D-139 exist, and no other Markdown file sits in ``docs/`` (the records
            live in ``docs/reviews``, ``docs/plan``, ``docs/research`` and ``spec/archive``);
* **head**  one ``#`` title on the first line, no skipped heading level, no heading twice in a file;
* **link**  every relative Markdown link reaches a file or folder, and an ``#anchor`` into a Markdown file names
            one of its headings;
* **path**  every repository path written in backticks (``tools/x.py``, ``deploy/...``) exists, or is a file git
            ignores (made on the box: ``deploy/.env``, ``deploy/site/...``);
* **gone**  no file outside the records names a retired document (the 18 → 8 merge of D-139).

Link and path problems are printed as warnings and do not fail the run unless ``--strict`` is given (D-311: a broken
link in a document does not block a code change). The gate-record check of T-661 was removed by D-311.

The records (``docs/reviews``, ``docs/plan``, ``docs/research``, ``spec/``) and ``docs/DECISIONS.md`` (append-only
history) are not checked for retired names: they say what was true when they were written.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/RUNBOOK.md",
    "docs/SECURITY.md",
    "docs/DATA.md",
    "docs/VALIDATION.md",
    "docs/USER_GUIDE.md",
    "docs/DECISIONS.md",
]
# the documents merged away in D-139 (their facts are in the eight, in spec/archive, or listed there as dropped)
RETIRED = [
    "docs/HANDOFF.md",
    "docs/NEXT_SESSION_PROMPT.md",
    "docs/PROGRESS.md",
    "docs/PLAN.md",
    "docs/BENCH.md",
    "docs/CONSENT.md",
    "docs/DEMO_VM.md",
    "docs/HARDENING.md",
    "docs/INTEGRATION_SCENARIOS.md",
    "docs/LANDSCAPE.md",
    "docs/OPEN_DATA.md",
    "docs/SERVING_CONFIG.md",
    "trialbox/SPEC.md",
    "trialbox/SPEC_v3.md",
]
RETIRED_RE = re.compile(
    r"(?<![\w./-])(?:docs/|\.\./|trialbox/)?"
    r"(HANDOFF|NEXT_SESSION_PROMPT|PROGRESS|PLAN|BENCH|CONSENT|DEMO_VM|HARDENING|INTEGRATION_SCENARIOS|LANDSCAPE"
    r"|OPEN_DATA|SERVING_CONFIG|SPEC|SPEC_v3)\.md\b"
)
# files the site puts on the box at install (not in the repository, not ignored by git either)
PLACED = {"deploy/keys/vendor_ed25519.pub"}
RECORDS = (
    "docs/reviews/",
    "docs/plan/",
    "docs/research/",
    "spec/",
    "docs/DECISIONS.md",
    "tools/doclint.py",
    "tests/unit/test_doclint.py",
)
# problem kinds that only warn unless --strict (D-311)
WARN_KINDS = (": link: ", ": path: ")
TOP = ("tools", "docs", "deploy", "services", "libs", "tests", "eval", "spec", "schemas", "rulesets", "models", "site")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
PATH = re.compile(r"`((?:" + "|".join(TOP) + r")/[^`\s]*)`")
FENCE = re.compile(r"^(```|~~~)")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to dashes."""
    s = re.sub(r"[`*_]", "", heading.strip().lower())
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def headings(text: str) -> list[tuple[int, int, str]]:
    out, fenced = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and (m := re.match(r"^(#{1,6}) (.+?)\s*#*\s*$", line)):
            out.append((n, len(m.group(1)), m.group(2)))
    return out


def anchors(path: Path) -> set[str]:
    return {slug(h[2]) for h in headings(path.read_text(encoding="utf-8"))}


def prose(text: str) -> str:
    """The text outside fenced code blocks (commands in a block are not links)."""
    keep, fenced = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            keep.append("")
        else:
            keep.append("" if fenced else line)
    return "\n".join(keep)


def ignored(rel: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT, check=False)
    return r.returncode == 0


def check_doc(rel: str, history: bool = False) -> list[str]:
    """``history``: DECISIONS.md, append-only: old entries name files that were removed later, so only its headings
    are checked."""
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    errs: list[str] = []
    hs = headings(text)
    if not text.startswith("# ") or sum(1 for h in hs if h[1] == 1) != 1:
        errs.append(f"{rel}:1: head: one '# ' title on the first line")
    seen: set[str] = set()
    prev = 1
    for n, level, title in hs:
        if level > prev + 1:
            errs.append(f"{rel}:{n}: head: level {level} after level {prev} ({title})")
        prev = level
        if title in seen:
            errs.append(f"{rel}:{n}: head: twice in this file ({title})")
        seen.add(title)
    body = "" if history else prose(text)
    for n, line in enumerate(body.splitlines(), 1):
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto:
                continue
            file, _, anchor = target.partition("#")
            dest = (path.parent / file).resolve() if file else path
            if not dest.exists():
                errs.append(f"{rel}:{n}: link: {target} does not exist")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                errs.append(f"{rel}:{n}: link: #{anchor} is not a heading of {dest.relative_to(ROOT)}")
        for p in PATH.findall(line):
            if any(c in p for c in "<>*{}$…|") or "..." in p:
                continue
            p = re.sub(r"(:\d+([-–]\d+)?)$", "", p.rstrip(".,;:)"))
            if not (ROOT / p).exists() and p not in PLACED and not ignored(p):
                errs.append(f"{rel}:{n}: path: {p} does not exist")
    return errs


def check_set() -> list[str]:
    errs = [f"{d}: set: missing" for d in DOCS if not (ROOT / d).exists()]
    extra = sorted(p.name for p in (ROOT / "docs").glob("*.md") if f"docs/{p.name}" not in DOCS)
    errs += [f"docs/{x}: set: not one of the eight documents (merge it, or move it to a record folder)" for x in extra]
    return errs


def check_gone() -> list[str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    files += subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.split()  # fmt: skip
    errs = []
    for rel in sorted(set(files)):
        if rel.startswith(RECORDS) or not (ROOT / rel).is_file():
            continue
        if Path(rel).suffix.lower() in (".png", ".jpg", ".pdf", ".gz", ".parquet", ".xlsx", ".docx", ".zip", ".ttf"):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for m in RETIRED_RE.finditer(line):
                errs.append(f"{rel}:{n}: gone: names {m.group(0)}, merged away in D-139 (see its document map)")
    return errs


def main(argv: list[str] | None = None) -> int:
    strict = "--strict" in (sys.argv[1:] if argv is None else argv)
    errs = check_set()
    for rel in DOCS + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs" / "handover").glob("*.md")):
        if (ROOT / rel).exists():
            errs += check_doc(rel, history=rel == "docs/DECISIONS.md")
    errs += check_gone()
    warns = [] if strict else [e for e in errs if any(k in e for k in WARN_KINDS)]
    errs = [e for e in errs if e not in warns]
    for w in warns:
        print(f"warning: {w}")
    for e in errs:
        print(e)
    summary = "clean" if not errs else f"{len(errs)} problem(s)"
    print(f"doclint: {summary}, {len(warns)} warning(s) ({len(DOCS)} documents)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
