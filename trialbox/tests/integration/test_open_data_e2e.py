"""Open-data end-to-end: MIMIC-IV FHIR demo -> adapter -> lake -> FEAS for two real ClinicalTrials.gov trials.

In process (no compose stack). Needs the PhysioNet files from ``python tools/fetch_open_data.py`` (``make
open-data-e2e``); skipped when they are absent so CI without network passes. docs/OPEN_DATA.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import open_data_e2e as od

pytestmark = [
    pytest.mark.slow,
    pytest.mark.timeout(3600),  # two full ingests; the default 900 s is per test and includes the fixture
    pytest.mark.skipif(
        not od.data_available(), reason="MIMIC-IV FHIR demo not fetched (python tools/fetch_open_data.py)"
    ),
]


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return od.run(repro=True)  # two independent ingests + FEAS runs


def test_ingest_and_mapping(report: dict[str, Any]) -> None:
    assert report["patients"] == 100
    counts = report["normalisation"]["counts"]
    assert report["normalisation"]["patients_shifted"] == 100
    assert counts["condition.icd10"] > 1000 and counts["condition.icd9_mapped"] > 50
    assert counts["observation.loinc"] == counts["observation.total"] > 10000
    assert counts["medication_request.atc"] > 100 and counts.get("medication_request.unresolved", 0) == 0
    assert counts["encounter.icu"] > 50 and counts["procedure.icu_snomed"] > 10
    lake = report["ingest"]["lake_tables"]
    assert lake["patient"] == 100 and lake["observation"] == counts["observation.total"]
    assert lake["condition"] == counts["condition.total"]
    assert not report["ingest"]["errors"]


def test_feas_invariants(report: dict[str, Any]) -> None:
    assert set(report["trials"]) == set(od.RULESETS)
    for rid, trial in report["trials"].items():
        assert report["invariants"][rid] == [], (rid, report["invariants"][rid])
        raw = trial["raw"]
        assert 0 < raw["start_n"] <= 100
        applied = [c for c in trial["criteria"] if c["applied"]]
        skipped = [c for c in trial["criteria"] if not c["applied"]]
        assert applied and skipped and all(c["class"] in ("note", "human") for c in skipped)
        rem = [raw["remaining"][c["id"]] for c in applied]
        assert rem == sorted(rem, reverse=True) and rem[0] <= raw["start_n"]
        # every structured criterion is evaluated on real data: some patients have a known value
        assert all(pc["known"] > 0 for pc in raw["per_criterion"].values())
        # the age criterion keeps every adult in this ICU cohort
        assert raw["per_criterion"][f"{rid}-INC-01"]["met"] == raw["start_n"]


def test_small_cell_rounding_in_released_output(report: dict[str, Any]) -> None:
    for trial in report["trials"].values():
        rel = trial["released"]
        values = (
            [rel["start_n"]] + [f["remaining"] for f in rel["funnel"]] + [s["remaining"] for s in rel["sensitivity"]]
        )
        for v in values:
            assert v == "<5" or (isinstance(v, int) and v % 5 == 0), v
        exact = {f["criterion_id"]: trial["raw"]["remaining"].get(f["criterion_id"]) for f in rel["funnel"]}
        for f in rel["funnel"]:
            n = exact[f["criterion_id"]]
            if isinstance(n, int) and 0 < n < 5:
                assert f["remaining"] == "<5"


def test_reproducible(report: dict[str, Any]) -> None:
    assert report["reproducible"] is True
    assert report["passed"] is True


def test_report_files(report: dict[str, Any], tmp_path: Path) -> None:
    od.write_outputs(report, tmp_path)
    body = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert body["results_sha256"] == report["results_sha256"] and body["passed"] is True
    md = (tmp_path / "report.md").read_text("utf-8")
    for rid, trial in report["trials"].items():
        assert rid in md and trial["nct_id"] in md
    assert "Result: PASS" in md
