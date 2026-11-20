"""H10G39-01 (Low, lane H): the terminology installer's XML guard read raw bytes, so a release written in UTF-16 or
UTF-32 (with or without a byte order mark) carried ``<!DOCTYPE`` and ``<!ENTITY`` past it and ElementTree expanded the
entity. Now the encoding is decided first (mark, first bytes, declaration), what cannot be decided is refused, the
guard reads the decoded text, and the parser itself refuses a DTD or an entity. Synthetic documents only."""

from __future__ import annotations

import codecs
import zipfile
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed

from tests.unit.test_term1_icd10cm_names import INDEX, TABULAR

ATTACK = '<!DOCTYPE x [<!ENTITY e "boom">]><x>&e;</x>'
DECL = '<?xml version="1.0" encoding="{}"?>'

# (label, python codec that writes the bytes, encoding named in the declaration or None)
ENCODED = [
    ("utf-8", "utf-8", None),
    ("utf-8 declared", "utf-8", "UTF-8"),
    ("utf-8 with a mark", "utf-8-sig", "UTF-8"),
    ("utf-16 le with a mark", "utf-16-le", "UTF-16"),  # the mark is written below
    ("utf-16 be with a mark", "utf-16-be", "UTF-16"),
    ("utf-16 le, no mark", "utf-16-le", "UTF-16"),
    ("utf-16 be, no mark", "utf-16-be", "UTF-16"),
    ("utf-32 le with a mark", "utf-32-le", "UTF-32"),
    ("utf-32 be with a mark", "utf-32-be", "UTF-32"),
    ("utf-32 le, no mark", "utf-32-le", "UTF-32"),
    ("utf-32 be, no mark", "utf-32-be", "UTF-32"),
]
MARKS = {"utf-16-le": codecs.BOM_UTF16_LE, "utf-16-be": codecs.BOM_UTF16_BE, "utf-32-le": codecs.BOM_UTF32_LE,
         "utf-32-be": codecs.BOM_UTF32_BE}  # fmt: skip


def _bytes(label: str, codec: str, declared: str | None, doc: str) -> bytes:
    """``doc`` (which may carry its own ``<?xml?>`` line: it is replaced) written in ``codec``."""
    body = doc.split("?>", 1)[1] if doc.startswith("<?xml") else doc
    text = (DECL.format(declared) if declared else "") + body
    data = text.encode(codec)
    return MARKS[codec] + data if "with a mark" in label and codec in MARKS else data


def _zip(tmp: Path, tabular: bytes, index: bytes) -> Path:
    z = tmp / "codes.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Table and Index/icd10cm_tabular_2026.xml", tabular)
        f.writestr("Table and Index/icd10cm_index_2026.xml", index)
    return z


@pytest.mark.parametrize(("label", "codec", "declared"), ENCODED, ids=[e[0] for e in ENCODED])
def test_the_attack_is_refused_in_every_encoding(tmp_path: Path, label: str, codec: str, declared: str | None) -> None:
    data = _bytes(label, codec, declared, ATTACK)
    if codec not in ("utf-8", "utf-8-sig"):
        assert b"<!DOCTYPE" not in data and b"<!ENTITY" not in data  # what the old raw-byte guard looked for
    with pytest.raises(ValueError, match="DTD or an entity"):
        installed._xml(data)
    with pytest.raises(ValueError, match="DTD or an entity"):
        installed.install_icd10cm(_zip(tmp_path, data, INDEX.encode()), tmp_path / "out", "2026")
    assert not (tmp_path / "out" / "manifest.json").exists()


@pytest.mark.parametrize(("label", "codec", "declared"), ENCODED, ids=[e[0] for e in ENCODED])
def test_a_genuine_release_is_read_alike_in_every_encoding(
    tmp_path: Path, label: str, codec: str, declared: str | None
) -> None:
    want = (installed.icd10cm_blocks(TABULAR.encode()), installed.icd10cm_index(INDEX.encode()))
    assert want[0] and want[1]
    tab, idx = _bytes(label, codec, declared, TABULAR), _bytes(label, codec, declared, INDEX)
    assert (installed.icd10cm_blocks(tab), installed.icd10cm_index(idx)) == want
    got = installed.install_icd10cm(_zip(tmp_path, tab, idx), tmp_path / "out", "2026")
    assert got and (tmp_path / "out" / "manifest.json").exists()


@pytest.mark.parametrize("declared", ["US-ASCII", "ISO-8859-1"])
def test_the_one_byte_encodings_the_parser_reads_are_read(declared: str) -> None:
    data = _bytes("", "latin-1", declared, TABULAR)
    assert installed.icd10cm_blocks(data) == installed.icd10cm_blocks(TABULAR.encode())


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (TABULAR.split("?>", 1)[1].encode("utf-16-le"), "NUL"),  # UTF-16 with neither a mark nor a declaration
        (ATTACK.encode("utf-16-be"), "NUL"),
        (ATTACK.encode("utf-32-le"), "DTD or an entity"),  # UTF-32 is told by its first bytes alone (appendix F)
        ((DECL.format("Shift_JIS") + ATTACK).encode(), "declares the encoding"),  # not one the installer reads
        ((DECL.format("UTF-7") + "+ADw-!DOCTYPE x+AD4-<x/>").encode(), "declares the encoding"),
        ((DECL.format("UTF-16") + "<x/>").encode(), "declares the encoding"),  # says UTF-16, written in UTF-8
        (codecs.BOM_UTF16_LE + (DECL.format("UTF-8") + "<x/>").encode("utf-16-le"), "declares"),  # the reverse
        (codecs.BOM_UTF8 + (DECL.format("ISO-8859-1") + "<x/>").encode(), "declares"),
        (b"<x>\xff\xfe</x>", "not utf-8"),  # not UTF-8, and nothing says otherwise
        (codecs.BOM_UTF16_LE + b"<\x00x\x00\x00\xd8>\x00", "not utf-16-le"),  # a lone surrogate
    ],
    ids=["utf16-bare", "utf16be-bare-attack", "utf32le-bare-attack-is-read-then-refused", "shift-jis", "utf-7", "utf16-says-utf8-is",
         "utf8-says-utf16-is", "mark-and-latin1", "bad-utf8", "bad-utf16"],
)  # fmt: skip
def test_what_cannot_be_decided_is_refused(data: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        installed._xml(data)


def test_the_parser_refuses_a_dtd_even_past_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second wall: with the text guard switched off the parser itself refuses the declaration and expands
    nothing."""
    monkeypatch.setattr(installed, "declares_dtd", lambda text: False)
    for doc in (ATTACK, '<!DOCTYPE x SYSTEM "http://example.invalid/x.dtd"><x/>', "<!DOCTYPE x><x/>"):
        with pytest.raises(ValueError, match="DTD or an entity"):
            installed._xml(doc.encode())


def test_the_tree_is_the_one_elementtree_built() -> None:
    import xml.etree.ElementTree as ET

    a, b = installed._xml(TABULAR.encode()), ET.fromstring(TABULAR)
    assert ET.tostring(a) == ET.tostring(b)
