"""PHI guard (SPEC §7.4): regex + dictionary scan run on the full text before any cloud LLM call.

Any hit disables cloud for the job (the local model is used) and the audit records ``phi_guard_hit=true``. A clean
scan returns a :class:`PhiClearance` bound to the text's sha256; ``tb_common.llm`` accepts cloud calls only with a
clearance for exactly the text being sent. The guard errs on the side of hits (false positives only cost latency).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from tb_common import dates
from tb_common.crypto import sha256_text

# ~100 most frequent ROC surnames (covers > 95 % of the population) + common compound surnames
ROC_SURNAMES = set(
    "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余趙盧梁顏柯翁魏孫戴范方宋鄧"
    "杜傅侯曹薛丁卓阮馬董温唐藍蔣石古紀姚連馮歐程湯黄田康姜汪白鄒尤巫鐘黎涂龔嚴韓袁金童陸夏柳凃邵錢伍倪溫于"
)
ROC_COMPOUND = {"歐陽", "司馬", "諸葛", "上官", "張簡", "范姜", "周黃", "陳李", "江謝", "張廖"}
JP_SURNAMES = {
    "佐藤",
    "鈴木",
    "高橋",
    "田中",
    "伊藤",
    "渡辺",
    "山本",
    "中村",
    "小林",
    "加藤",
    "吉田",
    "山田",
    "佐々木",
    "山口",
    "松本",
    "井上",
    "木村",
    "林",
    "斎藤",
    "清水",
    "山崎",
    "森",
    "池田",
    "橋本",
    "阿部",
    "石川",
    "山下",
    "中島",
    "石井",
    "小川",
    "前田",
    "岡田",
    "長谷川",
    "藤田",
    "後藤",
    "近藤",
    "村上",
    "遠藤",
    "青木",
    "坂本",
    "斉藤",
    "福田",
    "太田",
    "西村",
    "藤井",
    "金子",
    "岡本",
    "藤原",
    "中野",
    "三浦",
    "原田",
    "中川",
    "松田",
    "竹内",
    "小野",
    "田村",
    "中山",
    "和田",
}
HONORIFIC = r"(?:先生|小姐|女士|太太|老先生|老太太|阿嬤|阿公|君|さん|様|氏|くん|ちゃん)"
PATIENT_WORD = r"(?:病人|患者|個案|病患|案主|受試者)"
KEYWORDS = re.compile(
    r"病歷號(?:碼)?|身分證(?:字號)?|身份證|姓名|出生日期|聯絡電話|住址|患者ID|カルテ番号|氏名|生年月日"
)
TW_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![0-9])")
PHONE = re.compile(
    r"(?<!\d)(?:\+886[-\s]?9\d{2}|09\d{2})[-\s]?\d{3}[-\s]?\d{3}(?!\d)|(?<!\d)\(?0[2-8]\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"
)
# NEW-B-43 (D-744): an English phone number (North American, British or any with a country code). A local number of
# seven digits only after a word that says it is one (``Tel``, ``phone``, ``mobile``, ``contact``, ``number`` ...);
# the longer forms anywhere. Clinical ranges (100-300 mg, 4.5-11.0) and dates have neither shape. One pattern for the
# note masker, the gate before a call (:func:`scan`) and the guard service's recognisers. Group ``v``: the number.
_EN_PHONE_FULL = (
    r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?(?:[-.\s]?\d{2,4}){2,3}"  # any number with its country code
    r"|\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]\d{4}"  # North American: area code, exchange, line
    r"|0\d{2,4}\s\d{3,4}\s?\d{3,4}"  # British national: a leading 0, the area code, two groups
)
_EN_PHONE_LABEL = r"(?i:\b(?:tel(?:ephone)?|phone|ph|mobile|cell|fax|contact|call|number(?:\s+is)?)\b\.?)[\s:#.]*"
EN_PHONE = re.compile(
    rf"{_EN_PHONE_LABEL}(?P<v>(?:{_EN_PHONE_FULL}|\d{{3}}[-.]\d{{4}}))(?![\d-])"
    rf"|(?<![A-Za-z0-9+])(?:{_EN_PHONE_FULL})(?![\d-])"  # not inside a code (JLAC10 3D046 0000 019)
)
DATE = dates.PHI_SPAN  # Gregorian and 民國 written out (D-215: the pattern lives in tb_common.dates, unchanged)
EN_NAME = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|\bPatient(?: name)?:\s*[A-Z][a-z]+\s+[A-Z][a-z]+"
)


@dataclass(frozen=True)
class PhiClearance:
    """Proof that ``text_sha`` was scanned clean. Only :func:`scan` creates these."""

    text_sha: str


@dataclass
class PhiScan:
    hit: bool
    findings: list[tuple[str, str]] = field(default_factory=list)  # (kind, masked snippet)
    clearance: PhiClearance | None = None


def _mask(s: str) -> str:
    return s[0] + "*" * (len(s) - 1) if s else s


def _cjk_names(text: str) -> list[str]:
    hits: list[str] = []
    surname = "|".join(sorted(ROC_COMPOUND, key=len, reverse=True)) + "|[" + "".join(sorted(ROC_SURNAMES)) + "]"
    given = r"[一-鿿]{1,2}"
    pats = [
        rf"(?:{surname}){given}\s?{HONORIFIC}",
        rf"{PATIENT_WORD}[：:\s]?(?:{surname}){given}(?=[，,、\s(（]|$)",
        rf"(?:{surname}){given}[，,、\s]*[（(]?(?:男|女)[)）]?[，,、\s]*\d{{1,3}}\s?歲",
    ]
    for p in pats:
        hits.extend(m.group(0) for m in re.finditer(p, text))
    jp = "|".join(sorted(JP_SURNAMES, key=len, reverse=True))
    hits.extend(m.group(0) for m in re.finditer(rf"(?:{jp})[一-鿿぀-ヿ]{{0,3}}{HONORIFIC}", text))
    return hits


def variables_text(variables: Any) -> str:
    """The dynamic content of a prompt: every scalar value of its variables (keys sorted, list order kept), one per
    line, unescaped — what :func:`scan` must clear before a call may leave the box. The prompt templates around it
    are fixed, reviewed text; a JSON dump would not do (``\\n`` escapes hide an MRN at the start of a line)."""
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k in sorted(v, key=str):
                walk(v[k])
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x)
        elif v is not None:
            out.append(str(v))

    walk(variables)
    return "\n".join(out)


def scan(text: str, mrn_regex: str | None = None) -> PhiScan:
    findings: list[tuple[str, str]] = []
    for m in TW_ID.finditer(text):
        findings.append(("taiwan_id", _mask(m.group(0))))
    if mrn_regex:
        body = mrn_regex.strip("^$")
        for m in re.finditer(rf"(?<![0-9A-Za-z\-/.]){body}(?![0-9A-Za-z\-/.])", text):
            findings.append(("mrn", _mask(m.group(0))))
    for m in PHONE.finditer(text):
        findings.append(("phone", _mask(m.group(0))))
    for m in EN_PHONE.finditer(text):
        findings.append(("phone", _mask(m.group("v") or m.group(0))))
    for m in KEYWORDS.finditer(text):
        findings.append(("keyword", m.group(0)))
    names = _cjk_names(text)
    findings.extend(("name", _mask(n)) for n in names)
    for m in EN_NAME.finditer(text):
        findings.append(("name", _mask(m.group(0))))
    # date of birth near a name-like token
    for m in DATE.finditer(text):
        window = text[max(0, m.start() - 30) : m.end() + 30]
        if _cjk_names(window) or EN_NAME.search(window) or re.search(r"生日|出生|DOB|born", window, re.I):
            findings.append(("dob_near_name", _mask(m.group(0))))
    if findings:
        return PhiScan(True, findings, None)
    return PhiScan(False, [], PhiClearance(sha256_text(text)))


# ------------------------------------------------------------------------------------------------ note text (T-600)
# FR-DEID-01 (CR-028, DATA-020): names, phone numbers, chart numbers and ID numbers in note text are masked before
# the text is chunked, indexed for full-text search or embedded. The lake's ``document`` table keeps the original
# under the ``phi`` label (D-337). Masking keeps the length: every character of a span other than white space becomes
# ``MASK_CHAR``, so chunk boundaries, offsets and line breaks stay where they were and the clinical words around a span
# are untouched. ``○`` is how Taiwanese and Japanese records mask a name by hand; the tokenizer drops it, so a masked
# span gives no token to the full-text index or the hash embedder.
MASK_CHAR = "○"
# recorded in lake_meta.note_mask; bump when the recognisers below change what they mask (2: English phones, D-744)
NOTE_MASK_VERSION = "2"

_CJK_N = "一-鿿"
_KANA_N = "぀-ヿ"
_ROC = "|".join(sorted(ROC_COMPOUND, key=len, reverse=True)) + "|[" + "".join(sorted(ROC_SURNAMES)) + "]"
_JP = "|".join(sorted(JP_SURNAMES, key=len, reverse=True))
_GIVEN_JP = rf"(?:(?!さん|様|くん|ちゃん|より|から)[{_CJK_N}{_KANA_N}])"  # a given name, not the honorific after it
_ROLE_ZH = r"(?:醫師|醫生|護理師|藥師|個管師)"
_NOTE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # chart numbers after their label (the site pattern, unlabelled, is added per call)
    (
        "mrn",
        re.compile(
            r"(?:病歷號(?:碼)?|病历号|カルテ番号|患者ID|(?i:MRN|chart\s*no\.?|medical record (?:no\.?|number)))"
            r"[\s:：#]*(?P<v>[A-Z0-9][A-Z0-9-]{3,14})(?![A-Za-z0-9])"
        ),
    ),
    # insurance and ID numbers after their label
    (
        "id",
        re.compile(
            r"(?:健保卡號|身分證(?:字號)?|身份證|保険者番号|被保険者番号|(?i:insurance\s*no\.?|ID\s*no\.?))"
            r"[\s:：#]*(?P<v>[A-Z0-9][A-Z0-9-]{3,14})(?![A-Za-z0-9])"
        ),
    ),
    ("id", TW_ID),
    ("phone", PHONE),
    ("phone", EN_PHONE),
    (
        "phone",
        re.compile(
            r"(?<![\d+])(?:\+81[-\s]?\(?\d{1,4}\)?[-\s]?\d{1,4}[-\s]?\d{4}"
            r"|0[5-9]0[-\s]?\d{4}[-\s]?\d{4}|0\d{1,4}-\d{1,4}-\d{4})(?!\d)"
        ),
    ),
    # names after a role or a label (the writer of the note, a relative), with an honorific, or as the v1 rules find
    # them (patient word, sex and age); only the name is masked, never the title, the sex or the age
    (
        "name",
        re.compile(rf"(?:記載医|記載者|担当医|主治医|家族の|氏名)[\s:：]*(?P<v>(?:{_JP})[\s　]?{_GIVEN_JP}{{1,3}})"),
    ),
    ("name", re.compile(rf"(?:記錄者|紀錄者|家屬|家属|姓名)[\s:：]*(?P<v>(?:{_ROC})[{_CJK_N}]{{1,2}})")),
    ("name", re.compile(rf"(?P<v>(?:{_ROC})(?:(?!科)[{_CJK_N}]){{0,2}}){_ROLE_ZH}")),
    ("name", re.compile(rf"(?P<v>(?:{_ROC})[{_CJK_N}]{{0,2}}?)\s?{HONORIFIC}")),
    ("name", re.compile(rf"{PATIENT_WORD}[：:\s]?(?P<v>(?:{_ROC})[{_CJK_N}]{{1,2}})(?=[，,、\s(（]|$)")),
    (
        "name",
        re.compile(rf"(?P<v>(?:{_ROC})[{_CJK_N}]{{1,2}})[，,、\s]*[（(]?(?:男|女)[)）]?[，,、\s]*\d{{1,3}}\s?歲"),
    ),
    ("name", re.compile(rf"(?P<v>(?:{_JP})[\s　]?[{_CJK_N}{_KANA_N}]{{1,3}}?)\s?{HONORIFIC}")),
    (
        "name",
        re.compile(r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+|\bPatient(?: name)?:\s*)(?P<v>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"),
    ),
    (
        "name",
        re.compile(
            r"\b(?:[Dd]aughter|[Ss]on|[Ww]ife|[Hh]usband|[Mm]other|[Ff]ather|[Ss]ister|[Bb]rother|[Ss]pouse"
            r"|[Pp]artner|[Rr]elative|[Ss]een by|[Rr]eviewed by|[Dd]ictated by|[Nn]ame\s*[:：])"
            r"\s+(?:Dr\.?\s+)?(?!(?:Mr|Mrs|Ms|Miss|Dr)\b)(?P<v>[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)?)"
        ),
    ),
)


def note_spans(text: str, mrn_regex: str | None = None) -> list[tuple[str, int, int]]:
    """``(kind, start, end)`` of every name, phone number, chart number and ID number found in note text, overlaps
    merged (kinds: ``name``, ``phone``, ``mrn``, ``id``). ``mrn_regex`` is the site's chart number pattern
    (``settings.mrn_regex``); it also masks a chart number written without its label."""
    found: list[tuple[str, int, int]] = []
    for kind, rx in _NOTE_PATTERNS:
        for m in rx.finditer(text):
            if "v" in rx.groupindex and m.group("v") is not None:
                found.append((kind, m.start("v"), m.end("v")))
            else:
                found.append((kind, m.start(), m.end()))
    if mrn_regex:
        body = mrn_regex.strip("^$")
        for m in re.finditer(rf"(?<![0-9A-Za-z\-/.]){body}(?![0-9A-Za-z\-/.])", text):
            found.append(("mrn", m.start(), m.end()))
    merged: list[tuple[str, int, int]] = []
    for kind, s, e in sorted(found, key=lambda f: (f[1], -f[2])):
        if e <= s:
            continue
        if merged and s < merged[-1][2]:
            k0, s0, e0 = merged[-1]
            merged[-1] = (k0, s0, max(e0, e))
        else:
            merged.append((kind, s, e))
    return merged


def mask_note(text: str, mrn_regex: str | None = None) -> str:
    """Note text with every span of :func:`note_spans` masked, the length and the white space kept."""
    spans = note_spans(text, mrn_regex)
    if not spans:
        return text
    out = list(text)
    for _kind, s, e in spans:
        for i in range(s, e):
            if not out[i].isspace():
                out[i] = MASK_CHAR
    return "".join(out)


def site_mrn_regex() -> str | None:
    """The site's chart number pattern (``settings.mrn_regex``), or ``None`` when no site configuration is readable
    (a test lake, a tool run without a site): then only labelled chart numbers are masked."""
    try:
        from tb_common.config import get_config

        return get_config().settings.mrn_regex
    except Exception:
        return None
