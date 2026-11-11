"""The adapter's dual write into the OMOP store of record (T-106, D-339).

When the flag ``omop.dual_write`` is ``on``, a night that passed its checks is loaded into the OMOP CDM as soon as
its NDJSON snapshot is written, before the lake rebuild and apart from it:

    summary = load_night(cfg, "2026-11-10", lake_dir / "ndjson" / "2026-11-10")   # None when the flag is off

* **The batch is the whole snapshot.** A feed batch is the hospital's complete set of records (``omop.load``): on a
  delta night the snapshot's NDJSON is already the merge of the delta over the last good night, so the folder is
  read, not the delta. The batch is named by the snapshot, as the lake's own OMOP load names it, so a rebuild from
  OMOP after it finds every record ``same``.
* **The store is the lake's.** ``omop.schema.schema_for(lake_dir)``: the box's lake writes the ``omop`` schema.
* **All or nothing, and never the night's problem.** The load is one transaction (``omop.load.load_batch``). When the
  store refuses the batch (an older batch, a mass tombstone, a Data Quality hold) or any error rolls it back, the
  summary says ``refused`` or ``failed`` and the NDJSON night goes on exactly as without the dual write: it is not
  held, CURRENT moves as before. A failure is also kept in the store's ``tb_load`` (``feed-failed``) and names only
  the error type, since a database message can quote a cell.
* **The foreign-key check runs every night.** After the load the Data Quality Relational checks (``isRequired``,
  ``isPrimaryKey``, ``isForeignKey``, ``omop.dqd.relational_violations``) run on the store; the ones with violated
  rows are in the summary, which goes into the ingest report and the night's audit event.
* **The flag is read once**, when the night reaches this step: the stored flag of the trial database, else its seed
  variable ``TB_OMOP_DUAL_WRITE``, else ``off``.

What a feed file that arrives between nights does: it runs as its own night with ``rebuild_lake`` off. Its records
reach ``omop`` within the run (seconds for a site of thousands), while ``CURRENT`` and the screening lake stay on the
last night until the nightly rebuild.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tb_contracts import OmopLoadSummary

if TYPE_CHECKING:
    from adapter.pipeline import AdapterConfig

log = logging.getLogger("adapter")
FLAG = "omop.dual_write"


def enabled(db_url: str | None = None) -> bool:
    """The flag ``omop.dual_write``: its stored value in the trial database, else its seed (``TB_OMOP_DUAL_WRITE``,
    else ``off``). A seed variable with an undeclared value is refused (``ValueError``), never guessed."""
    from tb_common.flags import read, seed_value

    value = read(FLAG, db_url)
    if value is None:
        value = seed_value(FLAG)
    return value == "on"


def _omop_url(cfg: AdapterConfig) -> str | None:
    return os.environ.get("TB_OMOP_DB_URL") or cfg.db_url  # None: omop.schema falls back to TB_DB_URL


def load_night(cfg: AdapterConfig, snap: str, ndjson_dir: Path) -> OmopLoadSummary | None:
    """Load the snapshot in ``ndjson_dir`` into the lake's OMOP store when the flag is on; None when it is off. Never
    raises: a refusal or a failure is the summary's ``state``."""
    try:
        if not enabled(cfg.db_url):
            return None
    except ValueError as exc:  # TB_OMOP_DUAL_WRITE with a value the flag does not declare: said, not guessed
        log.error("omop dual write: %s", exc)
        return OmopLoadSummary(state="failed", batch=snap, schema_name="", seconds=0.0, error="ValueError")
    from omop import schema

    t0 = time.perf_counter()
    name = schema.schema_for(cfg.lake_dir)

    def done(state: str, **kw: Any) -> OmopLoadSummary:
        out = OmopLoadSummary(
            state=state,  # type: ignore[arg-type]
            batch=snap,
            schema_name=name,
            seconds=round(time.perf_counter() - t0, 2),
            **kw,
        )
        log.info("omop dual write %s: %s in %.2f s", snap, state, out.seconds)
        return out

    try:
        db = schema.connect(_omop_url(cfg), name)
    except Exception as exc:
        log.error("omop dual write %s: the store cannot be opened (%s)", snap, type(exc).__name__)
        return done("failed", error=type(exc).__name__)
    try:
        return _load(db, cfg, snap, ndjson_dir, done)
    finally:
        db.close()


def _load(
    db: Any, cfg: AdapterConfig, snap: str, ndjson_dir: Path, done: Callable[..., OmopLoadSummary]
) -> OmopLoadSummary:
    from omop import dqd
    from omop.load import load_batch
    from omop.schema import OmopError

    from adapter.ndjson import read_all

    try:
        feed = read_all(ndjson_dir)
        files = {k: f"ndjson/{snap}/{k}.ndjson" for k in feed}
        site = os.environ.get("TB_SITE_ID") or cfg.site_id
        rep = load_batch(db, "feed", snap, feed, files, cfg.tz, site)
    except OmopError as exc:  # the store's own refusal, rolled back and kept in tb_load (its text is ours)
        log.warning("omop dual write %s refused: %s", snap, exc)
        return done("refused", error=str(exc)[:2000])
    except Exception as exc:  # rolled back: nothing of the batch is in the store
        log.error("omop dual write %s failed (%s): rolled back, the night is not affected", snap, type(exc).__name__)
        _record_failure(db, snap, type(exc).__name__)
        return done("failed", error=type(exc).__name__)
    counts = {
        k: int(getattr(rep, k))
        for k in ("inserted", "updated", "same", "tombstoned", "restored", "concepts_minted", "conflicts_open")
    }
    try:
        with db.transaction() as tx:
            rel = dqd.relational_violations(tx)
    except Exception as exc:  # the load is committed; the check's own failure is said, not hidden
        log.error("omop dual write %s: the relational checks failed to run (%s)", snap, type(exc).__name__)
        return done("loaded", counts=counts, relational_checks=0, error=f"relational checks: {type(exc).__name__}")
    bad = {k: v for k, v in sorted(rel.items()) if v}
    return done("loaded", counts=counts, relational_checks=len(rel), relational_failed=bad)


def _record_failure(db: Any, snap: str, error: str) -> None:
    try:
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO tb_load (source_kind, batch, seconds, counts) VALUES ('feed-failed', ?, 0, ?::jsonb)",
                (snap, json.dumps({"failed": error, "by": "adapter dual write"})),
            )
    except Exception:  # the record is evidence, not a gate
        log.exception("omop dual write %s: the failure could not be recorded in tb_load", snap)
