"""D-595: the chart-number rule a box's pseudonyms were made with is recorded beside the site key's fingerprint, and
a night under another rule is refused. Synthetic chart numbers only."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.pidmap import PidMap
from tb_common import chartno
from tb_common.crypto import pid_for_mrn

SITE = "site-x"


@pytest.fixture
def pm(db_url: str, tmp_path: Path) -> PidMap:
    return PidMap(tmp_path / "pid_map.key", db_url)


def test_the_rule_is_recorded_the_first_time_and_never_replaced(pm: PidMap, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        monkeypatch.setenv(chartno.ENV, "digits:8")
        assert pm.stored_chartno_rule(SITE) is None and pm.site_key_problem(SITE, pm.key) is None
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_chartno_rule(SITE) == "digits:8"
        monkeypatch.setenv(chartno.ENV, "hex:8")
        pm.record_site_key(SITE, pm.key)  # recording again changes nothing
        assert pm.stored_chartno_rule(SITE) == "digits:8"
    finally:
        pm.close()


@pytest.mark.parametrize(("first", "then"), [("digits:8", ""), ("digits:8", "digits:9"), ("", "digits:8"),
                                             ("hex:6", "hex:6:lower"), ("asis", "digits")])  # fmt: skip
def test_a_night_under_another_rule_is_refused_and_both_rules_are_named(
    pm: PidMap, monkeypatch: pytest.MonkeyPatch, first: str, then: str
) -> None:
    """The box whose ``.env`` was removed and whose wizard wrote another rule: no patient row is needed to see it."""
    try:
        monkeypatch.setenv(chartno.ENV, first)
        pm.record_site_key(SITE, pm.key)
        monkeypatch.setenv(chartno.ENV, then)
        why = pm.site_key_problem(SITE, pm.key)
        assert why is not None and chartno.ENV in why
        assert str(chartno.parse_rule(first)) in why and str(chartno.parse_rule(then)) in why
        monkeypatch.setenv(chartno.ENV, first)
        assert pm.site_key_problem(SITE, pm.key) is None  # the rule put back: the box runs again
    finally:
        pm.close()


def test_the_same_rule_written_another_way_is_the_same_rule(pm: PidMap, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        monkeypatch.setenv(chartno.ENV, "DIGITS:8")
        pm.record_site_key(SITE, pm.key)
        for same in ("digits:8", " Digits:8 "):
            monkeypatch.setenv(chartno.ENV, same)
            assert pm.site_key_problem(SITE, pm.key) is None
        monkeypatch.delenv(chartno.ENV)
        assert "asis" in (pm.site_key_problem(SITE, pm.key) or "")
    finally:
        pm.close()


def test_a_box_from_before_records_the_rule_in_force_once_its_pseudonyms_check_out(
    pm: PidMap, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        monkeypatch.delenv(chartno.ENV, raising=False)
        pm.record_site_key(SITE, pm.key)
        with pm._db.transaction() as tx:  # the row as an earlier release left it: no rule
            tx.execute("UPDATE site_key SET chartno_rule = NULL WHERE site_id = ?", (SITE,))
        pm.upsert_many([(pid_for_mrn(pm.key, "123456"), "123456")])
        assert pm.stored_chartno_rule(SITE) is None and pm.site_key_problem(SITE, pm.key) is None
        monkeypatch.setenv(chartno.ENV, "digits:8")  # a rule set afterwards changes the stored patient's pseudonym
        why = pm.site_key_problem(SITE, pm.key)
        assert why is not None and chartno.ENV in why  # the message says the rule may be what changed
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_chartno_rule(SITE) is None  # ... and a rule that fails the check is never recorded
        monkeypatch.delenv(chartno.ENV)
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_chartno_rule(SITE) == "asis"
    finally:
        pm.close()


def test_a_rule_that_cannot_be_read_is_a_problem_not_a_crash(pm: PidMap, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        monkeypatch.setenv(chartno.ENV, "digits:8")
        pm.record_site_key(SITE, pm.key)
        monkeypatch.setenv(chartno.ENV, "eight digits")
        why = pm.site_key_problem(SITE, pm.key)
        assert why is not None and chartno.ENV in why
    finally:
        pm.close()


def _old_row(pm: PidMap) -> None:
    pm.record_site_key(SITE, pm.key)
    with pm._db.transaction() as tx:  # the row as an earlier release left it: no rule
        tx.execute("UPDATE site_key SET chartno_rule = NULL WHERE site_id = ?", (SITE,))


def test_a_box_from_before_is_checked_on_every_stored_patient_not_on_five(
    pm: PidMap, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's finding: 42 patients made under asis, two with leading zeros and not among the first five; a
    rule of ``digits`` passed the five-row probe and was recorded for good."""
    try:
        monkeypatch.delenv(chartno.ENV, raising=False)
        charts = [str(100000 + i) for i in range(40)]
        fifth = sorted(pid_for_mrn(pm.key, c) for c in charts)[4]
        # two leading-zero patients whose pseudonyms sort after the first five rows (what the old probe read)
        zeros = [c for c in (f"00{n}" for n in range(1000, 1200)) if pid_for_mrn(pm.key, c) > fifth][:2]
        assert len(zeros) == 2
        charts += zeros
        pm.upsert_many([(pid_for_mrn(pm.key, c), c) for c in charts])
        _old_row(pm)
        monkeypatch.setenv(chartno.ENV, "digits")
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_chartno_rule(SITE) is None  # not adopted: two patients would get another pseudonym
        monkeypatch.delenv(chartno.ENV)
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_chartno_rule(SITE) == "asis"
    finally:
        pm.close()


def test_a_held_nights_staged_patients_count_too(pm: PidMap, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        monkeypatch.delenv(chartno.ENV, raising=False)
        _old_row(pm)
        pm.stage("2026-11-01", [(pid_for_mrn(pm.key, "00123456"), "00123456")], [])
        monkeypatch.setenv(chartno.ENV, "digits")
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_chartno_rule(SITE) is None
    finally:
        pm.close()


def test_recording_under_a_rule_that_cannot_be_read_records_nothing_and_does_not_raise(
    pm: PidMap, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        monkeypatch.setenv(chartno.ENV, "eight digits")
        pm.record_site_key(SITE, pm.key)
        assert pm.stored_site_key(SITE) is None and pm.stored_chartno_rule(SITE) is None
    finally:
        pm.close()


@pytest.mark.parametrize(("text", "stored"), [
    ("", "asis"), ("asis", "asis"), ("digits", "digits"), ("digits:8", "digits:8"), ("DIGITS:08", "digits:8"),
    ("hex", "hex"), ("hex:8", "hex:8"), ("hex:8:upper", "hex:8"), ("hex:8:lower", "hex:8:lower"),
    ("hex:lower:8", "hex:8:lower"), ("hex:lower", "hex:lower"),
])  # fmt: skip
def test_the_text_of_a_rule_is_a_stored_format(text: str, stored: str) -> None:
    """These strings are in every box's pid map (D-595). Changing how a rule is written would refuse every box:
    a new spelling needs a migration of the stored text, not an edit here."""
    assert str(chartno.parse_rule(text)) == stored
