"""findings_register: the one findings register is well formed, and says what is open (plan 8 criterion 11, D-1180).

    python -m tools.findings_register --check             # exit 1 on a malformed row; CI job `checks`, `make lint`
    python -m tools.findings_register --check --release   # also exit 1 if a High is not closed or a Medium is `open`
    python -m tools.findings_register --counts            # open High, open Medium, open Low, total (printed, not kept)
    python -m tools.findings_register --add-from FILE     # append a card's findings.json to the register

The register is ``docs/handover/findings-register.md``: one Markdown table per card, under a heading
``## <card>: <words>``, with the columns

    | Id | Date found | Source | Severity | Claim | Lane | Basis | State |

``--check`` reads every such table and fails, naming the line and the id, when a row breaks a rule:

* **id**        unique in the file, of the form ``<card>-<local>`` with ``<card>`` the heading's card; lane V's cards
                (``V2``) take a number of two or more digits (``V2-07``); other cards keep the id their source gave
                (``H20-F-16``, ``H22-no-host-tree``) or the register's two-digit number in the source's order
                (``H18-01``);
* **date**      an ISO date (``2026-11-17``);
* **source**    a relative Markdown link ``[text](path)`` to a file that exists, from the register's folder;
* **severity**  ``High``, ``Medium`` or ``Low``, followed by `` (mapped)`` when the register mapped it from another
                scale;
* **claim**     one line, not empty;
* **lane**      one of ``LANES``;
* **basis**     ``shown``, ``hypothesis``, ``not_run``, or ``not stated`` (a seeded row whose source does not say);
* **state**     exactly one of ``open``; ``card issued #<pr>``; ``fixed <sha>`` (7 to 40 hex) optionally followed by
                ``, seen closed by <who> on <date>``; ``not a defect: <why>``.

A table whose header is not the register's header is not read (the file's head may hold other tables). A register
header under a heading that is not ``## <card>: ...`` is an error, and so is a heading of a card used twice.

The counts are printed by ``--counts``, never written into the file: a counts line in the file would be changed by
every pull request that adds a row, and so would conflict in every pair of them (D-1180). "Open" in the counts is
any row not closed: ``open`` or ``card issued``. ``--release`` is criterion 11: no High that is ``open`` or
``card issued``, and no Medium that is ``open`` (a Medium with a card or a recorded ruling passes).

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

``source`` is a path from the ``trialbox/`` folder; the row gets a link relative to the register. Every new row is
checked with the rules above before anything is written, and an id already in the register is refused. The rows are
appended in the file's order; nothing is sorted or rewritten, so two cards' additions touch different lines.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "handover" / "findings-register.md"

COLUMNS = ("Id", "Date found", "Source", "Severity", "Claim", "Lane", "Basis", "State")
HEADER = "| " + " | ".join(COLUMNS) + " |"
RULE = "| " + " | ".join("---" for _ in COLUMNS) + " |"

LANES = ("A2", "B2", "C2", "C2a", "C2b", "D", "E", "H", "W", "R", "Int", "V")
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


@dataclass
class Register:
    path: Path
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: card -> the line number of the last line of its table (where a new row goes)
    table_end: dict[str, int] = field(default_factory=dict)


def split_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in CELL_SPLIT.split(body)]


def parse(path: Path = REGISTER) -> Register:
    reg = Register(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        reg.errors.append(f"{path}: cannot be read: {exc}")
        return reg
    heading_card: str | None = None
    heading_line = 0
    seen_cards: dict[str, int] = {}
    in_table = False
    i = 0
    while i < len(lines):
        text = lines[i]
        n = i + 1
        if text.startswith("#"):
            in_table = False
            m = HEADING_RE.match(text)
            heading_card = m.group("card") if (m and text.startswith("## ")) else None
            heading_line = n
        elif text.strip() == HEADER:
            if heading_card is None or not CARD_RE.match(heading_card):
                reg.errors.append(f"{path.name}:{n}: a register table must sit under a heading '## <card>: <words>'")
                heading_card = heading_card or "?"
            elif heading_card in seen_cards:
                reg.errors.append(
                    f"{path.name}:{heading_line}: card {heading_card} has a second table (first at line "
                    f"{seen_cards[heading_card]}): add rows to the first"
                )
            seen_cards.setdefault(heading_card, n)
            if i + 1 >= len(lines) or split_cells(lines[i + 1]) != ["---"] * len(COLUMNS):
                reg.errors.append(f"{path.name}:{n + 1}: the register header must be followed by {RULE}")
            else:
                i += 1
            in_table = True
            reg.table_end[heading_card] = i + 1
        elif in_table and text.strip().startswith("|"):
            cells = split_cells(text)
            if len(cells) != len(COLUMNS):
                first = cells[0] if cells else "?"
                reg.errors.append(
                    f"{path.name}:{n}: row {first}: {len(cells)} cells, the register has {len(COLUMNS)} "
                    "(a '|' inside a cell is written '\\|')"
                )
            else:
                reg.rows.append(Row(n, heading_card or "?", dict(zip(COLUMNS, cells, strict=True))))
            reg.table_end[heading_card or "?"] = n
        else:
            in_table = False
        i += 1
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


def row_problems(row: Row, folder: Path) -> list[str]:
    c = row.cells
    out = []
    if (p := id_problem(row.card, c["Id"])) is not None:
        out.append(p)
    if not DATE_RE.match(c["Date found"]):
        out.append(f"date found '{c['Date found']}' is not an ISO date (YYYY-MM-DD)")
    m = LINK_RE.match(c["Source"])
    if not m:
        out.append(f"source '{c['Source']}' is not a relative link [text](path)")
    elif m.group("path").startswith(("/", "http:", "https:")):
        out.append(f"source '{m.group('path')}' is not a relative path")
    elif not (folder / m.group("path")).exists():
        out.append(f"source '{m.group('path')}' does not exist (from {folder.name}/)")
    if not SEVERITY_RE.match(c["Severity"]):
        out.append(f"severity '{c['Severity']}' is not one of {', '.join(SEVERITIES)} (optionally ' (mapped)')")
    if not c["Claim"]:
        out.append("the claim is empty")
    if c["Lane"] not in LANES:
        out.append(f"lane '{c['Lane']}' is not one of {', '.join(LANES)}")
    if c["Basis"] not in BASES:
        out.append(f"basis '{c['Basis']}' is not one of {', '.join(BASES)}")
    if not row.state:
        out.append(
            f"state '{c['State']}' is not one of: open; card issued #<pr>; fixed <sha of 7 to 40 hex>"
            "[, seen closed by <who> on <date>]; not a defect: <why>"
        )
    return out


def check(reg: Register) -> list[str]:
    errors = list(reg.errors)
    folder = reg.path.parent
    first: dict[str, int] = {}
    for row in reg.rows:
        if row.id in first:
            errors.append(
                f"{reg.path.name}:{row.line}: row {row.id}: the id is used twice (first at line {first[row.id]})"
            )
        first.setdefault(row.id, row.line)
        errors.extend(f"{reg.path.name}:{row.line}: row {row.id}: {p}" for p in row_problems(row, folder))
    return errors


def not_closed(row: Row) -> bool:
    return row.state in ("open", "card issued")


def counts(reg: Register) -> dict[str, int]:
    out = {f"open {lv}": sum(1 for r in reg.rows if r.level == lv and not_closed(r)) for lv in SEVERITIES}
    out["total"] = len(reg.rows)
    for st in STATE_RES:
        out[st] = sum(1 for r in reg.rows if r.state == st)
    return out


def counts_line(reg: Register) -> str:
    c = counts(reg)
    return (
        f"open High {c['open High']}, open Medium {c['open Medium']}, open Low {c['open Low']}, total {c['total']} "
        f"(open {c['open']}, card issued {c['card issued']}, fixed {c['fixed']}, not a defect {c['not a defect']})"
    )


def release_blockers(reg: Register) -> list[Row]:
    """Criterion 11 of plan 8: a High not closed, or a Medium still `open` (no card, no ruling)."""
    return [r for r in reg.rows if (r.level == "High" and not_closed(r)) or (r.level == "Medium" and r.state == "open")]


# --- --add-from -------------------------------------------------------------------------------------------------------


class AddError(ValueError):
    pass


def _cell(value: Any, name: str, fid: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AddError(f"finding {fid}: '{name}' is missing or not text")
    one = " ".join(value.split())
    return one.replace("|", "\\|")


def rows_from(data: dict[str, Any], register_path: Path, root: Path = ROOT) -> tuple[str, str, list[dict[str, str]]]:
    """The card, the title and the register cells of a card's findings file (raises AddError)."""
    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        raise AddError("the file has no 'findings' list")
    first_id = findings[0].get("id") if isinstance(findings[0], dict) else None
    card = data.get("card") or (first_id.split("-", 1)[0] if isinstance(first_id, str) else None)
    if not isinstance(card, str) or not CARD_RE.match(card):
        raise AddError(f"card '{card}' is not a card name (letters and digits, no hyphen: V2, H20)")
    title = data.get("title") or f"findings of card {card}"
    out = []
    for f in findings:
        if not isinstance(f, dict):
            raise AddError("a finding is not an object")
        fid = _cell(f.get("id"), "id", "?")
        source = _cell(f.get("source") or data.get("source"), "source", fid)
        target = root / source
        rel = Path(os.path.relpath(target, register_path.parent)).as_posix()
        out.append(
            {
                "Id": fid,
                "Date found": _cell(f.get("date") or data.get("date"), "date", fid),
                "Source": f"[{Path(source).name}]({rel})",
                "Severity": _cell(f.get("severity"), "severity", fid),
                "Claim": _cell(f.get("claim"), "claim", fid),
                "Lane": _cell(f.get("lane"), "lane", fid),
                "Basis": _cell(f.get("basis"), "basis", fid),
                "State": _cell(f.get("state") or "open", "state", fid),
            }
        )
    return card, str(title), out


def render(cells: dict[str, str]) -> str:
    return "| " + " | ".join(cells[c] for c in COLUMNS) + " |"


def add_from(findings_file: Path, register_path: Path = REGISTER, root: Path = ROOT) -> list[str]:
    """Append the rows; return the problems (nothing is written when there is one)."""
    try:
        data = json.loads(findings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{findings_file}: cannot be read as JSON: {exc}"]
    if not isinstance(data, dict):
        return [f"{findings_file}: the top level is not an object"]
    try:
        card, title, cells = rows_from(data, register_path, root)
    except AddError as exc:
        return [f"{findings_file}: {exc}"]
    reg = parse(register_path)
    if errs := check(reg):
        return ["the register does not pass --check before the addition:", *errs]
    have = {r.id for r in reg.rows}
    problems = []
    seen: set[str] = set()
    for i, c in enumerate(cells):
        row = Row(i + 1, card, c)
        if c["Id"] in have or c["Id"] in seen:
            problems.append(f"{findings_file.name}: {c['Id']}: the id is already in the register")
        seen.add(c["Id"])
        problems.extend(f"{findings_file.name}: {c['Id']}: {p}" for p in row_problems(row, register_path.parent))
    if problems:
        return problems
    lines = register_path.read_text(encoding="utf-8").splitlines()
    new = [render(c) for c in cells]
    if card in reg.table_end:
        at = reg.table_end[card]
        lines[at:at] = new
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"## {card}: {title}", "", HEADER, RULE, *new]
    register_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.findings_register", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on a malformed row")
    ap.add_argument("--release", action="store_true", help="with --check: criterion 11 (no High open, no Medium open)")
    ap.add_argument("--counts", action="store_true", help="print the counts of open findings")
    ap.add_argument("--add-from", type=Path, metavar="FINDINGS_JSON", help="append a card's findings to the register")
    ap.add_argument("--register", type=Path, default=REGISTER, help=argparse.SUPPRESS)
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not (args.check or args.counts or args.add_from):
        ap.error("give --check, --counts or --add-from")
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
    reg = parse(args.register)
    if args.check:
        errors = check(reg)
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
