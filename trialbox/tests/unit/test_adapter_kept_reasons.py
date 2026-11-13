"""D-682: what the SS-MIX2 reader and the share report keep of an error is their own sentence or the error's type,
never the text of an error nobody wrote, and never a field of the message that did not read. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import Ssmix2Source

from tools.ssmix2_export import hard_cases

VALUE = "YAMADA^HANAKO 19600101"  # stands for a field of a damaged message that slid into MSH-18's place


def _msh(charset: str) -> bytes:
    fields = [
        "MSH",
        "^~\\&",
        "S",
        "F",
        "R",
        "F",
        "20261001",
        "",
        "ADT^A08",
        "1",
        "P",
        "2.5",
        "",
        "",
        "",
        "",
        "",
        charset,
    ]
    return "|".join(fields).encode("ascii") + b"\rPID|||1\r\x80\xff\xfe\r"


@pytest.mark.parametrize("charset", ["~ISO IR87", "UNICODE UTF-8", "ISO IR6~ISO IR87", ""])
def test_an_unreadable_message_names_its_character_set_when_it_is_one(charset: str) -> None:
    with pytest.raises(hl7.Undecodable) as e:
        hl7.decode_bytes(_msh(charset))
    assert f"MSH-18 {charset!r}" in str(e.value)


@pytest.mark.parametrize("field", [VALUE, "x" * 300, "ISO IR87~" + VALUE])
def test_an_unreadable_message_never_quotes_a_field_that_is_not_a_character_set(field: str) -> None:
    with pytest.raises(hl7.Undecodable) as e:
        hl7.decode_bytes(_msh(field))
    text = str(e.value)
    assert "YAMADA" not in text and "19600101" not in text and "xxx" not in text
    assert "MSH-18 names no character set of HL7 table 0211" in text


def test_a_file_that_cannot_be_opened_is_quarantined_by_the_errors_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "storage"
    hard_cases(root)
    src = Ssmix2Source(root, licensed={}, quarantine_max_pct=100.0)

    def denied(data: bytes) -> Any:
        raise PermissionError(13, "Permission denied", "/mnt/his/storage/990/000/99000001/-/ADT-00/secret")

    monkeypatch.setattr(hl7, "decode_bytes", denied)
    assert list(src.rows("patient", "patient", None, None)) == []
    assert src.quarantined
    for _typ, _where, why in src.quarantined:
        assert why == "not an HL7 message: PermissionError"  # the type, not the error's text (it holds a path)


def test_a_message_without_msh_is_quarantined_by_the_readers_own_sentence(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    hard_cases(root)
    victim = next(p for p in sorted(root.rglob("*")) if p.is_file() and "ADT-00" in p.name)
    victim.write_bytes(b"PID|||99000001||" + VALUE.encode() + b"\r")
    src = Ssmix2Source(root, licensed={}, quarantine_max_pct=100.0)
    list(src.rows("patient", "patient", None, None))
    whys = [why for _t, where, why in src.quarantined if where.endswith(victim.name)]
    assert whys == ["not an HL7 message: ValueError"]


def test_the_share_reports_refusal_reason_holds_only_the_engines_words() -> None:
    """Kept as it is (D-588): the mapping's refusal is reduced to the words the engine itself writes; the first
    word that is not one of them (a value, quoted or not) ends it. Any other error is counted by its type."""
    from adapter.mapping.sharereport import UNWORDED, map_rows, scrub_reason

    assert VALUE.split("^", maxsplit=1)[0] not in scrub_reason(f"invalid date value {VALUE!r} in column birth")
    assert scrub_reason(VALUE) == UNWORDED

    class Broken:
        def map_table(self, table: str, rows: Any) -> Any:
            raise KeyError(VALUE)

    _, rejected = map_rows(Broken(), "patient", [{"a": "1"}])  # type: ignore[arg-type]
    assert dict(rejected) == {"(KeyError)": 1}


def test_a_lookup_that_failed_in_the_extended_reader_is_not_quoted(monkeypatch: pytest.MonkeyPatch) -> None:
    def lost(data: bytes) -> str:
        raise KeyError(VALUE)

    monkeypatch.setattr(hl7, "_iso2022", lost)
    with pytest.raises(hl7.Undecodable) as e:
        hl7.decode_bytes(b"MSH|^~\\&|\r\x1b$B\x29\x21\x1b(B\r")
    assert str(e.value) == "ISO-2022-JP: a character outside the code tables"


def test_the_omop_stores_refusals_name_no_record_so_the_dual_write_may_keep_them() -> None:
    """``adapter.dual_write`` keeps an ``OmopError``'s text as the night's ``omop.error`` (D-669 left it so). It
    is safe to keep whole since D-681: no refusal of the store is built from a record's id."""
    import ast

    root = Path(__file__).resolve().parents[2] / "services/omop"
    bad: list[str] = []
    for f in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Raise) and node.exc is not None and "OmopError" in ast.dump(node.exc):
                text = ast.unparse(node.exc)
                if any(w in text for w in ("srcid", "source_record_id", "get('id')", 'get("id")', "{key}")):
                    bad.append(f"{f.name}:{node.lineno}")
    assert bad == []
