"""S2b semantic screen of S2 zero-hit pairs (spec v4 §4.5, CAS-12, CAS-14, CAS-15).

The bilingual ``note_question`` (expanded with the approved lexicon terms, §6.11) is compared with the sentences of
the patient's notes inside the criterion window. The best cosine similarity decides: at or above the threshold the
pair goes to S3 with its top sentences as evidence; below it, absence semantics apply and the pair is logged in the
``S2b-below`` stratum.

Thresholds are per criterion type × language stratum. Until a stratum has ≥ 100 judged positives it uses the
public-prior threshold lowered by the site safety margin (CAS-14); the shipped prior is a placeholder until the LTT
fit on ``eval/criterion_ml`` exists (recorded as a deviation).

CAS-15 requires S2b to call embeddings through ``tb-gateway`` as one D3 batch per call. The gateway v0 exposes only
``/v1/chat/completions``, so the embedder is injected: :class:`BatchEmbedder` wraps any in-perimeter embedder
(``embed_service``) and counts one batch per call, ready to be swapped for the gateway embeddings client. It never
calls a generative model.

A :class:`SentenceSource` (T-203b, D-449) may rank the window's sentences from stored vectors instead (the vector
store of the trial database, read through the lake service). The cascade asks it only when the caller gives one (the
flag ``vec.s2b``) and only with absence semantics off; a :class:`SourceFallback` sends the pair to the on-the-fly
path above, and the trace says so per patient.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from tb_common.phi_guard import mask_names

#: public-prior similarity threshold (placeholder for the LTT fit) and the site safety margin (CAS-14)
PUBLIC_PRIOR_THRESHOLD = 0.12
SITE_SAFETY_MARGIN = 0.02
MIN_JUDGED_POSITIVES = 100


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class BatchEmbedder:
    """Counts embedding batches (one gateway audit record per batch, CAS-15) around an injected embedder."""

    inner: Embedder
    batches: int = 0
    texts: int = 0

    @property
    def model(self) -> str:
        return self.inner.model

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches += 1
        self.texts += len(texts)
        return self.inner.embed(texts)


@dataclass(frozen=True)
class Threshold:
    value: float
    source: str  # "public_prior" | "ltt_site"
    stratum: str


@dataclass
class ThresholdTable:
    """Per (criterion type, language stratum) thresholds; site LTT fits override the public prior (CAS-14)."""

    site: dict[str, tuple[float, int]] = field(default_factory=dict)  # stratum -> (threshold, judged positives)
    prior: float = PUBLIC_PRIOR_THRESHOLD
    margin: float = SITE_SAFETY_MARGIN

    def get(self, criterion_type: str, language: str) -> Threshold:
        key = f"{criterion_type}|{language}"
        fit = self.site.get(key)
        if fit is not None and fit[1] >= MIN_JUDGED_POSITIVES:
            return Threshold(fit[0], "ltt_site", key)
        return Threshold(self.prior - self.margin, "public_prior", key)


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


def cosines(q: Sequence[float], rows: Sequence[Sequence[float]]) -> list[float]:
    """:func:`cosine` of ``q`` with every row, in numpy (D-907): the same formula, a zero vector's norm read as 1. A
    zero-hit pair compares its query with every window of every note; a loop in Python was most of S2b's own time."""
    if not rows:
        return []
    qv = np.asarray(q, dtype=np.float64)
    m = np.asarray(rows, dtype=np.float64)
    dq = float(np.sqrt(qv @ qv)) or 1.0
    dm = np.sqrt(np.einsum("ij,ij->i", m, m))
    dm[dm == 0.0] = 1.0
    return [float(x) for x in (m @ qv) / (dm * dq)]


@dataclass(frozen=True)
class S2bResult:
    above: bool
    best: float
    threshold: Threshold
    top: list[tuple[int, float]]  # (sentence index, similarity), best first


# D-905 (lane G's review): an input longer than this many characters is embedded as overlapping windows and scored
# by its best window; the embed service cuts an input at its token cap, which would leave the end unscored
WINDOW_CHARS = 500
WINDOW_OVERLAP = 100
BOILERPLATE_NOTES = 3  # a sentence in this many notes of the window is boilerplate: not embedded


def windows(text: str, size: int = WINDOW_CHARS, overlap: int = WINDOW_OVERLAP) -> list[str]:
    """``text`` as overlapping windows of at most ``size`` characters (itself when it fits)."""
    if len(text) <= size:
        return [text]
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(len(text) - overlap, 1), step)]


def boilerplate(note_sentences: Sequence[Sequence[str]], min_notes: int = BOILERPLATE_NOTES) -> set[str]:
    """Sentences that recur in at least ``min_notes`` notes of the window (a template line, a disclaimer): they would
    rank every note alike, so S2b does not embed them. The judge still reads them."""
    count: dict[str, int] = {}
    for sents in note_sentences:
        for x in {s.strip() for s in sents if s.strip()}:
            count[x] = count.get(x, 0) + 1
    return {x for x, n in count.items() if n >= min_notes}


def screen(embedder: Embedder, query: str, sentences: list[str], threshold: Threshold, k: int = 5) -> S2bResult:
    """One batch: the query and every window sentence are embedded together; a long sentence as windows, scored by
    its best window."""
    if not sentences:
        return S2bResult(False, 0.0, threshold, [])
    pieces: list[tuple[int, str]] = [(i, w) for i, s in enumerate(sentences) for w in windows(mask_names(s))]
    vecs = embedder.embed([query, *(w for _, w in pieces)])
    score: dict[int, float] = {}
    for (i, _), c in zip(pieces, cosines(vecs[0], vecs[1:]), strict=True):
        score[i] = max(score.get(i, c), c)
    sims = sorted(score.items(), key=lambda t: (-t[1], t[0]))
    best = sims[0][1] if sims else 0.0
    return S2bResult(best >= threshold.value, best, threshold, sims[:k])


class SourceNote(Protocol):
    """A note of the S2b window as the cascade holds it: its id, its text in the pinned snapshot, its sentences."""

    @property
    def did(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def sents(self) -> list[str]: ...


@dataclass(frozen=True)
class SourceRanking:
    """A ranking from stored vectors: the best similarity, the top sentences (index into the window's sentences, in
    note then sentence order, and similarity; best first) and the embedding model of the vectors it compared."""

    best: float
    top: list[tuple[int, float]]
    model: str


@dataclass(frozen=True)
class SourceFallback:
    """The stored vectors cannot rank this pair (unavailable, stale for the pinned snapshot, another model, ...): the
    pair takes the on-the-fly path, and ``reason`` is recorded on the patient's trace."""

    reason: str


class SentenceSource(Protocol):
    def rank(self, pid: str, query: str, notes: Sequence[SourceNote], k: int) -> SourceRanking | SourceFallback: ...


__all__ = [
    "MIN_JUDGED_POSITIVES",
    "PUBLIC_PRIOR_THRESHOLD",
    "SITE_SAFETY_MARGIN",
    "BatchEmbedder",
    "Embedder",
    "S2bResult",
    "SentenceSource",
    "SourceFallback",
    "SourceNote",
    "SourceRanking",
    "Threshold",
    "ThresholdTable",
    "cosine",
    "cosines",
    "screen",
]
