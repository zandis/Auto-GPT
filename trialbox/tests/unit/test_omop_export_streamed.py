# ruff: noqa: F811  (the imported fixture feed_dir is requested by its name)
"""T-702 (D-754): the export back from OMOP is read through a server-side cursor and spooled, never held whole."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import pytest
from omop import export, schema

from tests.unit.test_omop_core import (
    SNAP,
    _feed,
    _load,
    _site,
    feed_dir,  # noqa: F401  (the fixture)
)


@pytest.fixture
def db(db_url: str) -> Any:
    d = schema.connect(db_url)
    yield d
    d.close()


def test_the_spooled_export_is_the_export(feed_dir: Path, db: Any, tmp_path: Path) -> None:
    _load(db, _feed(feed_dir), _site(feed_dir))
    whole = export.export_rows(db)
    spooled = export.export_spool(db, tmp_path / "spool")
    assert set(spooled) == set(whole)
    for table, rows in whole.items():
        assert list(spooled[table]) == rows, table  # every value with its type, in the same order
        assert list(spooled[table]) == rows  # read again


def test_the_store_is_read_a_batch_at_a_time(feed_dir: Path, db: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """No query of the export brings its rows whole: each comes through the server-side cursor."""
    from tb_common import db as tdb

    _load(db, _feed(feed_dir), _site(feed_dir))
    whole = export.export_rows(db)
    big = max(len(v) for v in whole.values())
    seen: list[int] = []
    real = tdb.Tx.fetchdicts

    def counted(self: Any, text: str, params: Any = ()) -> list[dict[str, Any]]:
        rows = real(self, text, params)
        seen.append(len(rows))
        return rows

    monkeypatch.setattr(tdb.Tx, "fetchdicts", counted)
    monkeypatch.setattr(tdb, "ITER_BATCH", 7)
    monkeypatch.setattr(tdb.Tx.iterdicts, "__defaults__", ((), 7))
    spooled = export.export_spool(db, tmp_path / "spool")
    assert seen == [] and big > 7  # no table read whole
    assert {t: list(v) for t, v in spooled.items()} == whole  # small batches change nothing


def test_the_spool_goes_when_its_streams_are_dropped(feed_dir: Path, db: Any, tmp_path: Path) -> None:
    _load(db, _feed(feed_dir), _site(feed_dir))
    folder = tmp_path / "spool"
    spooled = export.export_spool(db, folder, remove_when_done=True)
    assert any(folder.iterdir())
    del spooled
    gc.collect()
    assert not folder.exists()


def test_the_lake_s_stream_path_gives_the_spooled_rows(
    feed_dir: Path, db_url: str, tmp_path: Path, monkeypatch: Any
) -> None:
    from lake import source

    monkeypatch.setenv("TB_OMOP_DB_URL", db_url)
    lake = tmp_path / "lake"
    lake.mkdir()
    feed, site = _feed(feed_dir), _site(feed_dir)
    rows = source.omop_rows(feed, site, tz="Asia/Taipei", snapshot=SNAP, lake_dir=lake, spool=True)
    assert isinstance(rows["patient"], export.Spooled)
    assert str(rows["patient"].path).startswith(str(lake / "tmp"))
    whole = source.omop_rows(feed, site, tz="Asia/Taipei", snapshot=SNAP, lake_dir=lake)
    assert {t: list(v) for t, v in rows.items()} == whole
