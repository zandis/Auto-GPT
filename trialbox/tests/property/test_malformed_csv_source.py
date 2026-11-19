"""Card 10G-43 (OT-5): the CSV source on malformed files (``adapter.sources.csv.source.CsvSource``).

A file is read, or **refused by quarantine** (moved aside, no rows, ``quarantine_reason`` says why; T-615b): no
exception leaves ``rows``. Inputs: bytes built from CSV pieces (quotes, separators, line ends, NUL), UTF-8, Shift_JIS
and Big5 bytes, a BOM, and the change-time column with values that are and are not dates, for each declared
character set the settings allow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.malformed_kit import MAX_INPUT, SETTINGS, returns_or_refuses

from hypothesis import example, given
from hypothesis import strategies as st

from adapter.sources.csv.source import CsvSource

_PIECES = [
    b"id,updated_at,name\r\n", b"id,updated_at\n", b",", b",,", b"\"", b"\"\"", b"\"a,b\"", b"\r\n", b"\n", b"\r",
    b"\x00", b"1", b"2026-10-01", b"2026-13-45", b"20261001", b"not a date", b"\xef\xbb\xbf", b"\xe5\xb1\xb1\xe7\x94\xb0",
    b"\x8eR\x93c", b"\xa4s", b"\xff", b"\x80", b"\xe3\x81", b"\xef\xbf\xbd", b"\t", b";", b" ",
]  # fmt: skip
files = st.one_of(
    st.binary(max_size=256),
    st.lists(st.sampled_from(_PIECES) | st.binary(max_size=3), max_size=60).map(b"".join),
).filter(lambda b: len(b) <= MAX_INPUT)
declared = st.sampled_from([None, "", "utf-8", "UTF_8", "big5", "cp950", "shift_jis", "sjis", "cp932", "latin-1"])
since = st.sampled_from([None, "", "2026-01-01", "2026-10-01 12:00:00", "garbage"])


def _read(data: bytes, enc: str | None, delta: str | None, when: str | None) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "lab.csv").write_bytes(data)
        src = CsvSource(Path(d), enc)
        rows = list(src.rows("lab", "lab", delta, when))
        assert not (rows and src.quarantine_reason("lab")), "rows given from a quarantined file"
        src.has_table("lab")
        src.change_time_not_a_date("lab")
        return rows


@SETTINGS
@given(files, declared, st.sampled_from([None, "updated_at", "missing"]), since)
@example(b"", None, None, None)
@example(b"id\r\n\"open", None, None, None)
@example(b"id,updated_at\r\n1,2026-13-45\r\n", "utf-8", "updated_at", "2026-01-01")
@example(b"id\r\n" + b"a" * 131073 + b"\r\n", None, None, None)
@example(b"id\r\n\x00\r\n", "big5", None, None)
@example(b"id\r\na\rb\r\n", None, None, None)
def test_csv_source_reads_or_quarantines(data: bytes, enc: str | None, delta: str | None, when: str | None) -> None:
    returns_or_refuses(lambda: _read(data, enc, delta, when), ())
