"""Where the lake's rows come from (D-149): ``TB_LAKE_SOURCE=legacy`` (the default for now) or ``omop``.

* ``legacy``: the FHIR NDJSON of the snapshot and the site's inputs, flattened (``lake.flatten``), as before.
* ``omop``: the same NDJSON is loaded into the OMOP CDM store of record (``omop.load``: the snapshot as the
  ``feed`` batch, the site's inputs as the ``site`` batch; idempotent, tombstones for what is gone) and the lake
  tables are exported from OMOP (``omop.export``) with the same names, columns and rows.

Both paths give the rows of :data:`lake.flatten.SCHEMAS`; everything after (Parquet, DuckDB, chunks, embeddings,
``CURRENT``) is the rebuild's own and is unchanged. The OMOP store is the trial database's ``omop`` schema
for the box's lake (``TB_LAKE_DIR``) and an ``omop_<hash>`` schema for any other lake (a practice site's own space, a
test), in ``TB_OMOP_DB_URL`` or ``TB_DB_URL``. The flag flips to ``omop`` when goldens and parity hold (WS-03.5).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from lake.flatten import Flattener

Resources = dict[str, list[dict[str, Any]]]
Rows = dict[str, list[dict[str, Any]]]
SOURCES = ("legacy", "omop")


def lake_source() -> str:
    """``TB_LAKE_SOURCE`` (``legacy`` when unset); anything else is refused, never guessed."""
    value = (os.environ.get("TB_LAKE_SOURCE") or "legacy").strip().lower()
    if value not in SOURCES:
        raise ValueError(f"TB_LAKE_SOURCE={value!r}: use one of {', '.join(SOURCES)}")
    return value


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
    if (source or lake_source()) == "legacy":
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
