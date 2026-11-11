"""S2b from the vector store (T-203b, D-449): the lake ranks the stored chunks, the cascade maps them to sentences.

    # in the lake service (role tb_lake, the only one that reads schema vec, D-378), for one patient's window notes:
    answer = rank_chunks(store, embedder, pid, notes_of_the_pinned_snapshot, query, mrn_regex)
    # in the orchestrator, the cascade's S2b source (flag vec.s2b):
    run_cascade(lake, rs, cfg, embedder=..., s2b_source=LakeVecSource(lake, snapshot))

**The vectors must be those of the pinned snapshot.** A job reads the snapshot it pinned (T-305a). The store keeps one
set of chunks per note, whatever night indexed it, so the lake checks each window note of the pinned snapshot against
the store: the note is masked and chunked again exactly as the indexer does (:func:`vec.index.note_chunks`), and its
chunks (number, offsets, sha, mask version) must be the stored ones. Chunks are content-addressed, so equal chunks
mean the vectors were made from this snapshot's text. A note missing from the store, a note whose text changed since
it was indexed, or a chunk without a vector of the model is a fallback for the pair: the cascade ranks it on the fly
as before and records why on the patient's trace. Nothing here can drop a pair or decide an exclusion.

**One model.** The query is embedded by the lake's embedder and compared only with vectors of that embedder's model
(``VecStore.search`` filters on the model and the dimension); the answer names the model, and the cascade refuses a
second model inside one patient's run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from embed_service.embedder import Embedder
from matching.cascade.s2b_semantic import SourceFallback, SourceNote, SourceRanking
from tb_common.phi_guard import NOTE_MASK_VERSION

from vec.index import Note, note_chunks
from vec.store import check_model

#: the fallback reasons a lake answer may carry (a fixed vocabulary: no note id, no text in a trace)
UNAVAILABLE = "vector store unavailable"
NOT_INDEXED = "a window note of the pinned snapshot is not in the vector store"
STALE = "a window note changed since it was indexed: the stored vectors are not this snapshot's"
NO_VECTOR = "a window chunk has no vector of the embedder's model"
NO_LAKE_READ = "the lake client offers no vector read"


class SearchStore(Protocol):
    def chunks(self, pid: str) -> list[dict[str, Any]]: ...

    def search(
        self, vector: Sequence[float], model: str, k: int = 10, pids: Sequence[str] | None = None
    ) -> list[dict[str, Any]]: ...


def fallback(reason: str) -> dict[str, Any]:
    return {"state": "fallback", "reason": reason}


def rank_chunks(
    store: SearchStore | None,
    embedder: Embedder,
    pid: str,
    notes: Sequence[Note],
    query: str,
    mrn_regex: str | None = None,
) -> dict[str, Any]:
    """Rank the stored chunks of ``notes`` (the window notes of one patient, as the pinned snapshot holds them) by
    cosine to ``query``. ``{"state": "vec", "model", "hits": [{did, chunk_no, start, end, score}, ...]}`` best first,
    every chunk of every note; else ``{"state": "fallback", "reason"}``."""
    if store is None:
        return fallback(UNAVAILABLE)
    model = check_model(embedder.model)
    stored: dict[str, list[tuple[int, int, int, str, str]]] = {}
    for r in store.chunks(pid):
        stored.setdefault(str(r["did"]), []).append(
            (int(r["chunk_no"]), int(r["start_char"]), int(r["end_char"]), str(r["sha"]), str(r["mask_version"]))
        )
    want: set[tuple[str, int]] = set()
    for note in notes:
        have = sorted(stored.get(note.did, []))
        expect = [(c.chunk_no, c.start, c.end, c.sha, NOTE_MASK_VERSION) for c in note_chunks(note, mrn_regex)]
        if have != expect:
            return fallback(STALE if have else NOT_INDEXED)
        want |= {(note.did, c[0]) for c in expect}
    if not want:
        return {"state": "vec", "model": model, "hits": []}
    qvec = embedder.embed([query])[0]
    total = sum(len(v) for v in stored.values())
    hits = [h for h in store.search(qvec, model, k=total, pids=[pid]) if (str(h["did"]), int(h["chunk_no"])) in want]
    if {(str(h["did"]), int(h["chunk_no"])) for h in hits} != want:
        return fallback(NO_VECTOR)
    return {
        "state": "vec",
        "model": model,
        "hits": [
            {
                "did": str(h["did"]),
                "chunk_no": int(h["chunk_no"]),
                "start": int(h["start_char"]),
                "end": int(h["end_char"]),
                "score": float(h["score"]),
            }
            for h in hits
        ],
    }


def sentence_spans(text: str, sents: Sequence[str]) -> list[tuple[int, int]] | None:
    """Where each of the cascade's sentences (stripped substrings of ``text``, in order) sits in ``text``; None when
    one is not found (never guessed)."""
    out: list[tuple[int, int]] = []
    pos = 0
    for s in sents:
        i = text.find(s, pos)
        if i < 0:
            return None
        out.append((i, i + len(s)))
        pos = i + len(s)
    return out


def sentence_ranking(
    hits: Sequence[dict[str, Any]], notes: Sequence[SourceNote], model: str, k: int = 5
) -> SourceRanking | SourceFallback:
    """The window's sentences ranked by the best stored chunk that overlaps each: the top ``k`` (index into the
    sentences of ``notes`` in order, score), ties by position, and the best score."""
    by_note: dict[str, list[tuple[int, int, float]]] = {}
    for h in hits:
        by_note.setdefault(str(h["did"]), []).append((int(h["start"]), int(h["end"]), float(h["score"])))
    scored: list[tuple[int, float]] = []
    i = 0
    for n in notes:
        spans = sentence_spans(n.text, n.sents)
        if spans is None:
            return SourceFallback("a window sentence was not found in its note")
        for s, e in spans:
            over = [sc for cs, ce, sc in by_note.get(n.did, []) if cs < e and s < ce]
            if not over:
                return SourceFallback("a window sentence lies outside every stored chunk")
            scored.append((i, max(over)))
            i += 1
    if not scored:
        return SourceFallback("no sentence in the window")
    ranked = sorted(scored, key=lambda t: (-t[1], t[0]))
    return SourceRanking(best=ranked[0][1], top=ranked[:k], model=model)


class VecReader(Protocol):
    def vec_s2b(self, pid: str, dids: list[str], query: str, snapshot: str | None = None) -> dict[str, Any]: ...


@dataclass
class LakeVecSource:
    """The cascade's S2b source (``matching.cascade.s2b_semantic.SentenceSource``) over the lake's vector read, on
    the job's pinned snapshot. Built only when the flag ``vec.s2b`` is on."""

    lake: Any
    snapshot: str | None
    down: str | None = None  # an unavailable store is not asked again in this run: every later pair falls back

    def rank(self, pid: str, query: str, notes: Sequence[SourceNote], k: int) -> SourceRanking | SourceFallback:
        if self.down is not None:
            return SourceFallback(self.down)
        read = getattr(self.lake, "vec_s2b", None)
        if read is None:
            return SourceFallback(NO_LAKE_READ)
        answer = read(pid, sorted({n.did for n in notes}), query, self.snapshot)
        if answer.get("state") != "vec":
            reason = str(answer.get("reason") or UNAVAILABLE)
            if reason.startswith(UNAVAILABLE):
                self.down = reason
            return SourceFallback(reason)
        return sentence_ranking(answer.get("hits") or [], notes, str(answer["model"]), k)


__all__ = [
    "NOT_INDEXED",
    "NO_LAKE_READ",
    "NO_VECTOR",
    "STALE",
    "UNAVAILABLE",
    "LakeVecSource",
    "SearchStore",
    "VecReader",
    "fallback",
    "rank_chunks",
    "sentence_ranking",
    "sentence_spans",
]
