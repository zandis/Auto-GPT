"""Seed one patient in every store that has a clear, opt them out, run one tick, look (T-727, D-465).

One synthetic pseudonym is put in every store whose erasure entry has a clear today: the candidate pool, an open
candidate, OMOP (a load), the patient twin and, where the server has pgvector, the vector store. A second pseudonym
is put in the same stores and is not opted out (the scans must still find it: they can see). After the opt-out and
one tick of the worker:

* every clear's own verify finds nothing left;
* an independent raw scan of every table of the test database (each row as text) and of every file of the lake
  folder finds the opted-out pseudonym only in stores whose entry is ``keep`` or on the erasure-owed list;
* the erasure-owed list is exactly :data:`KNOWN_OWED`: a card that adds a clear removes its line here, so the list
  can only shrink.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
from tb_common import erasure
from tb_common.db import Database, split_url
from tb_common.optout import OptOutRegister

P, Q = "e7a5e0f0c0de0727", "e7a5e0f0c0de0728"  # P opts out; Q stays
T0 = "2026-11-02T09:00:00+00:00"
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
SNAP = "2026-11-02"

#: the erasure owed today (T-206b builds these on the registry; T-728 the backups' restore half). A card that adds a
#: clear takes its line out; a card that adds a store with patient data and no clear adds one.
KNOWN_OWED = frozenset(
    {
        "edc.draft", "lake:backfill", "lake:db", "lake:embed_cache.duckdb", "lake:fhir_ledger", "lake:ndjson",
        "lake:ndjson-rerun", "lake:parquet", "lake:site", "lake:tmp", "mail.send_keys", "objects:attachments",
        "objects:outputs", "omop.cohort", "omop.condition_era", "omop.cost", "omop.device_exposure", "omop.dose_era",
        "omop.drug_era", "omop.episode", "omop.episode_event", "omop.location", "omop.payer_plan_period",
        "omop.specimen", "omop.tb_conflict", "omop.tb_record", "omop.tb_record_event", "omop.visit_detail",
        "orch.candidate_events", "orch.candidates", "orch.jobs", "orch.submissions", "outside:backups", "outside:fhir_store",
        "outside:sitesetup_space_omop", "pidmap.identity", "recall.recall_known_positive", "recall.recall_observation",
        "site.pi_marks", "site.screening_no", "site.weekly_seen", "sitesetup.check_item", "sitesetup.fact", "sitesetup.fix",
        "sitesetup.input", "study.rc_record", "study.rc_write", "team.candidate_views", "trace.traces", "tuned.tuned_patients",
    }
)  # fmt: skip


class Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))


class FolderLake:
    """The lake folder as the lake lays it out (``ndjson/<night>``, ``db/<night>.duckdb``, ``embed_cache.duckdb``),
    read by the worker for the registry's refusals like the lake's own ``query``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "ndjson" / SNAP).mkdir(parents=True)
        (root / "db").mkdir()
        with (root / "ndjson" / SNAP / "Patient.ndjson").open("w", encoding="utf-8") as fh:
            for pid in (P, Q):
                fh.write(json.dumps({"resourceType": "Patient", "id": pid, "gender": "female"}) + "\n")
        con = duckdb.connect(str(root / "db" / f"{SNAP}.duckdb"))
        con.execute("CREATE TABLE patient (pid VARCHAR, sex VARCHAR)")
        con.execute("INSERT INTO patient VALUES (?, 'F'), (?, 'F')", [P, Q])
        con.execute("CREATE TABLE consent (consid VARCHAR, pid VARCHAR, status VARCHAR, contact_ok BOOLEAN, date DATE)")
        con.close()
        (root / "embed_cache.duckdb").write_bytes(b"")
        (root / "CURRENT").write_text(SNAP + "\n", encoding="utf-8")

    def snapshot(self) -> str:
        return SNAP

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        con = duckdb.connect(str(self.root / "db" / f"{snapshot or SNAP}.duckdb"), read_only=True)
        try:
            return con.execute(sql, params or []).to_arrow_table()
        finally:
            con.close()


def _batch(pids: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"Patient": [], "Encounter": [], "Condition": []}
    for i, p in enumerate(pids):
        out["Patient"].append({"resourceType": "Patient", "id": p, "birthDate": f"1960-01-0{i + 1}", "gender": "male"})
        out["Encounter"].append({"resourceType": "Encounter", "id": f"e-{p}", "status": "finished",
                                 "class": {"code": "AMB"}, "subject": {"reference": f"Patient/{p}"},
                                 "period": {"start": "2026-10-01T09:00:00", "end": "2026-10-01T10:00:00"}})  # fmt: skip
        out["Condition"].append({"resourceType": "Condition", "id": f"c-{p}", "subject": {"reference": f"Patient/{p}"},
                                 "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "M10.0"}]},
                                 "onsetDateTime": "2026-09-01", "recordedDate": "2026-09-01",
                                 "encounter": {"reference": f"Encounter/e-{p}"}})  # fmt: skip
    return out


def _vec_offered(url: str) -> bool:
    with Database.connect(url, "vec_probe") as db:
        if db.fetchval("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"):
            return True
        if not db.fetchval("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'"):
            return False
        db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        return True


def _seed_vec(url: str) -> None:
    from vec.store import VecStore

    with VecStore(url, model="test-embed", dim=3) as st:
        for i, pid in enumerate((P, Q)):
            sha = f"{i}" * 64
            st.put_vectors("test-embed", 3, {sha: [0.1 * (i + 1), 0.2, 0.3]})
            st.db.execute(
                "INSERT INTO note_chunk (pid, did, chunk_no, note_date, note_type, start_char, end_char, text, sha, "
                "mask_version) VALUES (?, ?, 0, '2026-10-01', 'progress', 0, 20, ?, ?, 'm1')",
                (pid, f"note-{pid}", f"masked note of {pid}", sha),
            )


def _raw_db_hits(url: str, needle: str) -> set[str]:
    """``schema.table`` (schema without the test's prefix) of every table of the test database with a row whose text
    holds ``needle``. Independent of the registry and the stores' code: it reads the catalogue and casts rows."""
    prefix = split_url(url)[1]
    hits: set[str] = set()
    with Database.connect(url, "scan_probe") as db:
        rows = db.fetchall(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
            "AND starts_with(table_schema, ?) ORDER BY 1, 2",
            (prefix,),
        )
        for schema, table in rows:
            if table == "_schema_version":
                continue  # the migration record (D-204): versions and checksums
            n = db.fetchval(f'SELECT count(*) FROM "{schema}"."{table}" t WHERE t::text LIKE ?', (f"%{needle}%",))
            if n:
                hits.add(f"{str(schema)[len(prefix) :]}.{table}")
    return hits


def _raw_lake_hits(root: Path, needle: str) -> set[str]:
    return {
        f"lake:{f.relative_to(root).parts[0]}"
        for f in root.rglob("*")
        if f.is_file() and needle.encode() in f.read_bytes()
    }


def _allowed(key: str) -> bool:
    e = erasure.entries().get(key)
    return e is not None and (e.kind == erasure.KEEP or e.owed_by is not None)


def test_the_owed_list_is_exactly_the_known_set() -> None:
    assert {k for k, _, _ in erasure.owed()} == KNOWN_OWED
    assert {card for _, card, _ in erasure.owed()} == {erasure.T206B}


def test_seed_opt_out_tick_and_nothing_left_where_a_clear_exists(db_url: str, tmp_path: Path) -> None:
    from datacore.optout_worker import WorkerEnv, run_once
    from omop import schema
    from omop.load import load_batch
    from orchestrator.db import JobDB
    from patient_profile.twin import ProfileStore

    lake = FolderLake(tmp_path / "lake")
    jobs = JobDB()
    for pid in (P, Q):
        jobs.pool_upsert("GZQO", "1", [{"pid": pid, "tier": "high", "verdicts": []}], "J1", T0)
        jobs.candidate_set("GZQO", pid, "candidate", None, "steward1", T0, "screen", "J1")
    omop = schema.connect(db_url)
    load_batch(omop, "feed", SNAP, _batch([P, Q]), tz="Asia/Taipei")
    twins = ProfileStore(db_url)
    for pid in (P, Q):
        twins.put({"pid": pid, "profile": "v1", "basis": {"snapshot": SNAP}, "layers": {"core": {"sex": "F"}}}, T0)
    twins.close()
    vec = _vec_offered(db_url)
    if vec:
        _seed_vec(db_url)
    before = _raw_db_hits(db_url, P)
    assert {"orch.pool", "orch.candidates", "omop.person", "profile.tb_patient_profile"} <= before
    assert not vec or "vec.note_chunk" in before

    reg = OptOutRegister()
    reg.add(P, "paper", "", "console:office1", T0)
    audit = Audit()
    out = run_once(WorkerEnv(register=reg, audit=audit, now=NOW, lake=lake, jobs=jobs, omop=omop))
    assert out["failed"] == [] and out["left"] == {}
    assert out["stores"]["profile"] == {"erased": 1}
    assert out["stores"]["vec"] == ({"chunks": 1, "embeddings": 1} if vec else {"skipped": 1})
    assert P not in repr(audit.events)  # counts, never who

    # 1. the registry's own verify functions
    env = WorkerEnv(register=reg, audit=audit, now=NOW, lake=lake, jobs=jobs, omop=omop)
    for c in erasure.clears():
        _, verify = c.resolve()
        assert not any(verify(frozenset({P}), env).values()), c.name
    # 2. an independent raw scan of the database and the lake folder
    after = _raw_db_hits(db_url, P)
    assert not {k for k in after if not _allowed(k)}, f"the opted-out patient is still in {sorted(after)}"
    for k in ("orch.pool", "omop.person", "profile.tb_patient_profile", "vec.note_chunk"):
        assert k not in after, k
    assert {"optout.optout_events", "omop.tb_withheld"} <= after  # kept on purpose (D-441)
    stays = _raw_db_hits(db_url, Q)  # the scan sees: the patient who did not opt out is everywhere still
    assert {"orch.pool", "omop.person", "profile.tb_patient_profile"} <= stays
    assert not vec or "vec.note_chunk" in stays
    lake_hits = _raw_lake_hits(lake.root, P)
    assert "lake:ndjson" in lake_hits  # the lake still holds the patient: owed (T-206b), and said so
    assert all(_allowed(k) for k in lake_hits), lake_hits
    # 3. the owed list
    assert {k for k, _, _ in erasure.owed()} == KNOWN_OWED
    omop.close()
    reg.close()


def test_the_vector_store_is_cleared_by_the_tick(db_url: str) -> None:
    """``VecStore.delete_patient`` reached through the registry (needs pgvector: the db image, or a local cluster that
    offers it; CI's pull-request jobs have none)."""
    if not _vec_offered(db_url):
        pytest.skip("the server offers no pgvector: the vector store cannot exist here (CI pull-request jobs)")
    from datacore.optout_worker import WorkerEnv, clear_vec, verify_vec

    _seed_vec(db_url)
    reg = OptOutRegister()
    env = WorkerEnv(register=reg, audit=Audit(), now=NOW)
    assert verify_vec(frozenset({P}), env) == {"vec.note_chunk": 1}
    assert clear_vec(frozenset({P}), env) == {"chunks": 1, "embeddings": 1}
    assert verify_vec(frozenset({P}), env) == {"vec.note_chunk": 0}
    assert verify_vec(frozenset({Q}), env) == {"vec.note_chunk": 1}
    reg.close()


def test_a_box_without_the_twin_or_vector_store_is_not_given_one(db_url: str) -> None:
    from datacore.optout_worker import WorkerEnv, clear_profile, clear_vec, verify_profile, verify_vec

    reg = OptOutRegister()
    env = WorkerEnv(register=reg, audit=Audit(), now=NOW)
    assert clear_vec(frozenset({P}), env) == {"skipped": 1} and verify_vec(frozenset({P}), env) == {}
    assert clear_profile(frozenset({P}), env) == {"skipped": 1} and verify_profile(frozenset({P}), env) == {}
    prefix = split_url(db_url)[1]
    for s in ("vec", "profile"):
        assert reg.db.fetchval("SELECT to_regnamespace(?)", (f"{prefix}{s}",)) is None, s
    reg.close()
