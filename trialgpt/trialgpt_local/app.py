"""Local web interface: paste or upload a patient note, run TrialGPT on the local LLM, read the ranked trials with
criterion-by-criterion explanations; see the benchmark and head-to-head reports.

    python -m trialgpt_local.app            # http://127.0.0.1:8090 (TG_HOST / TG_PORT to change)

Privacy: jobs live in memory only and the LLM disk cache is off for interactive runs (prompts contain the note).
The note goes to the local LLM; only the generated search keywords go to ClinicalTrials.gov (live mode). Nothing
from this interface is ever sent to trialgpt.app.
"""

from __future__ import annotations

import io
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from trialgpt_local import datasets
from trialgpt_local.config import ROOT, settings
from trialgpt_local.llm import LLMClient
from trialgpt_local.pipeline import run_patient

STATIC = ROOT / "trialgpt_local" / "static"
app = FastAPI(title="TrialGPT (local)", docs_url="/api/docs", openapi_url="/api/openapi.json")
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
MAX_JOBS = 50


class MatchRequest(BaseModel):
    note: str = Field(min_length=20, max_length=40000)
    source: str = "live"
    top_k: int = Field(default=10, ge=1, le=50)
    country: str | None = None


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config() -> dict[str, Any]:
    cfg = settings()
    sources = ["live"] + [c for c in datasets.COHORTS if (datasets.cohort_dir(c) / "corpus.jsonl").exists()]
    llm_ok, models = False, []
    try:
        if cfg.llm_backend == "ollama":
            r = httpx.get(f"{cfg.llm_base_url.rstrip('/')}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
        else:
            base = cfg.llm_base_url.rstrip("/")
            r = httpx.get(
                base + ("/models" if base.endswith("/v1") else "/v1/models"),
                timeout=5,
                headers={"Authorization": f"Bearer {cfg.llm_api_key}"},
            )
            models = [m["id"] for m in r.json().get("data", [])]
        llm_ok = r.status_code == 200
    except Exception:
        llm_ok = False
    return {
        "model": cfg.llm_model,
        "backend": cfg.llm_backend,
        "base_url": cfg.llm_base_url,
        "num_ctx": cfg.llm_num_ctx,
        "llm_reachable": llm_ok,
        "model_available": cfg.llm_model in models,
        "models": models,
        "sources": sources,
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (20 MB max)")
    name = (file.filename or "").lower()
    if name.endswith(".pdf") or data[:4] == b"%PDF":
        from pypdf import PdfReader

        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    else:
        text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise HTTPException(422, "no text found (scanned PDF? paste the text instead)")
    return {"text": text.strip()}


@app.post("/api/match")
def match(req: MatchRequest) -> dict[str, str]:
    if req.source != "live" and req.source not in datasets.COHORTS:
        raise HTTPException(422, f"unknown source {req.source}")
    jid = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "id": jid,
        "state": "running",
        "log": [],
        "result": None,
        "error": None,
        "started": time.time(),
    }
    with _LOCK:
        if len(_JOBS) >= MAX_JOBS:  # keep memory bounded: drop the oldest finished job
            old = min((j for j in _JOBS.values() if j["state"] != "running"), key=lambda j: j["started"], default=None)
            if old:
                _JOBS.pop(old["id"], None)
        _JOBS[jid] = job

    def work() -> None:
        try:
            run = run_patient(
                req.note,
                client=LLMClient(cache=False),
                source=req.source,
                top_k=req.top_k,
                country=req.country or None,
                progress=lambda m: job["log"].append({"t": round(time.time() - job["started"], 1), "msg": m}),
            )
            job["result"] = run.to_json()
            job["state"] = "done"
        except Exception as exc:
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["state"] = "failed"

    threading.Thread(target=work, name=f"job-{jid}", daemon=True).start()
    return {"id": jid}


@app.get("/api/jobs/{jid}")
def job(jid: str) -> dict[str, Any]:
    j = _JOBS.get(jid)
    if j is None:
        raise HTTPException(404, "no such job (jobs are kept in memory only)")
    return j


@app.get("/api/reports")
def reports() -> dict[str, Any]:
    root = settings().results_dir
    out: dict[str, Any] = {"benchmark": {}, "head_to_head": None}
    if root.exists():
        for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
            md = d / "report.md"
            if md.exists() and d.name != "h2h":
                out["benchmark"][d.name] = md.read_text(encoding="utf-8")
        h2h = root / "h2h" / "report.md"
        if h2h.exists():
            out["head_to_head"] = h2h.read_text(encoding="utf-8")
    return out


def _static_ok(path: Path) -> bool:
    return path.resolve().is_relative_to(STATIC.resolve()) and path.is_file()


@app.get("/static/{name}")
def static(name: str) -> FileResponse:
    path = STATIC / name
    if not _static_ok(path):
        raise HTTPException(404)
    return FileResponse(path)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=os.environ.get("TG_HOST", "127.0.0.1"), port=int(os.environ.get("TG_PORT", "8090")))


if __name__ == "__main__":
    main()
