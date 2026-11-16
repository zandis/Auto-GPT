"""criteria-compiler service: ``/compile``, ``/diff``, ``/approve`` (SPEC §4.3)."""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from lake.client import LakeHttp
from pydantic import ValidationError
from tb_common.audit_writer import open_audit
from tb_common.config import get_config
from tb_common.fhir import FhirEvaluator
from tb_common.http import make_app, trace_of
from tb_common.llm import LlmClient
from tb_common.objstore import from_config
from tb_common.ruleset import SEED_RULESETS, examples_allowed
from tb_contracts import (
    ApproveRequest,
    ApproveResult,
    CompileRequest,
    CompileResult,
    CtgovSearchRequest,
    CtgovSearchResult,
    DiffRequest,
    DiffResult,
)

from criteria_compiler.compile_cql.translator import Translator, available
from criteria_compiler.repo import RulesetRepo
from criteria_compiler.semantics import CompileError
from criteria_compiler.service import CompileFailed, Compiler, CompilerDeps
from criteria_compiler.terminology import resolver

_compiler: Compiler | None = None
SEED = SEED_RULESETS  # D-469: read-only; the working copy is cfg.env.rulesets_path


def _egfr(tz: str, locale: str | None) -> str:
    """D-149: a plain "eGFR" criterion is JSN 2009 at a Japanese site, CKD-EPI 2021 (``egfr``) elsewhere."""
    from tb_common.derived import country_of, egfr_for_site

    site = egfr_for_site(country_of(tz, locale))
    return "egfr" if site == "egfr_ckd_epi" else site


def ruleset_repo(path: Path) -> RulesetRepo:
    """The box's ruleset repository at ``path``. A new one starts from the shipped examples only on a DEV or TEST
    box (D-640, NEW-LIFE-1): a site box starts empty, and its first approved ruleset is the site's own."""
    return RulesetRepo(path, SEED if examples_allowed() else None)


def compiler() -> Compiler:
    global _compiler
    if _compiler is None:
        from tb_common.refdata import synonym_lookup

        cfg = get_config()
        audit = open_audit(cfg.env.audit_path, cfg.env.tz)
        th = cfg.settings.thresholds
        deps = CompilerDeps(
            store=from_config(),
            repo=ruleset_repo(cfg.env.rulesets_path),
            llm=LlmClient.from_config(audit),
            # D-172: the loaded zh-TW synonym dictionary; the source and release from the resolver (D-301)
            term=resolver.jp_ingredients(resolver.terminology(name_synonyms=synonym_lookup())),  # T-610: JP stems
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
            egfr_equation=_egfr(cfg.env.tz, cfg.settings.site.locale),
        )
        _compiler = Compiler(deps)
    return _compiler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialise the ruleset repository at start-up, before any other service reads it: a fresh DEV or TEST box
    seeds and materialises the shipped example rulesets (with their tags); a site box starts empty (D-640)."""
    compiler()
    yield


app = make_app("criteria-compiler", lifespan=lifespan)
log = logging.getLogger("criteria-compiler")


def _fail(exc: CompileFailed) -> HTTPException:
    return HTTPException(status_code=422, detail={"step": exc.step, "message": str(exc)})


def _answer[T](step: str, call: Callable[[], T]) -> T:
    """One route's work, with every failure answered (D-910; red of lane G's run, 11 HTTP 500s on FEAS and APPROVE).

    * ``CompileFailed``: 422 with its step and reason, as before.
    * A criterion or ruleset the compiler cannot build (``CompileError``, a model's output outside the IR): 422 with
      the step and the reason; for an IR refusal, where it was refused, never the refused value.
    * Anything else is a bug: 500 with an error id, and the error's type and frames (never its text, D-557) in the
      service's log and in the audit chain, which the box keeps (the container's own log is gone with it)."""
    try:
        return call()
    except CompileFailed as exc:
        raise _fail(exc) from exc
    except CompileError as exc:
        raise HTTPException(status_code=422, detail={"step": step, "message": str(exc)}) from exc
    except ValidationError as exc:
        where = ", ".join(".".join(str(x) for x in e["loc"]) or "input" for e in exc.errors()[:5])
        detail = {"step": step, "message": f"the ruleset is not valid here: {where}"}
        raise HTTPException(status_code=422, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_id = uuid.uuid4().hex[:12]
        trace = trace_of(exc)
        log.error("unhandled error", extra={"step": step, "error_id": error_id, **trace})
        with contextlib.suppress(Exception):  # the audit is where the box keeps it; a failing audit adds nothing
            compiler()._audit("compile.error", detail={"step": step, "error_id": error_id, **trace})
        raise HTTPException(
            status_code=500, detail={"step": step, "error": "internal error", "error_id": error_id}
        ) from exc


@app.post("/compile")
def compile_(req: CompileRequest) -> CompileResult:
    return _answer("compile", lambda: compiler().compile(req))


@app.post("/ctgov/search")
def ctgov_search(req: CtgovSearchRequest) -> CtgovSearchResult:
    return _answer("ctgov", lambda: compiler().ctgov_search(req))


@app.post("/diff")
def diff(req: DiffRequest) -> DiffResult:
    return _answer("diff", lambda: compiler().diff(req))


@app.post("/approve")
def approve(req: ApproveRequest) -> ApproveResult:
    return _answer("approve", lambda: compiler().approve(req))
