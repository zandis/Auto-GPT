"""``csv`` source: one ``<table>.csv`` (header row) per source table in a directory.

Character sets (T-615b, DATA-003). A HIS export may be UTF-8, Big5 (CP950) or Shift_JIS (CP932). Every file is read
through the one detector of D-215 (:mod:`tb_common.encoding`), with the site's declared encoding
(``settings.data_source.encoding``) as the first candidate. A file the detector refuses, or that is not a readable
CSV, is **quarantined**: it is moved to ``<directory>/quarantine/`` (left in place when the folder is read-only), the
table yields no rows, and :meth:`CsvSource.quarantine_reason` says why, with the line. The adapter holds the night and
reads the other tables; nothing is guessed and no U+FFFD reaches a record. A file cut short is not a readable CSV
either (F-2): one that does not end with a line end, ends inside a quoted field, starts with a blank line, or has a
row with more or fewer fields than its header, is quarantined with the line, never served with a value cut or a
column taken as empty.

Delta (T-615b, DATA-008). ``--since`` filters on the table's change-time column (the mapping's ``delta:``, canonical
``updated_at``). A row whose change time is empty is kept, and so is every row of a file that has no such column: a
row read twice is merged by its key, a row skipped is a correction lost.
"""

from __future__ import annotations

import codecs
import csv
import logging
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path

from tb_common import encoding

from adapter.sources.base import Row, after, change_time_is_date

log = logging.getLogger("adapter")

QUARANTINE_DIR = "quarantine"
# settings.data_source.encoding -> the detector's candidate name (Big5 tries CP950 itself; Shift_JIS is read as CP932)
_DECLARED = {"big5": "big5", "cp950": "big5", "shift_jis": "cp932", "sjis": "cp932", "cp932": "cp932"}


def _utf8_throughout(path: Path) -> str | None:
    """``utf-8-sig`` or ``utf-8`` when the file is valid UTF-8 from end to end and holds no replacement character
    (U+FFFD, a file damaged before it came: :func:`tb_common.encoding.file_codec` refuses it with its line); None
    otherwise. Read in chunks, never held whole (T-692)."""
    dec = codecs.getincrementaldecoder("utf-8")()
    with path.open("rb") as fh:
        head = fh.read(len(codecs.BOM_UTF8))
        bom = head == codecs.BOM_UTF8
        chunk = b"" if bom else head
        try:
            while True:
                if "\ufffd" in dec.decode(chunk):
                    return None
                chunk = fh.read(1 << 16)
                if not chunk:
                    dec.decode(b"", final=True)
                    break
        except UnicodeDecodeError:
            return None
    return "utf-8-sig" if bom else "utf-8"


def candidates(declared: str | None) -> tuple[str, ...]:
    """The detector's legacy candidates: the site's declared character set first, then the usual ones. UTF-8 is
    always tried by the detector itself."""
    first = _DECLARED.get((declared or "").strip().lower().replace("-", "_"))
    rest = tuple(c for c in encoding.LEGACY if c != first)
    return (first, *rest) if first else rest


def _ends_with_line_end(path: Path) -> bool:
    """Whether the file's last byte ends a line (every character set read here writes CR and LF as ASCII)."""
    with path.open("rb") as fh:
        if fh.seek(0, 2) == 0:
            return True
        fh.seek(-1, 2)
        return fh.read(1) in (b"\n", b"\r")


def _not_whole(path: Path, codec: str) -> str | None:
    """F-2 (H34-01, -03, -04): why the file is not a whole CSV, or None. A file that does not end with a line end is
    cut: a writer ends every row with one, and a row cut anywhere (inside a field, after a separator, after half of an
    escaped quote) can have the header's width, so only the missing line end tells it. Parsed strictly (a quoted field
    the file ends inside is an error, not a field), the first line is the header (a blank one would make every row's
    columns nameless), and every row has the header's fields: a row short or long is a row cut or split, never one
    whose missing column is taken as empty. Two shapes of a real export are no fault: header columns with no name at
    its end may be missing from a row, and a row may carry empty fields past the header's end (a trailing separator),
as long as every row of the file has the width of the first.
    Read as a stream, no row kept (T-692); the reason holds the line, never a cell's text."""
    if not _ends_with_line_end(path):
        return ": the file does not end with a line end, so its last row may be cut"
    width = named = first = 0
    try:
        with path.open(encoding=codec, newline="") as fh:
            reader = csv.reader(fh, strict=True)
            for rec in reader:
                if not width:
                    if not rec:
                        return f": line {reader.line_num} is blank where the header must be"
                    width = len(rec)
                    named = width
                    while named > 1 and not rec[named - 1].strip():
                        named -= 1
                    continue
                if not rec:  # a blank line is no row (as DictReader reads it)
                    continue
                n = len(rec)
                fits = named <= n <= width or (n > width and not any(f.strip() for f in rec[width:]))
                # every row of one export has one width: a row that differs from the first is shifted, even when its
                # extra field is empty (a decimal comma in a row whose last field is empty)
                if fits and n == (first or n):
                    first = n
                    continue
                return f": line {reader.line_num} has {n} fields where the header has {width}" + (
                    f" and the first row {first}" if fits else ""
                )
    except csv.Error as exc:
        return f" ({exc}, line {reader.line_num})"
    return None


class CsvSource:
    name = "csv"

    def __init__(self, directory: Path, declared_encoding: str | None = None) -> None:
        if not directory.is_dir():
            raise FileNotFoundError(f"csv source directory not found: {directory}")
        self.directory = directory
        self.candidates: Sequence[str] = candidates(declared_encoding)
        # D-805: the site says its export is UTF-8. Valid UTF-8 is then read as UTF-8, never weighed against Shift_JIS
        # or Big5 (an English note with one "β" or "®" was too short to tell); other bytes are weighed as before
        self.declared_utf8 = (declared_encoding or "").strip().lower().replace("_", "-") in ("utf-8", "utf8")
        self.encodings: dict[str, str] = {}  # source_name -> codec read
        self._quarantined: dict[str, str] = {}  # source_name -> why (no cell text, only the code and the line)
        self._not_a_date: dict[str, int] = {}  # F14 (D-810): source_name -> rows whose change time is not a date

    def has_table(self, source_name: str) -> bool:
        """Whether the export holds the table's file at all (T-611: a missing file is not an empty table)."""
        return source_name in self._quarantined or (self.directory / f"{source_name}.csv").is_file()

    def change_time_not_a_date(self, source_name: str) -> int:
        """Rows of ``source_name`` read on this delta night because their change time is not a date (F14, D-810)."""
        return self._not_a_date.get(source_name, 0)

    def quarantine_reason(self, source_name: str) -> str | None:
        """Why ``source_name`` was quarantined on this read, or None."""
        return self._quarantined.get(source_name)

    def _quarantine(self, path: Path, source_name: str, why: str) -> None:
        dest = self.directory / QUARANTINE_DIR / path.name
        try:
            dest.parent.mkdir(exist_ok=True)
            shutil.move(str(path), str(dest))
            where = f"moved to {QUARANTINE_DIR}/{path.name}"
        except OSError:  # a read-only export share: the file stays, the night is held all the same
            where = "left in place (the folder is read-only)"
        self._quarantined[source_name] = f"{path.name} quarantined: {why}; {where}"
        log.warning("csv source: %s", self._quarantined[source_name])

    def _codec(self, path: Path, source_name: str) -> str | None:
        """T-692 (D-473): the file's character set, and a first pass that parses it whole without keeping a row, so a
        file that is not a readable CSV is quarantined before any of its rows is given (as when it was read whole)."""
        try:
            codec = (_utf8_throughout(path) if self.declared_utf8 else None) or encoding.file_codec(
                path, self.candidates
            )
        except encoding.EncodingRefused as exc:
            self._quarantine(path, source_name, str(exc))
            return None
        why = _not_whole(path, codec)
        if why is not None:
            self._quarantine(path, source_name, f"not a readable CSV{why}")
            return None
        self.encodings[source_name] = codec
        return codec

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        """The table's rows one at a time, read from the file as they are asked for (T-692: never the whole table)."""
        path = self.directory / f"{source_name}.csv"
        if not path.exists():
            return
        codec = self._codec(path, source_name)
        if codec is None:
            return
        with path.open(encoding=codec, newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            col = delta_column if since and delta_column and delta_column in fields else None
            for raw in reader:
                row = dict(raw)
                if col is not None and str(row.get(col) or "").strip():
                    if not change_time_is_date(row.get(col)):
                        # F14 (D-810): a change time that is not a date never decides: read, as an empty one is
                        self._not_a_date[source_name] = self._not_a_date.get(source_name, 0) + 1
                    elif not after(row.get(col), since):
                        continue
                yield row
