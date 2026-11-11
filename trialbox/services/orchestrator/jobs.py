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

T-305b (D-403): the pin is also a *hold* on the lake (``Lake.hold``, keyed by the job id): while the job runs, or
waits for an approval, its snapshot is never rebuilt under it (a site publish on ``main`` waits and is applied after;
see ``sitesetup.service``) and never pruned. The orchestrator releases the hold when the job ends
(:func:`release_hold`).
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Any

from orchestrator.clients import StepFailed

if TYPE_CHECKING:
    from orchestrator.core import Ctx, Services

log = logging.getLogger("orchestrator")


class PinnedLake:
    """A job's view of the lake: every query and note search on the one snapshot it pinned."""

    def __init__(
        self,
        lake: Any,
        today: Callable[[], date],
        max_age_days: int,
        pinned: str | None = None,
        on_pin: Callable[[str], None] | None = None,
        holder: str | None = None,
    ) -> None:
        self.lake = lake
        self.pinned = pinned
        self.holder = holder
        self.held = False
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
            if not self.held:
                self._hold(self.pinned)
            return self.pinned

    def _hold(self, snap: str) -> None:
        """Hold the pinned snapshot on the lake for this job (D-403). A lake without holds (a test's fake) or a
        snapshot that is gone (an old re-run) is said in the log, never a failure: the pin still names the snapshot."""
        hold = getattr(self.lake, "hold", None)
        self.held = True
        if hold is None or not self.holder:
            return
        try:
            hold(snap, self.holder)
        except Exception as exc:
            log.warning("job %s: lake snapshot %s not held (%s)", self.holder, snap, type(exc).__name__)

    def release(self) -> None:
        """End this job's hold (the job is done, failed or cancelled)."""
        release = getattr(self.lake, "release", None)
        if not self.held or release is None or not self.holder:
            return
        try:
            release(self.holder)
        except Exception as exc:  # a lake that is down keeps the hold until it expires (Lake.HOLD_TTL_SECONDS)
            log.warning("job %s: lake hold not released (%s)", self.holder, type(exc).__name__)
        self.held = False

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
        holder=job.job_id,
    )
    return replace(base, lake=lake)


def release_hold(services: Services | None, holder: str | None = None) -> None:
    """End the job's lake hold (D-403): its pinned lake's, or, for a job that resumed in a new process and never
    touched the lake again, the hold the lake still keeps under the job's id."""
    lake = services.lake if services is not None else None
    if isinstance(lake, PinnedLake):
        if lake.held:
            lake.release()
            return
        lake = lake.lake
    release = getattr(lake, "release", None)
    if release is not None and holder:
        try:
            release(holder)
        except Exception as exc:
            log.warning("job %s: lake hold not released (%s)", holder, type(exc).__name__)
