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
from tb_common.config import get_config
from tb_common.http import make_app
from tb_common.objstore import from_config
from tb_contracts import SendRequest, SendResult

from mail_gateway.gateway import Gateway, http_job_sink
from mail_gateway.outbound import EncryptionError, RoutingRefused, smtp_transport
from mail_gateway.store import MailDB

_gw: Gateway | None = None


def gateway() -> Gateway:
    global _gw
    if _gw is None:
        cfg = get_config()
        env = cfg.env
        data = Path(os.environ.get("TB_MAIL_DIR", str(Path(env.data_dir) / "mail")))
        _gw = Gateway(
            cfg=cfg,
            store=from_config(),
            db=MailDB(data / "mail.sqlite"),
            audit=AuditLog(env.audit_path, env.tz),
            transport=smtp_transport(env.smtp_host, env.smtp_port, env.smtp_user, env.smtp_pass, env.smtp_starttls),
            jobs=http_job_sink(env.orchestrator_url),
            secrets_dir=Path(env.secrets_dir),
            authserv_id=os.environ.get("TB_MAIL_AUTHSERV_ID", ""),
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
    return {"encryption": gateway().mode}


app = make_app("mail-gateway", checks=[_mode], lifespan=lifespan)


@app.post("/send")
def send(req: SendRequest) -> SendResult:
    try:
        return gateway().send(req)
    except RoutingRefused as exc:
        raise HTTPException(status_code=422, detail={"step": "routing", "message": str(exc)}) from exc
    except EncryptionError as exc:
        raise HTTPException(status_code=422, detail={"step": "mail", "message": str(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=422, detail={"step": "mail", "message": f"attachment not found: {exc}"}
        ) from exc


@app.post("/poll")
def poll() -> dict[str, int]:
    return {"processed": gateway().poll_once()}
