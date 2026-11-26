"""T-730b (D-731): an update the administrator asked for "in the quiet hour" waits for it.

A person still asks for every update (D-178, review J-09); what changes is when it runs. A request for
``update_apply`` with ``when: quiet`` stays pending until the box's quiet hour (``TB_UPDATE_QUIET_AT``, for
``TB_UPDATE_QUIET_HOURS``, the site's clock) and until the orchestrator runs no job; a box that cannot say how many
jobs run is not quiet. It is not expired after the usual hour: it waits for the next quiet hour, and expires after
:data:`ops.QUIET_WAIT_H` without one. Only an update waits; any other request with ``when: quiet`` is refused."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import ops as tb_ops

pytestmark = pytest.mark.nodb

ENV = {"TB_TZ": "Asia/Taipei", "TB_UPDATE_QUIET_AT": "05:00", "TB_UPDATE_QUIET_HOURS": "2", "TB_ENV": "TEST"}  # rc1
IN_QUIET = datetime(2026, 11, 14, 21, 30, tzinfo=UTC)  # 05:30 in Taipei
NOT_QUIET = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)  # 14:00 in Taipei


class Runner(tb_ops.OpsRunner):
    """The real runner with the update itself and the job count stood in."""

    def __init__(self, tmp: Path, jobs: int | None = 0, now: datetime = IN_QUIET) -> None:
        box = tb_ops.Box("compose", tmp / "deploy", dict(ENV))
        super().__init__(box, tb_ops.OpsDir(tmp / "ops"))
        self.applied: list[dict[str, str]] = []
        self._jobs = jobs
        self._now = now

    def now(self) -> datetime:
        return self._now

    def jobs_running(self) -> int | None:
        return self._jobs

    def do_update_apply(self, args: Any) -> tuple[str, list[str]]:
        self.applied.append(dict(args))
        return f"{args.get('bundle')}: applied", []

    def audit(self, res: Any) -> None:  # no compose box here
        return None


def _ask(r: Runner, action: str = "update_apply", **args: str) -> str:
    return r.ops.submit(action, "admin:owner", {"bundle": "trialbox-2026.11-2.tar", **args})


def test_a_quiet_request_outside_the_quiet_hour_waits_and_does_not_run(tmp_path: Path) -> None:
    r = Runner(tmp_path, now=NOT_QUIET)
    rid = _ask(r, when="quiet")
    assert r.run_pending() == [] and r.applied == []
    assert r.ops.result(rid) is None
    waiting = r.write_status()["waiting"]
    assert [w["id"] for w in waiting] == [rid] and "quiet hour" in waiting[0]["why"]


def test_in_the_quiet_hour_with_no_job_running_it_runs(tmp_path: Path) -> None:
    r = Runner(tmp_path)
    rid = _ask(r, when="quiet")
    res = r.run_pending()
    assert [x["id"] for x in res] == [rid] and res[0]["ok"]
    assert r.applied == [{"bundle": "trialbox-2026.11-2.tar", "when": "quiet"}]


@pytest.mark.parametrize("jobs", [1, None])
def test_while_a_job_runs_or_nobody_can_say_it_waits(tmp_path: Path, jobs: int | None) -> None:
    r = Runner(tmp_path, jobs=jobs)
    rid = _ask(r, when="quiet")
    assert r.run_pending() == [] and r.applied == []
    why = r.write_status()["waiting"][0]["why"]
    assert ("1 job" in why) if jobs else ("cannot say" in why)
    assert r.ops.result(rid) is None


def test_a_quiet_request_is_not_expired_after_the_usual_hour(tmp_path: Path) -> None:
    r = Runner(tmp_path, now=NOT_QUIET)
    rid = _ask(r, when="quiet")
    old = time.time() - (tb_ops.MAX_AGE_MIN + 30) * 60
    p = tmp_path / "ops" / "requests" / f"{rid}.json"
    import os

    os.utime(p, (old, old))
    assert r.run_pending() == [] and r.ops.result(rid) is None


def test_with_no_quiet_hour_for_too_long_it_expires_and_never_runs(tmp_path: Path) -> None:
    r = Runner(tmp_path, now=NOT_QUIET)
    rid = _ask(r, when="quiet")
    assert r.run_pending() == []  # first seen by the runner now
    r = Runner(tmp_path, now=datetime.fromtimestamp(NOT_QUIET.timestamp() + tb_ops.QUIET_WAIT_H * 3600 + 60, UTC))
    res = r.run_pending()
    assert [x["id"] for x in res] == [rid]
    assert [x["state"] for x in res] == ["expired"] and not res[0]["ok"] and r.applied == []
    assert "quiet hour" in res[0]["summary"] and "ask again" in res[0]["summary"]


def test_an_update_asked_for_now_still_runs_now_and_still_expires_after_the_hour(tmp_path: Path) -> None:
    r = Runner(tmp_path, now=NOT_QUIET, jobs=3)
    rid = _ask(r)
    assert [x["id"] for x in r.run_pending()] == [rid] and len(r.applied) == 1  # as before: the person waits by it
    r2 = Runner(tmp_path / "b", now=NOT_QUIET)
    rid2 = _ask(r2)
    # the runner's clock is set against the file's own time as the file system reports it (faketime moves that)
    queued = (tmp_path / "b" / "ops" / "requests" / f"{rid2}.json").lstat().st_mtime
    r2._now = datetime.fromtimestamp(queued + (tb_ops.MAX_AGE_MIN + 1) * 60, UTC)
    assert [x["state"] for x in r2.run_pending()] == ["expired"]


def test_only_an_update_waits_for_the_quiet_hour(tmp_path: Path) -> None:
    r = Runner(tmp_path, now=NOT_QUIET)
    rid = r.ops.submit("backup", "admin:owner", {"when": "quiet"})
    res = r.run_pending()
    assert [x["id"] for x in res] == [rid] and not res[0]["ok"] and "only an update" in res[0]["summary"]


@pytest.mark.parametrize(
    ("at", "hours", "now", "quiet"),
    [
        ("05:00", "2", datetime(2026, 11, 14, 20, 59, tzinfo=UTC), False),  # 04:59
        ("05:00", "2", datetime(2026, 11, 14, 21, 0, tzinfo=UTC), True),  # 05:00
        ("05:00", "2", datetime(2026, 11, 14, 22, 59, tzinfo=UTC), True),  # 06:59
        ("05:00", "2", datetime(2026, 11, 14, 23, 0, tzinfo=UTC), False),  # 07:00
        ("23:30", "2", datetime(2026, 11, 14, 16, 0, tzinfo=UTC), True),  # 00:00, a window over midnight
    ],
)
def test_the_quiet_hour_is_read_in_the_site_s_clock(at: str, hours: str, now: datetime, quiet: bool) -> None:
    env = {**ENV, "TB_UPDATE_QUIET_AT": at, "TB_UPDATE_QUIET_HOURS": hours}
    assert tb_ops.in_quiet_hour(env, now) is quiet


def test_a_box_with_a_broken_setting_has_no_quiet_hour() -> None:
    assert tb_ops.in_quiet_hour({**ENV, "TB_UPDATE_QUIET_AT": "five"}, IN_QUIET) is False


# ------------------------------------------------------------------------------------------------ the review (D-731)
def _req_file(tmp: Path, rid: str) -> Path:
    return tmp / "ops" / "requests" / f"{rid}.json"


def _stage(tmp: Path, body: bytes = b"bundle one") -> None:
    inc = tmp / "deploy" / "updates" / "incoming"
    inc.mkdir(parents=True, exist_ok=True)
    (inc / "trialbox-2026.11-2.tar").write_bytes(body)


@pytest.mark.parametrize("args", ["x", ["a"], 7])
def test_a_request_whose_args_are_not_an_object_never_stops_the_runner(tmp_path: Path, args: object) -> None:
    """H1: the console's user writes the request files; a malformed one is a failed result, and the requests after
    it still run."""
    import json

    r = Runner(tmp_path)
    (tmp_path / "ops" / "requests").mkdir(parents=True, exist_ok=True)
    bad = "20261114T000000Z-aaaaaa"
    _req_file(tmp_path, bad).write_text(json.dumps({"id": bad, "action": "update_apply", "by": "x", "at": "2026-11-14T00:00:00+00:00",
                                                     "args": args}), encoding="utf-8")  # fmt: skip
    good = _ask(r)
    res = {x["id"]: x for x in r.run_pending()}
    assert good in res and res[good]["ok"]
    assert r.write_status()["waiting"] == []


def test_touching_the_request_file_does_not_keep_a_quiet_update_alive(tmp_path: Path) -> None:
    """M2: the wait is counted from when the runner first saw the request (its own stamp), not from the file's
    time, which the console's user can move."""
    import os

    r = Runner(tmp_path, now=NOT_QUIET)
    rid = _ask(r, when="quiet")
    assert r.run_pending() == []  # first seen now
    later = Runner(tmp_path, now=datetime.fromtimestamp(NOT_QUIET.timestamp() + tb_ops.QUIET_WAIT_H * 3600 + 60, UTC))
    os.utime(_req_file(tmp_path, rid), None)  # the file says "just now"
    res = later.run_pending()
    assert [x["state"] for x in res] == ["expired"] and later.applied == []


@pytest.mark.parametrize("when", ["Quiet", " quiet", "quiet_hour", "later", ""])
def test_a_when_that_is_not_exactly_quiet_is_refused_not_run_now(tmp_path: Path, when: str) -> None:
    """M3: an update asked for "later" in any other spelling never runs at once."""
    r = Runner(tmp_path, now=NOT_QUIET, jobs=2)
    rid = _ask(r, when=when)
    res = r.run_pending()
    assert [x["id"] for x in res] == [rid] and not res[0]["ok"] and r.applied == []
    assert "when" in res[0]["summary"]


def test_an_interrupted_quiet_update_is_never_run_again(tmp_path: Path) -> None:
    import json

    r = Runner(tmp_path)
    rid = _ask(r, when="quiet")
    marker = r.ops.marker(rid)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"id": rid, "started": "2026-11-14T21:10:00+00:00"}), encoding="utf-8")
    res = r.run_pending()
    assert [x["state"] for x in res] == ["interrupted"] and r.applied == []


def test_a_quiet_update_too_old_is_expired_even_inside_the_quiet_hour(tmp_path: Path) -> None:
    r = Runner(tmp_path, now=NOT_QUIET)
    rid = _ask(r, when="quiet")
    r.run_pending()
    late = Runner(tmp_path, now=datetime.fromtimestamp(IN_QUIET.timestamp() + 2 * 86400, UTC))
    res = late.run_pending()
    assert [x["id"] for x in res] == [rid] and res[0]["state"] == "expired" and late.applied == []


def test_a_quiet_update_runs_once(tmp_path: Path) -> None:
    r = Runner(tmp_path)
    _ask(r, when="quiet")
    r.run_pending()
    assert r.run_pending() == [] and len(r.applied) == 1


def test_a_bundle_replaced_while_it_waited_is_refused(tmp_path: Path) -> None:
    """L5: the person confirmed the file they checked; a different file of that name is not applied."""
    _stage(tmp_path, b"bundle one")
    r = Runner(tmp_path, now=NOT_QUIET)
    rid = _ask(r, when="quiet")
    r.run_pending()  # first seen: its sha256 is kept
    _stage(tmp_path, b"bundle two")
    res = Runner(tmp_path).run_pending()
    assert [x["id"] for x in res] == [rid] and not res[0]["ok"] and "changed" in res[0]["summary"]


def test_an_update_applied_closes_the_quiet_ones_that_wait(tmp_path: Path) -> None:
    """L4: an "apply now" of the same box makes a waiting quiet update superseded, so it is not applied again."""
    r = Runner(tmp_path, now=NOT_QUIET)
    quiet = _ask(r, when="quiet")
    now = _ask(r)
    res = {x["id"]: x for x in r.run_pending()}
    assert res[now]["ok"] and res[quiet]["state"] == "superseded" and len(r.applied) == 1


@pytest.mark.parametrize(
    ("env", "said"),
    [({"TB_TZ": ""}, "TB_TZ"), ({"TB_UPDATE_QUIET_HOURS": "24"}, "TB_UPDATE_QUIET_HOURS"),
     ({"TB_UPDATE_QUIET_HOURS": "0"}, "TB_UPDATE_QUIET_HOURS"), ({"TB_UPDATE_QUIET_AT": "5h"}, "TB_UPDATE_QUIET_AT")],
)  # fmt: skip
def test_a_setting_that_does_not_read_is_said_as_such(tmp_path: Path, env: dict[str, str], said: str) -> None:
    r = Runner(tmp_path)
    r.box.env.update(env)
    _ask(r, when="quiet")
    assert r.run_pending() == [] and r.applied == []
    why = r.write_status()["waiting"][0]["why"]
    assert "does not read" in why and said in why


def test_a_job_count_that_raises_is_not_known(tmp_path: Path) -> None:
    class Raising(Runner):
        def jobs_running(self) -> int | None:
            raise RuntimeError("no compose")

    r = Raising(tmp_path)
    _ask(r, when="quiet")
    assert r.run_pending() == [] and r.applied == []


def test_the_window_is_real_time_on_a_daylight_saving_day() -> None:
    """L6: on the night the clocks go back, a 01:00 window of 2 h lasts 2 real hours, not 3."""
    env = {**ENV, "TB_TZ": "America/New_York", "TB_UPDATE_QUIET_AT": "01:00", "TB_UPDATE_QUIET_HOURS": "2"}
    assert tb_ops.in_quiet_hour(env, datetime(2026, 11, 1, 5, 30, tzinfo=UTC))  # 01:30 EDT
    assert not tb_ops.in_quiet_hour(env, datetime(2026, 11, 1, 7, 30, tzinfo=UTC))  # 02:30 EST, 2 h 30 later
