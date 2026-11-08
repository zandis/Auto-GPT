"""Orchestrator API of TrialBox's own data core (D-123): forms, entry, sources, sync and conflicts.

* ``GET /studies/{rs}/forms``; ``POST /studies/{rs}/forms/dictionary`` (a REDCap data dictionary CSV -> one
  Questionnaire per instrument; identifier fields dropped).
* ``GET /studies/{rs}/data`` (records, fields, owners, values); ``PUT /studies/{rs}/data/{record}`` (a person enters
  values; a field owned by a source is refused with DATA-OWNED).
* ``PUT /studies/{rs}/sources/redcap`` (attach REDCap: token, field map, the fields REDCap owns, create on push);
  ``DELETE`` detaches (every field is TrialBox's again); ``POST /studies/{rs}/sync/{name}`` runs the two-way sync;
  ``GET /studies/{rs}/sources`` lists the sources and each field's owner, without any value (the console's page).
* ``GET /studies/{rs}/conflicts``; ``POST /studies/{rs}/conflicts/{id}`` with ``keep`` = ``theirs`` | ``trialbox``.
* ``GET /studies/{rs}/fhir`` (the Questionnaires and QuestionnaireResponses for HAPI).

With no source attached TrialBox works on its own data: entry, lists and the trial lifecycle never need REDCap.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from datacore import fhir, forms, sync
from datacore.sources import RedcapSource
from datacore.store import DataCore, DataError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from rc_bridge.client import RcError, RedcapClient
from tb_common.audit import AuditLog

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass
class DataService:
    dc: DataCore
    audit: AuditLog
    now: Callable[[], datetime]
    client: Callable[[str], RedcapClient]  # token_ref -> client (the study store's tokens)
    site_key: Callable[[], bytes] | None = None  # the site HMAC key (chart number -> pseudonym), read only

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def redcap(self, rs: str) -> RedcapSource | None:
        cfg = next((s["body"] for s in self.dc.sources(rs) if s["name"] == "redcap"), None)
        if cfg is None:
            return None
        ref = str(cfg["token_ref"])
        return RedcapSource(lambda: self.client(ref), key_field=str(cfg.get("key_field") or "tb_screening_no"),
                            field_map=dict(cfg["field_map"]), event=str(cfg.get("event") or ""),
                            create=bool(cfg.get("create")), dag=str(cfg.get("dag") or ""))  # fmt: skip

    def run_sync(self, rs: str, name: str, by: str) -> dict[str, Any]:
        src = self.redcap(rs) if name == "redcap" else None
        if src is None:
            raise HTTPException(status_code=404, detail={"code": "DATA-SOURCE", "message": f"no source {name}"})
        at = self.stamp()
        res = sync.sync(self.dc, rs, src, by, at).as_dict()
        self.dc.synced(rs, name, at, res)
        self.audit.append("data.sync", ruleset=rs, actor=by,
                          detail={"source": name, "pulled": res["pulled"], "taken": res["taken"],
                                  "pushed": res["pushed"], "conflicts": len(res["conflicts"])})  # fmt: skip
        return {**res, "at": at}


class DictionaryBody(BaseModel):
    csv: str
    record_field: str = ""
    by: str


class EntryBody(BaseModel):
    event: str = ""
    values: dict[str, str]
    by: str


class RedcapSourceBody(BaseModel):
    token_ref: str
    field_map: dict[str, str]  # REDCap field -> TrialBox field
    owned: list[str] = Field(default_factory=list)  # TrialBox field names REDCap owns
    key_field: str = "tb_screening_no"
    event: str = ""
    dag: str = ""
    create: bool = False
    by: str


class SheetBody(BaseModel):
    """A PI's spreadsheet, one import (TB-PLAN-04 step 3): CSV text, or XLSX as base64 in ``xlsx_b64``."""

    name: str = Field(default="sheet", pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    csv: str = ""
    xlsx_b64: str = ""
    columns: dict[str, str]  # sheet column -> TrialBox field
    key_column: str = ""  # the screening number
    mrn_column: str = ""  # a chart number: turned into the pseudonym with the site key, never stored
    by: str


class ResolveBody(BaseModel):
    keep: str
    by: str


class SyncBody(BaseModel):
    by: str


def _rs(rs: str) -> str:
    rid = rs.strip().upper()
    if not _RS.match(rid):
        raise HTTPException(status_code=400, detail={"code": "BAD-STUDY", "message": "not a study id"})
    return rid


def _fail(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "DATA-ERROR")
    status = 502 if isinstance(exc, RcError) and code == "RC-UPSTREAM" else 409
    return HTTPException(status_code=status, detail={"code": code, "message": getattr(exc, "message", str(exc)),
                                                     "fields": getattr(exc, "fields", [])})  # fmt: skip


def snapshot(dc: DataCore, rs: str) -> dict[str, Any]:
    flds = dc.fields(rs)
    owners = dc.owners(rs)
    recs: dict[str, dict[str, Any]] = {}
    for r in dc.values(rs):
        recs.setdefault(r["record"], {})[r["field"] if not r["event"] else f"{r['event']}:{r['field']}"] = {
            "value": r["value"], "by": r["changed_by"], "at": r["changed_at"]}  # fmt: skip
    return {
        "forms": [{"name": q["name"], "url": q["url"], "items": len(q.get("item", []))} for q in dc.forms(rs)],
        "fields": [
            {
                "name": f.name,
                "form": f.form,
                "kind": f.kind,
                "label": f.label,
                "options": f.options,
                "owner": owners.get(f.name, "trialbox"),
            }
            for f in flds.values()
        ],
        "records": recs,
        "sources": dc.sources(rs),
        "conflicts": dc.conflicts(rs),
    }


def router(get: Callable[[], DataService]) -> APIRouter:
    r = APIRouter()

    @r.get("/studies/{rs}/forms")
    def get_forms(rs: str) -> list[dict[str, Any]]:
        return get().dc.forms(_rs(rs))

    @r.post("/studies/{rs}/forms/dictionary")
    def import_dictionary(rs: str, body: DictionaryBody) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        try:
            fields = forms.read_dictionary(body.csv)
        except forms.FormError as exc:
            raise _fail(exc) from exc
        rec = body.record_field or fields[0].name
        qs = forms.questionnaires(rid, fields, record_field=rec)
        for q in qs:
            svc.dc.put_form(rid, q, "redcap-dictionary", svc.stamp())
        dropped = [f.name for f in fields if f.identifier]
        svc.audit.append("data.forms", ruleset=rid, actor=body.by, detail={"forms": [q["name"] for q in qs],
                                                                            "dropped": dropped})  # fmt: skip
        return {"forms": [q["name"] for q in qs], "fields": sum(len(q["item"]) for q in qs), "dropped": dropped}

    @r.get("/studies/{rs}/data")
    def get_data(rs: str) -> dict[str, Any]:
        return snapshot(get().dc, _rs(rs))

    @r.put("/studies/{rs}/data/{record}")
    def put_data(rs: str, record: str, body: EntryBody) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        if not _REC.match(record):
            raise HTTPException(status_code=400, detail={"code": "DATA-RECORD", "message": "not a record key"})
        try:
            n = sync.enter(svc.dc, rid, record.upper(), body.event, body.values, body.by, svc.stamp())
        except DataError as exc:
            raise _fail(exc) from exc
        svc.audit.append("data.entry", ruleset=rid, actor=body.by, detail={"record": record.upper(),
                                                                            "fields": sorted(body.values)})  # fmt: skip
        return {"changed": n, "record": svc.dc.record(rid, record.upper(), body.event)}

    @r.get("/studies/{rs}/sources")
    def get_sources(rs: str) -> dict[str, Any]:
        """The study's sources and who owns each field, without any record value (the console's Sources page)."""
        dc, rid = get().dc, _rs(rs)
        owners = dc.owners(rid)
        fields = [{"name": f.name, "form": f.form, "kind": f.kind, "label": f.label,
                   "owner": owners.get(f.name, "trialbox")} for f in dc.fields(rid).values()]  # fmt: skip
        return {"sources": dc.sources(rid), "fields": fields}

    @r.put("/studies/{rs}/sources/redcap")
    def put_redcap(rs: str, body: RedcapSourceBody) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        known = svc.dc.fields(rid)
        bad = [f for f in [*body.field_map.values(), *body.owned] if f not in known]
        if bad or any(f not in body.field_map.values() for f in body.owned):
            raise HTTPException(status_code=409, detail={"code": "DATA-FIELD", "message": "unknown or unmapped field",
                                                         "fields": bad})  # fmt: skip
        cfg = body.model_dump(exclude={"by"})
        svc.dc.put_source(rid, "redcap", cfg)
        src = svc.redcap(rid)
        assert src is not None
        for f, o in svc.dc.owners(rid).items():
            if o == "redcap":
                svc.dc.set_owner(rid, f, "trialbox")
        sync.attach(svc.dc, rid, src, body.owned)
        svc.audit.append("data.source", ruleset=rid, actor=body.by, detail={"source": "redcap", "owned": body.owned})
        return {"source": "redcap", "owned": body.owned, "fields": list(body.field_map.values())}

    @r.delete("/studies/{rs}/sources/redcap")
    def drop_redcap(rs: str, by: str = "admin") -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        src = svc.redcap(rid)
        if src is not None:
            sync.detach(svc.dc, rid, src)
        svc.dc.drop_source(rid, "redcap")
        svc.audit.append("data.source", ruleset=rid, actor=by, detail={"source": "redcap", "detached": True})
        return {"detached": True}

    @r.post("/studies/{rs}/sync/{name}")
    def run_sync(rs: str, name: str, body: SyncBody) -> dict[str, Any]:
        try:
            return get().run_sync(_rs(rs), name, body.by)
        except (RcError, DataError) as exc:
            raise _fail(exc) from exc

    @r.post("/studies/{rs}/import/sheet")
    def import_sheet(rs: str, body: SheetBody) -> dict[str, Any]:
        """Import a PI's spreadsheet: identifier columns dropped (listed), chart numbers pseudonymised with the site
        key, rows with no screening number and no chart number refused and listed. The mapped fields become the
        sheet's (its values are taken; a later different TrialBox value is a conflict, never forced)."""
        import base64
        import tempfile

        from datacore.sources import SheetSource
        from tb_common.crypto import pid_for_mrn

        svc, rid = get(), _rs(rs)
        key: bytes | None = None
        if body.mrn_column:
            if svc.site_key is None:
                raise HTTPException(status_code=409, detail={"code": "DATA-KEY", "message": "no site key on this box"})
            try:
                key = svc.site_key()
            except OSError as exc:
                missing = {"code": "DATA-KEY", "message": "the site key is missing: run an ingest first"}
                raise HTTPException(status_code=409, detail=missing) from exc
        known = svc.dc.fields(rid)
        bad = [f for f in body.columns.values() if f not in known]
        if bad:
            raise HTTPException(
                status_code=409, detail={"code": "DATA-FIELD", "message": "unknown field", "fields": bad}
            )
        with tempfile.TemporaryDirectory(prefix="tb-sheet-") as tmp:
            path = Path(tmp) / ("sheet.xlsx" if body.xlsx_b64 else "sheet.csv")
            path.write_bytes(base64.b64decode(body.xlsx_b64) if body.xlsx_b64 else body.csv.encode("utf-8"))
            src = SheetSource(path, dict(body.columns), key_column=body.key_column, mrn_column=body.mrn_column,
                              pseudonymise=(lambda m: pid_for_mrn(key, m)) if key else None,
                              name=f"sheet:{body.name}")  # fmt: skip
            try:
                sync.attach(svc.dc, rid, src, list(body.columns.values()))
                at = svc.stamp()
                res = sync.sync(svc.dc, rid, src, body.by, at, push=False).as_dict()
            except DataError as exc:
                raise _fail(exc) from exc
        res["dropped"] = src.dropped
        svc.audit.append("data.import", ruleset=rid, actor=body.by,
                         detail={"source": src.name, "pulled": res["pulled"], "taken": res["taken"],
                                 "dropped": src.dropped, "refused": len(res["refused"])})  # fmt: skip
        return {**res, "at": at}

    @r.get("/studies/{rs}/conflicts")
    def conflicts(rs: str, all: bool = False) -> list[dict[str, Any]]:
        return get().dc.conflicts(_rs(rs), open_only=not all)

    @r.post("/studies/{rs}/conflicts/{cid}")
    def resolve_conflict(rs: str, cid: int, body: ResolveBody) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        c = svc.dc.conflict(cid)
        if c is None or c["study"] != rid:
            raise HTTPException(status_code=404, detail={"code": "DATA-CONFLICT", "message": "no such conflict"})
        try:
            out = sync.resolve(svc.dc, cid, body.keep, body.by, svc.stamp())
        except DataError as exc:
            raise _fail(exc) from exc
        detail = {"conflict": cid, "keep": body.keep, "field": c["field"], "record": c["record"]}
        svc.audit.append("data.resolve", ruleset=rid, actor=body.by, detail=detail)
        return out

    @r.get("/studies/{rs}/fhir")
    def get_fhir(rs: str) -> dict[str, Any]:
        res = fhir.resources(get().dc, _rs(rs))
        return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": x} for x in res]}

    return r
