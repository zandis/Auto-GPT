"""Card 10B-22 (D-1261): every use of the MEDIS disease-name master, against the release's real shapes and the
stored shape of #1238's loader (one concept per exchange code, every row in ``extra["rows"]``, the index asked one
term at a time).

* The ICD-10 as the release writes it (``A99``, ``A999``, ``A9999``, ``A999`` and a lower-case letter, ``A99-9``,
  empty) is written for comparison by one shared function (``tb_common.icd10_who.comparable``), used by site
  set-up's suggestion, the JP Core check and the OMOP link.
* Site set-up's suggestion (D-135): a deleted entry is never suggested; one with a successor suggests the successor
  and says so; no ICD-10, or one the ICD-10-CM list lacks, suggests nothing (D-130), never another table's guess;
  the 病名表記 first, then the index by its groups (0, 1, a variant form, 2 "related"); 8, 9, ``0000`` and a
  modifier's spelling never; a 採択区分 3 name shows its level 1 name; hints for a dental, Kampo or usually-modified
  entry; the 複数分類コード is never the entry's code.
* The JP Core check: a code the loaded release marks deleted is a warning.

The rows are invented (tests/medis_fixture.py)."""

from __future__ import annotations

import json

import pytest
from adapter import licensed
from sitesetup import mapping
from sitesetup import medis_master as mm
from tb_common.icd10_who import comparable

from tests import medis_fixture as fx

DX = "urn:hospital:dx-code"


@pytest.fixture
def master() -> mm.Master:
    m = mm.rows({"medis": fx.concepts()})
    assert m is not None
    return m


@pytest.mark.parametrize(
    ("given", "want"),
    [("I10", "I10"), ("E119", "E11.9"), ("M1097", "M10.97"), ("E109a", "E10.9"), ("E109d", "E10.9"),
     ("A15-9", ""), ("", ""), ("E11.9", "E11.9"), (" K529 ", "K52.9"), ("E1", ""), ("e119", ""), ("E109ab", ""),
     ("N083", "N08.3")],
    ids=["A99", "A999", "A9999", "A999a", "A999d", "A99-9", "empty", "dotted", "blanks", "short", "lower",
         "two letters", "multi-class"],
)  # fmt: skip
def test_one_function_writes_every_shape_for_comparison(given: str, want: str) -> None:
    assert comparable(given) == want


def test_a_current_entry_suggests_its_icd10cm_code(master: mm.Master) -> None:
    assert mm.by_code(master, "za01") == {"system": mapping.ICD10CM, "code": "E11.9", "display": "テスト病甲",
                                          "method": "licensed", "confidence": "1.00"}  # fmt: skip
    assert mm.by_code(master, "ZA12")["code"] == "E10.9"  # the sub-classification letter left out for comparison


def test_a_deleted_entry_suggests_its_successor_and_says_so(master: mm.Master) -> None:
    got = mm.by_code(master, "ZA04")
    assert got["code"] == "K52.9" and got["display"] == "新テスト症"
    assert got["method"] == "licensed_successor" and got["replaced"] == "99000004"


def test_a_deleted_entry_without_a_successor_is_never_suggested(master: mm.Master) -> None:
    assert mm.by_code(master, "ZA11") == {}
    assert mm.by_name(master, "廃止テスト病") == {}


def test_a_successor_loop_or_a_missing_successor_gives_nothing() -> None:
    for succ in ("99000099", "99000004"):
        t = fx.concepts()
        extra = json.loads(t["ZA04"]["extra"])
        extra["rows"][0]["successor"] = succ
        t["ZA04"]["extra"] = json.dumps(extra)
        m = mm.rows({"medis": t})
        assert m is not None and mm.by_code(m, "ZA04") == {}, succ


@pytest.mark.parametrize(("code", "why"), [("ZA08", "no ICD-10 in the master"), ("ZA10", "U04.9: not in ICD-10-CM"),
                                           ("ZA09", "E14.2: WHO only (the 複数分類コード N08.3 is never taken)"),
                                           ("ZA13", "A15-9: a hyphen inside the value gives no code")])  # fmt: skip
def test_no_icd10cm_code_means_no_suggestion(master: mm.Master, code: str, why: str) -> None:
    assert mm.by_code(master, code) == {}, why


def test_rows_of_one_code_that_disagree_on_icd10_give_nothing() -> None:
    t = fx.concepts()
    t["ZA06"]["target_code"] = ""  # #1238 empties the code's ICD-10 when its current rows disagree
    m = mm.rows({"medis": t})
    assert m is not None and mm.by_code(m, "ZA06") == {}


def test_the_name_comes_first_then_the_index_by_its_groups(master: mm.Master) -> None:
    look = fx.lookup_term
    assert mm.by_name(master, "テスト病甲", look)["method"] == "licensed"
    assert mm.by_name(master, " ﾃｽﾄﾋﾞﾖｳｺｳ ", look)["code"] == "E11.9"  # NFKC, upper case, blanks removed: group 0
    assert mm.by_name(master, "テスト病a", look)["code"] == "E11.9"  # group 1, the hospital's lower case read upper
    assert mm.by_name(master, "テスト病甲型", look)["code"] == "E11.9"  # a variant form
    assert mm.by_name(master, "旧テスト症ノ別名", look)["method"] == "licensed_successor"
    related = mm.by_name(master, "テスト関連病", look)
    assert related["method"] == "licensed_related" and float(related["confidence"]) < 1
    for never in ("テスト非推奨名", "テスト検索語", "テスト廃語", "ダミーガワ"):  # 8, 9, 0000, a modifier's spelling
        assert mm.by_name(master, never, look) == {}, never


def test_a_synonym_shows_the_name_it_borrows_and_the_hints_are_said(master: mm.Master) -> None:
    syn = mm.by_name(master, "テスト病丙型")
    assert syn["method"] == "licensed_synonym" and syn["display"] == "テスト病丙"
    assert mm.by_code(master, "ZA02")["method"] == "licensed_with_modifier"
    assert mm.by_code(master, "ZA03")["method"] == "licensed_dental"
    assert mm.by_code(master, "ZA14")["method"] == "licensed_kampo"  # a hint, never a filter: still suggested


def test_a_modifiers_spelling_never_names_a_disease(master: mm.Master) -> None:
    rows = [{"term": "テスト修飾語", "code": "ZA01", "target_kind": "2", "synonym": "0", "variant": "9"}]
    assert mm.by_name(master, "テスト修飾語", lambda t: rows) == {}
    rows[0]["target_kind"] = "1"
    assert mm.by_name(master, "テスト修飾語", lambda t: rows)["code"] == "E11.9"  # the same row as a disease's: read


def test_a_name_of_two_diseases_gives_nothing() -> None:
    t = fx.concepts()
    extra = json.loads(t["ZA02"]["extra"])
    extra["rows"][0]["name"] = "テスト病甲"  # the same name, another ICD-10
    t["ZA02"]["extra"] = json.dumps(extra)
    m = mm.rows({"medis": t})
    assert m is not None and mm.by_name(m, "テスト病甲") == {}


def test_suggest_reads_the_master_first_and_never_guesses_past_it(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = {"medis": fx.concepts()}
    monkeypatch.setattr(licensed, "tables", lambda url=None, cached=False: tables)
    monkeypatch.setattr(mapping, "_medis_index", fx.lookup_term)
    assert mapping.suggest("condition", DX, "ZA01")["code"] == "E11.9"
    assert mapping.suggest("condition", DX, "ZA04")["method"] == "licensed_successor"
    assert mapping.suggest("condition", DX, "ZA10", "テスト病丁") == {}  # the master's code: no other guess
    assert mapping.suggest("condition", DX, "LOCAL-1", "テスト病Ａ")["code"] == "E11.9"  # a local code by its name


def test_without_the_master_suggest_is_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(licensed, "tables", lambda url=None, cached=False: {k: {} for k in licensed.KINDS})
    assert mapping.suggest("condition", DX, "E11.9")["method"] == "same"
    assert mapping.suggest("condition", DX, "ZA01", "テスト病甲") == {}


def test_the_check_warns_on_a_deleted_code_and_names_the_masters_form() -> None:
    from adapter.validate.jpcore import JpCoreValidator

    v = JpCoreValidator({"medis": fx.concepts()})
    res = {"resourceType": "Condition", "id": "c1", "code": {"coding": [
        {"system": licensed.MEDIS_BYOMEI, "code": "ZA11"}, {"system": licensed.MEDIS_BYOMEI, "code": "ZA01"},
        {"system": licensed.ICD10_WHO, "code": "E109a"}]}}  # fmt: skip
    texts = [i.text for i in v.check(res).issues]
    assert sum("deleted in the loaded" in x for x in texts) == 1
    assert not any("not in the loaded" in x for x in texts)
    assert any("the MEDIS master's form of E10.9" in x for x in texts)


def test_the_page_words_name_every_method() -> None:
    import console.medis_page  # noqa: F401 - its words join the catalogue
    from console.i18n import CATALOGUES

    for method in ("licensed_successor", "licensed_related", "licensed_synonym", "licensed_with_modifier",
                   "licensed_kampo", "licensed_dental"):  # fmt: skip
        for lang in ("en", "ja", "zh-TW"):
            assert f"site.codes.method.{method}" in CATALOGUES[lang], (method, lang)
