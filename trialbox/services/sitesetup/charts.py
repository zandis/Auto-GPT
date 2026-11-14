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
from typing import Any, Protocol

from doc_parser.hidden_text import hidden_text
from tb_common import encoding, instruments
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
# 高血圧, and a word that only looks negative ("非小細胞肺癌", "無症候性") is not a cue unless it stands right before
# the term. Schema fields for negation, subject and certainty need a prompt qualified on the model pair (D-359).
_CLAUSE = re.compile(r"[。．、，,;；\n]|\bbut\b|しかし|ただし|但し", re.I)
_NO = r"(?:なし|無し|ない|認めず|認めない|否定|陰性|\(\s*[-−－]\s*\)|（\s*[-−－]\s*）)"
_NEG_AFTER = re.compile(
    rf"^[\s:：はがも]*(?:の?(?:既往歴|既往|病歴)[はも]?)?[\s:：]*{_NO}"
    r"|^\s*(?:(?:was|is|has\s+been)\s+)?(?:ruled\s+out|excluded|negative)\b",
    re.I,
)
_NEG_BEFORE = re.compile(
    r"(?:\bno\b(?:\s+(?:history|evidence|signs?)\s+of)?|\bdenie[sd]\b|\bnegative\s+for\b|\bwithout\b|"
    r"\bruled\s+out\b|否認|未見|沒有|没有|無)\s*$",
    re.I,
)
_WHOLE_NEG = re.compile(rf"{_NO}\s*$|^\s*(?:no|denies|denied|negative\s+for|否認|未見|沒有|没有|無)\b", re.I)


def _negated(term: str, quote: str) -> bool:
    """Is every mention of ``term`` in ``quote`` negated in its own clause? A term the quote does not hold (the
    model's own wording) is judged on the whole quote: one clause that is negated as a whole."""
    text = messy.half_width(quote)
    clauses = [c for c in _CLAUSE.split(text) if c.strip()]
    t = messy.half_width(term).strip().lower()
    hits = [(c, m.start()) for c in clauses for m in re.finditer(re.escape(t), c.lower())] if t else []
    if not hits:
        return len(clauses) == 1 and bool(_WHOLE_NEG.search(clauses[0].strip()))
    return all(bool(_NEG_BEFORE.search(c[:at])) or bool(_NEG_AFTER.search(c[at + len(t) :])) for c, at in hits)


def normalise(raw: dict[str, Any]) -> dict[str, str] | None:
    """One model fact as a store fact (``sitesetup.store``), or None when it cannot be one (an unreadable date of
    birth, a lab value that is not a number, a unit TrialBox does not know for the test, a negated diagnosis)."""
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
) -> tuple[list[dict[str, str]], int]:
    """``(proposed facts, facts dropped)``: a fact whose quote is not in the chart is dropped, never kept. A chart
    longer than the model's context allows is read in parts (:func:`chart_parts`), each fact kept once. An item
    answer of a score-only instrument is dropped unless the site switched that instrument with a licence reference
    (``switches``, T-307)."""
    facts: list[dict[str, Any]] = []
    for part in chart_parts(text, part_budget(llm, lang)):
        res = llm.chat_json(
            "chart_facts",
            {"text": part, "language": lang, "language_name": LANGUAGE_NAMES.get(lang, "English")},
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
