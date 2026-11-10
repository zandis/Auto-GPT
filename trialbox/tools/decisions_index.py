"""decisions_index: one decision number, one text, one owner (T-002, D-306, CR-077).

    python -m tools.decisions_index            # print the index of every decision number (Markdown, to stdout)
    python -m tools.decisions_index --check    # exit 1 on any problem below; CI job `docs`

A decision's text lives in one of two places: the frozen log ``docs/DECISIONS.md`` (entries D-01 to D-270, each a
paragraph that starts ``**D-nnn``) or one file ``docs/decisions/D-nnn-<slug>.md``. Who may use a number is written in
``docs/decisions/REGISTRY.md``: one table row per number or per range ``D-aaa..D-bbb``, with a state:

* ``merged``    the text is on master (the log or a file);
* ``reserved``  held by a card, a pull request or a fix group; a file may land under it (the integrator later flips
                the row to ``merged``; a pull request never edits the registry, so two of them never conflict there);
* ``unused``    never to be used (a gap, or a reservation that was voided);
* ``missing``   cited on master, never written: the text is owed.

``--check`` fails on: a number written twice (in the log, in two files, or in the log and a file); a decision file
whose name and first line disagree; a decision file with no registry row; a log entry whose row is not ``merged``
(the log is frozen: a new decision is a file); a ``merged`` row with no text, an ``unused`` or ``missing`` row with
text; a number between D-01 and the registry's highest that no row covers (a gap must be marked); a number that two
rows cover; a file under a row that names cards (``T-nnn``) when the file's opening names none of them.

The index is printed, never committed: a committed index would be one more file that every decision branch edits.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATES = ("merged", "reserved", "unused", "missing")
ENTRY = re.compile(r"^\*\*D-(\d+)\b")  # a log entry starts a line with the bold number
FILE = re.compile(r"^D-(\d+)-[a-z0-9][a-z0-9-]*\.md$")
NUM = re.compile(r"D-(\d+)\b")
CARD = re.compile(r"\bT-\d+[a-z]?\b")
ROW_NUMBER = re.compile(r"^D-(\d+)(?:\.\.D-(\d+))?$")
OPENING = 1200  # characters of a file's start that must name its card


@dataclass
class Row:
    first: int
    last: int
    state: str
    holder: str
    note: str
    line: int


@dataclass
class Corpus:
    log: dict[int, list[tuple[int, str]]] = field(default_factory=dict)  # number -> [(line, title)]
    files: dict[int, list[Path]] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _title(line: str) -> str:
    t = re.sub(r"^#+\s*", "", line.strip()).replace("**", "")
    t = re.sub(r"^D-\d+\s*", "", t)
    return (t[:100] + "…") if len(t) > 101 else t


def read_log(path: Path, c: Corpus) -> None:
    if not path.exists():
        return
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if m := ENTRY.match(line):
            c.log.setdefault(int(m.group(1)), []).append((n, _title(line)))


def read_files(folder: Path, c: Corpus) -> None:
    for p in sorted(folder.glob("D-*.md")):
        m = FILE.match(p.name)
        if not m:
            c.errors.append(f"{p.name}: name: a decision file is D-<number>-<slug>.md (lower case, dashes)")
            continue
        num = int(m.group(1))
        first = next((ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()), "")
        head = NUM.search(first)
        if not head or int(head.group(1)) != num:
            c.errors.append(f"{p.name}: head: the first line must name D-{m.group(1)} (it says {first[:60]!r})")
        c.files.setdefault(num, []).append(p)


def read_registry(path: Path, c: Corpus) -> None:
    if not path.exists():
        c.errors.append(f"{path.name}: missing")
        return
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        cells = [x.strip() for x in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) < 4 or not cells[0].startswith("D-"):
            continue
        m = ROW_NUMBER.match(cells[0])
        if not m:
            c.errors.append(f"REGISTRY.md:{n}: row: number {cells[0]!r} is not D-nnn or D-aaa..D-bbb")
            continue
        first, last = int(m.group(1)), int(m.group(2) or m.group(1))
        state = cells[1].strip("`")
        if last < first:
            c.errors.append(f"REGISTRY.md:{n}: row: range {cells[0]} runs backwards")
        elif state not in STATES:
            c.errors.append(f"REGISTRY.md:{n}: row: state {state!r} is not one of {', '.join(STATES)}")
        else:
            c.rows.append(Row(first, last, state, cells[2], cells[3], n))


def load(root: Path = ROOT) -> Corpus:
    c = Corpus()
    read_log(root / "docs" / "DECISIONS.md", c)
    read_files(root / "docs" / "decisions", c)
    read_registry(root / "docs" / "decisions" / "REGISTRY.md", c)
    return c


def check(c: Corpus) -> list[str]:
    errs = list(c.errors)
    for num, hits in sorted(c.log.items()):
        if len(hits) > 1:
            errs.append(f"D-{num}: twice in DECISIONS.md (lines {', '.join(str(h[0]) for h in hits)})")
    for num, paths in sorted(c.files.items()):
        if len(paths) > 1:
            errs.append(f"D-{num}: two files: {', '.join(p.name for p in paths)}")
        if num in c.log:
            errs.append(f"D-{num}: in DECISIONS.md (line {c.log[num][0][0]}) and in {paths[0].name}")
    owner: dict[int, Row] = {}
    for r in c.rows:
        for num in range(r.first, r.last + 1):
            if num in owner:
                errs.append(f"D-{num}: two registry rows (lines {owner[num].line} and {r.line})")
            owner[num] = r
    top = max(owner, default=0)
    gaps = [num for num in range(1, top + 1) if num not in owner]
    if gaps:
        errs.append(f"registry: no row for {_ranges(gaps)} (a gap is a row marked unused)")
    for num, hits in sorted(c.log.items()):
        row = owner.get(num)
        if row is None:
            errs.append(f"D-{num}: DECISIONS.md line {hits[0][0]} has no registry row")
        elif row.state != "merged":
            errs.append(
                f"D-{num}: DECISIONS.md line {hits[0][0]} is a new log entry (row {row.state}); the log is frozen, "
                f"write docs/decisions/D-{num}-<slug>.md"
            )
    for num, paths in sorted(c.files.items()):
        row = owner.get(num)
        if row is None:
            errs.append(f"D-{num}: {paths[0].name} has no row in REGISTRY.md (the integrator adds it)")
            continue
        if row.state in ("unused", "missing"):
            errs.append(f"D-{num}: {paths[0].name} lands on a row marked {row.state}")
        cards = set(CARD.findall(row.holder))
        if cards and row.state in ("reserved", "merged"):
            opening = paths[0].read_text(encoding="utf-8")[:OPENING]
            if not cards & set(CARD.findall(opening)):
                errs.append(
                    f"D-{num}: {paths[0].name} does not name its card ({', '.join(sorted(cards))}) in its opening; "
                    "the number belongs to that card"
                )
    for r in c.rows:
        nums = range(r.first, r.last + 1)
        written = [n for n in nums if n in c.log or n in c.files]
        if r.state == "merged" and len(written) != len(nums):
            unwritten = [n for n in nums if n not in c.log and n not in c.files]
            errs.append(f"REGISTRY.md:{r.line}: merged, but {_ranges(unwritten)} has no text")
        if r.state in ("unused", "missing") and written:
            errs.append(f"REGISTRY.md:{r.line}: {r.state}, but {_ranges(written)} has text")
    return errs


def _ranges(nums: list[int]) -> str:
    runs: list[list[int]] = []
    for n in sorted(nums):
        if runs and runs[-1][1] == n - 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ", ".join(f"D-{a}" if a == b else f"D-{a}..D-{b}" for a, b in runs)


def index(c: Corpus) -> str:
    owner = {n: r for r in c.rows for n in range(r.first, r.last + 1)}
    lines = ["| Number | State | Holder | Title | Where |", "| --- | --- | --- | --- | --- |"]
    for num in sorted(set(owner) | set(c.log) | set(c.files)):
        r = owner.get(num)
        if num in c.files:
            p = c.files[num][0]
            first = next((ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()), "")
            title, where, state = _title(first), f"docs/decisions/{p.name}", "merged"
        elif num in c.log:
            title, where, state = c.log[num][0][1], f"DECISIONS.md:{c.log[num][0][0]}", "merged"
        else:
            title, where, state = (r.note if r else ""), "", (r.state if r else "?")
        lines.append(f"| D-{num} | {state} | {r.holder if r else ''} | {title.replace('|', '/')} | {where} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on a duplicate, a gap or a file with no row")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    c = load(args.root)
    if not args.check:
        sys.stdout.write(index(c))
        return 0
    errs = check(c)
    for e in errs:
        print(e)
    written = len(set(c.log) | set(c.files))
    print(f"decisions_index: {'clean' if not errs else f'{len(errs)} problem(s)'} ({written} decisions written)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
