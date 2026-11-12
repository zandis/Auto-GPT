"""The derive batch on the job runner (D-442, the rest of D-190).

* :func:`after_ingest`: after every ingest that passed, the stored derived rows of the new snapshot are recomputed
  (:func:`tb_common.derived_store.run_batch`, every patient, writes only what changed) before the follow-up
  micro-batch screens. The batch is recorded per snapshot; screening of a snapshot whose batch did not finish reads
  every stored score as unknown (:mod:`matching.stored_scores`), so a failed batch can only send patients to "needs
  information", never decide one. A failure is logged and audited (``derive.failed``) and never turns the passed
  ingest into a failed one.
* :func:`reader`: the store every screening path reads, or None while the flag ``derived.stored_read`` is off (the
  default) or without a trial database.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tb_common.db import ENV
from tb_common.derived_store import FLAG, DerivedStore, mapping_version_of, run_batch, shared_store, stored_read

log = logging.getLogger("orchestrator.derive")


def url_of(orch: Any) -> str | None:
    """The trial database the job runner's own tables live in (its job database), else None (``TB_DB_URL``)."""
    url = getattr(getattr(orch, "db", None), "url", None)
    return url if isinstance(url, str) and url else None


def store(url: str | None = None) -> DerivedStore | None:
    """The derive batch's store: one per trial database URL for the process (``TB_DB_URL`` when None)."""
    return shared_store(url)


def reader(orch: Any) -> DerivedStore | None:
    """The store every screening path reads (D-442), from the job runner's own trial database; None while the flag
    ``derived.stored_read`` is off (the default). No trial database, no flag store or a store that cannot be opened
    is "off": never an error, never an assumed "on". Read once when a job starts."""
    try:
        return stored_read(url_of(orch))
    except Exception as exc:  # the store cannot be opened: no path reads it (the flag reads as off)
        log.warning("stored-score read off: the derived store cannot be opened (%s)", type(exc).__name__)
        return None


class GenerationReader:
    """The stored-score store as one job reads it (T-725, D-491): for the job's own night, the snapshot's finished
    batch counts only when the derived rows are finished **from the generation the job pinned**
    (``datacore.generations.Built.readable``). Otherwise :meth:`batch` answers None, which every reader already
    treats as "no finished batch": each stored score is unknown (``derived_not_stored``). It only ever takes a
    decided answer away. Everything else is the store's own. The job's night and generation are read from its
    record when a batch is first asked for (the job has pinned by then) and the answer is kept to the job's end."""

    def __init__(self, store: DerivedStore, url: str | None, ctx: Any) -> None:
        self._store, self._url, self._ctx = store, url, ctx
        self._seen: dict[tuple[str, str], bool] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def _readable(self, snapshot: str, generation: str) -> bool:
        key = (snapshot, generation)
        if key not in self._seen:
            from datacore.generations import Built

            try:
                with Built(self._url) as ledger:
                    why = ledger.readable("derived", generation)
            except Exception as exc:  # the ledger cannot be read: unknown, never "as if finished"
                log.warning("stored scores unknown: the generation ledger cannot be read (%s)", type(exc).__name__)
                self._seen[key] = False
            else:
                self._seen[key] = why.ok
                if not why.ok:
                    log.info("stored scores read as unknown: %s", why.reason)
        return self._seen[key]

    def batch(self, snapshot: str) -> Any:
        job = getattr(self._ctx, "job", None)
        day = getattr(job, "snapshot_date", None)
        if day is not None and snapshot == day.isoformat():
            gen = str((getattr(job, "options", None) or {}).get("lake_generation") or snapshot)
            if not self._readable(snapshot, gen):
                return None
        return self._store.batch(snapshot)


def reader_for(ctx: Any) -> Any:
    """:func:`reader` of a job's context; a context without a job runner (a test's stand-in) reads as "off". With
    the flag on, the store is read through :class:`GenerationReader` for the generation the job pinned (T-724's
    ``options.lake_generation``; a job without one: its night's date)."""
    orch = getattr(ctx, "orch", None)
    st = reader(orch)
    if st is None or getattr(ctx, "job", None) is None:
        return st
    return GenerationReader(st, url_of(orch), ctx)


def after_ingest(orch: Any, snapshot: str) -> dict[str, Any] | None:
    """Recompute the stored derived rows of ``snapshot``; returns the batch's counts, or None when there is no trial
    database or the batch failed (logged and audited). Never raises."""
    if orch is None:  # a context without a job runner (a test's stand-in): nothing to recompute into
        return None
    try:
        st = store(url_of(orch))
        if st is None:
            log.info("derive batch skipped: no trial database (%s unset)", ENV)
            return None
        lake = orch.services.lake
        # T-725 (D-491, review F-4): the batch is the build of "derived" from this night's generation. A night
        # older than the one the stored rows are built from is refused: the newer rows stay
        from datacore.generations import generation_of, guarded

        rep = guarded(
            "derived",
            generation_of(lake, snapshot),
            lambda: run_batch(st, lake, mapping_version=mapping_version_of(lake, snapshot), snapshot=snapshot),
            url_of(orch),
        )
        if rep is None:
            orch.audit.append("derive.failed", detail={"snapshot": snapshot, "error": "OlderGeneration"})
            return None
        counts = {k: getattr(rep, k) for k in ("inserted", "unchanged", "superseded", "retired", "conflicts", "failed")}
        orch.audit.append("derive.batch", detail={"snapshot": snapshot, **counts})
        if rep.failed:
            log.warning("derive batch of %s: %d patient(s) failed; their scores read as unknown", snapshot, rep.failed)
        return counts
    except Exception as exc:  # the scores of this snapshot then read as unknown; the ingest itself has passed
        log.exception("derive batch of %s failed: %s", snapshot, type(exc).__name__)
        try:
            orch.audit.append("derive.failed", detail={"snapshot": snapshot, "error": type(exc).__name__})
        except Exception as aexc:  # the audit must not take the job down
            log.warning("derive.failed not audited: %s", aexc)
        return None


def status(orch: Any) -> dict[str, Any] | None:
    """For ``/models`` and the health line (``tb_common.metrics.check_derive``): the flag, the snapshot the lake
    serves and the newest derive batch; None without a trial database or when it cannot be read."""
    from tb_common.flags import read

    url = url_of(orch) or os.environ.get(ENV)
    if not url:
        return None
    try:
        st = shared_store(url)
        last = st.last_batch() if st is not None else None
        try:
            current = orch.services.lake.snapshot()
        except Exception:
            current = None
        return {"flag": read(FLAG, url) or "off", "current": current, "last": last}
    except Exception as exc:  # the health line then has no derive check; the page says nothing wrong
        log.warning("derive status not read: %s", type(exc).__name__)
        return None
