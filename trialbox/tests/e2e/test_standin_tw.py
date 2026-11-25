"""M6-TW: the Taiwan SQL-view door end to end on a seeded stand-in (tools/standin_tw.py): a full night, a delta
night, a failed night, the night report, a read-only account. Synthetic data; fixed clocks (nights are given dates)."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.sources.cgrd_sql.source import SqlSource
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tools import standin_tw

KEY = bytes(range(32))
FULL, DELTA, REDO = "2026-10-05", "2026-10-06", "2026-10-07"
EDITED = "2026-10-05 03:00:00"  # the hospital's edits, after the full night's read of 2026-10-05 00:00
TYPES = {"patient": "Patient", "diagnosis": "Condition", "lab": "Observation", "medication": "MedicationRequest"}


def _cfg(tmp: Path) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=standin_tw.site_mapping(tmp / "mapping"), site_id="T",
                         audit_dir=tmp / "audit")  # fmt: skip


def _night(cfg: AdapterConfig, dsn: str, snap: str, since: str | None = None) -> Any:
    return run_ingest(cfg, "cgrd_sql", dsn, snapshot=snap, since=since, load_fhir=False, validate=False,
                      rebuild_lake=False)  # fmt: skip


def _report(cfg: AdapterConfig, snap: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(
        (snapshot_dir(cfg.lake_dir, snap) / "completeness.json").read_text(encoding="utf-8")
    )
    return out


def _lines(cfg: AdapterConfig, snap: str) -> dict[str, list[str]]:
    """Every record of the night's snapshot, without its ``meta`` (which names the night that wrote it)."""
    out = {}
    for f in sorted(snapshot_dir(cfg.lake_dir, snap).glob("*.ndjson")):
        recs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
        out[f.name] = sorted(json.dumps({k: v for k, v in r.items() if k != "meta"}, sort_keys=True) for r in recs)
    return out


@pytest.fixture()
def site(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    db = tmp_path / "his.sqlite"
    return db, standin_tw.build(db)


def _keys(db: Path, table: str, n: int) -> list[str]:
    con = sqlite3.connect(db)
    key = standin_tw.TABLES_KEY[table]
    got = [r[0] for r in con.execute(f'SELECT {key} FROM "base_{table}" ORDER BY {key} LIMIT {n}')]
    con.close()
    return got


def test_a_full_night_reads_every_row_of_every_view(tmp_path: Path, site: tuple[Path, dict[str, int]]) -> None:
    db, counts = site
    cfg = _cfg(tmp_path)
    rep = _night(cfg, f"sqlite:///{db}", FULL)
    assert rep.passed, rep.errors
    tables = _report(cfg, FULL)["tables"]
    assert {t: tables[t]["rows"] for t in counts if t in tables} == {t: n for t, n in counts.items() if t in tables}
    assert len(tables) >= 10 and all(tables[t]["present"] for t in tables)
    assert rep.counts["Patient"] == counts["patient"]


def test_a_delta_night_reads_only_what_changed_and_ends_equal_to_a_full_read(
    tmp_path: Path, site: tuple[Path, dict[str, int]]
) -> None:
    db, counts = site
    cfg, dsn = _cfg(tmp_path), f"sqlite:///{db}"
    _night(cfg, dsn, FULL)
    edited = {t: _keys(db, t, max(1, counts[t] // 100)) for t in ("diagnosis", "lab", "medication")}  # about 1 %
    for t, ks in edited.items():
        standin_tw.touch(db, t, ks, EDITED)
    rep = _night(cfg, dsn, DELTA, since=f"{FULL} 00:00:00")
    assert rep.passed, rep.errors
    tables = _report(cfg, DELTA)["tables"]
    assert {t: tables[t]["rows"] for t in edited} == {t: len(ks) for t, ks in edited.items()}
    assert tables["note"]["rows"] == 0 and tables["encounter"]["rows"] == 0
    _night(cfg, dsn, REDO)  # a full re-read of the same database
    assert _lines(cfg, DELTA) == _lines(cfg, REDO)


def test_a_night_cut_half_way_then_a_good_one_leaves_no_duplicate_and_no_gap(
    tmp_path: Path, site: tuple[Path, dict[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _ = site
    cfg, dsn = _cfg(tmp_path), f"sqlite:///{db}"
    _night(cfg, dsn, FULL)
    standin_tw.touch(db, "lab", _keys(db, "lab", 5), EDITED)
    real = SqlSource.rows

    def cut(self: SqlSource, table: str, *a: Any, **kw: Any) -> Iterator[dict[str, Any]]:
        for i, row in enumerate(real(self, table, *a, **kw)):
            if table == "lab" and i == 2:
                raise sqlite3.OperationalError("the source stopped")
            yield row

    with monkeypatch.context() as mp:
        mp.setattr(SqlSource, "rows", cut)
        with pytest.raises(sqlite3.OperationalError):
            _night(cfg, dsn, DELTA, since=f"{FULL} 00:00:00")
    assert not (snapshot_dir(cfg.lake_dir, DELTA) / "completeness.json").exists()  # nothing of it is a night
    rep = _night(cfg, dsn, DELTA, since=f"{FULL} 00:00:00")  # the next night repeats what the failed one missed
    assert rep.passed, rep.errors
    _night(cfg, dsn, REDO)
    got = _lines(cfg, DELTA)
    assert got == _lines(cfg, REDO)
    ids = [json.loads(x)["id"] for x in got["Observation.ndjson"]]
    assert not [i for i, n in Counter(ids).items() if n > 1]


def test_the_night_report_counts_a_local_code_no_look_up_knows_and_a_view_the_mapping_does_not_list(
    tmp_path: Path, site: tuple[Path, dict[str, int]]
) -> None:
    db, _ = site
    cfg = _cfg(tmp_path)
    _night(cfg, f"sqlite:///{db}", FULL)
    codes = json.loads((snapshot_dir(cfg.lake_dir, FULL) / "unmapped_codes.json").read_text(encoding="utf-8"))
    assert standin_tw.LOCAL_CODE in json.dumps(codes["lab"])
    assert _report(cfg, FULL)["unlisted"] == {standin_tw.UNLISTED_VIEW: 3}  # named and counted, never read


def test_the_door_needs_no_write_right_and_never_writes(tmp_path: Path, site: tuple[Path, dict[str, int]]) -> None:
    db, counts = site
    cfg, ro = _cfg(tmp_path), standin_tw.readonly_dsn(db)
    seen: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(Engine, "before_cursor_execute", record)
    try:
        rep = _night(cfg, ro, FULL)
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert rep.passed, rep.errors
    assert seen and set(seen) <= {"SELECT", "PRAGMA"}
    with pytest.raises(sqlite3.OperationalError):  # the account really cannot write
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.execute('DELETE FROM "base_lab"')
    assert rep.counts["Patient"] == counts["patient"]


def test_a_night_from_the_views_is_screened_in_zh_tw(tmp_path: Path, site: tuple[Path, dict[str, int]]) -> None:
    """The stand-in's night feeds the lake; FEAS by mail comes back in the Taiwan site's language (D-100)."""
    import io

    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from pypdf import PdfReader
    from tb_contracts import RebuildResult

    from tests.inproc_box import make_box

    db, _ = site
    cfg = _cfg(tmp_path)

    def rebuild(snap: str, nd: Path) -> RebuildResult:
        st = Lake(cfg.lake_dir).rebuild(snap, HashEmbedder(), nd)
        return RebuildResult(snapshot=st.snapshot, tables=st.tables, chunks=st.chunks, embedded_new=st.embedded_new,
                             seconds=st.seconds)  # fmt: skip

    cfg.rebuild = rebuild
    cfg.synthetic_source = True
    rep = run_ingest(cfg, "cgrd_sql", f"sqlite:///{db}", snapshot=FULL, load_fhir=False, validate=False)
    assert rep.passed, rep.errors
    box = make_box(tmp_path / "box", cfg.lake_dir, cfg.secrets_dir)
    assert box.mail("FEAS GZQO") == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="FEAS")[0]
    assert job.state == "done", job.error
    (done,) = box.find_job("done", job.job_id)
    pdf = next(v for k, v in done.attachments().items() if k.endswith(".pdf"))
    assert "資格篩選漏斗" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
