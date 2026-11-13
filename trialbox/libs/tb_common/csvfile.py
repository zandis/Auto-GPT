"""A CSV file a person downloads (plan v7, wave 4: a byte order mark on every CSV).

Excel on a Japanese or Chinese Windows opens a CSV in the system's code page (CP932, CP950) unless the file starts
with the UTF-8 byte order mark; without it every non-ASCII cell is garbled, and saving the file back destroys it.
The mark is put on the file where it leaves the box for a person (a download), never on text one program hands
another (a JSON field, an API import), so a reader that does not expect it never meets it.

A reader of the box's own files opens them as ``utf-8-sig``, which reads both.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

BOM = "﻿"
_BOM_BYTES = BOM.encode("utf-8")


def for_spreadsheet(data: bytes | str) -> bytes:
    """The UTF-8 bytes of a CSV file with one byte order mark at its start. A file that has the mark is returned as
    it is; an empty file stays empty."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if not raw or raw.startswith(_BOM_BYTES):
        return raw
    return _BOM_BYTES + raw


def stream_for_spreadsheet(lines: Iterable[str]) -> Iterator[str]:
    """A CSV sent line by line: the mark before the first line (none for a file with no line)."""
    first = True
    for line in lines:
        if first and not line.startswith(BOM):
            yield BOM
        first = False
        yield line
