"""NEW-B-20 (D-661): the box keeps how long its nights took, where the host's doctor can read it.

Lane W's ``update_window`` line places the Windows update window outside the night "from the night's measured
length" (D-606), and no such record existed. The adapter writes each night's start and end into the lake; the
host's nightly backup copies that file beside the box's other records (``deploy/site/night-length.json``);
``tools.night_length.night_runs`` reads it with the standard library only."""

from __future__ import annotations

import ast
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from adapter import night_runs as nr
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg
from tools import night_length
from tools.trialbox import backup_schedule as bs

APPT = ["appt_no", "mrn", "staff_id", "dept_code", "appt_datetime", "duration_min", "status"]


def _feed(path: Path, when: str = "2026-10-05T09:00:00") -> str:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "appointment.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=APPT)
        w.writeheader()
        w.writerow({"appt_no": "A1", "mrn": "10000001", "staff_id": "S1", "dept_code": "MED",
                    "appt_datetime": when, "duration_min": "15", "status": "B"})  # fmt: skip
    return str(path)


def _runs(lake_dir: Path) -> list[dict[str, object]]:
    return list(json.loads((lake_dir / nr.RECORD).read_text(encoding="utf-8"))["nights"])


def test_a_night_that_passed_is_recorded_with_its_start_and_end(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    rep = run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed
    (run,) = _runs(cfg.lake_dir)
    assert run["snapshot"] == "2026-10-01" and run["finished"] is True
    start, end = datetime.fromisoformat(str(run["start"])), datetime.fromisoformat(str(run["end"]))
    assert start.utcoffset() is not None and end.utcoffset() is not None  # with the site's offset
    assert start == rep.started_at.replace(microsecond=0) and start <= end  # to the second
    assert set(run) == {"snapshot", "start", "end", "finished", "run", "steps_at"}  # times, step names: no patient data


def test_a_held_night_is_recorded_as_not_finished_and_a_rerun_replaces_it(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-01", load_fhir=False, validate=False)
    held = run_ingest(cfg, "csv", _feed(tmp_path / "bad", when="not a time"), snapshot="2026-10-02",
                      load_fhir=False, validate=False)  # fmt: skip
    assert held.held
    by = {r["snapshot"]: r for r in _runs(cfg.lake_dir)}
    assert by["2026-10-01"]["finished"] is True and by["2026-10-02"]["finished"] is False
    again = run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-02", load_fhir=False, validate=False)
    assert again.passed
    runs = _runs(cfg.lake_dir)
    assert [r["snapshot"] for r in runs] == ["2026-10-01", "2026-10-02"] and runs[1]["finished"] is True


def test_the_record_keeps_the_nights_the_lake_keeps_and_no_other_count(tmp_path: Path) -> None:
    """How many nights are kept is the lake's own retention: a night whose snapshot was pruned leaves the record."""
    lake = tmp_path / "lake"
    for snap in ("2026-10-01", "2026-10-02", "2026-10-03"):
        (lake / "ndjson" / snap).mkdir(parents=True)
        t = datetime.fromisoformat(f"{snap}T01:00:00+08:00")
        nr.record(lake, snap, t, t.replace(hour=3), finished=True)
    assert [r["snapshot"] for r in _runs(lake)] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    (lake / "ndjson" / "2026-10-01").rmdir()
    t = datetime.fromisoformat("2026-10-04T01:00:00+08:00")
    (lake / "ndjson" / "2026-10-04").mkdir()
    nr.record(lake, "2026-10-04", t, t.replace(hour=2), finished=True)
    assert [r["snapshot"] for r in _runs(lake)] == ["2026-10-02", "2026-10-03", "2026-10-04"]


def test_a_record_that_cannot_be_written_does_not_fail_the_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def no_disk(*a: object, **kw: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(nr, "_write", no_disk)
    cfg = _cfg(tmp_path)
    rep = run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed and "the night's length was not recorded" in caplog.text


# ----------------------------------------------------------------------------------------- the host's side
def _volume(tmp_path: Path, nights: list[dict[str, object]] | None) -> dict[str, str]:
    data = tmp_path / "volumes" / "trialbox_lake-data" / "_data"
    data.mkdir(parents=True)
    if nights is not None:
        (data / nr.RECORD).write_text(json.dumps({"nights": nights}), encoding="utf-8")
    return {"TB_DOCKER_VOLUMES": str(tmp_path / "volumes")}


NIGHTS: list[dict[str, object]] = [
    {"snapshot": "2026-10-01", "start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00",
     "finished": True, "steps_at": {}},
    {"snapshot": "2026-10-02", "start": "2026-10-02T01:00:00+08:00", "end": "2026-10-02T01:20:00+08:00",
     "finished": False, "steps_at": {}},
    {"snapshot": "2026-10-03", "start": "2026-10-03T01:30:00+08:00", "end": "2026-10-03T04:00:00+08:00",
     "finished": True, "steps_at": {}},
]  # fmt: skip


def test_the_nightly_backup_copies_the_record_beside_the_boxes_other_records(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    assert bs.copy_night_length(_volume(tmp_path, NIGHTS), deploy) == ""
    assert night_length.night_runs(deploy) == [
        {"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"},
        {"start": "2026-10-03T01:30:00+08:00", "end": "2026-10-03T04:00:00+08:00"},
    ]  # finished nights only, oldest first


def test_a_volume_the_host_cannot_read_leaves_the_record_as_it_was_and_says_why(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    why = bs.copy_night_length(_volume(tmp_path, None), deploy)
    assert "night_runs.json" in why and not (deploy / "site" / night_length.FILE).exists()
    assert night_length.night_runs(deploy) == []  # not measured


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"nights": 3}', '{"nights": [{"start": "x"}, 7]}'])
def test_a_file_the_reader_cannot_use_is_not_measured_never_an_error(tmp_path: Path, body: str) -> None:
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / night_length.FILE).write_text(body, encoding="utf-8")
    assert night_length.night_runs(tmp_path) == []


def test_the_reader_uses_the_standard_library_only() -> None:
    tree = ast.parse(Path(night_length.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {str(n.module).split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


# ------------------------------------------------------------------------------------------------ review fixes
@pytest.mark.parametrize("body", ['{"nights": [{"snapshot": ["a"]}]}', '{"nights": [{"snapshot": {"a": 1}}]}',
                                  "[" * 100000, '{"nights": "x"}'])  # fmt: skip
def test_a_damaged_record_never_fails_a_night_that_passed(tmp_path: Path, body: str) -> None:
    cfg = _cfg(tmp_path)
    cfg.lake_dir.mkdir(parents=True, exist_ok=True)
    (cfg.lake_dir / nr.RECORD).write_text(body, encoding="utf-8")
    rep = run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed
    assert [r["snapshot"] for r in _runs(cfg.lake_dir)] == ["2026-10-01"]  # and the record is whole again


def test_a_publish_record_of_an_unexpected_shape_never_fails_the_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import publish

    real = publish.read_record
    monkeypatch.setattr(publish, "read_record", lambda folder: {**real(folder), "at": ["x"]})
    cfg = _cfg(tmp_path)
    rep = run_ingest(cfg, "csv", _feed(tmp_path / "f"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed


def test_the_first_finished_run_of_a_night_is_the_nights_measure(tmp_path: Path) -> None:
    """A night run again (a steward's re-run by day, a held re-run of the served night) must not replace the
    night's own times: the update window is placed from them."""
    lake = tmp_path / "lake"
    (lake / "ndjson" / "2026-10-01").mkdir(parents=True)
    night = datetime.fromisoformat("2026-10-01T01:00:00+08:00")
    nr.record(lake, "2026-10-01", night, night.replace(hour=3), finished=True, steps_at={"lake": "x"})
    day = datetime.fromisoformat("2026-10-01T14:00:00+08:00")
    nr.record(lake, "2026-10-01", day, day.replace(hour=15), finished=False)  # a held re-run
    nr.record(lake, "2026-10-01", day, day.replace(hour=16), finished=True)  # a re-run that passed
    (run,) = _runs(lake)
    assert run["start"] == "2026-10-01T01:00:00+08:00" and run["end"] == "2026-10-01T03:00:00+08:00"
    assert run["finished"] is True and run["run"] == 1 and run["steps_at"] == {"lake": "x"}


def test_a_night_that_finished_only_on_a_later_run_is_not_a_measure_of_the_night(tmp_path: Path) -> None:
    """Held at night, passed when run again (by day, or once the lake was free): its times are a re-run's. The
    entry says which run it was, and the reader gives only nights that finished on their first run."""
    lake = tmp_path / "lake"
    (lake / "ndjson" / "2026-10-01").mkdir(parents=True)
    night = datetime.fromisoformat("2026-10-01T01:00:00+08:00")
    nr.record(lake, "2026-10-01", night, night.replace(hour=2), finished=False)
    day = datetime.fromisoformat("2026-10-01T14:00:00+08:00")
    nr.record(lake, "2026-10-01", day, day.replace(hour=15), finished=True)
    (run,) = _runs(lake)
    assert run["finished"] is True and run["run"] == 2 and run["start"] == "2026-10-01T14:00:00+08:00"
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / "site" / night_length.FILE).write_text((lake / nr.RECORD).read_text(), encoding="utf-8")
    assert night_length.night_runs(deploy) == []


@pytest.mark.parametrize("body", ["[]", "3", '{"nights": 3}', "[" * 100000, "not json"])
def test_the_host_copy_never_puts_a_wrong_shaped_file_over_a_good_one_and_never_raises(
    tmp_path: Path, body: str
) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    env = _volume(tmp_path, NIGHTS)
    assert bs.copy_night_length(env, deploy) == ""
    good = (deploy / "site" / night_length.FILE).read_bytes()
    (tmp_path / "volumes" / "trialbox_lake-data" / "_data" / nr.RECORD).write_text(body, encoding="utf-8")
    assert bs.copy_night_length(env, deploy) != ""
    assert (deploy / "site" / night_length.FILE).read_bytes() == good
    assert not list((deploy / "site").glob("*.tmp"))


def test_the_copy_is_readable_by_a_doctor_that_is_not_root(tmp_path: Path) -> None:
    import os

    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    old = os.umask(0o077)
    try:
        assert bs.copy_night_length(_volume(tmp_path, NIGHTS), deploy) == ""
    finally:
        os.umask(old)
    assert (deploy / "site" / night_length.FILE).stat().st_mode & 0o777 == 0o644  # times only: nothing to hide


def test_the_reader_never_raises_on_a_deeply_nested_file(tmp_path: Path) -> None:
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / night_length.FILE).write_text('{"nights": ' + "[" * 100000, encoding="utf-8")
    assert night_length.night_runs(tmp_path) == []


def test_every_backup_run_copies_the_record_and_says_when_it_could_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring: the box's backup run (the nightly's and the console's) makes the copy before the backup."""
    from tests.unit.test_backup_without_pause import GB, SizedBox, _ops_box
    from tools.trialbox import ops as tb_ops

    box = _ops_box(tmp_path, monkeypatch, SizedBox(db_bytes=GB, step_s={}))
    monkeypatch.setenv("TB_DOCKER_VOLUMES", _volume(tmp_path, NIGHTS)["TB_DOCKER_VOLUMES"])
    tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({"mode": "running"})
    assert len(night_length.night_runs(box.deploy)) == 2
    (tmp_path / "volumes" / "trialbox_lake-data" / "_data" / nr.RECORD).unlink()
    _, _, res = bs.run_backup(box.deploy)
    assert "was not copied" in res["night_length"] and len(night_length.night_runs(box.deploy)) == 2
