"""L1 validation and the publish gate (spec v4 §5.3 L1, §5.8–§5.10, DP-18…DP-25; S1-03).

Done-when of S1-03: each planted defect on synthetic data blocks publish with its reason code, the steward receives
the diff (here: a rendered notice), and the previous snapshot stays current. Site A of ``tools/make_fixtures.py``
stands in for Synthea 300k (scale is not part of the unit tests).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from dataplat import curated
from dataplat.common import fixed_clock
from dataplat.contracts import DEMO_HIS, classify_drift, load_contracts
from dataplat.dq import suite_for
from dataplat.landing import LandingZone, read_drop
from dataplat.pipeline import PipelineResult, run_pipeline
from dataplat.validate import validate_batch
from tb_contracts.landing import ColumnShape, ReasonCode, Severity
from tb_testkit.defects import EXPECTED_REASON, Defect, plant, write_source_totals

SITE_KEY = b"trialbox-test-site-key-0123456789abcdef"
CLOCK = fixed_clock(datetime(2026, 10, 5, 2, 0, tzinfo=UTC))
DEFECT_TABLE: dict[Defect, tuple[str, str | None]] = {
    Defect.ROW_DROP: ("lab", None),
    Defect.TYPE_DRIFT: ("vital", "weight_kg"),
    Defect.DUPLICATE_KEY: ("encounter", None),
    Defect.NULL_IDENTIFIER: ("diagnosis", None),
    Defect.CONTROL_TOTAL_MISMATCH: ("medication", None),
}


def _site_a_drop(synth_dir: Path, dest: Path) -> Path:
    shutil.copytree(synth_dir / "site-a", dest)
    contracts = load_contracts(DEMO_HIS)
    write_source_totals(dest, {t: (c.keys.patient, c.keys.watermark) for t, c in contracts.items()})
    return dest


def _run(src: Path, work: Path, **kw: Any) -> PipelineResult:
    return run_pipeline(src, work, site_key=SITE_KEY, clock=CLOCK, snapshot=kw.pop("snapshot", "2026-10-04"), **kw)


@pytest.fixture(scope="module")
def baseline(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, PipelineResult]:
    root = tmp_path_factory.mktemp("dp_gate")
    src = _site_a_drop(synth_dir, root / "drop")
    work = root / "work"
    res = _run(src, work)
    return src, work, res


@pytest.mark.req("S1-03", "DP-20", "DP-19")
def test_clean_site_a_publishes(baseline: tuple[Path, Path, PipelineResult]) -> None:
    _, work, res = baseline
    assert res.outcome == "PUBLISH", res.gate.conditions
    assert res.batch is not None and res.batch.control_totals_origin == "source"
    assert res.validation is not None and res.validation.outcome == "pass"
    assert res.validation.reconciliation.passed and res.reconciliation is not None and res.reconciliation.passed
    levels = {e.level for e in res.validation.reconciliation.equations + res.reconciliation.equations}
    assert levels == {"source→L0", "L0→L1", "L1→L2", "L2→L3", "L3→L4"}
    names = {e.name for e in res.validation.reconciliation.equations}
    assert {"count(*)", "count(distinct mrn)"} <= names and any(n.startswith("max(") for n in names)
    assert res.current is not None and res.current.snapshot_id == "snap_2026-10-04"
    assert [c.result for c in res.gate.conditions] == [
        "pass",
        "pass",
        "not_evaluated",
        "pass",
        "pass",
        "not_evaluated",
        "pass",
    ]
    assert len(list((work / "gates").glob("*.json"))) == 1


@pytest.mark.parametrize("defect", list(Defect), ids=lambda d: d.value)
@pytest.mark.req("S1-03", "DP-20", "DP-25")
def test_each_planted_defect_blocks_publish_with_its_reason(
    defect: Defect, baseline: tuple[Path, Path, PipelineResult], tmp_path: Path
) -> None:
    src0, work0, base = baseline
    src = tmp_path / "drop"
    shutil.copytree(src0, src)
    work = tmp_path / "work"
    shutil.copytree(work0, work)
    table, column = DEFECT_TABLE[defect]
    planted = plant(defect, src, table, column)
    assert planted.expected_reason == EXPECTED_REASON[defect]

    res = _run(src, work, snapshot="2026-10-05")

    assert res.outcome == "HOLD"
    assert planted.expected_reason.value in res.blocking_reasons, res.blocking_reasons
    assert res.validation is not None and res.validation.blocked
    tv = next(t for t in res.validation.tables if t.table == table)
    assert any(f.reason == planted.expected_reason and f.severity == Severity.BLOCKING for f in tv.findings) or any(
        e.reason == planted.expected_reason and e.table == table for e in res.validation.reconciliation.equations
    )
    # no partial publish: nothing of the held cycle is referenced, the previous snapshot stays current
    assert res.manifest is None
    assert curated.published(work / "l4") == ["2026-10-04"]
    assert not (work / "l4" / "staging" / "2026-10-05").exists()
    assert res.current is not None and base.current is not None
    assert res.current == base.current
    assert (work / "l4" / "lake" / "CURRENT").read_text() == "2026-10-04"
    assert not (work / "l4" / "lake" / "db" / "2026-10-05.duckdb").exists()
    assert res.gate.current_before == res.gate.current_after == "snap_2026-10-04"
    # the steward notice: rendered, addressed, carrying the diff and no patient identifiers
    n = res.notice
    assert n is not None
    assert n.to == ["steward-research-informatics@site-a.example"]
    assert "research-office@site-a.example" in n.cc and "his-dba@site-a.example" in n.cc
    assert planted.expected_reason.value in n.subject + n.body
    assert any(planted.expected_reason.value in r for r in n.failed_rules)
    assert "snap_2026-10-04" in n.body
    mrns = {line.split(",")[0] for line in (src / "patient.csv").read_text().splitlines()[1:]}
    assert not any(re.search(rf"\b{m}\b", n.body) for m in mrns)
    assert all(k.startswith("k_") for k in n.example_keys)
    assert (work / "notices" / f"{n.notice_id}.json").exists()
    # the hold is in the serving history and the lineage log (publish run FAILed)
    hist = [json.loads(x) for x in (work / "l5" / "history.jsonl").read_text().splitlines()]
    assert hist[-1]["action"] == "hold" and hist[-1]["snapshot_id"] == "snap_2026-10-04"
    events = [json.loads(x) for x in (work / "lineage" / "events.jsonl").read_text().splitlines()]
    mine = [e for e in events if e["run"]["facets"]["tb_cycle"]["cycle_id"] == res.cycle_id]
    assert any(e["job"]["name"] == "tb.l4.publish" and e["eventType"] == "FAIL" for e in mine)


@pytest.mark.req("S1-03", "DP-19")
def test_quarantined_rows_are_counted_never_dropped(
    baseline: tuple[Path, Path, PipelineResult], tmp_path: Path
) -> None:
    src0, _, _ = baseline
    src = tmp_path / "drop"
    shutil.copytree(src0, src)
    plant(Defect.NULL_IDENTIFIER, src, "lab")
    res = _run(src, tmp_path / "work")
    assert res.validation is not None
    tv = next(t for t in res.validation.tables if t.table == "lab")
    assert tv.quarantined == 1 and tv.accepted == tv.landed - 1
    assert tv.quarantine_by_reason == {"NULL_IDENTIFIER": 1}
    eq = next(e for e in res.validation.reconciliation.equations if e.level == "L0→L1" and e.table == "lab")
    assert eq.verdict == "pass" and eq.lhs == tv.landed
    q = (tmp_path / "work" / "l1" / "demo_his").glob("*/quarantine/lab.jsonl")
    lines = [json.loads(x) for p in q for x in p.read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["reasons"] == ["NULL_IDENTIFIER"]


@pytest.mark.req("DP-18")
def test_a_table_without_contract_blocks(baseline: tuple[Path, Path, PipelineResult], tmp_path: Path) -> None:
    src0, _, _ = baseline
    src = tmp_path / "drop"
    shutil.copytree(src0, src)
    (src / "surprise.csv").write_text("a,b\r\n1,2\r\n", encoding="utf-8")
    res = _run(src, tmp_path / "work")
    assert res.outcome == "HOLD" and "CONTRACT_MISSING" in res.blocking_reasons


@pytest.mark.req("DP-18")
def test_drift_is_classified_additive_or_breaking() -> None:
    c = load_contracts(DEMO_HIS)["lab"]
    base = [ColumnShape(name=col.name, type=col.type, nullable=col.nullable) for col in c.columns]
    assert classify_drift(c, base)[0] == "none"
    assert classify_drift(c, [*base, ColumnShape(name="new_col", type="string", nullable=True)])[0] == "additive"
    assert classify_drift(c, base[1:])[0] == "breaking"  # dropped column
    retyped = [
        ColumnShape(name=x.name, type="string" if x.name == "sample_datetime" else x.type, nullable=x.nullable)
        for x in base
    ]
    kind, findings = classify_drift(c, retyped)
    assert kind == "breaking" and findings[0][0] == ReasonCode.SCHEMA_DRIFT_BREAKING


@pytest.mark.req("DP-22", "DP-23")
def test_every_dq_rule_is_kahn_labelled(baseline: tuple[Path, Path, PipelineResult]) -> None:
    _, _, res = baseline
    assert res.validation is not None
    checks = [c for t in res.validation.tables for c in t.checks]
    assert checks and all(c.kahn_category in ("conformance", "completeness", "plausibility") for c in checks)
    assert all(c.kahn_subtype and c.context in ("verification", "validation") for c in checks)
    assert {c.expectation for c in checks} >= {
        "expect_column_values_to_not_be_null",
        "expect_compound_columns_to_be_unique",
        "expect_column_values_to_be_of_type",
        "expect_table_row_count_to_be_between",
    }
    for c in load_contracts(DEMO_HIS).values():
        assert suite_for(c)  # one suite per contract
    src = Path(__file__).resolve().parents[2] / "services" / "dataplat"
    assert not any("soda" in p.read_text(encoding="utf-8").lower().replace("soda core", "") for p in src.rglob("*.py"))


@pytest.mark.req("S1-03")
def test_missing_source_totals_are_taken_at_extract(synth_dir: Path, tmp_path: Path) -> None:
    """A drop without control_totals.json gets connector totals (origin ``extract``) and still validates."""
    zone = LandingZone(tmp_path / "l0", CLOCK)
    drop = read_drop(synth_dir / "site-a")
    assert drop.control_totals is None
    m = zone.land("demo_his", drop.files).manifest
    res = validate_batch(zone, m, load_contracts(DEMO_HIS), key_hasher=lambda s: "k_" + s[:4], clock=CLOCK)
    assert res.report.blocked and ReasonCode.CONTROL_TOTALS_MISSING in res.report.blocking_reasons
