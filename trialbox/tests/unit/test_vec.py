"""The vector store's chunker and indexing (T-203a, D-439), without a database.

The SQL of :mod:`vec.store` needs pgvector, which only the box's db image has: it is tested in
``tests/integration/test_vec_store.py``. Here the store is a fake with the same methods, so the PHI pass, the chunk
offsets, "embed once per sha" and the dimension rule are tested on every unit run.
"""

from __future__ import annotations

import itertools
import sys
import types
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from tb_common.db import Database, extensions
from tb_common.phi_guard import MASK_CHAR, NOTE_MASK_VERSION, mask_note
from vec import chunker, index, store
from vec.index import Note, index_notes, note_chunks
from vec.store import ChunkRow, VecError

from tests.unit.test_phi_note_mask import IDENTIFIERS, NOTES  # T-600's planted identifiers, synthetic

SITE_MRN = r"^\d{8}$"


class SpyEmbedder(HashEmbedder):
    def __init__(self, dim: int | None = None) -> None:
        self.inputs: list[str] = []
        self.out_dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        vecs = super().embed(texts)
        return [v[: self.out_dim] for v in vecs] if self.out_dim else vecs


class FakeStore:
    """:class:`vec.index.Store` in memory."""

    def __init__(self) -> None:
        self.vectors: dict[tuple[str, str], list[float]] = {}
        self.rows: dict[tuple[str, int], ChunkRow] = {}
        self.indexes: dict[str, int] = {}

    def ensure_index(self, model: str, dim: int) -> str:
        self.indexes[model] = dim
        return store.index_name(model)

    def have(self, shas: Iterable[str], model: str) -> set[str]:
        return {s for s in shas if (s, model) in self.vectors}

    def put_vectors(self, model: str, dim: int, vectors: dict[str, Sequence[float]]) -> int:
        new = {k: v for k, v in vectors.items() if (k, model) not in self.vectors}
        for sha, v in new.items():
            store.literal(v, dim)
            self.vectors[(sha, model)] = list(v)
        return len(new)

    def replace_notes(self, chunks: Sequence[ChunkRow], dids: Iterable[str]) -> int:
        gone = set(dids) | {c.did for c in chunks}
        self.rows = {k: r for k, r in self.rows.items() if r.did not in gone}
        for c in chunks:
            self.rows[(c.did, c.chunk_no)] = c
        return len(chunks)


def _notes() -> list[Note]:
    return [Note(f"p{i}", did, text, "2026-01-01", "progress") for i, (did, text) in enumerate(NOTES.items(), 1)]


# ------------------------------------------------------------------------------------------------ the chunker
def test_sentences_end_at_cjk_and_latin_ends_and_line_breaks_not_at_decimals() -> None:
    text = "尿酸9.2。血壓穩定！Gout flare. HbA1c 7.1%\n下次回診"
    got = [text[s:e] for s, e in chunker.sentences(text)]
    assert got == ["尿酸9.2。", "血壓穩定！", "Gout flare.", "HbA1c 7.1%", "下次回診"]
    assert chunker.sentences("  \n ") == []


def _long_note() -> str:
    parts = [f"第{i}次回診，尿酸{i % 9}.{i % 7}，血壓穩定，持續服藥並追蹤腎功能。" for i in range(60)]
    return "\n".join(parts) + " " + "x" * 1300  # and one sentence longer than a chunk


def test_chunk_offsets_map_back_to_the_note_text_and_bytes() -> None:
    note = _long_note()
    chunks = chunker.chunk_note(note)
    assert len(chunks) > 5
    raw = note.encode("utf-8")
    for c in chunks:
        assert c.text == note[c.start : c.end] and c.text == c.text.strip()
        assert 0 < len(c.text) <= chunker.SIZE
        b0, b1 = chunker.byte_span(note, c.start, c.end)
        assert raw[b0:b1].decode("utf-8") == c.text  # the offsets reach the note's own bytes
    assert [c.no for c in chunks] == list(range(len(chunks)))
    covered = set().union(*(range(c.start, c.end) for c in chunks))
    assert all(i in covered for i, ch in enumerate(note) if not ch.isspace())  # nothing of the note is lost


def test_chunks_are_cut_at_sentence_ends_and_overlap_by_whole_sentences() -> None:
    note = _long_note()
    ends = {e for _, e in chunker.sentences(note)}
    starts = {s for s, _ in chunker.sentences(note)}
    chunks = chunker.chunk_note(note)
    packed = [c for c in chunks if c.end <= note.index("x")]
    assert packed and all(c.start in starts and c.end in ends for c in packed)
    for a, b in itertools.pairwise(packed):
        assert b.start < a.end and a.end - b.start <= chunker.OVERLAP  # a whole trailing sentence carried over
    long_ = [c for c in chunks if "x" in c.text]
    assert len(long_) >= 3 and all(len(c.text) <= chunker.SIZE for c in long_)


def test_short_and_empty_notes() -> None:
    assert chunker.chunk_note("") == [] and chunker.chunk_note(" \n ") == []
    (only,) = chunker.chunk_note("  Gout.  ")
    assert (only.start, only.end, only.text) == (2, 7, "Gout.")
    with pytest.raises(ValueError, match="overlap"):
        chunker.spans("abc", size=10, overlap=10)


# ------------------------------------------------------------------------------------------------ the PHI pass
def test_chunks_are_made_after_the_phi_pass_and_keep_offsets_into_the_original() -> None:
    for note in _notes():
        rows = note_chunks(note, SITE_MRN)
        masked = mask_note(note.text, SITE_MRN)
        assert rows and len(masked) == len(note.text)
        for r in rows:
            assert r.text == masked[r.start : r.end] and r.mask_version == NOTE_MASK_VERSION
            # outside the masked spans the chunk is the note's own text, at the same offsets
            assert all(a == b for a, b in zip(r.text, note.text[r.start : r.end], strict=True) if a != MASK_CHAR)
            assert not any(ident in r.text for ident in IDENTIFIERS)


def test_planted_identifiers_reach_no_chunk_and_no_embedding_input() -> None:
    fake, spy = FakeStore(), SpyEmbedder()
    stats = index_notes(fake, _notes(), spy, mrn_regex=SITE_MRN)
    assert stats.notes == 2 and stats.chunks == len(fake.rows) > 0 and spy.inputs
    for ident in IDENTIFIERS:
        assert all(ident not in r.text for r in fake.rows.values()), ident
        assert all(ident not in x for x in spy.inputs), ident
    assert any("尿酸9.2" in x for x in spy.inputs) and any("Gout." in x for x in spy.inputs)


# ------------------------------------------------------------------------------------------------ indexing
def test_embed_once_per_sha() -> None:
    fake, spy = FakeStore(), SpyEmbedder()
    same = "Gout flare. Allopurinol continued."
    notes = [Note("p1", "a", same), Note("p2", "b", same), Note("p1", "c", "Knee pain.")]
    first = index_notes(fake, notes, spy)
    assert first.embedded_new == 2 and len(spy.inputs) == 2 == len(fake.vectors)  # one text, two notes: once
    again = index_notes(fake, notes, spy)  # the next night, nothing new
    assert again.embedded_new == 0 and len(spy.inputs) == 2 and again.chunks == first.chunks
    other = SpyEmbedder()
    other.model = "hash-other"
    assert index_notes(fake, notes[:1], other).embedded_new == 1  # another model is another vector


def test_a_note_indexed_again_has_its_chunks_replaced() -> None:
    fake = FakeStore()
    index_notes(fake, [Note("p1", "a", "One. " * 300)], HashEmbedder())
    assert len([r for r in fake.rows.values() if r.did == "a"]) > 1
    index_notes(fake, [Note("p1", "a", "Two."), Note("p1", "a", "Three.")], HashEmbedder(), batch_notes=5)
    assert [r.text for r in fake.rows.values() if r.did == "a"] == ["Three."]


def test_the_dimension_is_the_embedders_and_a_wrong_length_is_refused() -> None:
    fake = FakeStore()
    small = SpyEmbedder(dim=8)
    small.dim = 8
    index_notes(fake, [Note("p1", "a", "Gout.")], small)
    assert fake.indexes == {small.model: 8} and all(len(v) == 8 for v in fake.vectors.values())
    liar = SpyEmbedder(dim=8)  # says 1024, returns 8
    liar.model = "liar"
    with pytest.raises(VecError, match="dimension is 1024"):
        index_notes(fake, [Note("p1", "b", "Knee.")], liar)
    assert not any(m == "liar" for _, m in fake.vectors)


class _Short(HashEmbedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return super().embed(texts)[:-1]


def test_an_embedder_returning_too_few_vectors_is_refused() -> None:
    with pytest.raises(VecError, match="returned 1 vectors for 2 texts"):
        index.embed_missing(FakeStore(), {"s1": "a", "s2": "b"}, _Short())


# ------------------------------------------------------------------------------------------------ the store's SQL
def test_model_names_and_dimensions_are_checked_before_they_reach_sql() -> None:
    assert store.check_model("e-embed-1") == "e-embed-1" and store.check_model("hash-1024-v1")
    for bad in ("", "x'; DROP TABLE embedding; --", "a b", "?", "%s"):
        with pytest.raises(VecError):
            store.check_model(bad)
    for bad_dim in (0, -1, 4001, True, 1.5):
        with pytest.raises(VecError):
            store.check_dim(bad_dim)  # type: ignore[arg-type]


def test_the_hnsw_index_is_per_model_and_cast_to_its_dimension() -> None:
    ddl = store.index_ddl("e-embed-1", 1024)
    assert "USING hnsw ((emb::public.halfvec(1024)) public.halfvec_cosine_ops) WHERE model = 'e-embed-1'" in ddl
    assert store.index_name("e-embed-1") != store.index_name("hash-1024-v1")
    assert store.index_name("e-embed-1").startswith("embedding_hnsw_") and len(store.index_name("x")) == 27


def test_vector_literals() -> None:
    assert store.literal([1, 0.5, -2e-5], 3) == "[1.0,0.5,-2e-05]"
    with pytest.raises(VecError, match="dimension is 4"):
        store.literal([1.0, 2.0, 3.0], 4)
    with pytest.raises(VecError, match="not finite"):
        store.literal([float("nan")], 1)


def test_the_migration_names_no_fixed_dimension() -> None:
    assert "halfvec(" not in store.SCHEMA_V1 and "public.halfvec NOT NULL" in store.SCHEMA_V1
    assert "note_chunk_person_date ON note_chunk (pid, note_date)" in store.SCHEMA_V1


# ------------------------------------------------------------------------------------------------ the embedder's dim
def test_the_local_embedder_reports_its_models_dimension(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from embed_service import embedder as emb

    class _ST:
        def __init__(self, path: str, device: str = "cpu", trust_remote_code: bool = True) -> None:
            assert trust_remote_code is False

        def get_sentence_embedding_dimension(self) -> int:
            return 768

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_ST))
    (tmp_path / "model.safetensors").write_bytes(b"stand-in")
    assert emb.LocalEmbedder(str(tmp_path)).dim == 768  # not the DIM constant: the store follows the embedder


def test_the_http_client_takes_the_services_dimension() -> None:
    from embed_service import embedder as emb

    class _Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return {"vectors": [[0.0] * 768], "model": "e-embed-1", "dim": 768}

    client = emb.HttpEmbedder.__new__(emb.HttpEmbedder)
    client.base_url, client.model, client.dim = "http://embed", "remote", emb.DIM
    client.client = types.SimpleNamespace(post=lambda *a, **k: _Resp())  # type: ignore[assignment]
    assert len(client.embed(["Gout."])[0]) == 768 and (client.model, client.dim) == ("e-embed-1", 768)


def test_the_search_queries() -> None:
    near = store.search_sql("e-embed-1", 1024, 5, by_patient=False)
    assert "WHERE e.model = 'e-embed-1' ORDER BY (e.emb::public.halfvec(1024)) OPERATOR(public.<=>)" in near
    assert near.count("?") == 2 and "LIMIT 5" in near
    exact = store.search_sql("e-embed-1", 1024, 5, by_patient=True)
    assert "WHERE c.pid = ANY(?)" in exact and exact.count("?") == 3 and "AND e.dim = 1024" in exact
    with pytest.raises(VecError):
        store.search_sql("bad'model", 1024, 5, by_patient=True)


# ------------------------------------------------------------------------------------------------ the backup drill
def test_the_backup_drill_checks_the_vector_store(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import backup_drill as bd

    monkeypatch.setenv("TB_DB_URL", db_url)
    with Database.connect(db_url, "probe") as db:
        has_vector = bool(extensions(db, ("vector",))["vector"])
    snap = bd._vec(fill=True)
    assert (snap is None) == (not has_vector)  # the local cluster has no pgvector: the drill says so
    name, ok, why = bd._vec_check(None, None, require=False)
    assert ok and "no vector extension" in why and "D-439" in name
    assert bd._vec_check(None, None, require=True)[1] is False
    same = {"chunks": [("p", "d", 0, 0, 5, "Gout.", "s")], "vectors": [("s", "m", 2, "[1,0]")], "index": True,
            "search": [("d", 0)]}  # fmt: skip
    assert bd._vec_check(same, dict(same), require=True)[1] is True
    assert bd._vec_check(same, {**same, "vectors": []}, require=True)[1] is False
    assert bd._vec_check(same, {**same, "index": False}, require=True)[1] is False
