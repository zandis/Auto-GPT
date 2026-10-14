"""TrialGPT-Retrieval (NCBI ``hybrid_fusion_retrieval.py``): BM25 + MedCPT dense retrieval per keyword, fused by
reciprocal rank with keyword-priority weights: score(t) = sum_i sum_ret 1 / ((rank_ret(i, t) + k) * (i + 1)).

Differences from the NCBI script, none of which change the ranking definition:
* MedCPT runs on CPU (``TG_DEVICE=cuda`` when there is a GPU) and encodes in batches;
* dense search is an exact inner product with numpy (NCBI used ``faiss.IndexFlatIP``, also exact);
* indexes are cached under ``data/index/<name>/``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from nltk import word_tokenize
from rank_bm25 import BM25Okapi

from trialgpt_local.config import settings

QUERY_MODEL = "ncbi/MedCPT-Query-Encoder"
ARTICLE_MODEL = "ncbi/MedCPT-Article-Encoder"


def bm25_tokens(doc: dict[str, Any]) -> list[str]:
    """NCBI weighting: 3 x title, 2 x each condition, 1 x text."""
    tokens: list[str] = word_tokenize(str(doc.get("title") or "").lower()) * 3
    for disease in (doc.get("metadata") or {}).get("diseases_list") or []:
        tokens += word_tokenize(str(disease).lower()) * 2
    tokens += word_tokenize(str(doc.get("text") or "").lower())
    return tokens


class _Encoders:
    _cache: ClassVar[dict[str, Any]] = {}

    @classmethod
    def get(cls, name: str) -> tuple[Any, Any]:
        if name not in cls._cache:
            from transformers import AutoModel, AutoTokenizer

            model = AutoModel.from_pretrained(name).to(settings().device).eval()
            cls._cache[name] = (AutoTokenizer.from_pretrained(name), model)
        return cls._cache[name]  # type: ignore[no-any-return]


def encode_articles(docs: Sequence[dict[str, Any]], batch: int = 16) -> np.ndarray:
    import torch

    tok, model = _Encoders.get(ARTICLE_MODEL)
    out = []
    for i in range(0, len(docs), batch):
        chunk = docs[i : i + batch]
        enc = tok(
            [[str(d.get("title") or ""), str(d.get("text") or "")] for d in chunk],
            truncation=True,
            padding=True,
            return_tensors="pt",
            max_length=512,
        ).to(settings().device)
        with torch.no_grad():
            out.append(model(**enc).last_hidden_state[:, 0, :].cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 768), dtype=np.float32)


def encode_queries(texts: Sequence[str]) -> np.ndarray:
    import torch

    tok, model = _Encoders.get(QUERY_MODEL)
    enc = tok(list(texts), truncation=True, padding=True, return_tensors="pt", max_length=256).to(settings().device)
    with torch.no_grad():
        return np.asarray(model(**enc).last_hidden_state[:, 0, :].cpu().numpy())


@dataclass
class HybridIndex:
    nctids: list[str]
    bm25: BM25Okapi
    embeds: np.ndarray
    docs: dict[str, dict[str, Any]]

    @classmethod
    def build(cls, docs: Iterable[dict[str, Any]], name: str | None = None, dense: bool = True) -> HybridIndex:
        """``docs``: corpus entries ``{"_id", "title", "text", "metadata"}``. With ``name`` the index is cached."""
        items = list(docs)
        nctids = [d["_id"] for d in items]
        cache = settings().data_dir / "index" / name if name else None
        sig = hashlib.sha256("\n".join(nctids).encode()).hexdigest()[:16]
        if cache and (cache / "meta.json").exists() and json.loads((cache / "meta.json").read_text())["sig"] == sig:
            tokens = json.loads((cache / "bm25_tokens.json").read_text())
            embeds = np.load(cache / "medcpt.npy") if dense else np.zeros((len(items), 768), dtype=np.float32)
        else:
            tokens = [bm25_tokens(d) for d in items]
            embeds = encode_articles(items) if dense else np.zeros((len(items), 768), dtype=np.float32)
            if cache:
                cache.mkdir(parents=True, exist_ok=True)
                (cache / "bm25_tokens.json").write_text(json.dumps(tokens))
                if dense:
                    np.save(cache / "medcpt.npy", embeds)
                (cache / "meta.json").write_text(json.dumps({"sig": sig, "n": len(items), "dense": dense}))
        return cls(nctids, BM25Okapi(tokens), embeds, {d["_id"]: d for d in items})

    def search(
        self, conditions: Sequence[str], n: int = 2000, k: int = 20, bm25_wt: int = 1, medcpt_wt: int = 1
    ) -> list[tuple[str, float]]:
        conditions = [c for c in conditions if str(c).strip()]
        if not conditions:
            return []
        n = min(n, len(self.nctids))
        scores: dict[str, float] = {}
        dense_top: list[list[int]] = []
        if medcpt_wt > 0 and self.embeds.size and np.any(self.embeds):
            q = encode_queries(conditions)
            sims = q @ self.embeds.T
            dense_top = [list(np.argsort(-row, kind="stable")[:n]) for row in sims]
        for ci, cond in enumerate(conditions):
            if bm25_wt > 0:
                bm = self.bm25.get_scores(word_tokenize(cond.lower()))
                for rank, idx in enumerate(np.argsort(-bm, kind="stable")[:n]):
                    t = self.nctids[int(idx)]
                    scores[t] = scores.get(t, 0.0) + (1 / (rank + k)) * (1 / (ci + 1))
            if dense_top:
                for rank, idx in enumerate(dense_top[ci]):
                    t = self.nctids[int(idx)]
                    scores[t] = scores.get(t, 0.0) + (1 / (rank + k)) * (1 / (ci + 1))
        return sorted(scores.items(), key=lambda x: -x[1])[:n]


def index_path(name: str) -> Path:
    return settings().data_dir / "index" / name
