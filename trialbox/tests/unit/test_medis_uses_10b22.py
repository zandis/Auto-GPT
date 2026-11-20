"""Card 10B-22 (D-1261): every use of the MEDIS disease-name master, against the release's real shapes and the
stored shape of #1238's loader (one concept per exchange code, every row in ``extra["rows"]``, the index asked one
term at a time).

* The ICD-10 as the release writes it (``A99``, ``A999``, ``A9999``, ``A999`` and a lower-case letter, ``A99-9``,
  empty) is written for comparison by one shared function (``tb_common.icd10_who.comparable``), used by site
  set-up's suggestion, the JP Core check and the OMOP link.
* Site set-up's suggestion (D-135), as lane J ruled it: the master's code is WHO ICD-10, never taken for its
  ICD-10-CM namesake; the target is the same-numbered billable ICD-10-CM code, said as one to be checked, never a
  category with codes below it (H1), every confidence at most 0.80; a deleted entry is never suggested; one with a
  successor suggests the successor and says so (followed up to its bound); no ICD-10, or one the ICD-10-CM list
  lacks, suggests nothing (D-130), never another table's guess; the 病名表記 first, then the index by its groups (0,
  1, a variant form, 2 "related", which wins over a variant mark: H2); 8, 9, ``0000`` and a modifier's spelling
  never; several diseases all offered, ranked; a 採択区分 3 name shows its level 1 name; hints for a dental, Kampo
  or usually-modified entry; the 複数分類コード is never the entry's code; a local name that names neither the code
  nor its index terms is said (M6); only at a site whose layer uses the master, in the main workspace (M4), by the
  display only (M5).
* The JP Core check: a code the loaded release marks deleted is a warning; with no release loaded, said once (M9).

The rows are invented (tests/medis_fixture.py)."""

from __future__ import annotations

import itertools
import json
from typing import Any

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


CM = "http://hl7.org/fhir/sid/icd-10-cm"


# ------------------------------------------------------------------ the target: WHO ICD-10, never its CM namesake (H1)
def test_a_current_entry_suggests_its_same_numbered_billable_icd10cm_code(master: mm.Master) -> None:
    got = mm.by_code(master, "za01")
    assert {k: got[k] for k in ("system", "code", "display", "method", "confidence", "who", "family")} == {
        "system": CM, "code": "E11.9", "display": "テスト病甲", "method": "licensed_code", "confidence": "0.80",
        "who": "E11.9", "family": False}  # fmt: skip
    assert got["cm_title"]  # the ICD-10-CM code's own title, shown beside the WHO code to be checked
    assert mm.by_code(master, "ZA12")["code"] == "E10.9"  # the sub-classification letter left out for comparison
    three = mm.by_code(master, "ZA02")
    assert three["code"] == "I10" and three["family"] is True  # a three-character code: the family


def test_a_code_with_codes_below_it_in_icd10cm_is_never_a_target(master: mm.Master) -> None:
    """H1(a): E11.2 is a WHO code and an ICD-10-CM category (E11.21, ...): no suggestion."""
    assert mm.target(master, master.by_exchange["ZA18"][0]) == ("E11.2", "", False)
    assert mm.by_code(master, "ZA18") == {} and mm.by_name(master, "テスト見出し病") == {}


def test_no_target_over_the_whole_icd10cm_list_is_a_header() -> None:
    """H1(d): every code of the shipped ICD-10-CM list, as the master would write it: a code with a code below it
    never comes back as a target; a billable code the master can write comes back as itself."""
    codes = sorted(mm._cm_titles())
    assert len(codes) > 50_000
    flat = sorted(c.replace(".", "") for c in codes)
    headers = {a for a, b in itertools.pairwise(flat) if b.startswith(a)}
    empty = mm.Master({}, {}, {}, {})
    taken = 0
    for code in codes:
        bare = code.replace(".", "")
        who, got, family = mm.target(empty, mm.Entry("X", "1", "x", "0", bare))
        if bare in headers:
            assert got == "", code
        elif got:
            taken += 1
            assert got == code == who and family is ("." not in code), code
    assert taken > 5_000  # the master's shapes (three to five characters) reach many billable codes


def test_every_confidence_of_the_master_is_at_most_a_related_term_on_master() -> None:
    """H1(c): a person reads and confirms every suggestion of the master; none is above 0.80, and the ladder is
    strictly ordered (lane J, M7)."""
    ladder = [mm.CONFIDENCE[k] for k in (mm.CODE, mm.NAME, mm.INDEX_TERM, mm.NEAR_SYNONYM, mm.VARIANT, mm.SUCCESSOR,
                                         mm.RELATED_TERM, mm.NAME_DIFFERS)]  # fmt: skip
    assert ladder == sorted(ladder, reverse=True) and len(set(ladder)) == len(ladder) and max(ladder) <= 0.80


# ------------------------------------------------------------------ which entry
def test_a_deleted_entry_suggests_its_successor_and_says_so(master: mm.Master) -> None:
    got = mm.by_code(master, "ZA04")
    assert got["code"] == "K52.9" and got["display"] == "新テスト症"
    assert got["method"] == "licensed_successor" and got["replaced"] == "99000004" and got["confidence"] == "0.64"


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


def _chain(hops: int) -> mm.Master:
    """A deleted entry, ``hops`` successors away from the current entry ZA01's row."""
    t = fx.concepts()
    extra = json.loads(t["ZA11"]["extra"])
    rows = [{"no": f"9800{i:04d}", "name": f"テスト連鎖{i}", "icd": "R688", "change": "1",
             "successor": f"9800{i + 1:04d}" if i + 1 < hops else "99000001"} for i in range(hops)]  # fmt: skip
    extra["rows"] = rows
    t["ZA11"]["extra"] = json.dumps(extra)
    m = mm.rows({"medis": t})
    assert m is not None
    return m


def test_a_successor_chain_is_followed_up_to_its_bound() -> None:
    """Review B pin: more than two hops are followed; a chain as long as the bound is a damaged release."""
    for hops in (3, mm.MAX_HOPS - 1):
        m = _chain(hops)
        assert mm.by_code(m, "ZA11")["code"] == "E11.9"
        got = mm.resolve(m, m.by_number["98000000"])
        assert got is not None and got.number == "99000001", hops
    m = _chain(mm.MAX_HOPS)
    assert mm.resolve(m, m.by_number["98000000"]) is None


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


def test_a_codes_deleted_row_does_not_cloud_its_current_rows(master: mm.Master) -> None:
    # ZA06 holds a deleted row whose successor (ZA05) has another ICD-10: the code's current rows answer
    got = mm.by_code(master, "ZA06")
    assert got["code"] == "J02.9" and "of" not in got


# ------------------------------------------------------------------ by name: the name, then the index by its groups
def test_the_name_comes_first_then_the_index_by_its_groups(master: mm.Master) -> None:
    look = fx.lookup_term
    assert mm.by_name(master, "テスト病甲", look)["method"] == "licensed_name"
    group0 = mm.by_name(master, " ﾃｽﾄﾋﾞﾖｳｺｳ ", look)  # NFKC, upper case, blanks removed: group 0
    assert group0["code"] == "E11.9" and group0["method"] == "licensed_index"
    near = mm.by_name(master, "テスト病a", look)  # group 1, the hospital's lower case read upper
    assert near["code"] == "E11.9" and near["method"] == "licensed_near_synonym"
    variant = mm.by_name(master, "テスト病甲型", look)  # review B pin: a variant form's own method
    assert variant["code"] == "E11.9" and variant["method"] == "licensed_variant"
    assert mm.by_name(master, "旧テスト症ノ別名", look)["method"] == "licensed_successor"
    related = mm.by_name(master, "テスト関連病", look)
    assert related["method"] == "licensed_related" and related["confidence"] == "0.55"
    for never in ("テスト非推奨名", "テスト検索語", "テスト廃語", "ダミーガワ", "テスト非推奨異字"):
        assert mm.by_name(master, never, look) == {}, never  # 8, 9, 0000, a modifier's spelling, 8 as a variant form
    assert mm.by_name(master, "テストb型病", look)["code"] == "B18.1"  # the 病名表記 too is compared in upper case


def test_a_related_term_is_related_whatever_its_variant_mark(master: mm.Master) -> None:
    """Lane J, H2: 同義語区分 2 wins over 異字体区分 1 or 2."""
    for variant in ("1", "2"):
        row = {"term": "テスト語", "code": "ZA01", "target_kind": "1", "synonym": "2", "variant": variant}

        def lookup(_term: str, row: dict[str, str] = row) -> list[dict[str, str]]:
            return [row]

        assert mm.by_name(master, "テスト語", lookup)["method"] == "licensed_related", variant
    rows = [{"term": "テスト語", "code": "ZA01", "target_kind": "1", "synonym": "0", "variant": "1"}]
    assert mm.by_name(master, "テスト語", lambda t: rows)["method"] == "licensed_variant"


def test_the_code_0000_is_never_suggested_even_where_an_exchange_code_has_it() -> None:
    t = fx.concepts()
    t["0000"] = dict(t["ZA01"])
    m = mm.rows({"medis": t})
    rows = [{"term": "テスト廃語", "code": "0000", "target_kind": "1", "synonym": "0", "variant": "9"}]
    assert m is not None and mm.by_name(m, "テスト廃語", lambda term: rows) == {}


def test_a_synonym_shows_the_name_it_borrows_and_the_hints_are_said(master: mm.Master) -> None:
    """Review B pin: the name shown is the level 1 or 2 name, a synonym (採択区分 3) says so."""
    syn = mm.by_name(master, "テスト病丙型")
    assert syn["display"] == "テスト病丙" and syn["synonym"] is True and syn["method"] == "licensed_name"
    assert mm.by_code(master, "ZA06")["display"] == "テスト病丙" and "synonym" not in mm.by_name(master, "テスト病丙")
    assert mm.by_code(master, "ZA02")["hints"] == ["with_modifier"]
    assert mm.by_code(master, "ZA03")["hints"] == ["dental"]
    kampo = mm.by_code(master, "ZA14")  # a hint, never a filter: still suggested
    assert kampo["hints"] == ["kampo"] and kampo["code"] == "R12"
    assert "hints" not in mm.by_code(master, "ZA01")


def test_a_modifiers_spelling_never_names_a_disease(master: mm.Master) -> None:
    rows = [{"term": "テスト修飾語", "code": "ZA01", "target_kind": "2", "synonym": "0", "variant": "9"}]
    assert mm.by_name(master, "テスト修飾語", lambda t: rows) == {}
    rows[0]["target_kind"] = "1"
    assert mm.by_name(master, "テスト修飾語", lambda t: rows)["code"] == "E11.9"  # the same row as a disease's: read


def test_the_index_is_asked_once_for_a_name(master: mm.Master) -> None:
    asked: list[str] = []

    def lookup(term: str) -> list[dict[str, str]]:
        asked.append(term)
        return fx.lookup_term(term)

    assert mm.by_name(master, "テスト関連病", lookup)["code"] == "I10" and asked == ["テスト関連病"]


# ------------------------------------------------------------------ several diseases: all offered, ranked
def test_a_name_of_two_diseases_offers_both_ranked_never_one_in_silence() -> None:
    """D-1261 (lane J): one name or term that points at several diseases offers all of them, ranked; the first is the
    suggestion, the others ride beside it as one of N."""
    t = fx.concepts()
    extra = json.loads(t["ZA02"]["extra"])
    extra["rows"][0]["name"] = "テスト病甲"  # the same name, another ICD-10
    t["ZA02"]["extra"] = json.dumps(extra)
    m = mm.rows({"medis": t})
    assert m is not None
    got = mm.by_name(m, "テスト病甲")
    assert got["code"] == "E11.9" and got["of"] == 2  # the entry with the lower management number first
    assert [(c["code"], c["display"], c["method"], c["family"]) for c in got["candidates"]] == [
        ("I10", "テスト病甲", "licensed_name", True)]  # fmt: skip


def test_index_groups_are_all_offered_in_their_order(master: mm.Master) -> None:
    got = mm.by_name(master, "テスト二群語", fx.lookup_term)  # group 0 (ZA01) and group 2 (ZA02, related)
    assert got["code"] == "E11.9" and got["method"] == "licensed_index" and got["of"] == 2
    assert [(c["code"], c["display"], c["method"]) for c in got["candidates"]] == [
        ("I10", "テスト病乙", "licensed_related")]  # fmt: skip


def test_an_earlier_group_that_gives_nothing_does_not_hide_a_later_one(master: mm.Master) -> None:
    rows = [{"term": "テスト語", "code": "ZA10", "target_kind": "1", "synonym": "0", "variant": "9"},  # U04.9: not CM
            {"term": "テスト語", "code": "ZA01", "target_kind": "1", "synonym": "1", "variant": "9"}]  # fmt: skip
    got = mm.by_name(master, "テスト語", lambda t: rows)
    assert got["code"] == "E11.9" and "of" not in got


def test_one_target_given_by_several_entries_says_how_many_names(master: mm.Master) -> None:
    """ZA04 (deleted, its successor in ZA05) and ZA05 give one code: one candidate, the names counted."""
    rows = [{"term": "テスト語", "code": "ZA05", "target_kind": "1", "synonym": "0", "variant": "9"},
            {"term": "テスト語", "code": "ZA04", "target_kind": "1", "synonym": "0", "variant": "9"}]  # fmt: skip
    got = mm.by_name(master, "テスト語", lambda t: rows)
    assert got["code"] == "K52.9" and "of" not in got and "names" not in got  # ZA04 stands for ZA05's entry
    t = fx.concepts()
    t["ZA16"]["target_code"] = "K529"
    extra = json.loads(t["ZA16"]["extra"])
    extra["rows"][0]["icd"] = "K529"
    t["ZA16"]["extra"] = json.dumps(extra)
    m = mm.rows({"medis": t})
    assert m is not None
    rows.append({"term": "テスト語", "code": "ZA16", "target_kind": "1", "synonym": "0", "variant": "9"})
    got = mm.by_name(m, "テスト語", lambda t: rows)
    assert got["code"] == "K52.9" and got["names"] == 2 and "of" not in got


def test_a_wholly_deleted_code_offers_its_successors_by_code_as_by_name() -> None:
    t = fx.concepts()
    extra = json.loads(t["ZA11"]["extra"])
    extra["rows"][0]["successor"] = "99000001"  # every row of ZA11 deleted, its successor E11.9
    t["ZA11"]["extra"] = json.dumps(extra)
    m = mm.rows({"medis": t})
    assert m is not None
    got = mm.by_code(m, "ZA11")
    assert got["code"] == "E11.9" and got["method"] == "licensed_successor" and got["replaced"] == "99000011"
    assert mm.by_name(m, "廃止テスト病")["method"] == "licensed_successor"


def test_two_successors_of_one_deleted_code_are_both_offered() -> None:
    t = fx.concepts()
    extra = json.loads(t["ZA04"]["extra"])
    extra["rows"].append({"no": "99000019", "name": "旧テスト症別型", "icd": "K529", "change": "1",
                          "successor": "99000002"})  # fmt: skip
    t["ZA04"]["extra"] = json.dumps(extra)
    m = mm.rows({"medis": t})
    assert m is not None
    got = mm.by_code(m, "ZA04")
    assert got["of"] == 2 and {got["code"], got["candidates"][0]["code"]} == {"K52.9", "I10"}
    assert got["method"] == got["candidates"][0]["method"] == "licensed_successor"


# ------------------------------------------------------------------ a code whose local name differs (lane J, M6)
def test_a_local_name_that_names_neither_the_code_nor_its_index_terms_is_said(master: mm.Master) -> None:
    look = fx.lookup_term
    assert mm.by_code(master, "ZA01", "テスト病甲", look)["method"] == "licensed_code"  # its own name
    assert mm.by_code(master, "ZA01", "ﾃｽﾄﾋﾞﾖｳｺｳ", look)["method"] == "licensed_code"  # one of its index terms
    differs = mm.by_code(master, "ZA01", "テスト別物", look)
    assert differs["method"] == "licensed_name_differs" and differs["confidence"] == "0.50"
    assert mm.by_code(master, "ZA01", "", look)["method"] == "licensed_code"  # no name: nothing to compare


# ------------------------------------------------------------------ the 複数分類コード
def test_the_further_codes_ride_beside_the_suggestion_and_never_replace_it(master: mm.Master) -> None:
    """The 複数分類コード: written by the same function, carried as ``also``, never the suggested code (even when the
    ICD-10-CM list lacks it, it is shown, not mapped)."""
    got = mm.by_code(master, "ZA17")
    assert got["code"] == "I20.9" and got["also"] == ["N08.3"]
    assert "also" not in mm.by_code(master, "ZA01")
    assert mm.by_code(master, "ZA09") == {}  # its own code is WHO only: no suggestion, so no further codes either
    for multi, want in (("I209", None), ("N083 E142,A15-9", ["N08.3", "E14.2"])):  # review B pin: every code kept
        t = fx.concepts()
        extra = json.loads(t["ZA17"]["extra"])
        extra["rows"][0]["multi_class"] = multi
        t["ZA17"]["extra"] = json.dumps(extra)
        m = mm.rows({"medis": t})
        assert m is not None and mm.by_code(m, "ZA17").get("also") == want, multi


def test_the_store_keeps_the_detail_and_old_rows_read_as_none() -> None:
    from sitesetup.medis_master import detail_of, detail_read

    one = {"code": "I10", "display": "テスト病乙", "method": "licensed_related", "who": "I10", "cm_title": "t",
           "family": True}  # fmt: skip
    sug = {"code": "E11.9", "method": "licensed_index", "who": "E11.9", "cm_title": "T2", "family": False,
           "also": ["N08.3"], "of": 2, "candidates": [one]}  # fmt: skip
    raw = detail_of(sug)
    assert raw is not None and json.loads(raw) == {"who": "E11.9", "cm_title": "T2", "also": ["N08.3"], "of": 2,
                                                   "candidates": [one]}  # fmt: skip
    assert detail_read(raw)["candidates"] == [one] and detail_read(raw)["also"] == ["N08.3"]
    assert detail_of({"code": "E11.9", "method": "same"}) is None
    for bad in (None, "", "not json", '["I10"]', '"I10"'):
        assert detail_read(bad) in ({}, {"also": [], "candidates": []}), bad
    assert detail_read('{"also": "N08.3", "candidates": [{"display": "x"}, "I10"]}') == {"also": [], "candidates": []}


def test_an_index_term_in_lower_case_is_found_as_the_hospital_writes_it(master: mm.Master) -> None:
    """The index is asked by the loader's one key (upper case): a term the hospital writes in lower case is found."""
    index = {"テストA病": "ZA01", "テストB型名": "ZA16"}  # invented terms as stored, by their key

    def lookup(term: str) -> list[dict[str, str]]:
        code = index.get(licensed.index_key(term))
        return [{"term": term, "code": code, "target_kind": "1", "synonym": "0", "variant": "9"}] if code else []

    assert mm.by_name(master, "テストａ病", lookup)["code"] == "E11.9"  # full-width lower case
    assert mm.by_name(master, "テストｂ型名", lookup)["code"] == "B18.1"


def test_a_name_whose_own_entry_gives_nothing_is_still_read_in_the_index(master: mm.Master) -> None:
    # テスト病丁 is an entry of its own (U04.9: not in ICD-10-CM); the index names another disease for the same words
    rows = [{"term": "テスト病丁", "code": "ZA01", "target_kind": "1", "synonym": "1", "variant": "9"}]
    assert mm.by_name(master, "テスト病丁") == {}
    assert mm.by_name(master, "テスト病丁", lambda t: rows)["code"] == "E11.9"


# ------------------------------------------------------------------ site set-up's suggest
def test_suggest_reads_the_master_first_and_never_guesses_past_it(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = {"medis": fx.concepts()}
    monkeypatch.setattr(licensed, "tables", lambda url=None, cached=False: tables)
    monkeypatch.setattr(mapping, "_medis_index", fx.lookup_term)
    monkeypatch.setattr(mapping, "_master_here", lambda: True)
    assert mapping.suggest("condition", DX, "ZA01")["code"] == "E11.9"
    assert mapping.suggest("condition", DX, "ZA04")["method"] == "licensed_successor"
    assert mapping.suggest("condition", DX, "ZA10", "テスト病丁") == {}  # the master's code: no other guess
    assert mapping.suggest("condition", DX, "LOCAL-1", "テスト病Ａ")["code"] == "E11.9"  # a local code by its name
    assert mapping.suggest("condition", DX, "テスト病甲") == {}  # by name: the display only, never the code (M5)
    assert mapping.suggest("condition", DX, "ZA01", use_master=False) == {}  # another workspace: not read (M4)
    assert mapping.suggest("medication", DX, "ZA01") == {}  # a disease's master, read for conditions only


def test_a_site_whose_layer_does_not_use_the_master_never_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lane J, M4: the loaded tables are not read at a site whose country layer does not use the master."""
    read: list[int] = []

    def tables(url: Any = None, cached: bool = False) -> dict[str, Any]:
        read.append(1)
        return {"medis": fx.concepts()}

    monkeypatch.setattr(licensed, "tables", tables)
    monkeypatch.setattr(mapping, "_medis_index", fx.lookup_term)
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")
    assert mapping.suggest("condition", DX, "LOCAL-1", "テスト病甲").get("method", "") != "licensed_name"
    assert mapping.suggest("condition", DX, "ZA01", "テスト病甲") == {} and not read


def test_without_the_master_suggest_is_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(licensed, "tables", lambda url=None, cached=False: {k: {} for k in licensed.KINDS})
    monkeypatch.setattr(mapping, "_master_here", lambda: True)
    assert mapping.suggest("condition", DX, "E11.9")["method"] == "same"
    assert mapping.suggest("condition", DX, "ZA01", "テスト病甲") == {}


# ------------------------------------------------------------------ the JP Core check
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
    assert not any("not checked" in x for x in texts)


def test_the_check_says_once_when_no_release_is_loaded() -> None:
    """Lane J, M9: MEDIS codes with no release loaded: one information line per resource, never silence."""
    from adapter.validate.jpcore import JpCoreValidator

    v = JpCoreValidator({})
    res = {"resourceType": "Condition", "id": "c1", "code": {"coding": [
        {"system": licensed.MEDIS_BYOMEI, "code": "ZA11"}, {"system": licensed.MEDIS_BYOMEI, "code": "ZA01"}]}}  # fmt: skip
    got = [i for i in v.check(res).issues if "not checked" in i.text]
    assert len(got) == 1 and got[0].severity == "information"


def test_the_page_words_name_every_method() -> None:
    import importlib

    from console.i18n import CATALOGUES

    importlib.import_module("console.medis_page")  # its words join the catalogue

    for method in mm.CONFIDENCE:
        for lang in ("en", "ja", "zh-TW"):
            assert f"site.codes.method.{method}" in CATALOGUES[lang], (method, lang)
    for hint in (*mm.HINTS.values(), *mm.FIELDS.values()):
        for lang in ("en", "ja", "zh-TW"):
            assert f"site.codes.medis.hint.{hint}" in CATALOGUES[lang], (hint, lang)


def test_a_name_is_matched_by_the_loaders_one_key_blanks_and_all(master: mm.Master) -> None:
    """Review B, M1: the index's stored key and the query are one function: a term found with its blanks is found
    without them, and the 病名表記 the same way."""
    assert mm.by_name(master, "テスト 二群 語", fx.lookup_term)["code"] == "E11.9"
    assert mm.by_name(master, "テスト二群語", fx.lookup_term)["code"] == "E11.9"
    assert mm.by_name(master, "テスト　病甲")["code"] == "E11.9"  # a full-width blank inside the 病名表記
    assert mm.key("テスト ａ　語") == licensed.index_key("テストA語") == "テストA語"


def test_the_state_card_names_the_day_rows_codes_and_an_unknown_date() -> None:
    """Lane J, L1 (no date: said), L2 (the site's day, not UTC's), L3 (rows and codes, each named)."""
    from datetime import date
    from zoneinfo import ZoneInfo

    from console.medis_page import state

    row = {"kind": "medis", "state": "loaded", "version": "9.99", "released": "", "rows": 15, "table_rows": 18,
           "loaded_at": "2026-11-19T20:30:00+00:00", "loaded_by": "crc"}  # fmt: skip
    got = state([row], {}, date(2026, 11, 20), ZoneInfo("Asia/Tokyo"))
    assert got is not None
    assert got["dated"] is False and got["remind"] is False and got["released"] == "–"
    assert got["day"] == "2026-11-20"  # 05:30 in Tokyo, still the 19th in UTC
    assert (got["codes"], got["rows"]) == (15, 18)
    dated = state([{**row, "released": "2026-06-01"}], {}, date(2027, 1, 2), ZoneInfo("Asia/Tokyo"))
    assert dated is not None and dated["dated"] is True and dated["remind"] is True


def test_the_licence_is_said_as_it_is() -> None:
    """Lane J, L4: passing the master on is forbidden without MEDIS's permission, for the institution too."""
    from console.i18n_medis import EN, JA, ZH

    assert "without MEDIS's permission, for the institution too" in EN["medis.why"]
    assert "does not allow anyone else" not in EN["medis.why"]
    for cat in (EN, JA, ZH):
        assert not any(w in v for v in cat.values() for w in ("purchased", "購入", "購買")), cat["medis.title"]
