"""Orchestrator API of site set-up and data harmonization (TB-PLAN-04 step 5b, D-131, D-132, D-135).

Everything is per *workspace* (``main``: the hospital; ``practice``: the synthetic practice site; any other name: a
separate site space with its own lake). Reads:

* ``GET /setup/{ws}/readiness?study=RS``: the three questions, green / amber / red, with what is missing;
* ``GET /setup/{ws}/inputs``, ``/facts?status=``, ``/codes``, ``/checks``, ``/fixes``, ``/people``;
* ``GET /setup/{ws}/patients?study=RS``: every patient against the approved criteria, with the trail;
* ``GET /setup/{ws}/feasibility?study=RS``: the counts with how much rests on coded, confirmed and proposed facts;
* ``GET /setup/templates/{candidates|codes}?lang=&ws=``: XLSX templates in the site's language;
* ``GET /setup/remote``: the remote-help switch;
* ``GET /setup/terminology``: which licensed Japanese code lists are loaded (D-137).

Writes (each one audited, ``by`` is the person): ``POST /setup/{ws}/sheets`` (a sheet or a dump), ``POST
/setup/{ws}/sheets/{id}/roles``, ``POST /setup/{ws}/charts`` (pasted text or a file with the chart number),
``POST /setup/{ws}/facts/{id}`` (confirm, correct, reject, undo), ``POST /setup/{ws}/codes`` (one mapping) and
``/codes/sheet`` (a filled mapping sheet), ``POST /setup/{ws}/checks/{id}``, ``POST /setup/{ws}/people/resolve``,
``POST /setup/practice/load`` and ``/reset``, ``PUT /setup/remote``.

``POST /assist`` puts a draft answer the console built from its own pages to the local model for phrasing. It reads
nothing and writes nothing (the ask-the-box assistant never changes data; ``tests/console/test_site_setup_pages``).
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sitesetup import help as site_help
from sitesetup import publish, readiness
from sitesetup.intake import IntakeError
from sitesetup.service import SiteSetup, ws_ok
from sitesetup.store import SetupError
from tb_common.actor_v3 import Claim
from tb_common.patient_reads import PHI as _PHI

from orchestrator.actor import require_actor as _require_actor

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
LANGS = ("ja", "zh-TW", "en")

#: NEW-SEC-1 (D-717): a route that returns a patient's row takes the verified person, allowed to see
#: patient-level data on the route's study (tb_common.patient_reads)
PATIENT_READ = _require_actor(_PHI)  # D-717 review: no service principal
#: T-715g (D-803): the changing routes refuse a call without a verified person for the action: the site's set-up,
#: the opt-out desk (and the console's opt-out check timer) for a pseudonym, and the administrator's box network row
#: for the remote help switch (it opens the box to the vendor's connection; a row of its own waits for the guides)
AS_SITE = _require_actor("site.setup")
AS_OPTOUT = _require_actor("optout.keep", service=True)
AS_REMOTE = _require_actor("ops.network")


def _sees_patients(who: Claim, request: Request) -> None:
    """The review of D-803 (3): a set-up change that reads or writes one patient's facts (a fact, a chart, a person
    to resolve) also needs the signed role to see patient data, as the console's page asks (``need_view``); the
    administrator holds ``site.setup`` but not ``phi.view``."""
    from tb_common.authz import permit

    from orchestrator import actor as route_actor

    if not permit(who.role, "phi.view").allowed:  # on the record as every refusal (actor.refused)
        raise route_actor.refusal(request, "site.setup", "right", who.sub, None)


class InstrumentBody(BaseModel):
    """NEW-ARCH-3 slice 3 (D-864): an instrument's switch: what the site keeps of it, and the site's licence
    reference (an empty one is refused for a level above the catalogue's)."""

    model_config = ConfigDict(extra="forbid")  # the person is the verified one, never a field
    storable: str = Field(default="", max_length=40)
    licence_ref: str = Field(default="", max_length=200)


def _admin_only(who: Claim, request: Request) -> None:
    """NEW-ARCH-3 slice 3 (D-864): the instrument switches are the box's data steward's, the administrator, as the
    console's page has always asked: a coordinator holds ``site.setup`` too and is refused here."""
    from orchestrator import actor as route_actor

    if who.role != "admin":  # on the record as every refusal (actor.refused)
        raise route_actor.refusal(request, "site.setup", "right", who.sub, None)


class SheetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    kind: str = Field(pattern=r"^(sheet|dump)$")
    name: str = Field(max_length=200)
    b64: str
    roles: dict[str, str] = Field(default_factory=dict)


class RolesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    roles: dict[str, str]


class PseudonymBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    chart_no: str = Field(max_length=40)
    # NEW-DIN-3 (D-544): the opt-out desk asks whether the box knows the pseudonym; another caller pays no lookup
    ask_known: bool = False


class ChartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    chart_no: str = Field(max_length=40)
    name: str = Field(default="pasted.txt", max_length=200)
    text: str = Field(default="", max_length=60_000)
    b64: str = ""
    lang: str = "ja"


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    action: str = Field(pattern=r"^(confirm|correct|reject|undo)$")  # undo: D-178
    changes: dict[str, str] = Field(default_factory=dict)


class MapBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    domain: str
    system: str
    code: str
    target_system: str = ""
    target_code: str = ""
    target_display: str = ""


class MapSheetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    b64: str


class AnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    answer: str = Field(max_length=40)


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    pid: str = Field(pattern=r"^[0-9a-f]{32}$")
    what: str = Field(pattern=r"^(birth_date|sex)$")
    keep: str = Field(max_length=20)


class ByBody(BaseModel):
    """No field: the person is the verified one (T-715g, D-803)."""

    model_config = ConfigDict(extra="forbid")


class RemoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # T-715g (D-803): the person is the verified one, never a field
    on: bool
    # the hospital's approval (needed with real data): who approved, as the hospital writes it; not the caller
    # (T-715g, D-803: a field named like a person is no field of a refuse route)
    hospital_approval: str = Field(default="", max_length=80)


class AssistBody(BaseModel):
    question: str = Field(max_length=300)
    lang: str = "en"
    draft: str = Field(max_length=1500)
    points: list[str] = Field(default_factory=list, max_length=30)


SETUP_DOOR = ("site.setup",)  # T-719 (D-487): who may give site set-up a chart number (a chart, a sheet)


def _fail(exc: SetupError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message})


def _intake_fail(exc: IntakeError) -> HTTPException:
    """A sheet refused at import; ``column`` names the column it is about (T-629, FIT-U09), as the header writes it."""
    return HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message, "column": exc.column})


log = logging.getLogger("orchestrator.setup")


def router(
    get: Callable[[], SiteSetup],
    study_info: Callable[[str], dict[str, Any]],
    records: Callable[[str], dict[str, Any]],
    approved: Callable[[str], Any],
    real_data: Callable[[], bool],
    door: Callable[..., Any],
) -> APIRouter:
    """``study_info(rs)``: ``{id, exists, approved, waiting, approval_link}``; ``records(rs)``: ``{forms, redcap}``;
    ``approved(rs)``: the approved ``Ruleset`` or None; ``real_data()``: whether the box holds real patient data;
    ``door(request)``: who may turn a chart number into a pseudonym on this call (``orchestrator.identifiers.admit``:
    it refuses, or returns the record to write)."""
    r = APIRouter()

    def ws_of(ws: str) -> str:
        try:
            return ws_ok(ws)
        except SetupError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc

    def rs_of(rs: str) -> str:
        rid = (rs or "").strip().upper()
        if rid and not _RS.match(rid):
            raise HTTPException(status_code=400, detail={"code": "BAD-STUDY", "message": "not a study id"})
        return rid

    def call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except SetupError as exc:
            raise _fail(exc) from exc

    # D-146 (review J-08): declared before the ``/setup/{ws}/...`` routes, or ``/setup/templates/codes`` is read as
    # the hospital codes of a workspace named "templates" (a list, and the console's download was a 500)
    @r.get("/setup/templates/{name}")
    def template(name: str, lang: str = "ja", ws: str = "main") -> dict[str, Any]:
        lang = lang if lang in LANGS else "en"
        if name == "candidates":
            data = site_help.candidate_template(lang)
        elif name == "codes":
            data = site_help.mapping_sheet(get().store.locals(ws_of(ws)), lang)
        else:
            raise HTTPException(status_code=404, detail={"code": "SETUP-TEMPLATE", "message": "no such template"})
        return {
            "name": f"trialbox-{name}-{lang}.xlsx",
            "b64": base64.b64encode(data).decode("ascii"),
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }

    @r.get("/setup/{ws}/readiness")
    def get_readiness(ws: str, study: str = "") -> dict[str, Any]:
        svc, w, rid = get(), ws_of(ws), rs_of(study)
        st = study_info(rid) if rid else {"id": "", "exists": False}
        return readiness.readiness(svc, w, st, records(rid) if rid else {})

    @r.get("/setup/{ws}/inputs", dependencies=[PATIENT_READ])
    def get_inputs(ws: str) -> list[dict[str, Any]]:
        rows = get().store.inputs(ws_of(ws))
        return [{k: v for k, v in x.items() if k not in ("path", "sha256")} for x in rows]

    @r.get("/setup/{ws}/facts", dependencies=[PATIENT_READ])
    def get_facts(ws: str, status: str = "", pid: str = "") -> list[dict[str, Any]]:
        return get().store.facts(ws_of(ws), status or None, pid or None)

    @r.get("/setup/{ws}/codes")
    def get_codes(ws: str) -> list[dict[str, Any]]:
        return get().store.locals(ws_of(ws))

    @r.get("/setup/{ws}/checks", dependencies=[PATIENT_READ])
    def get_checks(ws: str, open_only: bool = False) -> list[dict[str, Any]]:
        return get().store.checks(ws_of(ws), open_only)

    @r.get("/setup/{ws}/fixes", dependencies=[PATIENT_READ])
    def get_fixes(ws: str) -> list[dict[str, Any]]:
        return get().store.fixes(ws_of(ws))

    @r.get("/setup/{ws}/people", dependencies=[PATIENT_READ])
    def get_people(ws: str) -> dict[str, Any]:
        """Patients by pseudonym with the inputs each one came from, and the disagreements between inputs."""
        svc, w = get(), ws_of(ws)
        facts = svc.store.facts(w)
        kinds = {i["id"]: i["kind"] for i in svc.store.inputs(w)}
        by: dict[str, set[str]] = {}
        for f in facts:
            by.setdefault(f["pid"], set()).add(kinds.get(f["input_id"], "?"))
        for i in svc.store.inputs(w, "chart"):
            if i["pid"]:
                by.setdefault(i["pid"], set()).add("chart")
        people = [{"pid": p, "short": p[:8], "inputs": sorted(k)} for p, k in sorted(by.items())]
        return {"people": people, "disagreements": publish.disagreements(facts)}

    @r.get("/setup/{ws}/patients", dependencies=[PATIENT_READ])
    def get_patients(ws: str, study: str) -> dict[str, Any]:
        svc, w, rid = get(), ws_of(ws), rs_of(study)
        rs = approved(rid)
        if rs is None:
            return {"study": rid, "approved": False, "patients": []}
        try:
            return {"study": rid, "approved": True, "patients": readiness.patient_check(svc, w, rs, svc.today())}
        except readiness.UNREAD as exc:  # D-709: said, not a 500 and not "no patients"
            status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
            # D-712: a rejected statement or another service's error goes on (by its type, status and service)
            if not readiness.unread_of(type(exc), status, getattr(exc, "service", None)):
                raise
            log.warning(
                "site patient check: the lake could not be read (%s %s)", type(exc).__name__, getattr(exc, "status", "")
            )
            return {"study": rid, "approved": True, "patients": [], "lake_unread": True}

    @r.get("/setup/{ws}/feasibility")
    def get_feasibility(ws: str, study: str) -> dict[str, Any]:
        svc, w, rid = get(), ws_of(ws), rs_of(study)
        rs = approved(rid)
        rd = readiness.readiness(svc, w, {"id": rid, "exists": True, "approved": bool(rs)}, {})
        if rs is None:
            return {"study": rid, "approved": False, "needs_bulk": not rd["bulk"], "feas": None}
        out = {"study": rid, "approved": True, "needs_bulk": False}
        if rd.get("lake_unread"):  # D-709: no count from a lake that cannot be asked, and not "needs a bulk input"
            return {**out, "feas": None, "lake_unread": True}
        if not rd["bulk"]:  # D-132: say plainly what cannot be done yet instead of failing
            return {"study": rid, "approved": True, "needs_bulk": True, "feas": None}
        try:
            return {**out, "feas": readiness.feasibility(svc, w, rs, svc.today())}
        except readiness.UNREAD as exc:
            status = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
            if not readiness.unread_of(type(exc), status, getattr(exc, "service", None)):
                raise
            log.warning(
                "site counts: the lake could not be read (%s %s)", type(exc).__name__, getattr(exc, "status", "")
            )
            return {**out, "feas": None, "lake_unread": True}

    @r.post("/setup/{ws}/sheets")
    def post_sheet(ws: str, body: SheetBody, request: Request, who: Claim = AS_SITE) -> dict[str, Any]:
        svc, w = get(), ws_of(ws)
        admitted = door(request, SETUP_DOOR)  # T-719 (D-487): a sheet's chart numbers become pseudonyms here
        try:
            data = base64.b64decode(body.b64, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "SETUP-FILE", "message": "not base64"}) from exc
        try:
            out = dict(call(lambda: svc.add_sheet(w, body.kind, body.name, data, body.roles, who.name)))
        except IntakeError as exc:
            raise _intake_fail(exc) from exc
        admitted.record_input(out.get("input") or out.get("id"))
        return out

    @r.post("/setup/{ws}/sheets/{iid}/roles")
    def post_roles(ws: str, iid: int, body: RolesBody, request: Request, who: Claim = AS_SITE) -> dict[str, Any]:
        svc = get()
        ws_of(ws)
        admitted = door(request, SETUP_DOOR)  # a new chart-number column is hashed at the re-read
        try:
            out = dict(call(lambda: svc.reread(iid, who.name, body.roles)))
        except IntakeError as exc:  # T-629 (FIT-U09): a chart-number column Excel turned into numbers
            raise _intake_fail(exc) from exc
        admitted.record_input(iid)
        return out

    @r.post("/setup/{ws}/charts")
    def post_chart(ws: str, body: ChartBody, request: Request, who: Claim = AS_SITE) -> dict[str, Any]:
        _sees_patients(who, request)
        svc, w = get(), ws_of(ws)
        admitted = door(request, SETUP_DOOR)  # T-719 (D-487): the chart's number becomes a pseudonym here
        lang = body.lang if body.lang in LANGS else "en"
        if body.b64:
            try:
                data = base64.b64decode(body.b64, validate=True)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"code": "SETUP-FILE", "message": "not base64"}) from exc
            out = dict(call(lambda: svc.add_chart(w, body.chart_no, body.name, data, who.name, lang)))
        else:
            out = dict(
                call(
                    lambda: svc.add_chart(
                        w, body.chart_no, "pasted.txt", body.text.encode("utf-8"), who.name, lang, pasted=True
                    )
                )
            )
        admitted.record_input(out.get("input"))
        return out

    @r.post("/setup/{ws}/facts/{fid}")
    def post_fact(ws: str, fid: int, body: DecideBody, request: Request, who: Claim = AS_SITE) -> dict[str, Any]:
        _sees_patients(who, request)
        svc, w = get(), ws_of(ws)
        f = svc.store.fact(fid)
        if f is None or f["ws"] != w:
            raise HTTPException(status_code=404, detail={"code": "SETUP-FACT", "message": "no such fact"})
        return dict(call(lambda: svc.decide(fid, body.action, who.name, dict(body.changes))))

    @r.post("/setup/{ws}/codes")
    def post_code(ws: str, body: MapBody, who: Claim = AS_SITE) -> dict[str, Any]:
        svc, w = get(), ws_of(ws)
        target = {"system": body.target_system, "code": body.target_code, "display": body.target_display}
        return dict(call(lambda: svc.map_code(w, body.domain, body.system, body.code, target, who.name)))

    @r.post("/setup/{ws}/codes/sheet")
    def post_code_sheet(ws: str, body: MapSheetBody, who: Claim = AS_SITE) -> dict[str, Any]:
        """A filled mapping sheet: every row with a standard code is mapped, as the sender's own decision."""
        from sitesetup import mapping as mp

        svc, w = get(), ws_of(ws)
        rows = site_help.read_mapping_sheet(base64.b64decode(body.b64))
        done, refused = 0, []
        for row in rows:
            target = {"system": mp.TARGET.get(row["domain"], ""), "code": row["use"]}
            try:
                svc.map_code(w, row["domain"], row["system"], row["code"], target, who.name)
                done += 1
            except SetupError as exc:
                refused.append({"code": row["code"], "why": exc.code})
        return {"mapped": done, "refused": refused}

    @r.post("/setup/{ws}/checks/{cid}")
    def post_check(ws: str, cid: int, body: AnswerBody, who: Claim = AS_SITE) -> dict[str, Any]:
        svc, w = get(), ws_of(ws)
        c = svc.store.check(cid)
        if c is None or c["ws"] != w:
            raise HTTPException(status_code=404, detail={"code": "SETUP-CHECK", "message": "no such check"})
        return dict(call(lambda: svc.answer(cid, body.answer, who.name)))

    @r.post("/setup/{ws}/people/resolve")
    def post_resolve(ws: str, body: ResolveBody, request: Request, who: Claim = AS_SITE) -> dict[str, Any]:
        _sees_patients(who, request)
        svc, w = get(), ws_of(ws)
        return dict(call(lambda: svc.resolve(w, body.pid, body.what, body.keep, who.name)))

    @r.post("/setup/pseudonym")
    def post_pseudonym(body: PseudonymBody, request: Request, who: Claim = AS_OPTOUT) -> dict[str, Any]:
        """D-147: a chart number typed at the door (the opt-out register) becomes the box's pseudonym here; the console
        stores only the pseudonym and the number is never kept or logged. T-719 (D-487): for the verified person of
        the call only, capped, and on the record with the pseudonym. NEW-DIN-3 (D-544): ``known``: the pid map has
        that pseudonym (true), has not (false), or cannot say (null); answered only when ``ask_known`` is sent."""
        admitted = door(request, ("optout.keep",), True)  # the opt-out desk, and the console's opt-out check
        chart = body.chart_no.strip()
        if not chart:
            raise HTTPException(status_code=400, detail={"code": "SETUP-CHART", "message": "give a chart number"})
        svc = get()
        pid = str(call(lambda: svc.pseudonym(chart)))
        admitted.record(pid)
        # NEW-DIN-3 (D-544): and whether that pseudonym is a patient of this box, so the desk does not register a
        # mistyped number as one
        return {"pid": pid, "known": svc.known_pid(pid)} if body.ask_known else {"pid": pid}

    @r.post("/setup/{ws}/publish")
    def post_publish(ws: str, body: ByBody, who: Claim = AS_SITE) -> dict[str, Any]:
        return dict(get().publish(ws_of(ws), who.name, force=True))

    @r.post("/setup/practice/load")
    def practice_load(body: ByBody, who: Claim = AS_SITE) -> dict[str, Any]:
        svc = get()
        svc.reset("practice", who.name)
        inp = site_help.practice_inputs()
        call(lambda: svc.add_sheet("practice", "dump", inp["dump"][0], inp["dump"][1], {}, who.name))
        call(lambda: svc.add_sheet("practice", "sheet", inp["sheet"][0], inp["sheet"][1], {}, who.name))
        for no, text in inp["charts"]:
            try:
                svc.add_chart("practice", no, "pasted.txt", text.encode("utf-8"), who.name, "ja", pasted=True)
            except SetupError as exc:
                raise _fail(exc) from exc
        svc.audit.append("setup.practice", actor=who.name, detail={"action": "load"})
        return {"loaded": True, "inputs": len(svc.store.inputs("practice"))}

    @r.post("/setup/practice/reset")
    def practice_reset(body: ByBody, who: Claim = AS_SITE) -> dict[str, Any]:
        get().reset("practice", who.name)
        return {"reset": True}

    @r.get("/setup/terminology")
    def get_terminology() -> list[dict[str, Any]]:
        """D-137: the licensed Japanese code lists (MEDIS 標準病名, JLAC10, YJ): loaded with version and source, or
        not loaded (their codes stay unknown, D-130)."""
        from adapter import licensed

        return licensed.status(get().store.db.url)

    @r.get("/setup/remote")
    def get_remote() -> dict[str, Any]:
        st = get().store
        return {
            "on": st.setting("remote_help") == "on",
            "approved_by": st.setting("remote_help_approved_by"),
            "real_data": real_data(),
        }

    @r.put("/setup/remote")
    def put_remote(body: RemoteBody, who: Claim = AS_REMOTE) -> dict[str, Any]:
        """Remote help from Aimedics (D-132): a switch only, off by default; no connection is made by TrialBox.
        With real patient data on the box, switching it on needs the hospital's approval (who approved)."""
        svc = get()
        if body.on and real_data() and not body.hospital_approval.strip():
            raise HTTPException(
                status_code=409,
                detail={"code": "SETUP-REMOTE", "message": "real data is present: the hospital's approval is needed"},
            )
        at = svc.stamp()
        approval = body.hospital_approval.strip() if body.on else ""
        svc.store.set_setting("remote_help", "on" if body.on else "off", who.name, at)
        svc.store.set_setting("remote_help_approved_by", approval, who.name, at)
        svc.audit.append(
            "setup.remote",
            actor=who.name,
            detail={"on": body.on, "approved_by": body.hospital_approval[:80], "real_data": real_data()},
        )
        return {"on": body.on, "approved_by": approval, "real_data": real_data()}

    @r.get("/setup/instruments")
    def get_instruments() -> dict[str, Any]:
        """NEW-ARCH-3 slice 3 (D-864): the instrument switches as stored (``tb_common.instruments``); no patient."""
        from tb_common import instruments

        return {"setting": get().store.setting(instruments.SETTING)}

    @r.put("/setup/instruments/{iid}")
    def put_instrument(iid: str, body: InstrumentBody, request: Request, who: Claim = AS_SITE) -> dict[str, Any]:
        """NEW-ARCH-3 slice 3 (D-864): the data steward's switch of one instrument (T-307, D-375): a level above
        the catalogue's needs the site's licence reference (400 with its code), the catalogue's own level needs
        none. The console writes the audit event, as before."""
        from tb_common import catalogue, instruments

        _admin_only(who, request)
        svc = get()
        at = svc.stamp()
        have = instruments.switches(svc.store.setting(instruments.SETTING))
        try:
            new = instruments.switch(have, iid[:40], body.storable, body.licence_ref, who.name, at)
        except instruments.SwitchRefused as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": "switch refused"}) from exc
        except catalogue.CatalogueError as exc:
            raise HTTPException(status_code=503, detail={"code": "register", "message": "register unreadable"}) from exc
        svc.store.set_setting(instruments.SETTING, instruments.dump(new), who.name, at)
        sw = new.get(iid)
        return {"storable": sw.storable if sw else "catalogue", "licence_ref": sw.licence_ref if sw else ""}

    @r.post("/assist")
    def assist(body: AssistBody) -> dict[str, Any]:
        """Phrase the console's draft answer with the local model. Reads and writes nothing; on any model trouble
        the draft itself is the answer (the help never depends on the model being up)."""
        from tb_common.llm import LlmError

        svc = get()
        names = {"ja": "Japanese", "zh-TW": "Traditional Chinese", "en": "English"}
        try:
            res = svc.llm.chat_json(
                "assist",
                {
                    "question": body.question,
                    "language": body.lang,
                    "language_name": names.get(body.lang, "English"),
                    "draft": body.draft,
                    "points": body.points,
                },
            )
            text = str(res.data.get("answer") or "").strip() or body.draft
            return {"answer": text, "model": True}
        except (LlmError, Exception):
            return {"answer": body.draft, "model": False}

    return r
