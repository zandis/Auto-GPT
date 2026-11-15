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
import itertools
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path

THRESHOLD = 0.6
# character sets that are never chosen unless asked for, but are weighed: when one reads a file as well as the
# chosen candidate, the file is refused rather than read wrong (GB18030 against Big5, EUC-JP against CP932)
RIVALS: tuple[str, ...] = ("cp932", "big5", "euc_jp", "gb18030", "euc_kr", "latin_1")
UTF8_SURE = 3  # valid UTF-8 with at least this many usual non-ASCII characters is read without weighing
UTF8_IMPLAUSIBLE = 0.3  # valid UTF-8 scoring this or less is weighed against the legacy readings, however long
UTF8_HEAD_START = 0.3  # what being valid UTF-8 is worth when it is weighed
LEGACY: tuple[str, ...] = ("cp932", "big5")  # the sheets' default candidates after UTF-8
_FAMILY = {"big5": ("big5", "cp950", "big5hkscs"), "cp932": ("cp932",), "euc_jp": ("euc_jp",)}
_LANGUAGE = {"cp932": "ja", "euc_jp": "ja", "big5": "zh-Hant"}  # the language a candidate family is the text of
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


# D-599: the Latin-1 symbols that count as usual wherever they stand (a urine protein column of ±). The others are,
# as two bytes, frequent hanzi (¾ 職, ² 簡, ½ 翻, § 禮): a column of one of those is not certain UTF-8
_LATIN1_SURE = set("µ°±×")


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
        return 0.9 if ch in _LATIN1_SURE else 0.6
    if 0x370 <= o <= 0x3FF or 0x1E00 <= o <= 0x1EFF or 0xAC00 <= o <= 0xD7AF:
        return 0.6
    if 0x400 <= o <= 0x4FF:
        return 0.4
    if o < 0x800:  # Latin Extended-A/B, IPA, modifiers, combining marks, Armenian, Hebrew, Arabic, Syriac, ...
        return 0.2
    return 0.5


# D-599: what only western text looks like, each with an ASCII letter or digit in a fixed place beside it. No
# Japanese or Chinese text has a half-width kana pair or one hanzi standing so: inside a word between letters, as
# the degree of a temperature, the micro of a unit, the square of a metre, between two numbers, hyphened to a word
_WESTERN = re.compile(
    "|".join(
        (
            r"(?<=[A-Za-z])[\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff]{1,2}(?=[a-z])",  # Sjögren, Ménière, naïve
            r"(?<=[0-9])\u00b0(?=[CF](?![A-Za-z]))|(?<=[0-9] )\u00b0(?=[CF](?![A-Za-z]))",  # 38°C, 37.5 °C
            r"(?<![A-Za-z])[\u00b5\u03bc](?=(?:mol|kat|IU|Eq|[glLmMsU])(?![a-z]))",  # µg, µmol/L, μL
            r"(?<=m)[\u00b2\u00b3](?![A-Za-z0-9])",  # m², cm³
            r"(?<=[0-9])\u00b1(?=[0-9])|(?<=[0-9] )\u00b1(?= [0-9])",  # 5±2, 5 ± 2
            r"(?<=[A-Za-z]{2}-)[\u03b1-\u03c9](?![A-Za-z])|(?<![A-Za-z])[\u03b1-\u03c9](?=-[A-Za-z]{2})",  # TNF-α
            # D-805: a curly apostrophe or quote at a Latin letter (Crohn’s, “better”). Its bytes are the garble 窶冱 /
            # 鈥檚 in Shift_JIS and GB18030 and no character at all in Big5, EUC-JP or EUC-KR
            r"(?<=[A-Za-z])[\u2018\u2019](?=[A-Za-z])|\u201c(?=[A-Za-z])|(?<=[A-Za-z.!?])\u201d",
        )
    )
)


def _western_only(text: str) -> bool:
    """Whether every non-ASCII character of ``text`` stands in one of the :data:`_WESTERN` places."""
    covered: set[int] = set()
    for m in _WESTERN.finditer(text):
        covered.update(range(m.start(), m.end()))
    return all(i in covered for i, ch in enumerate(text) if not ch.isascii())


# a run of accented letters with nothing ASCII beside it (``ÄÖÜ``) is the same bytes as half-width kana (``ﾄﾖﾜ``).
# Weighed so that such a run alone ties and is refused, and a kana name with its voicing marks and spaces (which
# are symbols in Windows-1252) is still read: at 0.9 half of a fuzz of kana-name sheets was refused, at 0.75 five
# of 3,600 western lines were read as kana
_WESTERN_ALONE = 0.8


# a symbol of single-byte western text where only that text has it (the bytes as ISO 8859-1): the degree of a
# temperature, a plus-minus between numbers, a micro before a unit, a square after m, a fraction before a word
_WESTERN_SYMBOL = re.compile(
    r"(?<=[0-9])\xb0(?=[CF])|(?<=[0-9] )\xb0(?=[CF])|(?<=[0-9])\xb1(?=[0-9])|(?<=[0-9] )\xb1(?= [0-9])"
    r"|(?<![A-Za-z])\xb5(?=[glLmMsU])|(?<=m)[\xb2\xb3](?![A-Za-z0-9])|(?<![A-Za-z\x80-\xff])[\xbc-\xbe](?= ?[A-Za-z])"
)


def _western_marks(text: str) -> set[int]:
    return {i for m in _WESTERN_SYMBOL.finditer(text) for i in range(m.start(), m.end())}


_WESTERN_WORD = 12  # characters looked at on each side of a high byte for its word (a long western word)
_WESTERN_RUN = 3  # high bytes in a row inside a western word at most (ŻÓŁTACZKA); kana and hanzi come in longer runs


def _weight_western(text: str, i: int, marks: set[int] | None = None) -> float:
    """How usual the high byte at ``i`` is in single-byte western text, read as ISO 8859-1 whatever the set really
    is (Windows-1252, Mac Roman, CP437, CP1250): never a candidate, weighed as a rival, because ``ATENÇÃO`` is the
    same bytes as ``ATENﾇﾃO`` and ``sévère`` in Mac Roman reads as ``s思俊e``. A high byte is an accented letter
    when its word (ASCII letters and high bytes) holds at least two ASCII letters, no more high bytes than ASCII
    letters plus one, and no run of more than :data:`_WESTERN_RUN` of them; a symbol in its place
    (:data:`_WESTERN_SYMBOL`) is one. A run of accented letters with nothing ASCII beside it weighs
    :data:`_WESTERN_ALONE`; anything else little, so Japanese and Chinese text, where high bytes come in runs, is
    not taken for western."""
    if marks is not None and i in marks:
        return 1.0

    def part(c: str) -> bool:
        return not c.isascii() or c.isalpha()

    lo = hi = i
    while lo > 0 and i - lo < _WESTERN_WORD and part(text[lo - 1]):
        lo -= 1
    while hi + 1 < len(text) and hi - i < _WESTERN_WORD and part(text[hi + 1]):
        hi += 1
    word = text[lo : hi + 1]
    ascii_letters = sum(1 for c in word if c.isascii())
    high = len(word) - ascii_letters
    run = longest = 0
    for c in word:
        run = 0 if c.isascii() else run + 1
        longest = max(longest, run)
    if ascii_letters >= 2 and high <= ascii_letters + 1 and longest <= _WESTERN_RUN:
        return 1.0
    if not ascii_letters and all(0xC0 <= ord(c) <= 0xFF for c in word):
        return _WESTERN_ALONE
    return 0.6 if 0xA0 <= ord(text[i]) <= 0xBF else 0.3


def _hw_runs_ok(text: str) -> dict[int, bool]:
    """:func:`_hw_run_ok` for every half-width katakana of ``text``, in one pass: each run's start is looked at
    once. Walking back from every character took time quadratic in the length of a run (8,000 in a row: 17 s)."""
    out: dict[int, bool] = {}
    ok = False
    inside = False
    for i, ch in enumerate(text):
        if ord(ch) in _HW_KANA:
            if not inside:
                ok = ch not in _HW_NOT_FIRST
                inside = True
            out[i] = ok
        else:
            inside = False
    return out


def _weight(codec: str, ch: str, text: str, i: int, hw_ok: dict[int, bool] | None = None) -> float:
    """How usual ``ch`` (a non-ASCII character decoded by ``codec``) is in that character set, 0..1. ``hw_ok`` is
    :func:`_hw_runs_ok` of ``text`` when the caller scores a whole text."""
    cat = unicodedata.category(ch)
    if cat in ("Co", "Cc", "Cn", "Cs") or ch == "\ufffd":
        return 0.0
    if codec in ("utf-8", "utf-8-sig"):
        return _weight_utf8(ch)
    if codec == "latin_1":
        return _weight_western(text, i)
    if codec == "euc_kr":  # a rival only: Hangul syllables are Korean text, the rest of the set is rarely written
        return 1.0 if 0xAC00 <= ord(ch) <= 0xD7A3 else 0.3
    try:
        b = ch.encode(codec)
    except UnicodeEncodeError:
        return 0.0
    if codec == "cp932":
        if len(b) == 1:  # half-width katakana
            return 1.0 if (hw_ok[i] if hw_ok is not None else _hw_run_ok(text, i)) else 0.05
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
    if codec in ("big5", "cp950", "big5hkscs"):
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
    if codec == "latin_1":
        marks = _western_marks(sample)
        w = [_weight_western(sample, i, marks) for i, ch in enumerate(sample) if not ch.isascii()]
        return sum(w) / len(w) if w else 1.0
    hw_ok = _hw_runs_ok(sample) if codec == "cp932" else None
    w = [_weight(codec, ch, sample, i, hw_ok) for i, ch in enumerate(sample) if not ch.isascii()]
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


_UTF16_HEAD = 4096  # bytes looked at for the NUL pattern of UTF-16
_UTF16_NULS = 0.3  # of the bytes on one side of each pair: western UTF-16 text has a NUL beside nearly every one


def _utf16_like(data: bytes) -> bool:
    """UTF-16 without its byte order mark: a NUL byte on the same side of most pairs. A stray NUL in a text (a PDF
    reader leaves them between glyphs) is not that; the readers drop it as before."""
    head = data[:_UTF16_HEAD]
    if len(head) < 4 or 0 not in head:
        return False
    half = len(head) // 2
    return max(head[0::2].count(0), head[1::2].count(0)) >= _UTF16_NULS * half


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
    if _utf16_like(data):
        raise EncodingRefused("the file reads as UTF-16 without a byte order mark (a NUL byte beside every character)")
    allowed = {m for c in candidates for m in _FAMILY.get(c, (c,))} | {"utf-8"}
    rivals = [r for r in RIVALS if r not in candidates]
    scored = _scores(data, [*candidates, *rivals])
    valid_utf8 = False  # the bytes are valid UTF-8 and their reading is weighed against the legacy ones
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        mixed = _mixed_line(data, candidates)
        if mixed is not None:
            raise EncodingRefused("the file mixes two character sets", mixed) from None
    else:
        if "\ufffd" in text:
            # a UTF-8 file damaged before it reached the box: UTF-8, so that :func:`decode` refuses it with the line
            # of the replacement character (as a rival, Windows-1252 reads its three bytes better than UTF-8 does)
            return "utf-8", 1.0
        utf8 = score("utf-8", text)
        usual = sum(1 for ch in text[:_SAMPLE] if not ch.isascii() and _weight_utf8(ch) >= 0.9)
        if usual >= UTF8_SURE or not scored or text.isascii():
            return "utf-8", 1.0
        if _western_only(text[:_SAMPLE]):  # D-599: every non-ASCII character is in a western word or a unit
            return "utf-8", 1.0
        # a few non-ASCII characters only: valid UTF-8 by chance (Big5 職 is C2 BE, also UTF-8 ¾)? Weighed against
        # the legacy readings, with a head start for being valid UTF-8
        scored = sorted([*scored, (min(1.0, utf8 + UTF8_HEAD_START), "utf-8")], reverse=True)
        valid_utf8 = True
    if not any(c in allowed for _, c in scored):
        names = ", ".join(("UTF-8", *candidates))
        raise EncodingRefused(f"the file is not text in any of {names}", _first_bad_line(data, candidates))
    best, codec = next((s, c) for s, c in scored if c in allowed)
    # another candidate (or UTF-8) must be clearly behind; a rival nobody asked for must not read the file better
    rival = max((s for s, c in scored if c != codec and c in allowed), default=0.0)
    outsider = max((s for s, c in scored if c not in allowed), default=0.0)
    if len({_LANGUAGE.get(_family(c), _family(c)) for c in candidates}) == 1:
        # the caller says what the file is (a vendor's master is Shift_JIS; an SS-MIX2 note is Japanese, in
        # Shift_JIS or EUC-JP): a rival must read it better to refuse it
        confidence = _confidence(best, rival) if outsider <= best else 0.0
    else:
        # a file of unknown origin: the reading taken must lead EVERY other reading clearly, a rival's too. Short
        # EUC-JP, GB18030 or Windows-1252 text tied with its Shift_JIS or Big5 reading and was read as that
        confidence = _confidence(best, max(rival, outsider))
    if confidence < THRESHOLD:
        others = ", ".join(f"{c} {s:.2f}" for s, c in scored)
        raise EncodingRefused(f"the character set cannot be told for certain ({others})")
    if valid_utf8 and codec != "utf-8":
        # D-599: bytes that are valid UTF-8 are read as UTF-8 or refused, never as a legacy character set. Kana or a
        # hanzi that happen to be valid UTF-8 and a word of another script are the same bytes (D0 AF is "Я" and
        # "ﾐｯ"): too little to tell, whichever reading weighs more
        raise EncodingRefused("the file is valid UTF-8 and too short to tell from Shift_JIS or Big5")
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


def _cjk(ch: str) -> bool:
    """A CJK ideograph or kana (full or half width): the letters of Japanese and Chinese text."""
    o = ord(ch)
    return 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF66 <= o <= 0xFF9F


UPLOAD_WESTERN_TEXT = 40  # ASCII letters that make an upload a western document, not a cell (two short sentences)


def decode_upload(data: bytes, candidates: Sequence[str] = LEGACY) -> tuple[str, str]:
    """``(text, codec)`` of a text file a person uploads (UX-004): a protocol as text, a data dictionary.

    Such a file is mostly western text and has always been read as UTF-8, so **bytes that are valid UTF-8 are
    UTF-8 when the file is a document**: with a byte order mark, all ASCII, or holding at least
    :data:`UPLOAD_WESTERN_TEXT` ASCII letters. :func:`detect` would refuse such a protocol for one ``§``. A shorter
    file is a cell or a line and is judged as a sheet is (:func:`decode`): a legacy cell whose bytes are valid
    UTF-8 by chance is refused, not read as ``¦``. A file with a UTF-16 byte order mark (Notepad's "Unicode") is
    UTF-16.

    Only bytes that are not UTF-8 are given to :func:`decode`, and its answer is taken only when the text it reads
    is CJK text: at least one run of two CJK characters. A western file in Windows-1252 has no such run; each of its
    accented bytes pairs with the next letter into one stray kanji (``Patient’s`` read as ``Patient痴``), and is
    refused. Raises :class:`EncodingRefused`; nothing is replaced by U+FFFD."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as exc:
            raise EncodingRefused("the file starts as UTF-16 and is not") from exc
    if _utf16_like(data):
        raise EncodingRefused("the file reads as UTF-16 without a byte order mark (a NUL byte beside every character)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    else:
        if data.startswith(codecs.BOM_UTF8):
            return text, "utf-8-sig"
        # a document: enough western text that it is not a legacy cell whose two bytes are valid UTF-8 by chance
        # (Big5 礎 is ``¦``; GB18030 转院 is a Hebrew and an Armenian letter). Shorter text is judged as a sheet is
        if text.isascii() or sum(1 for ch in text[:_SAMPLE] if ch.isascii() and ch.isalpha()) >= UPLOAD_WESTERN_TEXT:
            return text, "utf-8"
        detect(data, candidates)  # D-599: for bytes that are valid UTF-8 the answer is UTF-8 or a refusal
        return text, "utf-8"
    text, codec = decode(data, candidates)
    if not any(_cjk(a) and _cjk(b) for a, b in itertools.pairwise(text)):
        raise EncodingRefused("the file is not UTF-8 and does not read as Japanese or Chinese text")
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
