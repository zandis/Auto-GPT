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
# NEW-B-43 (D-744): an English phone number (North American, British or any with a country code). The long forms
# anywhere; a seven-digit local number, and a number written without separators, only after a word that says it is a
# phone (``Tel``, ``phone (no.)``, ``mobile``, ``contact``, ``call``, ``pager``, ``T:`` ...). Separators never cross a
# line: a prompt's variables are scanned one per line. Clinical ranges (100-300 mg, 4.5-11.0), runs of doses or counts
# (250 500 1000), times (0800 1200), study, lot and kit numbers and a spaced lab code (JLAC10) have none of the shapes.
# One pattern for the note masker, the gate before a call (:func:`scan`) and the guard service's recognisers. Group
# ``v``: the number (the word stays).
_SP = r"[^\S\n]"  # a space or tab, never a line break
_DASH = r"[-.\u2010-\u2015\u2212]"  # hyphen, dot and the Unicode dashes
_SEP = rf"(?:{_DASH}|{_SP})"
_EN_PHONE_FULL = (
    # with its country code (+ or 00), at least nine digits
    rf"(?=(?:[^\d\n]{{0,3}}\d){{9}})(?:\+|(?<![\d.,])(?<!\d{_SP})00(?=[1-9]))\d{{1,3}}{_SEP}?\(?\d{{1,4}}\)?(?:{_SEP}?\d{{2,4}}){{2,3}}"
    # North American: (area) or area and a dash, exchange, line; a leading 1 too
    rf"|(?:1{_DASH})?(?:\([2-9]\d{{2}}\){_SP}?|[2-9]\d{{2}}{_DASH})\d{{3}}{_DASH}\d{{4}}"
    # British national: the area code with a separator or in brackets, then the subscriber number
    rf"|(?<!\d{_SP})(?:\(0\d{{4}}\){_SP}?|0\d{{4}}{_SEP})\d{{3}}{_SEP}?\d{{3}}"
    rf"|(?<!\d{_SP})(?:\(0\d{{3}}\){_SP}?|0\d{{3}}{_SEP})\d{{3}}{_SEP}?\d{{4}}"
    rf"|(?<!\d{_SP})(?:\(0\d{{2}}\){_SP}?|0\d{{2}}{_SEP})\d{{4}}{_SEP}?\d{{4}}"
)
_EN_PHONE_LABEL = (
    r"(?i:\b(?:tel(?:ephone)?|phone|ph|mobile|mob|cell(?:phone)?|fax|pager|landline|helpline|contact|call|dial"
    r"|home|number\s+is|[TM](?=\s*:))\b\.?"
    rf"(?:{_SP}*(?:no\b\.?|number\b|#|details\b))?)(?:{_SP}|[:#.])*"
)
EN_PHONE = re.compile(
    rf"{_EN_PHONE_LABEL}(?P<v>{_EN_PHONE_FULL}|0\d{{9,10}}|\d{{10}}|\d{{3}}{_SEP}?\d{{4}})(?![\dA-Za-z])(?!{_DASH}\d)"
    rf"|(?<![A-Za-z0-9+.,])(?:{_EN_PHONE_FULL})(?![\dA-Za-z])(?!{_DASH}\d)"  # not inside a code (3D046 0000 019)
)
# NEW-B-44 (D-745): a date of birth, a postal address and a chart number after any of its labels. The owner's run of
# ``mask_note`` on a month of real notes (counts only) found these three surviving. One definition each for the note
# masker and the guard service's recognisers (which name them, not a copy). Group ``v``: the value; the label stays.
_CJK_A = "一-鿿"
_KANA_A = "぀-ヿ"
_NUM_A = r"[0-9０-９一二三四五六七八九十]+"
# a date of birth's value: the guard's forms (D-215) and, after a label or before 生, the ROC year without 民國, an
# era abbreviation (S31.3.14), day first (14/03/1956) and a day before the month's name (14 Mar 1956)
_DOB_VALUE = (
    rf"{dates.DOB_SPAN}"
    r"|(?:民國\s?)?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日"
    r"|(?:明治|大正|昭和|平成|令和|[MTSHR])\s?(?:\d{1,2}|元)[年./]\s?\d{1,2}[月./]\s?\d{1,2}日?"
    r"|\d{2,3}[/.\-]\d{1,2}[/.\-]\d{1,2}"
    r"|\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)\d{2}"
    r"|\d{1,2}[ -](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?[ -](?:19|20)\d{2}"
)
DOB_LABELLED = re.compile(
    r"(?:出生日期|出生年月日|出生日|出生|生日|生年月日|誕生日"
    r"|(?i:\bd\.?o\.?b\b\.?|\bdate\s+of\s+birth\b|\bbirth\s*date\b|\bborn(?:\s+on)?\b))"
    rf"[\s:：]*(?P<v>{_DOB_VALUE})(?![0-9])"
)
# a date followed by the word for born (1956年3月14日生, 昭和31年3月14日生まれ, 民國45年3月14日出生); never 生化
DOB_BORN = re.compile(rf"(?<![0-9])(?P<v>{_DOB_VALUE})\s?(?=生まれ|出生|に生まれ|生(?![化理物活命殖產産]))")
ADDRESS_ZH = re.compile(
    rf"(?:[{_CJK_A}]{{1,3}}(?:縣|市))?(?:[{_CJK_A}]{{1,3}}(?:區|鄉|鎮|市))?(?:[{_CJK_A}]{{1,4}}(?:村|里){_NUM_A}鄰)?"
    rf"[{_CJK_A}]{{1,5}}(?:路|街|大道)"
    rf"(?:{_NUM_A}段)?(?:{_NUM_A}巷)?(?:{_NUM_A}弄)?{_NUM_A}(?:之{_NUM_A})?號(?:{_NUM_A}樓(?:之{_NUM_A})?)?"
)
ADDRESS_JA = re.compile(
    rf"(?:東京都|北海道|大阪府|京都府|[{_CJK_A}]{{2,3}}県)[{_CJK_A}{_KANA_A}]{{1,10}}?(?:市|区|町|村|郡)"
    rf"[{_CJK_A}{_KANA_A}]{{0,8}}?[0-9０-９]+(?:(?:丁目|番地?|号|[-－ー])[0-9０-９]*){{1,4}}"
)
ADDRESS_EN = re.compile(
    r"\b(?!(?:19|20)\d{2}\b)\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Boulevard|Blvd|Drive|Dr|Way|Close|Court|Ct"
    r"|Place|Pl|Crescent|Terrace|Square|Sq|Parade|Highway|Hwy|Circle|Gardens|Row|Mews|Grove)\b\.?"
    r"(?:,\s*(?:Apt\.?|Unit|Suite)\s*\d+)?(?:,\s*[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)?"
)
# whatever follows an address label, to the end of the field: a separator after a Chinese or Japanese label, a colon
# after an English one ("address the dose" is no label)
ADDRESS_LABELLED = re.compile(
    r"(?:(?:通訊地址|戶籍地址|居住地址|聯絡地址|住址|地址|現住所|住所|居所)[\s:：]+|(?<!IP\s)(?<!peer\s)(?<!email\s)(?<!public\s)(?<!web\s)(?i:\baddress|\baddr\.?)\s*[:：]\s*)"
    r"(?P<v>[^\s，,。；;、\n（(：:][^，,。；;\n　]{1,60}?)(?=[，,。；;\n　]|\s{2}|\s*$)"
)
# a chart number after its label, the labels of Taiwanese, Japanese and English records; full-width digits too
MRN_LABELLED = re.compile(
    r"(?:病歷號(?:碼)?|病歷編號|病歷碼|病历号|病歴番号|カルテ(?:番号|No\.?)|患者(?:ID|番号|No\.?)|診察券番号|病[人患]ID"
    r"|(?i:\bMRN\b|\bchart\s*(?:no\b\.?|number\b)|\bmedical record (?:no\b\.?|number\b)"
    r"|\bhospital\s*(?:no\b\.?|number\b)"
    r"|\bpatient\s*ID\b))"
    r"[\s:：#]*(?P<v>[A-Z0-9０-９][A-Z0-9０-９-]{3,14})(?![A-Za-z0-9０-９])"
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
# recorded in lake_meta.note_mask; bump when the recognisers below change what they mask (2: English phones, D-744;
# 3: dates of birth, addresses and chart labels, D-745)
NOTE_MASK_VERSION = "3"

_CJK_N = "一-鿿"
_KANA_N = "぀-ヿ"
_ROC = "|".join(sorted(ROC_COMPOUND, key=len, reverse=True)) + "|[" + "".join(sorted(ROC_SURNAMES)) + "]"
_JP = "|".join(sorted(JP_SURNAMES, key=len, reverse=True))
_GIVEN_JP = rf"(?:(?!さん|様|くん|ちゃん|より|から)[{_CJK_N}{_KANA_N}])"  # a given name, not the honorific after it
_ROLE_ZH = r"(?:醫師|醫生|護理師|藥師|個管師)"
_NOTE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # chart numbers after their label (the site pattern, unlabelled, is added per call)
    ("mrn", MRN_LABELLED),
    # dates of birth after their label or before the word for born, and postal addresses (D-745)
    ("dob", DOB_LABELLED),
    ("dob", DOB_BORN),
    ("address", ADDRESS_LABELLED),
    ("address", ADDRESS_ZH),
    ("address", ADDRESS_JA),
    ("address", ADDRESS_EN),
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
    """``(kind, start, end)`` of every name, phone number, chart number, ID number, date of birth and postal address
    found in note text, overlaps merged (kinds: ``name``, ``phone``, ``mrn``, ``id``, ``dob``, ``address``).
    ``mrn_regex`` is the site's chart number pattern
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
