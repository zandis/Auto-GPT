"""tools/gen_traceability.py (TB-PLAN-05 §7.4): the matrix is derived from the plan's tables and the plan is consistent."""

from __future__ import annotations

from tools import gen_traceability as gt

SAMPLE = """
### WS-01 Hardening

| ID | Item | Acceptance | Depends on | Owner | Size | Trace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WS-01.1 | a | b | — | agent | 2 S, 1.5 R | URS-PI-01, RSK-01; TST-E2E-01 | G1 |
| WS-01.2 | c | d | — | agent | 1 S | URS-PI-01, URS-ADM-01, RSK-02; TST-SEC-01 | G2 |

### Totals

| Workstream | Agent sessions | Owner and reviewer hours |
| --- | --- | --- |
| WS-01 old | 9 | 9 |
| **All** | **9 agent sessions** | **9 owner and reviewer hours**, plus the engineer |

| ID | Requirement | FS | Plan |
| --- | --- | --- | --- |
| URS-PI-01 | r1 | FS-06 | WS-99.9 |
| URS-ADM-01 | r2 | FS-13 | WS-01.2 |

| ID | Hazard | Harm |
| --- | --- | --- |
| RSK-01 | h | x |
| RSK-02 | h | x |

| ID | Level | What |
| --- | --- | --- |
| TST-E2E-01 | E | e |
| TST-SEC-01 | S | s |
"""


def test_rows_carry_fs_and_level_and_derive_the_plan_column() -> None:
    plan = gt.parse(SAMPLE)
    rows = gt.rows(plan)
    assert {r["requirement"] for r in rows} == {"URS-PI-01", "URS-ADM-01"}
    first = next(r for r in rows if r["plan_item"] == "WS-01.1")
    assert first["fs"] == "FS-06" and first["level"] == "E" and first["evidence"] == "gate: G1"
    assert gt.derive_urs_plan(plan)["URS-PI-01"] == ["WS-01.1", "WS-01.2"]
    assert not gt.orphans(plan)


def test_rewrite_replaces_the_plan_cells_and_the_totals() -> None:
    plan = gt.parse(SAMPLE)
    plan.engineer_hours = ", plus the engineer"
    new = gt.rewrite(SAMPLE, plan)
    assert "| URS-PI-01 | r1 | FS-06 | WS-01.1, WS-01.2 |" in new
    assert "| WS-01 Hardening | 3 | 1.5 |" in new
    assert "| **All** | **3 agent sessions** | **1.5 owner and reviewer hours**, plus the engineer |" in new
    assert "| WS-01 old |" not in new


def test_orphans_are_named() -> None:
    plan = gt.parse(SAMPLE.replace("| RSK-02 | h | x |\n", "").replace("| TST-SEC-01 | S | s |\n", ""))
    errs = gt.orphans(plan)
    assert "RSK used but undefined: RSK-02" in errs
    assert "TST used but undefined: TST-SEC-01" in errs


def test_the_committed_plan_and_matrix_are_consistent() -> None:
    assert gt.main(["--check"]) == 0
