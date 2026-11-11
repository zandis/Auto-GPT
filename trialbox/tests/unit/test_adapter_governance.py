"""T-659b (D-370, D-381; DATA-002): the controls of the retired data platform, now in the adapter.

The planted defects of the old publish-gate test (``tb_testkit.defects``: row drop, type drift, duplicate key, null
patient key, control-total mismatch) each hold the adapter's night with their reason code in the night's one gate
record, while ``CURRENT`` stays on the last good night. Quarantined rows are counted by reason and never mapped; no
chart number reaches the gate, the contract report or the lineage. A chart-number merge adds one alias row, and both
chart numbers then give one pid; nothing is re-keyed. Synthetic site A only.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from adapter import governance
from adapter.ndjson import snapshot_dir
from adapter.pidmap import AliasError, PidMap, pseudonym
from adapter.pipeline import AdapterConfig, apply_aliases, run_ingest
from tb_contracts.landing import ReasonCode, Severity
from tb_testkit.defects import EXPECTED_REASON, Defect, plant, write_source_totals

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"k" * 32
GOOD, BAD = "2026-10-04", "2026-10-05"
DEFECT_TABLE: dict[Defect, tuple[str, str | None]] = {
    Defect.ROW_DROP: ("lab", None),
    Defect.TYPE_DRIFT: ("vital", "weight_kg"),
    Defect.DUPLICATE_KEY: ("encounter", None),
    Defect.NULL_IDENTIFIER: ("diagnosis", None),
    Defect.CONTROL_TOTAL_MISMATCH: ("medication", None),
}


def _rebuild(lake: Path) -> Any:
    from tb_contracts import RebuildResult

    def go(snap: str, nd: Path) -> RebuildResult:
        (lake / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)

    return go


def _cfg(tmp: Path, contracts: Path | None = governance.DEMO_HIS, **kw: Any) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
                         audit_dir=tmp / "audit", rebuild=_rebuild(tmp / "lake"), contracts_dir=contracts, **kw)  # fmt: skip


def _drop(tmp: Path, totals: bool = True) -> Path:
    dst = tmp / "drop"
    shutil.copytree(SITE_A, dst, ignore=shutil.ignore_patterns("*.json"))
    if totals:
        cs = governance.load_contracts(governance.DEMO_HIS)
        write_source_totals(dst, {t: (c.keys.patient, c.keys.watermark) for t, c in cs.items()})
    return dst


def _night(cfg: AdapterConfig, drop: Path, snap: str) -> Any:
    return run_ingest(cfg, "csv", str(drop), snapshot=snap, load_fhir=False, validate=False)


def _gate(lake: Path, snap: str) -> dict[str, Any]:
    return dict(json.loads((lake / "gates" / f"{snap}.json").read_text(encoding="utf-8")))


def _mrns() -> set[str]:
    with (SITE_A / "patient.csv").open(encoding="utf-8-sig", newline="") as fh:
        return {r["mrn"] for r in csv.DictReader(fh)}


@pytest.fixture(scope="module")
def good(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> Path:
    """One good night of site A under the contracts, with the export's control totals."""
    tmp = tmp_path_factory.mktemp("gov")
    sep = "&" if "?" in pg_cluster_url else "?"
    cfg = _cfg(tmp, db_url=f"{pg_cluster_url}{sep}tb_prefix=gov{os.getpid()}_")
    rep = _night(cfg, _drop(tmp), GOOD)
    assert rep.passed, rep.errors
    return tmp


def test_a_clean_night_publishes_with_one_gate_record_and_its_lineage(good: Path) -> None:
    lake = good / "lake"
    gate = _gate(lake, GOOD)
    assert gate["outcome"] in ("PUBLISH", "PUBLISH_WITH_WARNINGS") and gate["blocking_reasons"] == []
    results = {c["name"]: c["result"] for c in gate["conditions"]}
    assert results["every mapped table meets its contract"] == "pass"
    assert results["the export's control totals hold"] == "pass"
    assert set(results.values()) == {"pass"}
    assert [p.name for p in (lake / "gates").glob("*.json")] == [f"{GOOD}.json"]
    night = snapshot_dir(lake, GOOD)
    assert json.loads((night / governance.GATE).read_text()) == gate
    lin = json.loads((night / governance.LINEAGE).read_text())
    assert governance.lineage_complete(lin)
    assert {i["name"] for i in lin["inputs"]} >= {"patient.csv", "lab.csv"}
    assert lin["mapping"]["name"] == "demo_his.yaml" and lin["gate"]["outcome"] == gate["outcome"]
    rep = json.loads((night / governance.CONTRACT_REPORT).read_text())
    assert rep["outcome"] in ("pass", "warn") and {t["table"] for t in rep["tables"]} >= {"lab", "patient"}
    eqs = rep["reconciliation"]["equations"]
    assert eqs and all(e["verdict"] == "pass" for e in eqs)


@pytest.mark.parametrize("defect", list(Defect), ids=lambda d: d.value)
def test_each_planted_defect_holds_the_night_with_its_reason(defect: Defect, good: Path, tmp_path: Path) -> None:
    shutil.copytree(good / "lake", tmp_path / "lake")
    drop = _drop(tmp_path)
    table, column = DEFECT_TABLE[defect]
    planted = plant(defect, drop, table, column)
    assert planted.expected_reason == EXPECTED_REASON[defect]
    cfg = _cfg(tmp_path)
    rep = _night(cfg, drop, BAD)
    assert rep.held and not rep.passed
    gate = _gate(cfg.lake_dir, BAD)
    assert gate["outcome"] == "HOLD" and planted.expected_reason.value in gate["blocking_reasons"], gate
    assert gate["current_before"] == gate["current_after"] == GOOD
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD
    night = snapshot_dir(cfg.lake_dir, BAD)
    crep = json.loads((night / governance.CONTRACT_REPORT).read_text())
    tv = next(t for t in crep["tables"] if t["table"] == table)
    eqs = [e for e in crep["reconciliation"]["equations"] if e["table"] == table and e["verdict"] == "fail"]
    assert any(f["reason"] == planted.expected_reason.value for f in tv["findings"]) or any(
        e["reason"] == planted.expected_reason.value for e in eqs
    )
    assert planted.expected_reason.value in " ".join(rep.errors)
    # no chart number in what the night writes about itself
    text = " ".join((night / n).read_text() for n in (governance.GATE, governance.CONTRACT_REPORT, governance.LINEAGE))
    text += "".join(f.read_text() for f in (tmp_path / "audit").glob("*.jsonl"))
    assert not any(f'"{m}"' in text or f" {m} " in text for m in _mrns())
    assert all(k.startswith("k_") for k in tv["example_keys"])
    audit = [json.loads(x) for f in (tmp_path / "audit").glob("*.jsonl") for x in f.read_text().splitlines()]
    held = [e for e in audit if e["event"] == "ingest.held"]
    assert held and held[-1]["detail"]["gate"]["outcome"] == "HOLD"


def test_quarantined_rows_are_counted_and_never_mapped(tmp_path: Path) -> None:
    drop = _drop(tmp_path)
    plant(Defect.NULL_IDENTIFIER, drop, "lab")
    cfg = _cfg(tmp_path)
    rep = _night(cfg, drop, GOOD)
    crep = json.loads((snapshot_dir(cfg.lake_dir, GOOD) / governance.CONTRACT_REPORT).read_text())
    tv = next(t for t in crep["tables"] if t["table"] == "lab")
    assert tv["quarantined"] == 1 and tv["accepted"] == tv["landed"] - 1
    assert tv["quarantine_by_reason"] == {"NULL_IDENTIFIER": 1}
    assert rep.held and "NULL_IDENTIFIER" in _gate(cfg.lake_dir, GOOD)["blocking_reasons"]
    clean = tmp_path / "clean"
    clean.mkdir()
    ref = _night(_cfg(clean), _drop(clean), GOOD)
    assert rep.counts["Observation"] == ref.counts["Observation"] - 1  # the row was set aside, not mapped


def test_a_mapped_table_without_a_contract_holds(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    shutil.copytree(governance.DEMO_HIS, contracts)
    (contracts / "lab.yaml").unlink()
    cfg = _cfg(tmp_path, contracts)
    rep = _night(cfg, _drop(tmp_path), GOOD)
    assert rep.held and "CONTRACT_MISSING" in _gate(cfg.lake_dir, GOOD)["blocking_reasons"]


def test_without_control_totals_the_condition_is_not_evaluated(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    rep = _night(cfg, _drop(tmp_path, totals=False), GOOD)
    assert rep.passed, rep.errors
    conds = {c["name"]: c["result"] for c in _gate(cfg.lake_dir, GOOD)["conditions"]}
    assert conds["the export's control totals hold"] == "not_evaluated"


@pytest.mark.nodb
def test_without_contracts_the_gate_still_writes_one_record(tmp_path: Path) -> None:
    """No contracts configured (the default): condition 1 is not evaluated; the T-611 gate and the rest still are."""
    rec = governance.gate_record(governance.NightFacts(night=GOOD, completeness=["lab: table missing"]), _now())
    assert rec.outcome == "HOLD" and rec.blocking_reasons == [ReasonCode.FEED_INCOMPLETE]
    assert rec.conditions[0].result == "not_evaluated"
    ok = governance.gate_record(governance.NightFacts(night=GOOD, current_before="a", current_after=GOOD), _now())
    assert ok.outcome == "PUBLISH" and ok.current_after == GOOD


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 10, 5, 2, 0, tzinfo=UTC)


@pytest.mark.nodb
def test_drift_is_additive_or_breaking() -> None:
    c = governance.load_contracts(governance.DEMO_HIS)["lab"]
    cols = [x.name for x in c.columns]
    assert governance.classify_drift(c, cols)[0] == "none"
    assert governance.classify_drift(c, [*cols, "new_col"])[0] == "additive"
    kind, findings = governance.classify_drift(c, cols[1:])
    assert kind == "breaking" and findings[0].reason == ReasonCode.SCHEMA_DRIFT_BREAKING
    rows = [{x: "1" for x in cols} | {"sample_datetime": "yesterday"}]
    chk = governance.check_table(c, "lab", rows, today=_now().date())
    assert ReasonCode.TYPE_MISMATCH in {f.reason for f in chk.validation.findings}


@pytest.mark.nodb
def test_every_check_is_kahn_labelled_and_every_contract_loads() -> None:
    for d in (governance.DEMO_HIS, governance.MIMIC_FHIR):
        cs = governance.load_contracts(d)
        assert cs
        for c in cs.values():
            assert governance.rules_for(c)
    c = governance.load_contracts(governance.DEMO_HIS)["vital"]
    chk = governance.check_table(c, "vital", [], today=_now().date())
    assert all(x.kahn_category in ("conformance", "completeness", "plausibility") for x in chk.validation.checks)
    assert {x.expectation for x in chk.validation.checks} >= {
        "expect_column_values_to_not_be_null",
        "expect_compound_columns_to_be_unique",
        "expect_column_values_to_be_of_type",
    }
    assert any(f.reason == ReasonCode.VOLUME_ZERO and f.severity == Severity.BLOCKING for f in chk.validation.findings)


# ------------------------------------------------------------------------------------------------ the alias table
def test_a_chart_merge_maps_both_numbers_to_one_pid_with_one_alias_row(tmp_path: Path) -> None:
    """DATA-002's acceptance: A -> B maps both to one pid with an alias row; nothing is re-keyed."""
    pm = PidMap(tmp_path / "pid_map.key")
    try:
        a, b = pseudonym(KEY, "10000002")[0], pseudonym(KEY, "10000003")[0]
        pm.upsert_many([(a, "10000002"), (b, "10000003")])
        assert pm.merge(KEY, "10000002", "10000003", "duplicate chart", "HIS-1") == (a, b)
        assert pm.surviving(a) == pm.surviving(b) == b
        assert pm.aliases() == {a: b}
        assert pm.resolve(a) == "10000002" and pm.resolve(b) == "10000003"  # the pid map keeps both rows
        assert pm.merge(KEY, "10000002", "10000003", "again", "HIS-1") == (a, b)  # the same merge: no new row
        with pytest.raises(AliasError):
            pm.merge(KEY, "10000002", "10000004", "elsewhere", "HIS-2")  # append-only: never moved
        with pytest.raises(AliasError):
            pm.merge(KEY, "10000003", "10000002", "back", "HIS-3")  # a cycle
        with pytest.raises(AliasError):
            pm.merge(KEY, "10000005", "10000006", " ", "HIS-4")
        rows = pm._db.fetchall("SELECT old_pid, pid, reason, ticket FROM pid_alias")
        assert [tuple(r) for r in rows] == [(a, b, "duplicate chart", "HIS-1")]
    finally:
        pm.close()


def test_the_ingest_writes_a_merged_patients_records_under_the_surviving_pid(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, None)
    pm = cfg.pidmap()
    try:
        old, new = pm.merge(KEY, "10000002", "10000003", "duplicate chart", "HIS-1")
    finally:
        pm.close()
    rep = _night(cfg, _drop(tmp_path, totals=False), GOOD)
    assert rep.passed, rep.errors
    night = snapshot_dir(cfg.lake_dir, GOOD)
    ids = {json.loads(x)["id"] for x in (night / "Patient.ndjson").read_text().splitlines() if x.strip()}
    assert new in ids and old not in ids
    obs = (night / "Observation.ndjson").read_text()
    assert f"Patient/{old}" not in obs and f"Patient/{new}" in obs


@pytest.mark.nodb
def test_apply_aliases_moves_references_and_drops_the_merged_patient() -> None:
    by_type: dict[str, list[dict[str, Any]]] = {
        "Patient": [{"resourceType": "Patient", "id": "a"}, {"resourceType": "Patient", "id": "b"},
                    {"resourceType": "Patient", "id": "c", "identifier": [{"value": "c"}]}],
        "Condition": [{"resourceType": "Condition", "id": "x", "subject": {"reference": "Patient/a"}},
                      {"resourceType": "Condition", "id": "y", "subject": {"reference": "Patient/c"}}],
    }  # fmt: skip
    assert apply_aliases(by_type, {"a": "b", "c": "d"}) == 2
    assert [p["id"] for p in by_type["Patient"]] == ["b", "d"]
    assert by_type["Patient"][1]["identifier"] == [{"value": "d"}]
    assert [c["subject"]["reference"] for c in by_type["Condition"]] == ["Patient/b", "Patient/d"]
    assert apply_aliases(by_type, {}) == 0
