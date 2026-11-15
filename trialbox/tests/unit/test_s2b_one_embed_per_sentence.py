"""D-912: S2b embeds each distinct sentence once per run, and compares them in numpy.

S2b embedded ``[query, *every window sentence]`` for each zero-hit (patient, criterion) pair, so a patient's sentences
were embedded again for every zero-hit criterion, and again in every round of a two-phase run; the cosine was pure
Python. Now a run keeps its vectors by model and text hash (:class:`SentenceVectors`), shared across the rounds, and
the similarities are numpy's. The vectors and the scores are the same; the requests are fewer. The end-to-end check on
the synthetic site is in ``test_cascade_pipeline.py``.
"""

from __future__ import annotations

import math

import numpy as np
from embed_service.embedder import HashEmbedder
from matching.cascade.s2b_semantic import SentenceVectors, Threshold, cosine, cosines, screen

THR = Threshold(0.1, "public_prior", "inclusion|en")
SENTS = [
    "Gout flare of the left first MTP joint.",
    "Uric acid 9.1 mg/dL.",
    "Colchicine started.",
    "No tophi seen.",
    "Gout flare of the left first MTP joint.",  # the same sentence twice in one window (a copied-forward note)
    "",
]


class Counting:
    """The hash stub, counting what it is sent; ``model`` can be changed to stand for a service restarted."""

    def __init__(self, model: str = "hash-1024-v1") -> None:
        self.model = model
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return HashEmbedder().embed(texts)

    @property
    def sent(self) -> int:
        return sum(len(c) for c in self.calls)


class Float32:
    """A model's vectors: float32 values (a service's output), not unit length."""

    model = "e-embed-1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(np.float32(x * 3.0)) for x in v] for v in HashEmbedder().embed(texts)]


def test_the_vectors_are_the_ones_embedded() -> None:
    kept = {}
    for e in (HashEmbedder(), Float32()):
        memo = SentenceVectors()
        texts = ["query", *SENTS]
        direct = np.asarray(e.embed(texts), dtype=np.float64)
        assert np.array_equal(memo.matrix(e, texts), direct)  # embedded through the memo
        assert np.array_equal(memo.matrix(e, texts), direct)  # read back from it
        kept[e.model] = {v.dtype for v in memo._d.values()}
    # a model's float32 output is kept at 4 bytes a value; the stub's float64 values as they are (float32 only where
    # that loses nothing, as for the empty sentence's zero vector)
    assert kept["e-embed-1"] == {np.dtype(np.float32)} and np.dtype(np.float64) in kept["hash-1024-v1"]


def test_the_scores_are_the_same_with_and_without_the_memo() -> None:
    memo = SentenceVectors()
    for query in ("gout flare", "uric acid level", "tophus"):
        plain = screen(Counting(), query, SENTS, THR)
        kept = screen(Counting(), query, SENTS, THR, vectors=memo)
        again = screen(Counting(), query, SENTS, THR, vectors=memo)
        assert plain == kept == again
        # numpy's similarities are the pure-Python ones, in the same order
        vecs = HashEmbedder().embed([query, *SENTS])
        ref = sorted(((i, cosine(vecs[0], v)) for i, v in enumerate(vecs[1:])), key=lambda t: (-t[1], t[0]))
        assert [i for i, _ in plain.top] == [i for i, _ in ref[:5]]
        assert all(math.isclose(a, b, rel_tol=0, abs_tol=1e-12) for (_, a), (_, b) in zip(plain.top, ref, strict=False))


def test_each_sentence_is_sent_once_per_run() -> None:
    queries = [f"criterion {i} question" for i in range(4)]  # four zero-hit criteria of one patient
    without, with_memo = Counting(), Counting()
    memo = SentenceVectors()
    for q in queries:
        screen(without, q, SENTS, THR)
        screen(with_memo, q, SENTS, THR, vectors=memo)
    assert without.sent == 4 * (1 + len(SENTS))
    assert with_memo.sent == len(set(SENTS)) + 4  # each distinct sentence once, each query once
    assert memo.sent == with_memo.sent and memo.hits == without.sent - with_memo.sent
    # the second round of a two-phase run: nothing is sent again
    before = with_memo.sent
    for q in queries:
        screen(with_memo, q, SENTS, THR, vectors=memo)
    assert with_memo.sent == before


def test_vectors_of_two_models_are_never_mixed() -> None:
    e = Counting("model-a")
    memo = SentenceVectors()
    memo.matrix(e, SENTS[:3])

    class Restarted(Counting):  # the service answers under another model from this call on
        def embed(self, texts: list[str]) -> list[list[float]]:
            self.model = "model-b"
            return super().embed(texts)

    r = Restarted("model-a")
    got = memo.matrix(r, ["new sentence", *SENTS[:3]])
    assert r.model == "model-b" and r.calls[-1] == ["new sentence", *SENTS[:3]]  # all embedded again, model b
    assert got.shape == (4, 1024)
    assert len({k[0] for k in memo._d}) == 2


def test_numpy_cosines_match_the_pure_python_one() -> None:
    rng = np.random.default_rng(912)
    q = rng.normal(size=16)
    rows = rng.normal(size=(5, 16))
    rows[2] = 0.0  # a zero vector: its norm read as 1, as cosine() does
    got = cosines(q, rows)
    for i in range(5):
        assert math.isclose(float(got[i]), cosine(list(q), list(rows[i])), rel_tol=1e-12, abs_tol=1e-15)
    assert float(cosines(np.zeros(16), rows[:1])[0]) == 0.0
