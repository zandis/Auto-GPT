"""The vector store: schema ``vec`` of the trial database, in pgvector (T-203a, D-439, review CR-068).

    store = VecStore(url, model=embedder.model, dim=embedder.dim)    # migrates, makes the model's HNSW index
    hits = store.search(vector, embedder.model, k=10, pids=["p1"])  # T-203b (S2b, behind its flag)
    store.delete_patient("p1")                                      # T-206b (erasure): chunks and orphan vectors

``embedding`` holds one vector per masked chunk text (its sha256) and embedding model: a text is embedded once.
``note_chunk`` holds each chunk of a note: patient, note, date, type, its offsets in the note, the masked text and
its sha. The vector column is ``public.halfvec`` with no size: the dimension is the embedder's (D-429: it is known
only after G1), recorded per row and checked; the HNSW index is an expression index per model, cast to that
model's dimension, made by :meth:`VecStore.ensure_index`. pgvector lives in schema ``public`` (D-204), so its types,
functions and operators are written qualified.

The extension ``vector`` exists only on the box's db image; on a server without it :class:`VecStore` raises
:class:`tb_common.db.DatabaseError` from the migration.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import astuple, dataclass
from typing import Any

from tb_common.db import ENV, Database

STORE = "vec"
EXTENSION = "vector"
MAX_HNSW_DIM = 4000  # pgvector: halfvec in an HNSW index
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS embedding (sha TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL CHECK (dim > 0),
  emb public.halfvec NOT NULL, made_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (sha, model),
  CHECK (public.vector_dims(emb) = dim));
CREATE TABLE IF NOT EXISTS note_chunk (pid TEXT NOT NULL, did TEXT NOT NULL, chunk_no INTEGER NOT NULL,
  note_date DATE, note_type TEXT, start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, text TEXT NOT NULL,
  sha TEXT NOT NULL, mask_version TEXT NOT NULL, made_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (did, chunk_no), CHECK (0 <= start_char AND start_char < end_char));
CREATE INDEX IF NOT EXISTS note_chunk_person_date ON note_chunk (pid, note_date);
CREATE INDEX IF NOT EXISTS note_chunk_sha ON note_chunk (sha)
"""
MIGRATIONS = (SCHEMA_V1,)


class VecError(ValueError):
    """A model name, dimension or vector the store refuses."""


@dataclass(frozen=True)
class ChunkRow:
    pid: str
    did: str
    chunk_no: int
    note_date: str | None
    note_type: str | None
    start: int
    end: int
    text: str
    sha: str
    mask_version: str


def check_model(model: str) -> str:
    if not _MODEL.match(model or ""):
        raise VecError(f"embedding model name {model!r} is not one the store takes (letters, digits, ._:/+-)")
    return model


def check_dim(dim: int) -> int:
    if not isinstance(dim, int) or isinstance(dim, bool) or not 0 < dim <= MAX_HNSW_DIM:
        raise VecError(f"dimension {dim!r} is outside 1..{MAX_HNSW_DIM} (pgvector halfvec with HNSW)")
    return dim


def index_name(model: str) -> str:
    """The HNSW index of one embedding model (a hash: a model name may not be a valid identifier)."""
    return "embedding_hnsw_" + hashlib.sha256(check_model(model).encode("utf-8")).hexdigest()[:12]


def index_ddl(model: str, dim: int) -> str:
    """The model's HNSW index: cosine distance on the vector cast to the model's dimension, only that model's rows."""
    return (
        f"CREATE INDEX IF NOT EXISTS {index_name(model)} ON embedding USING hnsw "
        f"((emb::public.halfvec({check_dim(dim)})) public.halfvec_cosine_ops) WHERE model = '{check_model(model)}'"
    )


def literal(vec: Sequence[float], dim: int) -> str:
    """A vector as pgvector's text form; :class:`VecError` when its length is not ``dim`` or a value is not finite."""
    if len(vec) != dim:
        raise VecError(f"a vector of {len(vec)} values where the embedder's dimension is {dim}")
    vals = [float(v) for v in vec]
    if not all(math.isfinite(v) for v in vals):
        raise VecError("a vector holds a value that is not finite")
    return "[" + ",".join(repr(v) for v in vals) + "]"


def search_sql(model: str, dim: int, k: int, by_patient: bool) -> str:
    """The query of :meth:`VecStore.search`. Its parameters: the query vector, then (``by_patient``) the patients,
    then the query vector again. The model, the dimension and ``k`` are literals (checked), so the planner matches
    the model's partial HNSW index, its predicate and its expression."""
    check_model(model)
    check_dim(dim)
    k = int(k)
    dist = f"(e.emb::public.halfvec({dim})) OPERATOR(public.<=>) ?::public.halfvec({dim})"
    cols = (
        "c.pid, c.did, c.chunk_no, c.note_date::text AS date, c.note_type AS type, c.start_char, c.end_char, "
        "c.text, c.sha"
    )
    if by_patient:  # exact: the patients' chunks through the btree on pid, no vector index needed
        return (
            f"SELECT {cols}, 1 - {dist} AS score FROM note_chunk c JOIN embedding e ON e.sha = c.sha "
            f"AND e.model = '{model}' AND e.dim = {dim} WHERE c.pid = ANY(?) "
            f"ORDER BY {dist}, c.did, c.chunk_no LIMIT {k}"
        )
    return (
        f"WITH near AS (SELECT e.sha, {dist} AS d FROM embedding e WHERE e.model = '{model}' "
        f"ORDER BY {dist} LIMIT {k}) "
        f"SELECT {cols}, 1 - near.d AS score FROM near JOIN note_chunk c ON c.sha = near.sha "
        f"ORDER BY near.d, c.did, c.chunk_no LIMIT {k}"
    )


class VecStore:
    """The ``vec`` schema of the trial database (D-126, D-439)."""

    def __init__(self, url: str | None = None, model: str | None = None, dim: int | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), STORE)
        self._db.migrate(list(MIGRATIONS))
        if model is not None and dim is not None:
            self.ensure_index(model, dim)

    @property
    def db(self) -> Database:
        return self._db

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> VecStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ schema
    def ensure_index(self, model: str, dim: int) -> str:
        """Make the model's HNSW index if it is missing; refuse a model whose stored vectors have another dimension."""
        ddl = index_ddl(model, dim)
        with self._db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema() || '.vec_index'))")
            other = tx.fetchval("SELECT dim FROM embedding WHERE model = ? AND dim <> ? LIMIT 1", (model, dim))
            if other is not None:
                raise VecError(f"model {model!r} has vectors of dimension {other} in the store, not {dim}")
            tx.execute(ddl)
        return index_name(model)

    def indexes(self) -> dict[str, str]:
        """``{index name: definition}`` of the ``embedding`` table."""
        rows = self._db.fetchall(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'embedding'"
        )
        return {str(r[0]): str(r[1]) for r in rows}

    # ------------------------------------------------------------------ writing
    def have(self, shas: Iterable[str], model: str) -> set[str]:
        """The shas among ``shas`` that already have a vector of ``model``."""
        want = sorted(set(shas))
        if not want:
            return set()
        rows = self._db.fetchall("SELECT sha FROM embedding WHERE model = ? AND sha = ANY(?)", (model, want))
        return {str(r[0]) for r in rows}

    def put_vectors(self, model: str, dim: int, vectors: dict[str, Sequence[float]]) -> int:
        """Store new vectors (sha -> vector); a sha the store has for this model is left as it is. Returns how many
        were written."""
        check_model(model)
        check_dim(dim)
        rows = [(sha, model, dim, literal(v, dim)) for sha, v in sorted(vectors.items())]
        if not rows:
            return 0
        n = 0
        with self._db.transaction() as tx:
            other = tx.fetchval("SELECT dim FROM embedding WHERE model = ? AND dim <> ? LIMIT 1", (model, dim))
            if other is not None:
                raise VecError(f"model {model!r} has vectors of dimension {other} in the store, not {dim}")
            for r in rows:
                n += tx.execute(
                    "INSERT INTO embedding (sha, model, dim, emb) VALUES (?, ?, ?, ?::public.halfvec) "
                    "ON CONFLICT (sha, model) DO NOTHING",
                    r,
                )
        return n

    def replace_notes(self, chunks: Sequence[ChunkRow], dids: Iterable[str]) -> int:
        """Replace the chunks of the notes ``dids`` (all of them, in one transaction) by ``chunks``."""
        ids = sorted(set(dids) | {c.did for c in chunks})
        with self._db.transaction() as tx:
            if ids:
                tx.execute("DELETE FROM note_chunk WHERE did = ANY(?)", (ids,))
            if chunks:
                tx.executemany(
                    "INSERT INTO note_chunk (pid, did, chunk_no, note_date, note_type, start_char, end_char, text, "
                    "sha, mask_version) VALUES (?, ?, ?, ?::date, ?, ?, ?, ?, ?, ?)",
                    [astuple(c) for c in chunks],
                )
        return len(chunks)

    # ------------------------------------------------------------------ reading (T-203b, T-203c)
    def chunks(self, pid: str) -> list[dict[str, Any]]:
        """A patient's chunks, by date, note and number."""
        return self._db.fetchdicts(
            "SELECT pid, did, chunk_no, note_date::text AS date, note_type AS type, start_char, end_char, text, sha, "
            "mask_version FROM note_chunk WHERE pid = ? ORDER BY note_date NULLS FIRST, did, chunk_no",
            (pid,),
        )

    def search(
        self, vector: Sequence[float], model: str, k: int = 10, pids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        """The ``k`` chunks nearest ``vector`` (cosine), best first, each with ``score`` = 1 - cosine distance.

        With ``pids`` (S2b: one patient's notes), the chunks of those patients are ranked exactly; the caller's scope
        check (``permit``) decides ``pids`` before this call. Without, the model's HNSW index ranks the whole store
        (T-203c filters by scope before it calls). Ties are broken by note and chunk number."""
        check_model(model)
        dim = check_dim(len(vector))
        q = literal(vector, dim)
        if k <= 0 or (pids is not None and not pids):
            return []
        text = search_sql(model, dim, k, by_patient=pids is not None)
        params = (q, sorted(set(pids)), q) if pids is not None else (q, q)
        return self._db.fetchdicts(text, params)

    def counts(self) -> dict[str, int]:
        return {
            "chunks": int(self._db.fetchval("SELECT count(*) FROM note_chunk")),
            "embeddings": int(self._db.fetchval("SELECT count(*) FROM embedding")),
            "patients": int(self._db.fetchval("SELECT count(DISTINCT pid) FROM note_chunk")),
        }

    # ------------------------------------------------------------------ erasure (T-206b)
    def delete_patient(self, pid: str) -> dict[str, int]:
        """Remove a patient from the store in one transaction: their chunks, and every vector no other chunk uses.
        Returns ``{"chunks": n, "embeddings": m}``."""
        with self._db.transaction() as tx:
            deleted = tx.fetchall("DELETE FROM note_chunk WHERE pid = ? RETURNING sha", (pid,))
            shas = sorted({str(r[0]) for r in deleted})
            gone: list[tuple[Any, ...]] = []
            if shas:
                gone = tx.fetchall(
                    "DELETE FROM embedding e WHERE e.sha = ANY(?) AND NOT EXISTS "
                    "(SELECT 1 FROM note_chunk c WHERE c.sha = e.sha) RETURNING e.sha",
                    (shas,),
                )
        return {"chunks": len(deleted), "embeddings": len(gone)}
