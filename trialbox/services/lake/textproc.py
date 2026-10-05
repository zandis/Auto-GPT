"""Text processing for the lake: CJK-aware tokenisation (bigrams) and fixed-size chunking (SPEC §4.5)."""

from __future__ import annotations

import re
import unicodedata

_CJK = r"぀-ヿ㐀-䶿一-鿿豈-﫿"
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[a-z0-9]+(?:\.[0-9]+)?")


def tokens(text: str) -> list[str]:
    """Latin/digit words lower-cased; CJK runs as overlapping character bigrams (single char if run of one)."""
    norm = unicodedata.normalize("NFKC", text).lower()
    out: list[str] = []
    for m in _TOKEN_RE.finditer(norm):
        run = m.group(0)
        if re.match(rf"[{_CJK}]", run):
            if len(run) == 1:
                out.append(run)
            else:
                out.extend(run[i : i + 2] for i in range(len(run) - 1))
        else:
            out.append(run)
    return out


def token_string(text: str) -> str:
    return " ".join(tokens(text))


def chunk(text: str, size: int = 500, overlap: int = 100) -> list[str]:
    """Character windows of ``size`` with ``overlap`` (SPEC §4.5: 500 chars, 100 overlap)."""
    if size <= overlap:
        raise ValueError("size must exceed overlap")
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = size - overlap
    out = []
    for start in range(0, len(text), step):
        piece = text[start : start + size]
        out.append(piece)
        if start + size >= len(text):
            break
    return out


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
