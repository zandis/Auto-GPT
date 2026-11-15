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
    """The file is not whole: cut off (an interrupted write) or not in this format; never read as a short list."""


def is_excluded(filename: str) -> bool:
    return filename.startswith("excluded_") and filename.endswith((".json", ".jsonl"))


def newest(filenames: Iterable[str]) -> str | None:
    """Of a run's outputs, its excluded patients: the lines when it has them, else the old document."""
    names = [f for f in filenames if is_excluded(f)]
    return next((f for f in names if f.endswith(".jsonl")), names[0] if names else None)


def _line(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"


HEADER_KEYS = ("kind", "format", "rows")  # the format's own keys: a header field of these names would be overwritten


def write_jsonl(header: dict[str, Any], rows: Iterable[dict[str, Any]]) -> bytes:
    if clash := [k for k in HEADER_KEYS if k in header]:
        raise ValueError(f"the excluded list's header may not carry {', '.join(clash)}: the format's own keys")
    out = [_line({"kind": "header", "format": FORMAT, **header})]
    n = 0
    for r in rows:
        if "kind" in r:
            raise ValueError("an excluded row may not carry kind: the format's own key")
        out.append(_line({**r, "kind": "row"}))
        n += 1
    out.append(_line({"kind": "end", "rows": n}))
    return b"".join(out)


def _lines(data: bytes) -> Iterator[dict[str, Any]]:
    start = 0
    while start < len(data):
        end = data.find(b"\n", start)
        end = len(data) if end < 0 else end
        if end > start:
            try:
                obj = json.loads(data[start:end])
            except ValueError as e:  # JSONDecodeError and bad UTF-8: a line cut in two
                raise Incomplete(f"the excluded list has a broken line ({e}): it was cut off") from None
            if not isinstance(obj, dict):
                raise Incomplete("the excluded list has a line that is not an object")
            yield obj
        start = end + 1


def _walk(data: bytes) -> Iterator[dict[str, Any]]:
    """The header, then the rows, in order. :class:`Incomplete` unless the file is whole: the header first and once,
    rows only, then the end line with the rows' count, and nothing after it."""
    n, ended, headed = 0, False, False
    for obj in _lines(data):
        kind = obj.get("kind")
        if ended:
            raise Incomplete("the excluded list goes on after its end line")
        if kind == "header":
            if headed or n:
                raise Incomplete("the excluded list has a second header")
            headed = True
        elif not headed:
            raise Incomplete("the excluded list does not start with its header")
        elif kind == "row":
            n += 1
        elif kind == "end":
            count = obj.get("rows")
            if type(count) is not int or count != n:
                raise Incomplete(f"the excluded list says {count!r} rows and holds {n}: it was cut off")
            ended = True
            continue
        else:
            raise Incomplete(f"the excluded list has a line of kind {kind!r}")
        yield obj
    if not ended:
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
