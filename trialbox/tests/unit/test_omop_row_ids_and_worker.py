"""T-702 (D-753): the OMOP row ids are ``bigint``, and the opt-out worker never waits for a load (scale review F-17)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from omop import load, schema


@pytest.fixture
def db(db_url: str) -> Any:
    d = schema.connect(db_url)
    yield d
    d.close()


def _types(db: Any) -> dict[tuple[str, str], str]:
    with db.transaction() as tx:
        return {
            (str(t), str(c)): str(ty)
            for t, c, ty in tx.fetchall(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema()"
            )
        }


def test_every_column_that_holds_a_row_id_is_bigint(db: Any) -> None:
    types = _types(db)
    cols = [*schema.row_id_columns(), *schema.TB_ROW_ID_COLUMNS]
    assert ("measurement", "measurement_id") in cols and ("note_nlp", "note_id") in cols
    assert {c: types[c] for c in cols if types[c] != "bigint"} == {}
    # a partition follows its table
    parts = [k for k in types if k[0].startswith("measurement_y") or k[0] == "measurement_default"]
    assert all(types[(t, "measurement_id")] == "bigint" for t, _ in parts if (t, "measurement_id") in types)
    assert types[("person", "person_id")] == "integer" and types[("measurement", "measurement_concept_id")] == "integer"


def test_the_row_sequence_goes_past_the_int4_end(db: Any) -> None:
    with db.transaction() as tx:
        tx.execute(f"SELECT setval('tb_row_seq', {schema.INT4_MAX})")
        nxt = int(tx.fetchall("SELECT nextval('tb_row_seq')")[0][0])
        assert nxt == schema.INT4_MAX + 1
        tx.execute(
            "INSERT INTO measurement (measurement_id, person_id, measurement_concept_id, measurement_date, "
            "measurement_type_concept_id) VALUES (?, 1, 0, DATE '2026-01-01', 0)",
            (nxt,),
        )
        got = tx.fetchall("SELECT measurement_id FROM measurement WHERE measurement_id = ?", (nxt,))
        assert int(got[0][0]) == nxt
        tx.execute("DELETE FROM measurement WHERE measurement_id = ?", (nxt,))
        tx.execute("SELECT setval('tb_row_seq', 1, false)")


def test_the_opt_out_worker_does_not_wait_for_a_load(db: Any, db_url: str) -> None:
    """A load holds the store's lock for its whole transaction: the worker is refused at once, never held."""
    held, release = threading.Event(), threading.Event()

    def a_load() -> None:
        other = schema.connect(db_url)
        try:
            with other.transaction() as tx:
                tx.execute("SELECT pg_advisory_xact_lock(hashtext('trialbox-omop-load'))")
                held.set()
                release.wait(30)
        finally:
            other.close()

    t = threading.Thread(target=a_load)
    t.start()
    try:
        assert held.wait(30)
        start = time.monotonic()
        with pytest.raises(load.LoadRunning):
            load.withhold(db, ["P-1"])
        assert time.monotonic() - start < 5
    finally:
        release.set()
        t.join(30)
    assert load.withhold(db, ["P-1"]).withheld == 1  # after the load: withheld
    assert load.withhold(db, []).released == 1
