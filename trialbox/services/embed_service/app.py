"""embed-service: ``POST /embed {texts[]}`` -> 1024-d vectors (SPEC §4.7)."""

from __future__ import annotations

import os

from tb_common.http import make_app
from tb_contracts import EmbedRequest, EmbedResponse

from embed_service.embedder import Embedder, from_env

_embedder: Embedder | None = None


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = from_env(os.environ.get("TB_EMBED_MODE", "hash"))
    return _embedder


app = make_app("embed-service", checks=[lambda: {"model": embedder().model}])


@app.post("/embed")
def embed(req: EmbedRequest) -> EmbedResponse:
    e = embedder()
    return EmbedResponse(vectors=e.embed(req.texts), model=e.model, dim=e.dim)
