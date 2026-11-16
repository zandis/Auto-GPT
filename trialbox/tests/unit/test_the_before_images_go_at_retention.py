# ruff: noqa: F811 - the db fixture is imported from the ERASE-B test and taken by name
"""D-531 (the owner, 2026-11-16): an opted-out patient's before-images are kept hidden until retention, then blanked.

* past retention (the lake's month-end months, counted from the day the patient was withheld) the record events lose
  their before-images and the FHIR fields of the record image; the records keep their ids and provenance (D-441) and
  lose their FHIR fields (``extra``); another patient's stay;
* before retention, or for a patient released (lifted), nothing is blanked: a lift and the export as of a time work;
* an export as of an earlier time still winds back after the blank (the patient stays out); for a patient released
  since, an instant before a blanked image is refused (the review of D-531);
* the consent statements the withhold keeps (D-441) are not blanked; a steward's free-text reason goes;
* the opt-out worker's ``omop`` clear blanks with the box's retention and its verify counts what is left.

Synthetic ids and values only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from tests.unit.test_the_withhold_reaches_every_table_by_person import A, C, _put, db  # noqa: F401

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
FHIR = {"code": {"text": "synthetic"}, "note": "synthetic free text"}


def _record(db: Any, person: int, rid: int, n: int) -> int:
    _put(db, "tb_record", {"cdm_table": "drug_exposure", "record_id": rid, "person_id": person, "status": "coded",
                           "extra": json.dumps(FHIR)}, n)  # fmt: skip
    key = int(db.fetchval("SELECT record_key FROM tb_record WHERE record_id = ? AND cdm_table = 'drug_exposure'",
                          (rid,)))  # fmt: skip
    image = db.fetchval("SELECT row_to_json(r)::text FROM tb_record r WHERE record_key = ?", (key,))
    db.execute(
        "INSERT INTO tb_record_event (record_key, event, before_sha, before, record_before) VALUES "
        "(?, 'update', 'sha', ?::jsonb, ?::jsonb)",
        (key, json.dumps({"drug_exposure_id": rid}), image),
    )
    return key


def _withheld(db: Any, pid: str, since: str) -> None:
    db.execute("INSERT INTO tb_withheld (pid, since, reason) VALUES (?, ?::timestamptz, 'opted out')", (pid, since))


def _image(db: Any, key: int) -> tuple[Any, ...]:
    row = db.fetchone("SELECT before, before_sha, record_before FROM tb_record_event WHERE record_key = ?", (key,))
    return tuple(row)


def _extra(db: Any, key: int) -> Any:
    return db.fetchval("SELECT extra FROM tb_record WHERE record_key = ?", (key,))


def test_past_retention_the_images_and_the_fhir_fields_go_and_the_ids_stay(db: Any) -> None:
    from omop import load

    a, c = _record(db, A, 100, 1), _record(db, C, 101, 2)
    _withheld(db, "P-A", "2023-09-01T00:00:00+00:00")  # 38 months before NOW
    db.execute("UPDATE tb_record_event SET reason = 'synthetic steward note' WHERE record_key = ?", (a,))
    assert load.owed_at_retention(db, NOW, 36) == {"tb_record_event": 1, "tb_record.extra": 1}
    assert load.blank_at_retention(db, NOW, 36) == {"images_blanked": 1, "records_blanked": 1}
    before, sha, image = _image(db, a)
    assert before is None and sha is None
    image = image if isinstance(image, dict) else json.loads(image)
    assert image["extra"] == {} and image["record_id"] == 100 and image["person_id"] == A  # the ids stay
    assert image["blanked"] is True
    assert db.fetchval("SELECT reason FROM tb_record_event WHERE record_key = ?", (a,)) is None
    assert _extra(db, a) in ({}, "{}")
    assert _image(db, c)[0] is not None and _extra(db, c) not in ({}, "{}")  # another patient's stay
    assert load.owed_at_retention(db, NOW, 36) == {"tb_record_event": 0, "tb_record.extra": 0}
    assert load.blank_at_retention(db, NOW, 36) == {"images_blanked": 0, "records_blanked": 0}  # once


def test_before_retention_or_after_a_lift_nothing_is_blanked(db: Any) -> None:
    from omop import load

    a, c = _record(db, A, 100, 1), _record(db, C, 101, 2)
    _withheld(db, "P-A", "2026-10-01T00:00:00+00:00")  # withheld a month ago: kept hidden
    assert load.blank_at_retention(db, NOW, 36) == {"images_blanked": 0, "records_blanked": 0}
    assert _image(db, a)[0] is not None and _extra(db, a) not in ({}, "{}")
    assert _image(db, c)[0] is not None  # C was never withheld (or was lifted): not on the table
    assert load.owed_at_retention(db, NOW, 36) == {"tb_record_event": 0, "tb_record.extra": 0}


def test_an_export_as_of_an_earlier_time_still_winds_back(db: Any) -> None:
    from omop import load
    from omop.export import export_rows

    _record(db, A, 100, 1)
    _withheld(db, "P-A", "2023-09-01T00:00:00+00:00")
    load.blank_at_retention(db, NOW, 36)
    db.execute("UPDATE tb_record_event SET at = ?::timestamptz", ("2026-11-10T00:00:00+00:00",))
    out = export_rows(db, as_of=datetime(2026, 11, 1, tzinfo=UTC))  # never refused: the image keeps the ids
    assert not any(r.get("person_id") == A for rows in out.values() for r in rows if isinstance(r, dict))


def test_the_worker_blanks_with_the_boxs_retention_and_verify_counts_what_is_left(db: Any, db_url: str) -> None:
    from datacore.optout_worker import KEEP_MONTHS, WorkerEnv, _keep_months, clear_omop, verify_omop
    from tb_common.optout import OptOutRegister

    a = _record(db, A, 100, 1)
    reg = OptOutRegister(db_url)
    env = WorkerEnv(register=reg, audit=None, now=NOW, omop=db)
    clear_omop(frozenset({"P-A"}), env)  # no retention given: withheld, nothing blanked
    assert _image(db, a)[0] is not None
    db.execute("UPDATE tb_withheld SET since = '2023-09-01T00:00:00+00:00'::timestamptz")
    env.extra[KEEP_MONTHS] = 36
    # the update's image and the withhold's own tombstone image
    assert verify_omop(frozenset({"P-A"}), env)["omop.tb_record_event"] == 2
    assert clear_omop(frozenset({"P-A"}), env)["images_blanked"] == 2
    assert verify_omop(frozenset({"P-A"}), env)["omop.tb_record_event"] == 0
    reg.close()
    box = SimpleNamespace(cfg=SimpleNamespace(settings=SimpleNamespace(
        retention=SimpleNamespace(month_end_snapshots_months=24))))  # fmt: skip
    assert _keep_months(box) == 24 and _keep_months(SimpleNamespace()) == 36


def test_the_cutoff_is_the_lakes_month(db: Any) -> None:
    from omop import load

    _record(db, A, 100, 1)
    _withheld(db, "P-A", "2023-11-20T00:00:00+00:00")  # the lake drops its last snapshot of the patient 2026-11-01
    assert load.owed_at_retention(db, datetime(2026, 10, 31, tzinfo=UTC), 36)["tb_record_event"] == 0
    assert load.owed_at_retention(db, datetime(2026, 11, 1, tzinfo=UTC), 36)["tb_record_event"] == 1


def test_a_kept_consent_statement_is_not_blanked(db: Any) -> None:
    from omop import load

    _put(db, "tb_record", {"cdm_table": "tb_consent", "record_id": 900, "person_id": A, "status": "coded",
                           "extra": json.dumps({"provenance": "synthetic"})}, 9)  # fmt: skip
    _withheld(db, "P-A", "2023-09-01T00:00:00+00:00")
    load.blank_at_retention(db, NOW, 36)
    assert db.fetchval("SELECT extra FROM tb_record WHERE cdm_table = 'tb_consent'") not in ({}, "{}")


def test_a_released_patients_blanked_history_is_refused_not_guessed(db: Any) -> None:
    import pytest
    from omop import load
    from omop.export import export_rows
    from omop.schema import OmopError

    _record(db, A, 100, 1)
    _withheld(db, "P-A", "2023-09-01T00:00:00+00:00")
    load.blank_at_retention(db, NOW, 36)
    db.execute("UPDATE tb_record_event SET at = ?::timestamptz", ("2026-11-10T00:00:00+00:00",))
    db.execute("DELETE FROM tb_withheld")  # the patient lifted the opt-out
    with pytest.raises(OmopError, match="blanked at retention"):
        export_rows(db, as_of=datetime(2026, 11, 1, tzinfo=UTC))
