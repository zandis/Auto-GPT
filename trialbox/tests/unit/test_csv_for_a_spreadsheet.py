"""A CSV file a person downloads starts with the UTF-8 byte order mark (plan v7, wave 4): without it Excel on a
Japanese or Chinese Windows reads the file in the system's code page and every non-ASCII cell is garbled."""

from __future__ import annotations

import csv
import io

import pytest
from tb_common.csvfile import BOM, for_spreadsheet

NAME = "痛風"  # a two-character CJK word, written by code points


@pytest.mark.parametrize("given", [f"item,word\nmh,{NAME}\n", f"item,word\nmh,{NAME}\n".encode()])
def test_the_file_starts_with_one_mark_and_reads_back_the_same(given: str | bytes) -> None:
    data = for_spreadsheet(given)
    assert data.startswith(b"\xef\xbb\xbf") and not data[3:].startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert rows == [{"item": "mh", "word": NAME}]


def test_a_file_that_has_the_mark_gets_no_second_one() -> None:
    once = for_spreadsheet("a,b\n1,2\n")
    assert for_spreadsheet(once) == once and for_spreadsheet(BOM + "a,b\n1,2\n") == once


def test_an_empty_file_stays_empty() -> None:
    assert for_spreadsheet("") == b"" and for_spreadsheet(b"") == b""


def test_a_stream_gets_the_mark_before_its_first_line() -> None:
    from tb_common.csvfile import stream_for_spreadsheet

    assert "".join(stream_for_spreadsheet(iter(["a,b\n", "1,2\n"]))) == BOM + "a,b\n1,2\n"
    assert "".join(stream_for_spreadsheet(iter([]))) == ""


# ------------------------------------------------------------------------------------------------ the review
def test_a_stream_whose_first_chunks_are_empty_gets_one_mark() -> None:
    from tb_common.csvfile import stream_for_spreadsheet

    assert "".join(stream_for_spreadsheet(iter(["", BOM + "a,b\n", "1,2\n"]))) == BOM + "a,b\n1,2\n"
    assert "".join(stream_for_spreadsheet(iter(["", "", "a,b\n"]))) == BOM + "a,b\n"


def test_text_that_starts_with_several_marks_ends_with_one() -> None:
    assert for_spreadsheet(BOM + BOM + "a,b\n") == (BOM + "a,b\n").encode()


@pytest.mark.parametrize("raw", ["a,b\n".encode("utf-16"), f"a,{NAME}\n".encode("cp932")])
def test_bytes_that_are_not_utf8_are_left_as_they_are(raw: bytes) -> None:
    """The mark says "this file is UTF-8": it is never put on a file that is not."""
    assert for_spreadsheet(raw) == raw
