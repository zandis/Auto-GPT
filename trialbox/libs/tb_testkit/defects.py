"""Planted-defect generators for the publish-gate tests (spec v4 §5.10 planted-defect suite, DP-25; S1-03).

Each generator edits a copy of a CSV drop directory in place (one ``<table>.csv`` per table plus the source's
``control_totals.json``) and returns a :class:`PlantedDefect` naming the reason code the L1 gate must report.

* Defects *at the source* (type drift, duplicate key, null identifier) also update the source control totals: the
  source system counted the defective rows, so reconciliation still balances and the contract or DQ rule must catch it.
* A *row drop* happens between the source and the drop: the totals stay as the source took them, so reconciliation
  must catch it.
* A *control-total mismatch* edits only the totals file.

Generators are deterministic for a given ``seed``. Synthetic data only.
"""

from __future__ import annotations

import csv
import io
import json
import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tb_contracts.landing import ControlTotals, ReasonCode

CONTROL_TOTALS_FILE = "control_totals.json"


class Defect(StrEnum):
    ROW_DROP = "row_drop"
    TYPE_DRIFT = "type_drift"
    DUPLICATE_KEY = "duplicate_key"
    NULL_IDENTIFIER = "null_identifier"
    CONTROL_TOTAL_MISMATCH = "control_total_mismatch"


EXPECTED_REASON: dict[Defect, ReasonCode] = {
    Defect.ROW_DROP: ReasonCode.RECON_ROW_COUNT,
    Defect.TYPE_DRIFT: ReasonCode.TYPE_MISMATCH,
    Defect.DUPLICATE_KEY: ReasonCode.DUPLICATE_KEY,
    Defect.NULL_IDENTIFIER: ReasonCode.NULL_IDENTIFIER,
    Defect.CONTROL_TOTAL_MISMATCH: ReasonCode.RECON_DISTINCT_PATIENT,
}


@dataclass(frozen=True)
class PlantedDefect:
    kind: Defect
    table: str
    column: str | None
    rows_affected: int
    expected_reason: ReasonCode
    detail: str


# ---------------------------------------------------------------------------------------------------- csv helpers
def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader]
        return list(reader.fieldnames or []), rows


def _write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- totals
def totals_of(rows: list[dict[str, str]], patient_column: str | None, delta_column: str | None) -> ControlTotals:
    """``count(*)``, ``count(distinct patient)`` (non-empty) and ``max(delta)``, as a source system computes them."""
    patients = {r.get(patient_column, "").strip() for r in rows} - {""} if patient_column else set()
    deltas = [r.get(delta_column, "") for r in rows if delta_column and r.get(delta_column, "").strip()]
    return ControlTotals(
        rows=len(rows),
        distinct_patients=len(patients) if patient_column else None,
        max_delta=max(deltas) if deltas else None,
        patient_column=patient_column,
        delta_column=delta_column,
    )


def _load_totals(source_dir: Path) -> dict[str, ControlTotals]:
    path = source_dir / CONTROL_TOTALS_FILE
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {t: ControlTotals.model_validate(v) for t, v in (doc.get("tables") or {}).items()}


def _save_totals(source_dir: Path, totals: dict[str, ControlTotals]) -> None:
    body = {"tables": {t: v.model_dump(mode="json") for t, v in sorted(totals.items())}}
    (source_dir / CONTROL_TOTALS_FILE).write_text(
        json.dumps(body, sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def write_source_totals(source_dir: Path, keys: dict[str, tuple[str | None, str | None]]) -> dict[str, ControlTotals]:
    """Write the totals a source system would deliver with a clean drop: ``keys`` is
    ``{table: (patient_column, delta_column)}``."""
    totals: dict[str, ControlTotals] = {}
    for table, (patient, delta) in sorted(keys.items()):
        path = source_dir / f"{table}.csv"
        if path.exists():
            totals[table] = totals_of(_read(path)[1], patient, delta)
    _save_totals(source_dir, totals)
    return totals


def _recount(source_dir: Path, table: str, rows: list[dict[str, str]]) -> None:
    totals = _load_totals(source_dir)
    if table in totals:
        old = totals[table]
        totals[table] = totals_of(rows, old.patient_column, old.delta_column)
        _save_totals(source_dir, totals)


# ---------------------------------------------------------------------------------------------------- generators
def row_drop(source_dir: Path, table: str, fraction: float = 0.3, seed: int = 0) -> PlantedDefect:
    """Drop ``fraction`` of the rows of one table after the source took its totals (the §5.10 "30 % row drop")."""
    path = source_dir / f"{table}.csv"
    header, rows = _read(path)
    k = max(1, round(len(rows) * fraction))
    gone = set(random.Random(seed).sample(range(len(rows)), k))
    _write(path, header, [r for i, r in enumerate(rows) if i not in gone])
    return PlantedDefect(Defect.ROW_DROP, table, None, k, EXPECTED_REASON[Defect.ROW_DROP], f"dropped {k} rows")


def type_drift(source_dir: Path, table: str, column: str) -> PlantedDefect:
    """The source changes a typed column to free text (every non-empty value gets a unit suffix)."""
    path = source_dir / f"{table}.csv"
    header, rows = _read(path)
    if column not in header:
        raise KeyError(f"{table}.csv has no column {column!r}")
    n = 0
    for r in rows:
        if r.get(column, "").strip():
            r[column] = f"{r[column]} (text)"
            n += 1
    _write(path, header, rows)
    _recount(source_dir, table, rows)
    return PlantedDefect(
        Defect.TYPE_DRIFT, table, column, n, EXPECTED_REASON[Defect.TYPE_DRIFT], f"{column} became text"
    )


def duplicate_key(source_dir: Path, table: str, seed: int = 0) -> PlantedDefect:
    """The source emits one row twice (same primary key)."""
    path = source_dir / f"{table}.csv"
    header, rows = _read(path)
    i = random.Random(seed).randrange(len(rows))
    rows.append(dict(rows[i]))
    _write(path, header, rows)
    _recount(source_dir, table, rows)
    return PlantedDefect(
        Defect.DUPLICATE_KEY, table, header[0], 1, EXPECTED_REASON[Defect.DUPLICATE_KEY], f"row {i} duplicated"
    )


def null_identifier(source_dir: Path, table: str, column: str = "mrn", count: int = 1, seed: int = 0) -> PlantedDefect:
    """The source emits rows without a patient identifier."""
    path = source_dir / f"{table}.csv"
    header, rows = _read(path)
    if column not in header:
        raise KeyError(f"{table}.csv has no column {column!r}")
    picked = random.Random(seed).sample(range(len(rows)), min(count, len(rows)))
    for i in picked:
        rows[i][column] = ""
    _write(path, header, rows)
    _recount(source_dir, table, rows)
    return PlantedDefect(
        Defect.NULL_IDENTIFIER, table, column, len(picked), EXPECTED_REASON[Defect.NULL_IDENTIFIER], "mrn blanked"
    )


def control_total_mismatch(source_dir: Path, table: str, delta: int = 1) -> PlantedDefect:
    """The source's ``count(distinct mrn)`` disagrees with the delivered rows (the data itself is untouched)."""
    totals = _load_totals(source_dir)
    if table not in totals or totals[table].distinct_patients is None:
        raise KeyError(f"no distinct-patient control total for {table!r}")
    old = totals[table]
    totals[table] = old.model_copy(update={"distinct_patients": (old.distinct_patients or 0) + delta})
    _save_totals(source_dir, totals)
    return PlantedDefect(
        Defect.CONTROL_TOTAL_MISMATCH,
        table,
        old.patient_column,
        0,
        EXPECTED_REASON[Defect.CONTROL_TOTAL_MISMATCH],
        f"count(distinct {old.patient_column}) off by {delta}",
    )


def plant(kind: Defect, source_dir: Path, table: str, column: str | None = None, seed: int = 0) -> PlantedDefect:
    """Dispatch to one generator. ``column`` is required for ``type_drift``."""
    if kind == Defect.ROW_DROP:
        return row_drop(source_dir, table, seed=seed)
    if kind == Defect.TYPE_DRIFT:
        if column is None:
            raise ValueError("type_drift needs a column")
        return type_drift(source_dir, table, column)
    if kind == Defect.DUPLICATE_KEY:
        return duplicate_key(source_dir, table, seed=seed)
    if kind == Defect.NULL_IDENTIFIER:
        return null_identifier(source_dir, table, column or "mrn", seed=seed)
    return control_total_mismatch(source_dir, table)


__all__ = [
    "CONTROL_TOTALS_FILE",
    "EXPECTED_REASON",
    "Defect",
    "PlantedDefect",
    "control_total_mismatch",
    "duplicate_key",
    "null_identifier",
    "plant",
    "row_drop",
    "totals_of",
    "type_drift",
    "write_source_totals",
]
