"""Dense text embeddings (SPEC §4.7): bge-m3 (1024-d) in production, deterministic feature hashing in CPU CI (D-12)."""

from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol

DIM = 1024


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Signed feature hashing of CJK bigrams + Latin tokens into 1024 dims, L2-normalised. Deterministic."""

    model = "hash-1024-v1"
    dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        from lake.textproc import tokens

        out = []
        for text in texts:
            vec = [0.0] * DIM
            for tok in tokens(text):
                h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % DIM
                vec[idx] += 1.0 if h[4] & 1 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class BgeM3Embedder:
    """BAAI/bge-m3 dense vectors via sentence-transformers; weights from the offline models/ volume."""

    model = "bge-m3"
    dim = DIM

    def __init__(self, path: str, batch_size: int = 64) -> None:
        from sentence_transformers import SentenceTransformer

        self._st = SentenceTransformer(path, device=os.environ.get("TB_EMBED_DEVICE", "cpu"))
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._st.encode(texts, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vecs]


class HttpEmbedder:
    """Client for embed-service ``POST /embed``."""

    def __init__(self, base_url: str, model: str = "remote", timeout: float = 300) -> None:
        import httpx

        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)
        self.model = model
        self.dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            resp = self.client.post(f"{self.base_url}/embed", json={"texts": texts[i : i + 64]})
            resp.raise_for_status()
            body = resp.json()
            self.model = body["model"]
            out.extend(body["vectors"])
        return out


def from_env(mode: str | None = None, url: str | None = None) -> Embedder:
    mode = mode or os.environ.get("TB_EMBED_MODE", "hash")
    if mode == "hash":
        return HashEmbedder()
    if mode == "http":
        return HttpEmbedder(url or os.environ.get("EMBED_URL", "http://embed-service:8014"))
    if mode == "bge-m3":
        return BgeM3Embedder(os.environ.get("TB_EMBED_MODEL_PATH", "/models/bge-m3"))
    raise ValueError(f"unknown TB_EMBED_MODE {mode!r}")
