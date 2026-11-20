"""10G-42 (b), D-1344: the fifteen SQL-from-strings rules, each run on its own positive and negative fixture.

``tools/sql_rules.py`` holds the rules (written here; no registry rule copied in) and runs them on Python's ``ast``.
Each rule has ``tests/fixtures/sql_rules/<RULE>.pos.py.txt`` (synthetic SQL; every line the rule must hit ends with
``# hit``) and ``<RULE>.neg.py.txt`` (the safe forms of the same thing; the rule must not hit). The fixtures are
``.txt`` so ruff's S608, which now gates (D-928), does not read them as product code.

The run over the tree is compared with the ledger ``tools/sql_rules_ledger.yaml`` (safe hits with their reasons,
open findings by id). A difference is a warning here, not a failure: plan 10's ruling for 10G-42 is that the page
test warns, and D-928's ruff ratchet already fails a new f-string into ``execute``.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from tools import sql_rules

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "sql_rules"
FINDINGS = (
    ROOT / "docs" / "handover" / "sql-sites-classified-2026-11-18" / "findings.json",
    ROOT / "docs" / "handover" / "sql-from-strings-rules-2026-11-19" / "findings.json",
)
#: negative fixtures that hold a value which is escaped but still written into the text: another rule (SQLS01, a
#: value in the SQL text) may hit them; every other negative fixture is clean under all fifteen rules
ESCAPED = {"SQLS11", "SQLS12"}


def _fixture(rule: str, kind: str) -> str:
    return (FIX / f"{rule}.{kind}.py.txt").read_text(encoding="utf-8")


def test_there_are_fifteen_rules_each_with_a_text_and_a_severity() -> None:
    assert len(sql_rules.RULES) == 15
    assert set(sql_rules.SEVERITY) == set(sql_rules.RULES)
    assert set(sql_rules.SEVERITY.values()) <= {"High", "Medium", "Low"}


def test_every_fixture_belongs_to_a_rule() -> None:
    names = {p.name for p in FIX.iterdir()}
    want = {f"{r}.{k}.py.txt" for r in sql_rules.RULES for k in ("pos", "neg")}
    assert names == want


@pytest.mark.parametrize("rule", sorted(sql_rules.RULES))
def test_the_rule_hits_exactly_the_marked_lines_of_its_positive_fixture(rule: str) -> None:
    src = _fixture(rule, "pos")
    marked = {i for i, line in enumerate(src.splitlines(), 1) if line.rstrip().endswith("# hit")}
    assert marked, f"{rule}: the positive fixture marks no line"
    got = {h.line for h in sql_rules.scan_source(src) if h.rule == rule}
    assert got == marked, f"{rule}: hits {sorted(got)}, marked {sorted(marked)}"


@pytest.mark.parametrize("rule", sorted(sql_rules.RULES))
def test_the_rule_stays_silent_on_its_negative_fixture(rule: str) -> None:
    hits = sql_rules.scan_source(_fixture(rule, "neg"))
    assert not [h for h in hits if h.rule == rule], hits
    if rule not in ESCAPED:
        assert not hits, f"{rule}: the safe forms hit other rules: {hits}"


def test_a_hit_names_what_reaches_the_text() -> None:
    (hit,) = sql_rules.scan_source('def f(cur, name):\n    cur.execute(f"DELETE FROM t WHERE n = {name}")\n')
    assert (hit.rule, hit.line, hit.what) == ("SQLS01", 2, "name")


def test_a_sql_composition_and_a_non_sql_call_are_not_hits() -> None:
    src = (
        "from psycopg import sql\n"
        "def f(cur, table, ax, d):\n"
        "    cur.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table)))\n"
        "    ax.text(0, 1, f'{table}')\n"
        "    return d.copy()\n"
    )
    assert sql_rules.scan_source(src) == []


def _ledger_ids() -> set[str]:
    ids: set[str] = set()
    for e in sql_rules.load_ledger()["findings"]:
        ids |= set(e["ids"])
    return ids


def test_the_ledger_is_well_formed_and_names_only_registered_findings() -> None:
    ledger = sql_rules.load_ledger()
    assert ledger["reviewed"] and ledger["findings"]
    for e in ledger["reviewed"]:
        assert len(str(e["reason"])) > 20, e
        assert (ROOT / str(e["path"])).is_file(), e
    known = {f["id"] for p in FINDINGS for f in json.loads(p.read_text(encoding="utf-8"))["findings"]}
    assert _ledger_ids() <= known, _ledger_ids() - known


def test_the_ledger_refuses_an_entry_without_a_reason(tmp_path: Path) -> None:
    bad = tmp_path / "ledger.yaml"
    bad.write_text("reviewed:\n  - {path: a.py, rule: SQLS01, count: 1}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reason"):
        sql_rules.load_ledger(bad)
    bad.write_text("reviewed:\n  - {path: a.py, rule: SQLS99, count: 1, reason: a reason long enough}\n")
    with pytest.raises(ValueError, match="no rule"):
        sql_rules.load_ledger(bad)


def test_a_new_hit_and_a_stale_line_are_named() -> None:
    hits = sql_rules.scan_source('def f(cur, n):\n    cur.execute(f"SELECT * FROM t LIMIT {n}")\n', "x.py")
    ledger: dict[str, list[dict[str, object]]] = {"reviewed": [], "findings": []}
    assert sql_rules.judge(hits, ledger).new == hits
    ledger["reviewed"] = [{"path": "x.py", "rule": "SQLS01", "count": 1, "reason": "r"}]
    ledger["findings"] = [{"path": "x.py", "rule": "SQLS14", "count": 1, "ids": ["X-1"]}]
    v = sql_rules.judge(hits, ledger)
    assert (v.new, v.stale, v.reviewed, v.known) == ([], [], 1, {"X-1": 1})
    assert sql_rules.judge([], ledger).stale == ["x.py SQLS01: ledger 1, found 0", "x.py SQLS14: ledger 1, found 0"]


def test_report_only_exits_0_and_check_exits_1_on_a_new_hit(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text('def f(cur, name):\n    cur.execute(f"SELECT 1 FROM t WHERE n = {name}")\n', encoding="utf-8")
    out = tmp_path / "out" / "sql_rules.json"
    assert sql_rules.main([str(planted), "--json", str(out)]) == 0
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["by_rule"]["SQLS01"] == {"hits": 1, "new": 1}
    assert sql_rules.main([str(planted), "--check"]) == 1


def test_the_tree_matches_the_ledger_warning_only() -> None:
    hits = sql_rules.scan(list(sql_rules.DEFAULT_PATHS))
    assert hits, "no hit at all: the rules or the tree changed"
    v = sql_rules.judge(hits, sql_rules.load_ledger())
    if v.new or v.stale:
        new = sorted({f"{h.place()} {h.rule}" for h in v.new})
        warnings.warn(f"SQL rules differ from the ledger: new {new}; stale {v.stale}", stacklevel=1)
