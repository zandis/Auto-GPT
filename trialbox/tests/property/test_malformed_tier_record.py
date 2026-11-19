"""Card H-51 (finding H51-01): the tier record reader on malformed files (``tb_common.tier_value.measured``).

A replaced ``models/tiers/<profile>.json`` is read, or answered ``malformed``/``no_record`` with a fixed reason: no
exception leaves ``measured``, ``positive_int`` or the start-up line (D-1322; the gateway and console pages call it on
a file an operator can replace). The checker (``tools.tier_record.check``) is strict instead: on the same inputs it
returns problems and never a traceback. Inputs: bytes built from JSON pieces (deep brackets, NaN, huge numbers,
duplicate keys, wrong types where a mapping or number is expected, bools), raw bytes, and not-UTF-8 bytes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import example, given
from hypothesis import strategies as st
from tb_common import tier_value

from tests.malformed_kit import MAX_INPUT, SETTINGS, returns_or_refuses
from tools import tier_record

ENV = {"TB_PROFILE": "P-PRO6000"}
FIELD = "judge_sequences"
_PIECES = [
    b"{", b"}", b"[", b"]", b"[" * 3000, b"{\"a\":" * 2000, b",", b":", b"\"fields\"", b"\"judge_sequences\"",
    b"\"basis\"", b"\"measured\"", b"\"declared\"", b"\"not_measured\"", b"\"value\"", b"NaN", b"Infinity",
    b"-Infinity", b"9" * 5000, b"1e999", b"true", b"false", b"null", b"16", b"-1", b"0.5", b"\"\"", b"\xff",
    b"\xef\xbb\xbf", b"\x00", b" ", b"\n",
]  # fmt: skip
_RECORD = b'{"fields":{"judge_sequences":{"basis":"measured","value":%s}},"fields":{"judge_sequences":{"basis":"%s"}}}'
files = st.one_of(
    st.binary(max_size=256),
    st.lists(st.sampled_from(_PIECES) | st.binary(max_size=3), max_size=40).map(b"".join),
    st.builds(lambda v, b: _RECORD % (v, b), st.sampled_from(_PIECES), st.sampled_from([b"measured", b"declared"])),
).filter(lambda b: len(b) <= MAX_INPUT)


def _read(data: bytes) -> str:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "rtxpro6000.json"
        path.write_bytes(data)
        tv = tier_value.measured(FIELD, ENV, Path(d))
        assert tv.case in tier_value.CASES
        assert tv.case == "measured" or tv.value is None, "a value given when the field is not measured"
        tier_value.positive_int(tv)
        tv.line(tier_value.FALLBACK_SLOTS)
        assert isinstance(tier_record.check([path])[path], list)
        return tv.case


@SETTINGS
@given(files)
@example(b"[" * 200_000 + b"]" * 200_000)  # H51-01: RecursionError before the fix (beyond MAX_INPUT, kept as found)
@example(b"[" * 3000)
@example(b'{"fields":{"judge_sequences":{"basis":"measured","value":' + b"[" * 995 + b"]" * 995 + b"}}}")
@example(b"\xff\xfe")
@example(b"[1]")
@example(b'{"fields":{"judge_sequences":{"basis":"measured","value":NaN}}}')
@example(b'{"fields":{"judge_sequences":{"basis":"measured","value":' + b"9" * 5000 + b"}}}")
@example(b'{"fields":{"judge_sequences":{"basis":"measured","value":true}}}')
@example(b'{"fields":{"judge_sequences":[1]}}')
@example(b'{"fields":{"judge_sequences":{"basis":{}}}}')
def test_tier_record_reads_or_says_malformed(data: bytes) -> None:
    returns_or_refuses(lambda: _read(data), ())
