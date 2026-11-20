"""mail-gateway HTTP service (SPEC §4.1): ``POST /send`` for the orchestrator, ``POST /poll`` (manual intake run);
the IMAP poller and the outbox dispatcher (T-108c, D-401) run every ``TB_MAIL_POLL_SECONDS`` (default 60) while the
app is up. A send that could not go out yet answers 202 with ``X-TB-Mail-State`` (queued, uncertain, failed): the
caller's job is not failed by a mail outage; ``trialbox mail status`` and ``mail resolve`` show and settle it."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from tb_common.audit_writer import open_audit
from tb_common.config import environment_name, get_config
from tb_common.http import make_app
from tb_common.objstore import from_config
from tb_contracts import SendRequest, SendResult

from mail_gateway.gateway import (
    PER_RECIPIENT_PER_DAY,
    Gateway,
    http_job_sink,
    http_outputs_current,
    http_support_session,
    log,
)
from mail_gateway.outbound import EncryptionError, RoutingRefused, smtp_transport
from mail_gateway.store import MailDB, SendUncertain

_gw: Gateway | None = None


def gateway() -> Gateway:
    global _gw
    if _gw is None:
        cfg = get_config()
        env = cfg.env
        authserv = os.environ.get("TB_MAIL_AUTHSERV_ID", "").strip()
        if not authserv:  # D-369 (SEC-11): fails closed
            log.error(
                "TB_MAIL_AUTHSERV_ID is not set: no sender can be authenticated, so every request mail is refused "
                "and nothing is sent back. Set it to the authserv-id of the hospital MTA (RUNBOOK, mail)."
            )
        _gw = Gateway(
            cfg=cfg,
            store=from_config(),
            db=MailDB(),  # schema "mail" of the trial database (TB_DB_URL, D-126)
            audit=open_audit(env.audit_path, env.tz),
            transport=smtp_transport(env.smtp_host, env.smtp_port, env.smtp_user, env.smtp_pass, env.smtp_starttls),
            jobs=http_job_sink(env.orchestrator_url),
            outputs_current=http_outputs_current(env.orchestrator_url),  # D-863: asked before a patient file leaves
            support_session=http_support_session(env.orchestrator_url),  # D-1364 (H5): mail held during a session
            secrets_dir=Path(env.secrets_dir),
            authserv_id=authserv,
            # D-369 (OD-1): a password zip for patient files only on a synthetic box
            allow_phi_zip=environment_name(os.environ) in ("DEV", "TEST"),
            per_recipient_per_day=int(os.environ.get("TB_MAIL_PER_RECIPIENT_PER_DAY", "") or PER_RECIPIENT_PER_DAY),
        )
    return _gw


def outbox_loop(gw: Gateway, stop: threading.Event, interval: float) -> None:
    """The outbox dispatcher (T-108c): queued sends are tried again when due; a stale ``sending`` key is marked."""
    while not stop.wait(interval):
        try:
            done = gw.drain()
            if done:
                log.info("outbox: %s", done)
        except Exception:  # the database or the store is down: the next pass tries again
            log.exception("outbox pass failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    stop = threading.Event()
    interval = float(os.environ.get("TB_MAIL_POLL_SECONDS", "60"))
    threads: list[threading.Thread] = []
    if interval > 0 and gateway().cfg.env.imap_user:
        threads.append(threading.Thread(target=gateway().loop, args=(stop, interval), name="imap-poll", daemon=True))
    if interval > 0:
        threads.append(
            threading.Thread(target=outbox_loop, args=(gateway(), stop, interval), name="outbox", daemon=True)
        )
    for t in threads:
        t.start()
    try:
        yield
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)


def _mode() -> dict[str, Any]:
    gw = gateway()
    return {"encryption": gw.mode, "sender_auth": "on" if gw.authserv_id else "closed: TB_MAIL_AUTHSERV_ID unset"}


def _db() -> dict[str, Any]:
    """The mail store answers (D-142, review A-02): a lost connection is reopened, a dead database is a 503."""
    return gateway().db.db.ping()


def _outbox() -> dict[str, Any]:
    """Sends not yet out (T-108c): reported, never a health failure; ``trialbox mail status`` lists them."""
    return {"outbox": gateway().db.counts()}


app = make_app("mail-gateway", checks=[_mode, _db, _outbox], lifespan=lifespan, protect_reads=True)  # D-130: threads


@app.post("/send")
def send(req: SendRequest, response: Response) -> SendResult:
    try:
        out = gateway().deliver(req)
        if out.state not in ("sent", "duplicate"):
            response.status_code = 202  # accepted, not sent yet: the outbox or a person finishes it (T-108c)
        response.headers["X-TB-Mail-State"] = out.state
        return out.result
    except RoutingRefused as exc:
        raise HTTPException(status_code=422, detail={"step": "routing", "message": str(exc)}) from exc
    except EncryptionError as exc:
        raise HTTPException(status_code=422, detail={"step": "mail", "message": str(exc)}) from exc
    except SendUncertain as exc:  # D-127 (F-02): may have left already; a person must check, never an automatic resend
        raise HTTPException(status_code=409, detail={"step": "mail", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=422, detail={"step": "mail", "message": "an attachment was not found in the store"}
        ) from exc


@app.get("/threads/{job_id}")
def thread(job_id: str) -> dict[str, Any]:
    """Mail of one job (metadata only) for the admin console's thread view."""
    return {"job_id": job_id, "items": gateway().db.thread(job_id)}


@app.post("/poll")
def poll() -> dict[str, int]:
    return {"processed": gateway().poll_once()}
