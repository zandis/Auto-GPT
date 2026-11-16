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
``TB_LAKE_SOURCE`` only seeds that flag when a service first starts on the database; after that it is ignored (and
``trialbox doctor`` says so). Before any service has started there (a fresh test database) there is no row and
``TB_LAKE_SOURCE`` still decides. The tools that build a lake from a named source (``tools/omop_parity.py``,
``tools/goldens.py``) say so with :func:`force`, so a seeded flag cannot make them build both lakes from one source.
A rebuild reads the source once, when it starts, and keeps it to the end: a flip in the middle of a rebuild takes
effect at the next one, never half-way. Screening reads built snapshots, never the flag; what built each snapshot is
kept in ``<lake>/source.jsonl`` and, where the audit log is mounted (``TB_AUDIT_DIR``), as a ``lake.rebuild.source``
audit event (:func:`record_source`).
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import time
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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


@contextlib.contextmanager
def force(source: str) -> Iterator[None]:
    """Build from ``source`` inside the block, whatever the flag and the variable say. For the tools that must build
    a lake from a named source (``tools/omop_parity.py``, ``tools/goldens.py``): a ``lake.source`` flag seeded in
    their database must not make them build both lakes from one source. Never used by a service."""
    if source not in SOURCES:
        raise ValueError(f"lake source {source!r}: use one of {', '.join(SOURCES)}")
    token = _FORCED.set(source)
    try:
        yield
    finally:
        _FORCED.reset(token)


def rebuild_source() -> tuple[str, str]:
    """The source of a rebuild that starts now, and where it came from: a tool's :func:`force`; else the
    ``lake.source`` flag of the trial database; ``TB_LAKE_SOURCE`` only when no trial database is configured or the
    flag has never been seeded there. A flag store that is configured but cannot be read stops the rebuild (fail
    closed): falling back to the variable would silently build from a source the operator switched away from (review
    H1)."""
    from tb_common.flags import Flags, check_value

    forced = _FORCED.get()
    if forced is not None:
        return forced, "forced by the caller (a tool)"
    try:
        value = Flags().row("lake.source")
    except LookupError:  # no TB_DB_URL: a tool or a test without a trial database
        return lake_source(), "TB_LAKE_SOURCE (no trial database configured)"
    except Exception as e:
        raise RuntimeError(f"lake.source flag unreadable ({type(e).__name__}): the rebuild does not guess") from e
    if value is not None:
        return check_value("lake.source", value), "flag lake.source"
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
            from tb_common.audit_writer import open_audit

            open_audit(Path(audit_dir)).append(
                "lake.rebuild.source", actor="lake", detail={**entry, "lake": str(lake_dir or "")}
            )
    except Exception as e:  # the record is evidence, not a gate
        log.warning("lake %s, snapshot %s: the source record was not written (%s: %s)", lake_dir, snapshot,
                    type(e).__name__, e)  # fmt: skip


def lake_rows(
    feed: Mapping[str, Iterable[dict[str, Any]]],
    site: Mapping[str, Iterable[dict[str, Any]]],
    *,
    tz: str,
    snapshot: str,
    source: str | None = None,
    lake_dir: Path | None = None,
    deleted: dict[str, list[str]] | None = None,
    stream: bool = False,
) -> Rows:
    """The lake rows of one snapshot: ``feed`` is the snapshot's NDJSON by type, ``site`` the site's inputs;
    ``lake_dir`` names the lake, whose OMOP store is its own (``omop.schema.schema_for``); ``deleted`` the ids the
    source deleted in this snapshot (its ``tombstones.json``), for the OMOP tombstone's reason (T-305b).

    T-692 (D-473): with ``stream`` the values of ``feed`` and ``site`` may be re-readable streams (readers of NDJSON
    files) and the legacy rows come back as re-readable streams (:meth:`Flattener.stream`), one table at a time; the
    ``omop`` path loads them a chunk at a time (NEW-B-37, D-678); the export back from OMOP is still whole (scale
    review F-17, card T-702)."""
    if source is None:
        source, origin = rebuild_source()  # read once, when the rebuild starts (D-207)
        record_source(lake_dir, snapshot, source, origin)
    if source == "legacy" and stream:
        both = {k: _Joined(feed.get(k, ()), site.get(k, ())) for k in [*feed, *(k for k in site if k not in feed)]}
        return Flattener(tz).stream(both)  # type: ignore[return-value]
    if source == "legacy":
        merged: Resources = {k: list(v) for k, v in feed.items()}
        for k, v in site.items():  # D-135: the site's own inputs join every snapshot (after the hospital's)
            merged.setdefault(k, []).extend(v)
        return Flattener(tz).flatten(merged)
    if stream:  # NEW-B-37 (D-678): re-readable streams go to the OMOP load as they are, read a chunk at a time;
        # T-702 (D-754): the export back comes as re-readable streams of a spool on the lake's volume
        return omop_rows(feed, site, tz=tz, snapshot=snapshot, lake_dir=lake_dir, deleted=deleted, spool=True)
    feed_l: Resources = {k: list(v) for k, v in feed.items()}
    site_l: Resources = {k: list(v) for k, v in site.items()}
    return omop_rows(feed_l, site_l, tz=tz, snapshot=snapshot, lake_dir=lake_dir, deleted=deleted)


class _Joined:
    """The hospital's records of a type and then the site's own (D-135), read again each time it is iterated."""

    def __init__(self, first: Iterable[dict[str, Any]], then: Iterable[dict[str, Any]]) -> None:
        self.first, self.then = first, then

    def __iter__(self) -> Iterator[dict[str, Any]]:
        yield from self.first
        yield from self.then


def omop_rows(
    feed: Mapping[str, Iterable[dict[str, Any]]],
    site: Mapping[str, Iterable[dict[str, Any]]],
    *,
    tz: str,
    snapshot: str,
    url: str | None = None,
    lake_dir: Path | None = None,
    deleted: dict[str, list[str]] | None = None,
    spool: bool = False,
) -> Rows:
    """Load the snapshot into the lake's OMOP store and export the lake rows back. With ``spool`` (T-702, D-754) the
    rows come back as re-readable streams of files in the lake's scratch folder (``lake.store.temp_dir``), removed
    once the streams are dropped: never the whole export in memory."""
    import logging
    import tempfile

    from omop import schema
    from omop.export import export_rows, export_spool
    from omop.load import load_batch

    log = logging.getLogger("lake")
    t0 = time.perf_counter()
    db = schema.connect(url, schema.schema_for(lake_dir), lake_dir=lake_dir)
    try:
        name = os.environ.get("TB_SITE_ID", "")
        files = {k: f"ndjson/{snapshot}/{k}.ndjson" for k in feed}
        f = load_batch(db, "feed", snapshot, feed, files, tz, name, deleted=deleted)
        s = load_batch(db, "site", f"site@{snapshot}", site, {k: f"site/{k}.ndjson" for k in site}, tz, name)
        if spool:
            from lake.store import temp_dir

            base = temp_dir(lake_dir) if lake_dir is not None else Path(tempfile.gettempdir())
            base.mkdir(parents=True, exist_ok=True)
            out = Path(tempfile.mkdtemp(prefix="omop-export-", dir=base))
            # re-readable streams in place of lists, as the legacy path's stream (Flattener.stream) gives them
            rows: Rows = cast(Rows, export_spool(db, out, remove_when_done=True))
        else:
            rows = export_rows(db)
    finally:
        db.close()
    log.info("lake from OMOP: feed %s, site %s, export in %.1f s", f.as_dict(), s.as_dict(), time.perf_counter() - t0)
    return rows
