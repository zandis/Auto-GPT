"""EDC-010 (D-581): a value with a character XML 1.0 does not allow is refused at entry, and no ODM file is written
that an XML reader cannot open.

Before: ``ok \\x0b vertical tab`` (text pasted from a hospital note) was accepted, signed and sent, and both ODM
writers then wrote a file lxml refuses ("invalid character"); a NUL raised an uncaught database error.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from datacore import builtin, export
from datacore.forms import Field, problem, read_dictionary, reason
from datacore.store import DataCore, DataError
from datacore.sync import save_form
from edc.store import EdcError

from tests import edc_kit as k
from tests import odm_xsd

AT = "2026-11-08T10:00:00+09:00"
BAD = ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1f", "￾", "￿", "\ud800"]
FINE = ["line one\nline two", "tab\there", "carriage\r\nreturn", "痛風 ｶﾞｳﾄ 髙", "a < b & c > \"d\" ]]>", "\U0001f600",
        "", "�", "\x7f", "\x85"]  # fmt: skip


def _field(kind: str) -> Field:
    return next(f for f in k_fields() if f.kind == kind)


def k_fields() -> list[Field]:
    return read_dictionary(k.dictionary_csv())


@pytest.mark.parametrize("ch", BAD)
@pytest.mark.parametrize("kind", ["text", "notes"])
def test_a_character_xml_does_not_allow_is_a_problem(kind: str, ch: str) -> None:
    f = _field(kind)
    for value in (f"ok {ch} x", ch, f"x{ch}"):
        p = problem(f, value)
        assert p == {"field": f.name, "code": "chars"}
        assert value not in reason(p, value)  # the message names the field, never the value


@pytest.mark.parametrize("value", FINE)
def test_every_other_character_is_still_a_value(value: str) -> None:
    assert problem(_field("notes"), value) is None


def test_a_number_or_a_choice_with_such_a_character_is_refused_for_the_character() -> None:
    by_name = {f.name: f for f in k_fields()}
    assert problem(by_name["weight"], "72\x0b")["code"] == "chars"  # type: ignore[index]
    assert problem(by_name["sex"], "1\x00")["code"] == "chars"  # type: ignore[index]


# ----------------------------------------------------------------------------------------------- the pre-fill
def _drafts(svc: Any) -> dict[str, dict[str, Any]]:
    return {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}


@pytest.mark.parametrize("ch", ["\x0b", "\x0c", "￾", "\x00"])
def test_the_prefill_refuses_the_value_at_entry(tmp_path: Path, ch: str) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _drafts(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["comments"]["id"], "edit", value=f"ok {ch} vertical tab", reason="note text", by="crc",
                   citation={"text": "ward sheet", "day": "2026-11-05"})  # fmt: skip
    assert e.value.code == "edc.invalid" and e.value.problems == [{"field": "comments", "code": "chars"}]  # type: ignore[attr-defined]
    with pytest.raises(EdcError) as e:  # the reason for change is written into the trail and the ODM file
        svc.decide(k.STUDY, d["comments"]["id"], "edit", value="fine", reason=f"pasted {ch} reason", by="crc",
                   citation={"text": "ward sheet", "day": "2026-11-05"})  # fmt: skip
    assert e.value.code == "edc.invalid"
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["comments"]["id"], "edit", value="fine", reason="typed", by="crc",
                   citation={"text": f"ward {ch} sheet", "day": "2026-11-05"})  # fmt: skip
    assert e.value.code == "edc.invalid"
    out = svc.decide(k.STUDY, d["comments"]["id"], "edit", value="fine\nsecond line", reason="typed", by="crc",
                     citation={"text": "ward sheet", "day": "2026-11-05"})  # fmt: skip
    assert out["fate"] == "edited"


# ----------------------------------------------------------------------------------------------- the data core
@pytest.fixture
def dc() -> Iterator[DataCore]:
    core = DataCore()
    for q in builtin.builtin_questionnaires("GZQO"):
        core.put_form("GZQO", q, builtin.ORIGIN, AT)
    yield core
    core.close()


@pytest.mark.parametrize("ch", ["\x0b", "\x0c", "￾", "\x00"])
def test_the_data_core_refuses_the_value_at_entry(dc: DataCore, ch: str) -> None:
    with pytest.raises(DataError) as e:
        save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent",
                  {"ic_date": "2026-11-02", "ic_version": f"v2{ch}1", "ic_copy": "1", "ic_reconsent": "0"}, "crc", AT)  # fmt: skip
    assert e.value.problems == [{"field": "ic_version", "code": "chars"}]
    assert dc.history("GZQO") == []


def test_a_stored_value_from_before_the_rule_stops_the_export_and_names_the_field(dc: DataCore) -> None:
    save_form(dc, "GZQO", "GZQO-0001", "", "tb_consent",
              {"ic_date": "2026-11-02", "ic_version": "v2.1", "ic_copy": "1", "ic_reconsent": "0"}, "crc", AT)  # fmt: skip
    assert odm_xsd.problems(export.odm(dc, "GZQO", AT)) == []
    dc.write("GZQO", "GZQO-0001", "", "ic_version", "v2\x0b1", "old", AT, "entry")  # the store's own door: no check
    with pytest.raises(DataError) as e:
        export.odm(dc, "GZQO", AT)
    assert e.value.code == "DATA-CHARS" and "ic_version" in e.value.message and "v2" not in e.value.message
    assert e.value.problems == [{"field": "ic_version", "code": "chars"}]


def test_text_that_is_not_a_value_is_written_with_the_replacement_character() -> None:
    from datacore.forms import xml_text  # new with this card

    assert xml_text("label \x0b with ￾") == "label � with �"
    assert xml_text("fine\n\t") == "fine\n\t"
    root = ET.Element("a", {"b": xml_text("x\x0cy")})
    ET.fromstring(ET.tostring(root, encoding="unicode"))  # well-formed


def test_a_signed_value_from_before_the_rule_stops_the_prefill_export(tmp_path: Path, monkeypatch: Any) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    d = _drafts(svc)
    old = {**d["comments"], "final": "seen \x0b in clinic", "pid": k.PID}
    monkeypatch.setattr(svc.store, "signed", lambda rs: [old])
    with pytest.raises(EdcError) as e:
        svc.export_odm(k.STUDY, "crc")
    assert e.value.code == "edc.odm_chars" and "comments" in e.value.message and "clinic" not in e.value.message


def test_a_drafted_value_with_such_a_character_is_unknown_not_drafted() -> None:
    from edc.mapping import ItemMap
    from edc.prefill import _value

    f = _field("notes")
    m = ItemMap(item=f.name, source="note")
    assert _value(m, f, "tophus \x0c right ear", {"kind": "note"}, "2026-11-01").state == "unknown"
    assert _value(m, f, "tophus, right ear", {"kind": "note"}, "2026-11-01").state == "drafted"
