"""Phase 1 DoD against the running compose stack (`make fixtures up-test`; TB_INTEGRATION=1)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tb_common.crypto import pid_for_mrn

pytestmark = pytest.mark.integration
ADAPTER = "http://127.0.0.1:8016"
LAKE = "http://127.0.0.1:8013"
FHIR = "http://127.0.0.1:8080/fhir"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_patients" / "site-a"


@pytest.fixture(scope="module")
def ingest_report() -> dict[str, object]:
    resp = httpx.post(f"{ADAPTER}/run", json={"source": "csv", "snapshot": "2026-10-04"}, timeout=1800)
    assert resp.status_code == 200, resp.text[:1000]
    body: dict[str, object] = resp.json()
    return body


def test_adapter_run_passes(ingest_report: dict[str, object]) -> None:
    assert ingest_report["passed"], ingest_report.get("errors")
    counts = ingest_report["counts"]
    assert isinstance(counts, dict) and counts["Patient"] >= 500
    val = ingest_report["validation"]
    assert isinstance(val, dict) and val["validator"] == "hl7-validator" and val["errors"] == 0
    assert ingest_report["fhir_loaded"] == sum(counts.values())


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
