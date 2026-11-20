"""Card 10B-21 (D-1261): every use of the MEDIS disease-name master, against the release's real shapes.

* The ICD-10 is written as the release writes it, without the dot (``E119``): the box writes it ``E11.9`` before
  comparing it with the ICD-10-CM list (site set-up's suggestion, the OMOP link).
* Site set-up's suggestion (D-135): a deleted entry is never suggested; one with a successor suggests the successor
  and says so; an entry without an ICD-10, or whose ICD-10 the ICD-10-CM list lacks, suggests nothing (D-130),
  never another table's guess for the master's own code; a local name is matched to the 病名表記 and to the index
  table's spellings of a disease (never of a modifier); a name of two diseases gives nothing; the 複数分類コード is
  never the entry's code.
* The JP Core check: a code the loaded release marks deleted is a warning.

The rows are invented (tests/medis_fixture.py has the same made-up codes)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from adapter import licensed
from adapter.licensed import ICD10_WHO
from sitesetup import mapping
from sitesetup import medis_master as mm
from tb_common.icd10_who import dotted

from tests import medis_fixture as fx

DX = "urn:hospital:dx-code"


def _tables(index: bool = True, dots: bool = False) -> dict[str, dict[str, dict[str, Any]]]:
    """The invented release as ``licensed.tables()`` gives it: by exchange code (the first row of a shared code is
    the one kept on master; ZA06 is on two rows with one ICD-10)."""
    medis: dict[str, dict[str, Any]] = {}
    for change, no, name, _kana, ex, icd, _multi, succ in fx.DISEASES:
        extra = {"management_no": no, "change": change, **({"successor": succ} if succ else {})}
        medis.setdefault(ex, {"display": name, "target_system": ICD10_WHO if icd else "",
                              "target_code": dotted(icd) if dots else icd, "extra": json.dumps(extra)})  # fmt: skip
    out: dict[str, dict[str, dict[str, Any]]] = {"medis": medis}
    if index:
        out["medis_index"] = {
            f"{i}": {"display": term, "target_code": code, "extra": json.dumps({"kind": kind, "term": term})}
            for i, (term, code, kind, _kk, _syn) in enumerate(fx.INDEX)
        }
    return out


@pytest.fixture
def master() -> mm.Master:
    m = mm.rows(_tables())
    assert m is not None
    return m


def test_the_who_code_is_written_with_its_dot() -> None:
    assert [dotted(c) for c in ("E119", "e119", "I10", "E11.9", " K529 ", "M1097", "C50.911", "")] == [
        "E11.9", "E11.9", "I10", "E11.9", "K52.9", "M10.97", "C50.911", ""]  # fmt: skip


def test_a_current_entry_suggests_its_icd10cm_code(master: mm.Master) -> None:
    got = mm.by_code(master, "za01")
    assert got == {"system": mapping.ICD10CM, "code": "E11.9", "display": "テスト病甲", "method": "licensed",
                   "confidence": "1.00"}  # fmt: skip
    assert mm.by_code(master, "ZA02")["code"] == "I10"  # a three-character code: as it is


def test_a_deleted_entry_suggests_its_successor_and_says_so(master: mm.Master) -> None:
    got = mm.by_code(master, "ZA04")
    assert got["code"] == "K52.9" and got["display"] == "新テスト症"
    assert got["method"] == "licensed_successor" and got["replaced"] == "99000004"


def test_a_deleted_entry_without_a_successor_is_never_suggested(master: mm.Master) -> None:
    assert mm.by_code(master, "ZA11") == {}
    assert mm.by_name(master, "廃止テスト病") == {}


def test_a_successor_loop_or_a_missing_successor_gives_nothing() -> None:
    t = _tables(index=False)
    t["medis"]["ZA04"]["extra"] = json.dumps({"management_no": "99000004", "change": "1", "successor": "99000099"})
    m = mm.rows(t)
    assert m is not None and mm.by_code(m, "ZA04") == {}
    t["medis"]["ZA04"]["extra"] = json.dumps({"management_no": "99000004", "change": "1", "successor": "99000004"})
    m = mm.rows(t)
    assert m is not None and mm.by_code(m, "ZA04") == {}


@pytest.mark.parametrize(("code", "why"), [("ZA08", "no ICD-10 in the master"), ("ZA10", "U04.9: not in ICD-10-CM"),
                                           ("ZA09", "E14.2: WHO only (the 複数分類コード N08.3 is never taken)")])  # fmt: skip
def test_no_icd10cm_code_means_no_suggestion(master: mm.Master, code: str, why: str) -> None:
    assert mm.by_code(master, code) == {}, why


def test_a_local_name_is_matched_to_the_name_and_the_index(master: mm.Master) -> None:
    assert mm.by_name(master, "テスト病甲")["code"] == "E11.9"
    assert mm.by_name(master, " テスト病Ａ ")["code"] == "E11.9"  # the index's spelling, NFKC, blanks removed
    assert mm.by_name(master, "てすとびょうこう")["code"] == "E11.9"
    assert mm.by_name(master, "旧テスト症の別名")["code"] == "K52.9"  # a deleted entry's spelling: its successor
    assert mm.by_name(master, "ダミーがわ") == {}  # a modifier's spelling never names a disease
    assert mm.by_name(master, "テスト病丙")["code"] == "M19.9"  # the row kept of a shared exchange code


def test_a_modifiers_spelling_never_names_a_disease() -> None:
    """病名修飾語区分 2 (a modifier's spelling): even with a 対応用語コード equal to a disease's management number."""
    t = _tables(index=False)
    t["medis_index"] = {"m": {"display": "テスト修飾語", "target_code": "99000001",
                              "extra": json.dumps({"kind": "2", "term": "テスト修飾語"})}}  # fmt: skip
    m = mm.rows(t)
    assert m is not None and mm.by_name(m, "テスト修飾語") == {}
    t["medis_index"]["m"]["extra"] = json.dumps({"kind": "1", "term": "テスト修飾語"})
    m = mm.rows(t)
    assert m is not None and mm.by_name(m, "テスト修飾語")["code"] == "E11.9"  # the same row as a disease's: read


def test_a_name_of_two_diseases_gives_nothing() -> None:
    t = _tables(index=False)
    t["medis"]["ZA02"] = {**t["medis"]["ZA02"], "display": "テスト病甲"}  # the same name, another ICD-10
    m = mm.rows(t)
    assert m is not None and mm.by_name(m, "テスト病甲") == {}


def test_suggest_reads_the_master_first_and_never_guesses_past_it(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = _tables()
    monkeypatch.setattr(licensed, "tables", lambda url=None, cached=False: tables)
    assert mapping.suggest("condition", DX, "ZA01")["code"] == "E11.9"
    assert mapping.suggest("condition", DX, "ZA04")["method"] == "licensed_successor"
    assert mapping.suggest("condition", DX, "ZA10", "テスト病丁") == {}  # the master's code: no other guess
    assert mapping.suggest("condition", DX, "LOCAL-1", "テスト病Ａ")["code"] == "E11.9"  # a local code by its name


def test_without_the_master_suggest_is_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(licensed, "tables", lambda url=None, cached=False: {k: {} for k in licensed.KINDS})
    assert mapping.suggest("condition", DX, "E11.9")["method"] == "same"
    assert mapping.suggest("condition", DX, "ZA01", "テスト病甲") == {}


def test_the_check_warns_on_a_deleted_code() -> None:
    from adapter.validate.jpcore import JpCoreValidator

    v = JpCoreValidator(_tables(index=False))
    res = {"resourceType": "Condition", "id": "c1", "code": {"coding": [
        {"system": licensed.MEDIS_BYOMEI, "code": "ZA11"}, {"system": licensed.MEDIS_BYOMEI, "code": "ZA01"}]}}  # fmt: skip
    texts = [i.text for i in v.check(res).issues]
    assert sum("deleted in the loaded" in t for t in texts) == 1
    assert not any("not in the loaded" in t for t in texts)
