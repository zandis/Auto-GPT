"""A ruleset's approved SQL asked for its patients in batches (NEW-B-53; D-748's rule beyond the cascade's S1).

The approved SQL (``criteria_compiler.compile_sql.overlay.safe_sql``) takes the index dates (``$1``) and the patients
(``$2``, NULL for every patient), and its rows are per patient and index date: a patient's rows depend on that
patient alone, so the scope can be asked for in slices and the answers put together unchanged. The lake's memory
grows with the rows one query carries (patients times index dates, D-748), so a slice is as many patients as fit
``TB_CASCADE_S1_ROWS`` rows. "Every patient" is the snapshot's patients, in the lake's own order, so a query that
groups or orders by patient gives the same table batched as whole."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

ALL_PATIENTS_SQL = "SELECT pid FROM patient ORDER BY pid"


class _Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


def query_by_patients(
    lake: _Lake,
    sql: str,
    dates: Sequence[str],
    pids: Sequence[str] | None,
    snapshot: str | None,
    extra: Sequence[Any] = (),
    rows: int | None = None,
) -> Any:
    """``lake.query(sql, [dates, pids, *extra], snapshot)``, a slice of ``pids`` at a time (every patient of the
    snapshot when None); the tables put together in the slices' order. ``rows``: the rows one query may carry
    (``TB_CASCADE_S1_ROWS`` when None)."""
    from matching.cascade.engine import CascadeError, patients_per_query

    if rows is not None and rows <= 0:
        raise CascadeError(f"rows={rows}: give a whole number of rows above 0")
    who = (
        [str(r["pid"]) for r in lake.query(ALL_PATIENTS_SQL, [], snapshot).to_pylist()]
        if pids is None
        else sorted(set(pids))  # the SQL orders by pid, so the slices do too (and a patient is asked once)
    )
    size = patients_per_query(lake, len(who), len(dates), rows)  # D-748's batches, or one query (D-924)
    tables = [
        lake.query(sql, [list(dates), who[start : start + size], *extra], snapshot)
        for start in range(0, max(len(who), 1), size)
    ]
    return tables[0] if len(tables) == 1 else _joined(tables)


def _joined(tables: list[Any]) -> Any:
    import pyarrow as pa

    if all(isinstance(t, pa.Table) for t in tables):
        return pa.concat_tables(tables)
    return pa.Table.from_pylist([r for t in tables for r in t.to_pylist()])
