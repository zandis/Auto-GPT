"""Snapshot pinning (T-305a, D-383, CR-063): every job reads one lake snapshot from its first lake call to its end.

Before, a scenario read ``CURRENT`` once for its report and then queried without naming a snapshot: a nightly publish
that landed mid-job moved the later queries to the new night, so one candidate list mixed two nights. Now each job's
:class:`~orchestrator.core.Ctx` hands its scenario a :class:`PinnedLake`:

* the first lake call pins ``CURRENT`` (or the job's recorded ``snapshot_date``, the pin field, for a resumed job and
  a reproducibility re-run) and records it on the job; every later query and note search names that snapshot;
* a job that never touches the lake (STATUS, HELP, APPROVE) pins nothing and is never refused;
* when it pins ``CURRENT``, the snapshot's age is checked against ``TB_LAKE_MAX_SNAPSHOT_AGE_DAYS`` (the job's run
  date, so a frozen clock decides): a stale snapshot fails the job with a plain message instead of screening on a
  lake that stopped updating days ago. A recorded pin is not checked again (a re-run of an old job must work).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Any

from orchestrator.clients import StepFailed

if TYPE_CHECKING:
    from orchestrator.core import Ctx, Services


class PinnedLake:
    """A job's view of the lake: every query and note search on the one snapshot it pinned."""

    def __init__(
        self,
        lake: Any,
        today: Callable[[], date],
        max_age_days: int,
        pinned: str | None = None,
        on_pin: Callable[[str], None] | None = None,
    ) -> None:
        self.lake = lake
        self.pinned = pinned
        self._today = today
        self._max_age = max_age_days
        self._on_pin = on_pin
        self._lock = threading.Lock()

    def pin(self) -> str | None:
        """The job's snapshot: pinned on the first call (``CURRENT``, checked for age); None while the lake has none."""
        with self._lock:
            if self.pinned is None:
                current = getattr(self.lake, "snapshot", None)  # a test's fake lake may have no CURRENT at all
                snap = current() if current is not None else None
                if not snap:
                    return None
                from lake.store import StaleSnapshotError, check_snapshot_age

                try:
                    check_snapshot_age(snap, self._today(), self._max_age)
                except StaleSnapshotError as exc:
                    raise StepFailed("running", str(exc)) from None
                self.pinned = snap
                if self._on_pin is not None:
                    self._on_pin(snap)
            return self.pinned

    def snapshot(self) -> str | None:
        return self.pin()

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        return self.lake.query(sql, params, snapshot or self.pin())

    def chunks_search(
        self,
        pid: str,
        query: str,
        k: int = 5,
        date_from: date | None = None,
        date_to: date | None = None,
        snapshot: str | None = None,
    ) -> Any:
        return self.lake.chunks_search(pid, query, k, date_from, date_to, snapshot=snapshot or self.pin())

    def __getattr__(self, name: str) -> Any:  # put_site, rebuild and the rest: the lake itself
        return getattr(self.lake, name)


def pinned_services(ctx: Ctx) -> Services:
    """The job's services: the orchestrator's, with the lake pinned for this job (none when there is no lake)."""
    base = ctx.orch.services
    if base.lake is None:
        return base
    job = ctx.job

    def record(snap: str) -> None:
        if ctx.job.snapshot_date is None:
            with contextlib.suppress(ValueError):  # a snapshot not named after a night (only with the age check off)
                ctx.update(snapshot_date=date.fromisoformat(snap))

    lake = PinnedLake(
        base.lake,
        today=ctx.today,
        max_age_days=ctx.cfg.env.lake_max_snapshot_age_days,
        pinned=job.snapshot_date.isoformat() if job.snapshot_date else None,
        on_pin=record,
    )
    return replace(base, lake=lake)
