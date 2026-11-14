"""NEW-B-25 (D-666): a re-run of a COHORT MERGE rebuilds the alliance tables as the earlier merges left them.

A finding of lane A2's review of the one upload decoder (#479). An earlier merge whose Big5 or Shift_JIS table
made the job fail at the time (the old reader raised a Python error) parses today, and the replay stored it,
though the first run never did; the tables after it in that job, never reached then, were stored too. A replay
gives what the first run gave, or says that it cannot."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import rerun
from orchestrator.scenarios import cohort

pytestmark = pytest.mark.nodb


def _table(site: str, n: int = 12) -> list[dict[str, Any]]:
    return [{"site_id": site, "disease": "gout", "quarter": "2026Q3", "criterion_id": "GOUT-COH-INC-01",
             "criterion_label": "痛風の診断", "n": n, "n_contactable": 0, "definition_version": "GOUT-COH@1.0.0"}]  # fmt: skip


def _utf8(site: str) -> bytes:
    return cohort.to_csv(_table(site))


def _big5(site: str) -> bytes:
    rows = _table(site)
    rows[0]["criterion_label"] = "痛風診斷（確定）"
    return cohort.to_csv(rows).decode("utf-8-sig").encode("big5")


class _Db:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []  # (site, job)

    def cohort_store(self, rows: list[dict[str, Any]], job_id: str, sender: str) -> None:
        self.stored.append((rows[0]["site_id"], job_id))

    def cohort_senders(self, site: str) -> set[str]:
        return set()


def _job(job_id: str, files: list[tuple[str, bytes]], state: str = "done", error: Any = None) -> Any:
    return SimpleNamespace(
        job_id=job_id, state=state, ruleset="MERGE", requested_by="crc@hospb.test", error=error, outputs=[],
        inputs=[SimpleNamespace(filename=name, minio_key=f"{job_id}/{name}") for name, _ in files],
        _bytes={f"{job_id}/{name}": data for name, data in files},
    )  # fmt: skip


def _orch(jobs: list[Any]) -> Any:
    store = {k: v for j in jobs for k, v in j._bytes.items()}
    return SimpleNamespace(
        db=SimpleNamespace(find=lambda type_, limit: list(jobs)),
        cfg=SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(id="DEMO-A"))),
        store=SimpleNamespace(get=lambda key: store[key]),
    )


def _crash(detail: str) -> Any:
    return SimpleNamespace(step="running", message="Internal error while processing the job.", detail=detail)


def _replayed(jobs: list[Any]) -> list[tuple[str, str]]:
    db = _Db()
    rerun._replay_alliance_tables(_orch(jobs), db, "J9")  # type: ignore[arg-type]
    return db.stored


def test_a_table_that_made_the_first_run_fail_is_not_stored_by_the_replay_nor_the_tables_after_it() -> None:
    """The old reader raised on the Big5 table: the job failed there. What it had stored before that table stays;
    that table and the ones after it were never stored."""
    then = _crash("UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb5 in position 78: invalid start byte")
    failed = _job("J1", [("b.csv", _utf8("DEMO-B")), ("c.csv", _big5("DEMO-C")), ("d.csv", _utf8("DEMO-D"))],
                  state="failed", error=then)  # fmt: skip
    assert cohort.parse_csv(_big5("DEMO-C"))[1] == []  # today's reader reads it: that is the trap
    assert _replayed([failed]) == [("DEMO-B", "J1")]


def test_a_merge_that_ended_done_is_replayed_whole_whatever_its_tables_character_set() -> None:
    """A job that ended ``done`` read every table with the reader of its time. Before the one decoder such a job
    had only UTF-8 tables (anything else raised); since then the same decoder reads them now as then."""
    done = _job("J1", [("b.csv", _utf8("DEMO-B")), ("c.csv", _big5("DEMO-C"))])
    assert _replayed([done]) == [("DEMO-B", "J1"), ("DEMO-C", "J1")]


def test_a_merge_that_refused_every_table_stored_nothing() -> None:
    none = SimpleNamespace(step="running", message="No valid alliance table:\n- b.csv: header must be ...", detail=None)
    failed = _job("J1", [("b.csv", _utf8("DEMO-B"))], state="failed", error=none)
    assert _replayed([failed]) == []
    early = SimpleNamespace(step="received", message="This box is not the alliance root; COHORT MERGE is refused.",
                            detail=None)  # fmt: skip
    assert _replayed([_job("J1", [("b.csv", _utf8("DEMO-B"))], state="failed", error=early)]) == []


def test_a_merge_that_crashed_in_an_unknown_place_cannot_be_replayed_and_the_rerun_says_so() -> None:
    """An internal error that is not the old reader's: which tables the job had stored when it crashed is recorded
    nowhere. The replay does not guess."""
    failed = _job("J1", [("b.csv", _utf8("DEMO-B")), ("c.csv", _utf8("DEMO-C"))], state="failed",
                  error=_crash("KeyError: 'quarter'"))  # fmt: skip
    with pytest.raises(rerun.ReplayUnknown) as exc:
        _replayed([failed])
    assert "J1" in str(exc.value) and "KeyError" not in str(exc.value)  # the job, not its error's text


def test_a_merge_that_failed_after_its_tables_were_stored_is_replayed_whole() -> None:
    """A failure of a later step (the output's routing refused, a service down): the loop over the tables had
    ended."""
    routing = SimpleNamespace(step="routing", message="Output routing refused: x.", detail=None)
    failed = _job("J1", [("b.csv", _utf8("DEMO-B"))], state="failed", error=routing)
    assert _replayed([failed]) == [("DEMO-B", "J1")]


# ------------------------------------------------------------------------------------------------ review fixes
def _err(step: str, message: str, detail: str | None = None) -> Any:
    return SimpleNamespace(step=step, message=message, detail=detail)


@pytest.mark.parametrize(("error", "stored"), [
    # cancelled before it ran (only a job that has not started is cancelled by a person's request): nothing stored
    (_err("cancelled", "Cancelled by crc@hospa.test."), []),
    # failed in the report, which comes after the loop over the tables: every table was stored
    (_err("reporting", "Internal error while processing the job.", "KeyError: 'x'"), [("DEMO-B", "J1")]),
    (_err("reporting", "This job was interrupted by a restart 3 times (TB_JOB_MAX_RESTARTS)."), [("DEMO-B", "J1")]),
    (_err("routing", "Output routing refused: x."), [("DEMO-B", "J1")]),
])  # fmt: skip
def test_what_a_failed_merge_stored_is_told_from_where_it_failed(error: Any, stored: list[tuple[str, str]]) -> None:
    assert _replayed([_job("J1", [("b.csv", _utf8("DEMO-B"))], state="failed", error=error)]) == stored


@pytest.mark.parametrize("error", [
    # stopped while it ran, at a point nobody recorded: before the tables, between two of them, or after them
    _err("cancelled", "Cancelled on request."),
    _err("running", "This job was interrupted by a restart 3 times (TB_JOB_MAX_RESTARTS)."),
    _err("running", "The lake service failed.", "HTTP 503"),
    _err("unknown", "unknown error"),
    None,  # failed, with no error recorded at all
])  # fmt: skip
def test_a_merge_stopped_at_a_point_nobody_recorded_is_never_guessed(error: Any) -> None:
    with pytest.raises(rerun.ReplayUnknown, match="J1"):
        _replayed([_job("J1", [("b.csv", _utf8("DEMO-B"))], state="failed", error=error)])
