"""The derive batch on the job runner (D-442, the rest of D-190).

* :func:`after_ingest`: after every ingest that passed, the stored derived rows of the new snapshot are recomputed
  (:func:`tb_common.derived_store.run_batch`, every patient, writes only what changed) before the follow-up
  micro-batch screens. The batch is recorded per snapshot; screening of a snapshot whose batch did not finish reads
  every stored score as unknown (:mod:`matching.stored_scores`), so a failed batch can only send patients to "needs
  information", never decide one. A failure is logged and audited (``derive.failed``) and never turns the passed
  ingest into a failed one.
* :func:`store`: the trial database's derived store for the screening read, or None without a trial database (a
  bare DEV stack and the bench read the SQL alone).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from tb_common.db import ENV
from tb_common.derived_store import DerivedStore, mapping_version_of, run_batch

log = logging.getLogger("orchestrator.derive")
_lock = threading.Lock()
_stores: dict[str, DerivedStore] = {}


def store(url: str | None = None) -> DerivedStore | None:
    """One derived store per trial database URL for the process (``TB_DB_URL`` when None); None without one."""
    url = url or os.environ.get(ENV)
    if not url:
        return None
    with _lock:
        if url not in _stores:
            _stores[url] = DerivedStore(url)
        return _stores[url]


def after_ingest(orch: Any, snapshot: str) -> dict[str, Any] | None:
    """Recompute the stored derived rows of ``snapshot``; returns the batch's counts, or None when there is no trial
    database or the batch failed (logged and audited). Never raises."""
    try:
        st = store()
        if st is None:
            log.info("derive batch skipped: no trial database (%s unset)", ENV)
            return None
        lake = orch.services.lake
        rep = run_batch(st, lake, mapping_version=mapping_version_of(lake, snapshot), snapshot=snapshot)
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
