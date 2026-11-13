"""NEW-B-26 (D-667): the night record also holds when the ORCHESTRATOR's nightly work ended.

The adapter's record (D-661) ends when the lake is published. The orchestrator's ingest job then derives, builds the
twins and is followed by the night's chain (screen, NAV, retention; T-726). An update window that stays clear of
the adapter's times only could fall into the screening. The orchestrator writes its own pair of times per night,
read from its jobs; the host's backup copies it into the same file, and the same function answers it."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from orchestrator import night, night_work
from tb_contracts import Job

from tests.unit.test_t726_night_runner import MON, TUE, Box, box  # noqa: F401 (fixture)
from tools import night_length
from tools.trialbox import backup_schedule as bs


def _entries(b: Box) -> list[dict[str, Any]]:
    try:
        return list(json.loads((b.tmp_path / night_work.RECORD).read_text(encoding="utf-8"))["nights"])
    except FileNotFoundError:
        return []


def _night_jobs(b: Box, day: date) -> list[Job]:
    jobs = b.orch.db.find(limit=500)
    return [j for j in jobs if j.type == "INGEST" or (j.options or {}).get("night_day") == day.isoformat()]


def _site(b: Box, ts: datetime) -> str:
    return ts.astimezone(ZoneInfo(b.orch.cfg.env.tz)).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------- the orchestrator's record
def test_a_night_whose_chain_ended_is_recorded_from_the_ingests_start_to_the_last_jobs_end(box: Box) -> None:  # noqa: F811
    box.timer_ingest(MON)
    box.orch.drain()
    jobs = _night_jobs(box, MON)
    ingest = next(j for j in jobs if j.type == "INGEST")
    assert len(jobs) == 5 and all(j.updated_at for j in jobs)
    assert _entries(box) == [
        {
            "day": "2026-11-16",
            "start": _site(box, ingest.received_at),
            "end": _site(box, max(j.updated_at for j in jobs if j.updated_at)),
            "finished": True,
            "run": 1,
        }
    ]
    start = datetime.fromisoformat(_entries(box)[0]["start"])
    assert start.utcoffset() is not None  # the site's time, with its offset, as the adapter's record


def test_nothing_is_recorded_before_the_nights_last_step_has_ended(box: Box) -> None:  # noqa: F811
    seen: list[tuple[str, int]] = []
    box.orch.on_terminal.insert(0, lambda job: seen.append((job.type, len(_entries(box)))))  # before the chain's hook
    box.timer_ingest(MON)
    box.orch.drain()
    assert seen == [("INGEST", 0), ("MICROBATCH", 0), ("MICROBATCH", 0), ("NAV", 0), ("RETENTION", 0)]
    assert len(_entries(box)) == 1


def test_a_night_whose_ingest_failed_is_not_measured(box: Box) -> None:  # noqa: F811
    box.timer_ingest(MON, passes=False)
    box.orch.drain()
    assert _entries(box) == []


def test_a_night_that_passed_only_when_an_administrator_ran_it_again_is_not_the_nights_measure(
    box: Box,  # noqa: F811
    tmp_path: Path,
) -> None:
    box.timer_ingest(MON, passes=False)
    box.orch.drain()
    failed = next(j for j in box.orch.db.find(limit=50) if j.type == "INGEST")
    box.ingests.append((MON, True))
    box.orch.retry_scheduled(failed.job_id, by="console:admin", role="admin", reply_to="it@site.example")
    box.orch.drain()
    (entry,) = _entries(box)
    assert entry["day"] == "2026-11-16" and entry["finished"] is True and entry["run"] == 2
    assert entry["start"] == _site(box, failed.received_at)  # the night began with the timer's ingest
    # the host's reader does not take a daytime re-run for the night's length
    _deploy(tmp_path, [_adapter("2026-11-16")], [entry])
    assert night_length.night_runs(tmp_path / "deploy") == [
        {"start": "2026-11-16T01:00:00+08:00", "end": "2026-11-16T03:10:00+08:00"}
    ]


def test_the_first_finished_measure_of_a_night_stays(box: Box) -> None:  # noqa: F811
    box.timer_ingest(MON)
    box.orch.drain()
    before = (box.tmp_path / night_work.RECORD).read_bytes()
    stat = (box.tmp_path / night_work.RECORD).stat()
    for _ in range(3):  # a job's end by day, a restart: the night's times are the night's
        assert night.advance(box.orch) == []
    orch = box.start()
    orch.start()
    night.advance(orch)
    assert (box.tmp_path / night_work.RECORD).read_bytes() == before
    assert (box.tmp_path / night_work.RECORD).stat().st_mtime_ns == stat.st_mtime_ns  # not written again


# ------------------------------------------------------------------------------------------- an interrupt
def test_a_record_that_cannot_be_written_does_not_fail_the_chain_and_a_restart_writes_it_from_the_jobs(
    box: Box,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full(*_a: Any, **_k: Any) -> None:
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(night_work, "_write", full)
        box.timer_ingest(MON)
        box.orch.drain()
    jobs = _night_jobs(box, MON)
    assert len(jobs) == 5 and all(j.state == "done" for j in jobs)  # the night ran to its end
    assert _entries(box) == []
    orch = box.start()  # the process died before the record was written: the next one reads the night from its jobs
    orch.start()
    assert night.advance(orch) == []
    (entry,) = _entries(box)
    # the jobs' time, not the restart's
    assert entry["end"] == _site(box, max(j.updated_at for j in jobs if j.updated_at))
    assert entry["finished"] is True and entry["run"] == 1


@pytest.mark.parametrize("body", ["", "{", "[]", '{"nights": 3}', '{"nights": [3, {"day": 5}]}', "[" * 5000])
def test_a_damaged_record_never_fails_the_chain_and_is_written_anew(box: Box, body: str) -> None:  # noqa: F811
    (box.tmp_path / night_work.RECORD).write_text(body, encoding="utf-8")
    box.timer_ingest(MON)
    box.orch.drain()
    assert [e["day"] for e in _entries(box)] == ["2026-11-16"]
    assert len(box.chain()) == 4


def test_the_record_keeps_the_nights_whose_jobs_the_job_store_keeps_and_no_other_count(box: Box) -> None:  # noqa: F811
    gone = {"day": "2026-09-01", "start": "2026-09-01T02:00:00+08:00", "end": "2026-09-01T04:00:00+08:00",
            "finished": True, "run": 1}  # fmt: skip
    (box.tmp_path / night_work.RECORD).write_text(json.dumps({"nights": [gone]}), encoding="utf-8")
    box.timer_ingest(MON)
    box.orch.drain()
    assert [e["day"] for e in _entries(box)] == ["2026-11-16"]  # no job of 1 September is in the job store
    box.timer_ingest(TUE)
    box.orch.drain()
    assert [e["day"] for e in _entries(box)] == ["2026-11-16", "2026-11-17"]  # Monday's jobs are still kept


def test_a_night_without_a_retention_job_is_not_measured(box: Box) -> None:  # noqa: F811
    del box.orch.scenarios["RETENTION"]  # a box whose last step cannot run: when its night ended is not known
    box.timer_ingest(MON)
    box.orch.drain()
    assert len(box.chain()) == 3 and _entries(box) == []


# ------------------------------------------------------------------------------------------- the host's copy and reader
def _adapter(day: str, **over: Any) -> dict[str, Any]:
    return {"snapshot": day, "start": f"{day}T01:00:00+08:00", "end": f"{day}T03:10:00+08:00", "finished": True,
            "run": 1, "steps_at": {}, **over}  # fmt: skip


def _work(day: str, **over: Any) -> dict[str, Any]:
    return {"day": day, "start": f"{day}T01:00:00+08:00", "end": f"{day}T05:40:00+08:00", "finished": True,
            "run": 1, **over}  # fmt: skip


def _deploy(tmp_path: Path, nights: list[dict[str, Any]], work: Any = None) -> None:
    site = tmp_path / "deploy" / "site"
    site.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {"nights": nights}
    if work is not None:
        body["work"] = work
    (site / night_length.FILE).write_text(json.dumps(body), encoding="utf-8")


def _volumes(tmp_path: Path, nights: list[dict[str, Any]], work: str | None) -> dict[str, str]:
    lake = tmp_path / "volumes" / "trialbox_lake-data" / "_data"
    orch = tmp_path / "volumes" / "trialbox_orch-data" / "_data"
    lake.mkdir(parents=True, exist_ok=True)
    orch.mkdir(parents=True, exist_ok=True)
    (lake / "night_runs.json").write_text(json.dumps({"nights": nights}), encoding="utf-8")
    if work is not None:
        (orch / night_work.RECORD).write_text(work, encoding="utf-8")
    return {"TB_DOCKER_VOLUMES": str(tmp_path / "volumes")}


def test_the_backup_copies_both_records_into_the_one_file_and_the_reader_answers_both(tmp_path: Path) -> None:
    nights = [_adapter("2026-10-01"), _adapter("2026-10-02")]
    env = _volumes(tmp_path, nights, json.dumps({"nights": [_work("2026-10-02")]}))
    deploy = tmp_path / "deploy"
    assert bs.copy_night_length(env, deploy) == ""
    assert night_length.night_runs(deploy) == [
        {"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"},  # its work: not measured
        {"start": "2026-10-02T01:00:00+08:00", "end": "2026-10-02T03:10:00+08:00",
         "work_start": "2026-10-02T01:00:00+08:00", "work_end": "2026-10-02T05:40:00+08:00"},
    ]  # fmt: skip


DEEP = "[" * 1500 + "]" * 1500  # a list json reads and cannot write again


@pytest.mark.parametrize("work", [None, "", "{", "[]", '{"nights": 3}', "[" * 5000])
def test_an_orchestrator_record_the_host_cannot_use_leaves_the_adapters_copy_whole(
    tmp_path: Path, work: str | None
) -> None:
    deploy = tmp_path / "deploy"
    _deploy(tmp_path, [_adapter("2026-10-01")], [_work("2026-10-01")])  # an earlier run's copy
    env = _volumes(tmp_path, [_adapter("2026-10-01"), _adapter("2026-10-02")], work)
    assert bs.copy_night_length(env, deploy) == ""  # the adapter's record is the copy's reason: it was copied
    got = json.loads((deploy / "site" / night_length.FILE).read_text(encoding="utf-8"))
    assert got["nights"] == [_adapter("2026-10-01"), _adapter("2026-10-02")]
    assert got["work"] == [_work("2026-10-01")]  # the earlier copy of the part that could not be read stays
    assert [sorted(r) for r in night_length.night_runs(deploy)] == [
        ["end", "start", "work_end", "work_start"],
        ["end", "start"],
    ]
    assert not list((deploy / "site").glob("*.tmp"))


@pytest.mark.parametrize("where", ["volume", "copy"])
def test_a_part_nested_too_deep_to_write_again_never_fails_the_backup(tmp_path: Path, where: str) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    if where == "copy":
        (deploy / "site" / night_length.FILE).write_text(f'{{"nights": [], "work": {DEEP}}}', encoding="utf-8")
    env = _volumes(tmp_path, [_adapter("2026-10-01")], f'{{"nights": {DEEP}}}' if where == "volume" else None)
    assert bs.copy_night_length(env, deploy) == ""
    got = json.loads((deploy / "site" / night_length.FILE).read_text(encoding="utf-8"))
    assert got == {"nights": [_adapter("2026-10-01")], "work": []}  # what names no night is not copied


def test_the_hosts_copy_keeps_the_work_of_the_nights_the_lake_keeps_and_no_other_count(tmp_path: Path) -> None:
    # the job store keeps every job, so the orchestrator's file grows as its jobs do; the host's copy does not
    work = [_work("2026-09-01"), _work("2026-10-02"), {"day": 7}, "x"]
    env = _volumes(tmp_path, [_adapter("2026-10-02")], json.dumps({"nights": work}))
    assert bs.copy_night_length(env, tmp_path / "deploy") == ""
    got = json.loads((tmp_path / "deploy" / "site" / night_length.FILE).read_text(encoding="utf-8"))
    assert got["work"] == [_work("2026-10-02")]


@pytest.mark.parametrize(
    "work",
    [
        [_work("2026-10-01", finished=False)],
        [_work("2026-10-01", run=2)],
        [_work("2026-10-01", end="2026-10-01T05:40:00")],  # a time without its offset
        [_work("2026-10-01", end="2026-10-01T00:10:00+08:00")],  # an end before its start
        [_work("2026-10-01", start="yesterday")],
        [_work("2026-10-02")],  # another night's
        [3, "x", {"day": 7}],
        [_work("2026-10-01"), _work("2026-10-01", end="2026-10-01T09:00:00+08:00")],  # two answers for one night
        {"day": "2026-10-01"},
        "x",
    ],
)
def test_work_times_the_reader_cannot_use_are_not_measured_and_the_night_is_still_answered(
    tmp_path: Path, work: Any
) -> None:
    _deploy(tmp_path, [_adapter("2026-10-01")], work)
    assert night_length.night_runs(tmp_path / "deploy") == [
        {"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"}
    ]


def test_a_copy_made_before_this_card_reads_as_before(tmp_path: Path) -> None:
    _deploy(tmp_path, [_adapter("2026-10-01")])
    assert night_length.night_runs(tmp_path / "deploy") == [
        {"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"}
    ]


def test_entries_that_name_no_night_are_never_matched_to_each_other(tmp_path: Path) -> None:
    nameless = {k: v for k, v in _adapter("2026-10-01").items() if k != "snapshot"}
    no_day = {k: v for k, v in _work("2026-10-01").items() if k != "day"}
    for entry, work in ((nameless, no_day), ({**nameless, "snapshot": 1}, {**no_day, "day": 1})):
        _deploy(tmp_path, [entry], [work])
        assert night_length.night_runs(tmp_path / "deploy") == [
            {"start": "2026-10-01T01:00:00+08:00", "end": "2026-10-01T03:10:00+08:00"}
        ]


def test_a_write_that_fails_part_way_leaves_no_part_file(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    def full(self: Path, *_a: Any, **_k: Any) -> None:
        self.touch()
        raise OSError(28, "No space left on device")

    box.timer_ingest(MON)
    with monkeypatch.context() as m:
        m.setattr(Path, "replace", full)
        box.orch.drain()
    assert len(box.chain()) == 4 and _entries(box) == []
    assert [p.name for p in box.tmp_path.iterdir() if "night_work" in p.name] == []
