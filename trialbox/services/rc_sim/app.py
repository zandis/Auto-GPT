"""REDCap API simulator (TB-DS-08 §4.4, ICD-04S), written from the public REDCap API documentation only.

``POST /api/`` takes the same form fields as REDCap (``token``, ``content``, ``format=json``) and answers R1 version,
R2 project, R3 metadata, R7 record (flat export with ``records[]``/``fields[]``/``events[]``/``dateRangeBegin`` and
``exportDataAccessGroups``) and R8 dag. Every other ``content`` answers 501. Each fixture project has its own 32-hex
token; a wrong token answers 403 with REDCap's error text. ``POST /sim/records`` adds or edits a record (the test and
demo lever) and stamps its change time, which ``dateRangeBegin`` filters on.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SUPPORTED = {"version", "project", "metadata", "record", "dag"}
NO_PERMISSION = "You do not have permissions to use the API"


def load_projects(fixtures_dir: Path = FIXTURES) -> dict[str, dict[str, Any]]:
    """Read every ``*.json`` fixture project, keyed by its API token."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(fixtures_dir).glob("*.json")):
        proj = json.loads(path.read_text(encoding="utf-8"))
        out[str(proj["token"]).upper()] = proj
    return out


def _form_list(form: Any, name: str) -> list[str]:
    """REDCap accepts ``name[0]=a&name[1]=b``, ``name[]=a`` or a comma list in ``name``."""
    vals: list[str] = []
    for key, val in form.multi_items():
        if key in (name, f"{name}[]") or (key.startswith(f"{name}[") and key.endswith("]")):
            vals.extend(v.strip() for v in str(val).split(",") if v.strip())
    return vals


def _local_now() -> str:
    """REDCap stamps changes in its server's local time; the simulator uses the site zone (``TB_TZ``)."""
    try:
        zone: Any = ZoneInfo(os.environ.get("TB_TZ") or "Asia/Taipei")
    except Exception:
        zone = None
    return datetime.now(zone).replace(microsecond=0, tzinfo=None).isoformat()


def _err(status: int, msg: str) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status)


class SimState:
    def __init__(self, projects: dict[str, dict[str, Any]], version: str, rate_limit: int | None) -> None:
        self.projects = projects
        self.version = version
        self.rate_limit = rate_limit
        self.calls: list[float] = []
        self.lock = threading.Lock()

    def by_pid(self, project_id: int) -> dict[str, Any] | None:
        return next((p for p in self.projects.values() if int(p["project"]["project_id"]) == project_id), None)

    def limited(self) -> bool:
        if not self.rate_limit:
            return False
        now = time.monotonic()
        with self.lock:
            self.calls = [t for t in self.calls if now - t < 60.0]
            if len(self.calls) >= self.rate_limit:
                return True
            self.calls.append(now)
        return False


def _record_id_field(proj: dict[str, Any]) -> str:
    return str(proj["metadata"][0]["field_name"])


def _export_records(proj: dict[str, Any], form: Any) -> list[dict[str, Any]]:
    want_records = set(_form_list(form, "records"))
    want_fields = _form_list(form, "fields")
    want_events = set(_form_list(form, "events"))
    since = str(form.get("dateRangeBegin") or "").strip()
    with_dag = str(form.get("exportDataAccessGroups") or "").lower() == "true"
    longitudinal = bool(int(proj["project"].get("is_longitudinal", 0)))
    rid = _record_id_field(proj)
    known = [m["field_name"] for m in proj["metadata"]]
    if want_fields:
        cols = [rid] + [f for f in want_fields if f in known and f != rid]
    else:
        cols = list(known)
    rows: list[dict[str, Any]] = []
    for rec in proj["records"]:
        if want_records and str(rec.get(rid)) not in want_records:
            continue
        if want_events and rec.get("redcap_event_name") not in want_events:
            continue
        if since and str(rec.get("_changed", "")).replace("T", " ") < since.replace("T", " "):
            continue
        row: dict[str, Any] = {rid: str(rec.get(rid, ""))}
        if longitudinal:
            row["redcap_event_name"] = rec.get("redcap_event_name", "")
        if with_dag:
            row["redcap_data_access_group"] = rec.get("redcap_data_access_group", "")
        for col in cols:
            if col != rid:
                row[col] = str(rec.get(col, ""))
        rows.append(row)
    return rows


def create_app(fixtures_dir: Path | None = None, version: str | None = None, rate_limit: int | None = None) -> FastAPI:
    """Build a simulator app (each app holds its own copy of the fixtures, so tests stay independent)."""
    state = SimState(
        copy.deepcopy(load_projects(fixtures_dir or FIXTURES)),
        version or os.environ.get("TB_RC_SIM_VERSION", "16.0.10"),
        rate_limit,
    )
    app = FastAPI(title="trialbox-rc-sim")
    app.state.sim = state

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": "rc_sim", "projects": len(state.projects), "version": state.version}

    @app.post("/api/")
    async def api(request: Request) -> Any:
        form = await request.form()
        if state.limited():
            return _err(429, "Too many API requests")
        token = str(form.get("token") or "").strip().upper()
        proj = state.projects.get(token)
        if proj is None:
            return _err(403, NO_PERMISSION)
        content = str(form.get("content") or "")
        if str(form.get("format") or "json") != "json":
            return _err(400, "This simulator answers format=json only")
        if content not in SUPPORTED:
            return _err(501, f"The content '{content}' is not supported by the TrialBox REDCap simulator")
        if content == "version":
            return JSONResponse(state.version)
        if content == "project":
            return proj["project"]
        if content == "metadata":
            fields = set(_form_list(form, "fields"))
            return [m for m in proj["metadata"] if not fields or m["field_name"] in fields]
        if content == "dag":
            return proj["dags"]
        if str(form.get("type") or "flat") != "flat":
            return _err(400, "Only type=flat is supported")
        return _export_records(proj, form)

    @app.post("/sim/records")
    async def sim_records(request: Request) -> Any:
        """Add or edit records: ``{"project_id": 101, "records": [{...}]}``; unknown fields are refused."""
        body = await request.json()
        proj = state.by_pid(int(body.get("project_id", 0)))
        if proj is None:
            return _err(404, "No such project")
        rid = _record_id_field(proj)
        known = {m["field_name"] for m in proj["metadata"]} | {"redcap_event_name", "redcap_data_access_group"}
        stamp = str(body.get("at") or _local_now())
        n = 0
        for new in body.get("records", []):
            bad = set(new) - known
            if bad:
                return _err(400, f"Unknown fields: {', '.join(sorted(bad))}")
            key = (str(new.get(rid)), new.get("redcap_event_name"))
            hit = next((r for r in proj["records"] if (str(r.get(rid)), r.get("redcap_event_name")) == key), None)
            if hit is None:
                hit = {f: "" for f in known if f in {m["field_name"] for m in proj["metadata"]}}
                proj["records"].append(hit)
            hit.update({k: str(v) for k, v in new.items()})
            hit["_changed"] = stamp
            n += 1
        return {"count": n}

    @app.post("/sim/metadata/rename")
    async def sim_rename(request: Request) -> Any:
        """Rename a field in the data dictionary (lets a test break a link: RC-LINK-FIELD)."""
        body = await request.json()
        proj = state.by_pid(int(body.get("project_id", 0)))
        if proj is None:
            return _err(404, "No such project")
        old, new = str(body["old"]), str(body["new"])
        for m in proj["metadata"]:
            if m["field_name"] == old:
                m["field_name"] = new
        for r in proj["records"]:
            if old in r:
                r[new] = r.pop(old)
        return {"renamed": old, "to": new}

    return app


app = create_app()
INPROC_URL = "inproc://rc-sim"


def register_inproc(sim: FastAPI | None = None, replace: bool = True) -> None:
    """Route ``inproc://rc-sim`` in rc-bridge to this simulator (the module-level app unless one is given).
    ``replace=False`` (the orchestrator's DEV/TEST default) never overrides a simulator a demo registered first."""
    from fastapi.testclient import TestClient
    from rc_bridge.client import register_local

    target = sim or app
    register_local(INPROC_URL, lambda: TestClient(target, base_url="http://rc-sim"), replace=replace)


def main() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run(
        app, host=os.environ.get("TB_RC_SIM_HOST", "127.0.0.1"), port=int(os.environ.get("TB_RC_SIM_PORT", "8790"))
    )


if __name__ == "__main__":  # pragma: no cover
    main()
