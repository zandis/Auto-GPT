"""Typed clients for the services the orchestrator drives (contract models only, SPEC §4)."""

from __future__ import annotations

import json
import logging
import signal
from collections.abc import Callable
from typing import Any, Protocol

from tb_common.http import ServiceClient, ServiceError, kept_failure
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


class KeyedStepFailed(StepFailed):
    """A step failure said by a catalogue key of ``orchestrator.i18n`` with its values (F-44): the message is the
    English text, and the job's record and mail say it in the job's language (``core``)."""

    def __init__(self, step: str, key: str, detail: str, **values: str) -> None:
        from orchestrator import i18n

        super().__init__(step, i18n.t("en", key, **values), detail)
        self.key = key
        self.values = values


def _ingest_signalled(st: dict[str, Any], rid: str) -> KeyedStepFailed | None:
    """F-44: an ingest whose process a signal ended, by the number the adapter recorded from the return code
    (``exit_signal``); None for any other end. SIGKILL (9) adds what usually sends it, the memory limit. The texts
    are the catalogue's and the values a number and the platform's name for it (the D-557 scan's listed names)."""
    recorded = st.get("exit_signal")
    if st.get("state") != "failed" or not isinstance(recorded, int) or isinstance(recorded, bool) or recorded <= 0:
        return None
    name = {int(s): s.name for s in signal.Signals}.get(recorded, "unknown")
    if recorded == signal.SIGKILL:
        return KeyedStepFailed(
            "ingest",
            "ingest.signal_kill",
            f"adapter run {rid}, signal {recorded} ({name})",
            number=f"{recorded}",
            name=f"{name}",
        )
    return KeyedStepFailed(
        "ingest",
        "ingest.signal",
        f"adapter run {rid}, signal {recorded} ({name})",
        number=f"{recorded}",
        name=f"{name}",
    )


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

    def publish(self, body: dict[str, Any]) -> dict[str, Any]: ...  # NEW-SEC-4 (D-760)

    def publish_state(self, rid: str) -> dict[str, Any]: ...


def _ingest_ended(st: dict[str, Any]) -> str:
    """Why an ingest that is not done ended, for the job's record (D-557). The adapter's own sentence when it wrote
    one ("the source folder is empty", "night refused: ..."): those are its words for the operator. Its record of
    a failure it did not expect is an error's type and up to 500 characters of the error's text (a cast error
    quotes the value it could not cast): the job's record keeps the type (``tb_common.http.kept_failure``), the
    adapter's log has the rest."""
    detail = str(st.get("detail") or "").strip()
    kept = kept_failure(detail)
    if kept != detail:
        return f"The nightly ingest failed ({kept}); the adapter's log has it."
    if detail:
        return detail
    state = str(st.get("state") or "")
    return "the ingest ended " + (
        state if state in ("failed", "interrupted", "cancelled", "refused", "held") else "not done"
    )


def _step_error(exc: ServiceError, default_step: str) -> StepFailed:
    """A service's refusal of a step as the job's error (D-557). The message is the service's own when the answer
    has the shape of one: ``{"detail": {"step", "message"}}``, or a refusal (4xx) with a sentence as its detail
    ("an ingest is already running"). Anything else (a 5xx, a body that is not the service's JSON, up to 2,000
    characters of it, "unreachable: ...") is not kept in the job's record: it says which service did not do the
    step, and the detail says with what status."""
    step, message = default_step, f"The {exc.service} service did not do this step."
    try:
        body = json.loads(exc.detail)
        detail = body.get("detail", body)
        if isinstance(detail, dict) and detail.get("message"):
            step = str(detail.get("step") or default_step)
            message = str(detail["message"])
        elif isinstance(detail, str) and detail and 400 <= exc.status < 500:
            message = detail[:300]
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
        """NEW-PERF-2 (PERF-008, ARCH-002): the adapter refused the start because an ingest is running (409) and
        names that run (``X-TB-Run``). The job follows it to its end and takes its report, instead of failing
        beside a night that is published. Returns the state to poll from. Anything else is the step failure it
        was: another refusal, or a 409 that names no run (the adapter was still starting the run that holds it).
        The run the 409 names, never "the adapter's newest run": that can be last night's, ended (review F2)."""
        rid = refused.headers.get("x-tb-run", "").strip() if refused.status == 409 else ""
        if not rid:
            raise _step_error(refused, "ingest") from refused
        log.warning("an ingest is already running on the adapter (run %s): this job follows it", rid)
        return {"run": rid, "state": "running"}  # read by the poll, which bears silence up to its declared bound

    def run(self, req: IngestRequest) -> IngestReport:
        return self.run_followed(req, None)

    def publish(self, body: dict[str, Any]) -> dict[str, Any]:
        """NEW-SEC-4 (D-760): start the publish of a held night (the steward's accept, checked by the caller's route);
        the adapter's answer (202 and a run id) as it is. A refusal (404, 409) is raised as the ``ServiceError``."""
        out: dict[str, Any] = self.c.post_raw("/publish", body).json()
        return out

    def publish_state(self, rid: str) -> dict[str, Any]:
        out: dict[str, Any] = self.c.get_json(f"/publish/{rid}")
        return out

    def run_followed(self, req: IngestRequest, on_run: Callable[[str, bool], None] | None) -> IngestReport:
        """:meth:`run`, telling the caller which adapter run the job is on as soon as it is known
        (``on_run(run id, followed)``: ``followed`` when the run was already running and this call did not start
        it), so that the job can write it into its record before the run ends."""
        from tb_common.jobpoll import JobLost, Poll

        followed = False
        try:
            started = self.c.post_raw("/run", req).json()
        except ServiceError as exc:
            started, followed = self._running(exc), True
        rid = str(started.get("run") or "")
        if on_run is not None and rid:
            on_run(rid, followed)

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
        signalled = _ingest_signalled(st, rid)  # F-44: by the recorded number, never by the record's words
        if signalled is not None:
            raise signalled
        # D-557: the adapter's "failed" detail is an error's type and up to 500 characters of its text (a cast
        # error quotes the value it could not cast); the job's record keeps the type, the adapter's log the rest
        raise StepFailed("ingest", _ingest_ended(st), f"adapter run {rid}")
