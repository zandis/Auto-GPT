"""ERASE-A2 (D-875, the owner's D-532): the screening log keeps its rows, not the patient.

* a never-consented patient's rows in the screening log's five tables stay, numbered, under one random token per
  study that carries the site's day of the opt-out; the PI's note and the registry's reasons go; another patient's
  rows stay as they are;
* a trial subject's rows stay, per study, erring toward keeping: each source of consent keeps them on its own (the
  registry's history, the lifecycle, the consent forms, REDCap's read-back, a number not read back yet, the EDC, a
  merged chart's);
* an open candidate waits for its withdrawal; a source that cannot be read stops the clear and changes nothing;
* the console counts a token as opted out (it never shows one);
* the review of D-875: the lifecycle's subject of the number takes the token too (the lifecycle refresh never puts
  the patient back on the log), a number is compared as the lifecycle keys it (upper case), a merged chart's rows
  take a token with the person's, a consent recorded after the plan keeps the rows, and the registry's export leaves
  the token rows out.

Synthetic pseudonyms, numbers and dates only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from tb_common.db import Database
from tb_common.optout import OptOutRegister

A, A2, C = "a1b2c3d4e5f6b001" * 2, "a1b2c3d4e5f6b002" * 2, "c3d4e5f6a1b2b003" * 2  # A opts out; A2 is A's old chart
RS, OTHER = "GZQO", "RAXX"
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
T0 = "2026-11-12T23:30:00+00:00"  # the opt-out: 2026-11-12 in UTC
SCREENING_LOG = ("site.screening_no", "site.weekly_seen", "site.pi_marks", "orch.candidates", "orch.candidate_events")


def _stores(url: str) -> None:
    from adapter import pidmap
    from console import sitestore
    from datacore.store import DataCore
    from edc import store as edc_store
    from orchestrator import db as orch_db
    from orchestrator import studystore

    for name, mig in (("site", sitestore.MIGRATIONS), ("orch", orch_db.MIGRATIONS), ("study", studystore.MIGRATIONS),
                      ("edc", edc_store.MIGRATIONS), ("pidmap", pidmap.MIGRATIONS)):  # fmt: skip
        with Database.connect(url, name) as db:
            db.migrate(mig)
    DataCore(url)._db.close()


def _patient(url: str, rs: str, pid: str, no: str, status: str = "withdrawn", history: tuple[str, ...] = ()) -> None:
    """One patient's screening-log rows in one study, as the console and the registry write them."""
    at = "2026-11-02T09:00:00+00:00"
    with Database.connect(url, "site") as db:
        seq = int(db.fetchval("SELECT COALESCE(max(seq), 0) + 1 FROM screening_no WHERE ruleset = ?", (rs,)))
        db.execute("INSERT INTO screening_no (ruleset, pid, seq, no, at) VALUES (?,?,?,?,?)", (rs, pid, seq, no, at))
        db.execute("INSERT INTO weekly_seen (ruleset, pid, first_job, first_at) VALUES (?,?,?,?)", (rs, pid, "J1", at))
        db.execute("INSERT INTO pi_marks (ruleset, pid, mark, reason, note, by, at) VALUES (?,?,?,?,?,?,?)",
                   (rs, pid, "not_suitable", "other", "synthetic free text", "pi", at))  # fmt: skip
    with Database.connect(url, "orch") as db:
        db.execute("INSERT INTO candidates (ruleset, pid, status, reason, updated_at, updated_by, source) VALUES "
                   "(?,?,?,?,?,?,?)", (rs, pid, status, "synthetic reason", at, "crc", "manual"))  # fmt: skip
        prev = None
        for st in (*history, status):
            db.execute("INSERT INTO candidate_events (ruleset, pid, status, previous, reason, at, by) VALUES "
                       "(?,?,?,?,?,?,?)", (rs, pid, st, prev, "synthetic reason", at, "crc"))  # fmt: skip
            prev = st


def _env(url: str) -> Any:
    from datacore.optout_worker import WorkerEnv

    reg = OptOutRegister(url)
    reg.add(A, "paper", "", "office:t", T0)
    return WorkerEnv(register=reg, audit=None, now=NOW)


def _rows(url: str, key: str, pid: str) -> list[tuple[Any, ...]]:
    schema, table = key.split(".")
    with Database.connect(url, schema) as db:
        return [tuple(r) for r in db.fetchall(f"SELECT * FROM {table} WHERE pid = ?", (pid,))]


def _tokens(url: str, rs: str) -> set[str]:
    out: set[str] = set()
    for key in SCREENING_LOG:
        schema, table = key.split(".")
        with Database.connect(url, schema) as db:
            out |= {str(r[0]) for r in db.fetchall(f"SELECT pid FROM {table} WHERE ruleset = ? AND pid LIKE "
                                                   "'erased:%'", (rs,))}  # fmt: skip
    return out


@pytest.fixture
def box(db_url: str) -> Any:
    _stores(db_url)
    _patient(db_url, RS, A, "S-001", "declined", ("candidate", "contacted"))
    _patient(db_url, RS, C, "S-002", "declined", ("candidate",))
    env = _env(db_url)
    yield db_url, env
    env.register.close()


def test_a_never_consented_patients_rows_stay_numbered_under_one_token(box: Any) -> None:
    from datacore.optout_worker import clear_screening_log, verify_screening_log

    url, env = box
    before = {k: _rows(url, k, C) for k in SCREENING_LOG}
    assert verify_screening_log(frozenset({A}), env) == {"screening_log": 7}
    assert clear_screening_log(frozenset({A}), env) == {"tokened": 7, "kept_trial_subject": 0}
    assert verify_screening_log(frozenset({A}), env) == {"screening_log": 0}
    assert all(_rows(url, k, A) == [] for k in SCREENING_LOG)
    assert {k: _rows(url, k, C) for k in SCREENING_LOG} == before  # another patient's rows are untouched
    (token,) = _tokens(url, RS)  # one token for the patient's rows in the study
    assert token.startswith("erased:2026-11-12:") and A not in token
    with Database.connect(url, "site") as db:
        assert db.fetchall("SELECT no, seq FROM screening_no WHERE pid = ?", (token,)) == [("S-001", 1)]
        assert db.fetchval("SELECT note FROM pi_marks WHERE pid = ?", (token,)) is None  # the PI's free text goes
        assert db.fetchval("SELECT reason FROM pi_marks WHERE pid = ?", (token,)) == "other"  # a coded reason stays
    with Database.connect(url, "orch") as db:
        assert db.fetchall("SELECT status, reason FROM candidates WHERE pid = ?", (token,)) == [("declined", None)]
        assert [tuple(r) for r in db.fetchall("SELECT status, reason FROM candidate_events WHERE pid = ? ORDER BY seq",
                                              (token,))] == [("candidate", None), ("contacted", None),
                                                             ("declined", None)]  # fmt: skip
    from console.sitestore import SiteStore

    store = SiteStore(url)
    assert store.screening_no(RS, A) is None and store.screening_nos(RS)[C] == "S-002"
    assert store.assign_screening_no(RS, "e" * 32, _settings(), "2026-11-16T09:00:00+00:00").endswith("3")  # no reuse


def _settings() -> Any:
    from console.sitestore import StudySettings

    return StudySettings()


def test_a_trial_subjects_rows_stay_and_the_rule_is_per_study(box: Any) -> None:
    from datacore.optout_worker import clear_screening_log

    url, env = box
    _patient(url, OTHER, A, "R-001", "withdrawn", ("candidate", "consented"))  # consented once, withdrawn since
    out = clear_screening_log(frozenset({A}), env)
    assert out == {"tokened": 7, "kept_trial_subject": 1}
    assert len(_rows(url, "site.screening_no", A)) == 1 and len(_rows(url, "orch.candidate_events", A)) == 3
    assert _tokens(url, OTHER) == set() and len(_tokens(url, RS)) == 1


def _consent_in_datacore_subject(url: str) -> None:
    with Database.connect(url, "datacore") as db:
        db.execute("INSERT INTO subject (study, record, pid, state, since, changed_by, changed_at) VALUES "
                   "(?,?,?,?,?,?,?)", (RS, "S-001", "", "withdrawn", "2026-11-03", "crc", "t"))  # fmt: skip


def _consent_in_a_step(url: str) -> None:
    with Database.connect(url, "datacore") as db:
        db.execute(
            "INSERT INTO subject_step (study, record, old, new, on_day, who, at, source) VALUES (?,?,?,?,?,?,?,?)",
            (RS, "S-001", "consented", "screen_fail", "2026-11-03", "crc", "t", "ui"),
        )


def _consent_in_the_form(url: str) -> None:
    with Database.connect(url, "datacore") as db:
        db.execute("INSERT INTO value (study, record, field, value, changed_by, changed_at) VALUES (?,?,?,?,?,?)",
                   (RS, "S-001", "ic_date", "2026-11-03", "crc", "t"))  # fmt: skip


def _consent_in_the_forms_history(url: str) -> None:
    with Database.connect(url, "datacore") as db:
        db.execute(
            'INSERT INTO history (study, record, event, field, old, new, "by", at, source) VALUES (?,?,?,?,?,?,?,?,?)',
            (RS, "S-001", "", "ic_date", "2026-11-03", "", "crc", "t", "ui"),
        )


def _link(url: str, enabled: int, consent_field: str = "") -> None:
    body = json.dumps({"ruleset": RS, "project_id": 1, "token_ref": "t", "consent_field": consent_field})
    with Database.connect(url, "study") as db:
        db.execute("INSERT INTO rc_project_link (ruleset, body, enabled, set_by, set_at) VALUES (?,?,?,?,?)",
                   (RS, body, enabled, "dm", "t"))  # fmt: skip


def _consent_in_redcap(url: str) -> None:
    _link(url, 1, "ic_date")
    with Database.connect(url, "study") as db:
        db.execute("INSERT INTO rc_record (ruleset, record_id, link_value, pid, status, consent_date, read_at) VALUES "
                   "(?,?,?,?,?,?,?)", (RS, "7", "S-001", None, "screen_fail", "2026-11-03", "t"))  # fmt: skip


def _redcap_screen_fail_without_a_consent_field(url: str) -> None:
    _link(url, 1)
    with Database.connect(url, "study") as db:
        db.execute("INSERT INTO rc_record (ruleset, record_id, link_value, pid, status, read_at) VALUES "
                   "(?,?,?,?,?,?)", (RS, "7", "S-001", A, "screen_fail", "t"))  # fmt: skip


def _a_number_not_read_back_while_the_link_is_on(url: str) -> None:
    _link(url, 1, "ic_date")


def _a_draft_in_the_edc(url: str) -> None:
    with Database.connect(url, "edc") as db:
        db.execute(
            "INSERT INTO draft (study, record, pid, visit, visit_date, item, form, cdash, test, value, state, "
            "why, version, run_id, built_by, built_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (RS, "S-001", A, "V1", "2026-11-03", "i", "f", "c", "t", "v", "s", "w", "1", "r", "b", "t"),
        )


def _a_merged_charts_consent(url: str) -> None:
    with Database.connect(url, "pidmap") as db:
        db.execute("INSERT INTO pid_alias (old_pid, pid, reason, ticket, merged_at) VALUES (?,?,?,?,?)",
                   (A2, A, "duplicate chart", "T-1", "t"))  # fmt: skip
    with Database.connect(url, "orch") as db:
        db.execute("INSERT INTO candidates (ruleset, pid, status, updated_at, updated_by, source) VALUES "
                   "(?,?,?,?,?,?)", (RS, A2, "enrolled", "t", "crc", "manual"))  # fmt: skip


@pytest.mark.parametrize(
    "consent",
    [_consent_in_datacore_subject, _consent_in_a_step, _consent_in_the_form, _consent_in_the_forms_history,
     _consent_in_redcap, _redcap_screen_fail_without_a_consent_field, _a_number_not_read_back_while_the_link_is_on,
     _a_draft_in_the_edc, _a_merged_charts_consent],
)  # fmt: skip
def test_each_source_of_consent_keeps_the_rows(box: Any, consent: Any) -> None:
    from datacore.optout_worker import clear_screening_log, verify_screening_log

    url, env = box
    consent(url)
    assert clear_screening_log(frozenset({A}), env) == {"tokened": 0, "kept_trial_subject": 1}
    assert verify_screening_log(frozenset({A}), env) == {"screening_log": 0}  # a kept row is not owed
    assert all(len(_rows(url, k, A)) >= 1 for k in SCREENING_LOG)


def test_a_link_that_is_off_or_a_number_read_back_without_consent_does_not_keep(box: Any) -> None:
    from datacore.optout_worker import clear_screening_log

    url, env = box
    _link(url, 0, "ic_date")
    assert clear_screening_log(frozenset({A}), env)["tokened"] == 7


def test_an_open_candidate_waits_for_its_withdrawal(db_url: str) -> None:
    from datacore.optout_worker import clear_candidates, clear_screening_log
    from orchestrator.db import JobDB

    _stores(db_url)
    _patient(db_url, RS, A, "S-001", "contacted", ("candidate",))
    env = _env(db_url)
    assert clear_screening_log(frozenset({A}), env) == {"tokened": 0, "kept_trial_subject": 1}
    env.jobs = JobDB(db_url)
    clear_candidates(frozenset({A}), env)  # the candidate_registry clear, which the tick runs first
    env.jobs = None
    assert clear_screening_log(frozenset({A}), env)["tokened"] == 7  # the withdrawal is an event of its own
    env.register.close()


def test_a_source_that_cannot_be_read_stops_the_clear(box: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker

    url, env = box
    real = optout_worker._open

    def opener(u: str, schema: str) -> Any:
        if schema == "datacore":
            raise ConnectionError("the trial database did not answer")
        return real(u, schema)

    monkeypatch.setattr(optout_worker, "_open", opener)
    with pytest.raises(ConnectionError):
        optout_worker.clear_screening_log(frozenset({A}), env)
    assert all(_rows(url, k, A) for k in SCREENING_LOG) and _tokens(url, RS) == set()


def test_the_console_counts_a_token_as_opted_out() -> None:
    from tb_common.optout import Gone, GoneOn, erased_token

    t = erased_token("2026-11-12")
    gone, on = Gone({A}), GoneOn({A: "2026-11-13"})
    assert t in gone and A in gone and C not in gone
    assert t in on and on.get(t, "") == "2026-11-12" and on[t] == "2026-11-12" and on.get(A) == "2026-11-13"
    assert on.get(C, "") == "" and C not in on
    assert "erased:" + "0" * 32 in gone  # ERASE-C's token, no day: still opted out
    assert GoneOn().get("erased::" + "0" * 32, "x") == ""


def _subject(url: str, rs: str, record: str, pid: str, state: str = "approached") -> None:
    with Database.connect(url, "datacore") as db:
        db.execute("INSERT INTO subject (study, record, pid, state, since, changed_by, changed_at) VALUES "
                   "(?,?,?,?,?,?,?)", (rs, record, pid, state, "2026-11-03", "crc", "t"))  # fmt: skip


def test_the_lifecycles_subject_takes_the_token_and_is_never_mirrored_back(box: Any) -> None:
    from datacore.optout_worker import clear_screening_log
    from orchestrator.lifecycle_api import mirror

    url, env = box
    _subject(url, RS, "S-001", A)
    _subject(url, RS, "S-002", C)
    assert clear_screening_log(frozenset({A}), env)["tokened"] == 8
    (token,) = _tokens(url, RS)
    with Database.connect(url, "datacore") as db:
        assert db.fetchall("SELECT record, state FROM subject WHERE pid = ?", (token,)) == [("S-001", "approached")]
        assert db.fetchval("SELECT pid FROM subject WHERE record = 'S-002'") == C

    class Registry:
        def rows(self, rs: str) -> list[Any]:
            raise AssertionError("an erased subject is never looked up on the log")

    assert mirror(Registry(), RS, token, "consented", "crc", NOW) == "an erased row: the screening log is not updated"


def test_a_number_is_compared_as_the_lifecycle_keys_it(db_url: str) -> None:
    from datacore.optout_worker import clear_screening_log

    _stores(db_url)
    _patient(db_url, RS, A, "lc-0001", "declined", ("candidate",))  # a study's prefix is free text
    with Database.connect(db_url, "datacore") as db:
        db.execute("INSERT INTO value (study, record, field, value, changed_by, changed_at) VALUES (?,?,?,?,?,?)",
                   (RS, "LC-0001", "ic_date", "2026-11-03", "crc", "t"))  # fmt: skip
    env = _env(db_url)
    assert clear_screening_log(frozenset({A}), env) == {"tokened": 0, "kept_trial_subject": 1}
    env.register.close()


def test_a_merged_charts_rows_take_a_token_with_the_persons(box: Any) -> None:
    from datacore.optout_worker import clear_screening_log, verify_screening_log

    url, env = box
    with Database.connect(url, "pidmap") as db:
        db.execute(
            "INSERT INTO pid_alias (old_pid, pid, reason, ticket, merged_at) VALUES (?,?,?,?,?)",
            (A, A2, "duplicate chart", "T-1", "t"),
        )  # A was merged into A2: the register does not follow back
    _patient(url, RS, A2, "S-003", "declined", ("candidate",))
    assert verify_screening_log(frozenset({A}), env) == {"screening_log": 7 + 6}
    assert clear_screening_log(frozenset({A}), env)["tokened"] == 13
    assert all(_rows(url, k, A2) == [] for k in SCREENING_LOG)
    assert len(_tokens(url, RS)) == 2  # a chart numbered of its own keeps a token of its own


def test_a_consent_recorded_after_the_plan_keeps_the_rows(box: Any) -> None:
    from datacore import optout_worker, screening_tokens

    url, env = box
    reg = str(env.register.db.url)

    def has(schema: str, table: str) -> bool:
        return optout_worker.store_has(reg, schema, table)

    def open_(schema: str) -> Any:
        return optout_worker._open(reg, schema)

    todo, kept = screening_tokens.plan(frozenset({A}), has, open_)
    assert len(todo) == 1 and kept == 0
    with Database.connect(url, "orch") as db:
        db.execute("UPDATE candidates SET status = 'consented' WHERE pid = ?", (A,))
    assert screening_tokens.apply(todo, {}, has, open_) == 0
    assert _tokens(url, RS) == set()


def test_the_registrys_export_leaves_the_token_rows_out(box: Any, tmp_path: Any) -> None:
    import io

    from datacore.optout_worker import clear_screening_log
    from openpyxl import load_workbook
    from orchestrator.candidates import CandidateRegistry
    from orchestrator.db import JobDB

    url, env = box
    clear_screening_log(frozenset({A}), env)
    reg = CandidateRegistry(JobDB(url), None, tmp_path)  # type: ignore[arg-type]
    reg.mrns = lambda pids: {}  # type: ignore[method-assign]
    wb = load_workbook(io.BytesIO(reg.export_xlsx(RS, "DEMO-A", exclude=frozenset())))
    cells = {str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None}
    assert C in cells and not any(v.startswith("erased:") for v in cells)
