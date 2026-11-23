"""embed-service: ``POST /embed {texts[]}`` -> 1024-d vectors (SPEC §4.7).

The embedder is chosen by :func:`embed_service.embedder.service_embedder` (T-607, D-429): in PRODUCTION the hash stub
is refused and the local weights must match the site's pin, and the service fails at start rather than at the first
call. ``/healthz`` names the build and the first 12 characters of the weights' manifest digest."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache
from typing import Any

from tb_common.config import environment_name
from tb_common.http import make_app
from tb_common.phi_guard import mask_note, site_mrn_regex
from tb_contracts import EmbedRequest, EmbedResponse

from embed_service.embedder import Embedder, service_embedder

_embedder: Embedder | None = None
_load_lock = threading.Lock()
_gate: threading.BoundedSemaphore | None = None
_gate_lock = threading.Lock()


def embedder() -> Embedder:
    """The model, loaded once (red of 2026-11-15: requests that arrived together each loaded their own copy, and the
    service ran out of memory and restarted)."""
    global _embedder
    if _embedder is None:
        with _load_lock:
            if _embedder is None:
                _embedder = service_embedder()
    return _embedder


def gate() -> threading.BoundedSemaphore:
    """``TB_EMBED_CONCURRENCY`` requests encode at a time (1 by default: one CPU-bound encode uses every core)."""
    global _gate
    if _gate is None:
        with _gate_lock:
            if _gate is None:
                _gate = threading.BoundedSemaphore(max(1, int(os.environ.get("TB_EMBED_CONCURRENCY") or 1)))
    return _gate


def health() -> dict[str, str]:
    e = embedder()
    sha = getattr(e, "weights_sha256", None)
    return {"model": e.model, **({"weights": str(sha)[:12]} if sha else {})}


@cache
def mrn_regex() -> str | None:
    return site_mrn_regex()


@asynccontextmanager
async def lifespan(_app: Any) -> AsyncIterator[None]:
    """D-907 (from lane G's #772): the model is loaded when the service starts, in every environment, under the one
    lock (a request that arrives meanwhile waits for this load), so the first SCREEN request does not pay for it and a
    configuration the loader refuses stops the service at start."""
    embedder()
    yield


app = make_app("embed-service", checks=[health], lifespan=lifespan)

if environment_name(os.environ) == "PRODUCTION":  # refuse at start: a box never runs on the stub or unpinned weights
    embedder()


@app.post("/embed")
def embed(req: EmbedRequest) -> EmbedResponse:
    """Every input is masked first (T-600, D-337): a caller that sends note text unmasked still embeds no name, phone
    number, chart number or ID number. Masking keeps the length and is a no-op on text already masked."""
    e = embedder()
    texts = [mask_note(t, mrn_regex(), model_input=True) for t in req.texts]
    with gate():
        vectors = e.embed(texts)
    return EmbedResponse(vectors=vectors, model=e.model, dim=e.dim)
