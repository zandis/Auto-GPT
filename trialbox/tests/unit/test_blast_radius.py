"""Blast-radius tooling (RULEQ-1 §4): the impact index, the canary diff, the rollback property, the provenance walk."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR
from tb_contracts.criterion_ir import upgrade_v1

from tools.blast_radius import canary, impact_index, provenance, reconfirm_rows

ROOT = Path(__file__).resolve().parents[2]
RS = ROOT / "rulesets"


def _pin(rulesets: Path, ruleset: str, criterion: str, card: str, version: str) -> None:
    """Re-express one live criterion as an instance of ``card@version`` (IR 3.1, atoms unchanged)."""
    path = rulesets / ruleset / "ir" / (criterion + ".json")
    d = json.loads(path.read_text(encoding="utf-8"))
    if "atoms" not in d:  # still v1: upgrade once, later pins only change the card_ref
        d = json.loads(upgrade_v1(CriterionIR.model_validate(d)).model_dump_json(by_alias=True, exclude_none=True))
    d.update(ir_version="3.1.0", card_ref={"card_id": card, "card_version": version, "params": {"n": 1}})
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def rulesets(tmp_path: Path) -> Path:
    for rid in ("RA-COH", "RA-JAK"):
        shutil.copytree(RS / rid, tmp_path / rid)
    return tmp_path


def _sql(rulesets: Path) -> list[bytes]:
    return [p.read_bytes() for p in sorted((rulesets / "RA-COH" / "sql").rglob("*")) if p.is_file()]


def test_impact_index_lists_every_dependent_of_a_card_version(rulesets: Path) -> None:
    _pin(rulesets, "RA-COH", "RA-COH-INC-01", "t.age", "1.0.0")
    _pin(rulesets, "RA-COH", "RA-COH-INC-02", "t.age", "1.0.0")
    first_jak = sorted((rulesets / "RA-JAK" / "ir").glob("*.json"))[0].stem
    _pin(rulesets, "RA-JAK", first_jak, "t.age", "1.1.0")
    idx = impact_index(rulesets)
    assert sorted(k for k in idx if k.startswith("t.age")) == ["t.age@1.0.0", "t.age@1.1.0"]
    rows = reconfirm_rows(idx, "t.age", "1.0.0")
    assert [(r["ruleset"], r["criterion"]) for r in rows] == [("RA-COH", "RA-COH-INC-01"), ("RA-COH", "RA-COH-INC-02")]
    assert {r["protocol_version"] for r in rows} == {"v1"} and reconfirm_rows(idx, "t.age", "9.9.9") == []


def test_a_card_reversion_and_its_rollback_move_nothing(rulesets: Path) -> None:
    crit = "RA-COH-INC-01"
    sql_before = _sql(rulesets)
    before = provenance(rulesets, "RA-COH", crit)
    _pin(rulesets, "RA-COH", crit, "t.age", "1.0.0")
    pinned = provenance(rulesets, "RA-COH", crit)
    idx_v1 = impact_index(rulesets)
    _pin(rulesets, "RA-COH", crit, "t.age", "1.1.0")  # re-version, same atoms
    reversioned = provenance(rulesets, "RA-COH", crit)
    assert [k for k in impact_index(rulesets) if k.startswith("t.age")] == ["t.age@1.1.0"]
    _pin(rulesets, "RA-COH", crit, "t.age", "1.0.0")  # rollback
    # card_ref is outside the hash: the criterion keeps its identity through pin, re-version and rollback
    assert len({p["criterion"]["canonical_hash"] for p in (before, pinned, reversioned)}) == 1
    assert reversioned["card_ref"]["card_version"] == "1.1.0" and pinned["card_ref"]["card_version"] == "1.0.0"
    assert impact_index(rulesets) == idx_v1  # the rollback restores the dependents exactly
    assert _sql(rulesets) == sql_before  # pin, re-version and rollback never touch the compiled text
    # the ruleset's SQL is its own committed text (the loader reads v1 criteria only, so the live copy stands in)
    rs = Ruleset.load(RS / "RA-COH")
    rows = [{"pid": "p" + str(i), "C_" + crit: v} for i, v in enumerate((True, False, None))]
    assert canary(rs, rs, lambda sql, day: rows, "2026-01-31")["moved"] == []


def test_canary_reports_each_moved_verdict_and_criteria_on_one_side() -> None:
    rs = Ruleset.load(RS / "RA-COH")
    c1, c2 = rs.criteria[0].id, rs.criteria[1].id
    base = [{"pid": "a", "C_" + c1: True, "C_" + c2: False}, {"pid": "b", "C_" + c1: None, "C_" + c2: True}]
    changed = [{"pid": "a", "C_" + c1: False, "C_" + c2: False}, {"pid": "c", "C_" + c1: True}]
    calls: list[str] = []

    def runner(sql: str, day: str) -> list[dict[str, Any]]:
        calls.append(day)
        return changed if len(calls) == 2 else base

    narrower = replace(rs, criteria=rs.criteria[:-1])
    out = canary(rs, narrower, runner, "2026-01-31")
    assert out["only_old"] == [rs.criteria[-1].id] and out["only_new"] == [] and out["patients"] == 3
    assert {"pid": "a", "criterion": c1, "old": True, "new": False} in out["moved"]
    assert {"pid": "b", "criterion": c1, "old": None, "new": None} not in out["moved"]  # None on both sides: no move
    assert {"pid": "b", "criterion": c2, "old": True, "new": None} in out["moved"]  # a patient missing on one side
    assert calls == ["2026-01-31", "2026-01-31"]
    with pytest.raises(ValueError, match="two result rows"):
        canary(rs, rs, lambda sql, day: [{"pid": "a"}, {"pid": "a"}], "2026-01-31")


def test_provenance_walks_ruleset_to_card_to_library_record(rulesets: Path) -> None:
    crit = "RA-COH-INC-03"
    _pin(rulesets, "RA-COH", crit, "dx.ra", "2.0.0")
    seen: list[str] = []

    def by_hash(h: str) -> Any:
        seen.append(h)
        return SimpleNamespace(lib_id="cl_x", status="approved", supersedes=None)

    out = provenance(rulesets, "RA-COH", crit, SimpleNamespace(by_hash=by_hash))
    assert seen == [out["criterion"]["canonical_hash"]] and out["criterion"]["canonical_hash"].startswith("sha256:")
    assert out["ruleset"]["id"] == "RA-COH" and out["card_ref"]["card_id"] == "dx.ra"
    assert out["library"] == {"lib_id": "cl_x", "status": "approved", "supersedes": None}
    unpinned = provenance(rulesets, "RA-COH", "RA-COH-INC-04")  # never pinned in this copy: the v1 path
    assert unpinned["card_ref"] is None and unpinned["criterion"]["canonical_hash"].startswith("sha256:")
