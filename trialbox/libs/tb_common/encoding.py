"""Which character set a site's file is in (T-118, D-215; review R-33, MR-013, E-05): one detector.

Sites send CSV sheets and text in UTF-8, Shift_JIS (as CP932, with the Windows extensions) or Big5 (Taiwan; CP950 is
its Windows superset), and SS-MIX2 extended storage may be EUC-JP. Before D-215 each reader tried a fixed list of
codecs and took the **first that did not fail**; a Big5 sheet whose text is only in its header often decodes as CP932
without an error (``姓名`` becomes ``ｩmｦW``), so the name-column guard never fired (MR-013), and other readers
replaced what they could not read with U+FFFD.

:func:`detect` returns ``(codec, confidence)``. The contract is **the right text or a refusal, never wrong text**:

1. a UTF-8 byte-order mark is UTF-8 (``utf-8-sig``); ASCII is UTF-8; valid UTF-8 holding at least
   :data:`UTF8_SURE` usual non-ASCII characters (CJK, kana, full-width forms, the unit symbols µ ° ±) is UTF-8,
   confidence 1.0. Fewer may be legacy bytes that happen to be valid UTF-8 (Big5 ``職`` is C2 BE, UTF-8 ``¾``): then
   UTF-8 is weighed with the others below, with a head start;
2. every candidate that decodes the **whole** file strictly, and every :data:`RIVALS` character set nobody asked
   for (EUC-JP, GB18030, ...), is scored on what it decodes to: each non-ASCII character weighed by how usual it is
   in that character set (:func:`_weight`: hiragana, katakana and JIS level-1 kanji for CP932; the frequent-hanzi
   block for Big5; GB2312 level 1 for GB18030; a half-width katakana run that cannot start a word, private-use and
   control characters score nothing);
3. the best candidate must lead the other candidates clearly (``best * (1 - (second / best) ** 4)`` at least
   :data:`THRESHOLD`), and no rival may read the file better than it does;
4. a non-UTF-8 file whose lines are read clearly by different candidates (a Big5 line inside a Shift_JIS file, even
   one Shift_JIS decodes as mojibake), or that mixes UTF-8 and non-UTF-8 lines, is refused with that line;
5. otherwise :class:`EncodingRefused` (``FORM-ENCODING``, with the line where the file stops being readable when
   that is known). A person re-saves the file (UTF-8 is always read); nothing is guessed. A few short cells can be
   read alike by two character sets, so a sheet with little text is refused more often than one with much.

:func:`decode` is the strict read every caller uses: the text, never a U+FFFD.
"""

from __future__ import annotations

import codecs
import unicodedata
from collections.abc import Sequence
from pathlib import Path

THRESHOLD = 0.6
# character sets that are never chosen unless asked for, but are weighed: when one reads a file as well as the
# chosen candidate, the file is refused rather than read wrong (GB18030 against Big5, EUC-JP against CP932)
RIVALS: tuple[str, ...] = ("cp932", "big5", "euc_jp", "gb18030")
UTF8_SURE = 3  # valid UTF-8 with at least this many usual non-ASCII characters is read without weighing
UTF8_IMPLAUSIBLE = 0.3  # valid UTF-8 scoring this or less is weighed against the legacy readings, however long
UTF8_HEAD_START = 0.3  # what being valid UTF-8 is worth when it is weighed
LEGACY: tuple[str, ...] = ("cp932", "big5")  # the sheets' default candidates after UTF-8
_FAMILY = {"big5": ("big5", "cp950"), "cp932": ("cp932",), "euc_jp": ("euc_jp",)}
_SAMPLE = 200_000  # characters scored at most (the strict decode always covers the whole file)
_BOM = b"\xef\xbb\xbf"
_CHUNK = 1 << 20  # bytes read at a time by :func:`file_codec` (a read size, not a limit: the file is read to its end)


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
    """Whether the half-width katakana at ``i`` belongs to a run that can start a word. What stands next to the run
    is not judged: real names and drug masters glue kana to ASCII (``ｶﾙﾃNo``, ``ｱﾑﾛｼﾞﾋﾟﾝOD錠5mg``)."""
    j = i
    while j > 0 and ord(text[j - 1]) in _HW_KANA:
        j -= 1
    return text[j] not in _HW_NOT_FIRST


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
            return 1.0 if _hw_run_ok(text, i) else 0.05
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
    if codec == "gb18030":
        if len(b) == 4:
            return 0.05  # the four-byte planes
        if len(b) == 1:
            return 0.0
        hi, lo = b[0], b[1]
        if lo < 0xA1:
            return 0.15  # GBK's extension (trail bytes 40-A0)
        if 0xB0 <= hi <= 0xD7:
            return 1.0  # GB2312 level 1 hanzi
        if 0xA1 <= hi <= 0xA3:
            return 0.8
        if 0xD8 <= hi <= 0xF7:
            return 0.4  # level 2
        if hi in (0xA4, 0xA5):
            return 0.1  # GB2312's kana rows (EUC-JP kana have the same bytes)
        return 0.3  # Greek, Cyrillic, box drawing rows; GBK user areas
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


def _mixed_line(data: bytes, candidates: Sequence[str]) -> int | None:
    """The first line written in another character set than the lines before it, or None: UTF-8 against not, and,
    among the candidates, a line one of them reads clearly (:func:`_clear`) that the first such line's codec does
    not (a Big5 line inside a Shift_JIS file)."""
    first_utf8: bool | None = None
    first_codec: str | None = None
    for n, line in enumerate(data.split(b"\n"), start=1):
        if line.isascii():
            continue
        try:
            line.decode("utf-8")
            utf8 = True
        except UnicodeDecodeError:
            utf8 = False
        if first_utf8 is None:
            first_utf8 = utf8
        elif utf8 != first_utf8:
            return n
        if utf8:
            continue
        clear = _clear(line, candidates)
        if clear is None:
            continue
        if first_codec is None:
            first_codec = clear
        elif _family(clear) != _family(first_codec):
            return n
    return None


def _family(codec: str) -> str:
    return next((k for k, v in _FAMILY.items() if codec in v), codec)


def _scores(data: bytes, codecs: Sequence[str]) -> list[tuple[float, str]]:
    out = []
    for c in codecs:
        got = _strict(data, c)
        if got is not None:
            out.append((score(got[1], got[0]), got[1]))
    return sorted(out, reverse=True)


def _confidence(best: float, rival: float) -> float:
    return best * (1 - (rival / best) ** 4) if best > rival else 0.0


def _clear(line: bytes, candidates: Sequence[str]) -> str | None:
    """The candidate that reads one line clearly better than every other character set, or None."""
    allowed = {m for c in candidates for m in _FAMILY.get(c, (c,))}
    scored = _scores(line, [*candidates, *(r for r in RIVALS if r not in candidates)])
    if not scored or scored[0][1] not in allowed:
        return None
    rival = max((s for s, c in scored[1:] if c in allowed), default=0.0)
    return scored[0][1] if _confidence(scored[0][0], rival) >= THRESHOLD else None


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
    allowed = {m for c in candidates for m in _FAMILY.get(c, (c,))} | {"utf-8"}
    rivals = [r for r in RIVALS if r not in candidates]
    scored = _scores(data, [*candidates, *rivals])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        mixed = _mixed_line(data, candidates)
        if mixed is not None:
            raise EncodingRefused("the file mixes two character sets", mixed) from None
    else:
        utf8 = score("utf-8", text)
        usual = sum(1 for ch in text[:_SAMPLE] if not ch.isascii() and _weight_utf8(ch) >= 0.9)
        if usual >= UTF8_SURE or not scored or text.isascii():
            return "utf-8", 1.0
        # a few non-ASCII characters only: valid UTF-8 by chance (Big5 職 is C2 BE, also UTF-8 ¾)? Weighed against
        # the legacy readings, with a head start for being valid UTF-8
        scored = sorted([*scored, (min(1.0, utf8 + UTF8_HEAD_START), "utf-8")], reverse=True)
    if not any(c in allowed for _, c in scored):
        names = ", ".join(("UTF-8", *candidates))
        raise EncodingRefused(f"the file is not text in any of {names}", _first_bad_line(data, candidates))
    best, codec = next((s, c) for s, c in scored if c in allowed)
    # another candidate (or UTF-8) must be clearly behind; a rival nobody asked for must not read the file better
    rival = max((s for s, c in scored if c != codec and c in allowed), default=0.0)
    outsider = max((s for s, c in scored if c not in allowed), default=0.0)
    confidence = _confidence(best, rival) if outsider <= best else 0.0
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


def file_codec(path: Path, candidates: Sequence[str] = LEGACY) -> str:
    """The codec :func:`decode` gives the file at ``path``, with the same refusals (T-692, D-473). A file that is UTF-8
    throughout and that :func:`detect` reads as UTF-8 without weighing (a BOM, all ASCII, or enough usual non-ASCII
    characters in the first :data:`_SAMPLE`) is read in chunks and never held; any other file is decided over all
    its bytes, exactly as :func:`decode` does."""
    fast = _utf8_codec(path)
    if fast is not None:
        return fast
    return decode(path.read_bytes(), candidates)[1]


def _utf8_codec(path: Path) -> str | None:
    usual = seen = 0
    plain = True
    line, bad = 1, None
    with path.open("rb") as fh:
        head = fh.read(len(_BOM))
        bom = head == _BOM
        dec = codecs.getincrementaldecoder("utf-8")()
        pending = b"" if bom else head
        try:
            while True:
                text = dec.decode(pending)
                if text:
                    if seen < _SAMPLE:
                        part = text[: _SAMPLE - seen]
                        usual += sum(1 for ch in part if not ch.isascii() and _weight_utf8(ch) >= 0.9)
                        seen += len(part)
                    plain = plain and text.isascii()
                    at = text.find("\ufffd")
                    if at >= 0 and bad is None:
                        bad = line + text.count("\n", 0, at)
                    line += text.count("\n")
                pending = fh.read(_CHUNK)
                if not pending:
                    dec.decode(b"", final=True)
                    break
        except UnicodeDecodeError:
            return None
    if not bom and not (plain or usual >= UTF8_SURE):
        return None
    if bad is not None:
        raise EncodingRefused("the file holds replacement characters (U+FFFD)", bad)
    return "utf-8-sig" if bom else "utf-8"


__all__ = ["LEGACY", "THRESHOLD", "EncodingRefused", "decode", "detect", "file_codec", "score"]
