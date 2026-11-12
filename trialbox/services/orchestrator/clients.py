"""Typed clients for the services the orchestrator drives (contract models only, SPEC §4)."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from tb_common.http import ServiceClient, ServiceError
from tb_contracts import (
    ApproveRequest,
    ApproveResult,
    CompileRequest,
    CompileResult,
    CtgovSearchRequest,
    CtgovSearchResult,
    DiffRequest,
    DiffResult,
    IngestReport,
    IngestRequest,
    ParsedDoc,
    ParseRequest,
    SendRequest,
    SendResult,
)

log = logging.getLogger("orchestrator.clients")


class StepFailed(RuntimeError):
    """A scenario step failed; ``step`` and the plain-language message go into the job error and the Failed mail."""

    def __init__(self, step: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.step = step
        self.message = message
        self.detail = detail


class ParserAPI(Protocol):
    def parse(self, req: ParseRequest) -> ParsedDoc: ...


class CompilerAPI(Protocol):
    def compile(self, req: CompileRequest) -> CompileResult: ...

    def diff(self, req: DiffRequest) -> DiffResult: ...

    def approve(self, req: ApproveRequest) -> ApproveResult: ...

    def ctgov_search(self, req: CtgovSearchRequest) -> CtgovSearchResult: ...


class MailAPI(Protocol):
    def send(self, req: SendRequest) -> SendResult: ...


class AdapterAPI(Protocol):
    def run(self, req: IngestRequest) -> IngestReport: ...


def _step_error(exc: ServiceError, default_step: str) -> StepFailed:
    step, message = default_step, exc.detail
    try:
        body = json.loads(exc.detail)
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            step = str(detail.get("step") or default_step)
            message = str(detail.get("message") or message)
        elif isinstance(detail, str):
            message = detail
    except (ValueError, AttributeError):
        pass
    return StepFailed(step, message, f"{exc.service} HTTP {exc.status}")


class ParserHttp:
    def __init__(self, base_url: str) -> None:
        self.c = ServiceClient(base_url, "doc-parser", timeout=900)

    def parse(self, req: ParseRequest) -> ParsedDoc:
        try:
            return self.c.post("/parse", req, ParsedDoc)
        except ServiceError as exc:
            raise _step_error(exc, "parsing") from exc


class CompilerHttp:
    def __init__(self, base_url: str) -> None:
        self.c = ServiceClient(base_url, "criteria-compiler", timeout=3600, retries=0)

    def compile(self, req: CompileRequest) -> CompileResult:
        try:
            return self.c.post("/compile", req, CompileResult)
        except ServiceError as exc:
            raise _step_error(exc, "compiling") from exc

    def diff(self, req: DiffRequest) -> DiffResult:
        try:
            return self.c.post("/diff", req, DiffResult)
        except ServiceError as exc:
            raise _step_error(exc, "compiling") from exc

    def approve(self, req: ApproveRequest) -> ApproveResult:
        try:
            return self.c.post("/approve", req, ApproveResult)
        except ServiceError as exc:
            raise _step_error(exc, "approve") from exc

    def ctgov_search(self, req: CtgovSearchRequest) -> CtgovSearchResult:
        try:
            return self.c.post("/ctgov/search", req, CtgovSearchResult)
        except ServiceError as exc:
            raise _step_error(exc, "ctgov") from exc


class MailHttp:
    def __init__(self, base_url: str) -> None:
        self.c = ServiceClient(base_url, "mail-gateway", timeout=300, idempotent=False)  # a retry = a second mail

    def send(self, req: SendRequest) -> SendResult:
        try:
            return self.c.post("/send", req, SendResult)
        except ServiceError as exc:
            raise _step_error(exc, "mail") from exc


class AdapterHttp:
    """The night's ingest on the adapter (T-690, D-472): ``POST /run`` starts it (202 and a run id), then its state
    is read until it ends. The night is never timed (OD-10; before, 7,200 s around the whole run, no retry): each
    request is short; the poll's interval and its bound on silence are the declared settings of
    :mod:`tb_common.jobpoll`. When the adapter is already running an ingest (409), that run is followed
    (NEW-PERF-2)."""

    def __init__(self, base_url: str, poll: Any = None) -> None:
        self.c = ServiceClient(base_url, "adapter", timeout=60, retries=0, idempotent=False)
        self.poll = poll

    def _running(self, refused: ServiceError) -> dict[str, Any]:
        """NEW-PERF-2 (PERF-008, ARCH-002): the adapter refused the start because an ingest is running (409). That
        is the night this job asked for, started before the orchestrator restarted (or by another caller): the job
        follows it to its end and takes its report, instead of failing beside a night that is published. Returns
        the state of the run to follow (the adapter's newest run). Anything else is the step failure it was: another
        refusal, an adapter that cannot be asked, or one that knows no run (it restarted in between)."""
        if refused.status != 409:
            raise _step_error(refused, "ingest") from refused
        try:
            latest: dict[str, Any] = self.c.get_json("/run")
        except ServiceError:
            raise _step_error(refused, "ingest") from refused
        if not isinstance(latest, dict) or not latest.get("run") or latest.get("state") in (None, "none"):
            raise _step_error(refused, "ingest") from refused
        log.warning("an ingest is already running on the adapter (run %s): this job follows it", latest["run"])
        return latest

    def run(self, req: IngestRequest) -> IngestReport:
        from tb_common.jobpoll import JobLost, Poll

        try:
            started = self.c.post_raw("/run", req).json()
        except ServiceError as exc:
            started = self._running(exc)
        rid = str(started.get("run") or "")

        def read() -> dict[str, Any]:
            try:
                body: dict[str, Any] = self.c.get_json(f"/run/{rid}")
            except ServiceError as exc:
                if exc.status == 404:
                    raise JobLost(f"the adapter no longer knows ingest run {rid} (it restarted)") from None
                raise
            return body

        try:
            st = started if started.get("state") != "running" else (self.poll or Poll()).until_done(read, "ingest")
        except JobLost as exc:
            raise StepFailed("ingest", f"The nightly ingest could not be followed to its end: {exc}") from None
        except ServiceError as exc:
            raise _step_error(exc, "ingest") from exc
        if st.get("state") == "done":
            return IngestReport.model_validate(st.get("report") or {})
        raise StepFailed("ingest", str(st.get("detail") or f"the ingest ended {st.get('state')}"), f"adapter run {rid}")
