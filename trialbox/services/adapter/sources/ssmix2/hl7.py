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

from dataclasses import dataclass
from functools import lru_cache

_ESC = (("\\", "\\E\\"), ("|", "\\F\\"), ("^", "\\S\\"), ("~", "\\R\\"), ("&", "\\T\\"))


def escape(text: str) -> str:
    for raw, esc in _ESC:
        text = text.replace(raw, esc)
    return text


def unescape(text: str) -> str:
    for raw, esc in reversed(_ESC):
        text = text.replace(esc, raw)
    return text


@dataclass
class Segment:
    name: str
    fields: list[str]

    def field(self, n: int) -> str:
        """SEG-n (1-based, as the standard numbers them; MSH-1 is the field separator itself)."""
        i = n - 1 if self.name == "MSH" else n
        return self.fields[i] if 0 <= i < len(self.fields) else ""

    def comp(self, n: int, c: int = 1) -> str:
        """Component ``c`` of the first repetition of SEG-n, unescaped."""
        return self.rep_comp(self.field(n).split("~")[0], c)

    @staticmethod
    def rep_comp(rep: str, c: int) -> str:
        """Component ``c`` of one repetition, unescaped."""
        parts = rep.split("^")
        return unescape(parts[c - 1]) if 0 < c <= len(parts) else ""

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


def _msh18(data: bytes) -> str:
    """MSH-18 for a refusal's sentence (D-682): written out only when every part of it is a character set's name.
    A damaged message has anything in that place (a field that slid, a name); the sentence then says so only."""
    named = charset_of(data)
    if all(part.strip().upper() in _CHARSETS for part in named.split("~") if part.strip()):
        return f"MSH-18 {named!r}"
    return "MSH-18 names no character set of HL7 table 0211"


def decode_bytes(data: bytes) -> tuple[str, str]:
    """``(text, codec)`` of one message, read strictly (STD-020). Escape sequences: the ISO-2022-JP family
    (``iso2022_jp``, else the extended reading of :func:`_iso2022`). Bytes above 0x7F: UTF-8 when the bytes are valid
    UTF-8 (a Shift_JIS text almost never is), else Shift_JIS as Windows writes it (cp932), whatever MSH-18 says.
    Plain ASCII as ASCII. Raises :class:`Undecodable` when nothing reads it."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    high = any(b > 0x7F for b in data)
    if _ESC_BYTE in data and not high:
        try:
            return data.decode("iso2022_jp"), "iso2022_jp"
        except UnicodeDecodeError:
            pass
        try:
            return _iso2022(data), "iso2022_jp_ext"
        except (UnicodeDecodeError, KeyError) as exc:
            # D-682: a codec's reason is one of its fixed phrases; a failed lookup's text is the bytes looked up
            reason = exc.reason if isinstance(exc, UnicodeDecodeError) else "a character outside the code tables"
            raise Undecodable(f"ISO-2022-JP: {reason}") from exc
    if not high:
        return data.decode("ascii"), "ascii"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp932")
    except UnicodeDecodeError as exc:
        raise Undecodable(f"neither UTF-8 nor Shift_JIS ({_msh18(data)})") from exc
    if any(c in _CP932_STRAYS for c in text):  # Python's cp932 reads these lone bytes; Shift_JIS has no such byte
        raise Undecodable(f"neither UTF-8 nor Shift_JIS: a byte Shift_JIS does not use ({_msh18(data)})")
    return text.translate(_CP932_TO_JIS), "cp932"


def decode(data: bytes) -> str:
    """The text of one message (:func:`decode_bytes`)."""
    return decode_bytes(data)[0]


def parse(text: str) -> Message:
    segs = []
    for line in text.replace("\n", "\r").split("\r"):
        if line.strip():
            parts = line.split("|")
            segs.append(Segment(parts[0], parts))
    if not segs or segs[0].name != "MSH":
        raise ValueError("not an HL7 v2 message (no MSH segment)")
    return Message(segs)


def ts(value: str) -> str | None:
    """HL7 TS (``YYYYMMDD[HHMM[SS]]``, optional zone) -> ``YYYY-MM-DD[ HH:MM:SS]`` as the canonical tables use."""
    v = value.split("+", maxsplit=1)[0].split("-", maxsplit=1)[0].split(".", maxsplit=1)[0].strip()
    if len(v) < 8 or not v[:8].isdigit():
        return None
    day = f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    if len(v) < 10 or not v[8:10].isdigit():
        return day
    minute = v[10:12] if len(v) >= 12 else "00"  # STD-023: ``YYYYMMDDHH`` keeps its hour
    sec = v[12:14] if len(v) >= 14 else "00"
    return f"{day} {v[8:10]}:{minute}:{sec}"


def hl7_ts(value: str | None) -> str:
    """Inverse of :func:`ts`."""
    if not value:
        return ""
    v = value.replace("-", "").replace(":", "").replace(" ", "").replace("T", "")
    return v[:14]
