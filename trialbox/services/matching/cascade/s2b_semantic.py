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

import hashlib
import math
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

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


def cosines(q: Any, rows: Any) -> Any:
    """:func:`cosine` of ``q`` with each row of ``rows``, in numpy (D-912): the same formula, a zero vector's norm
    read as 1."""
    q = np.asarray(q, dtype=np.float64)
    m = np.asarray(rows, dtype=np.float64).reshape(-1, q.shape[0])
    dq = float(np.sqrt(q @ q)) or 1.0
    dm = np.sqrt(np.einsum("ij,ij->i", m, m))
    dm[dm == 0.0] = 1.0
    return (m @ q) / (dm * dq)


class SentenceVectors:
    """The vectors of one run's sentences, by the embedder's model and the text's hash (D-912): a SCREEN run embeds a
    patient's window sentences once, not once per zero-hit criterion, and the two-phase rounds (``twophase``) share
    them. A vector is kept as the embedder gave it (float32 when that loses nothing, as a model's output; float64
    otherwise), so a vector read back is the vector embedded. ``sent``: texts sent to the embedder; ``hits``: texts
    answered from here."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()
        self.sent = 0
        self.hits = 0

    def __len__(self) -> int:
        return len(self._d)

    @staticmethod
    def _key(model: str, text: str) -> tuple[str, str]:
        return model, hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _keep(vec: Sequence[float]) -> Any:
        full = np.asarray(vec, dtype=np.float64)
        small = full.astype(np.float32)
        return small if np.array_equal(small.astype(np.float64), full) else full

    def matrix(self, embedder: Embedder, texts: list[str]) -> Any:
        """The vectors of ``texts`` (rows, float64), embedding in one call only the texts not seen under this model.
        A model that changes during the call (the embed service restarted on other weights) is never mixed with
        vectors of the one before: every text is embedded again under the new model."""
        model = str(embedder.model)
        with self._lock:
            missing = list(dict.fromkeys(t for t in texts if self._key(model, t) not in self._d))
        if missing:
            got = embedder.embed(missing)
            now = str(embedder.model)
            if now != model:
                model, missing, got = now, list(dict.fromkeys(texts)), embedder.embed(list(dict.fromkeys(texts)))
            with self._lock:
                self.sent += len(missing)
                for t, v in zip(missing, got, strict=True):
                    self._d[self._key(model, t)] = self._keep(v)
        with self._lock:
            self.hits += len(texts) - len(missing)
            rows = [self._d[self._key(model, t)] for t in texts]
        return np.stack([r.astype(np.float64) for r in rows]) if rows else np.zeros((0, 0))


def screen(
    embedder: Embedder,
    query: str,
    sentences: list[str],
    threshold: Threshold,
    k: int = 5,
    vectors: SentenceVectors | None = None,
) -> S2bResult:
    """One batch: the query and every window sentence are embedded together; with ``vectors`` (D-912) only those the
    run has not embedded yet. Similarities in numpy."""
    if not sentences:
        return S2bResult(False, 0.0, threshold, [])
    texts = [query, *sentences]
    vecs = vectors.matrix(embedder, texts) if vectors is not None else np.asarray(embedder.embed(texts), np.float64)
    sims = sorted(enumerate(float(x) for x in cosines(vecs[0], vecs[1:])), key=lambda t: (-t[1], t[0]))
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
    "SentenceVectors",
    "SourceFallback",
    "SourceNote",
    "SourceRanking",
    "Threshold",
    "ThresholdTable",
    "cosine",
    "cosines",
    "screen",
]
