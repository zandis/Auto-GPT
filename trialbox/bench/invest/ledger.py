"""The run ledger: schemas, content hashes, a deterministic Parquet writer, DuckDB views (INVEST-1 §1.2).

Two fact tables and a run header, Parquet partitioned by ``run_id/protocol``. Every id is a content hash, so a re-run
on unchanged input writes the same bytes. Timing is the one non-deterministic column family and lives in its own
table (``match_timing``, keyed by ``row_key``), so the fact tables stay byte-identical. See ``LEDGER-SCHEMA.md``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

STR, INT, FLT, BOOL = pa.string(), pa.int64(), pa.float64(), pa.bool_()

#: ``match_stage``: one row per patient x protocol x criterion x stage x attempt (``*_json``: canonical JSON)
MATCH_COLS: tuple[tuple[str, pa.DataType], ...] = (
    ("row_key", STR),
    ("run_id", STR),
    ("pid", STR),
    ("protocol_id", STR),
    ("criterion_id", STR),
    ("card_id", STR),
    ("card_version", STR),
    ("canonical_hash", STR),
    ("stage", STR),
    ("attempt", INT),
    ("inputs_hash", STR),
    ("atoms_json", STR),
    ("sql_sha", STR),
    ("cql_sha", STR),
    ("row_evidence_json", STR),
    ("passages_json", STR),
    ("passage_k", INT),
    ("model_raw_json", STR),
    ("code_checks_json", STR),
    ("verdict", STR),
    ("unknown_kind", STR),
    ("reason_code", STR),
    ("basis", STR),
    ("final", BOOL),
    ("affirmed", BOOL),
    ("opinions_json", STR),
    ("confidence", FLT),
    ("gold", STR),
    ("gold_quote_rank", INT),
)

#: wall-clock columns, split out of ``match_stage`` so that table is reproducible
TIMING_COLS: tuple[tuple[str, pa.DataType], ...] = (
    ("row_key", STR),
    ("run_id", STR),
    ("protocol_id", STR),
    ("ms_wall", FLT),
    ("ms_model", FLT),
    ("queue_depth", INT),
)

#: ``trial_stage``: one row per nct x line x stage
TRIAL_COLS: tuple[tuple[str, pa.DataType], ...] = (
    ("row_key", STR),
    ("run_id", STR),
    ("nct", STR),
    ("source", STR),
    ("section_region", STR),
    ("line_id", STR),
    ("line_text_sha", STR),
    ("stage", STR),
    ("inputs_hash", STR),
    ("output_json", STR),
    ("model_raw_json", STR),
    ("status", STR),
    ("reason_code", STR),
    ("ms", FLT),
    ("gold", STR),
)

#: the run header; ``started`` is not part of it (a clock breaks reproducibility), it goes in ``run_clock.json``
RUN_COLS: tuple[tuple[str, pa.DataType], ...] = (
    ("run_id", STR),
    ("code_sha", STR),
    ("bench_sha", STR),
    ("model_pins_json", STR),
    ("prompt_shas_json", STR),
    ("schema_shas_json", STR),
    ("terminology_sha", STR),
    ("lake_snapshot_sha", STR),
    ("ruleset_hashes_json", STR),
    ("sets_json", STR),
    ("tz", STR),
    ("run_date", STR),
)

STAGES_MATCH = ("S0", "S1", "S1b", "S2", "S2b", "S3", "S4", "S5", "tier")
STAGES_TRIAL = (
    "region",
    "split",
    "atoms",
    "template",
    "card_proposal",
    "instantiate",
    "compile_sql",
    "compile_cql",
    "equivalence",
)
VERDICTS = ("T", "F", "U", "not_applicable")
TABLES: dict[str, tuple[tuple[str, pa.DataType], ...]] = {
    "match_stage": MATCH_COLS,
    "match_timing": TIMING_COLS,
    "trial_stage": TRIAL_COLS,
}


def canonical_json(obj: Any) -> str:
    """Sorted keys, no spaces, UTF-8 as is: the same value is always the same string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(*parts: Any) -> str:
    """sha256 over the canonical JSON of the parts, as ``sha256:<hex>``."""
    return "sha256:" + hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()


def sha_of_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_id_of(header: Mapping[str, Any]) -> str:
    """The run id is the hash of the header fields (code, pins, snapshot, rulesets, sets): same inputs, same id."""
    return "run-" + content_hash(dict(header))[7:23]


def schema_of(cols: Sequence[tuple[str, pa.DataType]]) -> pa.Schema:
    return pa.schema([pa.field(n, t) for n, t in cols])


_SQL_TYPES = {STR: "VARCHAR", INT: "BIGINT", FLT: "DOUBLE", BOOL: "BOOLEAN"}


def ddl_sql() -> str:
    """The ledger as DuckDB DDL, for documentation and tests (the views of ``connect`` have the same columns)."""
    out = []
    for table, cols in {**TABLES, "run": RUN_COLS}.items():
        body = ",\n  ".join(f"{n} {_SQL_TYPES[t]}" for n, t in cols)
        out.append(f"CREATE TABLE {table} (\n  {body}\n);")
    return "\n".join(out) + "\n"


def make_row(cols: Sequence[tuple[str, pa.DataType]], values: Mapping[str, Any]) -> dict[str, Any]:
    """A full row: every column present (None when absent), no unknown column, ``*_json`` values canonicalised."""
    names = {n for n, _ in cols}
    extra = set(values) - names
    if extra:
        raise KeyError(f"unknown ledger column(s): {sorted(extra)}")
    row: dict[str, Any] = {}
    for n, _ in cols:
        v = values.get(n)
        if n.endswith("_json") and v is not None and not isinstance(v, str):
            v = canonical_json(v)
        row[n] = v
    return row


def row_key_of(row: Mapping[str, Any], skip: Iterable[str] = ("row_key",)) -> str:
    """Hash of every column of the row except ``skip``: the row's content address."""
    skipped = set(skip)
    return content_hash({k: v for k, v in row.items() if k not in skipped})


class LedgerWriter:
    """Collects rows, then ``close()`` writes them: sorted, one Parquet file per table and protocol, fixed
    compression, no clock; a ``MANIFEST.json`` lists every file with its sha256 and row count."""

    def __init__(self, root: Path, run_id: str, header: Mapping[str, Any]) -> None:
        self.dir = Path(root) / run_id
        self.run_id = run_id
        self.header = dict(header)
        self._rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    def add(self, table: str, partition: str, values: Mapping[str, Any]) -> str:
        """Add one match or trial row; ``run_id`` is filled in and ``row_key`` computed. Returns the key."""
        row = make_row(TABLES[table], {**values, "run_id": self.run_id})
        row["row_key"] = row_key_of(row)
        self._rows[(table, partition)].append(row)
        return str(row["row_key"])

    def add_timing(self, partition: str, row_key: str, **t: Any) -> None:
        self._rows[("match_timing", partition)].append(
            make_row(TIMING_COLS, {"row_key": row_key, "run_id": self.run_id, "protocol_id": partition, **t})
        )

    def count(self, table: str, partition: str | None = None) -> int:
        return sum(len(r) for (t, p), r in self._rows.items() if t == table and partition in (None, p))

    def close(self, clock: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Write the whole run into a staging directory, then publish it by rename: a rewrite replaces the run, it
        never mixes with it, and an interrupted write leaves the earlier run (or nothing) in place."""
        stage = self.dir.with_name(f".{self.run_id}.staging")
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        files: dict[str, dict[str, Any]] = {}
        for (table, part), rows in sorted(self._rows.items()):
            rows.sort(key=lambda r: (str(r["row_key"]), canonical_json(r)))
            path = stage / table / f"protocol={part}" / "part-0.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_parquet(path, TABLES[table], rows)
            files[path.relative_to(stage).as_posix()] = {"rows": len(rows), "sha256": _file_sha(path)}
        run_path = stage / "run" / "run.parquet"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        _write_parquet(run_path, RUN_COLS, [make_row(RUN_COLS, {**self.header, "run_id": self.run_id})])
        files[run_path.relative_to(stage).as_posix()] = {"rows": 1, "sha256": _file_sha(run_path)}
        manifest = {"run_id": self.run_id, "files": files}
        (stage / "MANIFEST.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        if clock is not None:  # the only non-reproducible file, kept apart
            (stage / "run_clock.json").write_text(canonical_json(dict(clock)) + "\n", encoding="utf-8")
        old = self.dir.with_name(f".{self.run_id}.old")
        shutil.rmtree(old, ignore_errors=True)
        if self.dir.exists():
            self.dir.rename(old)
        stage.rename(self.dir)
        shutil.rmtree(old, ignore_errors=True)
        return manifest


def _write_parquet(path: Path, cols: Sequence[tuple[str, pa.DataType]], rows: list[dict[str, Any]]) -> None:
    table = pa.Table.from_pylist(rows, schema=schema_of(cols))
    pq.write_table(table, path, compression="zstd", use_dictionary=True, write_statistics=True, row_group_size=65536)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect(root: Path, run_id: str) -> Any:
    """An in-memory DuckDB with a view per table over the run's Parquet files (``match_stage``, ``match_timing``,
    ``trial_stage``, ``run``), over the files the run's ``MANIFEST.json`` lists and no others. A table with no file
    (or a run with no manifest: not published) gets an empty view with the right columns."""
    import duckdb

    con = duckdb.connect(":memory:")
    base = Path(root) / run_id
    manifest = base / "MANIFEST.json"
    listed = sorted(json.loads(manifest.read_text("utf-8"))["files"]) if manifest.exists() else []
    for table, cols in {**TABLES, "run": RUN_COLS}.items():
        files = [base / rel for rel in listed if rel.startswith(f"{table}/")]
        if files:
            con.register(table, con.read_parquet([f.as_posix() for f in files]))
        else:
            con.register(table, schema_of(cols).empty_table())
    return con
