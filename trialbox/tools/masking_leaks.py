"""The planted-identifier harness of card V-5 (plan 8, activity V6): does the note masker hide every identifier?

    python -m tools.masking_leaks --write   # the full run: writes leaks.json and the page's generated tables
    python -m tools.masking_leaks --check   # the page's generated tables equal what leaks.json gives (no run)

Base notes are the synthetic hospital's own sentences (``tools.synth.notes``, ``notes_ja``, ``notes_en``). Into each
note copy this tool plants ONE identifier it invents itself (its own name pools, digits from a seeded random source,
never the masker's patterns), at one of seven places. Then the text goes through the two real entry points:

* ``tb_common.phi_guard.mask_note(text, site_mrn_regex())``: what ``lake.store.Lake.rebuild`` runs before a note is
  chunked, indexed and embedded (``services/lake/store.py:1463``), and what the console runs on a note it shows
  (``services/console/reveal.py:81``);
* ``guard.Guard.from_settings().tripwire(text)``: what the gateway runs on a call that leaves the box
  (``services/gateway/core.py:579``). A miss there means the raw note is sent out.

Leak rule. ``mask_note`` keeps the length, so the planted value's own characters are read back at their place. The
value leaked when none of its characters other than separators (space, line break, dash, dot, slash, brackets,
colon, plus) was masked, so its surface string and its normalised form are still in the output. A name leaked when
its family name and at least one more letter of the name are unmasked. A tripwire leak is a note with a plant that
gives no hit. Date rule (D-745): a date of birth (after its label, or before the word for born) must be masked; a
date with neither is a clinical date and must stay, so bare dates are counted with the clinical strings.

Second set: clinical strings that screening criteria need (ages, lab values, doses, dates of diagnosis, durations,
stage, scores, variants, trial ids, codes, compact dates). Each is planted in a fresh note; a string with any
character masked counts as altered.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs/plan/measurements/masking-leaks-2026-11-17"
JSON_PATH = OUT_DIR / "leaks.json"
PAGE_PATH = ROOT / "docs/plan/measurements/masking-leaks-2026-11-17.md"
SEED = 20261117
LANGS = ("zh-TW", "ja", "en")
POSITIONS = ("start", "middle", "end", "label", "table", "cjk_adjacent", "line_break")
MIN_NOTES = 1000  # planted notes per language, at least
SEPARATORS = set(" \t\n　-‐－.．/／()（）:：+＋,，")

# ---------------------------------------------------------------------------------------------- invented pools
# Han surnames, common and rarer; given-name characters; romanised pairs (Wade-Giles, Pinyin)
ZH_SURNAMES = [
    "陳",
    "林",
    "黃",
    "張",
    "李",
    "王",
    "吳",
    "劉",
    "蔡",
    "楊",
    "闕",
    "冼",
    "粘",
    "尤",
    "卓",
    "涂",
    "龔",
    "諶",
]
ZH_COMPOUND = ["歐陽", "司馬", "張簡", "范姜"]
ZH_GIVEN = list("志明淑芬家豪怡君冠宇雅婷柏翰品妤承恩宥廷秉諺語彤沛晴睿")
ZH_ROMAN = [
    ("Chen", "Chen"),
    ("Lin", "Lin"),
    ("Huang", "Huang"),
    ("Chang", "Zhang"),
    ("Wang", "Wang"),
    ("Tsai", "Cai"),
    ("Hsu", "Xu"),
    ("Cheng", "Zheng"),
    ("Chueh", "Que"),
    ("Tu", "Tu"),
]
ZH_GIVEN_ROMAN = [
    ("Chih", "Zhi"),
    ("Ming", "Ming"),
    ("Shu", "Shu"),
    ("Fen", "Fen"),
    ("Chia", "Jia"),
    ("Hao", "Hao"),
    ("Kuan", "Guan"),
    ("Yu", "Yu"),
    ("Ting", "Ting"),
    ("Hsin", "Xin"),
]
# Japanese family and given names: kanji, katakana, hiragana, Hepburn
JA_FAMILY = [
    ("山田", "ヤマダ", "やまだ", "Yamada"),
    ("佐藤", "サトウ", "さとう", "Sato"),
    ("鈴木", "スズキ", "すずき", "Suzuki"),
    ("高橋", "タカハシ", "たかはし", "Takahashi"),
    ("森本", "モリモト", "もりもと", "Morimoto"),
    ("丸山", "マルヤマ", "まるやま", "Maruyama"),
    ("千葉", "チバ", "ちば", "Chiba"),
    ("大塚", "オオツカ", "おおつか", "Otsuka"),
    ("吉川", "ヨシカワ", "よしかわ", "Yoshikawa"),
    ("今井", "イマイ", "いまい", "Imai"),
]
JA_GIVEN = [
    ("太郎", "タロウ", "たろう", "Taro"),
    ("花子", "ハナコ", "はなこ", "Hanako"),
    ("健一", "ケンイチ", "けんいち", "Kenichi"),
    ("美咲", "ミサキ", "みさき", "Misaki"),
    ("翔太", "ショウタ", "しょうた", "Shota"),
    ("陽子", "ヨウコ", "ようこ", "Yoko"),
]
EN_FIRST = ["Alice", "Brian", "Carmen", "Derek", "Elena", "Felix", "Grace", "Hugo", "Irene", "Jonah", "Kara", "Liam"]
EN_LAST = [
    "Testwell",
    "Sampleton",
    "Hartley",
    "Okafor",
    "Lindqvist",
    "Brennan",
    "Moreau",
    "Whitcombe",
    "Nakamura",
    "Fairbanks",
    "Pennington",
    "Castellano",
]
TW_LETTERS = {
    "A": 10,
    "B": 11,
    "C": 12,
    "D": 13,
    "E": 14,
    "F": 15,
    "G": 16,
    "H": 17,
    "I": 34,
    "J": 18,
    "K": 19,
    "L": 20,
    "M": 21,
    "N": 22,
    "O": 35,
    "P": 23,
    "Q": 24,
    "R": 25,
    "S": 26,
    "T": 27,
    "U": 28,
    "V": 29,
    "W": 32,
    "X": 30,
    "Y": 31,
    "Z": 33,
}
ZH_DIGITS = "〇一二三四五六七八九"


def fw(s: str) -> str:
    """Full-width digits, letters and @ (the way a CJK input method writes them)."""
    return "".join(chr(ord(c) + 0xFEE0) if ("!" <= c <= "~") else c for c in s)


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def tw_id(rng: random.Random, second: str | None = None) -> str:
    """A Taiwan ID number with a valid check digit (letter, 1 or 2, seven digits, the check digit)."""
    letter = rng.choice(sorted(TW_LETTERS))
    body = (second or rng.choice("12")) + digits(rng, 7)
    n = TW_LETTERS[letter]
    total = n // 10 + (n % 10) * 9 + sum(int(d) * w for d, w in zip(body, (8, 7, 6, 5, 4, 3, 2, 1), strict=True))
    return letter + body + str((10 - total % 10) % 10)


def zh_numeral(n: int) -> str:
    return "".join(ZH_DIGITS[int(d)] for d in str(n))


@dataclass
class Item:
    """One planted string: ``surface`` is inserted; ``v`` the value's offsets in it; ``fam`` the family name's."""

    surface: str
    v: tuple[int, int]
    fam: tuple[int, int] | None = None
    labelled: bool = False  # the form carries its own label


def plain(s: str) -> Item:
    return Item(s, (0, len(s)))


def labelled(label: str, value: str) -> Item:
    return Item(label + value, (len(label), len(label) + len(value)), labelled=True)


def name_item(prefix: str, name: str, family: str, suffix: str = "") -> Item:
    s = prefix + name + suffix
    a = len(prefix)
    f = name.index(family)
    return Item(s, (a, a + len(name)), (a + f, a + f + len(family)))


# ---------------------------------------------------------------------------------------------- the forms
Gen = Callable[[random.Random], Item]


def _date(rng: random.Random) -> tuple[int, int, int]:
    return rng.randint(1930, 1999), rng.randint(1, 12), rng.randint(1, 28)


def _zh_name(rng: random.Random, n: int) -> tuple[str, str]:
    fam = rng.choice(ZH_COMPOUND) if n == 4 else rng.choice(ZH_SURNAMES)
    return fam + "".join(rng.choice(ZH_GIVEN) for _ in range(n - len(fam))), fam


def _roman(rng: random.Random, py: bool, given_first: bool) -> Item:
    fam = rng.choice(ZH_ROMAN)[1 if py else 0]
    g1, g2 = rng.sample(ZH_GIVEN_ROMAN, 2)
    given = (g1[1] + g2[1].lower()) if py else f"{g1[0]}-{g2[0].lower()}"
    name = f"{given} {fam}" if given_first else f"{fam} {given}"
    return name_item("", name, fam)


def _ja(rng: random.Random, script: int, space: bool, suffix: str = "") -> Item:
    f, g = rng.choice(JA_FAMILY), rng.choice(JA_GIVEN)
    name = f[script] + ("　" if space else "") + g[script]
    return name_item("", name, f[script], suffix)


def _hepburn(rng: random.Random, family_first: bool) -> Item:
    f, g = rng.choice(JA_FAMILY)[3], rng.choice(JA_GIVEN)[3]
    name = f"{f.upper()} {g}" if family_first else f"{g} {f}"
    return name_item("", name, f.upper() if family_first else f)


def _en(rng: random.Random, form: str) -> Item:
    first, last = rng.choice(EN_FIRST), rng.choice(EN_LAST)
    if form == "first_last":
        return name_item("", f"{first} {last}", last)
    if form == "last_comma_first":
        return name_item("", f"{last.upper()}, {first}", last.upper())
    if form == "middle_initial":
        return name_item("", f"{first} {rng.choice('BCDKMRT')}. {last}", last)
    if form == "dr":
        return name_item("Dr. ", last, last)
    if form == "mr":
        return name_item("Mr. ", f"{first} {last}", last)
    if form == "ms":
        return name_item("Ms. ", last, last)
    return plain(f"{first[0]}.{last[0]}.")  # initials


def _tw_phone(rng: random.Random, form: str) -> str:
    m = "09" + digits(rng, 8)
    land = "2" + digits(rng, 7)
    return {
        "mobile_hyphen": f"{m[:4]}-{m[4:7]}-{m[7:]}",
        "mobile_plain": m,
        "mobile_space": f"{m[:4]} {m[4:7]} {m[7:]}",
        "mobile_intl": f"+886-{m[1:4]}-{m[4:7]}-{m[7:]}",
        "mobile_intl_space": f"+886 {m[1]} {m[2:6]} {m[6:]}",
        "landline_paren": f"(0{land[0]}){land[1:5]}-{land[5:]}",
        "landline_hyphen": f"0{land[0]}-{land[1:5]}-{land[5:]}",
        "landline_ext": f"0{land[0]}-{land[1:5]}-{land[5:]} 分機{digits(rng, 3)}",
        "mobile_fullwidth": fw(f"{m[:4]}-{m[4:7]}-{m[7:]}"),
    }[form]


def _jp_phone(rng: random.Random, form: str) -> str:
    a, b = digits(rng, 4), digits(rng, 4)
    return {
        "mobile": f"090-{a}-{b}",
        "landline": f"03-{a}-{b}",
        "intl": f"+81-90-{a}-{b}",
        "plain": f"090{a}{b}",
        "fullwidth": fw(f"090-{a}-{b}"),
    }[form]


def _na_phone(rng: random.Random, form: str) -> str:
    area, last = rng.choice(["212", "415", "617", "312"]), "01" + digits(rng, 2)
    return {"paren": f"({area}) 555-{last}", "hyphen": f"{area}-555-{last}", "intl": f"+1 {area} 555 {last}"}[form]


def _tw_addr(rng: random.Random, form: str) -> str:
    city = rng.choice(["臺北市中正區", "新北市板橋區", "臺中市西屯區", "高雄市苓雅區", "宜蘭縣羅東鎮"])
    road = rng.choice(["測試路", "範例街", "模擬大道", "示範路"])
    no = f"{rng.randint(1, 300)}號"
    if form == "full":
        head = f"{rng.randint(100, 999)}{city}{road}{rng.choice('一二三')}段"
        return head + f"{rng.randint(1, 99)}巷{rng.randint(1, 20)}弄{no}{rng.randint(2, 15)}樓"
    if form == "no_postcode":
        return f"{city}{road}{rng.randint(1, 99)}巷{no}"
    return f"{city}{road}{no}{rng.randint(2, 15)}樓之{rng.randint(1, 5)}"  # floor and unit


def _jp_addr(rng: random.Random, form: str) -> str:
    pref = rng.choice(["東京都千代田区", "大阪府大阪市北区", "愛知県名古屋市中区", "北海道札幌市中央区"])
    town = rng.choice(["試験町", "見本町", "仮町"])
    chome = f"{rng.randint(1, 9)}丁目{rng.randint(1, 30)}番{rng.randint(1, 20)}号"
    post = f"〒{digits(rng, 3)}-{digits(rng, 4)}"
    if form == "full":
        return f"{post} {pref}{town}{chome}"
    if form == "hyphen_building":
        head = f"{pref}{town}{rng.randint(1, 9)}-{rng.randint(1, 30)}-{rng.randint(1, 20)}"
        return head + f" サンプルハイツ{rng.randint(101, 909)}号室"
    return f"{pref}{town}{chome}"


def _en_addr(rng: random.Random, form: str) -> str:
    st = rng.choice(["Example Street", "Sample Avenue", "Testing Road", "Placeholder Lane"])
    n = rng.randint(10, 9999)
    if form == "full":
        return f"{n} {st}, Springfield, IL {digits(rng, 5)}"
    return f"{n} {st}, Apt {rng.randint(1, 40)}"


def _email(rng: random.Random, form: str) -> str:
    user = rng.choice(["chen", "yamada", "a.tester", "pt"]) + digits(rng, 2)
    dom = rng.choice(["example.com", "example.org", "example.net"])
    if form == "plus":
        return f"{user}+clinic@{dom}"
    if form == "fullwidth_at":
        return f"{user}＠{dom}"
    return f"{user}@{dom}"


def _dob_values(rng: random.Random, lang: str) -> dict[str, str]:
    y, m, d = _date(rng)
    r = y - 1911
    mon = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ][m - 1]
    era = ("昭和", y - 1925, "S") if y >= 1926 else ("大正", y - 1911, "T")
    if y >= 1989:
        era = ("平成", y - 1988, "H")
    out = {
        "iso": f"{y}-{m:02d}-{d:02d}",
        "slash_ymd": f"{y}/{m:02d}/{d:02d}",
        "dotted": f"{y}.{m:02d}.{d:02d}",
        "compact8": f"{y}{m:02d}{d:02d}",
        "nen_gappi": f"{y}年{m}月{d}日",
        "nen_gappi_fullwidth": fw(f"{y}") + "年" + fw(f"{m}") + "月" + fw(f"{d}") + "日",
    }
    if lang == "zh-TW":
        out |= {
            "roc_nen": f"民國{r}年{m}月{d}日",
            "roc_slash": f"{r}/{m:02d}/{d:02d}",
            "roc_dot": f"{r}.{m}.{d}",
            "roc_compact": f"{r:03d}{m:02d}{d:02d}",
            "roc_numerals": f"民國{zh_numeral(r)}年{zh_numeral(m)}月{zh_numeral(d)}日",
        }
    if lang == "ja":
        out |= {"era_kanji": f"{era[0]}{era[1]}年{m}月{d}日", "era_letter": f"{era[2]}{era[1]}.{m}.{d}"}
    if lang == "en":
        out |= {
            "slash_dmy": f"{d:02d}/{m:02d}/{y}",
            "slash_mdy": f"{m:02d}/{d:02d}/{y}",
            "month_name": f"{mon} {d}, {y}",
            "day_month_abbr": f"{d} {mon[:3]} {y}",
            "two_digit_year": f"{m:02d}/{d:02d}/{y % 100:02d}",
        }
    return out


DOB_LABEL = {"zh-TW": "出生日期：", "ja": "生年月日：", "en": "DOB: "}
BORN_AFTER = {"zh-TW": "出生", "ja": "生まれ", "en": None}


def bind(f: Callable[..., Item], *args: Any) -> Gen:
    """A generator of one form: ``f(rng, *args)``."""
    return lambda r: f(r, *args)


def _han(r: random.Random, n: int, suffix: str = "") -> Item:
    return name_item("", *_zh_name(r, n), suffix)


def _pl(r: random.Random, fn: Callable[..., str], *args: Any) -> Item:
    return plain(fn(r, *args))


def _lab_digits(r: random.Random, label: str, n: int) -> Item:
    return labelled(label, digits(r, n))


def _dob_label(r: random.Random, lang: str, form: str) -> Item:
    return labelled(DOB_LABEL[lang], _dob_values(r, lang)[form])


def _dob_born(r: random.Random, lang: str, form: str, born: str) -> Item:
    v = _dob_values(r, lang)[form]
    return Item(v + born, (0, len(v)), labelled=True)


def _arc_old(r: random.Random) -> str:
    return r.choice("ABCDEF") + r.choice("ABCD") + digits(r, 8)


def _arc_new(r: random.Random) -> str:
    return tw_id(r, r.choice("89"))


def _tw_id_fw(r: random.Random) -> str:
    return fw(tw_id(r))


def _my_number_spaced(r: random.Random) -> str:
    return f"{digits(r, 4)} {digits(r, 4)} {digits(r, 4)}"


def _insurance_symbol_no(r: random.Random) -> Item:
    return labelled("被保険者証 記号・番号：", f"{digits(r, 4)}・{digits(r, 3)}")


def _ssn(r: random.Random) -> str:
    return f"9{digits(r, 2)}-{digits(r, 2)}-{digits(r, 4)}"


def _letter_7(r: random.Random) -> str:
    return r.choice("ABCDEFGH") + digits(r, 7)


def _digits_fw(r: random.Random, n: int) -> str:
    return fw(digits(r, n))


def forms(lang: str) -> list[tuple[str, str, Gen]]:
    """``(kind, form, generator)`` of every identifier planted in notes of ``lang``."""
    out: list[tuple[str, str, Gen]] = []

    def add(kind: str, form: str, gen: Gen) -> None:
        out.append((kind, form, gen))

    if lang == "zh-TW":
        for n in (2, 3, 4):
            add("name", f"han_{n}", bind(_han, n))
        for suf in ("先生", "女士", "醫師"):
            add("name", f"han_3_{suf}", bind(_han, 3, suf))
    if lang in ("zh-TW", "en"):
        add("name", "wade_giles_family_first", bind(_roman, False, False))
        add("name", "wade_giles_given_first", bind(_roman, False, True))
        add("name", "pinyin_family_first", bind(_roman, True, False))
        add("name", "pinyin_given_first", bind(_roman, True, True))
    if lang == "ja":
        add("name", "kanji", bind(_ja, 0, False))
        add("name", "kanji_space", bind(_ja, 0, True))
        add("name", "katakana_space", bind(_ja, 1, True))
        add("name", "hiragana_space", bind(_ja, 2, True))
        for suf in ("様", "さん", "殿", "先生"):
            add("name", f"kanji_{suf}", bind(_ja, 0, False, suf))
        add("name", "hepburn_family_first", bind(_hepburn, True))
        add("name", "hepburn_given_first", bind(_hepburn, False))
    if lang == "en":
        for f in ("first_last", "last_comma_first", "middle_initial", "dr", "mr", "ms", "initials"):
            add("name", f, bind(_en, f))
    # national and residence numbers
    if lang in ("zh-TW", "en"):
        add("national_id", "tw_id", bind(_pl, tw_id))
        add("national_id", "tw_arc_old", bind(_pl, _arc_old))
        add("national_id", "tw_arc_new", bind(_pl, _arc_new))
    if lang == "zh-TW":
        add("national_id", "tw_id_fullwidth", bind(_pl, _tw_id_fw))
    if lang == "ja":
        add("national_id", "my_number", bind(_pl, digits, 12))
        add("national_id", "my_number_spaced", bind(_pl, _my_number_spaced))
        add("national_id", "my_number_fullwidth", bind(_pl, _digits_fw, 12))
        add("national_id", "insurer_no", bind(_lab_digits, "保険者番号：", 8))
        add("national_id", "insurance_symbol_no", bind(_insurance_symbol_no))
    if lang == "en":
        add("national_id", "us_ssn", bind(_pl, _ssn))
    # chart numbers: bare (the site pattern is 8 digits), CGRD-like letter forms, and after each label
    add("chart", "bare_8", bind(_pl, digits, 8))
    add("chart", "bare_7", bind(_pl, digits, 7))
    add("chart", "letter_7", bind(_pl, _letter_7))
    chart_labels = {
        "zh-TW": ["病歷號：", "病歷號碼 ", "病歷號碼：", "ID:", "MRN "],
        "ja": ["カルテ番号：", "カルテNo.", "患者ID：", "ID:"],
        "en": ["MRN ", "MRN: ", "Chart No. ", "Hospital No.: ", "ID: "],
    }[lang]
    for lab in chart_labels:
        add("chart", "label_" + lab.strip(" :：.").replace(" ", "_"), bind(_lab_digits, lab, 8))
    # phones
    tw_phones = ("mobile_hyphen", "mobile_plain", "mobile_space", "mobile_intl", "mobile_intl_space")
    if lang in ("zh-TW", "en"):
        for f in (*tw_phones, "landline_paren", "landline_hyphen", "landline_ext"):
            add("phone", "tw_" + f, bind(_pl, _tw_phone, f))
    if lang == "zh-TW":
        add("phone", "tw_mobile_fullwidth", bind(_pl, _tw_phone, "mobile_fullwidth"))
    if lang == "ja":
        for f in ("mobile", "landline", "intl", "plain", "fullwidth"):
            add("phone", "jp_" + f, bind(_pl, _jp_phone, f))
    if lang == "en":
        for f in ("paren", "hyphen", "intl"):
            add("phone", "na_" + f, bind(_pl, _na_phone, f))
    # addresses
    if lang == "zh-TW":
        for f in ("full", "no_postcode", "floor_unit"):
            add("address", "tw_" + f, bind(_pl, _tw_addr, f))
    if lang == "ja":
        for f in ("full", "hyphen_building", "no_postcode"):
            add("address", "jp_" + f, bind(_pl, _jp_addr, f))
    if lang == "en":
        for f in ("full", "apt"):
            add("address", "en_" + f, bind(_pl, _en_addr, f))
    # e-mail
    for f in ("ascii", "plus", "fullwidth_at"):
        add("email", f, bind(_pl, _email, f))
    # dates of birth: after the label, and (zh-TW, ja) before the word for born (the value is what comes before it)
    born = BORN_AFTER[lang]
    for f in _dob_values(random.Random(0), lang):
        add("dob", "label_" + f, bind(_dob_label, lang, f))
        if born:
            add("dob", "born_" + f, bind(_dob_born, lang, f, born))
    return out


LABELS = {
    "name": {"zh-TW": "姓名：", "ja": "氏名：", "en": "Name: "},
    "national_id": {"zh-TW": "身分證號：", "ja": "番号：", "en": "ID No.: "},
    "chart": {"zh-TW": "病歷號：", "ja": "カルテ番号：", "en": "MRN: "},
    "phone": {"zh-TW": "電話：", "ja": "電話：", "en": "Phone: "},
    "address": {"zh-TW": "地址：", "ja": "住所：", "en": "Address: "},
    "email": {"zh-TW": "電子郵件：", "ja": "メール：", "en": "Email: "},
    "dob": {"zh-TW": "", "ja": "", "en": ""},
}
ADJ = {"zh-TW": ("聯絡", "已確認"), "ja": ("連絡先", "確認済"), "en": ("(", ")")}


# ---------------------------------------------------------------------------------------------- notes
def fillers(lang: str) -> list[str]:
    from tools.synth import notes, notes_en, notes_ja

    return list({"zh-TW": notes, "ja": notes_ja, "en": notes_en}[lang].FILLER)


def base_note(rng: random.Random, lang: str) -> list[str]:
    return rng.sample(fillers(lang), 3)


def plant(sents: list[str], it: Item, pos: str, lang: str, kind: str) -> tuple[str, int, int, Item]:
    """The note text, and where the planted surface starts and ends in it. ``line_break`` puts a line break inside
    the value (between family and given name for a name)."""
    sp = " " if lang == "en" else ""
    end = ". " if lang == "en" else "。"
    if pos == "line_break":
        a, b = it.v
        cut = it.fam[1] if it.fam and it.fam[1] < b else a + max(1, (b - a) // 2)
        s = it.surface[:cut] + "\n" + it.surface[cut:]

        def shift(x: int) -> int:
            return x + 1 if x >= cut else x

        it = Item(s, (shift(a), shift(b)), (shift(it.fam[0]), shift(it.fam[1])) if it.fam else None, it.labelled)
    label = "" if it.labelled else LABELS[kind][lang]
    if pos == "start":
        pre, post = "", sp + "".join(sents)
    elif pos == "end":
        pre, post = "".join(sents) + sp, ""
    elif pos == "label":
        pre, post = sents[0] + label, end + "".join(sents[1:])
    elif pos == "table":
        pre, post = sents[0] + "\n" + (label.rstrip(" :：") or "欄") + "\t", "\t" + "備註\n" + "".join(sents[1:])
    elif pos == "cjk_adjacent":
        pre, post = sents[0] + ADJ[lang][0], ADJ[lang][1] + sp + "".join(sents[1:])
    else:  # middle, line_break
        pre, post = sents[0] + sp, sp + "".join(sents[1:])
    text = pre + it.surface + post
    return text, len(pre), len(pre) + len(it.surface), it


class PlantError(RuntimeError):
    """The planted value is not where the harness put it: a harness error, never a masker result."""


def judge(text: str, out: str, start: int, it: Item, mask_char: str) -> str:
    """``leaked``, ``partly`` (some characters masked, not all) or ``masked``; see the module's leak rule."""
    if len(out) != len(text):
        raise PlantError("the masker changed the length; the leak rule reads by place")
    a, b = start + it.v[0], start + it.v[1]
    val = [i for i in range(a, b) if text[i] not in SEPARATORS]
    if not val or text[a:b] != it.surface[it.v[0] : it.v[1]]:
        raise PlantError("the value is not in the input")
    kept = [i for i in val if out[i] != mask_char]
    if it.fam:
        fam = range(start + it.fam[0], start + it.fam[1])
        rest = [i for i in kept if i not in fam]
        if all(out[i] != mask_char for i in fam if text[i] not in SEPARATORS) and rest:
            return "leaked"
    elif len(kept) == len(val):
        return "leaked"
    return "masked" if not kept else "partly"


# ---------------------------------------------------------------------------------------------- clinical strings
def clinical(lang: str) -> list[tuple[str, Callable[[random.Random], str]]]:
    """``(kind, generator)`` of the clinical strings screening criteria read."""

    def y(r: random.Random) -> int:
        return r.randint(2015, 2025)

    def m(r: random.Random) -> int:
        return r.randint(1, 12)

    def d(r: random.Random) -> int:
        return r.randint(1, 28)

    out: list[tuple[str, Callable[[random.Random], str]]] = [
        (
            "lab_value",
            lambda r: r.choice(
                [
                    f"HbA1c {r.randint(55, 120) / 10}%",
                    f"eGFR {r.randint(15, 110)} mL/min/1.73m2",
                    f"Cr {r.randint(5, 30) / 10} mg/dL",
                    f"WBC {r.randint(3000, 15000)}/uL",
                    f"PLT {r.randint(80, 400)}x10^3/uL",
                    f"ANC {r.randint(500, 5000)}/mm3",
                ]
            ),
        ),
        (
            "dose",
            lambda r: r.choice(
                [
                    f"Metformin {r.choice([500, 850, 1000])} mg BID",
                    "Pembrolizumab 200 mg q3w",
                    f"Prednisolone {r.randint(5, 60)} mg QD",
                    f"Insulin glargine {r.randint(6, 40)} U",
                ]
            ),
        ),
        ("staging", lambda r: r.choice(["T2N1M0", "cT2aN2M0", "stage IIIB", "pT1cN0M0 stage IA3"])),
        (
            "score",
            lambda r: r.choice(
                [
                    f"ECOG {r.randint(0, 3)}",
                    f"ECOG PS {r.randint(0, 3)}",
                    f"NYHA {r.choice(['I', 'II', 'III'])}",
                    f"MMSE {r.randint(10, 30)}/30",
                ]
            ),
        ),
        (
            "gene_variant",
            lambda r: r.choice(
                ["EGFR L858R", "EGFR exon 19 deletion", "KRAS G12C", "ALK fusion", "BRCA1 c.68_69delAG", "HER2 3+"]
            ),
        ),
        (
            "trial_id",
            lambda r: r.choice(
                [f"NCT0{r.randint(1000000, 6999999)}", f"protocol TBX-{r.randint(100, 999)}-{r.randint(10, 99)}"]
            ),
        ),
        ("code", lambda r: r.choice(["ICD-10 E11.9", "C34.1", "ICD-10-CM C50.911", "ATC A10BA02", "ATC L01FF02"])),
        ("accession_10", lambda r: f"{y(r) % 100:02d}{m(r):02d}{d(r):02d}{r.randint(1000, 9999)}"),
        ("date_compact8", lambda r: f"{y(r)}{m(r):02d}{d(r):02d}"),
        ("date_iso", lambda r: f"{y(r)}-{m(r):02d}-{d(r):02d}"),
        ("date_slash", lambda r: f"{y(r)}/{m(r):02d}/{d(r):02d}"),
    ]
    if lang == "zh-TW":
        out += [
            ("age", lambda r: f"{r.randint(20, 89)}歲"),
            (
                "duration",
                lambda r: r.choice([f"{r.randint(2, 11)}個月前", "三個月前", "半年前", f"{r.randint(2, 9)}年前"]),
            ),
            (
                "date_roc",
                lambda r: r.choice(
                    [
                        f"民國{y(r) - 1911}年{m(r)}月{d(r)}日",
                        f"{y(r) - 1911}/{m(r):02d}/{d(r):02d}",
                        f"{y(r) - 1911}.{m(r)}.{d(r)}",
                        f"{y(r) - 1911}{m(r):02d}{d(r):02d}",
                    ]
                ),
            ),
            ("date_nen", lambda r: f"{y(r)}年{m(r)}月{d(r)}日"),
        ]
    if lang == "ja":
        out += [
            ("age", lambda r: f"{r.randint(20, 89)}歳"),
            ("duration", lambda r: r.choice([f"{r.randint(2, 11)}か月前", "半年前", f"{r.randint(2, 9)}年前"])),
            (
                "date_era",
                lambda r: r.choice(
                    [
                        f"令和{r.randint(1, 7)}年{m(r)}月{d(r)}日",
                        f"R{r.randint(1, 7)}.{m(r)}.{d(r)}",
                        f"平成{r.randint(1, 30)}年{m(r)}月{d(r)}日",
                    ]
                ),
            ),
            ("date_nen", lambda r: f"{y(r)}年{m(r)}月{d(r)}日"),
        ]
    if lang == "en":
        mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        out += [
            (
                "age",
                lambda r: r.choice(
                    [f"{r.randint(20, 89)}-year-old", f"{r.randint(20, 89)} y/o", f"aged {r.randint(20, 89)}"]
                ),
            ),
            (
                "duration",
                lambda r: r.choice([f"{r.randint(2, 11)} months ago", "6 weeks ago", f"for {r.randint(2, 9)} years"]),
            ),
            ("date_month_name", lambda r: f"{r.choice(mon)} {d(r)}, {y(r)}"),
            ("date_mdy", lambda r: f"{m(r):02d}/{d(r):02d}/{y(r)}"),
        ]
    return out


# ---------------------------------------------------------------------------------------------- the run
@dataclass
class Engines:
    mask: Callable[[str], str]
    tripwire: Callable[[str], bool]
    mask_char: str
    mrn_regex: str | None


def engines() -> Engines:
    from guard.guard import Guard
    from tb_common.phi_guard import MASK_CHAR, mask_note, site_mrn_regex

    rx = site_mrn_regex()
    g = Guard.from_settings()
    return Engines(lambda t: mask_note(t, rx), lambda t: g.tripwire(t).hit, MASK_CHAR, rx)


def _shape(s: str) -> str:
    """An example for the record without its digits (the data scan would read a planted number as a real one)."""
    return re.sub(r"[0-9０-９]", "d", s.replace("\n", "⏎").replace("\t", "⇥"))


def cases(lang: str, per_form: int, seed: int = SEED) -> Iterator[tuple[str, str, str, str, int, Item]]:
    """``(kind, form, position, text, start, item)`` of every planted note of ``lang``, deterministic."""
    rng = random.Random(f"{seed}:{lang}")
    for kind, form, gen in forms(lang):
        for i in range(per_form):
            pos = POSITIONS[i % len(POSITIONS)]
            it = gen(rng)
            text, start, _end, it = plant(base_note(rng, lang), it, pos, lang, kind)
            yield kind, form, pos, text, start, it


def per_form(lang: str) -> int:
    n = len(forms(lang))
    return max(len(POSITIONS), math.ceil(MIN_NOTES / n / len(POSITIONS)) * len(POSITIONS))


def run(eng: Engines, per: int | None = None, seed: int = SEED, langs: tuple[str, ...] = LANGS) -> dict[str, Any]:
    t0 = time.monotonic()
    cells: dict[str, Any] = {}
    control: dict[str, Any] = {}
    for lang in langs:
        k = per or per_form(lang)
        rng = random.Random(f"{seed}:control:{lang}")
        base = ["".join(base_note(rng, lang)) for _ in range(200)]
        control[lang] = {
            "notes": len(base),
            "masked_chars": sum(eng.mask(t).count(eng.mask_char) for t in base),
            "tripwire_hits": sum(eng.tripwire(t) for t in base),
        }
        for kind, form, pos, text, start, it in cases(lang, k, seed):
            out = eng.mask(text)
            verdict = judge(text, out, start, it, eng.mask_char)
            tw_leak = not eng.tripwire(text)
            c = cells.setdefault(
                f"{lang}|{kind}|{form}",
                {
                    "planted": 0,
                    "leaked": 0,
                    "partly": 0,
                    "tripwire_missed": 0,
                    "examples": [],
                    "positions": {},
                    "planted_at": {},
                },
            )
            c["planted"] += 1
            c["planted_at"][pos] = c["planted_at"].get(pos, 0) + 1
            c["leaked"] += verdict == "leaked"
            c["partly"] += verdict == "partly"
            c["tripwire_missed"] += tw_leak
            if verdict == "leaked":
                c["positions"][pos] = c["positions"].get(pos, 0) + 1
                if len(c["examples"]) < 5:
                    a = start + it.v[0]
                    c["examples"].append(
                        {
                            "position": pos,
                            "value_shape": _shape(it.surface[it.v[0] : it.v[1]]),
                            "output": _shape(out[max(0, a - 12) : start + it.v[1] + 12]),
                        }
                    )
    over: dict[str, Any] = {}
    for lang in langs:
        rng = random.Random(f"{seed}:clinical:{lang}")
        sp = " " if lang == "en" else ""
        for kind, gen in clinical(lang):
            o = over.setdefault(f"{lang}|{kind}", {"planted": 0, "altered": 0, "tripwire_hits": 0, "examples": []})
            for i in range(60):
                s = gen(rng)
                sents = base_note(rng, lang)
                pre = ["", sents[0] + sp, "".join(sents) + sp][i % 3]
                text = pre + s + sp + ("".join(sents[1:]) if i % 3 == 1 else "")
                if text[len(pre) : len(pre) + len(s)] != s:
                    raise PlantError("clinical string not in the input")
                out = eng.mask(text)
                got = out[len(pre) : len(pre) + len(s)]
                o["planted"] += 1
                o["tripwire_hits"] += eng.tripwire(text)
                if got != s:
                    o["altered"] += 1
                    if len(o["examples"]) < 5:
                        o["examples"].append({"input": _shape(s), "output": _shape(got)})
    for c in list(cells.values()) + list(over.values()):
        c["per_thousand"] = round(1000 * c.get("leaked", c.get("altered", 0)) / c["planted"], 1)
    return {
        "card": "V-5",
        "date": "2026-11-17",
        "seed": seed,
        "entry_points": {
            "mask": "tb_common.phi_guard.mask_note(text, site_mrn_regex()) as at services/lake/store.py:1463",
            "tripwire": "guard.Guard.from_settings().tripwire(text) as at services/gateway/core.py:579",
        },
        "site_mrn_regex": eng.mrn_regex,
        "control_unplanted": control,
        "cells": dict(sorted(cells.items())),
        "over_masking": dict(sorted(over.items())),
        "seconds": round(time.monotonic() - t0, 1),
    }


# ---------------------------------------------------------------------------------------------- tables
def _pt(n: int, d: int) -> str:
    return f"{1000 * n / d:.1f}" if d else "-"


def tables(data: dict[str, Any]) -> dict[str, str]:
    cells = data["cells"]
    by_lang: dict[str, list[int]] = {}
    by_kind: dict[tuple[str, str], list[int]] = {}
    for key, c in cells.items():
        lang, kind, _form = key.split("|")
        for agg in (by_lang.setdefault(lang, [0, 0, 0, 0]), by_kind.setdefault((lang, kind), [0, 0, 0, 0])):
            agg[0] += c["planted"]
            agg[1] += c["leaked"]
            agg[2] += c["partly"]
            agg[3] += c["tripwire_missed"]
    tot = [sum(v[i] for v in by_lang.values()) for i in range(4)]
    s = [
        "| Language | Planted notes | Leaked (masker) | Per 1,000 | Partly masked | Tripwire missed | Per 1,000 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for lang, v in [*sorted(by_lang.items()), ("all", tot)]:
        s.append(f"| {lang} | {v[0]} | {v[1]} | {_pt(v[1], v[0])} | {v[2]} | {v[3]} | {_pt(v[3], v[0])} |")
    k = [
        "| Language | Kind | Planted | Leaked | Per 1,000 | Tripwire missed | Per 1,000 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for (lang, kind), v in sorted(by_kind.items()):
        k.append(f"| {lang} | {kind} | {v[0]} | {v[1]} | {_pt(v[1], v[0])} | {v[3]} | {_pt(v[3], v[0])} |")
    f = [
        "| Language | Kind | Form | Planted | Leaked | Per 1,000 | Partly | Tripwire missed | Leaked at |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for key, c in cells.items():
        if c["leaked"] or c["partly"] or c["tripwire_missed"]:
            lang, kind, form = key.split("|")
            where = ", ".join(f"{p} {n}" for p, n in sorted(c["positions"].items()))
            f.append(
                f"| {lang} | {kind} | {form} | {c['planted']} | {c['leaked']} | {c['per_thousand']} | "
                f"{c['partly']} | {c['tripwire_missed']} | {where} |"
            )
    clean = sorted(key for key, c in cells.items() if not (c["leaked"] or c["partly"] or c["tripwire_missed"]))
    f.append("")
    f.append(f"Clean cells (no leak, no partial mask, no tripwire miss): {len(clean)} of {len(cells)}.")
    o = [
        "| Language | Clinical kind | Planted | Altered (masker) | Per 1,000 | Tripwire hits | Example (digits as d) |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for key, c in data["over_masking"].items():
        lang, kind = key.split("|")
        ex = f"`{c['examples'][0]['input']}` → `{c['examples'][0]['output']}`" if c["examples"] else ""
        o.append(
            f"| {lang} | {kind} | {c['planted']} | {c['altered']} | {c['per_thousand']} | {c['tripwire_hits']} | {ex} |"
        )
    pos_n: dict[tuple[str, str], list[int]] = {}
    for key, c in cells.items():
        lang = key.split("|")[0]
        for p in POSITIONS:
            v = pos_n.setdefault((lang, p), [0, 0])
            v[0] += c["planted_at"].get(p, 0)
            v[1] += c["positions"].get(p, 0)
    langs = sorted({k[0] for k in pos_n})
    ps = [
        "| Position | " + " | ".join(f"{lang} leaked / planted (per 1,000)" for lang in langs) + " |",
        "|---|" + "---:|" * len(langs),
    ]
    for p in POSITIONS:
        ps.append(
            f"| {p} | "
            + " | ".join(
                f"{pos_n[(lang, p)][1]} / {pos_n[(lang, p)][0]} ({_pt(pos_n[(lang, p)][1], pos_n[(lang, p)][0])})"
                for lang in langs
            )
            + " |"
        )
    ctl = ["| Language | Unplanted notes | Characters masked | Tripwire hits |", "|---|---:|---:|---:|"]
    for lang, c in data["control_unplanted"].items():
        ctl.append(f"| {lang} | {c['notes']} | {c['masked_chars']} | {c['tripwire_hits']} |")
    return {
        "summary": "\n".join(s),
        "kinds": "\n".join(k),
        "forms": "\n".join(f),
        "over": "\n".join(o),
        "control": "\n".join(ctl),
        "positions": "\n".join(ps),
    }


def _block(name: str) -> re.Pattern[str]:
    return re.compile(rf"(<!-- masking-leaks:{name}:begin -->\n)(.*?)(\n<!-- masking-leaks:{name}:end -->)", re.S)


def render(page: str, data: dict[str, Any]) -> str:
    for name, body in tables(data).items():
        rx = _block(name)
        if not rx.search(page):
            raise SystemExit(f"the page has no generated block {name!r}")
        m = rx.search(page)
        assert m is not None
        page = page[: m.start(2)] + body + page[m.end(2) :]
    return page


def check(page_path: Path = PAGE_PATH, json_path: Path = JSON_PATH) -> list[str]:
    """The generated blocks of the page that differ from what ``leaks.json`` gives (empty when none)."""
    page = page_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    want = tables(data)
    bad = []
    for name, body in want.items():
        m = _block(name).search(page)
        if not m or m.group(2) != body:
            bad.append(name)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="run, write leaks.json and the page's generated tables")
    g.add_argument("--check", action="store_true", help="the page's generated tables equal leaks.json")
    a = ap.parse_args(argv)
    if a.check:
        bad = check()
        print("masking-leaks: page and leaks.json agree" if not bad else f"masking-leaks: blocks differ: {bad}")
        return 1 if bad else 0
    data = run(engines())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    PAGE_PATH.write_text(render(PAGE_PATH.read_text(encoding="utf-8"), data), encoding="utf-8")
    n = sum(c["planted"] for c in data["cells"].values())
    print(f"masking-leaks: {n} planted notes, {data['seconds']} s; wrote {JSON_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
