"""D-911: the embed service holds its memory whatever it is sent.

The note-processing review of lane G's SCREEN run (2026-11-15) found a sentence of any length reaching the embedder (a
pathology line with no punctuation is one sentence), cut at the token cap so its tail was never read. Now:

* a text over ``TB_EMBED_INPUT_CAP`` tokens is embedded as consecutive windows within the cap, and its vector is the
  normalised mean of theirs; a text within the cap keeps the vector it always had;
* every encode call holds at most ``TB_EMBED_BATCH_BUDGET`` padded tokens, whatever the count of texts;
* requests encode one at a time, and the model is loaded once, at start, in every environment.

Synthetic, no model: a stand-in sentence-transformers with a whitespace tokenizer and the hash stub's vectors.
"""

from __future__ import annotations

import math
import re
import sys
import threading
import time
import types
from typing import Any, ClassVar

import pytest
from embed_service import app as service
from embed_service import embedder as emb
from tb_contracts import EmbedRequest

_WORD = re.compile(r"\S+")


class _Tokenizer:
    """One token per run of non-blanks; a fast tokenizer's offsets; two special tokens per input."""

    def __call__(self, texts: list[str], **kw: Any) -> dict[str, Any]:
        spans = [[m.span() for m in _WORD.finditer(t)] for t in texts]
        out: dict[str, Any] = {"input_ids": [list(range(len(s))) for s in spans]}
        if kw.get("return_offsets_mapping"):
            out["offset_mapping"] = spans
        return out

    def num_special_tokens_to_add(self, pair: bool = False) -> int:
        return 2


class _ST:
    """Records what each encode call holds; vectors are the hash stub's (unit length, deterministic)."""

    loads = 0
    calls: ClassVar[list[list[str]]] = []
    inside = 0
    most = 0
    lock = threading.Lock()

    def __init__(self, *a: Any, **k: Any) -> None:
        type(self).loads += 1
        time.sleep(0.1)  # a slow load: requests that arrive meanwhile must wait for it, not start their own
        self.tokenizer = _Tokenizer()
        self.max_seq_length = 8192

    def get_sentence_embedding_dimension(self) -> int:
        return emb.DIM

    def encode(self, texts: list[str], **kw: Any) -> list[list[float]]:
        cls = type(self)
        with cls.lock:
            cls.inside += 1
            cls.most = max(cls.most, cls.inside)
            cls.calls.append(list(texts))
        time.sleep(0.01)
        with cls.lock:
            cls.inside -= 1
        return emb.HashEmbedder().embed(texts)


def _tokens(text: str) -> int:
    return len(_WORD.findall(text))


@pytest.fixture
def st(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    _ST.loads, _ST.calls, _ST.inside, _ST.most = 0, [], 0, 0
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_ST))
    monkeypatch.setattr(emb, "check_folder", lambda p: [])
    monkeypatch.delenv("TB_EMBED_INPUT_CAP", raising=False)
    monkeypatch.delenv("TB_EMBED_BATCH_BUDGET", raising=False)
    monkeypatch.delenv("TB_EMBED_CONCURRENCY", raising=False)
    monkeypatch.setattr(service, "_embedder", None)
    monkeypatch.setattr(service, "_gate", None)
    monkeypatch.setattr(service, "service_embedder", lambda: emb.LocalEmbedder(str(tmp_path)))
    return _ST


def _long_sentence(chars: int) -> str:
    words = ["tumour", "margin", "clear", "lymph", "node", "negative", "grade", "2", "ER+", "PR-", "HER2", "1+"]
    out: list[str] = []
    size = -1  # the joined length: the words and one blank between each two
    while size < chars:
        out.append(words[len(out) % len(words)] + str(len(out) // len(words)))
        size += len(out[-1]) + 1
    text = " ".join(out)[:chars]
    return text[:-1] + "x" if text.endswith(" ") else text  # ends on a word, as a line of a report does


# ------------------------------------------------------------------------------------------- a 50,000-character text
def test_a_50000_character_sentence_is_embedded_in_windows_within_the_cap(st: Any) -> None:
    text = _long_sentence(50_000)
    assert len(text) == 50_000 and "." not in text  # one sentence, no full stop
    got = service.embed(EmbedRequest(texts=[text, "Gout flare of the left toe."]))
    assert len(got.vectors) == 2 and all(len(v) == emb.DIM for v in got.vectors)
    assert math.isclose(math.sqrt(sum(x * x for x in got.vectors[0])), 1.0, rel_tol=1e-9)
    e = service.embedder()
    assert isinstance(e, emb.LocalEmbedder) and e.max_tokens == emb.MAX_TOKENS and e.budget == emb.BATCH_TOKENS
    pieces = [p for call in st.calls for p in call]  # in the order of the batches (by length)
    windows = [w for w, _ in e._windows(text)]  # in the text's order
    assert sorted(windows) == sorted(p for p in pieces if p != "Gout flare of the left toe.")
    assert len(windows) == math.ceil(_tokens(text) / (emb.MAX_TOKENS - 2)) > 10
    # every window within the cap (its special tokens counted), every call within the budget
    assert all(_tokens(w) + 2 <= emb.MAX_TOKENS for w in windows)
    for call in st.calls:
        assert max(_tokens(p) + 2 for p in call) * len(call) <= emb.BATCH_TOKENS
    # the windows are the whole text, in order: nothing is cut off any more
    assert "".join(windows).replace(" ", "") == text.replace(" ", "")
    assert " ".join(windows) == text
    # the vector is the normalised mean of the windows' vectors
    assert got.vectors[0] == pytest.approx(emb.mean_vector(emb.HashEmbedder().embed(windows)))


def test_a_text_within_the_cap_keeps_its_vector(st: Any) -> None:
    texts = ["Gout flare of the left toe.", "Uric acid 9.1 mg/dL.", _long_sentence(2_000)]
    assert all(_tokens(t) + 2 <= emb.MAX_TOKENS for t in texts)
    got = service.embed(EmbedRequest(texts=texts))
    assert got.vectors == emb.HashEmbedder().embed(texts)  # embedded as it is: the same vector as before D-911
    assert sorted(p for call in st.calls for p in call) == sorted(texts)


def test_the_mean_not_the_first_window(st: Any) -> None:
    """A long text's vector reads its tail too: the cut it replaces kept the first window only."""
    head, tail = _long_sentence(6_000), " ".join(["colchicine"] * 600)
    e = service.embedder()
    assert isinstance(e, emb.LocalEmbedder)
    whole = e.embed([head + " " + tail])[0]
    first = emb.HashEmbedder().embed([e._windows(head + " " + tail)[0][0]])[0]
    probe = emb.HashEmbedder().embed(["colchicine"])[0]

    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cos(whole, probe) > 0.5 > cos(first, probe)


def test_a_tokenizer_without_offsets_still_cuts_by_tokens(monkeypatch: pytest.MonkeyPatch, st: Any) -> None:
    class Plain(_Tokenizer):  # a slow tokenizer: no offsets, a decoder
        def __call__(self, texts: list[str], **kw: Any) -> dict[str, Any]:
            if kw.get("return_offsets_mapping"):
                raise NotImplementedError("return_offset_mapping is not available when using Python tokenizers")
            self.last = texts[0]
            return {"input_ids": [list(range(_tokens(t))) for t in texts]}

        def decode(self, ids: list[int]) -> str:
            return " ".join(_WORD.findall(self.last)[ids[0] : ids[-1] + 1])

    e = service.embedder()
    assert isinstance(e, emb.LocalEmbedder)
    e._st.tokenizer = Plain()
    text = _long_sentence(20_000)
    windows = [w for w, _ in e._windows(text)]
    assert " ".join(windows) == text and all(_tokens(w) + 2 <= emb.MAX_TOKENS for w in windows)


# ------------------------------------------------------------------------------------------- tokens, not texts
def test_many_short_texts_are_batched_by_tokens(st: Any) -> None:
    texts = [f"note sentence number {i} with a few words" for i in range(1000)]
    service.embed(EmbedRequest(texts=texts))
    assert sum(len(c) for c in st.calls) == 1000
    assert all(max(_tokens(p) + 2 for p in c) * len(c) <= emb.BATCH_TOKENS for c in st.calls)
    assert max(len(c) for c in st.calls) > 64  # more than the old fixed 64 when they are short


def test_the_client_cuts_requests_by_characters() -> None:
    parts = emb.request_parts(["a" * 60_000, "b" * 60_000, "c", "d" * 200_000, *(["e"] * 130)])
    assert [len(p) for p in parts] == [1, 2, 1, 64, 64, 2]  # in order, each text once
    assert [t for p in parts for t in p][:4] == ["a" * 60_000, "b" * 60_000, "c", "d" * 200_000]
    for p in parts:
        assert len(p) <= emb.REQUEST_TEXTS and (sum(map(len, p)) <= emb.REQUEST_CHARS or len(p) == 1)


# ------------------------------------------------------------------------------------------- one at a time, one load
def test_concurrent_requests_load_once_and_encode_one_at_a_time(st: Any) -> None:
    text = _long_sentence(50_000)
    errors: list[BaseException] = []
    out: list[tuple[int, Any]] = []

    def call(i: int) -> None:
        try:
            out.append((i, service.embed(EmbedRequest(texts=[text if i % 2 else f"short text {i}", f"other {i}"]))))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=call, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(out) == 8
    assert st.loads == 1 and st.most == 1  # one model in memory; one batch of activations at a time
    # the same text gives the same vector whichever request it came in, and alone
    longs = [r.vectors[0] for i, r in out if i % 2]
    assert len(longs) == 4 and all(v == longs[0] for v in longs)
    assert longs[0] == service.embed(EmbedRequest(texts=[text])).vectors[0]


def test_the_model_is_loaded_at_start_in_every_environment(st: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    for env in ("DEV", "TEST", "VALIDATION"):
        monkeypatch.setenv("TB_ENV", env)
        monkeypatch.setattr(service, "_embedder", None)
        before = st.loads
        with TestClient(service.app):
            assert service._embedder is not None and st.loads == before + 1  # loaded before any request
        assert st.loads == before + 1


def test_the_defaults_fit_a_4_gb_limit() -> None:
    """D-911: one batch at the cap and the budget, beside the weights and runtime (about 2.9 GB, D-900), stays inside a
    4 GB limit by the review's estimate: 16 heads x L^2 x 4 bytes of attention per input, twice (scores and softmax),
    and the 4,096-wide feed-forward layer per token."""
    from tb_common.config import DECLARED

    cap, budget = int(DECLARED["TB_EMBED_INPUT_CAP"].default), int(DECLARED["TB_EMBED_BATCH_BUDGET"].default)
    assert (cap, budget) == (emb.MAX_TOKENS, emb.BATCH_TOKENS)
    per_batch = (budget // cap) * 16 * cap * cap * 4 * 2 + budget * 4096 * 4
    assert 2.9e9 + per_batch < 3.5e9 < 4e9
