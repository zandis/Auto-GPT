"""TrialBox Test Bench web app (FastAPI + Jinja2 + vendored htmx; docs/HANDOFF.md §5).

    TB_ENV=DEV PYTHONPATH=libs:services:. .venv/bin/python -m tools.testbench          # 127.0.0.1:8765
    TB_ENV=DEV PYTHONPATH=libs:services:. .venv/bin/python -m uvicorn tools.testbench.app:app --port 8765

``app`` is built on first access (PEP 562), so importing this module has no side effect; building it runs the
start-up refusals of :mod:`tools.testbench.safety` and checks every bench dataset against ``eval/DATASETS.yaml``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tb_common.policy.classes import Environment, PolicyError, Topology

from tools.testbench import BANNER, HTMX_SHA256, HTMX_VERSION, drivers, e2e_adapter
from tools.testbench.datasets import all_datasets, require
from tools.testbench.jobs import Job, JobStore, Log, sse
from tools.testbench.safety import startup_checks

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_WORKDIR = ROOT / ".cache" / "testbench"
PAGES = [
    ("/", "Home"),
    ("/run", "Run"),
    ("/dataplat", "Data platform"),
    ("/llm", "LLM lab"),
    ("/guard", "PHI guard"),
    ("/recall", "Recall"),
    ("/match", "Registry match"),
]
E2E_DATASETS = ("synthea_site_a", "mimic_demo")
GUARD_SAMPLE = (
    "Synthetic note: patient A123456789 (fictional ID) phoned 0912-345-678 on 2026-10-01 about a gout flare; "
    "e-mail wang.test@example.com."
)
MATCH_SAMPLE = "A 60-year-old man with chronic tophaceous gout and serum urate above 6 mg/dL despite allopurinol."
PYTEST_ARGS = [
    "-q",
    "-m",
    "not integration and not e2e and not llm and not perf",
    "--ignore=tests/testbench",
    "-p",
    "no:cacheprovider",
]


def create_app(env: Mapping[str, str] | None = None, workdir: Path | None = None) -> FastAPI:
    e = dict(os.environ if env is None else env)
    environment = startup_checks(e)
    datasets = all_datasets(environment)  # refuses to start if any bench dataset is above D0 or not open/synthetic
    root = workdir or Path(e.get("TB_TESTBENCH_WORKDIR") or DEFAULT_WORKDIR)
    root.mkdir(parents=True, exist_ok=True)
    jobs = JobStore(root)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals.update(banner=BANNER, pages=PAGES, environment=environment.value, htmx_version=HTMX_VERSION)

    app = FastAPI(title="TrialBox Test Bench", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.environment = environment
    app.state.jobs = jobs
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def page(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {"path": request.url.path, **ctx}, status_code=status_code)

    def is_htmx(request: Request) -> bool:
        return request.headers.get("hx-request") == "true"

    def frag(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        """A partial for htmx swaps; opened directly it is wrapped in the full page (banner included)."""
        if is_htmx(request):
            return page(request, name, **ctx)
        return page(request, "fragment_page.html", inner=name, **ctx)

    def job_response(request: Request, job: Job) -> Response:
        if is_htmx(request):
            return page(request, "_job.html", job=job)
        return RedirectResponse(f"/jobs/{job.id}/view", status_code=303)

    @app.exception_handler(PolicyError)
    def refused(request: Request, exc: PolicyError) -> HTMLResponse:
        return page(request, "refused.html", status_code=403, message=str(exc))

    @app.middleware("http")
    async def banner_header(request: Request, call_next: Any) -> Response:
        resp: Response = await call_next(request)
        resp.headers["X-TB-Test-Bench"] = "synthetic-and-open-data-only"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------------------------------------ meta
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "testbench",
            "env": environment.value,
            "banner": BANNER,
            "htmx": HTMX_VERSION,
        }

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        entry = e2e_adapter.find_entry(e)
        return page(
            request,
            "home.html",
            datasets=datasets,
            e2e_entry=entry[0] if entry else None,
            htmx_sha256=HTMX_SHA256,
        )

    # ------------------------------------------------------------------------------------------------ jobs
    @app.get("/jobs/{jid}/events")
    def job_events(jid: str) -> StreamingResponse:
        job = _job(jid)
        return StreamingResponse(sse(job), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/jobs/{jid}")
    def job_status(jid: str) -> JSONResponse:
        job = _job(jid)
        return JSONResponse(
            {"id": job.id, "kind": job.kind, "status": job.status, "seconds": job.seconds, "lines": len(job.lines)}
        )

    @app.get("/jobs/{jid}/result", response_class=HTMLResponse)
    def job_result(request: Request, jid: str) -> HTMLResponse:
        job = _job(jid)
        return frag(request, "_job_result.html", job=job, **_result_ctx(job))

    @app.get("/jobs/{jid}/view", response_class=HTMLResponse)
    def job_view(request: Request, jid: str) -> HTMLResponse:
        job = _job(jid)
        return page(request, "job_view.html", job=job, **_result_ctx(job))

    @app.get("/files/{jid}/{rel:path}")
    def job_file(jid: str, rel: str) -> FileResponse:
        job = _job(jid)
        base = job.workdir.resolve()
        target = (base / rel).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise _NotFound(f"no file {rel!r} in job {jid}")
        return FileResponse(target, filename=target.name)

    def _job(jid: str) -> Job:
        job = jobs.get(jid)
        if job is None:
            raise _NotFound(f"no job {jid!r}")
        return job

    def _result_ctx(job: Job) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        if job.kind == "e2e" and isinstance(job.result, e2e_adapter.BenchE2E):
            r = job.result
            ctx["files"] = [
                (str(p.relative_to(job.workdir)) if p.is_relative_to(job.workdir) else p.name, p)
                for p in r.files
                if p.exists()
            ]
        if job.kind == "recall" and isinstance(job.result, drivers.RecallResult):
            ctx["svg"] = drivers.trajectory_svg(job.result.trajectory, job.result.trajectory_rate)
        return ctx

    @app.exception_handler(_NotFound)
    def not_found(request: Request, exc: _NotFound) -> HTMLResponse:
        return page(request, "refused.html", status_code=404, message=str(exc))

    # ------------------------------------------------------------------------------------------------ run
    @app.get("/run", response_class=HTMLResponse)
    def run_page(request: Request) -> HTMLResponse:
        rows = [d for d in datasets if d.id in E2E_DATASETS]
        last = jobs.latest("e2e")
        return page(
            request,
            "run.html",
            datasets=rows,
            default_trial=e2e_adapter.DEFAULT_TRIAL,
            last=last,
            **(_result_ctx(last) if last else {}),
        )

    @app.post("/run")
    def run_e2e(request: Request, dataset: str = Form(...), trial_id: str = Form("")) -> Response:
        ds = require(dataset, environment)
        if ds.id not in E2E_DATASETS:
            raise PolicyError(f"no end-to-end path for {ds.id}")

        def work(log: Log, wd: Path) -> e2e_adapter.BenchE2E:
            return e2e_adapter.run(ds, trial_id.strip(), wd / "out", log, e)

        return job_response(request, jobs.start("e2e", f"Run end to end: {ds.title}", work))

    @app.post("/tests")
    def run_tests(request: Request) -> Response:
        def work(log: Log, wd: Path) -> dict[str, Any]:
            cmd = [sys.executable, "-m", "pytest", *PYTEST_ARGS]
            log("$ " + " ".join(cmd))
            env2 = {**os.environ, "PYTHONPATH": "libs:services:."}
            proc = subprocess.Popen(  # fixed argv, no shell
                cmd, cwd=ROOT, env=env2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            assert proc.stdout is not None
            tail: list[str] = []
            for line in proc.stdout:
                line = line.rstrip()
                tail = [*tail[-40:], line]
                if line and not re.fullmatch(r"[.sxFE]+(\s+\[\s*\d+%\])?", line):
                    log(line)
            rc = proc.wait()
            summary = next(
                (x for x in reversed(tail) if re.search(r"\d+ (passed|failed)", x)), tail[-1] if tail else ""
            )
            return {"returncode": rc, "summary": summary, "passed": rc == 0}

        return job_response(request, jobs.start("tests", "Run all tests (unit)", work))

    # ------------------------------------------------------------------------------------------------ data platform
    @app.get("/dataplat", response_class=HTMLResponse)
    def dataplat_page(request: Request) -> HTMLResponse:
        return page(request, "dataplat.html", defects=list(drivers.DEFECT_TABLE), last=jobs.latest("dataplat"))

    @app.post("/dataplat")
    def dataplat_run(request: Request, defect: str = Form("")) -> Response:
        ds = require("synthea_site_a", environment)
        if defect and defect not in drivers.DEFECT_TABLE:
            raise PolicyError(f"unknown defect {defect!r}")

        def work(log: Log, wd: Path) -> drivers.DataplatResult:
            return drivers.run_dataplat(ds.path, defect, log, wd)

        return job_response(request, jobs.start("dataplat", f"Data platform: {defect or 'clean'}", work))

    # ------------------------------------------------------------------------------------------------ LLM lab
    def _topology(v: str) -> Topology:
        return Topology(v) if v in Topology.__members__ else Topology.A

    def _env(v: str) -> Environment:
        return Environment(v) if v in Environment.__members__ else environment

    @app.get("/llm", response_class=HTMLResponse)
    def llm_page(request: Request) -> HTMLResponse:
        version, builds, cards = drivers.registry_view()
        cols, rows, pver = drivers.route_table(environment, Topology.A)
        return page(
            request,
            "llm.html",
            cols=cols,
            rows=rows,
            policy_version=pver,
            sel={"topology": "A", "env": environment.value, "opt_in": False},
            registry_version=version,
            builds=builds,
            cards=cards,
            classes=drivers.CLASS_TAGS,
            envs=[x.value for x in Environment],
        )

    @app.get("/llm/routes", response_class=HTMLResponse)
    def llm_routes(request: Request, topology: str = "A", env: str = "", opt_in: str = "") -> HTMLResponse:
        # policy lookups only: no data moves, so every environment's routing can be inspected
        topo, envv = _topology(topology), _env(env)
        cols, rows, pver = drivers.route_table(envv, topo, cloud_opt_in=bool(opt_in))
        sel = {"topology": topo.value, "env": envv.value, "opt_in": bool(opt_in)}
        return frag(request, "_routes.html", cols=cols, rows=rows, policy_version=pver, sel=sel)

    @app.post("/llm/prompt", response_class=HTMLResponse)
    def llm_prompt(
        request: Request, text: str = Form(...), data_class: str = Form("D0"), topology: str = Form("A")
    ) -> HTMLResponse:
        # the call runs in the bench environment (DEV/TEST): the gateway itself refuses anything above D0
        out = drivers.send_test_prompt(text, data_class, environment, _topology(topology), root / "llm-audit")
        return frag(request, "_prompt.html", out=out)

    # ------------------------------------------------------------------------------------------------ guard
    @app.get("/guard", response_class=HTMLResponse)
    def guard_page(request: Request) -> HTMLResponse:
        return page(request, "guard.html", sample=GUARD_SAMPLE, out=None)

    @app.post("/guard", response_class=HTMLResponse)
    def guard_run(request: Request, text: str = Form(...)) -> HTMLResponse:
        out = drivers.guard_redact(text)
        if is_htmx(request):
            return page(request, "_guard.html", out=out)
        return page(request, "guard.html", sample=text, out=out)

    # ------------------------------------------------------------------------------------------------ recall
    @app.get("/recall", response_class=HTMLResponse)
    def recall_page(request: Request) -> HTMLResponse:
        last = jobs.latest("recall")
        return page(request, "recall.html", last=last, **(_result_ctx(last) if last else {}))

    @app.post("/recall")
    def recall_run(
        request: Request,
        reps: int = Form(20),
        months: int = Form(12),
        per_month: int = Form(40),
        rate: float = Form(0.02),
    ) -> Response:
        require("recall_cert", environment)
        if not (1 <= reps <= 300 and 1 <= months <= 24 and 1 <= per_month <= 200 and 0 < rate < 1):
            raise PolicyError("recall inputs out of range (reps 1–300, looks 1–24, draws 1–200, 0 < p < 1)")

        def work(log: Log, wd: Path) -> drivers.RecallResult:
            return drivers.run_recall(reps, months, per_month, rate, log, wd)

        return job_response(request, jobs.start("recall", f"Recall simulation p={rate}", work))

    # ------------------------------------------------------------------------------------------------ registry match
    @app.get("/match", response_class=HTMLResponse)
    def match_page(request: Request) -> HTMLResponse:
        return page(request, "match.html", sample=MATCH_SAMPLE, out=None)

    @app.post("/match", response_class=HTMLResponse)
    def match_run(
        request: Request,
        note: str = Form(...),
        open_data: str = Form(""),
        synthetic: str = Form(""),
        top_k: int = Form(5),
    ) -> HTMLResponse:
        if open_data:
            require("ctgov_records", environment)
        out = drivers.run_registry_match(note, bool(open_data), bool(synthetic), max(1, min(top_k, 20)))
        if is_htmx(request):
            return page(request, "_match.html", out=out)
        return page(request, "match.html", sample=note, out=out)

    return app


class _NotFound(LookupError):
    pass


def __getattr__(name: str) -> Any:
    """``tools.testbench.app:app`` for uvicorn: built (and checked) on first access, then cached."""
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)


__all__ = ["create_app"]
