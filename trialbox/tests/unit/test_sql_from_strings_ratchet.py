"""10G-42 (a), D-928: SQL built from strings is counted per file, and a new one fails CI.

Ruff's S608 (SQL from an f-string or a concatenation), S105 and S106 (a password-like name given a literal) were in
the global ignore list: a new f-string into ``execute`` passed every gate unseen. They are ignored per file now,
and ``tools/sql_from_strings.json`` holds each file's count; this test runs ruff with the three rules alone and no
configuration over the product's code and requires the counts to be exactly those. A new site fails here; a site
fixed lowers its count in the table (so the table stays the list part (c) reviews)."""

from __future__ import annotations

import collections
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "tools" / "sql_from_strings.json"
CODES = "S608,S105,S106"
SCANNED = ("services", "libs", "deploy")


def _found() -> tuple[dict[str, dict[str, int]], dict[str, list[str]]]:
    out = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", CODES, "--output-format", "json", *SCANNED],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    rows = json.loads(out.stdout or "[]")
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
    out = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", CODES, "--output-format", "json", str(f)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert [r["code"] for r in json.loads(out.stdout)] == ["S608"]
