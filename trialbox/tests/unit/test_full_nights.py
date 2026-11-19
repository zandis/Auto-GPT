"""10B-20 (D-1254): the lake keeps the date of its last full night and the delta nights since.

A delta night cannot see a record re-filed to another patient, a merged chart filed again, or an SS-MIX2 file
back-filed with an old 発生日時; the next full night corrects them. ``<lake>/full_nights.json`` says when that was: a
full night that completes writes it, a delta night that completes is counted, a night that fails, is refused or is
held changes nothing; a lake with no record says nothing (the page: "not known"). Each night's event carries the
record as it stands, for the data-operations page. Synthetic data only."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from adapter import full_nights as fn
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _Bad, _cfg, _csv, _Lakes, _row


def _record(lake: Path) -> dict[str, Any]:
    got: dict[str, Any] = json.loads((lake / fn.RECORD).read_text(encoding="utf-8"))
    return got


def _events(tmp_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if str(e.get("event", "")).startswith("ingest.")]


def _night(cfg: Any, tmp_path: Path, snap: str, *, since: str | None = None, **kw: Any) -> Any:
    _csv(tmp_path / snap, [_row("D1", "2026-09-01"), _row(f"D-{snap}", "2026-10-01")])
    kw.setdefault("validate", "validator" in kw)  # a night given a validator is validated by it
    return run_ingest(cfg, "csv", str(tmp_path / snap), since=since, snapshot=snap, load_fhir=False, **kw)


def test_a_full_night_writes_the_record_and_its_event_carries_it(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert fn.read(cfg.lake_dir) is None and fn.said(cfg.lake_dir) is None
    assert _night(cfg, tmp_path, "2026-10-01").passed
    assert _record(cfg.lake_dir) == {"last_full": "2026-10-01", "deltas": []}
    (done,) = [e for e in _events(tmp_path) if e["event"] == "ingest.done"]
    assert done["detail"]["full_night"] == {"last_full": "2026-10-01", "deltas": 0}
    assert not list(cfg.lake_dir.glob(".*.tmp"))  # written atomically: nothing left beside it


def test_delta_nights_are_counted_once_each_and_the_next_full_night_starts_again(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert _night(cfg, tmp_path, "2026-10-01").passed
    assert _night(cfg, tmp_path, "2026-10-02", since="2026-10-01").passed
    assert _night(cfg, tmp_path, "2026-10-03", since="2026-10-02").passed
    assert _record(cfg.lake_dir) == {"last_full": "2026-10-01", "deltas": ["2026-10-02", "2026-10-03"]}
    assert _night(cfg, tmp_path, "2026-10-03", since="2026-10-02").passed  # the same night run again
    assert fn.said(cfg.lake_dir) == {"last_full": "2026-10-01", "deltas": 2}
    assert _events(tmp_path)[-1]["detail"]["full_night"] == {"last_full": "2026-10-01", "deltas": 2}
    assert _night(cfg, tmp_path, "2026-10-04").passed
    assert _record(cfg.lake_dir) == {"last_full": "2026-10-04", "deltas": []}


def test_a_held_night_changes_nothing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert _night(cfg, tmp_path, "2026-10-01").passed
    before = (cfg.lake_dir / fn.RECORD).read_bytes()
    rep = _night(cfg, tmp_path, "2026-10-02", validator=_Bad())  # a full night, held at the gate
    assert rep.held and not rep.passed
    rep = _night(cfg, tmp_path, "2026-10-03", since="2026-10-01", validator=_Bad())  # a delta night, held
    assert rep.held
    assert (cfg.lake_dir / fn.RECORD).read_bytes() == before
    held = [e for e in _events(tmp_path) if e["event"] == "ingest.held"]
    assert [e["detail"]["full_night"] for e in held] == [{"last_full": "2026-10-01", "deltas": 0}] * 2


def test_a_failed_night_changes_nothing_and_says_the_record_as_it_stood(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert _night(cfg, tmp_path, "2026-10-01").passed
    assert _night(cfg, tmp_path, "2026-10-02", since="2026-10-01").passed
    before = (cfg.lake_dir / fn.RECORD).read_bytes()
    with pytest.raises(Exception):  # noqa: B017 - whatever the reader raises on a folder that is not there
        run_ingest(cfg, "csv", str(tmp_path / "no-such-folder"), snapshot="2026-10-03", load_fhir=False,
                   validate=False)  # fmt: skip
    assert (cfg.lake_dir / fn.RECORD).read_bytes() == before
    (failed,) = [e for e in _events(tmp_path) if e["event"] == "ingest.failed"]
    assert failed["detail"]["full_night"] == {"last_full": "2026-10-01", "deltas": 1}


def test_a_refused_night_changes_nothing(tmp_path: Path) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from adapter.pipeline import FutureNight

    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert _night(cfg, tmp_path, "2026-10-01").passed
    before = (cfg.lake_dir / fn.RECORD).read_bytes()
    with pytest.raises(FutureNight):
        _night(cfg, tmp_path, (datetime.now(ZoneInfo(cfg.tz)).date() + timedelta(days=3)).isoformat())
    assert (cfg.lake_dir / fn.RECORD).read_bytes() == before


def test_a_lake_without_a_record_says_not_known_never_a_guess(tmp_path: Path) -> None:
    """Installed before this card: the first delta night counts itself and leaves the date unknown."""
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert _night(cfg, tmp_path, "2026-10-01").passed
    (cfg.lake_dir / fn.RECORD).unlink()  # the lake as it was before this card
    assert fn.said(cfg.lake_dir) is None
    assert _night(cfg, tmp_path, "2026-10-02", since="2026-10-01").passed
    assert _record(cfg.lake_dir) == {"last_full": None, "deltas": ["2026-10-02"]}
    assert fn.said(cfg.lake_dir) == {"last_full": None, "deltas": 1}


def test_the_stewards_accept_of_a_held_full_night_completes_it(tmp_path: Path) -> None:
    from adapter.publish import publish_held

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    assert _night(cfg, tmp_path, "2026-10-01").passed
    assert _night(cfg, tmp_path, "2026-10-02", since="2026-10-01").passed
    assert _night(cfg, tmp_path, "2026-10-03", validator=_Bad()).held  # a full night held at the gate
    assert _record(cfg.lake_dir) == {"last_full": "2026-10-01", "deltas": ["2026-10-02"]}
    out = publish_held(cfg, "2026-10-03")
    assert out.ok and out.promoted
    assert _record(cfg.lake_dir) == {"last_full": "2026-10-03", "deltas": []}


@pytest.mark.parametrize("body", ["{", "[]", '{"last_full": "yesterday", "deltas": []}',
                                  '{"last_full": null, "deltas": ["2026-10-02", 3]}', '{"last_full": null}'])  # fmt: skip
def test_a_damaged_record_is_not_read_and_the_next_night_writes_it_anew(tmp_path: Path, body: str) -> None:
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    assert _night(cfg, tmp_path, "2026-10-01").passed
    (cfg.lake_dir / fn.RECORD).write_text(body, encoding="utf-8")
    assert fn.read(cfg.lake_dir) is None
    assert _night(cfg, tmp_path, "2026-10-02", since="2026-10-01").passed
    assert _record(cfg.lake_dir) == {"last_full": None, "deltas": ["2026-10-02"]}


def test_an_older_night_never_moves_the_record_back(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    fn.completed(lake, "2026-10-05", full=True)
    fn.completed(lake, "2026-10-03", full=True)  # a re-run of an older night
    fn.completed(lake, "2026-10-04", full=False)
    fn.completed(lake, "2026-10-05", full=False)
    assert fn.read(lake) == {"last_full": "2026-10-05", "deltas": []}
    fn.completed(lake, "2026-10-07", full=False)
    fn.completed(lake, "2026-10-06", full=True)  # a full night older than a counted delta keeps the delta
    assert fn.read(lake) == {"last_full": "2026-10-06", "deltas": ["2026-10-07"]}


def test_a_record_that_cannot_be_written_does_not_fail_the_night(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    (lake / fn.RECORD).mkdir()  # not a file: the rename fails
    fn.completed(lake, "2026-10-05", full=True)  # never raises
    assert fn.read(lake) is None
