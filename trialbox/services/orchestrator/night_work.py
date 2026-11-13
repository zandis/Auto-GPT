"""When the orchestrator's nightly work ended (NEW-B-26, D-667): ``<TB_ORCH_DIR>/night_work.json``.

The adapter's record of a night (``adapter.night_runs``, D-661) ends when the lake is published. The box's night
does not: the timed ingest job then derives and builds the twins, and the night's chain follows it (screen, NAV,
retention; :mod:`orchestrator.night`). This file holds, per night, when that work started and ended, so a tool on
the host that keeps an update clear of the night (``tools.night_length``) can stay clear of all of it.

**Read from the jobs, written once.** A night's entry is written when its last step (retention) has ended and no
job of its chain is still open: ``start`` is when the timer's ingest job was received, ``end`` the latest end among
that ingest and the chain's jobs (a job's ``updated_at`` is its end: nothing changes a job that has ended). The
times are the jobs', not the moment of writing, so a process that died before the write records the same night at
its next start. The first finished entry of a night stays. ``run`` is 1 when the timer's own ingest passed, 2 when
it passed only as an administrator's retry (a daytime interval: the reader does not take it for the night's length).

**Not measured**, never a guess: a night whose ingest failed, a night with no retention job (the scenario is not
on this box, or retention is held), a night whose chain was cut short by the next night's, a box whose scheduler
does not run. Times and a date only: no patient data.

How many nights are kept is not a number of this file's: an entry goes when the job store no longer holds a
retention job of its night (the box's own retention of jobs decides).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from orchestrator.core import Orchestrator

log = logging.getLogger("orchestrator.night")
RECORD = "night_work.json"


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        nights = json.loads(path.read_text(encoding="utf-8"))["nights"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return []
    if not isinstance(nights, list):
        return []
    return [n for n in nights if isinstance(n, dict) and isinstance(n.get("day"), str)]


def _write(path: Path, nights: list[dict[str, Any]]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps({"nights": nights}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def note(orch: Orchestrator) -> None:
    """Write the entry of the night the chain is on, when that night has ended and has none yet. Never raises: a
    record that cannot be written must not fail the chain (the next job's end, or the next start, writes it)."""
    from orchestrator import night

    try:
        ingest = night.current_ingest(orch)
        if ingest is None or ingest.snapshot_date is None:
            return
        day = ingest.snapshot_date.isoformat()
        path = Path(orch.data_dir) / RECORD
        before = _read(path)
        if any(n["day"] == day and n.get("finished") is True for n in before):
            return  # the night's measure is written: it stays
        name = night.night_of(ingest)
        last = night.chain_jobs(orch, name, "retention")
        jobs = [j for step in night.STEPS if step != "retention" for j in night.chain_jobs(orch, name, step)] + last
        if not last or any(j.state not in night.TERMINAL for j in jobs):
            return  # the night's work has not ended, or when it ended is not known
        root = orch.scheduled_root(ingest) or ingest
        ends = [j.updated_at for j in (ingest, *jobs) if j.updated_at is not None]
        if not ends:
            return
        zone = ZoneInfo(orch.cfg.env.tz)
        entry = {
            "day": day,
            "start": root.received_at.astimezone(zone).isoformat(timespec="seconds"),
            "end": max(ends).astimezone(zone).isoformat(timespec="seconds"),
            "finished": True,
            "run": 1 if root.job_id == ingest.job_id else 2,
        }
        kept = {
            str((j.options or {}).get("night_day"))
            for j in orch.db.scheduler_jobs(type_=night.STEP_TYPE["retention"], step="retention")
        }
        nights = [n for n in before if n["day"] in kept and n["day"] != day] + [entry]
        _write(path, sorted(nights, key=lambda n: str(n["day"])))
    except Exception as exc:
        log.warning("the night's work was not recorded (%s): %s", RECORD, type(exc).__name__)


__all__ = ["RECORD", "note"]
