"""The small HL7 v2.5 subset that SS-MIX2 standardized storage needs (D-122): parse, escape, timestamps, encoding.

SS-MIX2 files hold one message each, segments separated by ``\\r``. MSH-18 names the character set: ``~ISO IR87``
(JIS X 0208, stored as ISO-2022-JP) is the standard; ``UNICODE UTF-8`` is accepted because several vendors write it.

What vendor files hold in practice is wider (STD-020, T-615a): half-width katakana (``ESC ( I`` or SO / SI), NEC row
13 and the NEC-selected IBM extension characters (①, ㈱, 髙) inside ``ESC $ B`` as Windows writes them (CP50220),
JIS X 0212 (``ESC $ ( D``) and JIS X 0213 (``ESC $ ( Q``), and Shift_JIS files with or without the right MSH-18.
:func:`decode_bytes` reads each strictly and never replaces a byte it cannot read (no ``errors="replace"``): a file no
codec reads raises :class:`Undecodable` and the reader quarantines it. A JIS X 0208 character always reads as
``iso2022_jp`` reads it (``−`` U+2212, ``〜`` U+301C), from an ISO-2022-JP file or a Shift_JIS one, so the same
result text compares equal whichever way the vendor stored it; ISO-2022-JP holds no ``µ`` (U+00B5) and no ``－``
(U+FF0D), and the Greek ``μ`` and U+2212 of a JIS file read as they always did.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NULL = '""'  # HL7's explicit null
_ESC = (("\\", "\\E\\"), ("|", "\\F\\"), ("^", "\\S\\"), ("~", "\\R\\"), ("&", "\\T\\"))


def escape(text: str) -> str:
    for raw, esc in _ESC:
        text = text.replace(raw, esc)
    return text


_HEX = re.compile(r"\\X([0-9A-Fa-f]{2,})\\")


def _hex(m: re.Match[str]) -> str:
    data = bytes.fromhex(m.group(1)) if len(m.group(1)) % 2 == 0 else b""
    try:
        return data.decode("utf-8") if data else m.group(0)
    except UnicodeDecodeError:
        return m.group(0)  # not text this reader can name: kept as written


def unescape(text: str) -> str:
    """HL7 escapes: the separators (``\\F\\`` ...), a line break ``\\.br\\`` and a hexadecimal ``\\Xhh..\\`` (UTF-8
    bytes; anything else kept as written)."""
    if "\\" in text:
        text = text.replace("\\.br\\", "\n")
        text = _HEX.sub(_hex, text)
    for raw, esc in reversed(_ESC):
        text = text.replace(esc, raw)
    return text


@dataclass
class Segment:
    name: str
    fields: list[str]

    def field(self, n: int) -> str:
        """SEG-n (1-based, as the standard numbers them; MSH-1 is the field separator itself). HL7's explicit null
        ``""`` ("delete this value") reads as empty: never stored as a value (review of PR #1095 item 5)."""
        i = n - 1 if self.name == "MSH" else n
        value = self.fields[i] if 0 <= i < len(self.fields) else ""
        return "" if value == NULL else value

    def comp(self, n: int, c: int = 1) -> str:
        """Component ``c`` of the first repetition of SEG-n, unescaped."""
        return self.rep_comp(self.field(n).split("~")[0], c)

    @staticmethod
    def rep_comp(rep: str, c: int) -> str:
        """Component ``c`` of one repetition, unescaped."""
        parts = rep.split("^")
        part = parts[c - 1] if 0 < c <= len(parts) else ""
        return "" if part == NULL else unescape(part)

    def reps(self, n: int) -> list[str]:
        """Every repetition of SEG-n (STD-023: PID-3 and PID-5 may carry several)."""
        return [r for r in self.field(n).split("~") if r]

    def pick(self, n: int, c: int, wanted: tuple[str, ...]) -> str:
        """The first repetition of SEG-n whose component ``c`` is one of ``wanted`` (in that order of preference),
        else the first repetition."""
        reps = self.reps(n)
        for w in wanted:
            hit = next((r for r in reps if self.rep_comp(r, c).strip().upper() == w), None)
            if hit is not None:
                return hit
        return reps[0] if reps else ""


@dataclass
class Message:
    segments: list[Segment]

    def first(self, name: str) -> Segment | None:
        return next((s for s in self.segments if s.name == name), None)

    def all(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]


class Undecodable(ValueError):
    """A message no codec reads strictly; the reader quarantines the file (STD-020)."""


# cp932 reads a few JIS X 0208 cells as other code points than the JIS mapping does; give the JIS ones
_CP932_TO_JIS = str.maketrans(
    {"\uff0d": "\u2212", "\uff5e": "\u301c", "\u2225": "\u2016", "\uffe0": "\u00a2", "\uffe1": "\u00a3",
     "\uffe2": "\u00ac"}
)  # fmt: skip
_ESC_BYTE = b"\x1b"
_CP932_STRAYS = frozenset("\x80\uf8f0\uf8f1\uf8f2\uf8f3")  # what Python's cp932 makes of 0x80, 0xA0, 0xFD-0xFF
# escape sequence -> the character set it selects
_SETS = {
    b"\x1b(B": "ascii", b"\x1b(J": "ascii", b"\x1b(H": "ascii", b"\x1b(I": "kana", b"\x1b$@": "jis0208",
    b"\x1b$B": "jis0208", b"\x1b&@\x1b$B": "jis0208", b"\x1b$(B": "jis0208", b"\x1b$(D": "jis0212",
    b"\x1b$(O": "jis0213", b"\x1b$(Q": "jis0213", b"\x1b$(P": "jis0213p2",
}  # fmt: skip
_WIDE = {"jis0208", "jis0212", "jis0213", "jis0213p2"}


@lru_cache(maxsize=16384)
def _cell(charset: str, pair: bytes) -> str:
    """One two-byte cell of an ISO-2022-JP family set, read strictly. JIS X 0208 cells read as ``iso2022_jp`` reads
    them; a cell it leaves undefined (NEC row 13, the NEC-selected IBM extension in rows 89-92) is read the way
    Windows writes it, through Shift_JIS (cp932). Raises :class:`UnicodeDecodeError`."""
    if charset == "jis0208":
        try:
            return (b"\x1b$B" + pair + b"\x1b(B").decode("iso2022_jp")
        except UnicodeDecodeError:
            j1, j2 = pair
            s1 = (j1 + 1) // 2 + 0x70
            s1 += 0x40 if s1 >= 0xA0 else 0
            s2 = j2 + (0x1F + (j2 >= 0x60) if j1 % 2 else 0x7E)
            return bytes((s1, s2)).decode("cp932").translate(_CP932_TO_JIS)
    esc, codec = {"jis0212": (b"\x1b$(D", "iso2022_jp_2"), "jis0213": (b"\x1b$(Q", "iso2022_jp_2004"),
                  "jis0213p2": (b"\x1b$(P", "iso2022_jp_2004")}[charset]  # fmt: skip
    return (esc + pair + b"\x1b(B").decode(codec)


def _iso2022(data: bytes) -> str:
    """ISO-2022-JP and the extensions vendors write (``iso2022_jp_ext``, ``iso2022_jp_2004``, CP50220), strictly."""
    out: list[str] = []
    charset, i, n, shifted = "ascii", 0, len(data), False
    while i < n:
        b = data[i]
        if b == 0x1B:
            for esc, cs in _SETS.items():
                if data.startswith(esc, i):
                    charset, i = cs, i + len(esc)
                    break
            else:
                raise UnicodeDecodeError("iso2022_jp", data, i, i + 1, "unknown escape sequence")
            continue
        if b in (0x0E, 0x0F):  # SO / SI: half-width katakana in JIS7
            shifted, i = b == 0x0E, i + 1
            continue
        if b > 0x7F:
            raise UnicodeDecodeError("iso2022_jp", data, i, i + 1, "8-bit byte in a 7-bit message")
        if b in (0x0D, 0x0A):  # a segment ends in ASCII (the standard resets the set at each line)
            if shifted or charset != "ascii":
                # a set left open to the segment's end has read its separators as characters: which bytes were
                # data cannot be known, so the message is set aside (second review of PR #1095 item 1)
                raise UnicodeDecodeError("iso2022_jp", data, i, i + 1, "an escape sequence left open at a segment end")
            out.append(chr(b))
            charset, shifted, i = "ascii", False, i + 1
            continue
        if shifted or charset == "kana":
            if not 0x21 <= b <= 0x5F:
                raise UnicodeDecodeError("iso2022_jp", data, i, i + 1, "not a half-width katakana")
            out.append(chr(0xFF61 + b - 0x21))
            i += 1
        elif charset in _WIDE:
            if i + 1 >= n or not (0x21 <= b <= 0x7E and 0x21 <= data[i + 1] <= 0x7E):
                raise UnicodeDecodeError("iso2022_jp", data, i, i + 2, "broken two-byte character")
            out.append(_cell(charset, data[i : i + 2]))
            i += 2
        else:
            out.append(chr(b))
            i += 1
    if shifted or charset != "ascii":
        raise UnicodeDecodeError("iso2022_jp", data, n - 1, n, "an escape sequence left open at a segment end")
    return "".join(out)


def charset_of(data: bytes) -> str:
    """MSH-18 as written (the MSH line is ASCII in every encoding SS-MIX2 files come in)."""
    head = data.split(b"\r", 1)[0].split(b"\n", 1)[0].decode("ascii", "replace")
    fields = head.split("|")
    return fields[17] if len(fields) > 17 else ""


#: HL7 table 0211 (alternate character sets), the names SS-MIX2 files carry in MSH-18, and what vendors also write
_CHARSETS = frozenset({
    "ASCII", "ISO IR6", "ISO IR13", "ISO IR14", "ISO IR87", "ISO IR159", "8859/1", "UNICODE", "UNICODE UTF-8",
    "UNICODE UTF-16", "UNICODE UTF-32", "UTF-8", "SHIFT_JIS", "SJIS", "MS932", "CP932", "EUC-JP",
})  # fmt: skip

#: the site's declaration of the encoding of 8-bit files that MSH-18 does not name (second review of PR #1095 item 1)
ENCODING_ENV = "TB_SSMIX2_ENCODING"
_EUC = ("EUC-JP", "EUC_JP", "EUCJP")
_SJIS = ("SHIFT_JIS", "SHIFT-JIS", "SJIS", "MS932", "CP932", "WINDOWS-31J")
_UTF8 = ("UNICODE UTF-8", "UTF-8", "UTF8", "UNICODE")
#: an 8-bit encoding's names (MSH-18 or the site's setting) -> the codec read strictly
_DECLARED = {**dict.fromkeys(_EUC, "euc_jp"), **dict.fromkeys(_SJIS, "cp932"), **dict.fromkeys(_UTF8, "utf-8")}
#: the bytes that carry a message's structure
_STRUCTURE = "|^~&\\\r\n"
#: control characters a decoded message may not hold: C0 but its segment ends, and C1 (third review item 2)
_C0 = re.compile(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]")  # C1 too (U+0085), fourth review item d


def site_encoding(environ: dict[str, str] | None = None) -> str:
    """The codec of ``TB_SSMIX2_ENCODING`` (``euc_jp``, ``cp932``, ``utf-8``), empty when unset. An unknown value is an
    error, raised where the reader starts (third review of PR #1095 item 2), never ignored."""
    value = (environ if environ is not None else os.environ).get(ENCODING_ENV, "").strip().upper()
    if value and value not in _DECLARED:
        raise ValueError(f"{ENCODING_ENV}={value!r}: one of EUC-JP, SHIFT_JIS, UTF-8")
    return _DECLARED.get(value, "")


def _msh18(data: bytes) -> str:
    """MSH-18 for a refusal's sentence (D-682): written out only when every part of it is a character set's name.
    A damaged message has anything in that place (a field that slid, a name); the sentence then says so only."""
    named = charset_of(data)
    if all(part.strip().upper() in _CHARSETS for part in named.split("~") if part.strip()):
        return f"MSH-18 {named!r}"
    return "MSH-18 names no character set of HL7 table 0211"


def _declared(data: bytes) -> tuple[str, str]:
    """``(codec, who said it)`` of the 8-bit encoding MSH-18 names, else the site's setting, else ``("", "")``. MSH-18
    naming two different 8-bit encodings is refused."""
    named = {_DECLARED[p] for p in (x.strip().upper() for x in charset_of(data).split("~")) if p in _DECLARED}
    if len(named) > 1:
        raise Undecodable(f"MSH-18 names two encodings ({_msh18(data)})")
    if named:
        return named.pop(), _msh18(data)
    site = site_encoding()
    return (site, ENCODING_ENV) if site else ("", "")


def _checked(data: bytes, text: str, codec: str) -> tuple[str, str]:
    """The check every reading passes, declared or not (third review of PR #1095 item 2): no control character but
    the segment ends (an ESC or SO left in a name is bytes of another encoding)."""
    if _C0.search(text):
        raise Undecodable(f"a control character in the text read as {codec} ({_msh18(data)})")
    return text, codec


def decode_bytes(data: bytes) -> tuple[str, str]:
    """``(text, codec)`` of one message, read strictly (STD-020), never with a replacement character and never
    falling back to another encoding once one is declared (third review of PR #1095 items 1 and 2):

    * Escape sequences and no 8-bit byte: the ISO-2022-JP family (``iso2022_jp``, else the extended reading of
      :func:`_iso2022`); a set left open at a segment's end is refused.
    * 8-bit bytes and an encoding declared (MSH-18 first, else the site's ``TB_SSMIX2_ENCODING``): that encoding,
      read strictly; Shift_JIS is then checked as below.
    * 8-bit bytes and nothing declared: UTF-8 when it is valid UTF-8 holding a character above U+07FF (as Japanese
      text does), or valid UTF-8 that Shift_JIS cannot read; else Shift_JIS (cp932) when it is certain; anything
      both could be is refused.
    * Shift_JIS, declared or not, is refused when it loses a separator after a lead byte EUC-JP also writes, or
      when the same bytes are also valid EUC-JP or valid UTF-8 (an encoding mislabelled).
    * Every reading: no control character but the segment ends. Plain ASCII as ASCII.

    Raises :class:`Undecodable` when nothing reads it, or not for certain."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    high = any(b > 0x7F for b in data)
    if (_ESC_BYTE in data or b"\x0e" in data) and not high:
        # read by :func:`_iso2022`, which refuses a set left open at a segment end and reads SO / SI half-width
        # katakana; reported as plain ``iso2022_jp`` when Python's codec reads it the same
        try:
            text = _iso2022(data)
        except (UnicodeDecodeError, KeyError) as exc:
            # D-682: a codec's reason is one of its fixed phrases; a failed lookup's text is the bytes looked up
            reason = exc.reason if isinstance(exc, UnicodeDecodeError) else "a character outside the code tables"
            raise Undecodable(f"ISO-2022-JP: {reason}") from exc
        try:
            same = data.decode("iso2022_jp") == text
        except UnicodeDecodeError:
            same = False
        return _checked(data, text, "iso2022_jp" if same else "iso2022_jp_ext")
    if not high:
        return _checked(data, data.decode("ascii"), "ascii")
    codec, who = _declared(data)
    if codec:
        try:
            text = data.decode(codec)
        except UnicodeDecodeError as exc:
            raise Undecodable(f"not {codec} although {who} says so") from exc
        if codec == "cp932":
            _shift_jis_certain(data, text, f"although {who} says Shift_JIS", declared=True)
            text = text.translate(_CP932_TO_JIS)
        return _checked(data, text, codec)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        if max(map(ord, text)) > 0x7FF or not _reads(data, "cp932"):
            return _checked(data, text, "utf-8")
        raise Undecodable(f"UTF-8 or Shift_JIS, not named ({_msh18(data)}; the site may set {ENCODING_ENV})")
    try:
        text = data.decode("cp932")
    except UnicodeDecodeError as exc:
        raise Undecodable(f"neither UTF-8 nor Shift_JIS ({_msh18(data)})") from exc
    _shift_jis_certain(data, text, "not named", declared=False)
    return _checked(data, text.translate(_CP932_TO_JIS), "cp932")


def _reads(data: bytes, codec: str) -> bool:
    try:
        data.decode(codec)
    except UnicodeDecodeError:
        return False
    return True


def _shift_jis_certain(data: bytes, text: str, said: str, declared: bool) -> None:
    """Refuse a Shift_JIS reading in doubt (third review of PR #1095 item 2), declared or not:

    * a byte Shift_JIS does not use;
    * a separator lost after a lead byte EUC-JP also writes (EUC-JP read wrongly: every later field shifts); a
      separator after a lead byte EUC-JP never writes (− 0x817C, ポ 0x837C) is Shift_JIS's own character;
    * bytes that are valid UTF-8 holding a character above U+07FF (UTF-8 Japanese mislabelled);
    * bytes that are valid EUC-JP: undeclared, always; declared, when they also look like EUC-JP, with no byte in
      0x80-0x9F (where Shift_JIS writes its hiragana, punctuation and first-level kanji) and a lead byte from 0xE0.
      A declared file of half-width katakana alone, often valid EUC-JP too, is read as it says."""
    if any(c in _CP932_STRAYS for c in text):  # Python's cp932 reads these lone bytes; Shift_JIS has no such byte
        raise Undecodable(f"not Shift_JIS: a byte Shift_JIS does not use ({_msh18(data)})")
    if _swallowed(data):
        raise Undecodable(f"read as Shift_JIS, a separator is lost into a character ({_msh18(data)})")
    try:
        utf8 = data.decode("utf-8")
    except UnicodeDecodeError:
        utf8 = ""
    if utf8 and max(map(ord, utf8)) > 0x7FF:
        raise Undecodable(f"Shift_JIS or UTF-8, {said} ({_msh18(data)}; the site may set {ENCODING_ENV})")
    euc_like = not any(0x80 <= b <= 0x9F for b in data) and any(b >= 0xE0 for b in data)
    if _reads(data, "euc_jp") and (not declared or euc_like):
        raise Undecodable(f"Shift_JIS or EUC-JP, {said} ({_msh18(data)}; the site may set {ENCODING_ENV})")


def _swallowed(data: bytes) -> bool:
    """Whether a Shift_JIS reading of ``data`` takes a separator or segment end as the second byte of a character
    whose first byte EUC-JP also writes (0x8E, 0x8F, 0xA1 and above)."""
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC:
            if i + 1 < n and chr(data[i + 1]) in _STRUCTURE and (b >= 0xA1 or b in (0x8E, 0x8F)):
                return True
            i += 2
        else:
            i += 1
    return False


def decode(data: bytes) -> str:
    """The text of one message (:func:`decode_bytes`)."""
    return decode_bytes(data)[0]


_STANDARD = "|^~\\&"  # field, component, repetition, escape, subcomponent: what the parser reads


def _standard_separators(text: str) -> str:
    """A message whose MSH-1 / MSH-2 name other separators, written with the standard ones (review of PR #1095): a
    declared separator becomes its standard character, and a standard character that is data in such a message
    becomes its escape, so nothing else in the reader changes."""
    if not text.startswith("MSH") or len(text) < 8:
        return text
    declared = text[3] + text[4:8]
    if declared == _STANDARD or len(set(declared)) != 5:
        return text
    to_std = dict(zip(declared, _STANDARD, strict=True))
    esc = {"|": "\\F\\", "^": "\\S\\", "~": "\\R\\", "\\": "\\E\\", "&": "\\T\\"}
    head, body = "MSH" + _STANDARD, text[8:]
    return head + "".join(to_std.get(c) or esc.get(c, c) for c in body)


def parse(text: str) -> Message:
    text = _standard_separators(text)
    segs = []
    for line in text.replace("\n", "\r").split("\r"):
        if line.strip():
            parts = line.split("|")
            segs.append(Segment(parts[0], parts))
    if not segs or segs[0].name != "MSH":
        raise ValueError("not an HL7 v2 message (no MSH segment)")
    return Message(segs)


#: dates :func:`ts` refused or could not place, by reason (review of PR #1095 item 10); the reader adds them to its
#: statistics. Never the value itself.
REFUSED: Counter[str] = Counter()


_TS = re.compile(r"^(\d{8,14})(?:\.\d*)?([+-]\d{4})?$")
#: a timestamp with an offset anywhere in a message, between separators (third review of PR #1095 item 10)
_OFFSET_IN = re.compile(r"(?:^|(?<=[|^&~]))\d{8,14}(?:\.\d*)?[+-](\d{2})(\d{2})(?=$|[|^&~\r\n])", re.MULTILINE)


def offset_problem(text: str) -> str:
    """Why a message's timestamps cannot be placed, empty when they can: an offset beyond ±14:00 or with minutes
    beyond 59 (``+2400``, ``+9900``). The reader quarantines such a message, never the whole table."""
    for m in _OFFSET_IN.finditer(text):
        if int(m.group(1)) > 14 or int(m.group(2)) > 59:
            return "a time-zone offset out of range"
    return ""


def valid_stamp(stamp: str) -> bool:
    """A file name's 発生日時: 17 digits, ``YYYYMMDDHHMMSSfff``, a real date and time (third review item 10)."""
    if len(stamp) != 17 or not stamp.isdigit():
        return False
    try:
        datetime(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]), int(stamp[8:10]), int(stamp[10:12]),
                 int(stamp[12:14]))  # fmt: skip
    except ValueError:
        return False
    return True


def _site_zone() -> ZoneInfo | None:
    try:
        return ZoneInfo(os.environ.get("TB_TZ", "").strip()) if os.environ.get("TB_TZ", "").strip() else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def ts(value: str) -> str | None:
    """HL7 TS (``YYYYMMDD[HHMM[SS]]``, optional zone) -> ``YYYY-MM-DD[ HH:MM:SS]`` as the canonical tables use, in the
    site's time. A date that is not a real calendar date (``99999999``, ``20261301``) or not written in digits (a
    Japanese era) is None and counted in :data:`REFUSED` (an impossible date is still passed on, for the mapping to
    reject the row, STD-025). A time with an offset is converted to the site's zone (``TB_TZ``); with no zone set,
    the time is not kept, only the day (second review of PR #1095 item 3: never a wrong time). Counted either way."""
    raw = value.strip()
    v = raw.split("+", maxsplit=1)[0].split("-", maxsplit=1)[0].split(".", maxsplit=1)[0].strip()
    if not v:
        return None
    if len(v) < 8 or not v[:8].isdigit():
        REFUSED["not a date in digits (an era, a word)"] += 1
        return None
    valid = True
    try:
        date(int(v[:4]), int(v[4:6]), int(v[6:8]))
    except ValueError:
        # counted, and passed on as written: the mapping then refuses the row and counts it in the ingest's
        # completeness (STD-025), so the record is seen as rejected, never loaded undated
        REFUSED["not a calendar date (the row is rejected by the mapping)"] += 1
        valid = False
    day = f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    if len(v) > 8 and (len(v) not in (10, 12, 14) or not v[8:].isdigit()):
        # a time part of another length, or not digits: never half read (third review, minor)
        REFUSED["a time part that is not read: the day kept"] += 1
        return day
    if len(v) < 10:
        return day
    minute = v[10:12] if len(v) >= 12 else "00"  # STD-023: ``YYYYMMDDHH`` keeps its hour
    sec = v[12:14] if len(v) >= 14 else "00"
    if int(v[8:10]) > 23 or int(minute) > 59 or int(sec) > 59:  # a leap second too (third review, minor)
        REFUSED["not a time of day (the row is rejected by the mapping)"] += 1  # passed on, as a bad date is
        return f"{day} {v[8:10]}:{minute}:{sec}"
    m = _TS.match(raw)
    if "+" in raw or "-" in raw[8:]:
        zone = _site_zone()
        hours, minutes = (int(m.group(2)[1:3]), int(m.group(2)[3:5])) if m and m.group(2) else (99, 99)
        if not (m and m.group(2) and valid and zone) or hours > 14 or minutes > 59:
            REFUSED["an offset the site's zone cannot place: the time not kept"] += 1
            return day
        sign = 1 if m.group(2)[0] == "+" else -1
        off = timezone(sign * timedelta(hours=int(m.group(2)[1:3]), minutes=int(m.group(2)[3:5])))
        at = datetime(int(v[:4]), int(v[4:6]), int(v[6:8]), int(v[8:10]), int(minute), int(sec), tzinfo=off)
        local = at.astimezone(zone)
        if local.utcoffset() != off.utcoffset(None):
            REFUSED["an offset other than the site's: converted to the site's time"] += 1
        return local.strftime("%Y-%m-%d %H:%M:%S")
    return f"{day} {v[8:10]}:{minute}:{sec}"


def hl7_ts(value: str | None) -> str:
    """Inverse of :func:`ts`."""
    if not value:
        return ""
    v = value.replace("-", "").replace(":", "").replace(" ", "").replace("T", "")
    return v[:14]
