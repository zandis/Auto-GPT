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
    assert e.value.code == "edc.chars"
    for cite in ({"text": f"ward {ch} sheet", "day": "2026-11-05"}, {"text": "ward sheet", "day": f"2026{ch}11"}):
        with pytest.raises(EdcError) as e:
            svc.decide(k.STUDY, d["comments"]["id"], "edit", value="fine", reason="typed", by="crc", citation=cite)
        assert e.value.code == "edc.chars"
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
    with pytest.raises(DataError) as e:  # the store's own door refuses it too, whichever path brought it
        dc.write("GZQO", "GZQO-0001", "", "ic_version", "v2\x0b1", "old", AT, "entry")
    assert e.value.code == "DATA-CHARS"
    with dc.db.transaction() as tx:  # a row from before the rule
        tx.execute("UPDATE value SET value = ? WHERE field = 'ic_version'", ("v2\x0b1",))
    with pytest.raises(DataError) as e:
        export.odm(dc, "GZQO", AT)
    assert e.value.code == "DATA-CHARS" and "ic_version" in e.value.message and "v2" not in e.value.message
    assert e.value.problems == [{"field": "ic_version", "code": "chars"}]
    with pytest.raises(DataError) as e:  # the workbook too (its library would raise an error of its own)
        export.xlsx(dc, "GZQO")
    assert e.value.code == "DATA-CHARS" and "v2" not in e.value.message
    assert "ic_version" in export.redcap_csv(dc, "GZQO")  # a CSV carries it


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


# ---------------------------------------------------------------- the adversarial review of PR #347 (2026-11-12)
def _all_signed(svc: Any, **sign: str) -> None:
    for r in _drafts(svc).values():
        if r["state"] == "drafted":
            svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", role="coordinator", meaning="transcribed", lang="en",
             seen=k.seen(svc), **{"printed_name": "Chen Mei", "meaning_text": "I checked each value.", **sign})  # fmt: skip


@pytest.mark.parametrize("field", ["printed_name", "meaning_text"])
@pytest.mark.parametrize("ch", ["\x0b", "\x00"])
def test_a_signature_whose_words_hold_such_a_character_is_refused(tmp_path: Path, field: str, ch: str) -> None:
    """H1: the printed name and the meaning's words are under the signature's hash and go into the ODM file; they
    were accepted and then exported with U+FFFD in their place."""
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    with pytest.raises(EdcError) as e:
        _all_signed(svc, **{field: f"Dr {ch} Lin"})
    assert e.value.code == "edc.chars"
    assert svc.store.signatures(k.STUDY) == []


@pytest.mark.parametrize("planted", [{"reason": "old \x0b reason"}, {"record": "S\x0b001"},
                                     {"decided_by": "crc\x0c"}, {"final_citation": {"kind": "manual", "day": "2026\x0b11"}}])  # fmt: skip
def test_a_signed_row_from_before_the_rule_is_never_exported_rewritten(
    tmp_path: Path, monkeypatch: Any, planted: dict[str, Any]
) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    _all_signed(svc)
    ET.fromstring(svc.export_odm(k.STUDY, "crc"))
    rows = svc.store.signed(k.STUDY)
    monkeypatch.setattr(svc.store, "signed", lambda rs: [{**rows[0], **planted}, *rows[1:]])
    with pytest.raises(EdcError) as e:
        svc.export_odm(k.STUDY, "crc")
    assert e.value.code == "edc.odm_chars" and e.value.problems == [{"item": rows[0]["item"], "code": "chars"}]  # type: ignore[attr-defined]


def test_a_signature_from_before_the_rule_is_never_exported_rewritten(tmp_path: Path, monkeypatch: Any) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    _all_signed(svc)
    sigs, rows = svc.store.signatures(k.STUDY), svc.store.signed(k.STUDY)
    monkeypatch.setattr(svc.store, "signed", lambda rs: rows)
    monkeypatch.setattr(svc.store, "signatures", lambda rs, record=None: [{**sigs[0], "printed_name": "Dr \x0b Lin"}])
    with pytest.raises(EdcError) as e:
        svc.export_odm(k.STUDY, "crc")
    assert e.value.code == "edc.odm_chars" and "Lin" not in e.value.message


class _Source:
    """A source that owns ``ic_version`` and pulls what the test gives it."""

    name = "redcap"

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.refused: list[dict[str, str]] = []

    def fields(self) -> list[str]:
        return ["ic_version"]

    def pull(self) -> list[Any]:
        return self.rows

    def push(self, rows: list[Any]) -> dict[str, str]:
        return {}


@pytest.mark.parametrize("ch", ["\x0b", "\x0c", "\x00", "\ud800"])
def test_a_value_read_back_from_a_source_is_refused_not_stored(dc: DataCore, ch: str) -> None:
    """H3: the read-back from REDCap stored whatever it pulled; a NUL was an uncaught database error."""
    from datacore.sync import Row, sync

    dc.set_owner("GZQO", "ic_version", "redcap")
    rows = [Row("GZQO-0001", "", {"ic_version": f"v2{ch}1"}), Row("GZQO-0002", "", {"ic_version": "v2.1"})]
    res = sync(dc, "GZQO", _Source(rows), "crc", AT, push=False)
    assert res.taken == 1 and dc.record("GZQO", "GZQO-0001") == {}
    assert dc.record("GZQO", "GZQO-0002") == {"ic_version": "v2.1"}
    assert res.refused == [
        {"at": "record GZQO-0001, field ic_version", "reason": "the value holds a control character"}
    ]
    assert odm_xsd.problems(export.odm(dc, "GZQO", AT)) == []


def test_a_record_key_with_such_a_character_is_refused_not_stored(dc: DataCore) -> None:
    """H2: records ``S\\x0b1`` and ``S\\x0c1`` were both stored and exported as one SubjectKey ``S\ufffd1``."""
    from datacore.sync import Row, sync

    dc.set_owner("GZQO", "ic_version", "redcap")
    rows = [Row("S\x0b1", "", {"ic_version": "v1"}), Row("S\x0c1", "", {"ic_version": "v2"})]
    res = sync(dc, "GZQO", _Source(rows), "crc", AT, push=False)
    assert res.taken == 0 and dc.records("GZQO") == [] and len(res.refused) == 2
    assert all("S" not in r["at"] for r in res.refused)  # the key is not repeated
    with dc.db.transaction() as tx:  # two such rows from before the rule
        for rec in ("S\x0b1", "S\x0c1"):
            tx.execute("INSERT INTO value (study, record, event, field, value, changed_by, changed_at) VALUES "
                       "('GZQO', ?, '', 'ic_version', 'v1', 'old', ?)", (rec, AT))  # fmt: skip
    with pytest.raises(DataError) as e:
        export.odm(dc, "GZQO", AT)
    assert e.value.code == "DATA-CHARS"


def test_a_deviation_reason_with_such_a_character_is_refused() -> None:
    import inspect

    from datacore import lifecycle

    src = inspect.getsource(lifecycle.Lifecycle)
    assert "XML_ILLEGAL.search(reason)" in src and 'LifeError("chars"' in src


def test_the_export_route_answers_the_refusal_as_the_other_routes_do() -> None:
    """H4: the route called the export with no handler, so the refusal that names the field was a 500."""
    import inspect

    from orchestrator import datacore_api

    src = inspect.getsource(datacore_api)
    at = src.index("body = export.export(svc.dc, rid, fmt, at)")
    assert "except DataError as exc" in src[at : at + 200] and "_fail(exc)" in src[at : at + 300]


def test_the_refusals_have_words_in_three_languages() -> None:
    from console import i18n_edc, i18n_entry, i18n_lifecycle_mediums

    text = "".join(inspect_source(m) for m in (i18n_edc, i18n_entry, i18n_lifecycle_mediums))
    for key in ("edc.problem.chars", "edc.err.edc.chars", "edc.err.edc.odm_chars", "dc.why.chars",
                "dc.err.DATA-CHARS", "life.why.chars"):  # fmt: skip
        assert text.count(f'"{key}"') == 3, key


def inspect_source(module: Any) -> str:
    import inspect

    return inspect.getsource(module)
