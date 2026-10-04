"""criteria-compiler service: ``/compile``, ``/diff``, ``/approve`` (SPEC §4.3)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from lake.client import LakeHttp
from tb_common.audit import AuditLog
from tb_common.config import get_config
from tb_common.fhir import FhirEvaluator
from tb_common.http import make_app
from tb_common.llm import LlmClient
from tb_common.objstore import from_config
from tb_contracts import ApproveRequest, ApproveResult, CompileRequest, CompileResult, DiffRequest, DiffResult

from criteria_compiler.compile_cql.translator import Translator, available
from criteria_compiler.repo import RulesetRepo
from criteria_compiler.service import CompileFailed, Compiler, CompilerDeps
from criteria_compiler.terminology.mapper import Terminology

_compiler: Compiler | None = None
SEED = Path(__file__).resolve().parents[2] / "rulesets"


def compiler() -> Compiler:
    global _compiler
    if _compiler is None:
        cfg = get_config()
        audit = AuditLog(cfg.env.audit_path, cfg.env.tz)
        th = cfg.settings.thresholds
        deps = CompilerDeps(
            store=from_config(),
            repo=RulesetRepo(cfg.env.rulesets_path, SEED),
            llm=LlmClient.from_config(audit),
            term=Terminology(),
            settings_thresholds={
                "equivalence_min_pct": th.equivalence_min_pct,
                "tier_high_confidence": th.tier_high_confidence,
                "small_cell": th.small_cell,
            },
            tz=cfg.env.tz,
            mrn_regex=cfg.settings.mrn_regex,
            lake=LakeHttp(cfg.env.lake_url),
            fhir=FhirEvaluator(cfg.env.fhir_base_url, workers=int(os.environ.get("TB_FHIR_WORKERS", "8"))),
            translator=Translator() if available() else None,
            audit=audit,
            judge_model=(cfg.settings.models.judge if cfg.settings.models else "") or "",
        )
        _compiler = Compiler(deps)
    return _compiler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialise the ruleset repository at start-up: a fresh box seeds and materialises the vendor-shipped approved
    rulesets (with their approval tags) before any other service reads them."""
    compiler()
    yield


app = make_app("criteria-compiler", lifespan=lifespan)


def _fail(exc: CompileFailed) -> HTTPException:
    return HTTPException(status_code=422, detail={"step": exc.step, "message": str(exc)})


@app.post("/compile")
def compile_(req: CompileRequest) -> CompileResult:
    try:
        return compiler().compile(req)
    except CompileFailed as exc:
        raise _fail(exc) from exc


@app.post("/diff")
def diff(req: DiffRequest) -> DiffResult:
    try:
        return compiler().diff(req)
    except CompileFailed as exc:
        raise _fail(exc) from exc


@app.post("/approve")
def approve(req: ApproveRequest) -> ApproveResult:
    try:
        return compiler().approve(req)
    except CompileFailed as exc:
        raise _fail(exc) from exc
