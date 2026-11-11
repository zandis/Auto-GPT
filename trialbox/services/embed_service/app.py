"""embed-service: ``POST /embed {texts[]}`` -> 1024-d vectors (SPEC §4.7)."""

from __future__ import annotations

import os
from functools import cache

from tb_common.http import make_app
from tb_common.phi_guard import mask_note, site_mrn_regex
from tb_contracts import EmbedRequest, EmbedResponse

from embed_service.embedder import Embedder, from_env

_embedder: Embedder | None = None


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = from_env(os.environ.get("TB_EMBED_MODE", "hash"))
    return _embedder


@cache
def mrn_regex() -> str | None:
    return site_mrn_regex()


app = make_app("embed-service", checks=[lambda: {"model": embedder().model}])


@app.post("/embed")
def embed(req: EmbedRequest) -> EmbedResponse:
    """Every input is masked first (T-600, D-337): a caller that sends note text unmasked still embeds no name, phone
    number, chart number or ID number. Masking keeps the length and is a no-op on text already masked."""
    e = embedder()
    return EmbedResponse(vectors=e.embed([mask_note(t, mrn_regex()) for t in req.texts]), model=e.model, dim=e.dim)
