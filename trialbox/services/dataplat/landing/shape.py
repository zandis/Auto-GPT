"""Object shape at L0: rows, columns with inferred physical type and nullability, schema fingerprint (§5.8.2).

The fingerprint is computed from the batch itself, never from the contract:
``sha256(JCS([[name, physical_type, nullable] for each column sorted by name]))``. For arrays of strings and booleans,
canonical ``json.dumps`` (sorted keys, no spaces, UTF-8) is byte-identical to RFC 8785 JCS.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from tb_contracts.landing import ColumnShape

from dataplat.common import canonical, sha256_hex

Row = dict[str, Any]

_INT = re.compile(r"^-?\d+$")
_DEC = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")

# generality order used to combine per-value types into a column type
_JOIN: dict[frozenset[str], str] = {
    frozenset({"integer", "decimal"}): "decimal",
    frozenset({"date", "timestamp"}): "timestamp",
}


def value_type(value: str) -> str:
    """Physical type of one CSV cell: ``integer``, ``decimal``, ``date``, ``timestamp`` or ``string``."""
    if _INT.match(value):
        return "integer"
    if _DEC.match(value):
        return "decimal"
    if _DATE.match(value):
        return "date"
    if _TS.match(value):
        return "timestamp"
    return "string"


def join_types(a: str | None, b: str) -> str:
    if a is None or a == b:
        return b
    return _JOIN.get(frozenset({a, b}), "string")


def json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def fingerprint(columns: Iterable[ColumnShape]) -> str:
    cols = sorted([c.name, c.type, c.nullable] for c in columns)
    return sha256_hex(canonical(cols).encode("utf-8"))


def detect_encoding(data: bytes) -> str:
    """``utf-8-sig`` (BOM), ``utf-8``, else ``cp950`` (Big5, common in Taiwanese exports), else ``latin-1``."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in ("utf-8", "cp950"):
        try:
            data.decode(enc)
        except UnicodeDecodeError:
            continue
        return enc
    return "latin-1"


def object_format(path: Path | str) -> str:
    name = str(path)
    if name.endswith((".ndjson", ".ndjson.gz", ".jsonl")):
        return "ndjson"
    if name.endswith(".csv"):
        return "csv"
    raise ValueError(f"unsupported landing object {name!r} (csv or ndjson[.gz])")


def table_name(path: Path | str) -> str:
    name = Path(path).name
    for suffix in (".ndjson.gz", ".ndjson", ".jsonl", ".csv"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _text(data: bytes, path: Path | str) -> bytes:
    return gzip.decompress(data) if str(path).endswith(".gz") else data


def iter_rows(data: bytes, path: Path | str, encoding: str | None = None) -> Iterator[Row]:
    """Rows of a landed object: CSV rows as ``{column: str}``, NDJSON lines as parsed JSON objects."""
    raw = _text(data, path)
    if object_format(path) == "csv":
        enc = encoding or detect_encoding(raw)
        reader = csv.DictReader(io.StringIO(raw.decode(enc), newline=""))
        for row in reader:
            yield {k: (v if v is not None else "") for k, v in row.items() if k is not None}
        return
    for line in raw.decode(encoding or "utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield obj


def csv_header(data: bytes, encoding: str) -> list[str]:
    first = data.decode(encoding).splitlines()[:1]
    return next(csv.reader(first), []) if first else []


def shape(data: bytes, path: Path | str) -> tuple[int, str, list[ColumnShape]]:
    """``(rows, encoding, columns)`` of one object, from the object alone."""
    raw = _text(data, path)
    if object_format(path) == "csv":
        enc = detect_encoding(raw)
        header = csv_header(raw, enc)
        types: dict[str, str | None] = dict.fromkeys(header)
        nulls: dict[str, bool] = dict.fromkeys(header, False)
        n = 0
        for row in iter_rows(data, path, enc):
            n += 1
            for col in header:
                v = row.get(col, "")
                if v == "":
                    nulls[col] = True
                else:
                    types[col] = join_types(types[col], value_type(v))
        cols = [ColumnShape(name=c, type=types[c] or "null", nullable=nulls[c] or n == 0) for c in header]
        return n, enc, cols
    jtypes: dict[str, str | None] = {}
    present: dict[str, int] = {}
    n = 0
    for obj in iter_rows(data, path):
        n += 1
        for k, v in obj.items():
            t = json_type(v)
            present[k] = present.get(k, 0) + (t != "null")
            if t != "null":
                prev = jtypes.get(k)
                jtypes[k] = t if prev in (None, t) else "mixed"
            else:
                jtypes.setdefault(k, None)
    cols = [ColumnShape(name=k, type=jtypes[k] or "null", nullable=present[k] < n) for k in sorted(jtypes)]
    return n, "utf-8", cols
