"""embed-service: ``POST /embed {texts[]}`` -> 1024-d vectors (SPEC §4.7).

The embedder is chosen by :func:`embed_service.embedder.service_embedder` (T-607, D-429): in PRODUCTION the hash stub
is refused and the local weights must match the site's pin, and the service fails at start rather than at the first
call. ``/healthz`` names the build and the first 12 characters of the weights' manifest digest."""

from __future__ import annotations

import os
from functools import cache

from tb_common.config import environment_name
from tb_common.http import make_app
from tb_common.phi_guard import mask_note, site_mrn_regex
from tb_contracts import EmbedRequest, EmbedResponse

from embed_service.embedder import Embedder, service_embedder

_embedder: Embedder | None = None


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = service_embedder()
    return _embedder


def health() -> dict[str, str]:
    e = embedder()
    sha = getattr(e, "weights_sha256", None)
    return {"model": e.model, **({"weights": str(sha)[:12]} if sha else {})}


@cache
def mrn_regex() -> str | None:
    return site_mrn_regex()


app = make_app("embed-service", checks=[health])

if environment_name(os.environ) == "PRODUCTION":  # refuse at start: a box never runs on the stub or unpinned weights
    embedder()


@app.post("/embed")
def embed(req: EmbedRequest) -> EmbedResponse:
    """Every input is masked first (T-600, D-337): a caller that sends note text unmasked still embeds no name, phone
    number, chart number or ID number. Masking keeps the length and is a no-op on text already masked."""
    e = embedder()
    return EmbedResponse(vectors=e.embed([mask_note(t, mrn_regex()) for t in req.texts]), model=e.model, dim=e.dim)
