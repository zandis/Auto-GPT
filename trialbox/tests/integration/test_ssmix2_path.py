"""TB-PLAN-03 step 7 done-check (D-122): the same synthetic hospital read as SS-MIX2 standardized storage gives the
same GOUT-COH funnel as its CSV export, and every code resolves (no ``terminology_missed``)."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from orchestrator.scenarios.feas_compute import FeasParams, compute
from tb_common.ruleset import Ruleset

from tools.ssmix2_export import export

ROOT = Path(__file__).resolve().parents[2]
REF = date(2026, 11, 1)
SNAPSHOT = "2026-10-31"
MAPPINGS = {
    "csv": ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
    "ssmix2": ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml",
}


def _ingest(kind: str, path: Path, lake_dir: Path, secrets: Path) -> c.IngestReport:
    def rebuild(snap: str, nd: Path) -> c.RebuildResult:
        st = Lake(lake_dir).rebuild(snap, HashEmbedder(), nd)
        return c.RebuildResult(
            snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new, seconds=st.seconds
        )

    cfg = AdapterConfig(
        lake_dir=lake_dir,
        secrets_dir=secrets,
        mapping_path=MAPPINGS[kind],
        site_id="JP-A",
        audit_dir=lake_dir / "audit",
        rebuild=rebuild,
    )
    return run_ingest(cfg, kind, str(path), snapshot=SNAPSHOT, load_fhir=False, validate=False)


@pytest.fixture(scope="module")
def hospital(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    from tools.synth_hospital import run as synth_run

    out = tmp_path_factory.mktemp("synth")
    synth_run(out, profile="ci", sites="jp-a:JP:400", ref_date=REF)
    csv_dir = out / "jp-a"
    storage = tmp_path_factory.mktemp("ssmix2")
    export(csv_dir, storage)
    return {"csv": csv_dir, "ssmix2": storage}


def _codes(path: Path, column: str) -> set[str]:
    with path.open(encoding="utf-8") as fh:
        return {r[column] for r in csv.DictReader(fh) if r.get(column)}


def test_ssmix2_storage_gives_the_csv_funnel(hospital: dict[str, Path], site_key_dir: Path, tmp_path: Path) -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    params = FeasParams(run_date=REF, snapshot=SNAPSHOT, lookback_months=36)
    funnels: dict[str, Any] = {}
    for kind in ("csv", "ssmix2"):
        lake_dir = tmp_path / kind
        rep = _ingest(kind, hospital[kind], lake_dir, site_key_dir)
        assert rep.counts.get("Patient") == 400, rep.counts
        _, raw = compute(LakeLocal(lake_dir, HashEmbedder(), "Asia/Tokyo"), rs, params)
        funnels[kind] = (raw.start_n, raw.remaining)
    assert funnels["ssmix2"] == funnels["csv"]
    start, remaining = funnels["csv"]
    assert start == 400 and list(remaining.values())[2] > 0  # a real funnel, not two empty ones

    # no terminology_missed: every 標準病名 / YJ code resolved, every JLAC10 code has a LOINC row
    src = Ssmix2Source(hospital["ssmix2"])
    labs = {r["local_code"] for r in src.rows("lab", "lab", None, None)}
    for table in ("diagnosis", "medication"):
        assert all(r["icd10" if table == "diagnosis" else "atc"] for r in src.rows(table, table, None, None))
    assert not src.missed, src.missed
    jlac = _codes(ROOT / "services/adapter/mapping/jp_core/jlac10_to_loinc.csv", "local_code")
    assert labs and labs <= jlac, labs - jlac


def test_reader_versions_deletes_and_delta(tmp_path: Path) -> None:
    """Latest timestamp wins, flag 0 deletes, ISO-2022-JP and UTF-8 both decode, ``since`` filters the delta column."""
    root = tmp_path / "ss"

    def put(day: str, order: str, stamp: str, flag: str, value: str, when: str, enc: str = "iso2022_jp") -> None:
        d = storage_dir(root, "12345678", day, "OML-11")
        d.mkdir(parents=True, exist_ok=True)
        cs = "~ISO IR87" if enc == "iso2022_jp" else "UNICODE UTF-8"
        msg = "\r".join(
            [
                f"MSH|^~\\&|HIS||TB||20261101||OUL^R22|1|P|2.5||||||{cs}",
                f"OBR|1|{order}",
                f"OBX|1|NM|3C020000002327101^尿酸^JC10||{hl7.escape(value)}|mg/dL||||||||{when}" + "|" * 7 + order,
            ]
        )
        (d / f"12345678_{day}_OML-11_{order}_{stamp}_-_{flag}").write_bytes(msg.encode(enc))

    put("20260101", "L1", "20260101000000000", "1", "7.0", "20260101090000")
    put("20260101", "L1", "20260102000000000", "1", "7.5", "20260101090000")  # corrected result: newer wins
    put("20260201", "L2", "20260201000000000", "1", "8.1^x", "20260201090000", enc="utf-8")
    put("20260301", "L3", "20260301000000000", "1", "6.0", "20260301090000")
    put("20260301", "L3", "20260302000000000", "0", "6.0", "20260301090000")  # deleted
    src = Ssmix2Source(root)
    rows = {r["lab_no"]: r for r in src.rows("lab", "lab", None, None)}
    assert set(rows) == {"L1", "L2"}
    assert rows["L1"]["result_value"] == "7.5" and rows["L1"]["item_name"] == "尿酸"
    assert rows["L2"]["result_value"] == "8.1^x" and rows["L2"]["sample_datetime"] == "2026-02-01 09:00:00"
    delta = [r["lab_no"] for r in src.rows("lab", "lab", "sample_datetime", "2026-01-15")]
    assert delta == ["L2"]


def test_missing_storage_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ssmix2"):
        Ssmix2Source(tmp_path / "nope")
