"""Onboarding kit tools (SPEC §12 phase 9): ruleset spec export, parser backend comparison, mapping column analysis,
mapping ``extends`` / ``rename`` / ``values``."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from adapter.mapping.engine import Mapping, MappingError

from tools import export_spec, mapping_check, parser_compare

ROOT = Path(__file__).resolve().parents[2]


def test_export_spec_matches_artifacts() -> None:
    spec = export_spec.export(ROOT / "rulesets" / "GZQO")
    assert spec["ruleset"] == "GZQO" and spec["status"] == "approved" and len(spec["criteria"]) >= 20
    by_id = {c["id"]: c for c in spec["criteria"]}
    assert by_id["GZQO-INC-01"]["definition"] == "age ≥ 18"
    assert "latest bmi ≥ 27 kg/m2, within 365 days" in by_id["GZQO-INC-03"]["definition"]
    assert any(code.startswith("M10") for code in by_id["GZQO-INC-02"]["valuesets"]["VS_GOUT"])
    sql = (ROOT / "rulesets/GZQO/sql/GZQO.sql").read_text(encoding="utf-8")
    assert spec["artifacts"]["sql/GZQO.sql"] == hashlib.sha256(sql.encode()).hexdigest()
    md = export_spec.markdown(spec)
    assert md.startswith("# GZQO v1.0.0") and "## Artifacts (sha256)" in md


def test_parser_compare_recall(tmp_path: Path) -> None:
    assert parser_compare.recall(["Age ≥ 18", "Gout"], ["age ≥18", "gout", "BMI ≥ 27"]) == 66.7
    assert parser_compare.recall([], []) is None
    assert parser_compare.table_recall([[["a", "b"], ["c", ""]]], [[["a", "b"], ["c", "d"]]]) == 75.0
    rows = parser_compare.compare(ROOT / "tests" / "fixtures" / "protocols")
    gzqo = next(r for r in rows if r["document"] == "GZQO_protocol_v3.pdf" and r["backend"] == "lite")
    assert gzqo["inclusion"] >= 9 and gzqo["exclusion"] >= 14


def test_referenced_columns() -> None:
    m = Mapping.load(ROOT / "services/adapter/mapping/tw_core/demo_his.yaml")
    med = next(r for r in m.resources if r.type == "MedicationRequest")
    cols = mapping_check.referenced_columns(med.elements)
    assert {"nhi_drug_code", "atc", "drug_name", "order_date", "start_date", "end_date", "daily_dose"} <= cols
    assert mapping_check._patient_columns(med.elements) == {"mrn"}


def test_extends_rename_values(tmp_path: Path) -> None:
    (tmp_path / "lab.csv").write_text(
        (ROOT / "services/adapter/mapping/tw_core/lab_local_to_loinc.csv").read_text(encoding="utf-8"), encoding="utf-8"
    )
    site = tmp_path / "site.yaml"
    site.write_text(
        f"""version: 1
name: t
extends: {ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"}
tables:
  patient:
    source: PT
    key: mrn
    rename: {{CHART: mrn, SEXCD: sex}}
    values: {{sex: {{1: M, 2: F}}}}
  encounter:
    source: VISIT
    key: enc_no
    delta: visit_datetime
    rename: {{VNO: enc_no, VTIME: visit_datetime}}
lookups:
  lab: {{file: lab.csv, key: local_code}}
""",
        encoding="utf-8",
    )
    m = Mapping.load(site)
    assert set(m.tables) == {"patient", "encounter"}
    assert {r.table for r in m.resources} == {"patient", "encounter"}  # undeclared tables' resources dropped
    assert m.normalize("patient", {"CHART": "C1", "SEXCD": "2", "X": "y"}) == {"mrn": "C1", "sex": "F", "X": "y"}
    assert m.source_column("encounter", "visit_datetime") == "VTIME"
    assert m.source_column("patient", "birth_date") == "birth_date"
    assert "loinc" in m.systems and m.lookups["lab"].rows
    nested = tmp_path / "nested.yaml"
    nested.write_text(f"version: 1\nextends: {site}\ntables: {{}}\n", encoding="utf-8")
    with pytest.raises(MappingError, match="cannot extend"):
        Mapping.load(nested)
