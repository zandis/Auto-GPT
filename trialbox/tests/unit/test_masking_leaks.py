"""Card V-5: the planted-identifier harness (``tools.masking_leaks``).

* One case per entry point, language, kind, form and scope, on a fixed sample: each form once at each place. A case
  leaks when a planted value survives the real entry point (the module's leak rule). A leaking case is
  ``xfail(strict=True, raises=AssertionError)`` with its finding of
  ``docs/plan/measurements/masking-leaks-2026-11-17.md``: it turns red the day its form is masked, and a harness error
  (``PlantError``, a ``RuntimeError``) is never taken for the expected failure.
* Every generator writes its identifier in the real format (check digits, number lengths, ranges): a malformed plant
  is not an identifier.
* ``--check`` sees a page block or a json file that drifted.
"""

from __future__ import annotations

import random
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools import masking_leaks as ml
from tools.synth.generator import tw_id_valid

pytestmark = pytest.mark.nodb

# entry|language|kind|form|scope -> finding; generated once from the sample below, then kept by hand
XFAIL: dict[str, str] = {
    "mask|zh-TW|name|han_2|in": "V5-03",
    "mask|zh-TW|name|han_2|free": "V5-13",
    "mask|zh-TW|name|han_2|line_break": "V5-07",
    "mask|zh-TW|name|han_3|in": "V5-03",
    "mask|zh-TW|name|han_3|free": "V5-13",
    "mask|zh-TW|name|han_3|line_break": "V5-07",
    "mask|zh-TW|name|han_4|free": "V5-13",
    "mask|zh-TW|name|han_4|line_break": "V5-07",
    "mask|zh-TW|name|wade_giles_family_first|line_break": "V5-07",
    "mask|zh-TW|name|wade_giles_given_first|free": "V5-13",
    "mask|zh-TW|name|wade_giles_given_first|line_break": "V5-07",
    "mask|zh-TW|name|pinyin_family_first|in": "V5-03",
    "mask|zh-TW|name|pinyin_family_first|free": "V5-13",
    "mask|zh-TW|name|pinyin_family_first|line_break": "V5-07",
    "mask|zh-TW|name|pinyin_given_first|in": "V5-03",
    "mask|zh-TW|name|pinyin_given_first|free": "V5-13",
    "mask|zh-TW|name|pinyin_given_first|line_break": "V5-07",
    "mask|zh-TW|national_id|tw_id|line_break": "V5-07",
    "mask|zh-TW|national_id|tw_arc_old|line_break": "V5-07",
    "mask|zh-TW|national_id|tw_arc_new|line_break": "V5-07",
    "mask|zh-TW|national_id|tw_id_fullwidth|line_break": "V5-07",
    "mask|zh-TW|chart|bare_8|line_break": "V5-07",
    "mask|zh-TW|chart|label_病歷號_colon|line_break": "V5-07",
    "mask|zh-TW|chart|label_病歷號碼|line_break": "V5-07",
    "mask|zh-TW|chart|label_病歷號碼_colon|line_break": "V5-07",
    "mask|zh-TW|chart|label_ID_colon|line_break": "V5-07",
    "mask|zh-TW|chart|label_MRN|line_break": "V5-07",
    "mask|zh-TW|phone|tw_mobile_hyphen|line_break": "V5-07",
    "mask|zh-TW|phone|tw_mobile_plain|line_break": "V5-07",
    "mask|zh-TW|phone|tw_mobile_intl|line_break": "V5-07",
    "mask|zh-TW|phone|tw_landline_paren|line_break": "V5-07",
    "mask|zh-TW|phone|tw_landline_hyphen|line_break": "V5-07",
    "mask|zh-TW|phone|tw_landline_ext|line_break": "V5-07",
    "mask|zh-TW|phone|tw_mobile_fullwidth|in": "V5-06",
    "mask|zh-TW|phone|tw_mobile_fullwidth|line_break": "V5-07",
    "mask|zh-TW|address|tw_full|in": "V5-12",
    "mask|zh-TW|address|tw_full|line_break": "V5-07",
    "mask|zh-TW|address|tw_no_postcode|line_break": "V5-07",
    "mask|zh-TW|address|tw_floor_unit|line_break": "V5-07",
    "mask|zh-TW|email|ascii|line_break": "V5-07",
    "mask|zh-TW|email|plus|line_break": "V5-07",
    "mask|zh-TW|email|fullwidth_at|line_break": "V5-07",
    "mask|zh-TW|dob|label_iso|line_break": "V5-07",
    "mask|zh-TW|dob|born_iso|line_break": "V5-07",
    "mask|zh-TW|dob|label_slash_ymd|line_break": "V5-07",
    "mask|zh-TW|dob|born_slash_ymd|line_break": "V5-07",
    "mask|zh-TW|dob|label_dotted|line_break": "V5-07",
    "mask|zh-TW|dob|born_dotted|line_break": "V5-07",
    "mask|zh-TW|dob|label_compact8|line_break": "V5-07",
    "mask|zh-TW|dob|born_compact8|line_break": "V5-07",
    "mask|zh-TW|dob|label_roc_slash|line_break": "V5-07",
    "mask|zh-TW|dob|born_roc_slash|line_break": "V5-07",
    "mask|zh-TW|dob|label_roc_dot|line_break": "V5-07",
    "mask|zh-TW|dob|born_roc_dot|line_break": "V5-07",
    "mask|zh-TW|dob|label_roc_compact|line_break": "V5-07",
    "mask|zh-TW|dob|born_roc_compact|in": "V5-08",
    "mask|zh-TW|dob|born_roc_compact|line_break": "V5-07",
    "mask|zh-TW|dob|label_roc_numerals|line_break": "V5-07",
    "mask|zh-TW|dob|born_roc_numerals|line_break": "V5-07",
    "mask|ja|name|kanji_space|free": "V5-13",
    "mask|ja|name|katakana_space|line_break": "V5-07",
    "mask|ja|name|hepburn_family_first|free": "V5-13",
    "mask|ja|name|hepburn_family_first|line_break": "V5-07",
    "mask|ja|name|hepburn_given_first|free": "V5-13",
    "mask|ja|name|hepburn_given_first|line_break": "V5-07",
    "mask|ja|national_id|my_number|line_break": "V5-07",
    "mask|ja|national_id|my_number_spaced|line_break": "V5-07",
    "mask|ja|national_id|my_number_fullwidth|line_break": "V5-07",
    "mask|ja|national_id|insurer_no|line_break": "V5-07",
    "mask|ja|chart|bare_8|line_break": "V5-07",
    "mask|ja|chart|label_カルテ番号_colon|line_break": "V5-07",
    "mask|ja|chart|label_カルテNo|line_break": "V5-07",
    "mask|ja|chart|label_患者ID_colon|line_break": "V5-07",
    "mask|ja|chart|label_ID_colon|line_break": "V5-07",
    "mask|ja|phone|jp_mobile|line_break": "V5-07",
    "mask|ja|phone|jp_landline|line_break": "V5-07",
    "mask|ja|phone|jp_landline_3|line_break": "V5-07",
    "mask|ja|phone|jp_intl|line_break": "V5-07",
    "mask|ja|phone|jp_plain|line_break": "V5-07",
    "mask|ja|phone|jp_fullwidth|line_break": "V5-07",
    "mask|ja|address|jp_no_postcode|line_break": "V5-07",
    "mask|ja|email|ascii|line_break": "V5-07",
    "mask|ja|email|plus|line_break": "V5-07",
    "mask|ja|email|fullwidth_at|line_break": "V5-07",
    "mask|ja|dob|label_iso|line_break": "V5-07",
    "mask|ja|dob|born_iso|line_break": "V5-07",
    "mask|ja|dob|label_slash_ymd|line_break": "V5-07",
    "mask|ja|dob|born_slash_ymd|line_break": "V5-07",
    "mask|ja|dob|label_dotted|line_break": "V5-07",
    "mask|ja|dob|born_dotted|line_break": "V5-07",
    "mask|ja|dob|label_compact8|line_break": "V5-07",
    "mask|ja|dob|born_compact8|line_break": "V5-07",
    "mask|en|name|wade_giles_family_first|in": "V5-02",
    "mask|en|name|wade_giles_family_first|free": "V5-13",
    "mask|en|name|wade_giles_family_first|line_break": "V5-07",
    "mask|en|name|wade_giles_given_first|line_break": "V5-07",
    "mask|en|name|pinyin_family_first|in": "V5-02",
    "mask|en|name|pinyin_family_first|free": "V5-13",
    "mask|en|name|pinyin_family_first|line_break": "V5-07",
    "mask|en|name|pinyin_given_first|in": "V5-02",
    "mask|en|name|pinyin_given_first|free": "V5-13",
    "mask|en|name|pinyin_given_first|line_break": "V5-07",
    "mask|en|name|first_last|in": "V5-02",
    "mask|en|name|first_last|free": "V5-13",
    "mask|en|name|first_last|line_break": "V5-07",
    "mask|en|name|last_comma_first|in": "V5-02",
    "mask|en|name|last_comma_first|free": "V5-13",
    "mask|en|name|last_comma_first|line_break": "V5-07",
    "mask|en|name|middle_initial|in": "V5-02",
    "mask|en|name|middle_initial|free": "V5-13",
    "mask|en|name|middle_initial|line_break": "V5-07",
    "mask|en|name|dr|in": "V5-02",
    "mask|en|name|mr|in": "V5-02",
    "mask|en|name|ms|in": "V5-02",
    "mask|en|name|initials|in": "V5-02",
    "mask|en|name|initials|free": "V5-13",
    "mask|en|name|initials|line_break": "V5-07",
    "mask|en|national_id|tw_id|line_break": "V5-07",
    "mask|en|national_id|tw_arc_old|line_break": "V5-07",
    "mask|en|national_id|tw_arc_new|line_break": "V5-07",
    "mask|en|national_id|us_ssn|in": "V5-09",
    "mask|en|national_id|us_ssn|line_break": "V5-07",
    "mask|en|chart|bare_8|line_break": "V5-07",
    "mask|en|chart|label_MRN|line_break": "V5-07",
    "mask|en|chart|label_MRN_colon|line_break": "V5-07",
    "mask|en|chart|label_Chart_No|line_break": "V5-07",
    "mask|en|chart|label_Hospital_No_colon|line_break": "V5-07",
    "mask|en|chart|label_ID_colon|line_break": "V5-07",
    "mask|en|phone|tw_mobile_hyphen|line_break": "V5-07",
    "mask|en|phone|tw_mobile_plain|line_break": "V5-07",
    "mask|en|phone|tw_mobile_intl|line_break": "V5-07",
    "mask|en|phone|tw_landline_paren|line_break": "V5-07",
    "mask|en|phone|tw_landline_hyphen|line_break": "V5-07",
    "mask|en|phone|tw_landline_ext|line_break": "V5-07",
    "mask|en|phone|na_paren|line_break": "V5-07",
    "mask|en|phone|na_hyphen|line_break": "V5-07",
    "mask|en|phone|na_intl|line_break": "V5-07",
    "mask|en|address|en_full|in": "V5-12",
    "mask|en|address|en_full|line_break": "V5-07",
    "mask|en|email|ascii|line_break": "V5-07",
    "mask|en|email|plus|line_break": "V5-07",
    "mask|en|email|fullwidth_at|line_break": "V5-07",
    "mask|en|dob|label_iso|line_break": "V5-07",
    "mask|en|dob|label_slash_ymd|line_break": "V5-07",
    "mask|en|dob|label_dotted|line_break": "V5-07",
    "mask|en|dob|label_compact8|line_break": "V5-07",
    "mask|en|dob|label_slash_dmy|line_break": "V5-07",
    "mask|en|dob|label_slash_mdy|line_break": "V5-07",
    "mask|en|dob|label_month_name|line_break": "V5-07",
    "mask|en|dob|label_day_month_abbr|line_break": "V5-07",
    "mask|en|dob|label_two_digit_year|line_break": "V5-07",
    "tripwire|zh-TW|name|han_2|free": "V5-10",
    "tripwire|zh-TW|name|han_2|line_break": "V5-10",
    "tripwire|zh-TW|name|han_3|free": "V5-10",
    "tripwire|zh-TW|name|han_3|line_break": "V5-10",
    "tripwire|zh-TW|name|han_4|free": "V5-10",
    "tripwire|zh-TW|name|han_4|line_break": "V5-10",
    "tripwire|zh-TW|name|wade_giles_family_first|line_break": "V5-10",
    "tripwire|zh-TW|name|wade_giles_given_first|free": "V5-10",
    "tripwire|zh-TW|name|wade_giles_given_first|line_break": "V5-10",
    "tripwire|zh-TW|name|pinyin_family_first|free": "V5-10",
    "tripwire|zh-TW|name|pinyin_family_first|line_break": "V5-10",
    "tripwire|zh-TW|name|pinyin_given_first|free": "V5-10",
    "tripwire|zh-TW|name|pinyin_given_first|line_break": "V5-10",
    "tripwire|zh-TW|national_id|tw_id|line_break": "V5-10",
    "tripwire|zh-TW|national_id|tw_arc_old|line_break": "V5-10",
    "tripwire|zh-TW|national_id|tw_arc_new|line_break": "V5-10",
    "tripwire|zh-TW|national_id|tw_id_fullwidth|line_break": "V5-10",
    "tripwire|zh-TW|chart|bare_8|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_mobile_hyphen|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_mobile_plain|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_mobile_intl|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_landline_paren|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_landline_hyphen|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_landline_ext|line_break": "V5-10",
    "tripwire|zh-TW|phone|tw_mobile_fullwidth|in": "V5-10",
    "tripwire|zh-TW|phone|tw_mobile_fullwidth|line_break": "V5-10",
    "tripwire|zh-TW|address|tw_full|line_break": "V5-10",
    "tripwire|zh-TW|address|tw_no_postcode|line_break": "V5-10",
    "tripwire|zh-TW|address|tw_floor_unit|line_break": "V5-10",
    "tripwire|zh-TW|email|ascii|line_break": "V5-10",
    "tripwire|zh-TW|email|plus|line_break": "V5-10",
    "tripwire|zh-TW|email|fullwidth_at|line_break": "V5-10",
    "tripwire|zh-TW|dob|born_compact8|line_break": "V5-10",
    "tripwire|zh-TW|dob|born_roc_slash|line_break": "V5-10",
    "tripwire|zh-TW|dob|born_roc_dot|line_break": "V5-10",
    "tripwire|zh-TW|dob|born_roc_compact|in": "V5-10",
    "tripwire|zh-TW|dob|born_roc_compact|line_break": "V5-10",
    "tripwire|zh-TW|dob|born_roc_numerals|line_break": "V5-10",
    "tripwire|ja|name|kanji_space|free": "V5-10",
    "tripwire|ja|name|katakana_space|line_break": "V5-10",
    "tripwire|ja|name|hepburn_family_first|free": "V5-10",
    "tripwire|ja|name|hepburn_family_first|line_break": "V5-10",
    "tripwire|ja|name|hepburn_given_first|free": "V5-10",
    "tripwire|ja|name|hepburn_given_first|line_break": "V5-10",
    "tripwire|ja|national_id|my_number|line_break": "V5-10",
    "tripwire|ja|national_id|my_number_spaced|line_break": "V5-10",
    "tripwire|ja|national_id|my_number_fullwidth|line_break": "V5-10",
    "tripwire|ja|chart|bare_8|line_break": "V5-10",
    "tripwire|ja|phone|jp_mobile|line_break": "V5-10",
    "tripwire|ja|phone|jp_landline|line_break": "V5-10",
    "tripwire|ja|phone|jp_landline_3|line_break": "V5-10",
    "tripwire|ja|phone|jp_intl|line_break": "V5-10",
    "tripwire|ja|phone|jp_plain|line_break": "V5-10",
    "tripwire|ja|phone|jp_fullwidth|line_break": "V5-10",
    "tripwire|ja|address|jp_no_postcode|line_break": "V5-10",
    "tripwire|ja|email|ascii|line_break": "V5-10",
    "tripwire|ja|email|plus|line_break": "V5-10",
    "tripwire|ja|email|fullwidth_at|line_break": "V5-10",
    "tripwire|ja|dob|born_iso|line_break": "V5-10",
    "tripwire|ja|dob|born_slash_ymd|line_break": "V5-10",
    "tripwire|ja|dob|born_dotted|line_break": "V5-10",
    "tripwire|ja|dob|born_compact8|line_break": "V5-10",
    "tripwire|en|name|wade_giles_family_first|in": "V5-10",
    "tripwire|en|name|wade_giles_family_first|free": "V5-10",
    "tripwire|en|name|wade_giles_family_first|line_break": "V5-10",
    "tripwire|en|name|wade_giles_given_first|line_break": "V5-10",
    "tripwire|en|name|pinyin_family_first|in": "V5-10",
    "tripwire|en|name|pinyin_family_first|free": "V5-10",
    "tripwire|en|name|pinyin_family_first|line_break": "V5-10",
    "tripwire|en|name|pinyin_given_first|in": "V5-10",
    "tripwire|en|name|pinyin_given_first|free": "V5-10",
    "tripwire|en|name|pinyin_given_first|line_break": "V5-10",
    "tripwire|en|name|first_last|in": "V5-10",
    "tripwire|en|name|first_last|free": "V5-10",
    "tripwire|en|name|first_last|line_break": "V5-10",
    "tripwire|en|name|last_comma_first|in": "V5-10",
    "tripwire|en|name|last_comma_first|free": "V5-10",
    "tripwire|en|name|last_comma_first|line_break": "V5-10",
    "tripwire|en|name|middle_initial|in": "V5-10",
    "tripwire|en|name|middle_initial|free": "V5-10",
    "tripwire|en|name|middle_initial|line_break": "V5-10",
    "tripwire|en|name|initials|in": "V5-10",
    "tripwire|en|name|initials|free": "V5-10",
    "tripwire|en|name|initials|line_break": "V5-10",
    "tripwire|en|national_id|tw_id|line_break": "V5-10",
    "tripwire|en|national_id|tw_arc_old|line_break": "V5-10",
    "tripwire|en|national_id|tw_arc_new|line_break": "V5-10",
    "tripwire|en|national_id|us_ssn|in": "V5-10",
    "tripwire|en|national_id|us_ssn|line_break": "V5-10",
    "tripwire|en|chart|bare_8|line_break": "V5-10",
    "tripwire|en|phone|tw_mobile_hyphen|line_break": "V5-10",
    "tripwire|en|phone|tw_mobile_plain|line_break": "V5-10",
    "tripwire|en|phone|tw_mobile_intl|line_break": "V5-10",
    "tripwire|en|phone|tw_landline_paren|line_break": "V5-10",
    "tripwire|en|phone|tw_landline_hyphen|line_break": "V5-10",
    "tripwire|en|phone|tw_landline_ext|line_break": "V5-10",
    "tripwire|en|phone|na_paren|line_break": "V5-10",
    "tripwire|en|phone|na_hyphen|line_break": "V5-10",
    "tripwire|en|phone|na_intl|line_break": "V5-10",
    "tripwire|en|email|ascii|line_break": "V5-10",
    "tripwire|en|email|plus|line_break": "V5-10",
    "tripwire|en|email|fullwidth_at|line_break": "V5-10",
    "mask|en|phone|tw_landline_paren|in": "V5-06",
    "tripwire|en|phone|tw_landline_paren|in": "V5-10",
    "tripwire|en|dob|label_compact8|line_break": "V5-10",
    "tripwire|en|dob|label_slash_dmy|line_break": "V5-10",
    "tripwire|en|dob|label_slash_mdy|line_break": "V5-10",
    "tripwire|en|dob|label_month_name|line_break": "V5-10",
    "tripwire|en|dob|label_day_month_abbr|line_break": "V5-10",
    "tripwire|en|dob|label_two_digit_year|line_break": "V5-10",
}

REASONS = {
    "V5-01": "Japanese names in the ruling's scope leak (kana, Hepburn, unlisted surnames)",
    "V5-02": "English names in the ruling's scope leak (LAST, First; initials; a title after Name:)",
    "V5-03": "Chinese names in the ruling's scope leak (Pinyin, unlisted surnames)",
    "V5-04": "the insurance card's 記号・番号 leaks after its label",
    "V5-05": "an e-mail with a full-width ＠ is not masked",
    "V5-06": "full-width mobiles and (0dd) landlines are not masked",
    "V5-07": "a value split by a hard wrap is not masked",
    "V5-08": "a compact ROC birth date before 出生 is not masked",
    "V5-09": "an unlabelled US SSN is not masked",
    "V5-10": "the gateway tripwire misses this form",
    "V5-12": "the postcode of a masked address stays readable",
    "V5-13": "a free-standing name is not masked (outside D-337 section 1)",
}

SAMPLE: dict[str, tuple[int, list[str]]] = {}


@pytest.fixture(scope="module")
def eng() -> ml.Engines:
    return ml.engines()


def sample(eng: ml.Engines) -> dict[str, tuple[int, list[str]]]:
    """``entry|lang|kind|form|scope`` -> (notes, leaked places) on the fixed sample (one note per form and place)."""
    if SAMPLE:
        return SAMPLE
    for lang in ml.LANGS:
        ml.base_notes(lang, ml.clean_base(eng))
        for kind, form, pos, text, start, it in ml.cases(lang, len(ml.POSITIONS)):
            if form in ml.NOT_HELD:
                continue
            sc = ml.scope(kind, it, pos)
            got = {
                "mask": ml.judge(text, eng.mask(text), start, it, eng.mask_char, kind) == "leaked",
                "tripwire": not eng.tripwire(text),
            }
            for entry, leaked in got.items():
                n, bad = SAMPLE.get(f"{entry}|{lang}|{kind}|{form}|{sc}", (0, []))
                SAMPLE[f"{entry}|{lang}|{kind}|{form}|{sc}"] = (n + 1, [*bad, pos] if leaked else bad)
    return SAMPLE


def _keys() -> list[str]:
    out = []
    for entry in ("mask", "tripwire"):
        for lang in ml.LANGS:
            for kind, form, gen in ml.forms(lang):
                if form in ml.NOT_HELD:
                    continue
                free = kind == "name" and not gen(random.Random(0)).cue  # a name with a cue is never free-standing
                for sc in ("in", "free", "line_break") if free else ("in", "line_break"):
                    out.append(f"{entry}|{lang}|{kind}|{form}|{sc}")
    return out


def _cases() -> list[Any]:
    out = []
    for key in _keys():
        fid = XFAIL.get(key)
        marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"{fid}: {REASONS[fid]}")] if fid else []
        out.append(pytest.param(key, marks=marks, id=key.replace("|", "-")))
    return out


@pytest.mark.parametrize("key", _cases())
def test_no_planted_identifier_survives(eng: ml.Engines, key: str) -> None:
    n, bad = sample(eng).get(key, (0, []))
    if n == 0:
        raise ml.PlantError(f"no note was planted for {key}")
    assert not bad, f"{len(bad)} of {n} planted values leaked at {bad}"


def test_base_notes_are_clean(eng: ml.Engines) -> None:
    """The control: every base note used gives no mask and no tripwire hit, so a clean case is clean because the
    planted value was masked, and a tripwire hit is the plant's."""
    for lang in ml.LANGS:
        notes = ml.base_notes(lang, ml.clean_base(eng))
        assert len(notes) >= 100
        assert all(eng.mask("".join(s)) == "".join(s) and not eng.tripwire("".join(s)) for s in notes[:20])


def test_compact_clinical_dates_are_kept(eng: ml.Engines) -> None:
    """An 8-digit clinical date (a date of diagnosis written 20240503) is not an identifier (D-745: a date with no
    birth label stays)."""
    text = "病人於20240503確診第二型糖尿病，持續原處方藥物。"
    assert eng.mask(text) == text


test_compact_clinical_dates_are_kept = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="V5-11: the site chart pattern masks 8-digit clinical dates"
)(test_compact_clinical_dates_are_kept)


# ---------------------------------------------------------------------------------------------- generator formats
R = random.Random(7)
N = 200


def _arc_old_valid(s: str) -> bool:
    if not re.fullmatch(r"[A-Z][A-D]\d{8}", s):
        return False
    n = ml.TW_LETTERS[s[0]]
    vals = [n // 10, n % 10, ml.TW_LETTERS[s[1]] % 10, *(int(c) for c in s[2:])]
    return sum(v * w for v, w in zip(vals, (1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1), strict=True)) % 10 == 0


def _my_number_valid(s: str) -> bool:
    if not re.fullmatch(r"\d{12}", s):
        return False
    total = sum(int(p) * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(reversed(s[:11]), start=1))
    return int(s[11]) == (0 if total % 11 <= 1 else 11 - total % 11)


def _insurer_valid(s: str) -> bool:
    if not re.fullmatch(r"\d{8}", s) or not 1 <= int(s[2:4]) <= 47:
        return False
    total = sum(sum(divmod(int(c) * (2 if i % 2 == 0 else 1), 10)) for i, c in enumerate(s[:7]))
    return int(s[7]) == (10 - total % 10) % 10


def test_taiwan_ids_have_valid_check_digits() -> None:
    assert all(tw_id_valid(ml.tw_id(R)) for _ in range(N))
    new = [ml.tw_id(R, R.choice("89")) for _ in range(N)]
    assert all(tw_id_valid(s) and s[1] in "89" for s in new)  # the new resident number: same check digit rule
    assert all(_arc_old_valid(ml.arc_old(R)) for _ in range(N))


def test_japanese_numbers_have_valid_check_digits() -> None:
    assert all(_my_number_valid(ml.my_number(R)) for _ in range(N))
    assert all(_insurer_valid(ml.insurer_no(R)) for _ in range(N))


def test_ssn_is_in_the_issued_ranges() -> None:
    for _ in range(N):
        a, g, s = ml.ssn(R).split("-")
        assert len(a) == 3 and 1 <= int(a) <= 899 and int(a) != 666 and len(g) == 2 and int(g) and len(s) == 4
        assert int(s)


def test_taiwan_phones_have_true_lengths() -> None:
    lengths = dict(ml.TW_AREAS)
    for _ in range(N):
        area, sub = ml.tw_landline(R)
        assert len(sub) == lengths[area] and sub[0] not in "01"
        for form in ("landline_paren", "landline_hyphen"):
            digits = re.sub(r"\D", "", ml._tw_phone(R, form))
            assert any(digits.startswith(a) and len(digits) == len(a) + n for a, n in ml.TW_AREAS)
        for form in ("mobile_hyphen", "mobile_plain", "mobile_space"):
            assert re.fullmatch(r"09\d{8}", re.sub(r"\D", "", ml._tw_phone(R, form)))
        assert re.fullmatch(r"8869\d{8}", re.sub(r"\D", "", ml._tw_phone(R, "mobile_intl_space")))


def test_japanese_and_north_american_phones_have_true_lengths() -> None:
    for _ in range(N):
        assert re.fullmatch(r"0[789]0\d{8}", re.sub(r"\D", "", ml._jp_phone(R, "mobile")))
        assert re.fullmatch(r"0\d{9}", re.sub(r"\D", "", ml._jp_phone(R, "landline")))
        assert re.fullmatch(r"0\d{9}", re.sub(r"\D", "", ml._jp_phone(R, "landline_3")))
        assert re.fullmatch(r"81[789]0\d{8}", re.sub(r"\D", "", ml._jp_phone(R, "intl")))
        assert re.fullmatch(r"1?[2-9]\d{2}55501\d{2}", re.sub(r"\D", "", ml._na_phone(R, "intl")))


def test_postcodes_have_true_shapes() -> None:
    for _ in range(N):
        tw = ml._tw_addr(R, "full")
        assert 100 <= int(tw.surface[:3]) <= 983 and not tw.surface[3].isdigit()
        jp = ml._jp_addr(R, "full")
        assert re.fullmatch(r"〒\d{3}-\d{4}", jp.surface[jp.keys[0][0] - 1 : jp.keys[0][1]])
        en = ml._en_addr(R, "full")
        assert re.fullmatch(r"\d{5}", en.surface[en.keys[0][0] : en.keys[0][1]]) and int(en.surface[-5:]) >= 501


# ---------------------------------------------------------------------------------------------- --check
def test_page_blocks_match_the_json() -> None:
    assert ml.check() == []


def test_check_sees_a_drifted_page_and_a_drifted_json(tmp_path: Path) -> None:
    page, data, fnd = tmp_path / "page.md", tmp_path / "leaks.json", tmp_path / "findings.json"
    shutil.copy(ml.PAGE_PATH, page)
    shutil.copy(ml.JSON_PATH, data)
    shutil.copy(ml.FINDINGS_PATH, fnd)
    assert ml.check(page, data, fnd) == []
    page.write_text(page.read_text(encoding="utf-8").replace(" per 1,000**", " per 1,000 **", 1), encoding="utf-8")
    assert "verdict" in ml.check(page, data, fnd)
    shutil.copy(ml.PAGE_PATH, page)
    fnd.write_text(fnd.read_text(encoding="utf-8").replace('"High"', '"Low"', 1), encoding="utf-8")
    assert ml.check(page, data, fnd) == ["findings"]
