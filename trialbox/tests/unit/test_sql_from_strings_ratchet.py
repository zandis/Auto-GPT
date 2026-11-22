"""10G-42 (a), D-928: SQL built from strings is counted per file, and a new one fails CI.

Ruff's S608 (SQL from an f-string or a concatenation), S105 and S106 (a password-like name given a literal) were in
the global ignore list: a new f-string into ``execute`` passed every gate unseen. They are ignored per file now,
and ``tools/sql_from_strings.json`` holds each file's count; this test runs ruff with the three rules alone and no
configuration over the product's code and requires the counts to be exactly those. A new site fails here; a site
fixed lowers its count in the table (so the table stays the list part (c) reviews).

R22-14 (G-5): ruff runs with ``--ignore-noqa``, so ``# noqa`` or ``# NOQA: S608`` on the line hides nothing here; and a
statement joined from strings into ``execute`` (``" ".join([..., table])``), which no rule of ruff or bandit sees, is
found by reading the code."""

from __future__ import annotations

import ast
import collections
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "tools" / "sql_from_strings.json"
CODES = "S608,S105,S106"
SCANNED = ("services", "libs", "deploy")
#: ruff with the three rules alone, no configuration, and every ``noqa`` comment disregarded (R22-14)
RUFF = [
    sys.executable,
    "-m",
    "ruff",
    "check",
    "--isolated",
    "--ignore-noqa",
    "--select",
    CODES,
    "--output-format",
    "json",
]


def _ruff(*paths: str, cwd: Path | None = None) -> list[dict[str, object]]:
    out = subprocess.run([*RUFF, *paths], cwd=cwd, capture_output=True, text=True, check=False)
    rows: list[dict[str, object]] = json.loads(out.stdout or "[]")
    return rows


def joined_sql(root: Path) -> list[str]:
    """``file:line`` under ``root`` of every ``execute``/``executemany`` whose statement is a string's ``join``."""
    out = []
    for f in sorted(root.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("execute", "executemany")
            ):
                first = n.args[0] if n.args else None
                if (
                    isinstance(first, ast.Call)
                    and isinstance(first.func, ast.Attribute)
                    and first.func.attr == "join"
                    and isinstance(first.func.value, ast.Constant)
                    and isinstance(first.func.value.value, str)
                ):
                    out.append(f"{f.relative_to(root).as_posix()}:{n.lineno}")
    return out


def _found() -> tuple[dict[str, dict[str, int]], dict[str, list[str]]]:
    rows: list[dict[str, Any]] = _ruff(*SCANNED, cwd=ROOT)
    counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    where: dict[str, list[str]] = collections.defaultdict(list)
    for r in rows:
        rel = str(Path(r["filename"]).resolve().relative_to(ROOT))
        counts[rel][r["code"]] += 1
        where[rel].append(f"{rel}:{r['location']['row']} {r['code']}")
    return {f: dict(c) for f, c in counts.items()}, where


def test_every_file_holds_the_count_of_the_table() -> None:
    want: dict[str, dict[str, int]] = json.loads(TABLE.read_text(encoding="utf-8"))["counts"]
    got, where = _found()
    more = {f: (want.get(f, {}), c) for f, c in got.items() if any(n > want.get(f, {}).get(k, 0) for k, n in c.items())}
    assert not more, (
        "SQL built from a string (or a password-like literal) that the table does not hold: pass values as query "
        "parameters, or read an identifier from code and add it to tools/sql_from_strings.json with the reason. "
        + "; ".join(
            f"{f}: {want.get(f, {})} in the table, {c} found at " + ", ".join(where[f]) for f, (_, c) in more.items()
        )
    )
    fewer = {f: (c, got.get(f, {})) for f, c in want.items() if got.get(f, {}) != c}
    assert not fewer, f"a site was removed: lower its count in tools/sql_from_strings.json: {fewer}"


def test_the_rules_are_not_ignored_for_the_whole_tree() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ignore = text.split("[tool.ruff.lint]", 1)[1].split("[tool.ruff.lint.per-file-ignores]", 1)[0]
    for code in CODES.split(","):
        assert f'"{code}"' not in ignore, f"{code} is back in the global ignore list"


def test_a_new_f_string_into_execute_is_found(tmp_path: Path) -> None:
    """The card's acceptance: the rule this test counts fires on the shape it is meant to stop."""
    f = tmp_path / "bad.py"
    f.write_text('def q(tx, table):\n    tx.execute(f"SELECT * FROM {table} WHERE x = 1")\n', encoding="utf-8")
    assert [r["code"] for r in _ruff(str(f))] == ["S608"]


def test_the_scan_sees_every_spelling(tmp_path: Path) -> None:
    """R22-14 (G-5, R1-R3): a ``noqa`` comment in any case does not hide the statement, and a statement joined from
    strings is found; a statement passed with its values as parameters is not."""
    head = "def q(tx, table, x):\n"
    found = {
        "r1.py": '    tx.execute(f"SELECT * FROM {table} WHERE x = 1")  # noqa\n',
        "r2.py": '    tx.execute(f"SELECT * FROM {table} WHERE x = 1")  # NOQA: S608\n',
        "r2b.py": '    tx.execute("SELECT * FROM " + table + " WHERE x = 1")  # noqa: E501,S608\n',
    }
    joined = {"r3.py": '    tx.execute(" ".join(["SELECT", "*", "FROM", table]))\n',
              "r3b.py": '    tx.executemany("".join(("SELECT * FROM ", table)), [])\n'}  # fmt: skip
    clean = {"ok.py": '    tx.execute("SELECT * FROM t WHERE x = ?", [x])\n'}
    for name, body in {**found, **joined, **clean}.items():
        (tmp_path / name).write_text(head + body, encoding="utf-8")
    rows: list[dict[str, Any]] = _ruff(".", cwd=tmp_path)
    assert sorted(Path(str(r["filename"])).name for r in rows) == sorted(found)
    assert sorted(h.split(":")[0] for h in joined_sql(tmp_path)) == sorted(joined)


def test_no_statement_is_joined_from_strings_into_execute() -> None:
    hits = [f"{top}/{h}" for top in SCANNED for h in joined_sql(ROOT / top)]
    assert hits == [], f"a statement joined from strings into execute: pass values as query parameters: {hits}"
