"""Card 10G-43 (OT-5): HL7 v2 decode and parse on malformed input (:mod:`adapter.sources.ssmix2.hl7`).

``decode`` returns text or refuses with :class:`hl7.Undecodable`; ``parse`` returns a message or refuses with
``ValueError`` ("no MSH segment"), which is what the SS-MIX2 walker catches and quarantines (STD-020). Then every
accessor the walker uses (``field``, ``comp``, ``reps``, ``pick``, ``ts``) answers on whatever was parsed. A planted
``IndexError`` in ``hl7.parse`` fails these tests (the row's proof).
"""

from __future__ import annotations

from tests.malformed_kit import MAX_INPUT, SETTINGS, returns_or_refuses

from hypothesis import example, given
from hypothesis import strategies as st

from adapter.sources.ssmix2 import hl7

# bytes that steer the decoder into each of its branches: ESC sequences (ISO-2022-JP and its extensions), SO/SI,
# Shift_JIS lead bytes, UTF-8 lead bytes, a BOM, segment ends and the HL7 delimiters
_PIECES = [
    b"MSH|^~\\&|", b"PID|", b"OBX|", b"\r", b"\n", b"|", b"^", b"~", b"\\", b"&", b"\x1b$B", b"\x1b(B", b"\x1b(I",
    b"\x1b$(D", b"\x1b$(Q", b"\x1b$(P", b"\x1b&@\x1b$B", b"\x1b", b"\x0e", b"\x0f", b"\xef\xbb\xbf", b"\x82\xa0",
    b"\x81", b"\xe3\x81\x82", b"\xe3", b"\x80", b"\xa0", b"\xfd", b"\x7f\x7f", b"!!", b"0", b"20261001",
]  # fmt: skip
messy_bytes = st.one_of(
    st.binary(max_size=512),
    st.lists(st.sampled_from(_PIECES) | st.binary(max_size=4), max_size=80).map(b"".join),
).filter(lambda b: len(b) <= MAX_INPUT)

_FIELD = st.text(alphabet=st.sampled_from("|^~\\&EFSTR0123456789+-. \r\nAZaz山田\x00"), max_size=24)
messy_text = st.one_of(
    st.text(max_size=400),
    st.lists(st.sampled_from(["MSH", "PID", "OBX", "ORC", "PRB", ""]) | _FIELD, max_size=40).map("|".join),
)


def _touch(msg: hl7.Message) -> None:
    """What the walker asks of a parsed message: every segment's fields, components, repetitions and times."""
    for seg in msg.segments:
        for n in range(0, len(seg.fields) + 2):
            seg.field(n)
            seg.reps(n)
            for c in range(0, 4):
                seg.comp(n, c)
            seg.pick(n, 1, ("PI", "MR"))
            hl7.ts(seg.field(n))
            hl7.hl7_ts(seg.field(n))
    msg.first("PID")
    msg.all("OBX")


@SETTINGS
@given(messy_bytes)
@example(b"")
@example(b"\x1b$B!")
@example(b"\x1b$B\x2d\x21\x1b(B")
@example(b"MSH|^~\\&|\x1b$(P!!")
@example(b"\xef\xbb\xbf\x80")
def test_decode_returns_text_or_refuses(data: bytes) -> None:
    out = returns_or_refuses(lambda: hl7.decode_bytes(data), (hl7.Undecodable,))
    if out is not None:
        text, codec = out
        assert isinstance(text, str) and codec
        hl7.charset_of(data)


@SETTINGS
@given(messy_text)
@example("")
@example("\r\n")
@example("MSH")
@example("PID|1\rMSH|")
@example("MSH|^~\\&|" + "|" * 30 + "~^&\\E\\\\F\\")
def test_parse_returns_a_message_or_refuses(text: str) -> None:
    msg = returns_or_refuses(lambda: hl7.parse(text), (ValueError,))
    if msg is not None:
        assert msg.segments and msg.segments[0].name == "MSH"
        returns_or_refuses(lambda: _touch(msg), ())


@SETTINGS
@given(messy_bytes)
@example(b"MSH|\r")
@example(b"MSH|^~\\&|\x1b$B\x30\x21\x1b(B|\rPID|||\xe3\x81\x82")
def test_decode_then_parse_as_the_walker_reads_a_file(data: bytes) -> None:
    def read() -> None:
        _touch(hl7.parse(hl7.decode(data)))

    returns_or_refuses(read, (hl7.Undecodable, ValueError))
