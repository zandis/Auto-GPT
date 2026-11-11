"""mail-gateway HTTP service (SPEC §4.1): ``POST /send`` for the orchestrator, ``POST /poll`` (manual intake run);
the IMAP poller runs every ``TB_MAIL_POLL_SECONDS`` (default 60) while the app is up."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from tb_common.audit import AuditLog
from tb_common.config import environment_name, get_config
from tb_common.http import make_app
from tb_common.objstore import from_config
from tb_contracts import SendRequest, SendResult

from mail_gateway.gateway import Gateway, http_job_sink, log
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
            audit=AuditLog(env.audit_path, env.tz),
            transport=smtp_transport(env.smtp_host, env.smtp_port, env.smtp_user, env.smtp_pass, env.smtp_starttls),
            jobs=http_job_sink(env.orchestrator_url),
            secrets_dir=Path(env.secrets_dir),
            authserv_id=authserv,
            # D-369 (OD-1): a password zip for patient files only on a synthetic box
            allow_phi_zip=environment_name(os.environ) in ("DEV", "TEST"),
        )
    return _gw


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    stop = threading.Event()
    interval = float(os.environ.get("TB_MAIL_POLL_SECONDS", "60"))
    thread = None
    if interval > 0 and gateway().cfg.env.imap_user:
        thread = threading.Thread(target=gateway().loop, args=(stop, interval), name="imap-poll", daemon=True)
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=10)


def _mode() -> dict[str, Any]:
    gw = gateway()
    return {"encryption": gw.mode, "sender_auth": "on" if gw.authserv_id else "closed: TB_MAIL_AUTHSERV_ID unset"}


def _db() -> dict[str, Any]:
    """The mail store answers (D-142, review A-02): a lost connection is reopened, a dead database is a 503."""
    return gateway().db.db.ping()


app = make_app("mail-gateway", checks=[_mode, _db], lifespan=lifespan, protect_reads=True)  # D-130: threads


@app.post("/send")
def send(req: SendRequest) -> SendResult:
    try:
        return gateway().send(req)
    except RoutingRefused as exc:
        raise HTTPException(status_code=422, detail={"step": "routing", "message": str(exc)}) from exc
    except EncryptionError as exc:
        raise HTTPException(status_code=422, detail={"step": "mail", "message": str(exc)}) from exc
    except SendUncertain as exc:  # D-127 (F-02): may have left already; a person must check, never an automatic resend
        raise HTTPException(status_code=409, detail={"step": "mail", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=422, detail={"step": "mail", "message": f"attachment not found: {exc}"}
        ) from exc


@app.get("/threads/{job_id}")
def thread(job_id: str) -> dict[str, Any]:
    """Mail of one job (metadata only) for the admin console's thread view."""
    return {"job_id": job_id, "items": gateway().db.thread(job_id)}


@app.post("/poll")
def poll() -> dict[str, int]:
    return {"processed": gateway().poll_once()}
