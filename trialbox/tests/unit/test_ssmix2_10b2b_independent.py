"""Card 10B-2b (D-1252): the classes an independent tester found dangerous on this card's head 2bc79278 ("independent
set 1" in ``tests/ssmix2_probes.py``, written from lane J's description of them; the tester's inputs were not seen).
Each class must read every labelled id right; each fails on #1095's head and on 2bc79278.
"""

from __future__ import annotations

import pytest

from tests import ssmix2_probes as pb

CLASSES = sorted({c.family for c in pb.independent_cases()})


@pytest.mark.parametrize("family", CLASSES)
def test_every_case_of_the_class_reads_right(family: str) -> None:
    cases = [c for c in pb.independent_cases() if c.family == family]
    report = pb.measure({family: cases})
    bad = [(r["name"], r["expect"], r["got"]) for r in report[family] if r["wrong"]]
    assert bad == []


def test_the_guidelines_all_nines_is_no_order() -> None:
    """構築ガイドライン Ver.1.2j 表3.1-3 No.4 ("ALL9") and its own example (図3.1-1: a run of nines)."""
    from adapter.sources.ssmix2.source import no_order

    for value in ("ALL9", "ＡＬＬ９", "all9", "ALL9 ", "-", "9999999999999999999999", "99999999", "9999"):
        assert no_order(value), value
    for value in ("999", "99", "9", "RX01", "ALL", "A9", "99990001"):
        assert not no_order(value), value
