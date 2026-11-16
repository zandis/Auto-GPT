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

    g = frozenset({A})
    lst = SimpleNamespace(tag="phi", filename="candidate_list.json", minio_key="outputs/J1/candidate_list.json")
    job = SimpleNamespace(outputs=[lst, SimpleNamespace(tag="phi", filename="list.pdf", minio_key="outputs/J1/l.pdf")])
    store = {"outputs/J1/candidate_list.json": f'[{{"pid": "{A}"}}]'.encode()}
    assert capp._names_opted_out(job, "candidate_list.json", store["outputs/J1/candidate_list.json"], store.get, g)
    assert capp._names_opted_out(job, "candidate_list.csv", f"pid\n{A.upper()}\n".encode(), store.get, g)  # any case
    assert not capp._names_opted_out(job, "candidate_list.json", f'[{{"pid": "{C}"}}]'.encode(), store.get, g)
    assert capp._names_opted_out(job, "list.pdf", b"%PDF compressed", store.__getitem__, g)  # judged by the JSON list
    # the review of D-860: a per-patient file by its own patient; a TWPAS bundle holds no pseudonym at all
    assert capp._names_opted_out(job, f"twpas_GZQO_{A[:12]}.json", b'{"name": "synthetic"}', store.get, g)
    assert not capp._names_opted_out(job, f"draft_GZQO_{C[:12]}.docx", b"PK compressed", store.__getitem__, g)
    # the re-check of D-860: a CASE sheet named by its job id (a ULID can hold 12 hex characters) is judged by content
    sheet = f"<p>{A}</p>".encode()
    assert capp._names_opted_out(job, "case_GZQO_01M7FEVY0Y2Y5SEE55AAA65600.html", sheet, store.get, g)
    alone = SimpleNamespace(outputs=[SimpleNamespace(tag="phi", filename="list.pdf", minio_key="k")])
    assert capp._names_opted_out(alone, "list.pdf", b"%PDF", store.get, g)  # nothing to judge it by: withheld
    assert not capp._names_opted_out(job, "list.pdf", b"%PDF", store.__getitem__, frozenset())


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


# ---------------------------------------------------------------------------------------------- part 2b (D-862)
def test_the_stored_equivalence_report_names_no_patient() -> None:
    """The criteria compiler's equivalence sample is kept in the draft and the library's history: each disagreeing
    patient is a case label there, never the pseudonym (nothing reads it back), also inside an evidence string."""
    from criteria_compiler.equivalence.gate import without_pseudonyms
    from tb_contracts import Disagreement, EquivalenceReport

    d = [Disagreement(criterion_id="I1", pid=A, index_date="2026-11-01", cql=True, sql=False,
                      evidence_cql=[f"Condition/c-{A}"], evidence_sql=f"obs {A}"),
         Disagreement(criterion_id="I2", pid=A, index_date="2026-11-01", cql=False, sql=True),
         Disagreement(criterion_id="I1", pid=C, index_date="2026-11-01", cql=True, sql=False)]  # fmt: skip
    rep = EquivalenceReport.model_validate({"overall_pct": 50.0, "per_criterion": {"I1": 50.0, "I2": 50.0},
                                            "failing": ["I1"], "sample_size": 2, "disagreements": d})  # fmt: skip
    stored = without_pseudonyms(rep)
    text = stored.model_dump_json()
    assert A not in text and C not in text
    assert [x.pid for x in stored.disagreements or []] == ["case-001", "case-001", "case-002"]
    assert stored.failing == rep.failing and stored.per_criterion == rep.per_criterion  # what the run reads back


def test_the_embed_cache_loses_the_vectors_only_an_opted_out_patients_notes_hold(tmp_path: Any) -> None:
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    from tools.trialbox import memcaps

    night = "2026-10-04"
    memcaps.write_ndjson(tmp_path / "lake" / "ndjson" / night, 6)
    lake = Lake(tmp_path / "lake", "Asia/Taipei")
    lake.rebuild(night, HashEmbedder())
    rows = lake.query("SELECT pid, sha FROM document_chunk", [], night).to_pylist()
    by: dict[str, set[str]] = {}
    for r in rows:
        by.setdefault(r["pid"], set()).add(r["sha"])
    assert len(by) >= 2, "the synthetic night has notes of more than one patient"
    gone = sorted(by)[0]
    others = set().union(*(s for p, s in by.items() if p != gone))
    only = by[gone] - others
    assert lake.prune_cache([gone], dry_run=True) == {"vectors": len(only)}
    assert lake.prune_cache([gone]) == {"vectors": len(only)}
    assert lake.prune_cache([gone], dry_run=True) == {"vectors": 0}  # read back: nothing of theirs alone is left
    model = HashEmbedder().model
    assert set(lake.vectors(sorted(others), model)) == others  # every other patient's vectors stay
