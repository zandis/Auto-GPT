"""Card 10G-43 (OT-5): the SS-MIX2 walker on malformed storage (``adapter.sources.ssmix2.source.Ssmix2Source``).

A storage of generated files is read table by table: each file gives rows or is **refused by quarantine** (counted,
listed, skipped; STD-020), a name that is not a stored file's name is passed over, and no exception leaves ``rows``,
``deleted_rows``, ``quarantine_reason`` or ``reader_summary``. The messages are HL7 v2 built from the segments the
walker reads (MSH, EVN, PID, PV1, PRB, ORC, RXE, RXA, TQ1, OBR, OBX, SPM) with generated fields, in the byte forms
SS-MIX2 files come in, and plain damaged bytes. Synthetic only: the patient numbers and names are made up here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from adapter.sources.ssmix2.source import CHANGES, TYPES, Ssmix2Source, reader_summary, storage_dir
from hypothesis import example, given, settings
from hypothesis import strategies as st

from tests.malformed_kit import SETTINGS, returns_or_refuses

_SEGS = ["EVN", "PID", "PV1", "PRB", "ORC", "RXE", "RXA", "TQ1", "OBR", "OBX", "SPM", "NTE", "ZZZ", "MSH", ""]
_TYPES = [t for ts in (*TYPES.values(), *CHANGES.values()) for t in ts] + ["ZZZ-99", ""]
_FIELD = st.one_of(
    st.sampled_from(["", "^", "~", "^^^^", "&", "\\", "\\F\\", "D", "C", "F", "X", "NM", "ST", "CWE", "TX", "6.0",
                     "-1e999", "nan", "1^2^3", "A^B^99XYZ~C^D^JC10", "20261001", "2026100109", "20261399",
                     "202610010900+0900", "99999999999999", "I", "O", "E", "Y", "N", "PI", "MR", "山田^花子"]),
    st.text(alphabet=st.sampled_from("^~&\\|0129AZaz.-+ 山"), max_size=14),
)  # fmt: skip


#: the segments each message type's builder reads, written first so most messages reach the builder's own code
_NEEDS = {"ADT-00": ["EVN", "PID"], "ADT-12": ["EVN", "PID", "PV1"], "ADT-22": ["EVN", "PID", "PV1"],
          "ADT-52": ["EVN", "PID", "PV1"], "PPR-01": ["PID", "PRB", "PRB"], "OMP-01": ["PID", "ORC", "RXE", "TQ1"],
          "OMP-02": ["PID", "ORC", "RXE", "RXA"], "OMP-11": ["ORC", "RXE"], "OMP-12": ["ORC", "RXA"],
          "OML-11": ["PID", "ORC", "OBR", "SPM", "OBX", "OBX"]}  # fmt: skip


@st.composite
def messages(draw: st.DrawFn, typ: str) -> bytes:
    if draw(st.integers(0, 9)) == 0:
        return draw(st.binary(max_size=200))  # bytes that are no message at all
    lines = ["MSH|^~\\&|HIS||TB||20261001||" + draw(st.sampled_from(["ADT^A08", "OMP^O09", "OML^O33", "PPR^PC1", ""]))
             + "|1|P|2.5||||||" + draw(st.sampled_from(["~ISO IR87", "UNICODE UTF-8", "", "SJIS", "bogus"]))]  # fmt: skip
    segs = [*_NEEDS.get(typ, []), *draw(st.lists(st.sampled_from(_SEGS), max_size=4))]
    for seg in segs:
        lines.append("|".join([seg, *draw(st.lists(_FIELD, min_size=draw(st.integers(0, 24)), max_size=30))]))
    text = draw(st.sampled_from(["\r", "\n", "\r\n"])).join(lines)
    form = draw(st.sampled_from(["utf-8", "iso2022_jp", "cp932"]))
    try:
        return text.encode(form)
    except UnicodeEncodeError:
        return text.encode("utf-8")


@st.composite
def stored(draw: st.DrawFn) -> tuple[str, str, str, str, bytes]:
    """(patient, message type, order, file name, bytes) of one file of the storage; mostly a stored file's name."""
    patient = draw(st.sampled_from(["10000001", "10000002", "1", "abcdefghij"]))
    typ = draw(st.sampled_from(_TYPES))
    order = draw(st.sampled_from(["-", "O1", "O2", ""]))
    stamp = draw(st.sampled_from(["20261001000000000", "20261002000000000", "x"]))
    flag = draw(st.sampled_from(["1", "1", "1", "0", ""]))
    good = f"{patient}_20261001_{typ}_{order}_{stamp}_-_{flag}"
    name = draw(st.sampled_from([good, good, good, f"{patient}_{typ}", "x"]))
    return patient, typ or "ADT-00", order, name, draw(messages(typ))


def _walk(files: list[tuple[str, str, str, str, bytes]]) -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for patient, typ, _order, name, data in files:
            where = storage_dir(root, patient, "20261001", typ)
            where.mkdir(parents=True, exist_ok=True)
            (where / name).write_bytes(data)
        src = Ssmix2Source(root, licensed={}, quarantine_max_pct=100.0)
        for table in (*TYPES, "note"):
            list(src.rows(table, table, "updated_at", None))
            list(src.deleted_rows(table, table, "updated_at", None))
            src.quarantine_reason(table)
        reader_summary(src)


@settings(SETTINGS, max_examples=200)  # a storage is the most varied input: more examples than the others
@given(st.lists(stored(), min_size=1, max_size=6))
@example([])
@example([("10000001", "ADT-00", "-", "10000001_20261001_ADT-00_-_20261001000000000_-_1", b"MSH|\r")])
@example([("10000001", "OML-11", "O1", "10000001_20261001_OML-11_O1_20261001000000000_-_1",
           b"MSH|^~\\&|\rOBR|1|O1\rOBX|1|NM|^^|||\rSPM|")])  # fmt: skip
@example([("10000001", "OMP-01", "O1", "10000001_20261001_OMP-01_O1_20261001000000000_-_0", b"\x1b$B!")])
def test_walker_gives_rows_or_quarantines(files: list[tuple[str, str, str, str, bytes]]) -> None:
    returns_or_refuses(lambda: _walk(files), ())
