"""F-44 (a): an ingest whose process a signal ended says which signal, in its run, its log and its job.

A 50,000-patient synthetic night on the bench host: the kernel ended the ingest's process at the adapter's memory
limit (SIGKILL, return code -9). The adapter took the exit code only when it was above 0, so the run kept the
generic "ended without an answer", no log line was written, and the job's failure gave no reason. Now the run names
the signal by its number and name (SIGKILL adds that the memory limit is the usual cause), the adapter writes one
line with the step, the run and the signal, and the orchestrator's job says it from a catalogue key in the job's
language (en, ja, zh-TW) and logs its failed step. Decided by the return code only. Synthetic data only."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from adapter import app as adapter_app  # imported once, before a test: it sets up the service's logging
from adapter import runs
from orchestrator import i18n
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import IngestRequest, JobCreate, SendRequest, SendResult

ROOT = Path(__file__).resolve().parents[2]
RID = "5eed0f44"


def _killed_by(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, number: int) -> dict[str, Any]:
    """One ingest run whose process sends itself signal ``number`` as it starts (as the kernel does at the memory
    limit), waited for as the service waits for it."""
    child = f"import os; os.kill(os.getpid(), {number})"
    monkeypatch.setattr(adapter_app, "_run_command", lambda fd, spec: [sys.executable, "-c", child])
    state: dict[str, Any] = {
        "run": RID,
        "state": "running",
        "started": "2026-10-04T01:00:00+00:00",
        "ended": None,
        "detail": "",
    }
    adapter_app._run_in_process(state, tmp_path / "lake", {"source": "csv"})
    return state


@pytest.mark.parametrize(("number", "name", "memory"), [(9, "SIGKILL", True), (15, "SIGTERM", False)])
def test_a_run_ended_by_a_signal_names_it_and_leaves_one_log_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    number: int,
    name: str,
    memory: bool,
) -> None:
    with caplog.at_level(logging.INFO, logger="adapter"):
        st = _killed_by(monkeypatch, tmp_path, number)
    assert st["state"] == "failed" and st["ended"]
    assert st["detail"] != runs.ENDED_WITHOUT_ANSWER and f"signal {number} ({name})" in st["detail"]
    assert st["exit_signal"] == number
    assert ("memory limit" in st["detail"]) is memory
    assert runs.read(tmp_path / "lake", RID) == st  # the record on disk says the same
    lines = [r for r in caplog.records if r.name == "adapter" and r.levelno >= logging.WARNING]
    assert len(lines) == 1, [r.getMessage() for r in lines]
    said = lines[0].getMessage()
    assert "ingest" in said and RID in said and f"signal {number} ({name})" in said


def test_a_run_that_exits_by_itself_keeps_its_exit_code_and_no_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(adapter_app, "_run_command", lambda fd, spec: [sys.executable, "-c", "raise SystemExit(3)"])
    state: dict[str, Any] = {
        "run": RID,
        "state": "running",
        "started": "2026-10-04T01:00:00+00:00",
        "ended": None,
        "detail": "",
    }
    adapter_app._run_in_process(state, tmp_path / "lake", {"source": "csv"})
    assert state["state"] == "failed" and "exit code 3" in state["detail"] and "exit_signal" not in state


def _adapter(answer: dict[str, Any]) -> Any:
    """The orchestrator's adapter client, against an adapter whose run ended with ``answer``."""
    from orchestrator.clients import AdapterHttp

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"run": RID, "state": "running"})
        return httpx.Response(200, json={"run": RID, **answer})

    from tests.unit.test_polled_jobs import Clock, _poll

    ad = AdapterHttp("http://adapter", poll=_poll(Clock()))
    ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
    return ad


#: the adapter's record of a run the kernel ended (its words, as ``runs.ended_by_signal(9)`` writes them)
SAID = "the ingest's process ended without an answer: it was ended by signal 9 (SIGKILL)"
KILLED = {"state": "failed", "detail": SAID, "exit_signal": 9}


def test_the_ingest_steps_failure_names_the_signal_and_the_memory_limit() -> None:
    from orchestrator.clients import StepFailed

    with pytest.raises(StepFailed) as failed:
        _adapter(KILLED).run(IngestRequest(source="csv"))
    exc = failed.value
    assert exc.step == "ingest" and exc.message == i18n.t("en", "ingest.signal_kill", number=9, name="SIGKILL")
    assert "signal 9 (SIGKILL)" in exc.message and "memory limit" in exc.message
    assert runs.ENDED_WITHOUT_ANSWER not in exc.message and RID in exc.detail and "signal 9" in exc.detail
    with pytest.raises(StepFailed) as other:
        _adapter({"state": "failed", "detail": "ended by signal 15", "exit_signal": 15}).run(
            IngestRequest(source="csv")
        )
    assert other.value.message == i18n.t("en", "ingest.signal", number=15, name="SIGTERM")
    assert "memory" not in other.value.message


def test_the_reason_is_decided_by_the_number_never_by_the_records_words() -> None:
    from orchestrator.clients import StepFailed

    with pytest.raises(StepFailed) as failed:  # the words of a kill and no number: the adapter's sentence as before
        _adapter({"state": "failed", "detail": SAID}).run(IngestRequest(source="csv"))
    assert failed.value.message == SAID
    assert not hasattr(failed.value, "key")
    for odd in (True, "9", 0, -9):  # not a signal's number
        with pytest.raises(StepFailed) as again:
            _adapter({"state": "failed", "detail": "the source folder is empty", "exit_signal": odd}).run(
                IngestRequest(source="csv")
            )
        assert again.value.message == "the source folder is empty"


def test_the_catalogue_says_it_in_each_language() -> None:
    for lang in i18n.LANGS:
        for key in ("ingest.signal", "ingest.signal_kill"):
            text = i18n.T[lang][key].format(number=9, name="SIGKILL")
            assert "9" in text and "SIGKILL" in text, (lang, key)
    assert i18n.T["ja"]["ingest.signal_kill"] != i18n.T["en"]["ingest.signal_kill"]
    assert i18n.T["zh-TW"]["ingest.signal_kill"] != i18n.T["en"]["ingest.signal_kill"]


class _Mail:
    def __init__(self) -> None:
        self.sent: list[SendRequest] = []

    def send(self, req: SendRequest) -> SendResult:
        self.sent.append(req)
        return SendResult(message_id=f"<{len(self.sent)}@t>", sent_to=req.to, encrypted=bool(req.encrypt))


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_job_says_it_in_its_language_and_logs_its_failed_step(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, lang: str
) -> None:
    mail = _Mail()

    def ingest_like(ctx: Ctx) -> Outcome:
        ctx.state("running")
        _adapter(KILLED).run(IngestRequest(source="csv"))
        return Outcome(summary_md="not reached")

    cfg = Config(
        env=load_env(dotenv=tmp_path / "x.env", environ={}),
        settings=load_settings(ROOT / "deploy/settings.example.yaml"),
    )
    nothing = cast(Any, None)
    services = Services(lake=nothing, parser=nothing, compiler=nothing, mail=mail)
    orch = Orchestrator(
        cfg,
        JobDB(),
        FsStore(tmp_path / "obj"),
        AuditLog(tmp_path / "audit"),
        services,
        {"SCREEN": ingest_like},
        tmp_path / "rulesets",
        tmp_path,
        today=lambda: date(2026, 10, 5),
        workers=0,
        async_notify=False,
    )
    job_id = orch.create(
        JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test", options={"lang": lang})
    ).job_id
    with caplog.at_level(logging.INFO, logger="orchestrator"):
        orch.drain()
    job = orch.db.get(job_id)
    assert job is not None and job.state == "failed" and job.error is not None
    assert job.error.step == "ingest"
    assert job.error.message == i18n.t(lang, "ingest.signal_kill", number=9, name="SIGKILL")
    assert any(job.error.message in (m.body_md or "") for m in mail.sent)  # the Failed mail gives it
    lines = [
        r.getMessage() for r in caplog.records if r.name.startswith("orchestrator") and r.levelno >= logging.WARNING
    ]
    mine = [m for m in lines if job_id in m and "ingest" in m]
    assert len(mine) == 1 and "signal 9 (SIGKILL)" in mine[0], lines
