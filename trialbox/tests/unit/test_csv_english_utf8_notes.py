"""Blocker 12 (lane G's VALIDATION dry run, 2026-11-14): an English UTF-8 note file with no byte order mark and a few
non-ASCII characters was quarantined, "the character set cannot be told for certain".

D-599 reads valid UTF-8 without weighing only when it holds three usual non-ASCII characters or every one stands in a
fixed western place. One curly apostrophe (``Crohn’s``), one ``β blocker`` or one ``Humira®`` in a day's notes was
neither, and the file was weighed against Shift_JIS and Big5 and refused. Two changes (D-805):

* a curly apostrophe or quote beside a Latin letter is a western place: its bytes are the garble ``窶冱`` / ``鈥檚``
  in Shift_JIS and GB18030, unreadable in Big5, EUC-JP and EUC-KR;
* a site that declares its export UTF-8 (``settings.data_source.encoding: utf-8``) has its valid UTF-8 read as UTF-8:
  the declaration answers what the bytes cannot. Bytes that are not valid UTF-8 are weighed as before.

Synthetic text only."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.csv.source import CsvSource
from tb_common import encoding

HEADER = "note_no,mrn,enc_no,note_datetime,note_type,text\n"
PLAIN = "".join(
    f"{i},S{i:05d},E{i:05d},2026-11-14 09:00,progress,Seen in clinic. Plan unchanged.\r\n" for i in range(40)
)


def _notes(tmp_path: Path, line: str) -> Path:
    d = tmp_path / "site"
    d.mkdir(parents=True)
    (d / "note.csv").write_bytes((HEADER + PLAIN + f"99,S00099,E00099,2026-11-14 10:00,progress,{line}\r\n").encode())
    return d


def _read(d: Path, declared: str | None) -> tuple[list[dict[str, str]], str | None]:
    src = CsvSource(d, declared)
    rows = list(src.rows("note", "note", None, None) or [])
    return rows, src.quarantine_reason("note")


@pytest.mark.parametrize("line", ["History of Crohn’s disease.", "The patient’s mother attended.", "He doesn’t smoke.",
                                  "Reports feeling “much better” today."])  # fmt: skip
def test_a_curly_apostrophe_or_quote_in_an_english_note_is_read_as_utf8(tmp_path: Path, line: str) -> None:
    rows, why = _read(_notes(tmp_path, line), None)
    assert why is None and rows[-1]["text"] == line


@pytest.mark.parametrize("line", ["Remains on a β blocker.", "TNF α inhibitor stopped.", "Humira® 40 mg weekly.",
                                  "Head of bed at 30°.", "Take ½ tablet daily.", "Ca²⁺ 2.31 mmol/L.", "κ light chains raised.",
                                  "Café au lait spots."])  # fmt: skip
def test_a_site_that_declares_utf8_has_its_valid_utf8_notes_read(tmp_path: Path, line: str) -> None:
    """Without the declaration one of these alone is too little to tell from Shift_JIS or Big5 (D-599 refuses it, and
    still does); with it the file is read, never weighed."""
    rows, why = _read(_notes(tmp_path, line), "utf-8")
    assert why is None and rows[-1]["text"] == line
    assert _read(_notes(tmp_path / "undeclared", line), None)[1] is not None  # D-599 unchanged for an undeclared site


def test_a_declared_utf8_site_still_has_a_file_that_is_not_utf8_weighed_never_guessed(tmp_path: Path) -> None:
    """The declaration settles valid UTF-8 only. A Big5 file at a site that says UTF-8 is read as Big5 as before, and
    a damaged UTF-8 file is still quarantined with its line."""
    d = tmp_path / "site"
    d.mkdir()
    (d / "note.csv").write_bytes(
        ("note_no,text\n" + "".join(f"{i},病人今日回診，血壓穩定。\n" for i in range(20))).encode("big5")
    )
    rows, why = _read(d, "utf-8")
    assert why is None and rows[0]["text"] == "病人今日回診，血壓穩定。"
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "note.csv").write_bytes(b"note_no,text\n1,Seen in clinic\n2,Plan \xef\xbf\xbd unchanged\n")
    rows, why = _read(bad, "utf-8")
    assert rows == [] and why is not None and "line 3" in why


def test_the_detector_reads_the_apostrophe_and_a_japanese_note_beside_latin_letters_stays_shift_jis() -> None:
    """The other side. The apostrophe's bytes in Shift_JIS are 窶冱, a garble nobody writes (the same bytes, so
    "Crohn窶冱" written in Shift_JIS is read as "Crohn’s": there is no text to lose). A real Japanese note with Latin
    letters and kanji side by side is read as Shift_JIS, as before."""
    data = (HEADER + PLAIN + "99,S00099,E00099,2026-11-14 10:00,progress,Crohn’s disease\n").encode()
    assert encoding.detect(data)[0] == "utf-8"
    note = "".join(f"{i},Crohn病の既往あり。CRP 0.3 mg/dL、経過良好。\n" for i in range(20))
    assert encoding.detect(("note_no,text\n" + note).encode("cp932"))[0] == "cp932"
