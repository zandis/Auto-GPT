"""M5 (10K-16, SO-16): the data step (``/admin/data-step``): SS-MIX2 as the set-up's data step, count-only.

After the install, the box reads the hospital's SS-MIX2 storage (a read-only copy or mount) each night. This page is
the step that says whether that read has happened and what it found, in counts only:

* the newest SS-MIX2 night (``ingest.done``, ``ingest.held`` or ``ingest.failed`` with ``source: ssmix2``): when,
  and whether its rows went in, were held at the gate, or failed;
* **counts per type**: the night's resources per type (the adapter's ``counts``) and their total;
* **coverage lines**: the site profile's summary the night carries (``adapter.site_profile.summary``): declared types
  arrived, declared but none arrived, not read by this version, arrived undeclared, codes and rows no table maps,
  table rows still to verify. A night read without a site profile says so.

The step is done when the newest night's rows went in. Nothing here reads the storage or the lake: the page reads the
night's audit event (:func:`nights`), keeping counts and type names only, never a patient's value. Who may read it: the
administrator (``authz.admin_allowed(role, "ops.view")``). ``GET /api/v1/admin/data-step`` is the page's twin.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request, Response
from tb_common.authz import admin_allowed

from console.health_page import NIGHT_EVENTS, aware
from console.home import Helpers
from console.i18n import CATALOGUES
from console.i18n_m5 import EN, JA, ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

PATH = "/admin/data-step"
SOURCE = "ssmix2"
STATES = {"ingest.done": "in", "ingest.held": "held", "ingest.failed": "failed"}
#: the coverage numbers and lists the page shows, from the night's site profile summary
COVER_NUMBERS = ("types_declared", "types_arrived", "unmapped_codes", "unmapped_rows", "verify_rows")
COVER_LISTS = ("not_arrived", "not_read", "not_declared")


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _map(v: Any) -> Mapping[str, Any] | None:
    return v if isinstance(v, Mapping) else None


def nights(directory: Path) -> list[SimpleNamespace]:
    """The SS-MIX2 night events of the newest day file of the audit chain that holds any, read with the count-only
    projection: the counts per type (type names and numbers) and the site profile summary's numbers and type lists.
    The console's audit reader (``console.backend.read_audit``) keeps an ingest's totals only, so the page reads the
    chain itself; nothing else of a record is kept."""
    files = sorted(directory.glob("*.jsonl"), reverse=True) if directory.is_dir() else []
    for path in files:
        out: list[SimpleNamespace] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            if '"ingest.' not in raw or SOURCE not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            det = rec.get("detail") if isinstance(rec, dict) else None
            if not isinstance(det, dict) or rec.get("event") not in NIGHT_EVENTS or det.get("source") != SOURCE:
                continue
            counts = _map(det.get("counts")) or {}
            prof = _map(det.get("site_profile"))
            kept: dict[str, Any] = {
                "source": SOURCE,
                "counts": {str(k): n for k, v in counts.items() if (n := _int(v)) is not None},
            }
            if prof is not None:
                kept["site_profile"] = {k: prof.get(k) for k in (*COVER_NUMBERS, *COVER_LISTS, "id", "version")}
            out.append(SimpleNamespace(event=rec["event"], ts=str(rec.get("ts") or ""), detail=kept))
        if out:
            return out
    return []


def step(records: Iterable[Any]) -> dict[str, Any]:
    """The step from the audit's night records (any order): ``done``, ``state``, ``at``, ``counts`` (type to count,
    sorted), ``total`` and ``coverage`` (None: read without a site profile)."""
    newest: tuple[Any, Any] | None = None
    for r in records:
        if r.event not in NIGHT_EVENTS or str((r.detail or {}).get("source") or "") != SOURCE:
            continue
        if (at := aware(r.ts)) is not None and (newest is None or at > newest[0]):
            newest = (at, r)
    if newest is None:
        return {"done": False, "state": "none", "at": "", "counts": [], "total": 0, "coverage": None}
    at, rec = newest
    detail = rec.detail or {}
    raw = _map(detail.get("counts")) or {}
    counts = sorted((str(k), n) for k, v in raw.items() if (n := _int(v)) is not None)
    prof = _map(detail.get("site_profile"))
    coverage: dict[str, Any] | None = None
    if prof is not None:
        coverage = {k: _int(prof.get(k)) or 0 for k in COVER_NUMBERS}
        coverage.update({k: [str(x) for x in (prof.get(k) or [])] for k in COVER_LISTS})
        coverage["profile"] = f"{prof.get('id') or '?'} {prof.get('version') or ''}".strip()
    state = STATES[rec.event]
    return {"done": state == "in", "state": state, "at": at.isoformat(timespec="minutes"), "counts": counts,
            "total": sum(n for _, n in counts), "coverage": coverage}  # fmt: skip


def register(app: FastAPI, h: Helpers, env: Mapping[str, str] | None = None) -> None:
    def chain() -> Path:
        where = getattr(h.au, "directory", None) or (env or {}).get("TB_AUDIT_DIR") or "/data/audit"
        return Path(where)

    def need_admin(request: Request, sess: Any) -> Any:
        if not admin_allowed(sess.user.role, "ops.view"):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    @app.get(PATH)
    def data_step_page(request: Request) -> Response:
        sess = need_admin(request, h.need(request))
        return h.page(request, "data_step.html", sess, st=step(nights(chain())))

    @app.get("/api/v1" + PATH, response_model=None)
    def api_data_step(request: Request) -> Any:
        assert h.api_session is not None  # set by register() before any request
        need_admin(request, h.api_session(request))
        st = step(nights(chain()))
        return {**st, "counts": dict(st["counts"])}
