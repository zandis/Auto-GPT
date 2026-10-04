"""COHORT helpers: quarters, alliance CSV v1 round trip and validation, merge arithmetic with suppressed cells,
ClinicalTrials.gov parsing / ranking / cassette replay (SPEC §8.3)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from criteria_compiler.ctgov import CtGov, CtgovError, slug, to_study
from orchestrator.scenarios import cohort, trials
from tb_contracts import CohortTable, CtgovSearchRequest

ROOT = Path(__file__).resolve().parents[2]


def test_quarters() -> None:
    assert cohort.quarter_end(date(2026, 10, 4)) == date(2026, 12, 31)
    assert cohort.quarter_end(date(2026, 2, 1)) == date(2026, 3, 31)
    assert cohort.completed_quarters(date(2026, 10, 4), 4) == [
        date(2025, 12, 31),
        date(2026, 3, 31),
        date(2026, 6, 30),
        date(2026, 9, 30),
    ]
    assert cohort.completed_quarters(date(2026, 9, 30), 1) == [date(2026, 9, 30)]
    assert cohort.quarter_label(date(2026, 9, 30)) == "2026Q3"


def _row(site: str, cid: str, n: Any, nc: Any = 0, version: str = "GOUT-COH@1.0.0") -> dict[str, Any]:
    return {
        "site_id": site,
        "disease": "gout",
        "quarter": "2026Q3",
        "criterion_id": cid,
        "criterion_label": "痛風診斷",
        "n": n,
        "n_contactable": nc,
        "definition_version": version,
    }


def test_csv_round_trip_and_schema() -> None:
    rows = [_row("DEMO-A", "GOUT-COH-INC-01", 154, 98), _row("DEMO-A", "GOUT-COH-INC-02", "<5", "n/a")]
    CohortTable.model_validate({"schema_version": "alliance-v1", "rows": rows})
    data = cohort.to_csv(rows)
    assert data.decode().splitlines()[0] == ",".join(cohort.COLUMNS)
    back, errors = cohort.parse_csv(data)
    assert errors == [] and back == rows
    bad = data.decode().replace("2026Q3", "2026-Q3", 1).encode()
    _, errors = cohort.parse_csv(bad)
    assert errors and "line 2" in errors[0]
    _, errors = cohort.parse_csv(b"site,disease\nA,gout\n")
    assert errors == [f"header must be {','.join(cohort.COLUMNS)}"]
    two_sites = cohort.to_csv([*rows, _row("DEMO-B", "GOUT-COH-INC-01", 10)])
    assert "one file must hold one site's table" in cohort.parse_csv(two_sites)[1]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([120, 34], 154),
        ([3, 1], "<5"),  # exact total below the threshold is suppressed again
        ([0, 0], 0),
        ([120, "<5"], "121-124"),
        (["<5", "<5"], "<9"),  # 2..8 may be small: upper bound only
        (["<5", 1], "<6"),
        ([10, "<5"], "11-14"),
        ([10, "n/a"], "n/a"),
    ],
)
def test_merge_counts(values: list[Any], expected: Any) -> None:
    assert cohort.merge_counts(values, 5) == expected


def test_merged_keeps_definitions_apart() -> None:
    rows = [
        _row("DEMO-A", "GOUT-COH-INC-01", 154, 98),
        _row("DEMO-B", "GOUT-COH-INC-01", 120, "<5"),
        _row("DEMO-C", "GOUT-COH-INC-01", 50, 20, version="GOUT-COH@2.0.0"),
    ]
    out = cohort.merged(rows, 5)
    totals = {(r["definition_version"], r["site_id"]): r for r in out}
    assert totals[("GOUT-COH@1.0.0", "ALLIANCE")]["n"] == 274
    assert totals[("GOUT-COH@1.0.0", "ALLIANCE")]["n_contactable"] == "99-102"
    assert totals[("GOUT-COH@2.0.0", "ALLIANCE")]["n"] == 50
    assert [r["site_id"] for r in out] == ["DEMO-A", "DEMO-B", "ALLIANCE", "DEMO-C", "ALLIANCE"]
    CohortTable.model_validate({"schema_version": "alliance-v1", "rows": out})


def _cassette_studies(cond: str) -> list[dict[str, Any]]:
    path = ROOT / "services/criteria_compiler/cassettes/ctgov" / f"{slug(cond)}.json"
    studies: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["studies"]
    return studies


def test_cassette_search_and_rank() -> None:
    res = CtGov(mode="cassette").search(CtgovSearchRequest(condition="Gout"))
    assert res.source == "cassette"
    assert [s.nct_id for s in res.studies] == ["NCT99000001", "NCT99000002", "NCT99000003"]
    ranked = trials.rank(res.studies, 3)
    # Taiwan sites first, then later phase: P3 (TW) > P2 (TW) > P4 (JP)
    assert [s.nct_id for s in ranked] == ["NCT99000001", "NCT99000002", "NCT99000003"]
    assert trials.rank(res.studies, 1)[0].nct_id == "NCT99000001"
    only_jp = CtGov(mode="cassette").search(CtgovSearchRequest(condition="Gout", locations=["Japan"]))
    assert {s.nct_id for s in only_jp.studies} == {"NCT99000001", "NCT99000003"}
    assert CtGov(mode="cassette").search(CtgovSearchRequest(condition="Psoriasis")).studies == []


def test_to_study_skips_unusable_records() -> None:
    raw = _cassette_studies("Rheumatoid Arthritis")[0]
    s = to_study(raw)
    assert s is not None and s.nct_id == "NCT99000004" and s.countries == ["Japan", "Taiwan"]
    assert s.eligibility_text.startswith("Inclusion Criteria:")
    no_text = json.loads(json.dumps(raw))
    no_text["protocolSection"]["eligibilityModule"].pop("eligibilityCriteria")
    assert to_study(no_text) is None
    month_only = json.loads(json.dumps(raw))
    month_only["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2026-09"
    assert to_study(month_only) is None


def test_live_search_paginates_and_maps_params() -> None:
    pages = _cassette_studies("Gout")
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        if "pageToken" not in params:
            return httpx.Response(200, json={"studies": pages[:2], "nextPageToken": "p2"})
        return httpx.Response(200, json={"studies": pages[2:]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = CtGov(mode="live", base_url="https://ctgov.test/api/v2", http=client).search(
        CtgovSearchRequest(condition="Gout")
    )
    assert res.source == "api" and len(res.studies) == 3
    assert seen[0]["query.cond"] == "Gout" and seen[0]["query.locn"] == "Taiwan OR Japan"
    assert seen[0]["filter.overallStatus"] == "RECRUITING" and seen[1]["pageToken"] == "p2"

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(CtgovError, match="HTTP 503"):
        CtGov(mode="live", http=httpx.Client(transport=httpx.MockTransport(down))).search(
            CtgovSearchRequest(condition="Gout")
        )


def test_cohort_schedule_rulesets(tmp_path: Path) -> None:
    """Quarterly COHORT runs settings.cohort.rulesets, else every approved cohort ruleset (D-75)."""
    import shutil
    from types import SimpleNamespace

    from orchestrator.scheduler import cohort_rulesets
    from tb_common.config import load_settings

    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    for rid in ("GOUT-COH", "RA-COH", "RA-BIO"):
        shutil.copytree(ROOT / "rulesets" / rid, tmp_path / rid)
    orch = SimpleNamespace(cfg=SimpleNamespace(settings=settings), rulesets_dir=tmp_path)
    assert cohort_rulesets(orch) == ["GOUT-COH", "RA-COH"]  # type: ignore[arg-type]
    orch.cfg.settings = settings.model_copy(update={"cohort": None})
    assert cohort_rulesets(orch) == ["GOUT-COH", "RA-COH"]  # type: ignore[arg-type]
