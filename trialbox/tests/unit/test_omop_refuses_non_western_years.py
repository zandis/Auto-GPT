"""NEW-B-2 (D-521): the OMOP path refuses a date whose year is not a western year.

The lake's flattener reads a FHIR date with ``date.fromisoformat``: ``0115-03-01`` (a Republic-of-China year, an
era year) is the western year 115 to it. The legacy flatten is being removed and is not repaired. The OMOP store
of record, which the lake is built from, must not take such a date: the batch is refused whole (D-271: nothing
loaded, the night is held), because a feed that writes one date in another calendar writes all of them so."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_omop_additions import TZ, _feed, store

__all__ = ["store"]


def _counts(db: Any) -> tuple[int, int]:
    return (
        int(db.fetchval("SELECT count(*) FROM person")),
        int(db.fetchval("SELECT count(*) FROM condition_occurrence")),
    )


@pytest.mark.parametrize("where", ["onset", "onset with a time", "birth"])
def test_a_batch_with_a_year_of_another_calendar_is_refused_whole(store: Any, where: str) -> None:
    from omop.load import load_batch
    from omop.schema import OmopError

    good = _feed()
    load_batch(store, "feed", "2026-10-05", good, tz=TZ)
    before = _counts(store)
    starts = store.fetchall("SELECT condition_start_date FROM condition_occurrence ORDER BY 1")
    bad = _feed("2026-10-06")
    if where == "birth":
        bad["Patient"][0]["birthDate"] = "0049-01-01"  # ROC 49 is 1960
    else:
        bad["Condition"][0]["onsetDateTime"] = "0115-03-01" if where == "onset" else "0115-03-01T10:00:00+08:00"
    with pytest.raises(OmopError, match="not a western year") as err:
        load_batch(store, "feed", "2026-10-06", bad, tz=TZ)
    assert "0115" not in str(err.value) and "0049" not in str(err.value)  # no feed value in the message
    assert "refused, nothing loaded" in str(err.value)
    assert _counts(store) == before  # nothing of the batch is in the store
    assert store.fetchall("SELECT condition_start_date FROM condition_occurrence ORDER BY 1") == starts
    kinds = [str(r[0]) for r in store.fetchall("SELECT source_kind FROM tb_load ORDER BY 1")]
    assert kinds == ["feed", "feed-refused"]  # the refusal itself is kept
    load_batch(store, "feed", "2026-10-06", _feed("2026-10-06"), tz=TZ)  # the corrected feed loads


@pytest.mark.nodb
def test_the_flattener_refuses_only_where_it_is_asked_to() -> None:
    from lake.flatten import EARLIEST_YEAR, Flattener, NotWesternYear

    strict = Flattener(TZ, earliest_year=EARLIEST_YEAR)
    for value in ("0115-03-01", "0115-03-01T10:00:00+08:00", "1849-12-31"):
        with pytest.raises(NotWesternYear) as err:
            strict.ts(value)
        assert value[:4] not in str(err.value)
        with pytest.raises(NotWesternYear):
            strict.d(value)
    assert strict.ts("1850-01-01") is not None and strict.d("2026-09-02") is not None and strict.ts(None) is None
    # the legacy flatten (no bound asked for) reads as it did: it is being removed, not repaired
    assert Flattener(TZ).ts("0115-03-01") is not None
