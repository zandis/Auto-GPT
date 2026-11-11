"""Hidden text in an uploaded document (T-208, D-346; review LLM-034).

Text a reader cannot see is the easiest place to plant an instruction for a model: white letters on a white page, the
PDF's invisible text mode, letters under one point high, or Word's hidden-text format. The model reads the extracted
text, so it reads that text too; the person who checks the facts does not. This module counts such characters so the
parser can flag the document. The text itself is not removed: it stays data, and the flag tells the person why a
fact or a criterion may quote something they cannot see on the page.

* **PDF:** the page content stream is read operator by operator (``q``/``Q``, ``rg``/``g``/``k`` fill colour, ``Tr``
  render mode, ``Tf`` size, ``Tm`` scale). A string drawn in white (the page is taken to be white), in render mode 3
  or 7 (no fill, no stroke), or at under :data:`MIN_POINTS` is counted. Text inside form XObjects is not read.
* **DOCX:** every run of the body and of table cells; hidden (``w:vanish``), white, or under :data:`MIN_POINTS`.

Only counts and kinds leave this module, never the hidden text (it may be patient text).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any

MIN_POINTS = 1.0  # letters smaller than this are not readable on a page or a screen
MIN_CHARS = 3  # fewer hidden characters than this (a stray white space-like glyph) is not flagged
_INVISIBLE_MODES = (3, 7)


@dataclass(frozen=True)
class HiddenText:
    chars: int = 0  # non-space characters a reader cannot see
    kinds: tuple[str, ...] = ()  # white | invisible | tiny | vanish

    @property
    def found(self) -> bool:
        return self.chars >= MIN_CHARS

    def warning(self) -> str:
        return (
            f"hidden text: {self.chars} characters cannot be seen on the page ({', '.join(self.kinds)}); "
            "they are read as data and never followed"
        )


@dataclass
class _State:
    fill_white: bool = False
    mode: int = 0
    size: float = 12.0
    scale: float = 1.0
    stack: list[tuple[bool, int, float, float]] = field(default_factory=list)


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _glyphs(operand: Any) -> int:
    """Non-space characters in a ``Tj`` string or a ``TJ`` array (kerning numbers skipped)."""
    if isinstance(operand, list):
        return sum(_glyphs(x) for x in operand if not isinstance(x, (int, float)))
    if isinstance(operand, bytes | bytearray):
        return sum(1 for b in bytes(operand) if b not in b" \t\r\n\x00")
    if isinstance(operand, str):
        return sum(1 for c in operand if not c.isspace() and c != "\x00")
    raw = getattr(operand, "original_bytes", None)
    return _glyphs(raw) if raw is not None else 0


def pdf_hidden_text(data: bytes) -> HiddenText:
    from pypdf import PdfReader
    from pypdf.generic import ContentStream

    reader = PdfReader(io.BytesIO(data))
    counts: dict[str, int] = {}
    for page in reader.pages:
        contents = page.get_contents()
        if contents is None:
            continue
        st = _State()
        for operands, op in ContentStream(contents, reader).operations:
            name = op.decode("latin-1") if isinstance(op, bytes) else str(op)
            if name == "q":
                st.stack.append((st.fill_white, st.mode, st.size, st.scale))
            elif name == "Q" and st.stack:
                st.fill_white, st.mode, st.size, st.scale = st.stack.pop()
            elif name == "rg" and len(operands) == 3:
                st.fill_white = all(_num(x) >= 0.98 for x in operands)
            elif name == "g" and len(operands) == 1:
                st.fill_white = _num(operands[0]) >= 0.98
            elif name == "k" and len(operands) == 4:
                st.fill_white = all(_num(x) <= 0.02 for x in operands)
            elif name == "Tr" and operands:
                st.mode = int(_num(operands[0]))
            elif name == "Tf" and len(operands) == 2:
                st.size = abs(_num(operands[1]))
            elif name == "Tm" and len(operands) == 6:
                st.scale = math.hypot(_num(operands[2]), _num(operands[3])) or 1.0
            elif name in ("Tj", "TJ", "'", '"') and operands:
                n = _glyphs(operands[-1])
                if not n:
                    continue
                if st.mode in _INVISIBLE_MODES:
                    counts["invisible"] = counts.get("invisible", 0) + n
                elif st.fill_white:
                    counts["white"] = counts.get("white", 0) + n
                elif st.size * st.scale < MIN_POINTS:
                    counts["tiny"] = counts.get("tiny", 0) + n
    return HiddenText(sum(counts.values()), tuple(sorted(counts)))


def docx_hidden_text(data: bytes) -> HiddenText:
    import docx
    from docx.shared import RGBColor

    d = docx.Document(io.BytesIO(data))
    paragraphs = list(d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    counts: dict[str, int] = {}
    white = RGBColor(0xFF, 0xFF, 0xFF)
    for p in paragraphs:
        for run in p.runs:
            n = sum(1 for c in run.text if not c.isspace())
            if not n:
                continue
            f = run.font
            color = f.color.rgb if f.color is not None and f.color.type is not None else None
            if f.hidden:
                kind = "vanish"
            elif color == white:
                kind = "white"
            elif f.size is not None and f.size.pt < MIN_POINTS:
                kind = "tiny"
            else:
                continue
            counts[kind] = counts.get(kind, 0) + n
    return HiddenText(sum(counts.values()), tuple(sorted(counts)))


def hidden_text(kind: str, data: bytes) -> HiddenText:
    """Hidden characters of a ``pdf`` or ``docx`` file; nothing for other kinds or a file that cannot be read this
    way (the parser reports an unreadable file on its own)."""
    try:
        if kind == "pdf":
            return pdf_hidden_text(data)
        if kind == "docx":
            return docx_hidden_text(data)
    except Exception:  # a damaged stream: the text extraction decides whether the file is usable
        return HiddenText()
    return HiddenText()
