"""Sentence-aware chunks of note text with their offsets (T-203a, D-439).

The input is note text after the PHI pass (``tb_common.phi_guard.mask_note``), which keeps the length: an offset into
the masked text is the same offset into the original note. Every chunk's text is exactly ``text[start:end]``.

Sentences end at ``。！？；`` (and their full-width or Latin kin ``!?;``), at ``.`` followed by white space or the end
of the text (so ``9.2`` is not cut), and at a line break. Sentences are packed into chunks of at most ``size``
characters; the next chunk starts with the whole trailing sentences of the previous one that fit in ``overlap``
characters. A sentence longer than ``size`` is cut into windows of ``size`` with ``overlap``. White space at a
chunk's edges is left out of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tb_common.crypto import sha256_text

SIZE = 500
OVERLAP = 100
_END = re.compile(r"[。！？；!?;]+|\.(?=\s|$)|\n+")


@dataclass(frozen=True)
class Chunk:
    no: int
    start: int
    end: int
    text: str

    @property
    def sha(self) -> str:
        return sha256_text(self.text)


def sentences(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each sentence, white space at its edges left out; empty sentences dropped."""
    out: list[tuple[int, int]] = []
    pos = 0
    for m in _END.finditer(text):
        out.append((pos, m.end()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text)))
    trimmed = []
    for s, e in out:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            trimmed.append((s, e))
    return trimmed


def _windows(s: int, e: int, size: int, overlap: int) -> list[tuple[int, int]]:
    step = size - overlap
    out = []
    start = s
    while True:
        out.append((start, min(start + size, e)))
        if start + size >= e:
            return out
        start += step


def spans(text: str, size: int = SIZE, overlap: int = OVERLAP) -> list[tuple[int, int]]:
    """``(start, end)`` of each chunk of ``text``, in order."""
    if size <= overlap or overlap < 0:
        raise ValueError("size must exceed overlap, and overlap must not be negative")
    units: list[tuple[int, int]] = []
    for s, e in sentences(text):
        units.extend(_windows(s, e, size, overlap) if e - s > size else [(s, e)])
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(units):
        start = units[i][0]
        j = i
        while j + 1 < len(units) and units[j + 1][1] - start <= size:
            j += 1
        out.append((start, units[j][1]))
        if j + 1 >= len(units):
            break
        # the next chunk starts with the whole trailing units of this one that fit in the overlap
        k = j + 1
        while k - 1 > i and units[j][1] - units[k - 1][0] <= overlap:
            k -= 1
        i = k
    return out


def chunk_note(masked: str, size: int = SIZE, overlap: int = OVERLAP) -> list[Chunk]:
    """The chunks of a masked note, numbered from 0."""
    return [Chunk(n, s, e, masked[s:e]) for n, (s, e) in enumerate(spans(masked, size, overlap))]


def byte_span(text: str, start: int, end: int) -> tuple[int, int]:
    """The UTF-8 byte offsets of the character span ``[start, end)`` of ``text``."""
    b0 = len(text[:start].encode("utf-8"))
    return b0, b0 + len(text[start:end].encode("utf-8"))
