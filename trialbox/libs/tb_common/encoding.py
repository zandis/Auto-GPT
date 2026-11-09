"""Which character set a site's file is in (T-118, D-215; review R-33, MR-013, E-05): one detector.

Sites send CSV sheets and text in UTF-8, Shift_JIS (as CP932, with the Windows extensions) or Big5 (Taiwan; CP950 is
its Windows superset), and SS-MIX2 extended storage may be EUC-JP. Before D-215 each reader tried a fixed list of
codecs and took the **first that did not fail**; a Big5 sheet whose text is only in its header often decodes as CP932
without an error (``姓名`` becomes ``ｩmｦW``), so the name-column guard never fired (MR-013), and other readers
replaced what they could not read with U+FFFD.

:func:`detect` returns ``(codec, confidence)``:

1. a UTF-8 byte-order mark is UTF-8 (``utf-8-sig``); bytes that are valid UTF-8 are UTF-8 when what they decode to
   is usual text (CJK, kana, the unit symbols µ ° ±) or holds three or more non-ASCII characters, confidence 1.0.
   One or two characters that read as Latin Extended or an accented letter may be legacy bytes that happen to be
   valid UTF-8 (Big5 ``臟`` is C5 A6, UTF-8 ``Ŧ``): then UTF-8 is weighed with the others below, with a head start;
2. every candidate codec that decodes the **whole** file strictly is scored on what it decodes to: each
   non-ASCII character is weighed by how usual it is in that character set (:func:`_weight`: hiragana, katakana and
   JIS level-1 kanji for CP932; the frequent-hanzi block A440–C67E for Big5; a half-width katakana that cannot start
   a word, private-use and control characters score nothing). Big5 read as CP932 is mostly half-width katakana and
   private-use characters; Shift_JIS read as Big5 mostly fails;
3. the confidence is the best score less how close the second comes, ``best * (1 - (second / best) ** 4)``;
4. below :data:`THRESHOLD`, or when no candidate decodes the whole file, :class:`EncodingRefused` is raised
   (``FORM-ENCODING``, with the line where the file stops being readable, or the first line written in another
   encoding than the lines before it). A person re-saves the file; nothing is guessed.

:func:`decode` is the strict read every caller uses: the text, never a U+FFFD.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

THRESHOLD = 0.6
UTF8_IMPLAUSIBLE = 0.3  # valid UTF-8 scoring this or less is weighed against the legacy readings, however long
UTF8_HEAD_START = 0.3  # what being valid UTF-8 is worth when it is weighed
LEGACY: tuple[str, ...] = ("cp932", "big5")  # the sheets' default candidates after UTF-8
_FAMILY = {"big5": ("big5", "cp950"), "cp932": ("cp932",), "euc_jp": ("euc_jp",)}
_SAMPLE = 200_000  # characters scored at most (the strict decode always covers the whole file)
_BOM = b"\xef\xbb\xbf"


class EncodingRefused(ValueError):
    """``FORM-ENCODING``: the file's character set cannot be told for certain. ``line`` is 1-based, or None."""

    code = "FORM-ENCODING"

    def __init__(self, message: str, line: int | None = None) -> None:
        where = f" (line {line})" if line is not None else ""
        super().__init__(f"FORM-ENCODING: {message}{where}")
        self.message = message
        self.line = line


# ------------------------------------------------------------------------------------------------ scoring
_HW_KANA = range(0xFF61, 0xFFA0)
# half-width katakana that cannot begin a word: small kana, the long-vowel mark, (semi-)voiced marks, ン, the particle
# ヲ, and the half-width punctuation 。「」、・ (Big5's most frequent lead bytes A4-A6 read as CP932 are ､･ｦ)
_HW_NOT_FIRST = set("ｦｧｨｩｪｫｬｭｮｯｰﾞﾟﾝ｡｢｣､･")


def _hw_run_ok(text: str, i: int) -> bool:
    """Whether the half-width katakana at ``i`` belongs to a plausible run: the run does not start with a mark that
    cannot begin a word and is not glued to an ASCII letter or symbol (Big5 trail bytes 0x40-0x7E read as CP932)."""
    j = i
    while j > 0 and ord(text[j - 1]) in _HW_KANA:
        j -= 1
    k = i
    while k + 1 < len(text) and ord(text[k + 1]) in _HW_KANA:
        k += 1
    if text[j] in _HW_NOT_FIRST:
        return False
    for n in (j - 1, k + 1):
        if 0 <= n < len(text) and (text[n].isascii() and (text[n].isalpha() or text[n] in "@[\\]^_`{|}~")):
            return False
    return True


_LATIN1_SYMBOLS = set("µ°±×÷²³¹·§©®¼½¾«»¢£¥¬¦¯´¸ªº¿¡")


def _weight_utf8(ch: str) -> float:
    """How usual a character is in a Japanese or Taiwanese site's UTF-8 file: CJK, kana, full-width forms and the
    unit symbols (µ ° ±) are; Latin Extended, IPA and the right-to-left scripts (what two legacy bytes become when
    they happen to be valid UTF-8: Big5 臟 C5 A6 is ``Ŧ``) are not."""
    o = ord(ch)
    if 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF:
        return 1.0
    if 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF or 0x2000 <= o <= 0x27BF or 0x3200 <= o <= 0x33FF:
        return 0.9
    if 0xA0 <= o <= 0xFF:
        return 0.9 if ch in _LATIN1_SYMBOLS else 0.6
    if 0x370 <= o <= 0x3FF or 0x1E00 <= o <= 0x1EFF or 0xAC00 <= o <= 0xD7AF:
        return 0.6
    if 0x400 <= o <= 0x4FF:
        return 0.4
    if o < 0x800:  # Latin Extended-A/B, IPA, modifiers, combining marks, Armenian, Hebrew, Arabic, Syriac, ...
        return 0.2
    return 0.5


def _weight(codec: str, ch: str, text: str, i: int) -> float:
    """How usual ``ch`` (a non-ASCII character decoded by ``codec``) is in that character set, 0..1."""
    cat = unicodedata.category(ch)
    if cat in ("Co", "Cc", "Cn", "Cs") or ch == "\ufffd":
        return 0.0
    if codec in ("utf-8", "utf-8-sig"):
        return _weight_utf8(ch)
    try:
        b = ch.encode(codec)
    except UnicodeEncodeError:
        return 0.0
    if codec == "cp932":
        if len(b) == 1:  # half-width katakana
            return 0.9 if _hw_run_ok(text, i) else 0.05
        hi = b[0]
        if hi == 0x81:
            return 0.8  # punctuation and symbols
        if hi in (0x82, 0x83):
            return 1.0  # full-width digits and letters, hiragana, katakana
        if hi == 0x84:
            return 0.5  # Cyrillic, box drawing
        if hi == 0x87:
            return 0.7  # circled numbers, units (NEC row 13)
        if 0x88 <= hi <= 0x97 or (hi == 0x98 and b[1] <= 0x72):
            return 1.0  # JIS level 1 kanji
        if hi <= 0x9F or 0xE0 <= hi <= 0xEA:
            return 0.4  # JIS level 2 kanji
        return 0.15  # NEC-selected / IBM extensions
    if codec in ("big5", "cp950"):
        hi = b[0]
        if 0xA1 <= hi <= 0xA3:
            return 0.8  # punctuation and symbols
        if 0xA4 <= hi <= 0xC5 or (hi == 0xC6 and b[1] <= 0x7E):
            return 1.0  # frequent hanzi
        if 0xC9 <= hi <= 0xF9:
            return 0.4  # less frequent hanzi
        return 0.1
    if codec == "euc_jp":
        hi = b[0]
        if hi in (0xA1, 0xA2):
            return 0.8
        if hi in (0xA3, 0xA4, 0xA5):
            return 1.0  # full-width digits and letters, hiragana, katakana
        if 0xB0 <= hi <= 0xCF:
            return 1.0  # JIS level 1
        if 0xD0 <= hi <= 0xF4:
            return 0.4
        return 0.1  # half-width kana (0x8E), JIS X 0212 (0x8F), Greek, Cyrillic, box drawing
    return 0.5


def score(codec: str, text: str) -> float:
    """The mean :func:`_weight` of the non-ASCII characters of ``text`` (1.0 for ASCII-only text)."""
    sample = text[:_SAMPLE]
    w = [_weight(codec, ch, sample, i) for i, ch in enumerate(sample) if not ch.isascii()]
    return sum(w) / len(w) if w else 1.0


# ------------------------------------------------------------------------------------------------ detection
def _first_bad_line(data: bytes, codecs: Sequence[str]) -> int:
    """The 1-based line where the file stops decoding, for the candidate that reads furthest."""
    best = 0
    for c in codecs:
        for enc in _FAMILY.get(c, (c,)):
            try:
                data.decode(enc)
                continue
            except UnicodeDecodeError as exc:
                best = max(best, exc.start)
    return data.count(b"\n", 0, best) + 1


def _mixed_line(data: bytes) -> int | None:
    """The first line written in another encoding than the non-ASCII lines before it (UTF-8 against not), or None."""
    first: bool | None = None
    for n, line in enumerate(data.split(b"\n"), start=1):
        if line.isascii():
            continue
        try:
            line.decode("utf-8")
            utf8 = True
        except UnicodeDecodeError:
            utf8 = False
        if first is None:
            first = utf8
        elif utf8 != first:
            return n
    return None


def _strict(data: bytes, codec: str) -> tuple[str, str] | None:
    """``(text, member)``: the first member of ``codec``'s family that decodes the whole of ``data`` (Big5, else its
    Windows superset CP950), or None."""
    for enc in _FAMILY.get(codec, (codec,)):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None


def detect(data: bytes, candidates: Sequence[str] = LEGACY) -> tuple[str, float]:
    """``(codec, confidence)`` for ``data``; raises :class:`EncodingRefused` below :data:`THRESHOLD`. ``candidates``
    are the legacy codecs this kind of file may be in (UTF-8 is always tried first)."""
    if data.startswith(_BOM):
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise EncodingRefused(
                "the file starts as UTF-8 but is not UTF-8 throughout", data.count(b"\n", 0, exc.start) + 1
            ) from exc
        return "utf-8-sig", 1.0
    scored: list[tuple[float, str]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        mixed = _mixed_line(data)
        if mixed is not None:
            raise EncodingRefused("the file mixes two character sets", mixed) from None
    else:
        utf8 = score("utf-8", text)
        wide = sum(1 for ch in text[:_SAMPLE] if not ch.isascii())
        if utf8 >= 0.9 or (wide >= 3 and utf8 > UTF8_IMPLAUSIBLE):
            return "utf-8", 1.0
        # one or two characters that read as Latin Extended, an accented letter or Arabic: valid UTF-8 by chance
        # (Big5 臟 is C5 A6, which is also UTF-8 Ŧ)? Weighed against the legacy readings, with a head start
        scored.append((min(1.0, utf8 + UTF8_HEAD_START), "utf-8"))
    for c in candidates:
        got = _strict(data, c)
        if got is not None:
            scored.append((score(got[1], got[0]), got[1]))
    if not scored:
        names = ", ".join(("UTF-8", *candidates))
        raise EncodingRefused(f"the file is not text in any of {names}", _first_bad_line(data, candidates))
    scored.sort(reverse=True)
    best, codec = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    confidence = best * (1 - (second / best) ** 4) if best > 0 else 0.0
    if confidence < THRESHOLD:
        others = ", ".join(f"{c} {s:.2f}" for s, c in scored)
        raise EncodingRefused(f"the character set cannot be told for certain ({others})")
    return codec, round(confidence, 3)


def decode(data: bytes, candidates: Sequence[str] = LEGACY) -> tuple[str, str]:
    """``(text, codec)``: the file read strictly in the detected codec. Raises :class:`EncodingRefused`; a U+FFFD in
    the text (a file already damaged before it reached the box) is refused too, with its line."""
    codec, _ = detect(data, candidates)
    text = data.decode(codec)
    at = text.find("\ufffd")
    if at >= 0:
        raise EncodingRefused("the file holds replacement characters (U+FFFD)", text.count("\n", 0, at) + 1)
    return text, codec


__all__ = ["LEGACY", "THRESHOLD", "EncodingRefused", "decode", "detect", "score"]
