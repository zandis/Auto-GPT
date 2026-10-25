"""guard-service v0 HTTP surface: ``POST /v1/scan`` (tripwire verdict) and ``POST /v1/redact``.

Responses carry kinds, counts and offsets only, never the matched text.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from tb_common.http import make_app

from guard.guard import Guard


class TextIn(BaseModel):
    text: str


def create_app(guard: Guard | None = None) -> FastAPI:
    g = guard or Guard.from_settings()
    app = make_app("guard")

    @app.post("/v1/scan")
    def scan(body: TextIn) -> dict[str, Any]:
        v = g.tripwire(body.text)
        return {
            "hit": v.hit,
            "kinds": list(v.kinds),
            "count": v.count,
            "spans": [{"kind": f.kind, "start": f.start, "end": f.end} for f in v.findings],
        }

    @app.post("/v1/redact")
    def redact(body: TextIn) -> dict[str, Any]:
        return {"text": g.redact(body.text)}

    return app
