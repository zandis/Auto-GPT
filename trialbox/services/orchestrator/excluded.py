"""NEW-B-48 (D-749): the excluded patients of a SCREEN run, one line each (T-694 part 5, F-36).

``excluded_<ruleset>_v<version>.jsonl``: UTF-8, one JSON object per line, keys sorted. The first line is the header
(``{"kind": "header", "format": 1, ...}``: the run's fields that the old document had at its top), then one line per
excluded patient (``{"kind": "row", "pid", "criteria", "actions"}``: the old document's ``rows`` entries), then the
end (``{"kind": "end", "rows": <count>}``). A file without its end was cut off: it is said, never read as a short
list. A run written before this change has only ``excluded_<ruleset>_v<version>.json``; the readers here take the
lines when a run has them, else the old document."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

FORMAT = 1


class Incomplete(ValueError):
    """The file has no end line: it was cut off (an interrupted write)."""


def is_excluded(filename: str) -> bool:
    return filename.startswith("excluded_") and filename.endswith((".json", ".jsonl"))


def newest(filenames: Iterable[str]) -> str | None:
    """Of a run's outputs, its excluded patients: the lines when it has them, else the old document."""
    names = [f for f in filenames if is_excluded(f)]
    return next((f for f in names if f.endswith(".jsonl")), names[0] if names else None)


def _line(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"


def write_jsonl(header: dict[str, Any], rows: Iterable[dict[str, Any]]) -> bytes:
    out = [_line({"kind": "header", "format": FORMAT, **header})]
    n = 0
    for r in rows:
        out.append(_line({"kind": "row", **r}))
        n += 1
    out.append(_line({"kind": "end", "rows": n}))
    return b"".join(out)


def _lines(data: bytes) -> Iterator[dict[str, Any]]:
    start = 0
    while start < len(data):
        end = data.find(b"\n", start)
        end = len(data) if end < 0 else end
        if end > start:
            yield json.loads(data[start:end])
        start = end + 1


def _walk(data: bytes) -> Iterator[dict[str, Any]]:
    """The lines in order; :class:`Incomplete` when the end line is missing or its count is not the rows'."""
    n = 0
    for obj in _lines(data):
        if obj.get("kind") == "end":
            if int(obj.get("rows", -1)) != n:
                raise Incomplete(f"the excluded list says {obj.get('rows')} rows and holds {n}: it was cut off")
            return
        if obj.get("kind") == "row":
            n += 1
        yield obj
    raise Incomplete("the excluded list has no end line: it was cut off")


def read(data: bytes, filename: str) -> dict[str, Any]:
    """The run's excluded patients as the old document (its header fields and ``rows``)."""
    if not filename.endswith(".jsonl"):
        return dict(json.loads(data))
    doc: dict[str, Any] = {"rows": []}
    for obj in _walk(data):
        kind = obj.pop("kind", None)
        if kind == "header":
            obj.pop("format", None)
            doc.update(obj)
        elif kind == "row":
            doc["rows"].append(obj)
    return doc


def pids(data: bytes, filename: str) -> set[str]:
    """Only the patient ids, one line at a time (the rows' evidence is never kept)."""
    if not filename.endswith(".jsonl"):
        return {str(r.get("pid")) for r in json.loads(data).get("rows") or []}
    return {str(obj.get("pid")) for obj in _walk(data) if obj.get("kind") == "row"}
