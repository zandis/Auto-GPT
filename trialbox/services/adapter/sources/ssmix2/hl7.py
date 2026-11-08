"""The small HL7 v2.5 subset that SS-MIX2 standardized storage needs (D-122): parse, escape, timestamps, encoding.

SS-MIX2 files hold one message each, segments separated by ``\\r``. MSH-18 names the character set: ``~ISO IR87``
(JIS X 0208, stored as ISO-2022-JP) is the standard; ``UNICODE UTF-8`` is accepted because several vendors write it.
"""

from __future__ import annotations

from dataclasses import dataclass

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
        rep = self.field(n).split("~")[0]
        parts = rep.split("^")
        return unescape(parts[c - 1]) if 0 < c <= len(parts) else ""


@dataclass
class Message:
    segments: list[Segment]

    def first(self, name: str) -> Segment | None:
        return next((s for s in self.segments if s.name == name), None)

    def all(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]


def decode(data: bytes) -> str:
    """Decode by MSH-18; ISO-2022-JP is 7-bit, so the MSH line can be read as ASCII first."""
    head = data.split(b"\r", 1)[0].decode("ascii", "replace")
    fields = head.split("|")
    charset = fields[17] if len(fields) > 17 else ""
    if "IR87" in charset or "ISO-2022" in charset.upper():
        return data.decode("iso2022_jp")
    return data.decode("utf-8-sig")


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
    if len(v) < 12:
        return day
    sec = v[12:14] if len(v) >= 14 else "00"
    return f"{day} {v[8:10]}:{v[10:12]}:{sec}"


def hl7_ts(value: str | None) -> str:
    """Inverse of :func:`ts`."""
    if not value:
        return ""
    v = value.replace("-", "").replace(":", "").replace(" ", "").replace("T", "")
    return v[:14]
