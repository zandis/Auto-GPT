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
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from doc_parser.hidden_text import hidden_text
from tb_common import catalogue, encoding
from tb_common.quotes import quote_in

from sitesetup import messy
from sitesetup.ocr import Ocr

TEXT_EXT = (".txt", ".md")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
CHART_EXT = (*TEXT_EXT, ".docx", ".pdf", *IMAGE_EXT)
MAX_CHART_BYTES = 20 * 1024 * 1024
MAX_CHART_CHARS = 60_000
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
SYSTEMS = {"icd10cm": ICD10CM, "loinc": LOINC, "atc": ATC, "": ""}
LOINC_ANALYTE = {a.loinc: name for name, a in messy.ANALYTES.items()}
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


def normalise(raw: dict[str, Any]) -> dict[str, str] | None:
    """One model fact as a store fact (``sitesetup.store``), or None when it cannot be one (an unreadable date of
    birth, a lab value that is not a number, a unit TrialBox does not know for the test)."""
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
        return {**base, "domain": "condition", "code": code if system else "", "system": system if code else ""}
    if dom == "medication":
        return {**base, "domain": "medication", "code": code if system == ATC else "", "system": ATC if code else ""}
    if dom == "observation":
        num, cell_unit = messy.parse_number(str(raw.get("value") or ""))
        if num is None:
            return None
        analyte = LOINC_ANALYTE.get(code) or messy.analyte_of(term) or ""
        unit = messy.norm_unit(str(raw.get("unit") or "")) or cell_unit
        conv = messy.convert(analyte, num, unit) if unit else None
        if conv is None:
            return None
        value, stored, _ = conv
        if not code and analyte in messy.ANALYTES:
            code, system = messy.ANALYTES[analyte].loinc, LOINC
        return {
            **base,
            "domain": "observation",
            "code": code,
            "system": system if code else "",
            "value": f"{value:g}",
            "unit": stored,
        }
    return None


def extract(llm: _Llm, text: str, lang: str, job_id: str | None = None) -> tuple[list[dict[str, str]], int]:
    """``(proposed facts, facts dropped)``: a fact whose quote is not in the chart is dropped, never kept."""
    res = llm.chat_json(
        "chart_facts",
        {"text": text, "language": lang, "language_name": LANGUAGE_NAMES.get(lang, "English")},
        job_id=job_id,
    )
    data = res.data if hasattr(res, "data") else res
    kept: list[dict[str, str]] = []
    dropped = 0
    seen: set[tuple[str, ...]] = set()
    for raw in data.get("facts") or []:
        if not quote_in(str(raw.get("quote") or ""), text):
            dropped += 1
            continue
        if catalogue.refused_fact(str(raw.get("term") or ""), str(raw.get("code") or "").strip()):
            dropped += 1  # T-107 (D-353): an item answer of a score-only instrument is never kept
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
