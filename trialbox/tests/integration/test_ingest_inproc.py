"""Phase 1 DoD (in-process): 500+ synthetic patients ingested, validator sample clean, 20 seeded queries hit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_all
from adapter.pidmap import PidMap
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.validate.validator import Hl7Validator, sample
from embed_service.embedder import HashEmbedder
from lake.store import Lake
from tb_common.audit import verify
from tb_common.crypto import pid_for_mrn

SNAPSHOT = "2026-10-04"


def _digest(directory: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(directory.glob("*.ndjson")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def test_ingest_report(ingested: dict[str, Any]) -> None:
    rep = ingested["report"]
    assert rep.passed, rep.errors
    assert rep.counts["Patient"] >= 500
    assert rep.missing_required == {}
    assert rep.validation.sampled >= 100 and rep.validation.errors == 0
    assert rep.lake is not None and rep.lake.chunks > rep.lake.tables["document"]
    assert verify(ingested["lake_dir"] / "audit").ok


def test_no_direct_identifiers_leave_the_adapter(ingested: dict[str, Any], synth_dir: Path) -> None:
    nd = ingested["lake_dir"] / "ndjson" / SNAPSHOT
    blob = "".join(f.read_text(encoding="utf-8") for f in nd.glob("*.ndjson"))
    import csv

    patients = list(csv.DictReader((synth_dir / "site-a" / "patient.csv").open(encoding="utf-8")))
    for p in patients[:200]:
        assert p["mrn"] not in blob
        assert p["id_no"] not in blob
        assert p["name"] not in blob
        assert p["phone"] not in blob


def test_pidmap_resolves_internal_only(ingested: dict[str, Any], site_key_dir: Path) -> None:
    pm = PidMap(site_key_dir / "pid_map.sqlite", site_key_dir / "pid_map.key")
    pid = pid_for_mrn(ingested["key"], "10000001")
    assert pm.resolve(pid) == "10000001"
    raw = (site_key_dir / "pid_map.sqlite").read_bytes()
    assert b"10000001" not in raw  # encrypted at rest
    pm.close()


def test_csv_and_sqlite_sources_produce_identical_snapshots(
    synth_dir: Path, site_key_dir: Path, tmp_path: Path, repo_root: Path
) -> None:
    out = {}
    for kind, path in (
        ("csv", str(synth_dir / "site-a")),
        ("cgrd_sql", f"sqlite:///{synth_dir}/site-a/cgrd.sqlite"),
    ):
        lake_dir = tmp_path / kind
        cfg = AdapterConfig(
            lake_dir=lake_dir,
            secrets_dir=site_key_dir,
            mapping_path=repo_root / "services/adapter/mapping/tw_core/demo_his.yaml",
            site_id="DEMO-A",
        )
        rep = run_ingest(cfg, kind, path, snapshot=SNAPSHOT, load_fhir=False, rebuild_lake=False, validate=False)
        assert rep.passed, rep.errors
        out[kind] = _digest(lake_dir / "ndjson" / SNAPSHOT)
    assert out["csv"] == out["cgrd_sql"]


def test_rerun_is_reproducible(
    ingested: dict[str, Any], synth_dir: Path, site_key_dir: Path, tmp_path: Path, repo_root: Path
) -> None:
    cfg = AdapterConfig(
        lake_dir=tmp_path,
        secrets_dir=site_key_dir,
        mapping_path=repo_root / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id="DEMO-A",
    )
    run_ingest(
        cfg,
        "csv",
        str(synth_dir / "site-a"),
        snapshot=SNAPSHOT,
        load_fhir=False,
        rebuild_lake=False,
        validate=False,
    )
    assert _digest(tmp_path / "ndjson" / SNAPSHOT) == _digest(ingested["lake_dir"] / "ndjson" / SNAPSHOT)


def test_delta_run_merges_over_previous_snapshot(
    synth_dir: Path, site_key_dir: Path, tmp_path: Path, repo_root: Path
) -> None:
    cfg = AdapterConfig(
        lake_dir=tmp_path,
        secrets_dir=site_key_dir,
        mapping_path=repo_root / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id="DEMO-A",
    )
    full = run_ingest(
        cfg,
        "csv",
        str(synth_dir / "site-a"),
        snapshot="2026-10-03",
        load_fhir=False,
        rebuild_lake=False,
        validate=False,
    )
    delta = run_ingest(
        cfg,
        "csv",
        str(synth_dir / "site-a"),
        snapshot=SNAPSHOT,
        since="2026-09-01",
        load_fhir=False,
        rebuild_lake=False,
        validate=False,
    )
    assert delta.counts == full.counts  # merged snapshot is complete again


def test_seeded_queries_return_the_planted_chunk(ingested: dict[str, Any], synth_dir: Path) -> None:
    lake = Lake(ingested["lake_dir"])
    needles = json.loads((synth_dir / "site-a" / "needles.json").read_text(encoding="utf-8"))
    assert len(needles) == 20
    for n in needles:
        hits = lake.search(pid_for_mrn(ingested["key"], n["mrn"]), n["query"], HashEmbedder(), k=5)
        assert hits and n["fragment"] in hits[0]["text"], n["query"]


def test_search_is_restricted_to_patient_and_window(ingested: dict[str, Any], synth_dir: Path) -> None:
    from datetime import date

    lake = Lake(ingested["lake_dir"])
    n = json.loads((synth_dir / "site-a" / "needles.json").read_text(encoding="utf-8"))[0]
    other_pid = pid_for_mrn(ingested["key"], "19999999")
    assert lake.search(other_pid, n["query"], HashEmbedder()) == []
    hits = lake.search(
        pid_for_mrn(ingested["key"], n["mrn"]), n["query"], HashEmbedder(), k=50, date_from=date(2030, 1, 1)
    )
    assert hits == []


def test_lake_query_and_guard(ingested: dict[str, Any]) -> None:
    from lake.sqlguard import SqlRejected

    lake = Lake(ingested["lake_dir"])
    t = lake.query("SELECT count(*) AS n FROM patient")
    assert t.to_pylist()[0]["n"] >= 500
    t = lake.query("SELECT count(*) AS n FROM observation WHERE code = ? AND value_num IS NOT NULL", ["8480-6"])
    assert t.to_pylist()[0]["n"] > 0
    with pytest.raises(SqlRejected):
        lake.query("DROP TABLE patient")


@pytest.mark.skipif(Hl7Validator.from_env() is None, reason="HL7 validator jar/package cache not configured")
def test_hl7_validator_sample_zero_errors(ingested: dict[str, Any]) -> None:
    v = Hl7Validator.from_env()
    assert v is not None
    resources = [r for items in read_all(ingested["lake_dir"] / "ndjson" / SNAPSHOT).values() for r in items]
    res = v.validate(sample(resources, 0.01))
    assert res.sampled >= 100
    assert res.errors == 0, res.messages[:10]


def test_ssmix2_is_explicitly_unsupported(site_key_dir: Path, tmp_path: Path, repo_root: Path) -> None:
    cfg = AdapterConfig(
        lake_dir=tmp_path,
        secrets_dir=site_key_dir,
        mapping_path=repo_root / "services/adapter/mapping/tw_core/demo_his.yaml",
        site_id="X",
    )
    with pytest.raises(NotImplementedError, match="v1.1"):
        run_ingest(cfg, "ssmix2", str(tmp_path), snapshot=SNAPSHOT, load_fhir=False, rebuild_lake=False)


_ = os
