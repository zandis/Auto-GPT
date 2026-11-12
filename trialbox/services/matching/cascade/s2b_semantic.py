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


@dataclass(frozen=True)
class S2bResult:
    above: bool
    best: float
    threshold: Threshold
    top: list[tuple[int, float]]  # (sentence index, similarity), best first


def screen(embedder: Embedder, query: str, sentences: list[str], threshold: Threshold, k: int = 5) -> S2bResult:
    """One batch: the query and every window sentence are embedded together."""
    if not sentences:
        return S2bResult(False, 0.0, threshold, [])
    vecs = embedder.embed([query, *sentences])
    q, rest = vecs[0], vecs[1:]
    sims = sorted(((i, cosine(q, v)) for i, v in enumerate(rest)), key=lambda t: (-t[1], t[0]))
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
    "screen",
]
