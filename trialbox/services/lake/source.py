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
``trialbox doctor`` says so). Before any service has started there (a tool's own lakes, a fresh test database) there
is no row and ``TB_LAKE_SOURCE`` still decides, which keeps ``tools/omop_parity.py`` and ``tools/goldens.py`` able to
build both lakes in one run. A rebuild reads the source once, when it starts, and keeps it to the end: a flip in the
middle of a rebuild takes effect at the next one, never half-way (screening reads built snapshots, never the flag).
"""

from __future__ import annotations

import logging
import os
import time
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


def rebuild_source() -> tuple[str, str]:
    """The source of a rebuild that starts now, and where it came from: the ``lake.source`` flag of the trial
    database; ``TB_LAKE_SOURCE`` only while the flag has never been seeded there (or cannot be read: logged)."""
    from tb_common.flags import read

    value = read("lake.source")
    if value is not None:
        return value, "flag lake.source"
    return lake_source(), "TB_LAKE_SOURCE (no lake.source flag in this database)"


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
        logging.getLogger("lake").info("lake %s, snapshot %s: source %s (%s)", lake_dir, snapshot, source, origin)
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
