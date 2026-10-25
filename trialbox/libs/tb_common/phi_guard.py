"""PHI guard (SPEC §7.4): regex + dictionary scan run on the full text before any cloud LLM call.

Any hit disables cloud for the job (the local model is used) and the audit records ``phi_guard_hit=true``. A clean
scan returns a :class:`PhiClearance` bound to the text's sha256; ``tb_common.llm`` accepts cloud calls only with a
clearance for exactly the text being sent. The guard errs on the side of hits (false positives only cost latency).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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
DATE = re.compile(r"(?:19|20)\d{2}[/\-.年]\s?\d{1,2}[/\-.月]\s?\d{1,2}日?|民國\s?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日")
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
