"""ERASE-B (D-867): an opt-out reaches the OMOP tables no loader writes yet, and the clinical conflicts.

The withhold (``omop.load.withhold``, D-441) deleted the clinical tables the loaders write. Twelve more CDM tables
hold a person's rows when a loader writes them (eras, episodes, specimens, visit details, payer plan periods,
devices, cohorts, costs, an address), and ``tb_conflict`` holds every source's value of a disputed item. Each is now
cleared by person at the opt-out, so a later loader is covered from its first row. Another person's rows stay.

Synthetic ids only: every required column gets a placeholder."""

from __future__ import annotations

from typing import Any

import pytest

A, C = 7, 8  # the persons of the pseudonyms P-A (opts out) and P-C (does not)

#: table -> the column that names the person (cost and episode_event are reached through an event)
BY_PERSON = {
    "condition_era": "person_id", "drug_era": "person_id", "dose_era": "person_id", "device_exposure": "person_id",
    "specimen": "person_id", "visit_detail": "person_id", "payer_plan_period": "person_id", "episode": "person_id",
    "cohort": "subject_id", "tb_conflict": "person_id",
}  # fmt: skip


def _required(db: Any, table: str) -> list[tuple[str, str]]:
    return [
        (str(r[0]), str(r[1]))
        for r in db.fetchall(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = ? AND is_nullable = 'NO' AND column_default IS NULL ORDER BY ordinal_position",
            (table,),
        )
    ]


def _value(col: str, kind: str, n: int) -> Any:
    if "json" in kind:
        return "[]"
    if kind in ("integer", "bigint", "smallint", "numeric", "double precision", "real"):
        return n
    if "date" in kind or "timestamp" in kind:
        return "2026-11-01"
    return f"syn-{col}-{n}"


def _put(db: Any, table: str, fixed: dict[str, Any], n: int) -> None:
    cols = dict(fixed)
    for col, kind in _required(db, table):
        cols.setdefault(col, _value(col, kind, n))
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    db.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(cols.values()))


@pytest.fixture
def db(db_url: str) -> Any:
    from omop import schema

    d = schema.connect(db_url)
    d.execute("INSERT INTO tb_id_map (id_kind, source_id, omop_id) VALUES ('person', 'P-A', ?), ('person', 'P-C', ?)",
              (A, C))  # fmt: skip
    for i, person in enumerate((A, C)):
        n = 100 + i
        _put(d, "location", {"location_id": n}, n)
        _put(d, "person", {"person_id": person, "location_id": n}, n)
        for table, col in BY_PERSON.items():
            extra: dict[str, Any] = {"episode_id": n} if table == "episode" else {}
            if table == "tb_conflict":
                extra = {"claims": "[]", "state": "open", "values_sha": f"s{n}"}
            _put(d, table, {col: person, **extra}, n)
        _put(d, "episode_event", {"episode_id": n}, n)
        _put(d, "drug_exposure", {"drug_exposure_id": n, "person_id": person}, n)
        _put(d, "cost", {"cost_event_id": n, "cost_domain_id": "Drug"}, n)
    yield d
    d.close()


def _left(db: Any, person: int, n: int) -> dict[str, int]:
    out = {t: int(db.fetchval(f"SELECT count(*) FROM {t} WHERE {c} = ?", (person,)))
           for t, c in BY_PERSON.items()}  # fmt: skip
    out["episode_event"] = int(db.fetchval("SELECT count(*) FROM episode_event WHERE episode_id = ?", (n,)))
    out["cost"] = int(db.fetchval("SELECT count(*) FROM cost WHERE cost_event_id = ?", (n,)))
    out["location"] = int(db.fetchval("SELECT count(*) FROM location WHERE location_id = ?", (n,)))
    return out


def test_an_opt_out_clears_every_table_by_person_and_keeps_another_persons(db: Any) -> None:
    from omop import load

    _put(db, "tb_record", {"cdm_table": "person", "record_id": A, "person_id": A, "status": "coded"}, 1)
    load.withhold(db, ["P-A"])
    assert all(v == 0 for v in _left(db, A, 100).values()), _left(db, A, 100)
    assert all(v == 1 for v in _left(db, C, 101).values()), _left(db, C, 101)


def test_the_worker_reads_every_table_back(db: Any, db_url: str) -> None:
    from datacore.optout_worker import _verify_one_omop

    for i, (table, rid) in enumerate((("person", A), ("drug_exposure", 100))):  # what the loader wrote, as it records
        _put(db, "tb_record", {"cdm_table": table, "record_id": rid, "person_id": A, "status": "coded"}, i + 1)

    before = _verify_one_omop("omop", db, frozenset({"P-A"}))
    for k in ("omop.cohort", "omop.episode_event", "omop.tb_conflict", "omop.condition_era", "omop.visit_detail"):
        assert before[k] == 1, (k, before)
    from omop import load

    load.withhold(db, ["P-A"])
    after = _verify_one_omop("omop", db, frozenset({"P-A"}))
    assert {k: v for k, v in after.items() if v} == {}, after
