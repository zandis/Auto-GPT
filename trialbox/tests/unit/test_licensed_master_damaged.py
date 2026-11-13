"""A licensed vendor master (MEDIS, JLAC10, YJ) that is UTF-8 and already holds U+FFFD, the replacement character:
some program damaged it before it reached the box. The sheet reader refuses such a file with the line of the
character; the licensed reader decoded it and loaded the damaged names. Found by the review of #481."""

from __future__ import annotations

import pytest
from adapter.licensed import LicensedError, parse

HEAD = "jlac10,name,loinc\n"
GOOD = "3C0150000023271,尿酸,3084-1\n3D0100000023271,クレアチニン,2160-0\n"


def test_a_utf8_master_that_holds_a_replacement_character_is_refused_with_its_line() -> None:
    damaged = HEAD + GOOD + "3D0450000023271,HbA�c,4548-4\n"
    with pytest.raises(LicensedError) as e:
        parse("jlac10", damaged.encode("utf-8"))
    assert e.value.code == "LIC-ENCODING"
    assert "U+FFFD" in e.value.message and "line 4" in e.value.message


@pytest.mark.parametrize("codec", ["utf-8", "utf-8-sig", "cp932"])
def test_a_sound_master_is_read_as_before(codec: str) -> None:
    got = parse("jlac10", (HEAD + GOOD).encode(codec))
    assert len(got.concepts) == 2 and got.encoding == ("utf-8-sig" if codec == "utf-8-sig" else codec)
