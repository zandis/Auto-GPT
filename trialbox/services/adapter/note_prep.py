"""``note_prep``: the deterministic pre-processing of a clinical note into ``note_segment`` rows (MATCH-ARCH
layer (a)).

One pure function, ``prepare(did, text, note_date)``, no model, no network, the same bytes for the same input:

* **sections** by header (``Chief complaint:``, ``【主訴】``, ``家族歴``, ``用藥``, ``A/P`` ...) in English,
  Japanese and Chinese: ``chief_complaint``, ``history``, ``medication``, ``assessment_plan``, ``family_history``,
  ``allergy``; ``other`` for a header of another part of the note (exam, labs, social); ``unlabelled`` before the
  first header. A header is a whole line, or a ``Header:`` at the start of a line, that is in the tables; any other
  line is text. ``family_history`` means the family, not the patient, whatever the sentence says.
* **sentences** by line, bullet, and the sentence marks (``。``, ``．``, ``!``, ``?``, ``.`` before a capital, digit
  or non-ASCII letter and not after an abbreviation or an initial). Hard-wrapped prose is split at every line: a
  sentence that continues on the next line is two segments, and a sentence that starts in lower case after a full
  stop is read as a continuation of the one before (the known ceilings; the section and every cue stay right).
* per segment, on its **NFKC** text (full-width digits, units and punctuation folded): the ConText cues
  (:mod:`adapter.note_cues`), the dates as ISO intervals including wareki and ROC years
  (:mod:`adapter.note_dates`), and the numbers with their units (``tb_common.labvalue.ucum`` for lab units, a small
  dose table for ``mg``, ``mg/day``).

**Nothing is dropped.** Every sentence of the note is a segment; a header label, a bullet mark, blanks and a
stretch with no letter or digit in it are the only text no segment holds. A cue is a tag, not a verdict (see
:mod:`adapter.note_cues`); a number with an unknown unit and a relative date with no note date are not emitted
(unknown carries nothing). ``start`` and ``end`` are offsets in the RAW note, ``raw == text[start:end]`` exactly, so
a quote can be checked against the note byte for byte; ``text`` is the NFKC form and the offsets of cues, dates and
numbers are in that ``text``.

``cache_key`` is the sha256 of (``PREP_VERSION``, note date, note text): a note that did not change is never
prepared twice and a new table version (a bump of ``PREP_VERSION``) misses every old row. The cache is a mapping the
caller passes in. A prepared note holds the note's text, so where it is kept is the lake's to decide (its store, its
``phi`` label and its row in the record inventory); this module writes nothing to disk.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import MutableMapping
from dataclasses import asdict, dataclass
from typing import Any

from tb_common import labvalue

from adapter import note_cues, note_dates

PREP_VERSION = "note-prep-1"

SECTIONS = ("chief_complaint", "history", "medication", "assessment_plan", "family_history", "allergy")
_HEADERS: dict[str, tuple[str, ...]] = {
    "chief_complaint": ("cc", "chief complaint", "chief complaints", "reason for visit", "presenting complaint",
                        "主訴", "主诉", "来院理由", "來院理由"),
    "history": ("hpi", "history of present illness", "history", "pmh", "pmhx", "past medical history", "past history",
                "medical history", "現病歴", "既往歴", "既往", "病歴", "現病史", "病史", "既往史", "過去病史"),
    "medication": ("medications", "medication", "meds", "current medications", "home medications", "rx", "内服薬",
                   "内服", "処方", "服薬", "常用薬", "用藥", "用药", "目前用藥", "現用藥", "處方"),
    "assessment_plan": ("assessment", "plan", "assessment and plan", "assessment/plan", "a/p", "a&p", "impression",
                        "評価", "計画", "方針", "診断", "評価・計画", "評估", "計畫", "處置", "診斷", "診斷與處置",
                        "診斷/處置", "診斷及處置"),
    "family_history": ("family history", "fhx", "fh", "家族歴", "家族史"),
    "allergy": ("allergies", "allergy", "nkda", "drug allergies", "アレルギー", "アレルギー歴", "過敏", "過敏史",
                "藥物過敏", "药物过敏", "过敏史"),
    "other": ("social history", "sh", "exam", "physical exam", "pe", "ros", "review of systems", "labs", "laboratory",
              "vitals", "生活歴", "社会歴", "身体所見", "理学所見", "検査", "検査所見", "バイタル", "個人史",
              "理學檢查", "檢查"),
}  # fmt: skip
_HEADER_OF = {name: label for label, names in _HEADERS.items() for name in names}
_BRACKET = re.compile(r"^[ \t]*[\[【(（][ \t]*([^\]】)）\n]{1,40}?)[ \t]*[\]】)）][ \t]*[:：]?")
_COLON = re.compile(r"^[ \t]*[#*]*[ \t]*([^:：\n]{1,40}?)[ \t]*[:：]")
_WHOLE = re.compile(r"^[ \t]*[#*]*[ \t]*([^\n]{1,40}?)[ \t]*$")
_BULLET = re.compile(r"^[ \t]*(?:[-*•・●○▪]+|\(?\d{1,2}[.)）](?=\s)|[①-⑩])[ \t]*")
_STOP = re.compile(r"(?:[。．！？!?]+|\.(?=\s|$))[」』）)\"'”’]*")
_ABBREV = frozenset({"dr", "mr", "mrs", "ms", "prof", "vs", "approx", "e.g", "i.e", "cf", "fig", "no", "st", "dept"})
_LETTER_OR_CJK = re.compile(r"[^\W_]")
_NUM = re.compile(
    r"(?<![A-Za-z0-9_./])(?P<cmp><=|>=|<|>|≦|≤|≧|≥)?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>[A-Za-zµμ][A-Za-zµμ0-9^*{}\[\]]*(?:/(?:(?:[A-Za-zµμ0-9^*{}\[\]%]|\.(?=\d))+|[日天週周]))*|%|/[A-Za-zµμ]{1,3}\b)"
)
_DOSE = {"mg": "mg", "g": "g", "ug": "ug", "µg": "ug", "μg": "ug", "mcg": "ug", "ml": "mL", "iu": "[IU]", "u": "U"}
_PER = {
    "day": "d",
    "d": "d",
    "日": "d",
    "天": "d",
    "wk": "wk",
    "week": "wk",
    "週": "wk",
    "周": "wk",
    "h": "h",
    "hr": "h",
}
_CMP = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "≦": "<=", "≤": "<=", "≧": ">=", "≥": ">="}


@dataclass(frozen=True)
class Quantity:
    start: int  # offsets in the segment's NFKC text
    end: int
    text: str
    value: float
    comparator: str | None
    unit: str  # as written, NFKC
    ucum: str


@dataclass(frozen=True)
class Segment:
    did: str
    seg_id: int
    section: str
    start: int  # offsets in the RAW note: raw == note[start:end]
    end: int
    raw: str
    text: str  # NFKC of raw
    cues: tuple[note_cues.Cue, ...]
    dates: tuple[note_dates.DateRef, ...]
    numbers: tuple[Quantity, ...]

    def row(self) -> dict[str, Any]:
        """The ``note_segment`` row: JSON-able, keyed by (did, seg_id), with the table version."""
        d = asdict(self)
        d["cues"] = [c._asdict() for c in self.cues]
        d["dates"] = [x._asdict() for x in self.dates]
        d["numbers"] = [asdict(q) for q in self.numbers]
        d["prep_version"] = PREP_VERSION
        return d


def _header(line: str) -> tuple[str, int] | None:
    """``(section label, end of the header in the line)`` when the line starts with a header of the tables."""
    for rx in (_BRACKET, _COLON, _WHOLE):
        m = rx.match(line)
        if m:
            name = re.sub(r"\s*([/&])\s*", r"\1", unicodedata.normalize("NFKC", m.group(1)).casefold()).strip(" .")
            label = _HEADER_OF.get(re.sub(r"\s+", " ", name))
            if label:
                return label, m.end()
    return None


def _sentences(line: str, base: int) -> list[tuple[int, int]]:
    """Spans (raw offsets) of the sentences of one line, bullet mark and blanks left out."""
    lead = _BULLET.match(line)
    pos = lead.end() if lead else 0
    out: list[tuple[int, int]] = []

    def emit(a: int, b: int) -> None:
        while a < b and line[a].isspace():
            a += 1
        while b > a and line[b - 1].isspace():
            b -= 1
        if a < b and _LETTER_OR_CJK.search(line[a:b]):
            out.append((base + a, base + b))

    for m in _STOP.finditer(line, pos):
        if line[m.start()] == ".":
            before = line[pos : m.start()]
            word = re.search(r"([A-Za-z][A-Za-z.]*)$", before)
            tail = line[m.end() :].lstrip()
            initial = re.search(r"(?:^|\s)[A-Z]$", before)  # "J. Smith"; the L of "U/L" is a unit
            if initial or (word and word.group(1).lower() in _ABBREV) or (tail and tail[0].islower()):
                continue
        emit(pos, m.end())
        pos = m.end()
    emit(pos, len(line))
    return out


def _quantities(text: str, blocked: list[tuple[int, int]]) -> tuple[Quantity, ...]:
    out: list[Quantity] = []
    for m in _NUM.finditer(text):
        if any(s < m.end() and m.start() < e for s, e in blocked):
            continue
        unit = m.group("unit")
        code = labvalue.ucum(unit)
        if code is None:
            head, _, per = unit.partition("/")
            base = _DOSE.get(head.lower())
            if base and not per:
                code = base
            elif base and (per.lower() in _PER or per in _PER):
                code = f"{base}/{_PER.get(per.lower()) or _PER[per]}"
        if code is None:
            continue
        value = float(m.group("num").replace(",", ""))
        first = m.start("cmp") if m.group("cmp") else m.start("num")
        out.append(Quantity(first, m.end(), text[first : m.end()], value, _CMP.get(m.group("cmp") or ""), unit, code))
    return tuple(out)


def _prepare(text: str, note_date: object) -> list[dict[str, Any]]:
    """Segments without ``did``, as JSON-able dicts (the cached body)."""
    body: list[dict[str, Any]] = []
    section = "unlabelled"
    offset = 0
    for line in text.split("\n"):
        line_body = line.rstrip("\r")
        start, hdr = offset, _header(line_body)
        offset += len(line) + 1
        if hdr:
            section, cut = hdr
            line_body, start = line_body[cut:], start + cut
        for a, b in _sentences(line_body, start):
            raw = text[a:b]
            norm = unicodedata.normalize("NFKC", raw)
            dates = note_dates.dates_in(norm, note_date)
            body.append(
                {
                    "seg_id": len(body),
                    "section": section,
                    "start": a,
                    "end": b,
                    "raw": raw,
                    "text": norm,
                    "cues": [c._asdict() for c in note_cues.tag(norm)],
                    "dates": [d._asdict() for d in dates],
                    "numbers": [asdict(q) for q in _quantities(norm, [(d.start, d.end) for d in dates])],
                }
            )
    return body


def cache_key(text: str, note_date: object = None) -> str:
    nd = note_dates.parse_note_date(note_date)
    return hashlib.sha256(f"{PREP_VERSION}\0{nd.isoformat() if nd else ''}\0{text}".encode()).hexdigest()


def prepare(
    did: str, text: str, note_date: object = None, *, cache: MutableMapping[str, list[dict[str, Any]]] | None = None
) -> list[Segment]:
    """The ``note_segment`` rows of one note. ``note_date`` (a date or ``YYYY-MM-DD``) lets a relative date resolve.
    ``cache`` is any mapping the caller owns (``cache_key`` is its key); this module opens no store of its own."""
    key = cache_key(text, note_date)
    body = cache.get(key) if cache is not None else None
    if body is None:
        body = _prepare(text, note_date)
        if cache is not None:
            cache[key] = body
    return [
        Segment(
            did,
            s["seg_id"],
            s["section"],
            s["start"],
            s["end"],
            s["raw"],
            s["text"],
            tuple(note_cues.Cue(**c) for c in s["cues"]),
            tuple(note_dates.DateRef(**d) for d in s["dates"]),
            tuple(Quantity(**q) for q in s["numbers"]),
        )
        for s in body
    ]
