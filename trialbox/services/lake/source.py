"""Where the lake's rows come from (D-151): ``TB_LAKE_SOURCE=legacy`` (the default for now) or ``omop``.

* ``legacy``: the FHIR NDJSON of the snapshot and the site's inputs, flattened (``lake.flatten``), as before.
* ``omop``: the same NDJSON is loaded into the OMOP CDM store of record (``omop.load``: the snapshot as the
  ``feed`` batch, the site's inputs as the ``site`` batch; idempotent, tombstones for what is gone) and the lake
  tables are exported from OMOP (``omop.export``) with the same names, columns and rows.

Both paths give the rows of :data:`lake.flatten.SCHEMAS`; everything after (Parquet, DuckDB, chunks, embeddings,
``CURRENT``) is the rebuild's own and is unchanged. The OMOP store is the trial database's ``omop`` schema
for the box's lake (``TB_LAKE_DIR``) and an ``omop_<hash>`` schema for any other lake (a practice site's own space, a
test), in ``TB_OMOP_DB_URL`` or ``TB_DB_URL``. The flag flips to ``omop`` when goldens and parity hold (WS-03.5).

**The source is the ``lake.source`` flag** (T-008, D-207, ``tb_common.flags``): the audited ``app.flag`` row of the
trial database, changed on ``/ops/flags`` and seen by every service within five seconds, without a restart.
``TB_LAKE_SOURCE`` only seeds that flag when the console first starts on the database; after that it is ignored (and
``trialbox doctor`` says so). Before the flag is seeded there (a fresh test database) there is no row and
``TB_LAKE_SOURCE`` still decides. A flag that cannot be read stops the rebuild: the variable is never used in place
of an unreadable flag. The tools that build a lake from a named source (``tools/omop_parity.py``,
``tools/goldens.py``) say so with :func:`force`, so a seeded flag cannot make them build both lakes from one source.
A rebuild reads the source once, when it starts, and keeps it to the end: a flip in the middle of a rebuild takes
effect at the next one, never half-way. Screening reads built snapshots, never the flag; what built each snapshot is
kept in ``<lake>/source.jsonl`` and, where the audit log is mounted, as a ``lake.rebuild.source`` audit event.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lake.flatten import Flattener

Resources = dict[str, list[dict[str, Any]]]
Rows = dict[str, list[dict[str, Any]]]
SOURCES = ("legacy", "omop")


def lake_source() -> str:
    """The ``TB_LAKE_SOURCE`` setting (``legacy`` when unset), the seed of the ``lake.source`` flag; anything else is
    refused, never guessed."""
    value = (os.environ.get("TB_LAKE_SOURCE") or "legacy").strip().lower()
    if value not in SOURCES:
        raise ValueError(f"TB_LAKE_SOURCE={value!r}: use one of {', '.join(SOURCES)}")
    return value


_FORCED: contextvars.ContextVar[str | None] = contextvars.ContextVar("tb_lake_source_forced", default=None)
READ_ATTEMPTS = 3
READ_PAUSE_S = 1.0


@contextlib.contextmanager
def force(source: str) -> Iterator[None]:
    """Build from ``source`` inside the block, whatever the flag and the variable say. For the tools that must
    build a lake from a named source (``tools/omop_parity.py``, ``tools/goldens.py``): a ``lake.source`` flag seeded
    in their database must not make them build both lakes from one source. Never used by a service."""
    if source not in SOURCES:
        raise ValueError(f"lake source {source!r}: use one of {', '.join(SOURCES)}")
    token = _FORCED.set(source)
    try:
        yield
    finally:
        _FORCED.reset(token)


def rebuild_source() -> tuple[str, str]:
    """The source of a rebuild that starts now, and where it came from: a tool's :func:`force`; else the
    ``lake.source`` flag of the trial database; ``TB_LAKE_SOURCE`` only when the store was read and the flag has no
    row there (never seeded), or no trial database is configured. A flag that cannot be read (the database is down,
    a bad stored value) is tried :data:`READ_ATTEMPTS` times and then stops the rebuild: falling back to the
    variable would build the lake from the source the administrator switched away from."""
    from tb_common.flags import Flags, FlagUnreadable

    forced = _FORCED.get()
    if forced is not None:
        return forced, "forced by the caller (a tool)"
    for attempt in range(1, READ_ATTEMPTS + 1):
        try:
            value = Flags().value("lake.source")
            break
        except LookupError:
            return lake_source(), "TB_LAKE_SOURCE (no trial database configured)"
        except FlagUnreadable as e:
            if attempt == READ_ATTEMPTS:
                raise RuntimeError(
                    f"the lake rebuild is refused: {e}. TB_LAKE_SOURCE is not used in its place (D-207)"
                ) from e
            time.sleep(READ_PAUSE_S)
    if value is not None:
        return value, "flag lake.source"
    return lake_source(), "TB_LAKE_SOURCE (no lake.source flag in this database)"


def record_source(lake_dir: Path | None, snapshot: str, source: str, origin: str) -> None:
    """Which source built which snapshot, kept: one line in ``<lake>/source.jsonl`` and, where the process has the
    audit log (``TB_AUDIT_DIR``), a ``lake.rebuild.source`` audit event. Until ``lake_meta`` carries the source
    (T-202) this is the record that answers "what built this snapshot". Never stops a rebuild."""
    log = logging.getLogger("lake")
    log.info("lake %s, snapshot %s: source %s (%s)", lake_dir, snapshot, source, origin)
    entry = {"snapshot": snapshot, "source": source, "origin": origin,
             "at": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
    try:
        if lake_dir is not None:
            Path(lake_dir).mkdir(parents=True, exist_ok=True)
            with (Path(lake_dir) / "source.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
        audit_dir = os.environ.get("TB_AUDIT_DIR")
        if audit_dir:
            from tb_common.audit import AuditLog

            AuditLog(Path(audit_dir)).append(
                "lake.rebuild.source", actor="lake", detail={**entry, "lake": str(lake_dir or "")}
            )
    except Exception as e:  # the record is evidence, not a gate
        log.warning("lake %s, snapshot %s: the source record was not written (%s: %s)", lake_dir, snapshot,
                    type(e).__name__, e)  # fmt: skip


def lake_rows(
    feed: Resources,
    site: Resources,
    *,
    tz: str,
    snapshot: str,
    source: str | None = None,
    lake_dir: Path | None = None,
) -> Rows:
    """The lake rows of one snapshot: ``feed`` is the snapshot's NDJSON by type, ``site`` the site's inputs;
    ``lake_dir`` names the lake, whose OMOP store is its own (``omop.schema.schema_for``)."""
    if source is None:
        source, origin = rebuild_source()  # read once, when the rebuild starts (D-207)
        record_source(lake_dir, snapshot, source, origin)
    if source == "legacy":
        merged: Resources = {k: list(v) for k, v in feed.items()}
        for k, v in site.items():  # D-135: the site's own inputs join every snapshot (after the hospital's)
            merged.setdefault(k, []).extend(v)
        return Flattener(tz).flatten(merged)
    return omop_rows(feed, site, tz=tz, snapshot=snapshot, lake_dir=lake_dir)


def omop_rows(
    feed: Resources,
    site: Resources,
    *,
    tz: str,
    snapshot: str,
    url: str | None = None,
    lake_dir: Path | None = None,
) -> Rows:
    import logging

    from omop import schema
    from omop.export import export_rows
    from omop.load import load_batch

    log = logging.getLogger("lake")
    t0 = time.perf_counter()
    db = schema.connect(url, schema.schema_for(lake_dir))
    try:
        name = os.environ.get("TB_SITE_ID", "")
        f = load_batch(db, "feed", snapshot, feed, {k: f"ndjson/{snapshot}/{k}.ndjson" for k in feed}, tz, name)
        s = load_batch(db, "site", f"site@{snapshot}", site, {k: f"site/{k}.ndjson" for k in site}, tz, name)
        rows = export_rows(db)
    finally:
        db.close()
    log.info("lake from OMOP: feed %s, site %s, export in %.1f s", f.as_dict(), s.as_dict(), time.perf_counter() - t0)
    return rows
