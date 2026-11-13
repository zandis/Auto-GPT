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
