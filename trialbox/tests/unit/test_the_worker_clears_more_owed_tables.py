"""ERASE-A1 (D-866): three more owed stores leave the owed list, by the opt-out worker's ``owed_tables`` clear.

* ``edc.draft``: a never-consented patient's drafts go; a consented or enrolled subject's stay (OD-8), and so does a
  draft already signed or sent;
* ``recall.recall_observation`` and ``recall.recall_known_positive``: the draw stays for the recall estimate, and its
  ``pid_hash`` (an unsalted hash of the pseudonym) becomes a random token, so the patient cannot be found in it;
* ``sitesetup.fact``: a fact read from an uploaded file, by pseudonym, goes.

Synthetic pseudonyms only."""

from __future__ import annotations

from typing import Any

import pytest

A, B, C = "a1b2c3d4e5f6e001" * 2, "b2c3d4e5f6a1e002" * 2, "c3d4e5f6a1b2e003" * 2  # A, B opt out; C does not


class Registry:
    """The candidate registry as the worker reads it: B consented in GZQO, A was only listed."""

    def candidate_summaries(self) -> list[dict[str, Any]]:
        return [{"ruleset": "GZQO"}]

    def candidates(self, rs: str) -> list[dict[str, Any]]:
        return [{"pid": A, "status": "listed"}, {"pid": B, "status": "consented"}, {"pid": C, "status": "listed"}]


def _draft(db: Any, pid: str, *, signed: bool = False) -> None:
    db.execute(
        "INSERT INTO draft (study, record, pid, visit, visit_date, item, form, cdash, test, value, state, why, version,"
        " run_id, built_by, built_at, signature_id) VALUES ('GZQO', 'R1', ?, 'v1', '2026-11-01', 'i', 'f', 'c', 't',"
        " '1', 'drafted', 'synthetic', '1', 'run', 'sys', '2026-11-01', ?)",
        (pid, 7 if signed else None),
    )


@pytest.fixture
def stores(db_url: str) -> Any:
    from edc import store as edc_store
    from orchestrator.recall import ledger
    from sitesetup.store import SetupStore
    from tb_common.db import Database

    with Database.connect(db_url, "edc") as db:
        db.migrate(edc_store.MIGRATIONS)
        for pid in (A, B, C):
            _draft(db, pid)
        _draft(db, A, signed=True)  # a signed draft is the record of what was done: it stays
    with Database.connect(db_url, "recall") as db:
        db.migrate(ledger.MIGRATIONS)
    SetupStore(db_url).close()  # the site set-up's tables
    return db_url


def _env(db_url: str, gone: set[str]) -> Any:
    from datetime import UTC, datetime

    from datacore.optout_worker import WorkerEnv
    from tb_common.optout import OptOutRegister

    reg = OptOutRegister(db_url)
    return WorkerEnv(register=reg, audit=None, now=datetime(2026, 11, 16, tzinfo=UTC), jobs=Registry())


def test_a_never_consented_patients_drafts_go_and_a_subjects_stay(stores: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables
    from tb_common.db import Database

    env = _env(stores, {A, B})
    gone = frozenset({A, B})
    assert verify_tables(gone, env)["edc.draft"] == 1  # A's unsigned draft only
    assert clear_tables(gone, env)["edc.draft"] == 1
    assert verify_tables(gone, env)["edc.draft"] == 0
    with Database.connect(stores, "edc") as db:
        left = sorted((str(r[0]), r[1] is not None) for r in db.fetchall("SELECT pid, signature_id FROM draft"))
    assert left == sorted([(A, True), (B, False), (C, False)])  # A's signed one, B the subject's, C not opted out
    env.register.close()


def test_a_recall_draw_stays_and_cannot_be_traced_to_the_patient(stores: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables
    from matching.cascade.certificate import pid_hash
    from tb_common.db import Database

    with Database.connect(stores, "recall") as db:
        for i, pid in enumerate((A, C)):
            db.execute(
                "INSERT INTO recall_known_positive (line, population, seq_no, draw_id, pid_hash, missed, observed_at)"
                " VALUES ('l', 'p', ?, ?, ?, 0, '2026-11-01')",
                (i, f"d{i}", pid_hash(pid)),
            )
    env = _env(stores, {A})
    gone = frozenset({A})
    assert verify_tables(gone, env)["recall.recall_known_positive"] == 1
    assert clear_tables(gone, env)["recall.recall_known_positive"] == 1
    assert verify_tables(gone, env)["recall.recall_known_positive"] == 0
    with Database.connect(stores, "recall") as db:
        hashes = [str(r[0]) for r in db.fetchall("SELECT pid_hash FROM recall_known_positive ORDER BY seq_no")]
    assert len(hashes) == 2 and hashes[0].startswith("erased:") and hashes[1] == pid_hash(C)  # the count stays
    env.register.close()


def test_a_fact_by_the_pseudonym_goes(stores: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables
    from tb_common.db import Database

    with Database.connect(stores, "sitesetup") as db:
        for pid in (A, C):
            db.execute(
                "INSERT INTO fact (ws, input_id, pid, domain, status, at) VALUES ('main', 1, ?, 'dx', 'ok', 'now')",
                (pid,),
            )
    env = _env(stores, {A})
    gone = frozenset({A})
    assert verify_tables(gone, env)["sitesetup.fact"] == 1
    assert clear_tables(gone, env)["sitesetup.fact"] == 1
    assert verify_tables(gone, env)["sitesetup.fact"] == 0
    with Database.connect(stores, "sitesetup") as db:
        assert [str(r[0]) for r in db.fetchall("SELECT pid FROM fact")] == [C]
    env.register.close()


def test_with_no_candidate_registry_the_drafts_are_never_called_cleared(stores: str) -> None:
    from datacore.optout_worker import clear_tables

    env = _env(stores, {A})
    env.jobs = None
    with pytest.raises(RuntimeError):
        clear_tables(frozenset({A}), env)
    env.register.close()


def test_the_registry_lists_them_on_the_clear() -> None:
    from tb_common import erasure

    es = erasure.entries()
    for k in ("edc.draft", "recall.recall_observation", "recall.recall_known_positive", "sitesetup.fact"):
        assert es[k].kind == erasure.ERASE and es[k].clear == "owed_tables" and not es[k].owed_by, k
