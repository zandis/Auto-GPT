"""Charts one by one (D-131, D-132): text from what a coordinator has, and the model's *proposed* facts.

Inputs: text pasted from the EMR screen, ``.txt`` / ``.md``, Word (``.docx``), a PDF with a text layer, and a scan (a
PDF without text, or an image) read by OCR on the box (:mod:`sitesetup.ocr`). Without OCR a scan is refused with a
plain reason and everything else still works.

:func:`extract` puts the chart to the local model (prompt ``chart_facts``, the stub in tests and the e2e) and keeps
a fact only when its quote is found in the chart, character for character (after width and space normalisation,
``tb_common.quotes``). Each kept fact is normalised (dates through :mod:`sitesetup.messy`, units to the stored unit,
code systems to their URIs) and is **proposed**: it waits beside its quote for a coordinator's one-tap Confirm,
Correct or Reject, and until then it can only send the patient to "needs information" (``matching.proposed``).
The chart itself stays in the box's protected data folder; the lake gets the text with identifiers redacted.

A chart longer than the model can read at once is read in parts (T-603, review LLM-015): each part is sized from the
model's context (:meth:`tb_common.llm.LlmClient.text_budget`), so 60,000 characters of Japanese or Chinese, which
fit no profile in one prompt, are read on the 8k, 16k and 32k profiles alike. Facts found in several parts are kept
once.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Protocol

from doc_parser.hidden_text import hidden_text
from tb_common import encoding, instruments
from tb_common.output_gate import prepare_output
from tb_common.phi_guard import DOB_LABELLED, MRN_LABELLED
from tb_common.quotes import quote_in
from tb_llm.budget import estimate_tokens

from sitesetup import messy
from sitesetup.ocr import Ocr

TEXT_EXT = (".txt", ".md")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
CHART_EXT = (*TEXT_EXT, ".docx", ".pdf", *IMAGE_EXT)
MAX_CHART_BYTES = 20 * 1024 * 1024
MAX_CHART_CHARS = 60_000  # what a coordinator may upload; read in parts sized from the model's context (T-603)
MIN_PART_TOKENS = 200  # a context that leaves less than this for chart text cannot read a chart
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
SYSTEMS = {"icd10cm": ICD10CM, "loinc": LOINC, "atc": ATC, "": ""}
LOINC_ANALYTE = {a.loinc: name for name, a in messy.ANALYTES.items()}
# a term that names the analyte but not its serum result: another specimen (尿クレアチニン, 尿中尿酸, a urinalysis
# line "UA-PRO", pleural fluid, CSF) or another quantity (体重変化, 出生体重, a ratio). 尿酸 itself is urate
_NOT_SERUM = re.compile(
    r"尿(?!酸)|urin|\bU-|\bUA-|\bUA\s+(?=[^\s(（])|胸水|腹水|髄液|髓液|腦脊|脳脊|胸腔|肋膜|積液|穿刺|関節液|關節液"
    r"|pleural|peritoneal|ascit|synovial|\bCSF\b|透析|dialysate|OGTT|負荷"
    r"|変化|減少|増加|出生|change|loss|gain|\bbirth|比|ratio",
    re.I,
)
# LOINCs of a stored test in another unit or method: the same test, stored under the analyte's own code once converted
SAME_TEST = {
    "14933-6": "urate",
    "14682-9": "creatinine",
    "59261-8": "hba1c",
    "14749-6": "glucose",
    "15074-8": "glucose",
}
# LOINCs of a variant of a stored test that a criterion may name on its own (fasting glucose, glucose in blood, HbA1c
# by HPLC, creatinine in blood, body weight measured): kept as the model gave them on a line that names the test
VARIANTS = {
    "glucose": {"1558-6", "2339-0", "41653-7"},
    "hba1c": {"17856-6"},
    "creatinine": {"38483-4"},
    "weight": {"3141-9"},
}
LANGUAGE_NAMES = {"ja": "Japanese", "zh-TW": "Traditional Chinese", "en": "English"}


class ChartError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ChartText:
    text: str
    method: str  # paste | text | docx | pdf | ocr
    pages: int = 1
    notes: list[str] = field(default_factory=list)
    hidden_chars: int = 0  # characters nobody sees on the page (T-208): named in ``notes`` and the chart summary


# D-146 (review J-07): a PDF's text layer may carry NUL and other control characters (a CJK font without a usable
# ToUnicode map gives U+0000 for every glyph it cannot map); PostgreSQL text refuses NUL. Tab and line breaks stay.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")


def clean(text: str) -> str:
    """``text`` without NUL, the other C0 control characters but tab and line breaks, DEL and lone surrogates."""
    return _CONTROL.sub("", text)


def _decode(data: bytes) -> str:
    try:  # D-215: one detector for UTF-8, Shift_JIS and Big5; a file it cannot tell is refused, never guessed
        return encoding.decode(data)[0]
    except encoding.EncodingRefused as exc:
        raise ChartError("CHART-TEXT", str(exc)) from exc


def _docx(data: bytes) -> str:
    import docx

    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        lines += [" | ".join(c.text.strip() for c in r.cells) for r in t.rows]
    return "\n".join(lines)


def _pdf(data: bytes, ocr: Ocr) -> ChartText:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [p.extract_text() or "" for p in reader.pages]
    text = "\n\n".join(pages)
    if pages and len(text.strip()) / len(pages) >= 20:
        return ChartText(text, "pdf", len(pages))
    # no text layer: a scan. Each page's images go to OCR on the box
    if not ocr.available():
        raise ChartError("CHART-OCR", "this PDF is a scan and OCR is not installed on this box")
    out = []
    for p in reader.pages:
        for img in p.images:
            out.append(ocr.image_text(img.data))
    if not "".join(out).strip():
        raise ChartError("CHART-EMPTY", "OCR found no text in this scan")
    return ChartText("\n\n".join(out), "ocr", len(pages), ["read by OCR: check the facts against the paper"])


def chart_text(name: str, data: bytes, ocr: Ocr) -> ChartText:
    """The text of one chart file. Raises :class:`ChartError` (``CHART-TYPE``, ``CHART-OCR``, ``CHART-EMPTY``,
    ``CHART-SIZE``) with a plain reason."""
    if len(data) > MAX_CHART_BYTES:
        raise ChartError("CHART-SIZE", "the file is larger than 20 MB")
    ext = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in TEXT_EXT:
        out = ChartText(_decode(data), "text")
    elif ext == ".docx":
        try:
            out = ChartText(_docx(data), "docx")
        except Exception as exc:
            raise ChartError("CHART-TYPE", "this Word file cannot be read") from exc
    elif ext == ".pdf" or data[:4] == b"%PDF":
        try:
            out = _pdf(data, ocr)
        except ChartError:
            raise
        except Exception as exc:
            raise ChartError("CHART-TYPE", "this PDF cannot be read") from exc
    elif ext in IMAGE_EXT:
        if not ocr.available():
            raise ChartError("CHART-OCR", "a scanned image needs OCR, which is not installed on this box")
        out = ChartText(ocr.image_text(data), "ocr", 1, ["read by OCR: check the facts against the paper"])
    else:
        raise ChartError("CHART-TYPE", "charts are pasted text, .txt, Word (.docx), PDF or a scanned image")
    if out.method in ("pdf", "docx"):  # T-208 (D-346): a planted instruction hides best where nobody reads
        hidden = hidden_text(out.method, data)
        if hidden.found:
            out.hidden_chars = hidden.chars
            out.notes.append(hidden.warning())
    out.text = clean(out.text)
    if not out.text.strip():
        raise ChartError("CHART-EMPTY", "no text found in this file")
    if len(out.text) > MAX_CHART_CHARS:
        raise ChartError("CHART-SIZE", f"the chart is longer than {MAX_CHART_CHARS} characters")
    return out


class _Llm(Protocol):
    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any: ...


# Deep review 2026-11-13 (screening, SCR-04), D-657: a negated mention ("悪性腫瘍なし", "No history of
# hypertension", "否認高血壓") is never the patient's proposed diagnosis, whatever the model proposed. The negation is
# bound to the fact's own term inside its own clause: a clause boundary stops it, so "糖尿病なし、高血圧あり" keeps
# 高血圧. A cue after the term must end its clause ("高血圧なし→あり", "痛風否定できず", "陰性化", "ないし" are no
# negation); a cue before it must stand right before the term or before a list joined by "or" / 及 / 或 ("no
# hypertension or diabetes"), so "非小細胞肺癌", "無症候性" and "no chest pain and gout" keep the fact. When the
# quote does not hold the term nothing binds a negation to it: the fact stays proposed and a person reads the quote.
# Schema fields for negation, subject and certainty need a prompt qualified on the model pair (D-359).
_CLAUSE = re.compile(r"[。．、，,;；\n]|(?<=\S)\.(?=\s|$)|\bbut\b|しかし|ただし|但し", re.I)
_AFTER_JA = (
    r"[\s:：はがもを]*(?:特に)?(?:の?(?:既往歴|既往|病歴)[はがも]?)?[\s:：]*"
    r"(?:[(（]\s*(?:なし|無し|[-−－ｰー—–])\s*[)）]|なし|無し|無い|無|ない|なかった|ありません|ではない|でない|"
    r"認めず|認めない|認められない|認められず|否定的?|陰性)"
)
_AFTER_EN = r"\s*[-:]?\s*(?:(?:was|is|has\s+been)\s+)?(?:ruled\s+out|excluded|negative|absent|none|no)"
_NEG_AFTER = re.compile(rf"^(?:{_AFTER_JA}|{_AFTER_EN})\s*(?:です|でした)?\s*[)）]?\s*$", re.I)
_CUE_EN = (
    r"\b(?:no(?:\s+known)?(?:\s+(?:history|evidence|signs?)\s+of)?|not|never(?:\s+had)?|denie[sd]|"
    r"negative\s+for|without|free\s+of|ruled\s+out)"
)
_CUE_ZH = r"(?:否認|否认|未見|未见|沒有|没有|無|无)"
_NEG_BEFORE = re.compile(rf"(?:{_CUE_EN}[\s-]*(?:[^;]*?\s(?:or|nor)\s+)?|{_CUE_ZH}\s*(?:[^;]*?(?:及|或))?)$", re.I)


def _mentions(term: str, text: str) -> list[int]:
    """Where ``term`` (lower case) stands in ``text``; a term in Latin letters only as a whole word ("MI" is not in
    "Family")."""
    if not term:
        return []
    edge = r"(?<![a-z0-9])" if term[:1].isascii() and term[:1].isalnum() else ""
    tail = r"(?![a-z0-9])" if term[-1:].isascii() and term[-1:].isalnum() else ""
    return [m.start() for m in re.finditer(edge + re.escape(term) + tail, text.lower())]


def _negated(term: str, quote: str) -> bool:
    """Is every mention of ``term`` in ``quote`` negated in its own clause? A term the quote does not hold (the
    model's own wording or language) binds nothing: not negated, the fact stays for a person."""
    text = messy.half_width(quote)
    clauses = [c for c in _CLAUSE.split(text) if c.strip()]
    t = messy.half_width(term).strip().lower()
    hits = [(c, at) for c in clauses for at in _mentions(t, c)]
    return bool(hits) and all(
        bool(_NEG_BEFORE.search(c[:at])) or bool(_NEG_AFTER.search(c[at + len(t) :])) for c, at in hits
    )


# SCR-04, family history (D-658): a relative's diagnosis ("家族歴：母 乳癌", "Mother had breast cancer") is never the
# patient's proposed diagnosis. A fact is dropped only where the binding is plain; anything less stays proposed and a
# person reads the quote (a dropped fact is invisible, a kept one is reviewed):
# - a relative right before the term (separators, 罹患 / 患 / had / has / with / w/ between), or "<term> in father";
# - a family history heading in the term's own clause, or in the clause before when that clause ends with a
#   relative ("Family history: mother, breast cancer"); an empty heading ("なし", "none", "noncontributory"), another
#   heading ("既往歴：", "Dx:") or the patient as subject (本人, patient) ends its reach;
# - "FH:" is no heading (familial hypercholesterolemia), 子 is no relative (子宮癌), and a one-character relative needs
#   a separator after it (母乳).
_REL_LONG = (
    r"祖父|祖母|叔父|叔母|伯父|伯母|母親|父親|母亲|父亲|実母|実父|義母|義父|兄弟|姉妹|息子|長男|長女|次男|次女|"
    r"媽媽|爸爸|妈妈|哥哥|姐姐|弟弟|妹妹|外婆|外公|奶奶|爺爺|爷爷|儿子|兒子|女儿|女兒|丈夫|妻子"
)
_REL_ONE = r"母|父|兄|姉|弟|妹|娘|夫|妻"
_REL_EN = (
    r"mother|father|brother|sister|son|daughter|grandmother|grandfather|aunt|uncle|sibling|sibs?|parent|mom|dad|"
    r"wife|husband|spouse|child|children"
)
_REL_WORD = re.compile(rf"^(?:{_REL_LONG}|{_REL_ONE}|(?:{_REL_EN})s?)$", re.I)
_REL_BEFORE = re.compile(
    rf"(?:^|[\s:：(（/・]|患者の|[父母]方の?)(?:(?:{_REL_LONG})|(?:{_REL_ONE})(?=\s|[:：のが・\-–—]|罹患|患))"
    r"\s*(?:\([^)]{0,20}\)|（[^）]{0,20}）)?\s*(?:[:：のが・\-–—]\s*)?(?:罹患|患有|患)?\s*$"
    rf"|\b(?:{_REL_EN})s?\b\s*(?:\([^)]{{0,20}}\))?\s*(?:[:\-–—]\s*|\s(?:had|has|have|with|w/)\s+)?$",
    re.I,
)
_REL_AFTER = re.compile(rf"^\s*(?:in|\()\s*(?:(?:her|his|the|their)\s+)?(?:{_REL_EN})s?\b", re.I)
_FAMILY_HEAD = re.compile(r"家族歴|家族史|family\s+(?:history|hx)|fam\.?\s*hx|famhx|\bFHx\b|\bfamily\s*:", re.I)
_EMPTY_HEAD = re.compile(
    r"^[\s:：]*(?:特記事項なし|特記すべきことなし|特記なし|なし|無し|無|无|none|nil|negative|noncontributory|"
    r"unremarkable|n/?c)(?![a-z])",
    re.I,
)
_SUBJECT = re.compile(r"本人|患者本人|\bpatient\b|\bpersonal\b|\bshe\b|\bhe\b", re.I)
_OWN_HEAD = re.compile(
    r"既往歴|既往史|現病歴|现病史|現病史|個人史|个人史|past\s+(?:medical\s+)?history|\bPMHx?\b|\bHPI\b", re.I
)
_ANY_HEAD = re.compile(r"([^\s:：、，,;；。]{1,12})\s*[:：]")


def _head_reaches(before: str) -> bool:
    """Does a family history heading in ``before`` (the clause up to the term) still govern its end?"""
    heads = list(_FAMILY_HEAD.finditer(before))
    if not heads:
        return False
    rest = before[heads[-1].end() :]
    if _EMPTY_HEAD.search(rest) or _OWN_HEAD.search(rest) or _SUBJECT.search(rest):
        return False
    return all(_REL_WORD.match(h.group(1).strip()) for h in _ANY_HEAD.finditer(rest))  # another heading ends it


def _family(term: str, quote: str) -> bool:
    """Is every mention of ``term`` in ``quote`` plainly a relative's? A term the quote does not hold binds nothing."""
    text = messy.half_width(quote)
    t = messy.half_width(term).strip().lower()
    hits: list[bool] = []
    for sentence in re.split(r"[。．\n]|(?<=\S)\.(?=\s|$)", text):
        clauses = _CLAUSE.split(sentence)
        for i, clause in enumerate(clauses):
            for at in _mentions(t, clause):
                before, after = clause[:at], clause[at + len(t) :]
                prev = clauses[i - 1] if i else ""
                led = (
                    not before.strip()
                    and bool(re.search(rf"(?:{_REL_LONG}|{_REL_ONE}|\b(?:{_REL_EN})s?\b)\s*$", prev, re.I))
                    and _head_reaches(prev)
                )
                hits.append(
                    (bool(_REL_BEFORE.search(before)) and not _SUBJECT.search(before))  # "patient and his father"
                    or bool(_REL_AFTER.search(after))
                    or _head_reaches(before)
                    or led
                )
    return bool(hits) and all(hits)


def normalise(raw: dict[str, Any]) -> dict[str, str] | None:
    """One model fact as a store fact (``sitesetup.store``), or None when it cannot be one (an unreadable date of
    birth, a lab value that is not a number, a unit TrialBox does not know for the test, a negated diagnosis, a
    relative's diagnosis)."""
    dom = str(raw.get("domain") or "")
    quote = str(raw.get("quote") or "").strip()
    term = re.sub(r"\s+", " ", messy.half_width(str(raw.get("term") or ""))).strip()[:120]
    code = messy.half_width(str(raw.get("code") or "")).strip().upper()[:20]
    system = SYSTEMS.get(str(raw.get("system") or ""), "")
    day = messy.parse_date(str(raw.get("date") or "")).iso or ""
    base = {"quote": quote, "day": day, "status": "proposed", "term": term}
    if dom == "birth_date":
        iso = messy.parse_date(str(raw.get("value") or "")).iso
        return {**base, "domain": "demographic", "code": "birth_date", "value": iso, "day": ""} if iso else None
    if dom == "sex":
        sx = {
            "男": "male",
            "男性": "male",
            "male": "male",
            "m": "male",
            "女": "female",
            "女性": "female",
            "female": "female",
            "f": "female",
        }.get(str(raw.get("value") or "").strip().lower())
        return {**base, "domain": "demographic", "code": "sex", "value": sx, "day": ""} if sx else None
    if dom == "condition":
        if _negated(term, quote):  # SCR-04 (D-657): a negated mention proposes nothing
            return None
        if _family(term, quote):  # SCR-04 (D-658): nor does a relative's diagnosis
            return None
        return {**base, "domain": "condition", "code": code if system else "", "system": system if code else ""}
    if dom == "medication":
        return {**base, "domain": "medication", "code": code if system == ATC else "", "system": ATC if code else ""}
    if dom == "observation":
        num, cell_unit = messy.parse_number(str(raw.get("value") or ""))
        if num is None:
            return None
        # deep review 2026-11-13 (screening, SCR-02): a LOINC of a test TrialBox stores (or of the same test in
        # another unit, such as urate's moles code 14933-6) is kept only on a line that names that test, and is then
        # stored as the code of the unit it is converted to; on any other line it is dropped (the fact stays
        # uncoded: a person maps it). Before, a creatinine code on a urate line stored the urate value as creatinine,
        # and urate's moles code on a value stored in mg/dL hid it from a mass-code criterion (lane G, P5). On a line
        # that names a stored test only its variants (VARIANTS) keep their own code; on any other line the model's
        # LOINC is kept as given (urine creatinine, a pleural fluid, an OGTT value)
        named = None if _NOT_SERUM.search(term) else messy.analyte_of(term)
        of_code = (LOINC_ANALYTE.get(code) or SAME_TEST.get(code)) if system == LOINC else None
        if system != LOINC or (of_code is not None and of_code != named):
            code = ""
        if named and code not in VARIANTS.get(named, ()):
            code, of_code = "", named  # on a line that names a stored test, only that test's own codes are kept
        analyte = named or ""
        unit = messy.norm_unit(str(raw.get("unit") or "")) or cell_unit
        conv = messy.convert(analyte, num, unit) if unit else None
        if conv is None:
            return None
        value, stored, _ = conv
        if named and (not code or of_code == named):
            code, system = messy.ANALYTES[named].loinc, LOINC
        return {
            **base,
            "domain": "observation",
            "code": code,
            "system": system if code else "",
            "value": f"{value:g}",
            "unit": stored,
        }
    return None


def _part_tokens(text: str) -> int:
    """What ``text`` adds to the chart prompt, which renders it as a JSON string (``tojson_pretty``)."""
    return estimate_tokens(json.dumps(text, ensure_ascii=False))


def chart_parts(text: str, budget: int | None) -> list[str]:
    """``text`` cut at line ends into parts of at most ``budget`` tokens each (T-603); a line longer than the budget
    is cut inside. ``None``: the context is not known, one part. Every character is in exactly one part."""
    if budget is None or _part_tokens(text) <= budget:
        return [text]
    if budget < MIN_PART_TOKENS:
        raise ChartError("CHART-SIZE", "the model on this box cannot read a chart: its context is too small")
    parts: list[str] = []
    cur = ""
    for line in text.splitlines(keepends=True):
        while _part_tokens(line) > budget:  # one very long line: cut it where it still fits
            lo, hi = 1, len(line)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if _part_tokens(line[:mid]) <= budget else (lo, mid - 1)
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:lo])
            line = line[lo:]
        if cur and _part_tokens(cur + line) > budget:
            parts.append(cur)
            cur = ""
        cur += line
    if cur:
        parts.append(cur)
    return parts


def part_budget(llm: _Llm, lang: str) -> int | None:
    """Tokens of chart text one ``chart_facts`` prompt may hold on this model (None: the context is not known)."""
    fn = getattr(llm, "text_budget", None)
    if not callable(fn):
        return None
    room = fn("chart_facts", {"text": "", "language": lang, "language_name": LANGUAGE_NAMES.get(lang, "English")})
    return int(room) if isinstance(room, int) else None


def extract(
    llm: _Llm,
    text: str,
    lang: str,
    job_id: str | None = None,
    switches: Mapping[str, instruments.Switch] | None = None,
    mrn_regex: str | None = None,
    patient_numbers: tuple[str, ...] = (),
) -> tuple[list[dict[str, str]], int]:
    """``(proposed facts, facts dropped)``: a fact whose quote is not in the chart is dropped, never kept. A chart
    longer than the model's context allows is read in parts (:func:`chart_parts`), each fact kept once. An item
    answer of a score-only instrument is dropped unless the site switched that instrument with a licence reference
    (``switches``, T-307)."""
    # A labelled demographic header can be read locally. Keep the site's proposed DOB fact
    # and its source quote even though the model can no longer read that value.
    safe = prepare_output("chart_facts", "model", {"text": text, "language": lang}, mrn_regex=mrn_regex)
    facts: list[dict[str, Any]] = []
    projected_lines = safe["text"].splitlines()
    header_lines = text.splitlines()[:3]
    for index, (header, line) in enumerate(pairwise(header_lines)):
        number = MRN_LABELLED.search(header)
        if number is None or number["v"] not in patient_numbers:
            continue
        if index and not re.fullmatch(
            r"(?:外来記録|門診紀錄|Outpatient (?:record|note))\s*(?:[\d年月日./ -]+)?", header_lines[0].strip(), re.I
        ):
            continue
        prefix = projected_lines[index][: number.start()].strip()
        if number.end() != len(header.rstrip()) or not re.fullmatch(
            r"(?:患者|病人|Patient)(?:\s*[:：]?\s*[○\s.]+(?:様|女士|先生)?)?", prefix, re.I
        ):
            continue
        dob = DOB_LABELLED.match(line.strip())
        if dob and re.fullmatch(
            r"(?:\s*(?:性別|性别|Sex)\s*[:：]?\s*(?:男性|女性|男|女|male|female))?\s*", line.strip()[dob.end() :], re.I
        ):
            facts.append({"domain": "birth_date", "value": dob["v"], "quote": dob[0]})
    # Analyse the complete chart before a context boundary can divide a name.
    for part in chart_parts(safe["text"], part_budget(llm, lang)):
        res = llm.chat_json(
            "chart_facts",
            {**safe, "text": part},
            job_id=job_id,
        )
        data = res.data if hasattr(res, "data") else res
        facts.extend(data.get("facts") or [])
    kept: list[dict[str, str]] = []
    dropped = 0
    seen: set[tuple[str, ...]] = set()
    for raw in facts:
        if not quote_in(str(raw.get("quote") or ""), text):
            dropped += 1
            continue
        if instruments.refused_fact(str(raw.get("term") or ""), str(raw.get("code") or "").strip(), switches):
            dropped += 1  # T-107 (D-353), T-307 (D-375): an item answer the site may not keep is never kept
            continue
        f = normalise(raw)
        if f is None:
            dropped += 1
            continue
        key = (f["domain"], f.get("code", ""), f.get("term", ""), f.get("value", ""), f["day"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(f)
    return kept, dropped
