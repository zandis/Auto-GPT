"""Every inline security suppression has a reviewed ledger line (10G-39, OT-1 of review 21; D-1338).

A ``# nosec`` comment hides a line from bandit and a ``# noqa: S...`` comment hides it from ruff's security rules;
neither is counted by ``tools/security_scan_ignores.yaml``. This check reads the comments (``tokenize``, so text in
a string is never taken for one) of every Python file git tracks under trialbox/ and holds them to
``tools/inline_suppressions.yaml``, one entry per suppressed line:

* ``path``      the file, from trialbox/;
* ``rule``      the codes the comment names, sorted and joined by ", " (``B608``; ``S314``); ``nosec`` with no code
  is ``all``, and so is a ``noqa`` with no code (``# noqa``, ``# ruff: noqa``: it hides the security rules too; F-4);
* ``code``      the line's code before the comment, spaces collapsed: the entry follows the line when lines move;
* ``verdict``   ``safe`` (the reason says why) or ``finding`` (a defect kept out of "safe"; ``finding`` names its id);
* ``reason``    why, in at least 20 characters;
* ``reviewer``, ``reviewed`` (YYYY-MM-DD) and ``review_by`` (YYYY-MM-DD, at most 180 days after today; once it
  passes the check fails until the entry is reviewed again), as the supply-chain allow-list dates its entries.

``python -m tools.inline_suppressions --check`` fails (exit 1) on a suppressed line with no entry, on an entry that
matches no line (the line was changed or removed: the entry goes too), on a malformed entry and on a lapsed review
date. ``python -m tools.inline_suppressions`` prints the ledger as a table. ``make lint`` runs the check.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import subprocess
import sys
import tokenize
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tools" / "inline_suppressions.yaml"

VERDICTS = ("safe", "finding")
MIN_REASON = 20
MAX_AHEAD_DAYS = 180
FIELDS = ("path", "rule", "code", "verdict", "reason", "reviewer", "reviewed", "review_by")

_NOSEC = re.compile(r"(?<![\w-])nosec\b(?P<codes>(?:[\s:,]*[BS]\d{3})*)")
_NOQA = re.compile(r"(?<![\w-])noqa\s*:\s*(?P<codes>[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)", re.IGNORECASE)
_CODE = re.compile(r"[A-Z]+\d+")
#: F-4: a ``noqa`` that hides every rule, as ruff reads one: no colon after it (ruff ignores a colon with no valid code)
_BLANKET = re.compile(r"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b(?!\s*:)", re.IGNORECASE)
_FINDING_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d{2,}$")


class LedgerError(Exception):
    """The ledger cannot be read, or an entry is malformed."""


@dataclass(frozen=True)
class Suppression:
    path: str
    line: int
    rule: str
    code: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.rule, self.code)


@dataclass(frozen=True)
class Entry:
    path: str
    rule: str
    code: str
    verdict: str
    reason: str
    reviewer: str
    reviewed: dt.date
    review_by: dt.date
    finding: str | None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.rule, self.code)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def suppressions_in(text: str, path: str) -> list[Suppression]:
    """The suppressed lines of one Python source: a ``nosec`` comment (any codes, or none: ``all``) and a ``noqa``
    comment naming at least one ruff ``S`` code, in any case as ruff reads it (its other codes are not security
    rules and are left out), or naming none (``all``)."""
    lines = text.splitlines()
    out: list[Suppression] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        raise LedgerError(f"{path}: cannot be read as Python: {exc}") from exc
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        rules: set[str] = set()
        for m in _NOSEC.finditer(tok.string):
            codes = _CODE.findall(m.group("codes"))
            rules |= set(codes) if codes else {"all"}
        for m in _NOQA.finditer(tok.string):
            rules |= {c for c in _CODE.findall(m.group("codes").upper()) if re.fullmatch(r"S\d+", c)}
        if _BLANKET.search(tok.string):
            rules.add("all")
        if not rules:
            continue
        row, col = tok.start
        code = _collapse(lines[row - 1][:col]) if row - 1 < len(lines) else ""
        # a comment alone on its line (a file-level ruff directive) keeps the comment as its code
        out.append(Suppression(path, row, ", ".join(sorted(rules)), code or _collapse(tok.string)))
    return out


def tracked_python(root: Path) -> list[str]:
    """The ``.py`` files git tracks under ``root`` (relative to it); every ``.py`` below it outside a repo."""
    proc = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=root, capture_output=True, check=False,
                          timeout=120)  # fmt: skip
    names = [n for n in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if n] if proc.returncode == 0 else []
    if not names:
        names = [str(p.relative_to(root)) for p in root.rglob("*.py")]
    return sorted(n for n in names if (root / n).is_file() and not (root / n).is_symlink())


def scan(root: Path, files: Iterable[str] | None = None) -> list[Suppression]:
    out: list[Suppression] = []
    for name in files if files is not None else tracked_python(root):
        text = (root / name).read_text(encoding="utf-8", errors="replace")
        if "nosec" in text or "noqa" in text.lower():
            out += suppressions_in(text, name)
    return out


def _date(value: object, where: str, field: str) -> dt.date:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise LedgerError(f"{where}: {field} must be a date YYYY-MM-DD")


def load_ledger(path: Path) -> list[Entry]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LedgerError(f"{path.name}: cannot be read: {exc}") from exc
    rows = (data or {}).get("suppressions") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise LedgerError(f"{path.name}: needs a list `suppressions`")
    out: list[Entry] = []
    for i, row in enumerate(rows):
        where = f"{path.name}: suppressions[{i}]"
        if not isinstance(row, dict):
            raise LedgerError(f"{where}: not a mapping")
        unknown = sorted(set(row) - {*FIELDS, "finding"})
        if unknown:
            raise LedgerError(f"{where}: unknown field(s) {', '.join(unknown)}")
        for f in ("path", "rule", "code", "verdict", "reason", "reviewer"):
            if not isinstance(row.get(f), str) or not row[f].strip():
                raise LedgerError(f"{where}: needs {f}")
        if row["verdict"] not in VERDICTS:
            raise LedgerError(f"{where}: verdict must be one of {', '.join(VERDICTS)}")
        if len(row["reason"].strip()) < MIN_REASON:
            raise LedgerError(f"{where}: the reason must say why, in at least {MIN_REASON} characters")
        finding = row.get("finding")
        if row["verdict"] == "finding" and not (isinstance(finding, str) and _FINDING_ID.match(finding)):
            raise LedgerError(f"{where}: a `finding` verdict names its finding id (finding: H10G39-01)")
        if row["verdict"] == "safe" and finding is not None:
            raise LedgerError(f"{where}: a `safe` entry names no finding")
        out.append(
            Entry(
                path=row["path"].strip(),
                rule=row["rule"].strip(),
                code=_collapse(row["code"]),
                verdict=row["verdict"],
                reason=row["reason"].strip(),
                reviewer=row["reviewer"].strip(),
                reviewed=_date(row.get("reviewed"), where, "reviewed"),
                review_by=_date(row.get("review_by"), where, "review_by"),
                finding=finding if isinstance(finding, str) else None,
            )
        )
    return out


def judge(found: Sequence[Suppression], ledger: Sequence[Entry], today: dt.date) -> list[str]:
    """Every failure: a suppressed line with no entry, an entry with no line, a review date lapsed or too far."""
    failures: list[str] = []
    have = Counter(s.key for s in found)
    want = Counter(e.key for e in ledger)
    for s in found:
        if have[s.key] > want.get(s.key, 0):
            failures.append(f"{s.path}:{s.line}: {s.rule}: an inline suppression with no ledger line")
    for key, n in sorted(want.items()):
        if n > have.get(key, 0):
            path, rule, code = key
            failures.append(f"{path}: {rule}: a ledger line that matches no code line ({code!r}): remove it")
    for e in ledger:
        if e.review_by < today:
            failures.append(f"{e.path}: {e.rule}: review_by {e.review_by} has passed: review the entry again")
        elif (e.review_by - today).days > MAX_AHEAD_DAYS:
            failures.append(f"{e.path}: {e.rule}: review_by {e.review_by} is more than {MAX_AHEAD_DAYS} days ahead")
        if e.reviewed > today:
            failures.append(f"{e.path}: {e.rule}: reviewed {e.reviewed} is in the future")
    return failures


def check(root: Path, ledger_path: Path, today: dt.date) -> int:
    try:
        ledger = load_ledger(ledger_path)
        found = scan(root)
    except LedgerError as exc:
        print(f"inline-suppressions: ERROR {exc}", file=sys.stderr)
        return 2
    failures = judge(found, ledger, today)
    for f in failures:
        print(f"FAIL {f}")
    kinds = Counter("nosec" if s.rule[0] in "Ba" else "noqa: S" for s in found)
    findings = sum(1 for e in ledger if e.verdict == "finding")
    print(
        f"inline-suppressions: {kinds['nosec']} nosec and {kinds['noqa: S']} noqa: S lines; {len(ledger)} ledger "
        f"lines ({findings} kept as findings); {'FAIL' if failures else 'PASS'}"
    )
    if failures:
        print(f"inline-suppressions: add a reviewed line to {ledger_path.name}, or remove the suppression")
        return 1
    return 0


def table(ledger_path: Path) -> str:
    lines = ["| File | Rule | Verdict | Reason | Reviewer | Review by |", "| --- | --- | --- | --- | --- | --- |"]
    for e in load_ledger(ledger_path):
        verdict = f"finding {e.finding}" if e.finding else e.verdict
        lines.append(f"| `{e.path}` | {e.rule} | {verdict} | {e.reason} | {e.reviewer} | {e.review_by} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="inline_suppressions", description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--check", action="store_true", help="hold the code's suppressions to the ledger (exit 1 if not)")
    ap.add_argument("--root", type=Path, default=ROOT, help="the folder to read (default: trialbox/)")
    ap.add_argument("--ledger", type=Path, default=LEDGER, help="the reviewed ledger")
    ap.add_argument("--today", type=dt.date.fromisoformat, default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.check:
        return check(a.root.resolve(), a.ledger, a.today or dt.date.today())
    try:
        print(table(a.ledger))
    except LedgerError as exc:
        print(f"inline-suppressions: ERROR {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
