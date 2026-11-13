"""The limits lint (T-687, D-471, D-534; OD-10 of TB-PLAN-06.1): every fixed time limit and every fixed row count in
``services/`` is listed, with a reason, in ``tools/limits_allow.yaml``.

OD-10: every time limit, memory cap and count in the product is derived from the hardware, the model's measured speed
or the size of the data, or it is a declared setting with a reason, or the work is refused at its start with an
estimate. A literal is none of these, so each one is on the list with its finding (``F-nn`` of the scale review
2026-11-11), the card that removes it (``T-nnn``) or why it is not a cut (one row by key, a page with a "more" link,
a test-only path). The scale review's class (§1) came from literals nobody listed: a 330 s limit around an 805 s
rebuild, the newest 500 jobs of the box as "this study's latest".

What counts (Python's own parser, so comments and docstrings never count):

* ``timeout``: a ``timeout=<number>`` keyword, a parameter named ``timeout`` (or ``*_timeout``) whose default is a
  number, or ``Timeout(<number>, ...)``, whatever the number (D-534: until then only above 60 s, so a 45 s limit
  around a model call was never listed);
* ``limit``: a ``limit=<integer>`` keyword or a parameter named ``limit`` with an integer default, and ``LIMIT <n>`` in
  a string (SQL), whatever the number.

An entry is ``(path, kind, value)`` with the number of such literals in the file. A literal that is not on the list, or
more of them than the list allows, fails (a new one). An entry whose literals are gone, or fewer, fails too: the card
that removes a limit removes its line, so the list only shrinks (like ``EXPECTED`` in the judge-in-the-loop test).

    python -m tools.limits_lint            # exit 1 on a new or a stale entry
    python -m tools.limits_lint --list     # every literal found, as allow-list lines
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOW = ROOT / "tools" / "limits_allow.yaml"
_SQL_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
_SQL_HINT = re.compile(r"\b(SELECT|FROM|WHERE|ORDER BY)\b", re.IGNORECASE)
# a reason names a finding, a card, a decision, or says why the count is not a cut
_REASON = re.compile(r"\b(F-\d{2}|T-\d{3}[a-z]?|D-\d{2,3}|G1-\d)\b|not a cut|a setting")

Key = tuple[str, str, str]


@dataclass(frozen=True)
class Literal:
    path: str
    line: int
    kind: str  # "timeout" | "limit"
    value: str

    @property
    def key(self) -> Key:
        return (self.path, self.kind, self.value)


def _num(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def _docstrings(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def _is_timeout_name(name: str) -> bool:
    return name == "timeout" or name.endswith("_timeout")


def scan_source(text: str, path: str) -> Iterator[Literal]:
    """The literals of one file (``path`` is only the label)."""
    tree = ast.parse(text)
    docs = _docstrings(tree)

    def timeout(node: ast.AST, v: float | None) -> Iterator[Literal]:
        if v is not None and v > 0:  # 0 or less is "do not wait", not a limit
            yield Literal(path, getattr(node, "lineno", 0), "timeout", _fmt(v))

    def limit(node: ast.AST, v: float | None) -> Iterator[Literal]:
        if v is not None and v == int(v):
            yield Literal(path, getattr(node, "lineno", 0), "limit", _fmt(v))

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg:
            if _is_timeout_name(node.arg):
                yield from timeout(node.value, _num(node.value))
            elif node.arg == "limit":
                yield from limit(node.value, _num(node.value))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if name == "Timeout" and node.args:
                yield from timeout(node, _num(node.args[0]))
            elif name == "min" and any(isinstance(x, ast.Name) and x.id == "limit" for x in node.args):
                for x in node.args:  # min(limit, 500): a cap on what a caller may ask for
                    yield from limit(node, _num(x))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            a = node.args
            pos = [*a.posonlyargs, *a.args]
            pairs = list(zip(pos[len(pos) - len(a.defaults) :], a.defaults, strict=True))
            pairs += [(k, d) for k, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d is not None]
            for arg, default in pairs:
                if _is_timeout_name(arg.arg):
                    yield from timeout(default, _num(default))
                elif arg.arg == "limit":
                    yield from limit(default, _num(default))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            s = node.value
            if _SQL_HINT.search(s) or s.lstrip().upper().startswith("LIMIT"):
                for m in _SQL_LIMIT.finditer(s):
                    yield Literal(path, node.lineno, "limit", m.group(1))


def scan(root: Path = ROOT, dirs: Iterable[str] = ("services",)) -> list[Literal]:
    out: list[Literal] = []
    for d in dirs:
        for f in sorted((root / d).rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            if "/tests/" in rel or rel.split("/")[-1].startswith("test_"):
                continue
            out.extend(scan_source(f.read_text(encoding="utf-8"), rel))
    return sorted(out, key=lambda x: (x.path, x.line, x.kind, x.value))


@dataclass(frozen=True)
class Entry:
    path: str
    kind: str
    value: str
    count: int
    reason: str

    @property
    def key(self) -> Key:
        return (self.path, self.kind, self.value)


def load_allow(path: Path = ALLOW) -> list[Entry]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[Entry] = []
    for row in doc.get("allow") or []:
        out.append(
            Entry(
                str(row["path"]),
                str(row["kind"]),
                str(row["value"]),
                int(row.get("count", 1)),
                str(row.get("reason") or "").strip(),
            )
        )
    return out


def check(found: list[Literal], allow: list[Entry]) -> list[str]:
    """The problems: new literals, stale or duplicate entries, entries without a reason. Empty: clean."""
    problems: list[str] = []
    have = Counter(x.key for x in found)
    allowed: dict[Key, Entry] = {}
    for e in allow:
        if e.kind not in ("timeout", "limit"):
            problems.append(f"{e.path}: kind {e.kind!r} is neither timeout nor limit")
        if e.key in allowed:
            problems.append(f"{e.path}: {e.kind}={e.value} is listed twice")
        allowed[e.key] = e
        if not _REASON.search(e.reason):
            problems.append(
                f"{e.path}: {e.kind}={e.value} has no reason naming its finding (F-nn), card (T-nnn) or decision, "
                "or saying it is 'not a cut' or 'a setting' (OD-10)"
            )
    for key, n in sorted(have.items()):
        got = allowed.get(key)
        lines = ", ".join(str(x.line) for x in found if x.key == key)
        if got is None or n > got.count:
            ok = 0 if got is None else got.count
            problems.append(
                f"{key[0]}:{lines}: new fixed {key[1]} {key[2]} ({n} found, {ok} allowed): derive it from the "
                "hardware, the model's measured speed or the size of the data, or declare it as a setting, or add a "
                "line to tools/limits_allow.yaml with its reason (OD-10, D-471)"
            )
    for key, e in sorted(allowed.items()):
        n = have.get(key, 0)
        if n < e.count:
            problems.append(
                f"{key[0]}: {key[1]}={key[2]} is listed {e.count} time(s) but found {n}: the limit was removed or "
                "changed, remove or lower its line in tools/limits_allow.yaml"
            )
    return problems


def as_yaml(found: list[Literal]) -> str:
    rows = Counter(x.key for x in found)
    out = ["allow:"]
    for (path, kind, value), n in sorted(rows.items()):
        out.append(f'  - {{path: {path}, kind: {kind}, value: {value}, count: {n}, reason: ""}}')
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="print every literal found as allow-list lines")
    ap.add_argument("--allow", type=Path, default=ALLOW)
    a = ap.parse_args(argv)
    found = scan()
    if a.list:
        sys.stdout.write(as_yaml(found))
        return 0
    problems = check(found, load_allow(a.allow))
    for p in problems:
        print(p)
    print(
        f"limits_lint: {len(found)} literals in services/, {'clean' if not problems else f'{len(problems)} problem(s)'}"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
