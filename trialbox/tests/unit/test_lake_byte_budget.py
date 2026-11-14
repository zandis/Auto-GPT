"""NEW-B-38 (D-679; deep review DATA-025): the lake keeps its snapshots within a byte budget.

The lake kept the last nightly snapshots and each month's last one for 36 months, by count only: at 50,000 dense
patients one snapshot is about 41 GB (NDJSON 0.55 MB, DuckDB 0.23 MB, Parquet 0.05 MB a patient), and 39 of them
about 1.6 TB against a 2 TB disk; nothing checked the free space before a night wrote its snapshot. Now a budget
(declared, or derived from the lake's disk) is kept after the count's pruning: a month-end snapshot's NDJSON goes
first (the lake still serves it), then whole month-end snapshots, the oldest first; the served snapshot, the
nightly ones and a snapshot a job holds never go; a budget that cannot be met is said; and a night with less free
space than the last snapshot took is held before it writes."""

from __future__ import annotations

import json
import shutil
from collections import namedtuple
from datetime import date
from pathlib import Path

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import PASSED, AdapterConfig, prune_lake, prune_snapshots
from lake.store import Lake

TZ = "Asia/Taipei"
MB = 1024 * 1024
TODAY = date(2026, 10, 7)
NIGHTLY = ["2026-10-04", "2026-10-05", "2026-10-06"]
MONTH_ENDS = ["2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30"]  # oldest first


def _snap(lake_dir: Path, s: str, ndjson_mb: int = 4, db_mb: int = 2) -> None:
    nd = snapshot_dir(lake_dir, s)
    nd.mkdir(parents=True, exist_ok=True)
    (nd / PASSED).write_text(json.dumps({"snapshot": s}))
    (nd / "Patient.ndjson").write_bytes(b"x" * ndjson_mb * MB)
    (lake_dir / "db").mkdir(exist_ok=True)
    (lake_dir / "db" / f"{s}.duckdb").write_bytes(b"d" * db_mb * MB)


def _lake(tmp_path: Path) -> AdapterConfig:
    lake_dir = tmp_path / "lake"
    for s in [*MONTH_ENDS, *NIGHTLY]:
        _snap(lake_dir, s)
    (lake_dir / "CURRENT").write_text(NIGHTLY[-1])
    return AdapterConfig(lake_dir=lake_dir, secrets_dir=tmp_path, mapping_path=tmp_path, site_id="T", keep_nightly=3,
                         keep_month_end_months=36)  # fmt: skip


def _has(cfg: AdapterConfig, s: str) -> tuple[bool, bool]:
    return snapshot_dir(cfg.lake_dir, s).exists(), (cfg.lake_dir / "db" / f"{s}.duckdb").exists()


def test_within_the_budget_the_count_alone_decides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _lake(tmp_path)
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "1000")
    res = prune_lake(cfg, TODAY)
    assert res.gone == [] and res.ndjson_dropped == [] and not res.unmet
    assert 7 * 6 * MB <= res.used_bytes < 7 * 6 * MB + 64 * 1024 and res.budget_bytes == 1000 * MB  # with the markers


def test_over_the_budget_month_end_ndjson_goes_first_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _lake(tmp_path)  # 42 MB: 7 snapshots of 4 MB NDJSON and 2 MB DuckDB
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "35")  # two month-end NDJSON folders (8 MB) bring it to 34
    res = prune_lake(cfg, TODAY)
    assert res.ndjson_dropped == MONTH_ENDS[:2] and res.gone == [] and not res.unmet
    for s in MONTH_ENDS[:2]:
        assert not (snapshot_dir(cfg.lake_dir, s) / "Patient.ndjson").exists()
        assert (cfg.lake_dir / "db" / f"{s}.duckdb").exists()  # the lake still serves it
    for s in [*MONTH_ENDS[2:], *NIGHTLY]:
        assert (snapshot_dir(cfg.lake_dir, s) / "Patient.ndjson").exists()
    assert res.used_bytes <= res.budget_bytes


def test_then_whole_month_end_snapshots_go_oldest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _lake(tmp_path)
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "21")  # every month-end NDJSON (16 MB) leaves 26; two whole ones 22, 20
    res = prune_lake(cfg, TODAY)
    assert res.ndjson_dropped == MONTH_ENDS
    assert res.gone == MONTH_ENDS[:3] and not res.unmet
    assert _has(cfg, MONTH_ENDS[0]) == (False, False) and _has(cfg, MONTH_ENDS[3])[1]
    assert all(_has(cfg, s) == (True, True) for s in NIGHTLY)


def test_a_budget_that_cannot_be_met_keeps_what_must_stay_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = _lake(tmp_path)
    Lake(cfg.lake_dir, TZ).hold(NIGHTLY[0], "01LONG")  # a job still reads the oldest nightly
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "5")
    res = prune_lake(cfg, TODAY)
    assert res.gone == MONTH_ENDS and res.unmet
    assert all(_has(cfg, s) == (True, True) for s in NIGHTLY)
    assert "the lake's byte budget cannot be met" in caplog.text
    assert "18 MB used, 5 MB budget" in res.said


def test_a_held_month_end_snapshot_is_never_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _lake(tmp_path)
    Lake(cfg.lake_dir, TZ).hold(MONTH_ENDS[0], "01FEAS")  # a feasibility job reads the oldest month-end
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "1")
    res = prune_lake(cfg, TODAY)
    assert MONTH_ENDS[0] not in res.gone and MONTH_ENDS[0] not in res.ndjson_dropped
    assert _has(cfg, MONTH_ENDS[0]) == (True, True) and res.unmet


def test_prune_snapshots_still_answers_the_snapshots_gone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _lake(tmp_path)
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "21")
    assert prune_snapshots(cfg, TODAY) == MONTH_ENDS[:3]


def test_unset_the_budget_is_derived_from_the_lakes_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter import pipeline

    cfg = _lake(tmp_path)
    monkeypatch.delenv("TB_LAKE_BUDGET_MB", raising=False)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100 * MB, 50 * MB, 50 * MB))
    res = prune_lake(cfg, TODAY)
    assert res.budget_bytes == int(100 * MB * pipeline.LAKE_DISK_SHARE)


@pytest.mark.parametrize("raw", ["0", "-3", "lots"])
def test_a_budget_that_is_not_a_whole_number_of_megabytes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    cfg = _lake(tmp_path)
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", raw)
    with pytest.raises(ValueError, match="TB_LAKE_BUDGET_MB"):
        prune_lake(cfg, TODAY)


# ------------------------------------------------------------------------------------- the free space before a night
def test_a_night_with_less_free_space_than_the_last_snapshot_took_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.pipeline import run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _row

    cfg = _cfg(tmp_path)
    _csv(tmp_path / "full", [_row("D1", "2026-09-01")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, rebuild_lake=False,
                     validate=False)  # fmt: skip
    assert rep.passed, rep.errors
    usage = namedtuple("usage", "total used free")
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(real(p).total, real(p).used, 1))
    from adapter.pipeline import NoRoomForNight

    with pytest.raises(NoRoomForNight, match="not enough free disk for tonight's snapshot"):
        run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-02", load_fhir=False, rebuild_lake=False,
                   validate=False)  # fmt: skip
    assert not snapshot_dir(cfg.lake_dir, "2026-10-02").exists()  # nothing read or written
    audit = [json.loads(x) for f in (tmp_path / "audit").glob("*.jsonl") for x in f.read_text().splitlines()]
    assert any(e["event"] == "ingest.failed" and e["detail"].get("refused") == "disk" for e in audit)
