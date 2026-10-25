"""model-registry service v0 (spec v4 §8.4): read-only alias -> build map over HTTP.

``GET /v1/builds`` lists builds; ``GET /v1/aliases/{alias}`` lists one alias's builds. No endpoint addresses are
served (those live only in the gateway's routing policy, LLM-1).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from tb_common.http import make_app

from registry.registry import DEFAULT_PATH, Registry


def create_app(reg: Registry | None = None) -> FastAPI:
    registry = reg or Registry.load(Path(os.environ.get("TB_REGISTRY_PATH") or DEFAULT_PATH))
    app = make_app("model-registry", checks=[lambda: {"registry_version": registry.version}])

    @app.get("/v1/builds")
    def builds() -> dict[str, Any]:
        return {"version": registry.version, "builds": registry.table()}

    @app.get("/v1/aliases/{alias}")
    def alias(alias: str) -> dict[str, Any]:
        if alias not in registry.aliases:
            raise HTTPException(status_code=404, detail=f"unknown alias {alias!r}")
        rows = [r for r in registry.table() if r["alias"] == alias]
        return {"alias": alias, **registry.aliases[alias], "builds": rows}

    return app
