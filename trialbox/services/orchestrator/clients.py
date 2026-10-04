"""Typed clients for the services the orchestrator drives (contract models only, SPEC §4)."""

from __future__ import annotations

import json
from typing import Protocol

from tb_common.http import ServiceClient, ServiceError
from tb_contracts import (
    ApproveRequest,
    ApproveResult,
    CompileRequest,
    CompileResult,
    DiffRequest,
    DiffResult,
    IngestReport,
    IngestRequest,
    ParsedDoc,
    ParseRequest,
    SendRequest,
    SendResult,
)


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


class MailHttp:
    def __init__(self, base_url: str) -> None:
        self.c = ServiceClient(base_url, "mail-gateway", timeout=300)

    def send(self, req: SendRequest) -> SendResult:
        try:
            return self.c.post("/send", req, SendResult)
        except ServiceError as exc:
            raise _step_error(exc, "mail") from exc


class AdapterHttp:
    def __init__(self, base_url: str) -> None:
        self.c = ServiceClient(base_url, "adapter", timeout=7200, retries=0)

    def run(self, req: IngestRequest) -> IngestReport:
        try:
            return self.c.post("/run", req, IngestReport)
        except ServiceError as exc:
            raise _step_error(exc, "ingest") from exc
