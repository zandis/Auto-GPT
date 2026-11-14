"""Orchestrator API of EDC prefill (D-160). Every route is under ``/studies/{rs}/edc``; the console's pages and its
``/api/v1`` routes call these after their own role check (``authz.edc_allowed``), and the rules are checked again
here (``edc.service``).

* ``GET  /studies/{rs}/edc``: the switch, its last changes, the map, the REDCap target, per subject and visit counts.
* ``POST /studies/{rs}/edc/switch``: on (the acknowledgement; the stored re-entry result) or off.
* ``POST /studies/{rs}/edc/reentry``: an administrator records the blind re-entry result with the id of its filed
  report (T-115, E-14); the switch goes on with the newest one, by another person.
* ``POST /studies/{rs}/edc/dictionary``: read the REDCap project's data dictionary into the study's forms.
* ``GET  /studies/{rs}/edc/map/suggest``; ``PUT /studies/{rs}/edc/map`` (the items and the REDCap target).
* ``POST /studies/{rs}/edc/drafts`` (one subject and visit); ``GET /studies/{rs}/edc/drafts?record=&visit=`` (with
  a record, each signed value carries its signature: printed name, role, time and meaning; E-12).
* ``POST /studies/{rs}/edc/drafts/{id}/decide``: confirm, edit (reason) or reject.
* ``POST /studies/{rs}/edc/sign``: the signature of one subject and visit (the console re-authenticated the signer).
* ``POST /studies/{rs}/edc/import/odm``: a CDISC ODM file (base64) read into open drafts that cite it, proposals a
  person confirms and signs (D-435); refused whole with a named ``odm.*`` reason.
* ``GET /studies/{rs}/edc/copy?record=&format=``: the copy-assist sheet (D-434), signed values only, audited;
  ``POST /studies/{rs}/edc/copy/tick``: "copied" ticks (or their undo, with a reason) on values of the sheet.
* ``POST /studies/{rs}/edc/send/redcap``; ``GET /studies/{rs}/edc/export/odm``;
  ``GET /studies/{rs}/edc/trail/{record}``.

Who acts (D-162, review E-01): every route that changes something, and the export, takes the person from the
verified ``X-TB-Actor`` assertion the console signs (``tb_common.service_auth``), and their role from the signed
``X-TB-Actor-Role``; never from the body. The role must allow the action (``authz.edc_role_may``). The signature
needs an assertion the console made right after it re-authenticated the signer (session ``reauth-...``); so does a
change to a signed value (the record lock, D-281). Such a session counts only when assertions are checked with the
console's own key, never on a box that still shares one service token (SEC-16, T-205; :func:`reauthenticated`).
A ``by`` in a body counts only on a DEV or TEST box without a token, as for the other routes. A refused role or a
missing re-authentication is audited as ``edc.refused`` (SEC-7).
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable
from typing import Any, TypeVar

from edc import copyassist
from edc.service import EdcService
from edc.store import EdcError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from tb_common.authz import edc_role_may
from tb_common.patient_reads import MONITOR as _MONITOR
from tb_common.patient_reads import PHI as _PHI
from tb_common.service_auth import (
    ACTOR_HEADER,
    ACTOR_KEYS_ENV,
    ASSERTION_HEADER,
    OPEN_ENVS,
    ROLE_HEADER,
    Actor,
    ActorError,
    verify_actor,
)

from orchestrator.actor import require_actor as _require_actor

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VISIT = re.compile(r"^([a-z][a-z0-9_]{0,99})?$")
_USER = r"^[a-z0-9:._@-]{1,120}$"
REAUTH = "reauth-"  # the session part of an assertion the console signs right after re-authenticating a signer
T = TypeVar("T")
Claim = Callable[[Request, "str | None"], Actor]

#: NEW-SEC-1 (D-717): a route that returns a patient's row takes the verified person, allowed to see
#: patient-level data on the route's study (tb_common.patient_reads)
PATIENT_READ = _require_actor(_PHI)  # D-717 review: no service principal
#: D-389: the four reads of the monitor's page (a sponsor's CRA under a monitor grant) take its row too
MONITOR_READ = _require_actor(_MONITOR)


class SwitchBody(BaseModel):
    on: bool
    kind: str = ""
    reference: str = Field(default="", max_length=120)
    ack_date: str = Field(default="", max_length=10)
    reentry_pages: int = Field(default=0, ge=0, le=100000)
    reentry_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)
    by: str | None = Field(default=None, pattern=_USER)
    copy_assist: bool = False  # D-434: on as copy-assist (no acknowledgement; never a write to the sponsor's EDC)


class ReentryBody(BaseModel):
    pages: int = Field(ge=0, le=100000)
    accuracy: float = Field(ge=0.0, le=1.0)
    document: str = Field(min_length=1, max_length=120)  # the id of the filed re-entry report
    by: str | None = Field(default=None, pattern=_USER)


class DictionaryBody(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    record_field: str = Field(default="", max_length=100)
    by: str | None = Field(default=None, pattern=_USER)


class Target(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    key_field: str = Field(default="tb_screening_no", pattern=r"^[a-z][a-z0-9_]{0,99}$")
    id_field: str = Field(default="record_id", pattern=r"^[a-z][a-z0-9_]{0,99}$")


class MapBody(BaseModel):
    items: list[dict[str, Any]] = Field(max_length=2000)
    target: Target
    by: str | None = Field(default=None, pattern=_USER)


class DraftBody(BaseModel):
    record: str = Field(pattern=_REC.pattern)
    pid: str = Field(min_length=1, max_length=64)
    visit: str = Field(default="", pattern=_VISIT.pattern)
    visit_date: str = Field(max_length=10)
    by: str | None = Field(default=None, pattern=_USER)


class DecideBody(BaseModel):
    action: str
    value: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=300)
    citation: dict[str, str] | None = None
    by: str | None = Field(default=None, pattern=_USER)
    unlock: bool = False  # counts only on a DEV or TEST box without a token, as ``by`` (D-281)


class SignBody(BaseModel):
    record: str = Field(pattern=_REC.pattern)
    visit: str = Field(default="", pattern=_VISIT.pattern)
    signer: str | None = Field(default=None, pattern=_USER)
    printed_name: str = Field(min_length=1, max_length=120)
    meaning: str = "transcribed"
    meaning_text: str = Field(min_length=1, max_length=600)
    # how the console re-authenticated: the password (and code) again, or a fresh sign-in at the directory (T-205)
    method: str = Field(default="password", pattern=r"^(password|password\+totp|oidc\+mfa)$")
    lang: str = Field(default="en", pattern=r"^(en|ja|zh-TW)$")
    seen: dict[int, str] = Field(max_length=2000)  # draft id -> content hash, as the review page showed them


class ImportBody(BaseModel):
    name: str = Field(default="", max_length=120)
    data: str = Field(min_length=1, max_length=8_000_000)  # the file, base64 (TB_EDC_ODM_MAX_BYTES bounds the bytes)
    by: str | None = Field(default=None, pattern=_USER)


class TickBody(BaseModel):
    record: str = Field(pattern=_REC.pattern)
    drafts: list[int] = Field(min_length=1, max_length=2000)
    action: str = Field(default="copied", pattern=r"^(copied|undone)$")
    reason: str = Field(default="", max_length=300)
    by: str | None = Field(default=None, pattern=_USER)


class SendBody(BaseModel):
    record: str | None = Field(default=None, pattern=_REC.pattern)
    by: str | None = Field(default=None, pattern=_USER)


def _rs(rs: str) -> str:
    rid = rs.strip().upper()
    if not _RS.match(rid):
        raise HTTPException(status_code=400, detail={"code": "BAD-STUDY", "message": "not a study id"})
    return rid


def _rec(record: str) -> str:
    if not _REC.match(record):
        raise HTTPException(status_code=400, detail={"code": "edc.record", "message": "not a record key"})
    return record.upper()


def _fail(exc: EdcError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if getattr(exc, "problems", None):
        detail["problems"] = exc.problems  # type: ignore[attr-defined]
    return HTTPException(status_code=exc.status, detail=detail)


def reauthenticated(a: Actor) -> bool:
    """Did the console sign this assertion right after re-authenticating the person (session ``reauth-...``)?

    SEC-16 (T-205, D-391): with one shared service token every container derives the same assertion key, so any of
    them could write a ``reauth-`` session. It counts only when the orchestrator verifies assertions with the
    console's own key (``TB_ACTOR_KEYS_FILE``, per-service tokens, D-138), or on a DEV or TEST box. A box that
    still runs on the shared token signs nothing and unlocks nothing until ``trialbox secrets init`` has run."""
    if not a.verified or not a.session.startswith(REAUTH):
        return False
    if (os.environ.get(ACTOR_KEYS_ENV) or "").strip():
        return True
    return (os.environ.get("TB_ENV") or "").strip().upper() in OPEN_ENVS


def claim_of(request: Request, fallback: str | None = None) -> Actor:
    """The verified person behind a call (the orchestrator app passes its own, audited, version)."""
    try:
        return verify_actor(request.headers.get(ACTOR_HEADER), request.headers.get(ASSERTION_HEADER), fallback,
                            role=request.headers.get(ROLE_HEADER))  # fmt: skip
    except ActorError as exc:
        raise HTTPException(status_code=403, detail={"code": "edc.actor", "message": str(exc)}) from exc


def router(get: Callable[[], EdcService], claim: Claim = claim_of) -> APIRouter:
    r = APIRouter()

    def refused(rs: str, a: Actor, action: str, code: str) -> None:
        """A refusal before the service is reached is audited too (D-281, SEC-7); the study id as given, checked."""
        rid = rs.strip().upper()
        get().audit.append("edc.refused", ruleset=rid if _RS.match(rid) else "", actor=a.name or "unknown",
                           detail={"action": action, "code": code})  # fmt: skip

    def who(request: Request, action: str, fallback: str | None = None, rs: str = "") -> Actor:
        """The verified person and role, allowed to take ``action`` (D-162)."""
        a = claim(request, fallback)
        if not a.role or not edc_role_may(a.role, action):
            refused(rs, a, action, "edc.role")
            raise HTTPException(status_code=403, detail={"code": "edc.role", "message": "this role may not do that"})
        return a

    def run(fn: Callable[[], T]) -> T:
        try:
            return fn()
        except EdcError as exc:
            raise _fail(exc) from exc

    @r.get("/studies/{rs}/edc", dependencies=[MONITOR_READ])  # D-717 review: its subjects are patients' rows
    def status(rs: str) -> dict[str, Any]:
        return get().status(_rs(rs))

    @r.post("/studies/{rs}/edc/switch")
    def switch(rs: str, body: SwitchBody, request: Request) -> dict[str, Any]:
        a = who(request, "switch_on" if body.on else "switch_off", body.by, rs)
        return run(lambda: get().set_switch(_rs(rs), body.on, by=a.name, role=a.role, kind=body.kind,
                                            reference=body.reference, ack_date=body.ack_date,
                                            reentry_pages=body.reentry_pages,
                                            reentry_accuracy=body.reentry_accuracy, reason=body.reason,
                                            copy=body.copy_assist))  # fmt: skip

    @r.post("/studies/{rs}/edc/reentry")
    def reentry(rs: str, body: ReentryBody, request: Request) -> dict[str, Any]:
        a = claim(request, body.by)
        if a.role != "admin":  # an administrator files it; the PI who turns the switch on cannot (E-14)
            refused(rs, a, "reentry", "edc.role")
            raise HTTPException(status_code=403, detail={"code": "edc.role", "message": "an administrator records it"})
        return run(lambda: get().record_reentry(_rs(rs), pages=body.pages, accuracy=body.accuracy,
                                                document=body.document, by=a.name))  # fmt: skip

    @r.post("/studies/{rs}/edc/dictionary")
    def dictionary(rs: str, body: DictionaryBody, request: Request) -> dict[str, Any]:
        a = who(request, "map", body.by, rs)
        return run(lambda: get().import_dictionary(_rs(rs), body.token_ref, a.name, body.record_field))

    @r.get("/studies/{rs}/edc/map/suggest")
    def suggest(rs: str) -> list[dict[str, Any]]:
        return get().suggest(_rs(rs))

    @r.put("/studies/{rs}/edc/map")
    def put_map(rs: str, body: MapBody, request: Request) -> dict[str, Any]:
        a = who(request, "map", body.by, rs)
        return run(lambda: get().put_map(_rs(rs), body.items, body.target.model_dump(), a.name))

    @r.post("/studies/{rs}/edc/drafts")
    def drafts(rs: str, body: DraftBody, request: Request) -> list[dict[str, Any]]:
        a = who(request, "draft", body.by, rs)
        return run(lambda: get().build(_rs(rs), body.record.upper(), body.pid, body.visit, body.visit_date, a.name))

    @r.get("/studies/{rs}/edc/drafts", dependencies=[MONITOR_READ])
    def list_drafts(rs: str, record: str | None = None, visit: str | None = None) -> list[dict[str, Any]]:
        if visit is not None and not _VISIT.match(visit):
            raise HTTPException(status_code=400, detail={"code": "edc.visit", "message": "not a visit name"})
        rid = _rs(rs)
        store = get().store
        rows = store.drafts(rid, _rec(record) if record else None, visit or None)
        covered = store.covered_ids(rid, rows)  # D-461: "signed" only while an intact signature covers the value
        for d in rows:
            d["covered"] = int(d["id"]) in covered
        if record:  # the signature beside each covered value: who, as what, when, and its meaning (E-12)
            sigs = {int(s["id"]): s for s in store.signatures(rid, _rec(record))}
            for d in rows:
                s = sigs.get(int(d["signature_id"])) if d["covered"] else None
                if s is not None:
                    d["signature"] = {k: s[k] for k in ("printed_name", "role", "at", "meaning", "meaning_text",
                                                        "lang", "method")}  # fmt: skip
        return rows

    @r.post("/studies/{rs}/edc/drafts/{draft_id}/decide")
    def decide(rs: str, draft_id: int, body: DecideBody, request: Request) -> dict[str, Any]:
        a = who(request, "review", body.by, rs)
        # the record lock (D-281): a signed value changes only under an assertion made right after a password check
        # (with a token); on a DEV or TEST box without one, the console says so in the body, as it names the person
        unlock = reauthenticated(a) if a.verified else body.unlock
        return run(lambda: get().decide(_rs(rs), draft_id, body.action, value=body.value, reason=body.reason,
                                        citation=body.citation, by=a.name, unlock=unlock))  # fmt: skip

    @r.post("/studies/{rs}/edc/sign")
    def sign(rs: str, body: SignBody, request: Request) -> dict[str, Any]:
        a = who(request, "sign", body.signer, rs)
        if a.verified and not reauthenticated(a):
            if a.session.startswith(REAUTH):  # SEC-16: a shared token cannot vouch for a re-authentication
                code, msg = "edc.reauth_shared_token", "one shared service token: run trialbox secrets init first"
            else:
                code, msg = "edc.reauth_needed", "sign right after typing the password again"
            refused(rs, a, "sign", code)
            raise HTTPException(status_code=403, detail={"code": code, "message": msg})
        return run(lambda: get().sign(_rs(rs), body.record.upper(), body.visit, signer=a.name,
                                      printed_name=body.printed_name, role=a.role, meaning=body.meaning,
                                      meaning_text=body.meaning_text, lang=body.lang, seen=body.seen,
                                      method=body.method))  # fmt: skip

    @r.post("/studies/{rs}/edc/import/odm")
    def import_odm(rs: str, body: ImportBody, request: Request) -> dict[str, Any]:
        a = who(request, "draft", body.by, rs)  # an import drafts: the same question as a draft run
        try:
            data = base64.b64decode(body.data, validate=True)
        except ValueError as exc:
            msg = {"code": "odm.base64", "message": "the file is base64"}
            raise HTTPException(status_code=400, detail=msg) from exc
        return run(lambda: get().import_odm(_rs(rs), data, a.name, body.name))

    @r.get("/studies/{rs}/edc/copy", dependencies=[PATIENT_READ])
    def copy_sheet(rs: str, request: Request, record: str | None = None, format: str = "page",
                   by: str | None = None) -> dict[str, Any]:  # fmt: skip
        if by is not None and not re.match(_USER, by):
            raise HTTPException(status_code=400, detail={"code": "edc.by", "message": "who is reading"})
        a = who(request, "review", by, rs)  # D-434: the sheet is read by those who review and sign
        rid = _rs(rs)
        return run(lambda: copyassist.sheet(get(), rid, _rec(record) if record else None, a.name, format))

    @r.post("/studies/{rs}/edc/copy/tick")
    def copy_tick(rs: str, body: TickBody, request: Request) -> dict[str, Any]:
        a = who(request, "review", body.by, rs)
        return run(lambda: copyassist.tick(get(), _rs(rs), body.record.upper(), body.drafts, body.action, a.name,
                                           body.reason))  # fmt: skip

    @r.post("/studies/{rs}/edc/send/redcap")
    def send(rs: str, body: SendBody, request: Request) -> dict[str, Any]:
        a = who(request, "send", body.by, rs)
        return run(lambda: get().send_redcap(_rs(rs), a.name, body.record.upper() if body.record else None))

    @r.get("/studies/{rs}/edc/export/odm", dependencies=[PATIENT_READ])
    def export_odm(rs: str, request: Request, by: str | None = None) -> dict[str, Any]:
        if by is not None and not re.match(_USER, by):
            raise HTTPException(status_code=400, detail={"code": "edc.by", "message": "who is exporting"})
        a = who(request, "export", by, rs)
        rid = _rs(rs)
        text = run(lambda: get().export_odm(rid, a.name))
        return {"name": f"{rid}-edc-prefill.odm.xml", "media_type": "application/xml", "text": text}

    @r.get("/studies/{rs}/edc/trail/{record}", dependencies=[MONITOR_READ])
    def trail(rs: str, record: str) -> dict[str, Any]:
        return get().trail(_rs(rs), _rec(record))

    return r
