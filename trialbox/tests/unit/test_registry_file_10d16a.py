"""10D-16a (D-1373): a jRCT record from a person's own file, read as hostile input (``tb_common.registry_file``).

The hostile-file table: each file breaks one rule and is refused with that rule's code, before anything is kept;
a file with investigators' names, e-mail addresses and telephone numbers keeps none of them; the limits the messages
state are the module's. Synthetic values only (``example.invalid`` addresses, ``+1-555-01xx`` numbers, no real
study's number)."""

from __future__ import annotations

import pytest
from console import i18n_registry_record as words
from tb_common import registry_file as rf

pytestmark = [pytest.mark.nodb]

HEAD = "jRCT番号,研究の名称,対象疾患名,研究の進捗状況,試験のフェーズ,最終公表日"
ROW = "jRCT2031260901,A synthetic study of drug X,Condition A、Condition B,募集中,Phase 2,2026-10-01"
GOOD = f"{HEAD}\n{ROW}\n".encode()

#: the names, addresses and numbers a jRCT download may carry in its other columns (all synthetic)
PERSONS = ("Investigator Synthetic-One", "Contact Synthetic-Two", "pi-one@example.invalid", "+1-555-0100",
           "Board Member Synthetic-Three", "contact-two@example.invalid", "+1-555-0101")  # fmt: skip
WITH_NAMES = (
    "jRCT No.,Scientific Title,Condition,Recruitment Status,Phase,Last Update,"
    "Responsible investigator,Contact person,E-mail,Phone,Review board member,Contact e-mail,Contact phone,"
    "Inclusion Criteria\n"
    "jRCT2031260902,A synthetic trial,Condition C,Recruiting,Phase 3,2026-09-30,"
    f"{PERSONS[0]},{PERSONS[1]},{PERSONS[2]},{PERSONS[3]},{PERSONS[4]},{PERSONS[5]},{PERSONS[6]},"
    '"Adults; referred by Investigator Synthetic-One"\n'
).encode()


def test_a_good_file_keeps_the_six_fields() -> None:
    rec = rf.read_record(GOOD)
    assert rec.as_dict() == {"id": "jRCT2031260901", "title": "A synthetic study of drug X",
                             "condition": "Condition A; Condition B", "status": "募集中", "phase": "Phase 2",
                             "updated": "2026-10-01"}  # fmt: skip
    assert tuple(rec.as_dict()) == rf.KEPT


def test_shift_jis_and_a_bom_and_the_s_category_are_read() -> None:
    assert rf.read_record(GOOD.decode().encode("cp932")).status == "募集中"
    assert rf.read_record(b"\xef\xbb\xbf" + GOOD).id == "jRCT2031260901"
    s = f"{HEAD}\njRCTs031260903,T,,,,\n".encode()
    assert rf.read_record(s).id == "jRCTs031260903"


def test_a_file_with_investigator_names_stores_none() -> None:
    """The card's proof (plan 10 row 10D-16): a file with investigators' names stores none of them."""
    rec = rf.read_record(WITH_NAMES)
    kept = repr(rec.as_dict())
    assert rec.id == "jRCT2031260902" and rec.title == "A synthetic trial"
    for p in (*PERSONS, "Synthetic-One", "example.invalid", "555", "Adults"):
        assert p not in kept, p


def _csv(*rows: str) -> bytes:
    return ("\n".join(rows) + "\n").encode()


ENTITIES = (b'<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">'
            b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;">]>\n<lolz>&lol3;</lolz>\n')  # fmt: skip
EXTERNAL = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'

#: (case, file, the code it is refused with)
HOSTILE: tuple[tuple[str, bytes, str], ...] = (
    ("empty", b"", "empty"),
    ("oversize", GOOD + b"x" * rf.MAX_BYTES, "too_large"),
    ("oversize by one byte", b"a" * (rf.MAX_BYTES + 1), "too_large"),
    ("xlsx named .csv", b"PK\x03\x04" + b"\x00" * 64, "archive"),
    ("pdf", b"%PDF-1.7\n" + GOOD, "binary"),
    ("old excel", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + GOOD, "binary"),
    ("gzip", b"\x1f\x8b\x08\x00" + GOOD, "binary"),
    ("utf-16", "﻿".encode("utf-16-le") + GOOD.decode().encode("utf-16-le"), "binary"),
    ("a NUL byte", GOOD + b"\x00", "binary"),
    ("entity expansion", ENTITIES, "markup"),
    ("external entity", EXTERNAL, "markup"),
    ("html after blank lines", b"\n\n  <html><body>" + GOOD + b"</body></html>", "markup"),
    ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "markup"),
    ("deep json array", b"[" * 100_000 + b"]" * 100_000, "json"),
    ("json object", b'{"a": {"b": {"c": 1}}}', "json"),
    ("neither utf-8 nor shift_jis", b"\xff\xfe\xfd" * 3 + GOOD, "binary"),
    ("undecodable", GOOD + b"\x81\xff", "not_text"),
    ("a control character", GOOD.replace(b"Phase 2", b"Phase\x072"), "not_text"),
    ("a C1 control character", GOOD.replace(b"Phase 2", "Phase\x852".encode()), "not_text"),
    ("an unclosed quote", _csv(HEAD, 'jRCT2031260901,"A synthetic study,x,y,z,w'), "bad_csv"),
    ("text after a closing quote", _csv(HEAD, 'jRCT2031260901,"A" b,x,y,z,w'), "bad_csv"),
    ("too many columns", _csv(HEAD + "," + ",".join(f"c{i}" for i in range(rf.MAX_COLUMNS)), ROW), "too_wide"),
    ("a cell too long", _csv(HEAD + ",Other", ROW + "," + "x" * (rf.CELL_MAX + 1)), "cell_long"),
    ("no jRCT header", _csv("a,b,c", "1,2,3"), "no_header"),
    ("only blank lines", b"\n\n\r\n", "no_header"),
    ("a title column twice", _csv(HEAD + ",研究の名称", ROW + ",other title"), "header_twice"),
    ("a row wider than the header", _csv(HEAD, ROW + ",extra"), "row_wide"),
    ("the header alone", _csv(HEAD), "no_record"),
    ("two records", _csv(HEAD, ROW, ROW.replace("0901", "0904")), "many_records"),
    ("the same record twice", _csv(HEAD, ROW, ROW), "many_records"),
    ("a short number", _csv(HEAD, ROW.replace("jRCT2031260901", "jRCT123")), "bad_id"),
    ("two numbers in one cell", _csv(HEAD, ROW.replace("jRCT2031260901", '"jRCT2031260901 jRCT2031260905"')),
     "bad_id"),
    ("another registry's number", _csv(HEAD, ROW.replace("jRCT2031260901", "UMIN000012345")), "bad_id"),
    ("a number with text around it", _csv(HEAD, ROW.replace("jRCT2031260901", "see jRCT2031260901")), "bad_id"),
    ("a path as the number", _csv(HEAD, ROW.replace("jRCT2031260901", "../../etc/passwd")), "bad_id"),
    ("a title column under two names", _csv(HEAD + ",Public Title", ROW + ",Investigator Synthetic-One"),
     "header_twice"),
    ("two number columns", _csv(HEAD + ",Trial ID", ROW + ",jRCT2031260905"), "header_twice"),
    ("two number columns, the same number", _csv(HEAD + ",jRCT No.", ROW + ",jRCT2031260901"), "header_twice"),
    ("a cell over python's csv limit", _csv(HEAD + ",Other", ROW + "," + "x" * 150_000), "cell_long"),
    ("a direction override in the title", _csv(HEAD, ROW.replace("drug X", "drug \u202eX")), "invisible"),
    ("a zero-width space in the status", _csv(HEAD, ROW.replace("募集中", "募集\u200b中")), "invisible"),
    ("an isolate in the phase", _csv(HEAD, ROW.replace("Phase 2", "\u2066Phase 2\u2069")), "invisible"),
    ("a formula as the title", _csv(HEAD, ROW.replace("A synthetic study of drug X", "=HYPERLINK(1)")), "formula"),
    ("a plus as the status", _csv(HEAD, ROW.replace("募集中", "+1")), "formula"),
    ("an at sign as the phase", _csv(HEAD, ROW.replace("Phase 2", "@SUM(1)")), "formula"),
    ("a minus as the conditions", _csv(HEAD, ROW.replace("Condition A、Condition B", "-2+3")), "formula"),
    ("a title too long", _csv(HEAD, ROW.replace("A synthetic study of drug X", "T" * 1001)), "field_long"),
    ("a status too long", _csv(HEAD, ROW.replace("募集中", "S" * 201)), "field_long"),
)  # fmt: skip


@pytest.mark.parametrize(("case", "data", "code"), HOSTILE, ids=[c for c, _, _ in HOSTILE])
def test_the_hostile_file_table(case: str, data: bytes, code: str) -> None:
    with pytest.raises(rf.Refused) as got:
        rf.read_record(data)
    assert got.value.code == code, (case, got.value)
    for cat in (words.EN, words.JA, words.ZH):  # each refusal has its true message in the three languages
        assert cat[f"rrec.err.{code}"]


def test_markup_inside_a_field_is_kept_as_text_never_parsed() -> None:
    """Markup in a kept field is text: the parser neither runs nor removes it; the page escapes it (console test)."""
    rec = rf.read_record(_csv(HEAD, ROW.replace("A synthetic study of drug X", '"<script>alert(1)</script>"')))
    assert rec.title == "<script>alert(1)</script>"


def test_every_code_has_its_message_in_three_languages() -> None:
    for code in (*rf.CODES, "no_file", "other_study", "api_type", "bad_form", "store"):
        for cat in (words.EN, words.JA, words.ZH):
            assert cat[f"rrec.err.{code}"], code
    assert set(words.EN) == set(words.JA) == set(words.ZH)


def test_the_messages_state_the_modules_limits() -> None:
    en = words.EN
    assert rf.MAX_BYTES == 256 * 1024 and "256 KB" in en["rrec.err.too_large"] and "256 KB" in en["rrec.file.hint"]
    assert f"{rf.MAX_COLUMNS}" in en["rrec.err.too_wide"]
    assert f"{rf.CELL_MAX:,}" in en["rrec.err.cell_long"]
    assert rf.FIELD_MAX["title"] == rf.FIELD_MAX["condition"] == 1000 and "1,000" in en["rrec.err.field_long"]
    assert rf.FIELD_MAX["status"] == rf.FIELD_MAX["phase"] == 200 and "at most 200" in en["rrec.err.field_long"]
    assert rf.FIELD_MAX["updated"] == 40 and "at most 40" in en["rrec.err.field_long"]
    for cat in (words.JA, words.ZH):
        assert "256 KB" in cat["rrec.err.too_large"] and "32,000" in cat["rrec.err.cell_long"]
        assert all(n in cat["rrec.err.field_long"] for n in ("1,000", "200", "40"))


def test_the_parser_opens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No socket, no file, no process: the parser reads the bytes it is given."""
    import builtins
    import socket
    import subprocess

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the parser opened something")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert rf.read_record(WITH_NAMES).id == "jRCT2031260902"
    for _case, data, _code in HOSTILE:
        with pytest.raises(rf.Refused):
            rf.read_record(data)


def test_a_dash_alone_is_kept_and_markup_is_not_a_formula() -> None:
    """A dash alone means "none" and is kept as written; only a value a spreadsheet would read as a formula fails."""
    rec = rf.read_record(_csv(HEAD, ROW.replace("Phase 2", "-")))
    assert rec.phase == "-"
