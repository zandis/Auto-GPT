"""Notes into the vector store (T-203a, D-439): the PHI pass, the chunker, one embedding per text and model.

    stats = index_notes(store, notes, embedder, mrn_regex=site_mrn_regex())

Each note is masked first (``tb_common.phi_guard.mask_note``, T-600, D-337): names, phone numbers, chart numbers and
ID numbers never reach a chunk, the ``note_chunk`` table or the embedder's input. Masking keeps the length, so the
chunk offsets index the original note. Only the chunk texts whose sha has no vector of the embedder's model are
embedded; every vector must have the embedder's dimension (``embedder.dim``: the embedder's own setting, D-429),
checked before anything is written. A note indexed again has its chunks replaced.

The store is any object with :class:`Store`'s methods: :class:`vec.store.VecStore` on the box's db image, a fake in
the unit tests (the stock PostgreSQL of the test cluster has no pgvector).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from embed_service.embedder import Embedder
from tb_common.phi_guard import NOTE_MASK_VERSION, mask_note

from vec.chunker import OVERLAP, SIZE, chunk_note
from vec.store import ChunkRow, VecError, check_dim, check_model

BATCH = 64  # texts per embedder call, as the lake and the HTTP client


@dataclass(frozen=True)
class Note:
    pid: str
    did: str
    text: str
    date: str | None = None  # ISO date
    type: str | None = None


@dataclass(frozen=True)
class IndexStats:
    notes: int
    chunks: int
    embedded_new: int


class Store(Protocol):
    def ensure_index(self, model: str, dim: int) -> str: ...

    def have(self, shas: Iterable[str], model: str) -> set[str]: ...

    def put_vectors(self, model: str, dim: int, vectors: dict[str, Sequence[float]]) -> int: ...

    def replace_notes(self, chunks: Sequence[ChunkRow], dids: Iterable[str]) -> int: ...


def note_chunks(note: Note, mrn_regex: str | None = None, size: int = SIZE, overlap: int = OVERLAP) -> list[ChunkRow]:
    """The rows of one note: chunks of its masked text, with offsets into the note."""
    masked = mask_note(note.text or "", mrn_regex, model_input=True)
    return [
        ChunkRow(note.pid, note.did, c.no, note.date, note.type, c.start, c.end, c.text, c.sha, NOTE_MASK_VERSION)
        for c in chunk_note(masked, size, overlap)
    ]


def embed_missing(store: Store, texts: dict[str, str], embedder: Embedder) -> int:
    """Embed the texts (sha -> masked text) that have no vector of the embedder's model; return how many."""
    model, dim = check_model(embedder.model), check_dim(embedder.dim)
    have = store.have(texts, model)
    missing = sorted(s for s in texts if s not in have)
    n = 0
    for i in range(0, len(missing), BATCH):
        batch = missing[i : i + BATCH]
        vecs = embedder.embed([texts[s] for s in batch])
        if len(vecs) != len(batch):
            raise VecError(f"the embedder returned {len(vecs)} vectors for {len(batch)} texts")
        bad = sorted({len(v) for v in vecs} - {dim})
        if bad:
            raise VecError(f"the embedder {model!r} returned vectors of {bad} values; its dimension is {dim}")
        n += store.put_vectors(model, dim, dict(zip(batch, vecs, strict=True)))
    return n


def index_notes(
    store: Store, notes: Iterable[Note], embedder: Embedder, mrn_regex: str | None = None, batch_notes: int = 500
) -> IndexStats:
    """Mask, chunk, embed and store ``notes``, ``batch_notes`` at a time (vectors first, then the notes' chunks)."""
    store.ensure_index(check_model(embedder.model), check_dim(embedder.dim))
    n_notes = n_chunks = n_new = 0
    pending: list[Note] = []

    def flush() -> None:
        nonlocal n_notes, n_chunks, n_new
        if not pending:
            return
        latest = {n.did: n for n in pending}  # a note given twice: its last text wins
        rows = [r for note in latest.values() for r in note_chunks(note, mrn_regex)]
        n_new += embed_missing(store, {r.sha: r.text for r in rows}, embedder)
        n_chunks += store.replace_notes(rows, list(latest))
        n_notes += len(latest)
        pending.clear()

    for note in notes:
        pending.append(note)
        if len(pending) >= batch_notes:
            flush()
    flush()
    return IndexStats(n_notes, n_chunks, n_new)


SNAPSHOT_NOTES_SQL = """
SELECT pid, did, CAST(date AS DATE) AS d, type, text FROM document WHERE did > $1 ORDER BY did LIMIT {page}
"""


def snapshot_notes(lake: Any, snapshot: str, exclude: Iterable[str] = (), page: int = 2000) -> Iterator[Note]:
    """The notes of a lake snapshot (its ``document`` table, the original text: masked by :func:`note_chunks`), a page
    at a time by note id. Patients in ``exclude`` (the opt-out register, D-147) are never read into the store."""
    gone = frozenset(exclude)
    last = ""
    while True:
        rows = lake.query(SNAPSHOT_NOTES_SQL.format(page=int(page)), [last], snapshot).to_pylist()
        if not rows:
            return
        for r in rows:
            if str(r["pid"]) not in gone:
                yield Note(str(r["pid"]), str(r["did"]), str(r["text"] or ""), r["d"].isoformat() if r["d"] else None,
                           r["type"])  # fmt: skip
        last = str(rows[-1]["did"])


def index_snapshot(
    store: Store,
    lake: Any,
    snapshot: str,
    embedder: Embedder,
    exclude: Iterable[str] = (),
    mrn_regex: str | None = None,
) -> IndexStats:
    """Index every note of ``snapshot`` (T-203b, D-449: the night's job after the lake rebuild), skipping the patients
    in ``exclude``. A note already indexed with the same text costs no embedding (one vector per sha); a note whose
    text changed has its chunks replaced, so S2b on that snapshot reads its vectors."""
    return index_notes(store, snapshot_notes(lake, snapshot, exclude), embedder, mrn_regex)
