"""Card 10B-2b (D-1252): the classes an independent tester found dangerous on this card's head 2bc79278 ("independent
set 1" in ``tests/ssmix2_probes.py``, written from lane J's description of them; the tester's inputs were not seen).
Each class must read every labelled id right; each fails on #1095's head and on 2bc79278.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import ssmix2_probes as pb

CLASSES = sorted({c.family for c in pb.independent_cases()})
CLASSES_2 = sorted({c.family for c in pb.independent_cases_2()})


@pytest.mark.parametrize("family", CLASSES)
def test_every_case_of_the_class_reads_right(family: str) -> None:
    cases = [c for c in pb.independent_cases() if c.family == family]
    report = pb.measure({family: cases})
    bad = [(r["name"], r["expect"], r["got"]) for r in report[family] if r["wrong"]]
    assert bad == []


@pytest.mark.parametrize("family", CLASSES_2)
def test_every_case_of_the_second_testers_class_reads_right(family: str) -> None:
    """The second tester's classes B to F at 5ae5593f (lane J), and the correct-site shapes ("OK") that must stay
    confirmed with the master."""
    cases = [c for c in pb.independent_cases_2() if c.family == family]
    report = pb.measure({family: cases})
    bad = [(r["name"], r["expect"], r["got"]) for r in report[family] if r["wrong"]]
    assert bad == []


def test_a_type_the_reader_does_not_read_is_counted_never_silent(tmp_path: Path) -> None:
    """Class E: files of a type no table reads (OML-01, OMG-01) are counted by type."""
    from adapter.sources.ssmix2.source import Ssmix2Source

    for typ, order in (("OML-01", "L1"), ("OMG-01", "G1"), ("OMG-01", "G2")):
        pb.F(pb.P1, pb.DAY_A, typ, order, pb.stamp(pb.DAY_A, 0), "1", [pb.msh("X^Y"), pb.pid(pb.P1)]).write(tmp_path)
    src = Ssmix2Source(tmp_path, licensed={"medis": {}, "jlac10": {}, "yj": {}})
    list(src.rows("diagnosis", "diagnosis", None, None))
    assert src.stats["storage:OML-01 file (a type the reader does not read)"] == 1
    assert src.stats["storage:OMG-01 file (a type the reader does not read)"] == 2


def test_the_guidelines_all_nines_is_no_order() -> None:
    """構築ガイドライン Ver.1.2j 表3.1-3 No.4 ("ALL9") and its own example (図3.1-1: a run of nines)."""
    from adapter.sources.ssmix2.source import no_order

    for value in ("ALL9", "ＡＬＬ９", "all9", "ALL9 ", "-", "9999999999999999999999", "99999999", "9999"):
        assert no_order(value), value
    for value in ("999", "99", "9", "RX01", "ALL", "A9", "99990001"):
        assert not no_order(value), value
