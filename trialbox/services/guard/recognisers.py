"""PHI recognisers for Taiwan and Japan (spec v4 §7.14, §8.6 layer 2; S1-08).

Pattern and dictionary recognisers with span output, so the same detector serves the gateway tripwire (any hit
blocks) and the trace store (redaction at write). It folds in :mod:`tb_common.phi_guard`: the v1 surname
dictionaries, name patterns and :func:`tb_common.phi_guard.scan` are called, not copied.

Identifiers with a check digit (Taiwan national ID, ARC, Japanese My Number) are validated. A string of the right
shape with a wrong check digit is still redacted (kind ``ID_NUMBER``): over-redaction costs readability only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from tb_common import phi_guard

# ------------------------------------------------------------------------------------------------ check digits
_TW_LETTER = {
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
_TW_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 1, 1)


def tw_id_valid(value: str) -> bool:
    """Taiwan national ID and new-format ARC (``[A-Z][1289]\\d{8}``): weighted sum of the letter code and the nine
    digits is a multiple of 10. Old-format ARC (``[A-Z][A-D]\\d{8}``): the second letter contributes the units
    digit of its code."""
    if len(value) != 10 or value[0] not in _TW_LETTER or not value[2:].isdigit():
        return False
    code = _TW_LETTER[value[0]]
    total = code // 10 + (code % 10) * 9
    second = value[1]
    if second.isdigit():
        digits = [int(c) for c in value[1:]]
    elif second in "ABCD":
        digits = [_TW_LETTER[second] % 10] + [int(c) for c in value[2:]]
    else:
        return False
    total += sum(d * w for d, w in zip(digits, _TW_WEIGHTS, strict=True))
    return total % 10 == 0


def tw_id_check_digit(prefix9: str) -> str:
    """The check digit that completes a 9-character prefix (letter + 8 characters); used by the generator."""
    for d in "0123456789":
        if tw_id_valid(prefix9 + d):
            return d
    raise ValueError(f"no check digit for {prefix9!r}")


def my_number_check_digit(first11: str) -> int:
    """Japanese Individual Number: 11 - (Σ P_n·Q_n mod 11), 0 when the remainder is ≤ 1 (P_n from the right)."""
    digits = [int(c) for c in reversed(first11)]
    total = sum(p * (n + 1 if n <= 6 else n - 5) for n, p in enumerate(digits, start=1))
    r = total % 11
    return 0 if r <= 1 else 11 - r


def my_number_valid(value: str) -> bool:
    v = re.sub(r"[\s-]", "", value)
    return len(v) == 12 and v.isdigit() and my_number_check_digit(v[:11]) == int(v[11])


# ------------------------------------------------------------------------------------------------ patterns
_CJK = "一-鿿"
_KANA = "぀-ヿ"
TW_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![0-9])")
TW_ARC = re.compile(r"(?<![A-Za-z0-9])[A-Z](?:[89]\d{8}|[A-D]\d{8})(?![0-9])")
MY_NUMBER = re.compile(r"(?<![\d-])\d{4}[ -]?\d{4}[ -]?\d{4}(?![\d-])")
PHONE_TW = re.compile(
    r"(?<![\d+])(?:\+886[-\s]?|0)(?:9\d{2}[-\s]?\d{3}[-\s]?\d{3}|[2-8][-\s]?\d{3,4}[-\s]?\d{4})(?!\d)"
    r"|\(0[2-8]\)\s?\d{3,4}[-\s]?\d{4}(?!\d)"
)
PHONE_JP = re.compile(
    r"(?<![\d+])(?:\+81[-\s]?(?:[789]0|\d{1,4})[-\s]\d{1,4}[-\s]\d{4}"
    r"|0[789]0[-\s]?\d{4}[-\s]?\d{4}"
    r"|0\d{1,4}-\d{1,4}-\d{4})(?!\d)"
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PASSPORT_JP = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{7}(?![0-9])")
PASSPORT_CTX = re.compile(
    r"(?:護照(?:號碼|号码|號)?|旅券(?:番号)?|パスポート(?:番号)?|(?i:passport)(?:\s*(?:no\.?|number|#))?)"
    r"[\s:：#]*(?P<v>[A-Z0-9]{6,9})(?![A-Za-z0-9])"
)
MRN_CTX = re.compile(
    r"(?:病歷號(?:碼)?|病历号|カルテ番号|患者ID|(?i:MRN|chart\s*no\.?|medical record (?:no\.?|number)))"
    r"[\s:：#]*(?P<v>[A-Z0-9][A-Z0-9-]{3,14})(?![A-Za-z0-9])"
)
_NUM = r"[0-9０-９一二三四五六七八九十]+"
ADDRESS_ZH = re.compile(
    rf"(?:[{_CJK}]{{1,3}}(?:縣|市))?(?:[{_CJK}]{{1,3}}(?:區|鄉|鎮|市))?[{_CJK}]{{1,5}}(?:路|街|大道)"
    rf"(?:{_NUM}段)?(?:{_NUM}巷)?(?:{_NUM}弄)?{_NUM}(?:之{_NUM})?號(?:{_NUM}樓(?:之{_NUM})?)?"
)
ADDRESS_JA = re.compile(
    rf"(?:東京都|北海道|大阪府|京都府|[{_CJK}]{{2,3}}県)[{_CJK}{_KANA}]{{1,10}}?(?:市|区|町|村|郡)"
    rf"[{_CJK}{_KANA}]{{0,8}}?[0-9０-９]+(?:(?:丁目|番地?|号|[-－ー])[0-9０-９]*){{1,4}}"
)
ADDRESS_EN = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Boulevard|Blvd|Drive|Dr|Way)\b\.?"
    r"(?:,\s*(?:Apt\.?|Unit|Suite)\s*\d+)?(?:,\s*[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)?"
)
_DATE = (
    r"(?:(?:19|20)\d{2}[/\-.]\d{1,2}[/\-.]\d{1,2}|(?:19|20)\d{2}年\s?\d{1,2}月\s?\d{1,2}日"
    r"|民國\s?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日|(?:昭和|平成|令和)\s?(?:\d{1,2}|元)年\s?\d{1,2}月\s?\d{1,2}日"
    r"|\d{1,2}/\d{1,2}/(?:19|20)\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d{2})"
)
DOB = re.compile(rf"(?:生日|出生(?:日期)?|生年月日|誕生日|(?i:DOB|date of birth|born(?: on)?))[\s:：]*(?P<v>{_DATE})")

_SURNAMES_ROC = (
    "|".join(sorted(phi_guard.ROC_COMPOUND, key=len, reverse=True))
    + "|["
    + "".join(sorted(phi_guard.ROC_SURNAMES))
    + "]"
)
_SURNAMES_JP = "|".join(sorted(phi_guard.JP_SURNAMES, key=len, reverse=True))
_LABEL = r"(?:姓名|氏名|名前|患者|病人|病患|個案|受試者|案主|被保険者)[\s:：]*"
NAME_ZH_CTX = re.compile(rf"{_LABEL}(?P<v>(?:{_SURNAMES_ROC})[{_CJK}]{{1,2}})")
NAME_JA_CTX = re.compile(rf"{_LABEL}(?P<v>(?:{_SURNAMES_JP})[\s　]?[{_CJK}{_KANA}]{{1,3}})")
NAME_JA_HON = re.compile(rf"(?P<v>(?:{_SURNAMES_JP})[\s　]?[{_CJK}{_KANA}]{{1,3}}?)\s?{phi_guard.HONORIFIC}")
NAME_ZH_SEX = re.compile(rf"(?P<v>(?:{_SURNAMES_ROC})[{_CJK}]{{1,2}})[，,、\s]*[（(]?(?:男|女)[)）]?")
NAME_EN_CTX = re.compile(
    r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+|\b(?:Patient(?: name)?|Name|Pt)\s*[:：]\s*)"
    r"(?P<v>[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)?)"
)


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int
    valid: bool = True  # check digit valid (where the kind has one)


def _spans(rx: re.Pattern[str], text: str, kind: str, group: str | None = None) -> Iterator[Finding]:
    for m in rx.finditer(text):
        if group and m.groupdict().get(group) is not None:
            yield Finding(kind, m.start(group), m.end(group))
        else:
            yield Finding(kind, m.start(), m.end())


def _ids(text: str) -> Iterator[Finding]:
    for m in TW_ID.finditer(text):
        ok = tw_id_valid(m.group(0))
        yield Finding("TW_NATIONAL_ID" if ok else "ID_NUMBER", m.start(), m.end(), ok)
    for m in TW_ARC.finditer(text):
        ok = tw_id_valid(m.group(0))
        yield Finding("TW_ARC" if ok else "ID_NUMBER", m.start(), m.end(), ok)
    for m in MY_NUMBER.finditer(text):
        ok = my_number_valid(m.group(0))
        yield Finding("JP_MY_NUMBER" if ok else "ID_NUMBER", m.start(), m.end(), ok)


def _v1_names(text: str) -> Iterator[Finding]:
    """Names found by the v1 guard (tb_common.phi_guard), located in the text."""
    for name in phi_guard._cjk_names(text):
        start = 0
        while (i := text.find(name, start)) >= 0:
            yield Finding("NAME", i, i + len(name))
            start = i + 1
    yield from _spans(phi_guard.EN_NAME, text, "NAME")


def _mrn(text: str, mrn_regex: str | None) -> Iterator[Finding]:
    yield from _spans(MRN_CTX, text, "MRN", "v")
    if mrn_regex:
        body = mrn_regex.strip("^$")
        for m in re.finditer(rf"(?<![0-9A-Za-z\-/.]){body}(?![0-9A-Za-z\-/.])", text):
            yield Finding("MRN", m.start(), m.end())


Recogniser = Callable[[str], Iterator[Finding]]


def recognisers(mrn_regex: str | None = None) -> list[tuple[str, Recogniser]]:
    return [
        ("ids", _ids),
        ("mrn", lambda t: _mrn(t, mrn_regex)),
        ("passport", lambda t: _spans(PASSPORT_CTX, t, "PASSPORT", "v")),
        ("passport_jp", lambda t: _spans(PASSPORT_JP, t, "PASSPORT")),
        ("phone_tw", lambda t: _spans(PHONE_TW, t, "PHONE")),
        ("phone_jp", lambda t: _spans(PHONE_JP, t, "PHONE")),
        ("email", lambda t: _spans(EMAIL, t, "EMAIL")),
        ("address_zh", lambda t: _spans(ADDRESS_ZH, t, "ADDRESS")),
        ("address_ja", lambda t: _spans(ADDRESS_JA, t, "ADDRESS")),
        ("address_en", lambda t: _spans(ADDRESS_EN, t, "ADDRESS")),
        ("dob", lambda t: _spans(DOB, t, "DOB", "v")),
        ("name_zh", lambda t: _spans(NAME_ZH_CTX, t, "NAME", "v")),
        ("name_zh_sex", lambda t: _spans(NAME_ZH_SEX, t, "NAME", "v")),
        ("name_ja", lambda t: _spans(NAME_JA_CTX, t, "NAME", "v")),
        ("name_ja_hon", lambda t: _spans(NAME_JA_HON, t, "NAME", "v")),
        ("name_en", lambda t: _spans(NAME_EN_CTX, t, "NAME", "v")),
        ("v1_names", _v1_names),
    ]
