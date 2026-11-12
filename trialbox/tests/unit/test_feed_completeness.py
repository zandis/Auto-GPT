"""T-611 (DATA-001, DATA-009, DATA-017): the completeness gate before a night is published.

The four bad feeds of the deep review's trace (TB-DR-06 §2: ``lab.csv`` missing, ``patient.csv`` header only,
``medication.csv`` missing, an empty export) are held: ``CURRENT`` stays, the lake is not rebuilt (so OMOP writes no
tombstone), nothing is pruned. A 15 % drop of one table holds. One fault-injection test per table of the site
mapping. A patient row that leaves the feed while their records stay holds; duplicate source keys are counted.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import COMPLETENESS, HELD, PASSED, AdapterConfig, prune_snapshots, run_ingest
from embed_service.embedder import HashEmbedder
from lake.store import Lake
from sitesetup.readiness import feed_held, last_feed_night, newest_batch
from tb_common.retention import snapshots_to_keep
from tb_contracts import RebuildResult

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
TABLES = ("patient", "practitioner", "encounter", "appointment", "diagnosis", "lab", "vital", "medication",
          "procedure", "report", "note", "claim", "registry")  # fmt: skip
GOOD = "2026-11-01"
BAD = "2026-11-02"


class _Rebuild:
    """The adapter's lake hook: a real lake (``real``) or a stand-in that only moves ``CURRENT``."""

    def __init__(self, lake_dir: Path, real: bool = False) -> None:
        self.lake_dir, self.real = lake_dir, real
        self.calls: list[str] = []

    def __call__(self, snap: str, nd: Path) -> RebuildResult:
        self.calls.append(snap)
        if self.real:
            st = Lake(self.lake_dir).rebuild(snap, HashEmbedder(), nd)
            return RebuildResult(snapshot=st.snapshot, tables=st.tables, chunks=st.chunks,
                                 embedded_new=st.embedded_new, seconds=st.seconds)  # fmt: skip
        (self.lake_dir / "db").mkdir(parents=True, exist_ok=True)
        (self.lake_dir / "db" / f"{snap}.duckdb").write_bytes(b"")
        (self.lake_dir / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)


def _cfg(tmp: Path, rebuild: _Rebuild | None = None, **kw: Any) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
                         audit_dir=tmp / "audit", rebuild=rebuild, **kw)  # fmt: skip


def _night(cfg: AdapterConfig, feed: Path, snap: str, since: str | None = None) -> Any:
    return run_ingest(cfg, "csv", str(feed), snapshot=snap, since=since, load_fhir=False, validate=False)


def _feed(tmp: Path, name: str = "feed") -> Path:
    dst = tmp / name
    shutil.copytree(SITE_A, dst, ignore=shutil.ignore_patterns("*.json"))
    return dst


def _rewrite(path: Path, keep: Any) -> None:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(keep(rows))


@pytest.fixture(scope="module")
def good_lake(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> Path:
    """One good night of the synthetic site A (600 patients), promoted; copied by each test (which has its own
    ``TB_DB_URL`` for the pid map)."""
    tmp = tmp_path_factory.mktemp("good")
    sep = "&" if "?" in pg_cluster_url else "?"
    cfg = _cfg(tmp, _Rebuild(tmp / "lake"), db_url=f"{pg_cluster_url}{sep}tb_prefix=feedgate{os.getpid()}_")
    rep = _night(cfg, _feed(tmp), GOOD)
    assert rep.passed and not rep.held
    return tmp


def _from_good(good: Path, tmp: Path, real: bool = False, **kw: Any) -> tuple[AdapterConfig, _Rebuild]:
    shutil.copytree(good / "lake", tmp / "lake")
    rb = _Rebuild(tmp / "lake", real)
    return _cfg(tmp, rb, **kw), rb


def _audit(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


def _assert_held(cfg: AdapterConfig, rb: _Rebuild, rep: Any, *needles: str) -> None:
    assert rep.held and not rep.passed
    assert rb.calls == []  # the lake (and through it OMOP) never sees the night: no rebuild, no tombstone
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD
    assert (snapshot_dir(cfg.lake_dir, GOOD) / PASSED).exists()  # nothing pruned
    assert (snapshot_dir(cfg.lake_dir, BAD) / HELD).exists()
    text = " ".join(rep.errors)
    for n in needles:
        assert n in text, text


# ------------------------------------------------------------------------- the four bad feeds of the trace
def test_the_four_bad_feeds_of_the_trace_are_held(good_lake: Path, tmp_path: Path) -> None:
    def drop(*names: str) -> Callable[[Path], None]:
        def go(f: Path) -> None:
            for p in f.glob("*.csv"):
                if not names or p.stem in names:
                    p.unlink()

        return go

    def header_only(f: Path) -> None:
        _rewrite(f / "patient.csv", lambda rows: [])

    variants: dict[str, Callable[[Path], None]] = {
        "lab.csv missing": drop("lab"),
        "patient.csv header only": header_only,
        "medication.csv missing": drop("medication"),
        "empty export": drop(),
    }
    needles = {
        "lab.csv missing": "lab: table missing",
        "patient.csv header only": "patient: table empty",
        "medication.csv missing": "medication: table missing",
        "empty export": "encounter: table missing",
    }
    for i, (name, broke) in enumerate(variants.items()):
        tmp = tmp_path / str(i)
        cfg, rb = _from_good(good_lake, tmp)
        feed = _feed(tmp)
        broke(feed)
        rep = _night(cfg, feed, BAD)
        _assert_held(cfg, rb, rep, needles[name])
        ev = _audit(tmp)[-1]
        assert ev["event"] == "ingest.held" and any(needles[name] in p for p in ev["detail"]["incomplete"])


def test_a_held_night_on_a_real_lake_keeps_current_and_its_rows(good_lake: Path, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _Rebuild(tmp_path / "lake", real=True))
    assert _night(cfg, _feed(tmp_path), GOOD).passed  # a real lake for the good night
    lake = Lake(cfg.lake_dir)
    labs = lake.query("SELECT count(*) AS n FROM observation").to_pylist()[0]["n"]
    feed = _feed(tmp_path, "bad")
    (feed / "lab.csv").unlink()
    rep = _night(cfg, feed, BAD)
    assert rep.held and (cfg.lake_dir / "CURRENT").read_text().strip() == GOOD
    assert Lake(cfg.lake_dir).query("SELECT count(*) AS n FROM observation").to_pylist()[0]["n"] == labs


# ------------------------------------------------------------------------- one fault per table
@pytest.mark.parametrize("table", TABLES)
def test_a_missing_table_holds_the_night(table: str, good_lake: Path, tmp_path: Path) -> None:
    cfg, rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    (feed / f"{table}.csv").unlink()
    _assert_held(cfg, rb, _night(cfg, feed, BAD), f"{table}: table missing")


@pytest.mark.parametrize("table", ("patient", "lab", "medication", "procedure"))
def test_an_emptied_table_holds_the_night(table: str, good_lake: Path, tmp_path: Path) -> None:
    cfg, rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    _rewrite(feed / f"{table}.csv", lambda rows: [])
    _assert_held(cfg, rb, _night(cfg, feed, BAD), f"{table}: table empty")


def test_a_15_pct_drop_holds_and_a_small_one_passes(good_lake: Path, tmp_path: Path) -> None:
    cfg, rb = _from_good(good_lake, tmp_path / "a")
    feed = _feed(tmp_path / "a")
    _rewrite(feed / "lab.csv", lambda rows: rows[: int(len(rows) * 0.85)])
    _assert_held(cfg, rb, _night(cfg, feed, BAD), "lab: ", "% fewer than the last good night's", "limit 10 %")
    comp = json.loads((snapshot_dir(cfg.lake_dir, BAD) / COMPLETENESS).read_text())
    assert comp["tables"]["lab"]["rows_before"] > comp["tables"]["lab"]["rows"] > 0
    # 2 % fewer lab rows is an ordinary night
    cfg, rb = _from_good(good_lake, tmp_path / "b")
    feed = _feed(tmp_path / "b")
    _rewrite(feed / "lab.csv", lambda rows: rows[: int(len(rows) * 0.98)])
    rep = _night(cfg, feed, BAD)
    assert rep.passed and rb.calls == [BAD]


def test_the_band_is_a_site_setting(good_lake: Path, tmp_path: Path) -> None:
    cfg, _rb = _from_good(good_lake, tmp_path, table_max_drop_pct=20.0)
    feed = _feed(tmp_path)
    _rewrite(feed / "diagnosis.csv", lambda rows: rows[: int(len(rows) * 0.85)])
    assert _night(cfg, feed, BAD).passed


def test_an_optional_table_may_go_missing(good_lake: Path, tmp_path: Path) -> None:
    # (a table whose loss removes every record of a resource type is still held by D-271's guard)
    cfg, _rb = _from_good(good_lake, tmp_path, optional_tables=("practitioner",))
    feed = _feed(tmp_path)
    (feed / "practitioner.csv").unlink()
    assert _night(cfg, feed, BAD).passed


def test_a_required_table_is_checked_on_the_first_night(tmp_path: Path) -> None:
    rb = _Rebuild(tmp_path / "lake")
    cfg = _cfg(tmp_path, rb, required_tables=("patient", "lab"))
    feed = _feed(tmp_path)
    (feed / "lab.csv").unlink()
    rep = _night(cfg, feed, GOOD)
    assert rep.held and rb.calls == [] and "lab: required table missing" in " ".join(rep.errors)
    assert not (tmp_path / "lake" / "CURRENT").exists()


def test_the_override_naming_the_night_lets_it_through_and_is_audited(
    good_lake: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    (feed / "procedure.csv").unlink()
    monkeypatch.setenv("TB_FEED_DROP_OVERRIDE", f"{BAD}: the hospital stopped the procedure export (ticket 7)")
    rep = _night(cfg, feed, BAD)
    assert rep.passed and rb.calls == [BAD]
    assert "ticket 7" in _audit(tmp_path)[-1]["detail"]["drop_override"]


def test_a_delta_night_missing_a_table_file_is_held(good_lake: Path, tmp_path: Path) -> None:
    cfg, rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    (feed / "diagnosis.csv").unlink()
    _assert_held(cfg, rb, _night(cfg, feed, BAD, since="2026-10-31"), "diagnosis: table missing")


# ------------------------------------------------------------------------- DATA-009 and DATA-017
def test_a_patient_row_that_leaves_the_feed_with_records_behind_is_held(good_lake: Path, tmp_path: Path) -> None:
    cfg, rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    _rewrite(feed / "patient.csv", lambda rows: rows[1:])
    rep = _night(cfg, feed, BAD)
    _assert_held(cfg, rb, rep, "1 patients of the last good night left the feed", "(orphans)")
    comp = json.loads((snapshot_dir(cfg.lake_dir, BAD) / COMPLETENESS).read_text())
    assert comp["patients_vanished"] == 1 and comp["orphans_of_vanished"] > 0


def test_duplicate_source_keys_are_counted(good_lake: Path, tmp_path: Path) -> None:
    cfg, _rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    _rewrite(feed / "lab.csv", lambda rows: [*rows, rows[0]])
    rep = _night(cfg, feed, BAD)
    assert rep.passed
    comp = json.loads((snapshot_dir(cfg.lake_dir, BAD) / COMPLETENESS).read_text())
    assert comp["tables"]["lab"]["duplicate_keys"] == 1
    assert _audit(tmp_path)[-1]["detail"]["duplicate_keys"] == {"lab": 1}


# ------------------------------------------------------------------------- retention
def test_held_nights_never_push_a_good_snapshot_out() -> None:
    snaps = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"]
    good = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-07"]
    keep = snapshots_to_keep(snaps, date(2026, 11, 7), 3, 0, good)
    assert keep == {"2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"}
    assert snapshots_to_keep(snaps, date(2026, 11, 7), 3, 0) == {"2026-11-05", "2026-11-06", "2026-11-07"}


def test_prune_after_three_held_nights_keeps_the_good_ones(good_lake: Path, tmp_path: Path) -> None:
    cfg, _rb = _from_good(good_lake, tmp_path)
    for snap in ("2026-11-02", "2026-11-03"):
        assert _night(cfg, _feed(tmp_path, snap), snap).passed
    for snap in ("2026-11-04", "2026-11-05", "2026-11-06"):
        feed = _feed(tmp_path, snap)
        (feed / "lab.csv").unlink()
        assert _night(cfg, feed, snap).held
    assert _night(cfg, _feed(tmp_path, "g"), "2026-11-07").passed
    left = sorted(p.name for p in (cfg.lake_dir / "ndjson").iterdir() if p.is_dir())
    assert "2026-11-02" in left and "2026-11-03" in left and "2026-11-07" in left
    assert prune_snapshots(cfg, date(2026, 11, 7)) == []


# ------------------------------------------------------------------------- readiness
def test_the_readiness_page_names_the_held_tables(good_lake: Path, tmp_path: Path) -> None:
    cfg, _rb = _from_good(good_lake, tmp_path)
    feed = _feed(tmp_path)
    (feed / "lab.csv").unlink()
    _night(cfg, feed, BAD)

    class _Svc:
        class audit:  # noqa: N801 - the SiteSetup attribute it stands for
            directory = tmp_path / "audit"

    rec = last_feed_night(tmp_path / "audit")
    assert rec is not None and rec["event"] == "ingest.held"
    item = feed_held(_Svc())  # type: ignore[arg-type]
    assert item is not None and item["key"] == "patients.feed_held" and "lab" in item["tables"]
    assert item["snapshot"] == BAD and item["link"] == "/data-ops"  # T-112b (D-443): the steward's console
    # T-112b (D-443, TB-ASSESS-01 T-112 acceptance 5): the light read from dataops says the same as the audit chain
    night = newest_batch()
    assert night is not None and night.state == "HELD" and night.snapshot == BAD
    assert feed_held(_Svc(), night) == item  # type: ignore[arg-type]
    assert _night(cfg, _feed(tmp_path, "next"), "2026-11-03").passed
    assert feed_held(_Svc()) is None  # type: ignore[arg-type]
    night = newest_batch()
    assert night is not None and night.state == "PUBLISHED" and feed_held(_Svc(), night) is None  # type: ignore[arg-type]
