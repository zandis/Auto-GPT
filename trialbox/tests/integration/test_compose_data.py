"""Phase 1 DoD against the running compose stack (`make fixtures up-test`; TB_INTEGRATION=1)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tb_common.crypto import pid_for_mrn

from tests.stack import ensure_ingested, url

pytestmark = pytest.mark.integration
ADAPTER, LAKE, FHIR = url("ADAPTER"), url("LAKE"), url("FHIR", "/fhir")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_patients" / "site-a"


@pytest.fixture(scope="module")
def ingest_report() -> dict[str, object]:
    body = ensure_ingested(force=True)  # this module checks the ingest itself, so always run it
    assert body is not None
    return body


def test_adapter_run_passes(ingest_report: dict[str, object]) -> None:
    assert ingest_report["passed"], ingest_report.get("errors")
    counts = ingest_report["counts"]
    assert isinstance(counts, dict) and counts["Patient"] >= 500
    val = ingest_report["validation"]
    assert isinstance(val, dict) and val["validator"] == "hl7-validator" and val["errors"] == 0
    # NEW-B-57: the FHIR load is a delta against what the store already holds (T-725, D-491: PUT what is new or
    # changed, DELETE what the night no longer has). The fixture re-runs a night this stack may hold already, so
    # this run loads anything from none (the same night again) to every resource (a fresh stack); either way the
    # store then holds every resource of the night
    loaded, total = ingest_report["fhir_loaded"], sum(counts.values())
    assert isinstance(loaded, int) and 0 <= loaded <= total, (loaded, total)
    for rtype, n in counts.items():
        held = httpx.get(f"{FHIR}/{rtype}", params={"_summary": "count"}, timeout=60).json()["total"]
        assert held >= n, (rtype, held, n)  # at least: other modules of this stack may add to the store


def test_fhir_store_has_patients(ingest_report: dict[str, object]) -> None:
    total = httpx.get(f"{FHIR}/Patient", params={"_summary": "count"}, timeout=60).json()["total"]
    assert total >= 500


def test_lake_http_query_arrow(ingest_report: dict[str, object]) -> None:
    import pyarrow as pa

    resp = httpx.post(f"{LAKE}/query", json={"sql": "SELECT count(*) AS n FROM patient"}, timeout=60)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/vnd.apache.arrow")
    assert pa.ipc.open_stream(resp.content).read_all().to_pylist()[0]["n"] >= 500
    bad = httpx.post(f"{LAKE}/query", json={"sql": "DELETE FROM patient"}, timeout=60)
    assert bad.status_code == 400


def test_lake_http_seeded_queries(ingest_report: dict[str, object]) -> None:
    key = (Path(__file__).resolve().parents[2] / ".cache" / "test-secrets" / "site_hmac.key").read_bytes()
    needles = json.loads((FIXTURES / "needles.json").read_text(encoding="utf-8"))
    for n in needles:
        hits = httpx.post(
            f"{LAKE}/chunks/search",
            json={"pid": pid_for_mrn(key, n["mrn"]), "query": n["query"], "k": 5},
            timeout=60,
        ).json()["hits"]
        assert hits and n["fragment"] in hits[0]["text"], n["query"]
