"""doclint: the repository's documents stay eight, and every link and path in them resolves (TB-PLAN-04 step 9, D-139).

    python tools/doclint.py            # exit 0 unless a set, head or gone problem; part of `make lint`
    python tools/doclint.py --strict   # link and path problems fail too
    python tools/doclint.py --write    # rewrite the indexes of the four documents kept as section files (T-669)

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

**Section files (T-669, D-352).** Four hot documents are kept as one file per numbered section, so two branches that
each change or add a section touch different files:

    docs/RUNBOOK.md     -> docs/runbook/NN-<slug>.md
    docs/DATA.md        -> docs/data/NN-<slug>.md
    docs/USER_GUIDE.md  -> docs/user-guide/NN-<slug>.md
    docs/SECURITY.md    -> docs/security/NN-<slug>.md

A section file starts ``# N. Title``; any other ``NN-<slug>.md`` in the folder is a part of section N (its title is
free). The document itself (the hub) keeps its title and opening and a generated index between two marker lines: one
``## N. Title`` heading per section (so the old links ``RUNBOOK.md#9-proof-of-concept-with-docker`` still resolve) and
a line that links the file, its parts and its ``##`` headings. A hub may hold a ``## Section numbers`` table
(RUNBOOK does): every number used must have a row, and a row with no file yet gets a placeholder block in the index,
so the branch that writes a reserved section changes only its own block.

    python -m tools.doclint --write             # rewrite the four indexes from the section files
    python -m tools.doclint --whole RUNBOOK     # print the document as one file (for a bundle or a printout)

More checks, all failing: **index** (the committed index differs from the files: run ``--write``), **number**
(a number written twice, a file whose name and title disagree, a part with no section, a RUNBOOK number with no row in
the table) and **set** (a file in a section folder that is not ``NN-<slug>.md``). Every section file also gets the
head, link and path checks of the documents.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
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
# the hot documents kept as one file per section (T-669): hub -> its section folder
HUBS = {
    "docs/RUNBOOK.md": "docs/runbook",
    "docs/DATA.md": "docs/data",
    "docs/USER_GUIDE.md": "docs/user-guide",
    "docs/SECURITY.md": "docs/security",
}
BEGIN = "<!-- index: generated by `python -m tools.doclint --write` from the section files; do not edit by hand -->"
END = "<!-- end of the generated index -->"
NUMBERS = "## Section numbers"
SECTION_NAME = re.compile(r"^(\d{2})-[a-z0-9][a-z0-9-]*\.md$")
SECTION_TITLE = re.compile(r"^# (\d+)\. (.+?)\s*$")
TABLE_ROW = re.compile(r"^\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|")
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


@dataclass
class Section:
    number: int
    title: str = ""
    file: str = ""  # path relative to the hub's folder (``runbook/09-....md``); empty while only reserved
    subs: list[str] = field(default_factory=list)  # its ``##`` headings
    parts: list[tuple[str, str]] = field(default_factory=list)  # (title, path) of the other files of this number
    reserved: str = ""  # the title the table gives a number that has no file yet


def numbers_table(hub_text: str) -> dict[int, tuple[str, str]]:
    """The ``## Section numbers`` table of a hub: number -> (title, holder). Empty when the hub has none."""
    if NUMBERS not in hub_text:
        return {}
    rows: dict[int, tuple[str, str]] = {}
    for line in hub_text.split(NUMBERS, 1)[1].splitlines():
        if line.startswith("#"):
            break
        if m := TABLE_ROW.match(line):
            rows[int(m.group(1))] = (m.group(2).strip(), m.group(3).strip())
    return rows


def sections(hub: str) -> tuple[dict[int, Section], list[str]]:
    """The sections of one hub, read from its folder, and the problems found on the way."""
    folder = ROOT / HUBS[hub]
    rel_folder = Path(HUBS[hub]).relative_to(Path(hub).parent).as_posix()
    out: dict[int, Section] = {}
    errs: list[str] = []
    parts: list[tuple[int, str, str]] = []
    for f in sorted(folder.glob("*")) if folder.is_dir() else []:
        rel = f"{HUBS[hub]}/{f.name}"
        m = SECTION_NAME.match(f.name)
        if not f.is_file() or not m:
            errs.append(f"{rel}: set: a section folder holds only NN-<slug>.md files")
            continue
        number = int(m.group(1))
        text = f.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        link = f"{rel_folder}/{f.name}"
        t = SECTION_TITLE.match(first)
        if not t:
            parts.append((number, first.lstrip("# ").strip() or f.name, link))
            continue
        if int(t.group(1)) != number:
            errs.append(f"{rel}:1: number: the title says §{t.group(1)}, the file name says §{number}")
            continue
        if number in out:
            errs.append(f"{rel}: number: §{number} is written twice ({out[number].file} and {link})")
            continue
        subs = [h[2] for h in headings(text) if h[1] == 2]
        out[number] = Section(number, t.group(2), link, subs)
    for number, title, link in parts:
        if number not in out:
            errs.append(f"{HUBS[hub]}/{Path(link).name}: number: a part of §{number}, which has no section file")
        else:
            out[number].parts.append((title, link))
    table = numbers_table((ROOT / hub).read_text(encoding="utf-8")) if (ROOT / hub).exists() else {}
    if table:
        for number in out:
            if number not in table:
                errs.append(f"{hub}: number: §{number} has no row in the section-numbers table")
        for number, (title, holder) in table.items():
            if number not in out:
                out[number] = Section(number, reserved=f"{title} (reserved for {holder})")
    return dict(sorted(out.items())), errs


def render_index(hub: str) -> str:
    """The generated index of one hub, marker lines included."""
    blocks = [BEGIN]
    for s in sections(hub)[0].values():
        if not s.file:
            blocks += [f"## {s.number}. {s.reserved}", "Not written yet: the number is held in the table below."]
            continue
        line = f"File: [{s.file}]({s.file})."
        if s.subs:
            line += " In it: " + ", ".join(f"[{h}]({s.file}#{slug(h)})" for h in s.subs) + "."
        if s.parts:
            line += " Parts: " + ", ".join(f"[{t}]({p})" for t, p in s.parts) + "."
        blocks += [f"## {s.number}. {s.title}", line]
    blocks.append(END)
    return "\n\n".join(blocks)


def write_index(hub: str) -> bool:
    """Rewrite the index of ``hub`` in place; True when the file changed."""
    path = ROOT / hub
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{hub}: no index markers; put the two marker lines where the index goes")
    head, rest = text.split(BEGIN, 1)
    new = head + render_index(hub) + rest.split(END, 1)[1]
    if new != text:
        path.write_text(new, encoding="utf-8")
    return new != text


def check_sections(hub: str) -> list[str]:
    """Index, number and set problems of one hub, then the document checks of each of its section files."""
    if not (ROOT / hub).exists():
        return []
    errs = sections(hub)[1]
    text = (ROOT / hub).read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        errs.append(f"{hub}:1: index: the generated-index marker lines are missing")
    elif BEGIN + text.split(BEGIN, 1)[1].split(END, 1)[0] + END != render_index(hub):
        errs.append(f"{hub}:1: index: out of date with {HUBS[hub]}/ (run python -m tools.doclint --write)")
    for f in sorted((ROOT / HUBS[hub]).glob("*.md")) if (ROOT / HUBS[hub]).is_dir() else []:
        errs += check_doc(f"{HUBS[hub]}/{f.name}")
    return errs


def whole(hub: str) -> str:
    """The document as one file: the hub's opening, then every section file one heading level down."""
    text = (ROOT / hub).read_text(encoding="utf-8")
    out = [text.split(BEGIN, 1)[0].rstrip()]
    for s in sections(hub)[0].values():
        for rel in [s.file] + [p for _, p in s.parts] if s.file else []:
            body, fenced = [], False
            for line in (ROOT / Path(hub).parent / rel).read_text(encoding="utf-8").splitlines():
                if FENCE.match(line):
                    fenced = not fenced
                body.append("#" + line if not fenced and re.match(r"^#{1,5} ", line) else line)
            out.append("\n".join(body).strip())
    return "\n\n".join(out) + "\n"


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
    args = sys.argv[1:] if argv is None else argv
    if "--whole" in args:
        name = args[args.index("--whole") + 1]
        hub = next((h for h in HUBS if Path(h).stem == name or h == name), None)
        if hub is None:
            print(f"doclint: --whole takes one of {', '.join(Path(h).stem for h in HUBS)}", file=sys.stderr)
            return 2
        sys.stdout.write(whole(hub))
        return 0
    strict = "--strict" in args
    if "--write" in args:
        for hub in HUBS:
            if write_index(hub):
                print(f"doclint: wrote the index of {hub}")
    errs = check_set()
    for rel in DOCS + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs" / "handover").glob("*.md")):
        if (ROOT / rel).exists():
            errs += check_doc(rel, history=rel == "docs/DECISIONS.md")
    for hub in HUBS:
        errs += check_sections(hub)
    errs += check_gone()
    warns = [] if strict else [e for e in errs if any(k in e for k in WARN_KINDS)]
    errs = [e for e in errs if e not in warns]
    for w in warns:
        print(f"warning: {w}")
    for e in errs:
        print(e)
    summary = "clean" if not errs else f"{len(errs)} problem(s)"
    print(f"doclint: {summary}, {len(warns)} warning(s) ({len(DOCS)} documents, {len(HUBS)} kept as section files)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
