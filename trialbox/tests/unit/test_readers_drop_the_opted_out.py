"""T-206b part 2a (D-860; the owner's ruling D-513): the kept files are withheld on read.

D-513: the lake's kept snapshots, the job outputs and the attachments are not rewritten for an opt-out; every reader
drops an opted-out pseudonym on read, and the files go when retention rewrites them. This part:

* every job's lake read of patients is already scoped without an opted-out pseudonym, at receipt and at publish,
  audited by count (D-441); the review of D-860 kept it there (a second filter at the lake hid those counts);
* the console's two raw downloads of a patient-level output refuse a file that names a patient opted out since it
  was made, as the workbook already did: a per-patient file (a TWPAS bundle, a draft) by its own patient, a list in
  text by its content (any case), a compressed list by the job's text lists;
* a FEEDBACK row naming an opted-out patient is refused; a SUBMIT of a bundle for one is refused;
* ``orch.submissions``: a dry run goes, a live submission stays (D-513).

Synthetic pseudonyms only."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

A, C = "a1b2c3d4e5f6b001" * 2, "c3d4e5f6a1b2b003" * 2  # A has opted out; C has not (distinct 12-prefixes)


# ---------------------------------------------------------------------------------------------- the console
def test_a_patient_level_file_naming_an_opted_out_patient_is_withheld(monkeypatch: pytest.MonkeyPatch) -> None:
    from console import app as capp
    from tb_common import optout

    monkeypatch.setattr(optout, "register_now", lambda: frozenset({A}))
    lst = SimpleNamespace(tag="phi", filename="candidate_list.json", minio_key="outputs/J1/candidate_list.json")
    job = SimpleNamespace(outputs=[lst, SimpleNamespace(tag="phi", filename="list.pdf", minio_key="outputs/J1/l.pdf")])
    store = {"outputs/J1/candidate_list.json": f'[{{"pid": "{A}"}}]'.encode()}
    assert capp._names_opted_out(job, "candidate_list.json", store["outputs/J1/candidate_list.json"], store.get)
    assert capp._names_opted_out(job, "candidate_list.csv", f"pid\n{A.upper()}\n".encode(), store.get)  # any case
    assert not capp._names_opted_out(job, "candidate_list.json", f'[{{"pid": "{C}"}}]'.encode(), store.get)
    assert capp._names_opted_out(job, "list.pdf", b"%PDF compressed", store.__getitem__)  # judged by the JSON list
    # the review of D-860: a per-patient file by its own patient; a TWPAS bundle holds no pseudonym at all
    assert capp._names_opted_out(job, f"twpas_GZQO_{A[:12]}.json", b'{"name": "synthetic"}', store.get)
    assert not capp._names_opted_out(job, f"draft_GZQO_{C[:12]}.docx", b"PK compressed", store.__getitem__)
    # the re-check of D-860: a CASE sheet named by its job id (a ULID can hold 12 hex characters) is judged by content
    sheet = f"<p>{A}</p>".encode()
    assert capp._names_opted_out(job, "case_GZQO_01M7FEVY0Y2Y5SEE55AAA65600.html", sheet, store.get)
    alone = SimpleNamespace(outputs=[SimpleNamespace(tag="phi", filename="list.pdf", minio_key="k")])
    assert capp._names_opted_out(alone, "list.pdf", b"%PDF", store.get)  # nothing to judge it by: withheld
    monkeypatch.setattr(optout, "register_now", frozenset)
    assert not capp._names_opted_out(job, "list.pdf", b"%PDF", store.__getitem__)


# ---------------------------------------------------------------------------------------------- FEEDBACK
class _Stored(Exception):
    pass


def test_a_feedback_row_naming_an_opted_out_patient_is_refused() -> None:
    from orchestrator.scenarios import feedback

    rows: list[Any] = []

    def upsert(rs: str, good: list[dict[str, Any]], *_a: Any) -> None:
        rows.extend(good)
        raise _Stored

    csv = f"pid,outcome\n{A},enrolled\n{C},enrolled\n".encode()
    ctx = SimpleNamespace(
        job=SimpleNamespace(ruleset="GZQO", inputs=[SimpleNamespace(filename="screen_feedback.csv")], job_id="J1"),
        state=lambda *_a: None,
        input_bytes=lambda _f: csv,
        decision=SimpleNamespace(register_now=lambda: frozenset({A})),
        orch=SimpleNamespace(db=SimpleNamespace(pool=lambda rs: [{"pid": A}, {"pid": C}], feedback_upsert=upsert),
                             _now=lambda: date(2026, 11, 2)),
    )  # fmt: skip
    with pytest.raises(_Stored):
        feedback.run(ctx)  # type: ignore[arg-type]
    assert [r["pid"] for r in rows] == [C]


# ---------------------------------------------------------------------------------------------- orch.submissions
def test_a_dry_run_goes_and_a_live_submission_stays(db_url: str) -> None:
    from datacore.optout_worker import WorkerEnv, clear_tables, verify_tables
    from orchestrator import db as orch_db
    from tb_common.db import Database
    from tb_common.optout import OptOutRegister

    with Database.connect(db_url, "orch") as db:
        db.migrate(orch_db.MIGRATIONS)
        for job, dry in (("J-dry", 1), ("J-live", 0)):
            db.execute("INSERT INTO submissions (job_id, ruleset, pid, nav_job_id, bundle_sha, dry_run, outcome,"
                       " submitted_by, submitted_at) VALUES (?, 'GZQO', ?, 'N1', 's', ?, 'ok', 'crc', 'now')",
                       (job, A, dry))  # fmt: skip
    reg = OptOutRegister(db_url)
    env = WorkerEnv(register=reg, audit=None, now=None)  # type: ignore[arg-type]
    clear_tables(frozenset({A}), env)
    assert verify_tables(frozenset({A}), env)["orch.submissions"] == 0
    with Database.connect(db_url, "orch") as db:
        assert [r[0] for r in db.fetchall("SELECT job_id FROM submissions")] == ["J-live"]
    reg.close()
