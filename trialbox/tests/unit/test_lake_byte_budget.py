"""NEW-B-38 (D-679; deep review DATA-025): the lake keeps its snapshots within a byte budget.

The lake kept the last nightly snapshots and each month's last one for 36 months, by count only: at 50,000 dense
patients one snapshot is about 41 GB (NDJSON 0.55 MB, DuckDB 0.23 MB, Parquet 0.05 MB a patient), and 39 of them
about 1.6 TB against a 2 TB disk; nothing checked the free space before a night wrote its snapshot. Now a budget
(declared, or derived from the lake's disk) is kept after the count's pruning: a month-end snapshot's NDJSON goes
first (the lake still serves it), then whole month-end snapshots, the oldest first; the served snapshot, the
nightly ones and a snapshot a job holds never go; a budget that cannot be met is said; and a night with less free
space than the last snapshot took is refused before it reads."""

from __future__ import annotations

import json
import shutil
from collections import namedtuple
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import PASSED, AdapterConfig, prune_lake, prune_snapshots
from lake.store import Lake

TZ = "Asia/Taipei"
MB = 1024 * 1024
TODAY = date(2026, 10, 7)
NIGHTLY = ["2026-10-04", "2026-10-05", "2026-10-06"]
MONTH_ENDS = ["2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30"]  # oldest first


def _snap(lake_dir: Path, s: str, ndjson_mb: int = 4, db_mb: int = 2, passed: bool = True) -> None:
    nd = snapshot_dir(lake_dir, s)
    nd.mkdir(parents=True, exist_ok=True)
    if passed:
        (nd / PASSED).write_text(json.dumps({"snapshot": s}))
    (nd / "ingest_report.json").write_text(json.dumps({"snapshot": s}))  # the night's own report
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
def test_a_night_with_less_free_space_than_the_last_snapshot_took_is_refused(
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


# ------------------------------------------------------------------------------------------ the review's findings
def test_a_month_ends_ndjson_goes_and_its_folder_reports_and_mark_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The NDJSON files go, not the night's folder: its reports and its ``passed.json`` stay, the lake still lists
    it, and a late night never merges over a folder that holds no NDJSON."""
    from adapter.ndjson import list_snapshots
    from adapter.pipeline import NDJSON_REMOVED, merge_base

    cfg = _lake(tmp_path)
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "35")
    prune_lake(cfg, TODAY)
    for s in MONTH_ENDS[:2]:
        nd = snapshot_dir(cfg.lake_dir, s)
        assert not list(nd.glob("*.ndjson"))
        assert (nd / PASSED).exists() and (nd / "ingest_report.json").exists() and (nd / NDJSON_REMOVED).exists()
        assert s in list_snapshots(cfg.lake_dir)
    assert merge_base(cfg.lake_dir, "2026-08-01") is None  # 07-31 and 06-30 hold no NDJSON: nothing to merge over
    assert merge_base(cfg.lake_dir, "2026-09-01") == MONTH_ENDS[2]
    assert merge_base(cfg.lake_dir, "2026-10-07") == NIGHTLY[-1]


def test_a_file_with_two_names_is_counted_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    cfg = _lake(tmp_path)
    link = cfg.lake_dir / "db" / ".open" / "x"
    link.mkdir(parents=True)
    os.link(cfg.lake_dir / "db" / f"{NIGHTLY[-1]}.duckdb", link / f"{NIGHTLY[-1]}.duckdb")  # a reader's link
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "1000")
    assert prune_lake(cfg, TODAY).used_bytes < 7 * 6 * MB + 64 * 1024


def test_a_file_that_goes_while_it_is_counted_does_not_stop_the_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuild's spill file or a reader's link can go between the listing and its size."""
    cfg = _lake(tmp_path)
    spill = cfg.lake_dir / "tmp" / "spill.bin"
    spill.parent.mkdir()
    spill.write_bytes(b"s" * 10)
    import errno
    import os

    real = os.lstat

    def lstat(path: Any, *a: Any, **k: Any) -> Any:
        if str(path).endswith("spill.bin"):
            raise FileNotFoundError(errno.ENOENT, "gone", str(path))
        return real(path, *a, **k)

    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "35")
    assert prune_lake(cfg, TODAY).ndjson_dropped == MONTH_ENDS[:2]


def test_a_pruning_that_fails_does_not_fail_a_night_already_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import pipeline
    from adapter.pipeline import run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _Lakes, _row

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "full", [_row("D1", "2026-09-01")])

    def broken(cfg: AdapterConfig, today: date) -> Any:
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(pipeline, "prune_lake", broken)
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed, rep.errors
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == "2026-10-01"
    audit = [json.loads(x) for f in (tmp_path / "audit").glob("*.jsonl") for x in f.read_text().splitlines()]
    done = [e for e in audit if e["event"] == "ingest.done"]
    assert done and done[-1]["detail"]["lake_budget"] == {"error": "RuntimeError"}
    assert not any(e["event"] == "ingest.failed" for e in audit)


def test_a_budget_setting_that_is_not_a_number_refuses_the_night_before_it_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.pipeline import LakeBudgetError, run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _row

    cfg = _cfg(tmp_path)
    _csv(tmp_path / "full", [_row("D1", "2026-09-01")])
    monkeypatch.setenv("TB_LAKE_BUDGET_MB", "lots")
    with pytest.raises(LakeBudgetError, match="TB_LAKE_BUDGET_MB"):
        run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, rebuild_lake=False,
                   validate=False)  # fmt: skip
    assert not snapshot_dir(cfg.lake_dir, "2026-10-01").exists()


def test_the_room_is_measured_by_the_newest_night_that_passed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A held night's partial folder is not what tonight needs; the numbers are said, one decimal."""
    from adapter.pipeline import NoRoomForNight, check_room

    cfg = _lake(tmp_path)
    _snap(cfg.lake_dir, "2026-10-07", ndjson_mb=1, db_mb=0, passed=False)  # held: no passed.json, no DuckDB
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100 * MB, 97 * MB, 3 * MB))
    with pytest.raises(NoRoomForNight, match=r"about 6\.0 MB needed \(snapshot 2026-10-06 took that\), 3\.0 MB free"):
        check_room(cfg, "2026-10-08")


def test_a_refused_night_keeps_its_numbers_in_the_run_record_and_the_command_says_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from adapter import cli, failure
    from adapter.pipeline import NoRoomForNight

    exc = NoRoomForNight("not enough free disk for tonight's snapshot: about 6.0 MB needed, 3.0 MB free")
    assert "6.0 MB needed" in failure.words(exc)
    cfg = _lake(tmp_path)
    monkeypatch.setattr(cli, "build_config", lambda: (cfg, "csv", str(tmp_path)))

    def refuse(*a: Any, **k: Any) -> Any:
        raise exc

    monkeypatch.setattr(cli, "run_ingest", refuse)
    assert cli.main(["run"]) == 2
    assert "night refused" in capsys.readouterr().err
