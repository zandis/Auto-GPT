"""Plan 10 cards 10B-2 to 10B-5 (review 12's faults F1 to F4, criterion F1): the SS-MIX2 reader read against a
storage written from the specification (``tests/ssmix2_spec_kit.py``), not against TrialBox's own exporter. Each
test failed on the reader before its card and passes after it. All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


@pytest.fixture
def storage(tmp_path: Path) -> kit.Storage:
    return kit.build(tmp_path)


def _source(st: kit.Storage, **kw: object) -> Ssmix2Source:
    return Ssmix2Source(st.root, licensed=EMPTY, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ F1 (10B-2)
def test_f1_three_visits_on_three_days_read_as_three_with_all9_and_with_a_per_day_number(
    storage: kit.Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 12's probe M4: three ADT-12 files on three days under "ALL9" (patient 1) and under "1" (patient 2)
    gave one visit each under the old default key; the specification's key (D-1000) gives three."""
    monkeypatch.delenv("TB_SSMIX2_ORDER_NUMBERS", raising=False)
    rows = list(_source(storage).rows("encounter", "encounter", None, None))
    for patient, visits in kit.VISITS.items():
        got = sorted(r["enc_no"] for r in rows if r["mrn"] == patient and r["enc_type"] == "OPD")
        assert got == [v for _day, v in visits], patient


def test_f1_each_admission_is_kept_and_discharged(storage: kit.Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """Card 12-1's proof: two admissions and two discharges, each under the per-day sequence "1"; the first
    admission is no longer lost and none stays "in-progress"."""
    monkeypatch.delenv("TB_SSMIX2_ORDER_NUMBERS", raising=False)
    src = _source(storage)
    rows = {r["enc_no"]: r for r in src.rows("encounter", "encounter", None, None) if r["enc_type"] == "IPD"}
    assert sorted(rows) == ["V2101", "V2102"]
    assert {k: (r["enc_status"], r["end_datetime"]) for k, r in rows.items()} == {
        "V2101": ("finished", "2026-09-05 11:00:00"),
        "V2102": ("finished", "2026-09-25 11:00:00"),
    }
    assert src.stats["ADT-52:discharge"] == 2


def test_f1_a_site_that_declares_unique_still_keeps_all9_and_adt_records_by_day(storage: kit.Storage) -> None:
    """``unique`` stays as a site's declared exception (D-1000); "ALL9" is not an order number and an ADT number is
    a per-day sequence, so neither ever collapses days."""
    rows = list(_source(storage, order_key="unique").rows("encounter", "encounter", None, None))
    assert len(rows) == 8  # six outpatient visits and two admissions


def test_f1_the_default_is_the_specifications_key() -> None:
    from adapter.sources.ssmix2 import source
    from tb_common.config import DECLARED

    assert source.DEFAULT_ORDER_KEY == "per_day"
    assert DECLARED["TB_SSMIX2_ORDER_NUMBERS"].default == "per_day"
