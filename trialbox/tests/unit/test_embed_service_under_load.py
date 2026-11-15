"""Red of lane G's accuracy run (#639, 2026-11-15): the embed service died in the middle of a SCREEN job.

It served one protocol of 500 pathology reports at about 23 cores, single requests up to 33 s, then restarted and
loaded its model three times, once per request that arrived together, under a 4 GB limit for a 2.3 GB model. Now:

* the model is loaded once, under a lock, however many requests arrive together;
* the service encodes ``TB_EMBED_CONCURRENCY`` requests at a time (1 by default), each input cut at
  ``TB_EMBED_INPUT_CAP`` tokens, in batches of at most ``TB_EMBED_BATCH_BUDGET`` tokens rather than a fixed 64 texts;
* SCREEN embeds each sentence once: the client keeps the vectors it got, keyed by the model and the text's hash
  (``TB_EMBED_CACHE_VECTORS`` of them), so a patient's notes are not embedded again for every criterion and protocol.

Synthetic, no model: a stand-in tokenizer and a counting client.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from typing import Any

import pytest
from embed_service import app as service
from embed_service import embedder as emb


# ------------------------------------------------------------------------------------------- one load
def test_the_model_is_loaded_once_however_many_requests_arrive(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[int] = []

    def slow_load() -> Any:
        loads.append(1)
        time.sleep(0.2)
        return emb.HashEmbedder()

    monkeypatch.setattr(service, "_embedder", None)
    monkeypatch.setattr(service, "service_embedder", slow_load)
    got: list[Any] = []
    threads = [threading.Thread(target=lambda: got.append(service.embedder())) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(loads) == 1 and len({id(x) for x in got}) == 1


def test_requests_encode_one_at_a_time_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    inside, most = [0], [0]
    lock = threading.Lock()

    class Slow(emb.HashEmbedder):
        def embed(self, texts: list[str]) -> list[list[float]]:
            with lock:
                inside[0] += 1
                most[0] = max(most[0], inside[0])
            time.sleep(0.05)
            with lock:
                inside[0] -= 1
            return super().embed(texts)

    monkeypatch.setattr(service, "_embedder", Slow())
    monkeypatch.setattr(service, "_gate", None)
    monkeypatch.delenv("TB_EMBED_CONCURRENCY", raising=False)
    from tb_contracts import EmbedRequest

    threads = [threading.Thread(target=lambda: service.embed(EmbedRequest(texts=["a b c"]))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most[0] == 1


# ------------------------------------------------------------------------------------------- tokens, not 64 texts
def test_batches_are_sized_by_tokens_and_inputs_are_cut() -> None:
    lengths = [10, 600, 300, 300, 5, 5, 700]
    batches = emb.token_batches(lengths, max_tokens=512, budget=1024)
    assert sorted(i for b in batches for i in b) == list(range(len(lengths)))  # every input, once
    for b in batches:  # an input counts at most max_tokens; a batch holds at most the budget (or one input)
        assert sum(min(lengths[i], 512) for i in b) <= 1024 or len(b) == 1
    assert len(batches) >= 3


def test_the_local_embedder_cuts_inputs_at_the_token_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    calls: list[int] = []

    class FakeST:
        max_seq_length = 8192

        def __init__(self, *a: Any, **k: Any) -> None:
            self.tokenizer = lambda texts, **kw: {"input_ids": [list(range(min(len(t), 9999))) for t in texts]}

        def get_sentence_embedding_dimension(self) -> int:
            return 4

        def encode(self, texts: list[str], **kw: Any) -> list[list[float]]:
            calls.append(len(texts))
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeST))
    monkeypatch.setattr(emb, "check_folder", lambda p: [])
    monkeypatch.setenv("TB_EMBED_INPUT_CAP", "256")
    monkeypatch.setenv("TB_EMBED_BATCH_BUDGET", "512")
    e = emb.LocalEmbedder(str(tmp_path))
    assert e._st.max_seq_length == 256
    out = e.embed(["x" * 1000, "y" * 1000, "z" * 1000, "short"])
    assert len(out) == 4 and len(calls) >= 2 and max(calls) <= 2  # 256 + 256 per batch at most


# ------------------------------------------------------------------------------------------- the client's cache
class _Counting:
    model = "e-embed-1"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.sent += texts
        return [[float(len(t)), 1.0] for t in texts]


def test_screen_embeds_each_sentence_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios import screen_cascade as sc

    monkeypatch.setattr(sc, "_VECTORS", sc._VectorCache(100))
    inner = _Counting()
    served = sc._Served(inner)
    first = served.embed(["query one", "sentence a", "sentence b"])
    again = served.embed(["query two", "sentence a", "sentence b"])  # the next criterion on the same patient
    assert inner.sent == ["query one", "sentence a", "sentence b", "query two"]
    assert again[1:] == first[1:] and again[0] == [9.0, 1.0]
    other_job = sc._Served(_Counting())  # the next protocol: the same model, the same text, no new call
    other_job.embed(["sentence a"])
    assert other_job.inner.sent == []


def test_the_cache_is_bounded_and_keyed_by_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios import screen_cascade as sc

    cache = sc._VectorCache(2)
    cache.put("m1", "a", [1.0])
    cache.put("m1", "b", [2.0])
    cache.put("m1", "c", [3.0])
    assert cache.get("m1", "a") is None and cache.get("m1", "c") == [3.0]
    assert cache.get("m2", "c") is None  # another model never reads these vectors
    monkeypatch.setenv("TB_EMBED_CACHE_VECTORS", "7")
    assert sc._VectorCache.from_env().size == 7


def test_the_settings_are_declared() -> None:
    from tb_common.config import DECLARED

    for name in ("TB_EMBED_CONCURRENCY", "TB_EMBED_INPUT_CAP", "TB_EMBED_BATCH_BUDGET", "TB_EMBED_CACHE_VECTORS"):
        assert name in DECLARED, name
