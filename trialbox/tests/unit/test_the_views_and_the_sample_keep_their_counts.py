"""ERASE-C (D-868): two owed stores keep their rows and lose the pseudonym at an opt-out.

* ``team.candidate_views``: the reveal cap counts a person's rows and they say who saw an identity. Each row stays,
  so the cap and "who saw" hold, and its pseudonym becomes a random token. The patient's own disclosure report reads
  the audit log (D-771), not this table.
* ``tuned.tuned_patients``: the PI's weekly sample of patients not matched. A reviewed week is never drawn again
  while it has rows, so the row stays with a random token, and the not-matched page counts it as removed.

Synthetic pseudonyms only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

A, C = "a1b2c3d4e5f6f001" * 2, "c3d4e5f6a1b2f003" * 2  # A opts out; C does not


def _env(db_url: str) -> Any:
    from datacore.optout_worker import WorkerEnv
    from tb_common.optout import OptOutRegister

    return WorkerEnv(register=OptOutRegister(db_url), audit=None, now=datetime(2026, 11, 16, tzinfo=UTC))


def test_the_reveal_ledger_keeps_its_count_and_who_saw_but_not_the_patient(db_url: str) -> None:
    from console.teamstore import TeamStore
    from datacore.optout_worker import clear_tables, verify_tables

    team = TeamStore(db_url)
    for p in (A, A, C):
        team.record_view("GZQO", p, "contact", "reveal", "crc1", "2026-11-16T09:00:00+00:00")
    assert team.count_views("crc1", "reveal", "2026-11-16T00:00:00+00:00") == 3
    env = _env(db_url)
    gone = frozenset({A})
    assert verify_tables(gone, env)["team.candidate_views"] == 2
    assert clear_tables(gone, env)["team.candidate_views"] == 2
    assert verify_tables(gone, env)["team.candidate_views"] == 0
    assert team.count_views("crc1", "reveal", "2026-11-16T00:00:00+00:00") == 3  # the cap still counts them
    assert team.views("GZQO", A) == [] and len(team.views("GZQO", C)) == 1
    tokens = [str(r[0]) for r in team.db.fetchall("SELECT pid FROM candidate_views WHERE by = 'crc1' ORDER BY id")]
    assert tokens[0].startswith("erased:") and tokens[1].startswith("erased:") and tokens[0] != tokens[1]
    team.close()
    env.register.close()


def test_a_reviewed_weeks_sample_keeps_its_size_and_the_page_counts_the_row_removed(db_url: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables
    from tb_common.notmatched import NotMatchedStore, sample_week

    store = NotMatchedStore(db_url)
    doc = {"rows": [{"pid": A, "criteria": [{"id": "E1"}]}, {"pid": C, "criteria": [{"id": "E1"}]}]}
    got, drawn = sample_week(store, "GZQO", "2026-W47", doc, job_id="J1", snapshot="s", gone=(), by="pi",
                             at="2026-11-16T09:00:00+00:00")  # fmt: skip
    assert drawn and {t.pid for t in got} == {A, C}
    env = _env(db_url)
    assert clear_tables(frozenset({A}), env)["tuned.tuned_patients"] == 1
    assert verify_tables(frozenset({A}), env)["tuned.tuned_patients"] == 0
    again, drawn = sample_week(store, "GZQO", "2026-W47", doc, job_id="J1", snapshot="s", gone=(A,), by="pi",
                               at="2026-11-16T10:00:00+00:00")  # fmt: skip
    assert not drawn and len(again) == 2  # the reviewed week is not drawn again
    from console.notmatched_pages import ERASED

    assert [t.pid for t in again if not t.pid.startswith(ERASED)] == [C]
    store.close()
    env.register.close()
