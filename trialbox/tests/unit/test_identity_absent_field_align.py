"""TRIAGE-1 §3.7 (identity, the R2 residual of H34-06): a comparison field absent on both accounts is "no difference"
today, so two people under one chart number who both lack a birth date are compared on sex alone and published as
one person (7,152 patients of the 100k twin have no birth date).

The recommendation before ALIGN: an absent comparison field is "insufficient to compare"; the night holds such a pair
(``identity_unverifiable``, counted, the steward's to accept) and never publishes them as one. ALIGN decides the
semantics, so this is the scaffold only: the journey as a strict expected failure. When ALIGN's rule lands, the test
passes, ``strict`` turns that into a failure, and the marker comes off with the ruling's PR."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import HELD, PASSED
from tb_common.crypto import pid_for_mrn

from tests.unit.test_one_chart_two_people import NEXT, _feed, _from_good, _night, _rows, _write, good  # noqa: F401

ALIGN = "TRIAGE-1 §3.7 goes to ALIGN: an absent comparison field is not yet 'insufficient to compare'"


def _no_birth_date_other(row: dict[str, str]) -> dict[str, str]:
    """Another, made-up person under ``row``'s chart number, as a feed without names and birth dates carries one (the
    twin's case): the same sex, nothing else to compare (no phone, no national id)."""
    return {**row, "name": "", "id_no": "", "birth_date": "", "death_date": "", "phone": ""}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=ALIGN)  # only the hold may be missing, no error
def test_two_people_without_a_birth_date_under_one_chart_are_held(good: Any, tmp_path: Path) -> None:  # noqa: F811
    cfg, rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    rows = _rows(feed / "patient.csv")
    first = {**rows[0], "name": "", "id_no": "", "birth_date": ""}  # the first account gives no more either
    _write(feed / "patient.csv", [first, *rows[1:], _no_birth_date_other(first)])
    rep = _night(cfg, feed, NEXT)
    assert pid_for_mrn(b"k" * 32, first["mrn"])
    assert rep.held and not rep.passed and rb.calls == []
    assert (snapshot_dir(cfg.lake_dir, NEXT) / HELD).exists()
    assert not (snapshot_dir(cfg.lake_dir, NEXT) / PASSED).exists()
