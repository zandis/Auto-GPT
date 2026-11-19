"""The console's ``/metrics`` and the box's health now (T-209a, D-379; review OPS-027).

:func:`health` joins the host's facts (the operations status ``trialbox ops run`` writes each minute:
``tb_common.metrics.host_facts``) with the orchestrator's canary (``/models``) and evaluates them with the
thresholds of ``tb_common.metrics``. The coordinator's morning mail carries it as one line and the administrators'
daily health mail as one line per check (``console.notify``).

``GET /metrics`` gives the same health in the Prometheus text format. Who may read it: a scraper with the metrics
token (``Authorization: Bearer``; the token is the content of ``TB_METRICS_TOKEN_FILE``, made by
``trialbox ops metrics-token`` and mounted by ``deploy/docker-compose.monitoring.yml``), or a signed-in
administrator. Everyone else gets 401 or 403. It carries counts, ages and percentages only: no patient, no user name.
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from tb_common import metrics

from console.home import Helpers


def metrics_token(env: Any = None) -> str:
    """The scraper's token, read from ``TB_METRICS_TOKEN_FILE`` at each call (a rotation needs no restart); empty
    when there is none, and then only an administrator reads ``/metrics``."""
    e = os.environ if env is None else env
    path = str(e.get("TB_METRICS_TOKEN_FILE") or "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def register(app: FastAPI, h: Helpers) -> None:
    def health() -> metrics.Health:
        now = h.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        st = h.ops_status() if h.ops_status is not None else {}
        try:
            models = h.bk.models()
        except Exception:  # the orchestrator is down: the canary check says unknown
            models = None
        canary = (models or {}).get("canary") if isinstance(models, dict) else None
        worker = (models or {}).get("optout_worker") if isinstance(models, dict) else None  # D-441
        derive = (models or {}).get("derive_batch") if isinstance(models, dict) else None  # D-442
        out = metrics.evaluate((st or {}).get("health"), canary, now, optout=worker, derive=derive)
        # 10C-14: a site with a holiday list says when it runs out or a working-day setting is not used
        from tb_common import workdays

        from console.notify import site_calendar

        line = workdays.health(site_calendar(h), h.today())
        if line is None:
            return out
        return metrics.Health(out.at, (*out.checks, metrics.Check("calendar", line[0], line[1])))

    h.health = health

    @app.get("/metrics")
    def metrics_route(request: Request) -> Response:
        auth = request.headers.get("authorization") or ""
        bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        want = metrics_token()
        if not (bearer and want and hmac.compare_digest(bearer.encode(), want.encode())):
            if bearer:
                assert h.api_session is not None
                sess = h.api_session(request)
            else:
                sess = h.need(request)
            if not sess.user.is_admin:
                h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
                raise h.problem(403, "forbidden")
        body = metrics.prometheus(health(), "console")
        return Response(body, media_type="text/plain; version=0.0.4; charset=utf-8")
