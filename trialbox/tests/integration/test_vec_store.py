"""The vector store's SQL on pgvector (T-203a, D-439): schema ``vec`` on a server with the ``vector`` extension.

The stock PostgreSQL of the unit job and of the local test cluster (``tools/pglocal.py``) has no pgvector. These
tests run where the extension is: the test database itself when it has ``vector`` (``TB_TEST_DB_URL`` pointing at
the box's db image), or the box's db image started as ``tests/integration/test_db_image.py`` starts it (marker
``integration``, ``TB_INTEGRATION=1``, image built by ``make images``; the nightly workflow ``trialbox-e2e.yml``,
``make test-compose``, which allows no skip). Anywhere else they skip with that reason.

Synthetic notes only; the planted identifiers are T-600's (``tests/unit/test_phi_note_mask.py``).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from embed_service.embedder import HashEmbedder
from tb_common.db import Database, extensions, script_sha256
from vec import store as vs
from vec.index import Note, index_notes
from vec.store import VecError, VecStore

from tests.unit.test_phi_note_mask import IDENTIFIERS, NOTES, SITE_MRN

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def vec_server(request: pytest.FixtureRequest) -> Iterator[str]:
    """A database URL whose database has the ``vector`` extension."""
    given = os.environ.get("TB_TEST_DB_URL")
    if given:
        with Database.connect(given, "probe") as db:
            offered = db.fetchval("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")
            if offered and not extensions(db, ("vector",))["vector"]:
                # installed on the server but not created in this database: create it (a nightly run must not skip
                # by accident); a role without the right fails here, with the reason, instead of skipping
                db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            if extensions(db, ("vector",))["vector"]:
                yield given
                return
    from tests.integration import test_db_image as dbi

    image = dbi._image()  # skips without TB_INTEGRATION=1 or the built image, with the reason
    name = f"tb-vec-{uuid.uuid4().hex[:8]}"
    try:
        port = dbi._start(image, name)
        yield f"postgresql://trialbox:wf-test@127.0.0.1:{port}/trialbox_wf"
    finally:
        dbi._docker("rm", "-f", "-v", name, check=False)


@pytest.fixture
def url(vec_server: str) -> str:
    """Schemas of this test only (``tb_prefix``)."""
    sep = "&" if "?" in vec_server else "?"
    return f"{vec_server}{sep}tb_prefix=v{uuid.uuid4().hex[:8]}_"


def _notes() -> list[Note]:
    shared = "Gout flare. Allopurinol continued."
    return [
        Note("p1", "d1", NOTES["d1"], "2026-01-01", "progress"),
        Note("p2", "d2", NOTES["d2"], "2026-01-02", "progress"),
        Note("p1", "d3", shared, "2026-01-03", "progress"),
        Note("p3", "d4", shared, "2026-01-04", "progress"),
        Note("p3", "d5", "Knee pain after a fall. X-ray normal.", "2026-01-05", "ed"),
    ]


def test_the_store_migrates_twice_with_its_pinned_checksum(url: str) -> None:
    for _ in range(2):
        with VecStore(url) as st:
            assert [(r.version, r.sha256) for r in st.db.applied()] == [
                (1, script_sha256(vs.SCHEMA_V1)),
                (2, script_sha256(vs.MIGRATIONS[1])),  # D-1253: tb_id_rule
            ]


def test_the_hnsw_index_is_there_after_the_store_opens_for_a_model(url: str) -> None:
    e = HashEmbedder()
    with VecStore(url, model=e.model, dim=e.dim) as st:
        idx = st.indexes()
        name = vs.index_name(e.model)
        assert name in idx and "USING hnsw" in idx[name] and "halfvec_cosine_ops" in idx[name]
        assert "halfvec(1024)" in idx[name] and e.model in idx[name]
        assert st.ensure_index(e.model, e.dim) == name  # idempotent
        assert {"note_chunk_person_date", "note_chunk_sha"} <= set(
            str(r[0]) for r in st.db.fetchall("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
        )


def test_notes_are_indexed_masked_and_embedded_once_per_sha(url: str) -> None:
    e = HashEmbedder()
    with VecStore(url) as st:
        first = index_notes(st, _notes(), e, mrn_regex=SITE_MRN)
        texts = [str(r[0]) for r in st.db.fetchall("SELECT text FROM note_chunk")]
        assert texts and not any(i in t for t in texts for i in IDENTIFIERS)
        shas = st.db.fetchval("SELECT count(DISTINCT sha) FROM note_chunk")
        assert first.embedded_new == shas == st.counts()["embeddings"] < first.chunks  # the shared text once
        again = index_notes(st, _notes(), e, mrn_regex=SITE_MRN)
        assert again.embedded_new == 0 and st.counts()["chunks"] == first.chunks
        for c in st.chunks("p1"):
            assert c["end_char"] - c["start_char"] == len(c["text"])
        assert st.db.fetchval("SELECT count(*) FROM embedding WHERE public.vector_dims(emb) <> dim") == 0


def test_search_by_patient_is_exact_and_stays_in_the_patients(url: str) -> None:
    e = HashEmbedder()
    with VecStore(url) as st:
        index_notes(st, _notes(), e, mrn_regex=SITE_MRN)
        q = e.embed(["Knee pain after a fall. X-ray normal."])[0]
        hits = st.search(q, e.model, k=3, pids=["p3"])
        assert hits and {h["pid"] for h in hits} == {"p3"} and hits[0]["did"] == "d5"
        assert hits[0]["score"] == pytest.approx(1.0, abs=1e-2)  # halfvec precision
        assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
        assert st.search(q, e.model, k=3, pids=["p1"]) and all(
            h["pid"] == "p1" for h in st.search(q, e.model, k=3, pids=["p1"])
        )
        assert st.search(q, e.model, k=3, pids=[]) == [] and st.search(q, "another-model", k=3, pids=["p3"]) == []


def test_search_over_the_store_uses_the_models_hnsw_index(url: str) -> None:
    e = HashEmbedder()
    with VecStore(url, model=e.model, dim=e.dim) as st:
        index_notes(st, _notes(), e, mrn_regex=SITE_MRN)
        q = e.embed(["Gout flare. Allopurinol continued."])[0]
        hits = st.search(q, e.model, k=2)
        assert {h["did"] for h in hits} == {"d3", "d4"}  # one vector, two patients' notes
        lit = vs.literal(q, e.dim)
        with st.db.transaction() as tx:
            tx.execute("SET LOCAL enable_seqscan = off")
            plan = "\n".join(
                str(r[0]) for r in tx.fetchall("EXPLAIN " + vs.search_sql(e.model, e.dim, 2, False), (lit, lit))
            )
        assert vs.index_name(e.model) in plan, plan


def test_the_dimension_follows_the_embedder_and_a_model_keeps_one(url: str) -> None:
    class Small(HashEmbedder):
        model, dim = "hash-small", 8

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [v[:8] for v in super().embed(texts)]

    with VecStore(url) as st:
        index_notes(st, _notes()[:2], HashEmbedder(), mrn_regex=SITE_MRN)
        index_notes(st, _notes()[:2], Small(), mrn_regex=SITE_MRN)
        dims: dict[str, int] = dict(st.db.fetchall("SELECT model, max(dim) FROM embedding GROUP BY model"))
        assert dims == {HashEmbedder.model: 1024, "hash-small": 8}
        assert "halfvec(8)" in st.indexes()[vs.index_name("hash-small")]
        with pytest.raises(VecError, match="dimension 8"):
            st.ensure_index("hash-small", 16)
        q = Small().embed(["Gout."])[0]
        assert all(len(h["text"]) for h in st.search(q, "hash-small", k=2, pids=["p1", "p2"]))


def test_delete_patient_removes_their_chunks_and_only_orphan_vectors(url: str) -> None:
    e = HashEmbedder()
    with VecStore(url) as st:
        index_notes(st, _notes(), e, mrn_regex=SITE_MRN)
        before = st.counts()
        mine = {c["sha"] for c in st.chunks("p1")}
        shared = {c["sha"] for c in st.chunks("p3")} & mine
        assert shared  # the text p1 and p3 both have
        out = st.delete_patient("p1")
        assert out["chunks"] == before["chunks"] - st.counts()["chunks"] > 0
        assert st.chunks("p1") == [] and out["embeddings"] == len(mine - shared)
        assert st.have(shared, e.model) == shared and st.have(mine - shared, e.model) == set()
        q = e.embed(["Gout flare. Allopurinol continued."])[0]
        assert {h["pid"] for h in st.search(q, e.model, k=5)} <= {"p2", "p3"}
        assert st.delete_patient("p1") == {"chunks": 0, "embeddings": 0}


def test_new_chunks_are_refused_beside_chunks_of_the_earlier_id_rule(url: str) -> None:
    """D-1253: an empty store is stamped with the lake-id rule at its first write; one that holds chunks under no rule
    (a store from before D-1253) takes no new chunk, and nothing is written."""
    from tb_common import id_rule

    store = VecStore(url)
    store.replace_notes([vs.ChunkRow("p1", "d1", 0, "2026-01-01", "progress", 0, 4, "text", "sha", "m1")], ["d1"])
    with Database.connect(url, "vec") as db:
        assert db.fetchval("SELECT count(*) FROM tb_id_rule WHERE rule = ?", (id_rule.RULE,)) == 1
        db.execute("DELETE FROM tb_id_rule")  # the store as it was before D-1253
    with pytest.raises(id_rule.IdRuleError, match="vec"):
        store.replace_notes([vs.ChunkRow("p1", "d2", 0, "2026-01-01", "progress", 0, 4, "text", "sha2", "m1")], ["d2"])
    with Database.connect(url, "vec") as db:
        assert db.fetchval("SELECT count(*) FROM note_chunk") == 1
