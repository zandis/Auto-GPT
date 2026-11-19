"""findings_register: the one findings register is well formed, and says what is open (plan 8 criterion 11, D-1180).

    python -m tools.findings_register --check             # exit 1 on a malformed line or row; `make lint`, CI `checks`
    python -m tools.findings_register --check --release   # also exit 1 while a finding stops the release (criterion 11)
    python -m tools.findings_register --counts            # open High, open Medium, open Low, total (printed, not kept)
    python -m tools.findings_register --add-from FILE     # append a card's findings.json to the register
    python -m tools.findings_register --resolve           # after a merge: fold the copies of a row whose state changed
    python -m tools.findings_register --sync-states       # move a row's state forward to its findings file's state

The register is ``docs/handover/findings-register.md``. Its head is prose. From the first card heading on, the file is
nothing but card sections, each a heading ``## <card>: <words>``, blank lines, the header and rule

    | Id | Date found | Source | Severity | Claim | Lane | Basis | State |
    | --- | --- | --- | --- | --- | --- | --- | --- |

and one or more rows, one per line, with no blank line among them. Between one table and the next card heading only
blank lines may stand. ``--check`` is strict, so that it cannot read fewer rows than the file holds without failing:

* in the head, a ``|`` outside a code span is an error (a table there would be read by no one);
* below the first card heading, every line that is not blank, a card heading, the header, the rule or a row of a
  table is an error; a card heading with no table, a table with no row, a second section of one card, a header that
  is not exactly the register's, a rule missing after it, and a row that does not start and end with ``|`` are errors.

A parse error names its line (``findings-register.md:57: ...``); a row error names the line and the id
(``findings-register.md:59: row H20-F-01: ...``). The rules of a row:

* **id**        unique in the file, of the form ``<card>-<local>`` with ``<card>`` the heading's card; lane V's cards
                (``V2``) take a number of two or more digits (``V2-07``); other cards keep the id their source gave
                (``H20-F-16``, ``H22-no-host-tree``) or the register's two-digit number in the source's order
                (``H18-01``);
* **date**      a real calendar date written ``YYYY-MM-DD``;
* **source**    a relative Markdown link ``[text](path)`` to a file (not a folder) inside the ``trialbox/`` tree;
* **severity**  ``High``, ``Medium`` or ``Low``, followed by `` (mapped)`` when the register mapped it from another
                scale;
* **claim**     one line, not empty;
* **lane**      one of ``LANES``;
* **basis**     ``shown``, ``hypothesis``, ``not_run``, or ``not stated`` (a seeded row whose source does not say);
* **state**     exactly one of ``open``; ``card issued #<pr>``; ``fixed <sha>`` (7 to 40 lower-case hex) optionally
                followed by ``, seen closed by <who> on <date>``; ``not a defect: <why>``. The sha and the PR number are
                checked for their form only, not looked up.

``--release`` is criterion 11 of plan 8 ("No High finding is open ... every Medium has a card done or a recorded
ruling"; "a finding closes when it is seen closed"): a High passes only as ``fixed <sha>, seen closed by ... on
<date>`` or ``not a defect: ...``; a Medium passes only as ``fixed <sha>`` or ``not a defect: ...`` (``card issued``
is not a card done); a Low never stops the release. It is not wired into CI.

The counts are printed by ``--counts``, never written into the file: a counts line in the file would be changed by
every pull request that adds a row, and so would conflict in every pair of them (D-1180). "Open" in the counts is a
row in state ``open`` or ``card issued``.

**Merges.** The file is merged as a union (``.gitattributes``): rows that two branches append are both kept. When one
branch changes a row's state and the other changes a neighbouring row or appends next to it, the union keeps both
copies of the changed row, and ``--check`` fails on the id used twice. ``--resolve`` folds such copies: when the
copies of an id are the same in every cell but the state, and exactly one state other than ``open`` is among them,
one row with that state stays in the place of the first copy (copies identical in every cell are folded too). Any
other duplicate (a different claim or severity, or two different states other than ``open``) is left for a person.

``--add-from FILE`` reads a card's findings file and appends its rows to the card's table (made at the end of the
file when the card has none). The file is the form of ``docs/plan/measurements/runbook-install-2026-11-17/
findings.json`` (an object with a ``findings`` list) with these fields added:

    {
      "card": "V2",                              # the register's card; else the part of the first id before "-"
      "title": "the lake's erasure, checked",   # optional: the words of a new heading "## V2: <title>"
      "date": "2026-11-18",                      # optional: the default for each finding's "date"
      "source": "docs/plan/measurements/v2-erasure-2026-11-18.md",  # optional default, a path below trialbox/
      "findings": [
        {"id": "V2-07", "date": "2026-11-18", "source": "docs/...md", "severity": "High",
         "claim": "one line", "lane": "B2", "basis": "shown",
         "state": "open",                         # optional, "open" when absent
         "place": "...", "expected": "...", "happened": "..."}   # any other field is the page's and is not copied
      ]
    }

Every field the register takes is a string with no line break or control character. ``source`` is a relative path
from the ``trialbox/`` folder to an existing file inside it; the row gets a link relative to the register. A ``|``
in a claim is written ``\\|`` (one already written so is kept). Every new row is checked with the rules above before
anything is written; an id already in the register, or twice in the file, is refused and nothing is written. After
writing, the whole register is checked again and the old file is put back if the check fails. The rows are appended
in the file's order; nothing is sorted or rewritten, so two cards' additions touch different lines.

**States follow their findings files.** ``--add-from`` refuses an id already in the register, so it cannot carry a
later state. ``--sync-states`` reads every findings file under ``trialbox/docs/`` (any ``.json`` with a ``findings``
list) and, for each registered id a finding there gives with a ``state`` field, rewrites only that row's state cell,
in place, to the file's state, printing ``<id>: <old> -> <new>``; nothing else in the file changes. It moves a row
only forward (``open``, then ``card issued``, then ``fixed`` or ``not a defect``). It never touches a row seen closed
(lane R sets that), never moves a row back (a lane may close a row in the register before its file says so), and
leaves two different states of one rank (``fixed`` against ``not a defect``, or two shas) and an id that two files
give differently for a person; each such row is printed as ``not synced`` and is not an error. A state the register
cannot take is refused (exit 1) and that row is not written. A row whose id no findings file gives, or whose finding
has no ``state`` field (the seeded rows, a source page with no findings file), is not synced and not checked.
``--check`` fails on a row that ``--sync-states`` would move (``... is behind its findings file's ...``) and on a
refused source state, so a stale row cannot return unnoticed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "handover" / "findings-register.md"

COLUMNS = ("Id", "Date found", "Source", "Severity", "Claim", "Lane", "Basis", "State")
HEADER = "| " + " | ".join(COLUMNS) + " |"
RULE = "| " + " | ".join("---" for _ in COLUMNS) + " |"

LANES = ("A2", "B2", "C2", "C2a", "C2b", "D", "E", "G", "H", "J", "K", "W", "R", "Int", "V")
SEVERITIES = ("High", "Medium", "Low")
BASES = ("shown", "hypothesis", "not_run", "not stated")

CARD_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
LANE_V_CARD_RE = re.compile(r"^V\d+$")
LOCAL_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
HEADING_RE = re.compile(r"^## (?P<card>[^:\s]+): \S")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"^\[[^\]]+\]\((?P<path>[^)\s#]+)(?:#[^)\s]*)?\)$")
SEVERITY_RE = re.compile(r"^(?P<level>High|Medium|Low)(?P<mapped> \(mapped\))?$")
STATE_RES = {
    "open": re.compile(r"^open$"),
    "card issued": re.compile(r"^card issued #(?P<pr>[1-9]\d*)$"),
    "fixed": re.compile(
        r"^fixed (?P<sha>[0-9a-f]{7,40})(?:, seen closed by (?P<who>[^,]+?) on (?P<seen>\d{4}-\d{2}-\d{2}))?$"
    ),
    "not a defect": re.compile(r"^not a defect: (?P<why>\S.*)$"),
}
CELL_SPLIT = re.compile(r"(?<!\\)\|")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
CODE_SPAN = re.compile(r"`[^`]*`")
CONTROL = re.compile(r"[\x00-\x1f\x7f  ]")


def real_date(text: str) -> bool:
    if not DATE_RE.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


@dataclass
class Row:
    line: int
    card: str
    cells: dict[str, str]

    @property
    def id(self) -> str:
        return self.cells["Id"]

    @property
    def level(self) -> str:
        m = SEVERITY_RE.match(self.cells["Severity"])
        return m.group("level") if m else ""

    @property
    def state(self) -> str:
        for name, rx in STATE_RES.items():
            if rx.match(self.cells["State"]):
                return name
        return ""

    @property
    def seen_closed(self) -> bool:
        m = STATE_RES["fixed"].match(self.cells["State"])
        return bool(m and m.group("seen"))


@dataclass
class Register:
    path: Path
    lines: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: card -> the line number of the last row of its table (a new row goes after it)
    table_end: dict[str, int] = field(default_factory=dict)


def root_of(register_path: Path) -> Path:
    """The ``trialbox/`` folder of a register at ``<root>/docs/handover/<name>.md``."""
    return register_path.resolve().parents[2]


def split_cells(line: str) -> list[str]:
    body = line.strip()[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in CELL_SPLIT.split(body)]


def parse(path: Path = REGISTER) -> Register:
    reg = Register(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        reg.errors.append(f"{path}: cannot be read: {exc}")
        return reg
    reg.lines = text.removeprefix("﻿").splitlines()
    name = path.name

    def err(n: int, msg: str) -> None:
        reg.errors.append(f"{name}:{n}: {msg}")

    # head | heading (blank lines, then the header) | header (the rule) | rule (a row) | rows | between | skip
    phase = "head"
    card = "?"
    card_line = 0
    seen: dict[str, int] = {}
    for i, raw in enumerate(reg.lines):
        n = i + 1
        line = raw.rstrip()
        blank = not line.strip()
        heading = HEADING_RE.match(line)
        if phase == "head" and not heading:
            if "|" in CODE_SPAN.sub("", line):
                err(n, "a '|' in the head, before the first card heading: a table belongs under '## <card>: <words>'")
            continue
        if heading:
            if phase in ("heading", "header", "rule"):
                err(card_line, f"card {card}'s heading has no table with a row under it")
            card, card_line = heading.group("card"), n
            if not CARD_RE.match(card):
                err(n, f"'{card}' is not a card name (letters and digits, no hyphen: V2, H20)")
            if card in seen:
                err(n, f"card {card} has a second section (first at line {seen[card]}): add rows to the first")
            seen.setdefault(card, n)
            phase = "heading"
            continue
        if phase == "skip":
            continue
        if blank:
            if phase == "header":
                err(n, f"the register header must be followed at once by {RULE}")
                phase = "skip"
            elif phase == "rule":
                err(n, f"card {card}'s table: a blank line after the rule (a table has rows and no blank line in it)")
                phase = "between"
            elif phase == "rows":
                phase = "between"
            continue
        if phase == "heading":
            if line.strip() == HEADER:
                phase = "header"
            else:
                err(n, f"after the heading of card {card} the only line allowed is the register header {HEADER}")
                phase = "skip"
        elif phase == "header":
            if split_cells(line) == ["---"] * len(COLUMNS) and line.strip().startswith("|"):
                phase = "rule"
            else:
                err(n, f"the register header must be followed at once by {RULE}")
                phase = "skip"
        elif phase in ("rule", "rows"):
            stripped = line.strip()
            if not stripped.startswith("|") or not stripped.endswith("|") or stripped.endswith("\\|"):
                err(n, f"inside card {card}'s table, a line that is not a row (a row starts and ends with '|')")
                phase = "skip"
                continue
            cells = split_cells(stripped)
            if len(cells) != len(COLUMNS):
                err(
                    n, f"row {cells[0]}: {len(cells)} cells, the register has {len(COLUMNS)} (a '|' in a cell is '\\|')"
                )
            else:
                reg.rows.append(Row(n, card, dict(zip(COLUMNS, cells, strict=True))))
            reg.table_end[card] = n
            phase = "rows"
        else:  # between
            err(n, f"after card {card}'s table only blank lines may stand before the next card heading")
            phase = "skip"
    if phase in ("heading", "header", "rule"):
        err(card_line, f"card {card}'s heading has no table with a row under it")
    if not seen:
        reg.errors.append(f"{name}: no card heading '## <card>: <words>': the register holds no table")
    return reg


def id_problem(card: str, rid: str) -> str | None:
    if not rid.startswith(card + "-"):
        return f"the id must start with its heading's card '{card}-'"
    local = rid[len(card) + 1 :]
    if LANE_V_CARD_RE.match(card):
        if not re.fullmatch(r"\d{2,}", local):
            return f"a lane V id is the card and a number of two or more digits ({card}-07)"
    elif not LOCAL_RE.match(local):
        return "the part after the card is letters, digits and single hyphens (the source's own id)"
    return None


def source_problem(link_path: str, folder: Path, root: Path) -> str | None:
    if link_path.startswith("/") or ":" in link_path:
        return f"source '{link_path}' is not a relative path"
    target = (folder / link_path).resolve()
    if not target.is_relative_to(root.resolve()):
        return f"source '{link_path}' leaves the trialbox/ tree"
    if not target.is_file():
        return f"source '{link_path}' is not an existing file (from {folder.name}/)"
    return None


def row_problems(row: Row, folder: Path, root: Path) -> list[str]:
    c = row.cells
    out = []
    if (p := id_problem(row.card, c["Id"])) is not None:
        out.append(p)
    if not real_date(c["Date found"]):
        out.append(f"date found '{c['Date found']}' is not a real date written YYYY-MM-DD")
    m = LINK_RE.match(c["Source"])
    if not m:
        out.append(f"source '{c['Source']}' is not a relative link [text](path)")
    elif (p := source_problem(m.group("path"), folder, root)) is not None:
        out.append(p)
    if not SEVERITY_RE.match(c["Severity"]):
        out.append(f"severity '{c['Severity']}' is not one of {', '.join(SEVERITIES)} (optionally ' (mapped)')")
    if not c["Claim"]:
        out.append("the claim is empty")
    if c["Lane"] not in LANES:
        out.append(f"lane '{c['Lane']}' is not one of {', '.join(LANES)}")
    if c["Basis"] not in BASES:
        out.append(f"basis '{c['Basis']}' is not one of {', '.join(BASES)}")
    seen = STATE_RES["fixed"].match(c["State"])
    if not row.state:
        out.append(
            f"state '{c['State']}' is not one of: open; card issued #<pr>; fixed <sha of 7 to 40 hex>"
            "[, seen closed by <who> on <date>]; not a defect: <why>"
        )
    elif seen and seen.group("seen") and not real_date(seen.group("seen")):
        out.append(f"state '{c['State']}': '{seen.group('seen')}' is not a real date")
    return out


def check(reg: Register, sources: Path | None = None) -> list[str]:
    """Every problem of the register; ``sources`` is the trialbox/ folder whose findings files the states follow."""
    errors = list(reg.errors)
    folder = reg.path.parent
    root = root_of(reg.path)
    first: dict[str, int] = {}
    for row in reg.rows:
        if row.id in first:
            errors.append(
                f"{reg.path.name}:{row.line}: row {row.id}: the id is used twice (first at line {first[row.id]}); "
                "run --resolve after a merge"
            )
        first.setdefault(row.id, row.line)
        errors.extend(f"{reg.path.name}:{row.line}: row {row.id}: {p}" for p in row_problems(row, folder, root))
    if not errors:
        errors.extend(stale_problems(reg, sources or root))
    return errors


def not_closed(row: Row) -> bool:
    return row.state in ("open", "card issued")


def counts(reg: Register) -> dict[str, int]:
    out = {f"open {lv}": sum(1 for r in reg.rows if r.level == lv and not_closed(r)) for lv in SEVERITIES}
    out["total"] = len(reg.rows)
    for st in STATE_RES:
        out[st] = sum(1 for r in reg.rows if r.state == st)
    out["fixed, not seen closed"] = sum(1 for r in reg.rows if r.state == "fixed" and not r.seen_closed)
    return out


def counts_line(reg: Register) -> str:
    c = counts(reg)
    return (
        f"open High {c['open High']}, open Medium {c['open Medium']}, open Low {c['open Low']}, total {c['total']} "
        f"(open {c['open']}, card issued {c['card issued']}, fixed {c['fixed']} of which not seen closed "
        f"{c['fixed, not seen closed']}, not a defect {c['not a defect']})"
    )


def passes_release(row: Row) -> bool:
    """Criterion 11: a High is closed only when seen closed or ruled no defect; a Medium needs its fix or a ruling."""
    if row.level == "High":
        return (row.state == "fixed" and row.seen_closed) or row.state == "not a defect"
    if row.level == "Medium":
        return row.state in ("fixed", "not a defect")
    return True


def release_blockers(reg: Register) -> list[Row]:
    return [r for r in reg.rows if not passes_release(r)]


# --- --resolve ---


def render(cells: dict[str, str]) -> str:
    return "| " + " | ".join(cells[c] for c in COLUMNS) + " |"


def resolve(path: Path = REGISTER) -> tuple[list[str], list[str]]:
    """Fold the copies of a row that a union merge kept. Returns (ids folded, problems left for a person)."""
    reg = parse(path)
    groups: dict[str, list[Row]] = {}
    for r in reg.rows:
        groups.setdefault(r.id, []).append(r)
    lines = list(reg.lines)
    drop: list[int] = []
    folded, left = [], []
    for rid, copies in groups.items():
        if len(copies) < 2:
            continue
        rest = [{k: v for k, v in r.cells.items() if k != "State"} for r in copies]
        states = [r.cells["State"] for r in copies]
        moved = sorted({s for s in states if s != "open"})
        if any(x != rest[0] for x in rest[1:]):
            left.append(f"{rid}: its copies differ beyond the state (lines {', '.join(str(r.line) for r in copies)})")
            continue
        if len(set(states)) == 1:
            keep = states[0]
        elif len(moved) == 1:
            keep = moved[0]
        else:
            left.append(f"{rid}: two states other than open ({'; '.join(moved)}): a person decides")
            continue
        lines[copies[0].line - 1] = render({**copies[0].cells, "State": keep})
        drop.extend(r.line - 1 for r in copies[1:])
        folded.append(rid)
    if folded:
        for i in sorted(drop, reverse=True):
            del lines[i]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folded, left


# --- --sync-states ---

#: how far a state has come; a sync only moves a row forward (D-1180: a finding closes when it is seen closed)
STATE_RANK = {"open": 0, "card issued": 1, "fixed": 2, "not a defect": 2}


def state_name(text: str) -> str:
    for name, rx in STATE_RES.items():
        if rx.match(text):
            return name
    return ""


def source_states(root: Path) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """The ``state`` of every finding in a findings file under ``<root>/docs``, by id.

    Returns ({id: (state, file)} for the findings that give a state, {id: why it is left} for the ids two files
    give different states). A JSON file not in the ``--add-from`` form, and a finding with no ``state`` field, give
    nothing; a register row whose id no file gives is not synced or checked against a source.
    """
    found: dict[str, set[tuple[str, str]]] = {}
    for f in sorted((root / "docs").rglob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        findings = data.get("findings") if isinstance(data, dict) else None
        if not isinstance(findings, list):
            continue
        for x in findings:
            if isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("state"), str):
                found.setdefault(x["id"], set()).add((x["state"].strip(), f.relative_to(root).as_posix()))
    states, mixed = {}, {}
    for fid, pairs in found.items():
        if len({st for st, _ in pairs}) == 1:
            states[fid] = min(pairs, key=lambda p: p[1])
        else:
            mixed[fid] = (
                "its findings files give different states ("
                + "; ".join(f"{st} in {fn}" for st, fn in sorted(pairs, key=lambda p: p[1]))
                + "): a person decides"
            )
    return states, mixed


@dataclass
class SyncPlan:
    changes: list[tuple[Row, str]] = field(default_factory=list)  # (row, the source's state)
    refused: list[str] = field(default_factory=list)  # a source state the register cannot take
    left: list[str] = field(default_factory=list)  # differs, but a sync does not move it (printed, not an error)


def sync_plan(reg: Register, root: Path) -> SyncPlan:
    """What ``--sync-states`` would change: a row moves only forward to its source's state, never once seen closed."""
    states, mixed = source_states(root)
    plan = SyncPlan()
    for row in reg.rows:
        if row.id in mixed:
            plan.left.append(f"{row.id}: {mixed[row.id]}")
            continue
        if row.id not in states:
            continue
        new, fn = states[row.id]
        old = row.cells["State"]
        if new == old:
            continue
        name = state_name(new)
        if not name or CONTROL.search(new) or UNESCAPED_PIPE.search(new):
            plan.refused.append(f"{row.id}: the state '{new}' in {fn} is not a state the register takes")
        elif row.seen_closed:
            plan.left.append(f"{row.id}: '{old}' is seen closed, set by a person; {fn} says '{new}': not synced")
        elif not row.state or STATE_RANK[name] > STATE_RANK[row.state]:
            plan.changes.append((row, new))
        elif STATE_RANK[name] < STATE_RANK[row.state]:
            plan.left.append(f"{row.id}: the register's '{old}' is ahead of '{new}' in {fn}: not moved back")
        else:
            plan.left.append(f"{row.id}: the register says '{old}', {fn} says '{new}': a person decides")
    return plan


def stale_problems(reg: Register, root: Path) -> list[str]:
    """For --check: a row behind its source's state, or a source state the register cannot take."""
    plan = sync_plan(reg, root)
    out = [
        f"{reg.path.name}:{row.line}: row {row.id}: the state '{row.cells['State']}' is behind its findings file's "
        f"'{new}': run --sync-states"
        for row, new in plan.changes
    ]
    return out + [f"{reg.path.name}: {p}" for p in plan.refused]


def sync_states(path: Path = REGISTER, root: Path = ROOT) -> tuple[list[str], list[str], list[str]]:
    """Rewrite the state cell of each row behind its source. Returns (changes 'id: old -> new', refused, left)."""
    reg = parse(path)
    plan = sync_plan(reg, root)
    if not plan.changes:
        return [], plan.refused, plan.left
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    done = []
    for row, new in plan.changes:
        i = row.line - 1
        old_line = lines[i]
        tail = f"| {row.cells['State']} |"
        assert old_line.rstrip().endswith(tail), (row.id, old_line)
        cut = old_line.rstrip().rfind(tail)
        lines[i] = old_line[:cut] + f"| {new} |" + old_line[cut + len(tail) :]
        done.append(f"{row.id}: {row.cells['State']} -> {new}")
    path.write_text("\n".join(lines), encoding="utf-8")
    if errs := check(parse(path), root):
        path.write_text(text, encoding="utf-8")
        return [], [*plan.refused, "the register after the sync fails --check; the old file is put back:", *errs], []
    return done, plan.refused, plan.left


# --- --add-from ---


class AddError(ValueError):
    pass


def _text(value: Any, name: str, fid: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AddError(f"finding {fid}: '{name}' is missing or not text")
    if CONTROL.search(value):
        raise AddError(f"finding {fid}: '{name}' holds a line break or a control character")
    return UNESCAPED_PIPE.sub(r"\\|", value.strip())


def _source(value: Any, fid: str, root: Path) -> str:
    src = _text(value, "source", fid)
    p = Path(src)
    if p.is_absolute() or ":" in src:
        raise AddError(f"finding {fid}: source '{src}' is not a path relative to trialbox/")
    target = (root / p).resolve()
    if not target.is_relative_to(root.resolve()):
        raise AddError(f"finding {fid}: source '{src}' leaves the trialbox/ tree")
    if not target.is_file():
        raise AddError(f"finding {fid}: source '{src}' is not an existing file")
    return src


def rows_from(data: dict[str, Any], register_path: Path, root: Path = ROOT) -> tuple[str, str, list[dict[str, str]]]:
    """The card, the title and the register cells of a card's findings file (raises AddError)."""
    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        raise AddError("the file has no 'findings' list")
    first_id = findings[0].get("id") if isinstance(findings[0], dict) else None
    card = data.get("card") or (first_id.split("-", 1)[0] if isinstance(first_id, str) else None)
    if not isinstance(card, str) or not CARD_RE.match(card):
        raise AddError(f"card '{card}' is not a card name (letters and digits, no hyphen: V2, H20)")
    title = _text(data["title"], "title", card) if "title" in data else f"findings of card {card}"
    out = []
    for f in findings:
        if not isinstance(f, dict):
            raise AddError("a finding is not an object")
        fid = _text(f.get("id"), "id", "?")
        source = _source(f.get("source", data.get("source")), fid, root)
        target = (root / source).resolve()
        link = Path(os.path.relpath(target, register_path.resolve().parent)).as_posix()
        out.append(
            {
                "Id": fid,
                "Date found": _text(f.get("date", data.get("date")), "date", fid),
                "Source": f"[{target.name}]({link})",
                "Severity": _text(f.get("severity"), "severity", fid),
                "Claim": _text(f.get("claim"), "claim", fid),
                "Lane": _text(f.get("lane"), "lane", fid),
                "Basis": _text(f.get("basis"), "basis", fid),
                "State": _text(f.get("state", "open"), "state", fid),
            }
        )
    return card, title, out


def add_from(findings_file: Path, register_path: Path = REGISTER, root: Path = ROOT) -> list[str]:
    """Append the rows; return the problems (nothing is written, or the old file is put back, when there is one)."""
    try:
        data = json.loads(findings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{findings_file}: cannot be read as JSON: {exc}"]
    if not isinstance(data, dict):
        return [f"{findings_file}: the top level is not an object"]
    try:
        card, title, cells = rows_from(data, register_path, root)
    except AddError as exc:
        return [f"{findings_file.name}: {exc}: nothing written"]
    reg = parse(register_path)
    if errs := check(reg, root):
        return ["the register does not pass --check before the addition: nothing written", *errs]
    have = {r.id for r in reg.rows}
    problems = []
    seen: set[str] = set()
    for i, c in enumerate(cells):
        if c["Id"] in have:
            problems.append(f"{findings_file.name}: {c['Id']}: already in the register: nothing written")
        elif c["Id"] in seen:
            problems.append(f"{findings_file.name}: {c['Id']}: twice in the file: nothing written")
        seen.add(c["Id"])
        row = Row(i + 1, card, c)
        problems.extend(
            f"{findings_file.name}: {c['Id']}: {p}"
            for p in row_problems(row, register_path.parent, root_of(register_path))
        )
    if problems:
        return problems
    before = register_path.read_text(encoding="utf-8")
    lines = list(reg.lines)
    new = [render(c) for c in cells]
    if card in reg.table_end:
        at = reg.table_end[card]
        lines[at:at] = new
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"## {card}: {title}", "", HEADER, RULE, *new]
    register_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if errs := check(parse(register_path), root):
        register_path.write_text(before, encoding="utf-8")
        return ["the register after the addition fails --check; the old file is put back:", *errs]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.findings_register", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on a malformed line or row")
    ap.add_argument("--release", action="store_true", help="with --check: criterion 11")
    ap.add_argument("--counts", action="store_true", help="print the counts of open findings")
    ap.add_argument("--add-from", type=Path, metavar="FINDINGS_JSON", help="append a card's findings to the register")
    ap.add_argument("--resolve", action="store_true", help="after a merge: fold the copies of a row (see the doc)")
    ap.add_argument(
        "--sync-states", action="store_true", help="move each row's state forward to its findings file's (see the doc)"
    )
    ap.add_argument("--register", type=Path, default=REGISTER, help=argparse.SUPPRESS)
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not (args.check or args.counts or args.add_from or args.resolve or args.sync_states):
        ap.error("give --check, --counts, --add-from, --resolve or --sync-states")
    if args.release and not args.check:
        ap.error("--release goes with --check")
    rc = 0
    if args.add_from:
        problems = add_from(args.add_from, args.register, args.root)
        for p in problems:
            print(f"findings register: {p}", file=sys.stderr)
        if problems:
            return 1
        print(f"findings register: added the rows of {args.add_from}")
    if args.resolve:
        folded, left = resolve(args.register)
        for rid in folded:
            print(f"findings register: resolved {rid}: one row kept")
        for p in left:
            print(f"findings register: not resolved: {p}", file=sys.stderr)
        if left:
            rc = 1
    if args.sync_states:
        changed, refused, left = sync_states(args.register, args.root)
        for c in changed:
            print(f"findings register: synced {c}")
        for p in left:
            print(f"findings register: not synced: {p}")
        for p in refused:
            print(f"findings register: refused: {p}", file=sys.stderr)
        if refused:
            rc = 1
        if not changed:
            print("findings register: no state to sync")
    reg = parse(args.register)
    if args.check or args.resolve or args.sync_states:
        errors = check(reg, args.root)
        for e in errors:
            print(f"findings register: {e}", file=sys.stderr)
        if errors:
            rc = 1
        else:
            print(f"findings register: {len(reg.rows)} rows, well formed")
        if args.release and not errors:
            blockers = release_blockers(reg)
            for r in blockers:
                what = f"{r.id} ({r.cells['Severity']}, {r.cells['State']})"
                print(f"findings register: release: {what}: {r.cells['Claim']}", file=sys.stderr)
            if blockers:
                print(
                    f"findings register: release: {len(blockers)} findings stop the release (criterion 11)",
                    file=sys.stderr,
                )
                rc = 1
    if args.counts:
        print(counts_line(reg))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
