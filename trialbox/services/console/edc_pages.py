"""EDC prefill pages and their ``/api/v1`` routes (D-160).

* ``/studies/{rs}/edc``: the switch (on only with the sponsor's written acknowledgement and the blind re-entry result;
  off by default), the REDCap target, the map's state, each subject and visit with its counts, "draft a subject",
  "send signed values to REDCap" and the ODM file.
* ``/studies/{rs}/edc/map``: read the data dictionary from REDCap, then per item its CDASH tag and where its value may
  come from. A suggestion fills the rows; nothing is drafted from a diagnosis or medicine code nobody typed.
* ``/studies/{rs}/edc/review/{record}``: the coordinator's review. Per value: the value and its citation; confirm,
  change with a reason, or reject. A value without a citation has no confirm button and is refused anyway. Then the
  electronic signature: the person types their password again, sees the meaning of the signature and their printed
  name, and signs every confirmed value of that subject and visit. A directory (OIDC) account has no console password:
  it signs by typing its credentials and second factor at the hospital's identity provider again (T-205, D-391).
  Then send. A signed value is locked (D-281): to
  change or withdraw it the person gives a reason and types their password (and code) again.
* ``/studies/{rs}/edc/trail/{record}``: every draft, decision, signature and send of one subject.
* ``POST /studies/{rs}/edc/import`` (T-302c): an ODM file read into open drafts that cite it (D-435), proposals the
  coordinator reviews and signs like any draft; ``/studies/{rs}/edc/copy/...`` is copy-assist
  (``console.copy_assist_page``, D-434).

Who may do what is the matrix's ``edc.*`` rows (``tb_common.authz.permit``: ``enter_data`` for the work, the PI alone to
switch on, the PI or an admin to switch off; never a viewer or a CRO account), read through the delegation log
(``console.team``). To sign, the person needs their own active entry on the study's delegation log, whose name is the
printed name; to switch on, the log must name them as the PI (D-162). Every call that changes something carries the
person's signed assertion (``actor_header``) and the orchestrator takes the person and role from it, never from the
body; the signature call carries an assertion made right after the password check. The orchestrator checks the switch
and every review rule again (``edc.service``). Each action is one function used by the page and by ``/api/v1``.
"""

from __future__ import annotations

import base64
import re
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from datacore.export import BASE_EVENT
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from httpx import HTTPError
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUpload
from tb_common.authz import Standing as Grant
from tb_common.authz import permit
from tb_common.service_auth import actor_header

from console import demo_guard, s28
from console.api_first import before_body, page_twin
from console.auth import Session, source_of
from console.backend import Problem, Unavailable, service_and_status
from console.home import Helpers
from console.i18n import translate
from console.oidc import OidcError
from console.studies import known_study

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VISIT = re.compile(r"^([a-z][a-z0-9_]{0,99})?$")
_ITEM = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
SOURCES = ("none", "patient", "observation", "condition", "medication", "note")
WHAT = {"none": ("",), "patient": ("birth_date", "sex"), "observation": ("value", "date"),
        "condition": ("presence", "date"), "medication": ("presence", "term", "start"), "note": ("value",)}  # fmt: skip
ACK_KINDS = ("sponsor_letter", "iit_pi_sponsor")
OIDC_METHOD = "oidc+mfa"  # T-205: the signer typed their credentials and a second factor at the provider again
# the page's buttons (``copy``: the copy-assist link, D-434)
EDC_PAGE_ACTIONS = ("map", "draft", "review", "sign", "send", "export", "switch_on", "switch_off", "copy")
ODM_MAX = 6 * 1024 * 1024  # bytes of an ODM file the page reads; the orchestrator's own bound (5 MB) decides
SIGN_TTL = 720.0  # seconds between the sign button and the return from the provider (its ten minutes, and two)


@dataclass(frozen=True)
class PendingSign:
    """A directory account's signature while the person is at the identity provider (T-205): the session that
    asked, the study, and what the page showed when they pressed the button."""

    token_sha: str
    rid: str
    body: ApiSign
    created: float


_CHOICE_WORDS = frozenset({"male", "female", "yes", "no", "true", "false", "unknown"})


def _key(lang: str, key: str) -> str:
    """The catalogue's text for ``key``, or "" when no catalogue has it."""
    text = translate(lang, key)
    return "" if text == key else text


def item_words(d: Mapping[str, Any], f: Mapping[str, Any] | None, m: Mapping[str, Any] | None,
               lang: str) -> dict[str, Any]:  # fmt: skip
    """D-398 (TB-DR-02a UX-010): what the review page shows for one draft in words, not codes.

    ``label``: the item's name in the reader's language: the dictionary's own label in that language, else the
    standard name of its CDASH variable (``edc.var.<cdash>[.<test>]``), else the dictionary's label as written
    (``given`` is then true, so the page marks it as the source's word), else the variable name.
    ``options``: code -> word in the reader's language (the dictionary's choice label in that language, else a common
    word such as Male or Yes from the catalogue, else the choice label as written).
    ``source``: one readable line for the citation ("Test or measurement 2026-11-01: 72.5 kg"); the table, row and
    snapshot stay on the page under "Record reference"."""
    f = f or {}
    m = m or {}
    labels = f.get("labels") or {}
    cdash, test = str(d.get("cdash") or ""), str(d.get("test") or "")
    std = (_key(lang, f"edc.var.{cdash}.{test}") if test else "") or (_key(lang, f"edc.var.{cdash}") if cdash else "")
    own = str(f.get("label") or "") if lang == "en" else str(labels.get(lang) or "")
    label, given = own or std, False
    if not label:
        label, given = str(f.get("label") or "") or str(d.get("item") or ""), lang != "en"
    tr = (f.get("option_labels") or {}).get(lang) or {}
    options: dict[str, str] = {}
    for code, text in (f.get("options") or {}).items():
        word = str(tr.get(code) or "")
        if not word and lang != "en" and str(text).strip().lower() in _CHOICE_WORDS:
            word = translate(lang, f"edc.word.{str(text).strip().lower()}")
        options[str(code)] = word or str(text)
    c = d.get("final_citation") or d.get("citation") or {}
    source = ""
    if c and c.get("kind") != "manual":
        what = _key(lang, f"edc.src.{c.get('table')}")
        if what:
            source = what + (f" {c['day']}" if c.get("day") else "")
            unit = str(m.get("unit") or "")
            if c.get("table") == "observation" and m.get("what", "value") == "value" and d.get("value") and unit:
                source += f": {d['value']} {unit}"
    return {"label": label, "given": given, "options": options, "source": source}


class ApiSwitch(BaseModel):
    on: bool
    kind: str = ""
    reference: str = Field(default="", max_length=120)
    ack_date: str = Field(default="", max_length=10)
    reentry_pages: int = Field(default=0, ge=0, le=100000)
    reentry_accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)
    copy_assist: bool = False  # D-434: on as copy-assist (no acknowledgement; never a write to the sponsor's EDC)


class ApiEdcDictionary(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    record_field: str = Field(default="", max_length=100)


class ApiTarget(BaseModel):
    token_ref: str = Field(min_length=1, max_length=32)
    key_field: str = "tb_screening_no"
    id_field: str = "record_id"


class ApiMap(BaseModel):
    items: list[dict[str, Any]] = Field(max_length=2000)
    target: ApiTarget


class ApiDraft(BaseModel):
    record: str = Field(max_length=64)
    visit: str = Field(default="", max_length=100)
    visit_date: str = Field(max_length=10)


class ApiDecide(BaseModel):
    action: str
    value: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=300)
    source: str = Field(default="", max_length=300)  # where a typed value comes from (a manual citation)
    source_day: str = Field(default="", max_length=10)
    password: str = Field(default="", max_length=200)  # D-281: to change a signed value, the password again
    otp: str = Field(default="", max_length=12)  # and, with TOTP on, a fresh code


class ApiSign(BaseModel):
    record: str = Field(max_length=64)
    visit: str = Field(default="", max_length=100)
    password: str = Field(min_length=1, max_length=200)
    otp: str = Field(default="", max_length=12)  # D-279 (SEC-1 P-2): the second component when TOTP is on
    meaning_ack: bool = False  # the signer read the meaning of the signature
    seen: dict[int, str] = Field(max_length=2000)  # draft id -> ``sha`` of each value the signer saw (GET drafts)


class ApiImport(BaseModel):
    name: str = Field(default="", max_length=120)
    data: str = Field(min_length=1, max_length=8_000_000)  # the ODM file, base64 (the orchestrator bounds the bytes)


class ApiSend(BaseModel):
    record: str | None = Field(default=None, max_length=64)


def err_of(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, Problem):
        return {"code": exc.code, "fields": ", ".join(exc.fields), "problems": exc.problems or
                list((exc.detail or {}).get("problems") or [])}  # fmt: skip
    return {"code": "unavailable", "fields": "", "problems": []}


def percent(text: str) -> float:
    """The re-entry accuracy as typed on the page: ``98.5``, ``98.5 %`` or ``0.985`` -> 0.985."""
    t = text.replace("%", "").strip()
    if not t:
        return 0.0
    x = float(t)
    return min(x / 100 if x > 1 else x, 1.0)


def parse_rows(form: Mapping[str, Any], items: list[str]) -> list[dict[str, Any]]:
    """The map page's rows (``<field>-<item>`` inputs) as map items."""
    out = []
    for it in items:

        def g(k: str, it: str = it) -> str:
            return str(form.get(f"{k}-{it}") or "").strip()

        sex = {}
        for part in g("sex_codes").split(","):
            key, _, val = part.partition("=")
            if key.strip() and val.strip():
                sex[key.strip()] = val.strip()
        try:
            window = int(g("window_days") or "30")
        except ValueError:
            window = -1
        out.append({"item": it, "cdash": g("cdash").upper(), "test": g("test").upper(), "source": g("source") or "none",
                    "what": g("what"), "codes": [c.strip() for c in g("codes").split(",") if c.strip()],
                    "system": g("system"), "unit": g("unit"), "pick": g("pick") or "latest_before",
                    "window_days": window, "yes_code": g("yes_code") or "1", "sex_codes": sex,
                    "question": g("question")})  # fmt: skip
    return out


def parse_seen(text: str) -> dict[int, str]:
    """The sign form's ``id:sha,id:sha`` list of what the page showed."""
    out: dict[int, str] = {}
    for part in text.split(","):
        k, _, v = part.strip().partition(":")
        if k.isdigit() and re.fullmatch(r"[0-9a-f]{64}", v):
            out[int(k)] = v
    return out


SEND_RESULTS = (
    "sent",
    "already_there",
    "conflict",
    "no_record",
    "readback",
    "opted_out",
    "duplicate",
    "no_event",
    "target_changed",
    "stale_map",
    "dictionary_changed",
    "format",
    # T-302b placement and logic, and NEW-EDC-2 (D-690): a repeat instance someone else holds
    "not_on_event",
    "wrong_arm",
    "repeating_form",
    "not_repeating_form",
    "hidden",
    "logic",
    "instance_taken",
    "refused",  # NEW-EDC-7 (D-692): REDCap refused the import of the record
)  # T-115: held back, with the reason


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        return s28.call(bk, method, path, body)

    def act(
        sess: Session, method: str, path: str, body: dict[str, Any] | None = None, session: str | None = None
    ) -> Any:
        """A call the orchestrator attributes to the signed-in person (their signed assertion and role, D-162). A
        patient read (the copy sheet, the ODM export) carries the person's v3 claim instead (NEW-SEC-1, D-717): the
        route verifies it and names that person."""
        from tb_common import patient_reads

        if method.upper() == "GET" and patient_reads.match(method, path) is not None:
            return s28.call(bk, method, path, body)  # signed in s28.call from the request's account
        return s28.call(bk, method, path, body, headers=actor_header(sess.user.username, session, sess.user.role))

    def stand(sess: Session, rid: str) -> tuple[frozenset[str], bool, Any]:
        from console.team import standing

        if h.team is None:
            return frozenset(), False, None
        s = standing(h.team, sess.user, rid, h.today())
        return s.tasks, s.pi, s.entry

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def study_or_404(sess: Session, rs: str, action: str | tuple[str, ...], path: str) -> str:
        """A study this account sees and an ``edc.*`` row it holds; with several actions, any one of them (T-657:
        the check before the body, when the body picks the row)."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not any(may(sess, rid, (action,) if isinstance(action, str) else action).values()):
            raise deny(sess, path)
        return rid

    def first(*actions: str) -> Any:
        """T-657 (D-444): the action's own first check, run before the body is read (console.api_first)."""

        def check(sess: Session, request: Request) -> None:
            study_or_404(sess, request.path_params["rs"], actions, request.url.path)

        return check

    def may(sess: Session, rid: str, actions: tuple[str, ...] = EDC_PAGE_ACTIONS) -> dict[str, bool]:
        """The ``edc.*`` rows (T-102c, D-425) with the account's standing in the study, read once."""
        tasks, pi, _ = stand(sess, rid)
        grant = Grant(is_pi=pi, tasks=tasks)
        return {a: permit(sess.user.role, f"edc.{a}", grant).allowed for a in actions}

    def pid_of(rid: str, record: str) -> str:
        """The subject's pseudonymous id from its screening number (the record key in the EDC); never a chart no."""
        rec = record.strip().upper()
        if not _REC.match(rec):
            raise h.problem(400, "edc.err.edc.record")
        pid = next((p for p, n in store.screening_nos(rid).items() if str(n).upper() == rec), None)
        if pid is None:
            raise h.problem(404, "notfound")
        if pid in h.gone():  # D-477: the one register read of the pages
            raise h.problem(409, "edc.err.edc.opted_out")
        return pid

    # ------------------------------------------------------------------ the actions (page and /api/v1)
    def do_switch(sess: Session, path: str, rs: str, body: ApiSwitch) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "switch_on" if body.on else "switch_off", path)
        if body.on:
            _, _, entry = stand(sess, rid)
            logged = h.team is not None and any(
                e.role == "pi" and e.username == sess.user.username and e.active_on(h.today())
                for e in h.team.entries(rid))  # fmt: skip
            if entry is None or not entry.name or not logged:
                raise h.problem(409, "edc.err.edc.no_log_pi")  # only a PI the log names turns it on (E-10)
        out = act(sess, "POST", f"/studies/{rid}/edc/switch", body.model_dump())
        au.append("console.edc", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "switch", "on": body.on, "copy": body.copy_assist})  # fmt: skip
        return dict(out)

    def do_dictionary(sess: Session, path: str, rs: str, body: ApiEdcDictionary) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "map", path)
        return dict(act(sess, "POST", f"/studies/{rid}/edc/dictionary", body.model_dump()))

    def do_map(sess: Session, path: str, rs: str, body: ApiMap) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "map", path)
        return dict(act(sess, "PUT", f"/studies/{rid}/edc/map", body.model_dump()))

    def do_draft(sess: Session, path: str, rs: str, body: ApiDraft) -> list[dict[str, Any]]:
        rid = study_or_404(sess, rs, "draft", path)
        if not _VISIT.match(body.visit):
            raise h.problem(400, "edc.err.edc.visit")
        pid = pid_of(rid, body.record)
        return list(act(sess, "POST", f"/studies/{rid}/edc/drafts", {"record": body.record.strip().upper(),
                                                                     "pid": pid, "visit": body.visit,
                                                                     "visit_date": body.visit_date}))  # fmt: skip

    def refuse(sess: Session, rid: str, status: int, key: str, record: str = "") -> Exception:
        """A refusal of the signing or unlocking step, audited before it is raised (D-281, SEC-7)."""
        au.append("console.edc_refused", ruleset=rid, actor=h.actor(sess),
                  detail={"record": record.upper()[:64], "code": key.removeprefix("edc.err.")})  # fmt: skip
        return h.problem(status, key)

    def oidc_signer(sess: Session) -> bool:
        """Signs at the identity provider (T-205): an OIDC account on a console with OIDC on."""
        ident = h.identity
        return ident is not None and ident.oidc_enabled and h.users.is_oidc(sess.user.username)

    def reauth(sess: Session, rid: str, password: str, otp: str, source: str, record: str) -> str:
        """The person types their password again and, with TOTP on, a fresh code (two components, 21 CFR 11.200(a);
        D-279), each failure counting toward the lockout of that address. Answers how (``password`` or
        ``password+totp``); refuses with an audited problem otherwise."""
        if h.users.is_sso(sess.user.username):
            raise refuse(sess, rid, 409, "edc.err.edc.sign_sso", record)
        if h.users.must_change(sess.user.username):  # D-279 (P-1): never sign with a password someone else set
            raise refuse(sess, rid, 409, "edc.err.edc.must_change", record)
        if h.users.authenticate(sess.user.username, password, source=source) is None:
            au.append("console.edc_reauth_failed", ruleset=rid, actor=h.actor(sess),
                      detail={"record": record.upper()[:64]})  # fmt: skip
            raise h.problem(401, "edc.err.edc.reauth")
        why = h.identity.step_up(sess.user.username, otp, source) if h.identity is not None else ""
        if why:  # D-279 (P-2): the second component; a wrong or replayed code signs nothing
            au.append("console.edc_reauth_failed", ruleset=rid, actor=h.actor(sess),
                      detail={"record": record.upper()[:64], "factor": "totp", "reason": why})  # fmt: skip
            raise h.problem(401, "edc.err.edc.otp")
        totp_on = h.identity is not None and h.identity.settings.totp_required
        return "password+totp" if totp_on else "password"

    def do_decide(
        sess: Session, path: str, rs: str, draft_id: int, body: ApiDecide, source: str = ""
    ) -> dict[str, Any]:
        """Confirm, change or reject a value. With ``password`` the person re-authenticates first, which unlocks a
        signed value (the record lock, D-281, CR-035); without it a signed value is refused by the orchestrator."""
        rid = study_or_404(sess, rs, "review", path)
        cit = {"text": body.source, "day": body.source_day} if body.source.strip() else None
        payload: dict[str, Any] = {"action": body.action, "value": body.value, "reason": body.reason, "citation": cit}
        session = None
        if body.password:
            reauth(sess, rid, body.password, body.otp, source, f"draft-{draft_id}")
            payload["unlock"] = True
            session = "reauth-" + secrets.token_hex(8)
        return dict(act(sess, "POST", f"/studies/{rid}/edc/drafts/{draft_id}/decide", payload, session=session))

    def sign_checks(sess: Session, rid: str, body: ApiSign) -> Any:
        """What a signature needs besides the re-authentication: a visit name, the meaning acknowledged, the
        signer's own entry on the delegation log (its name is the printed name, never a login name; E-10) and what
        the page showed. Each refusal is audited (D-281, SEC-7). Answers the log entry."""
        rec = body.record
        if not _VISIT.match(body.visit):
            raise refuse(sess, rid, 400, "edc.err.edc.visit", rec)
        if not body.meaning_ack:
            raise refuse(sess, rid, 400, "edc.err.edc.meaning_ack", rec)
        _, _, entry = stand(sess, rid)
        if entry is None or not entry.name:
            raise refuse(sess, rid, 409, "edc.err.edc.no_log_entry", rec)
        if not body.seen:
            raise refuse(sess, rid, 400, "edc.err.edc.sign_changed", rec)
        return entry

    def do_sign(sess: Session, path: str, rs: str, body: ApiSign, source: str = "", proved: str = "") -> dict[str, Any]:
        """The electronic signature: the signer types their password again and, with TOTP on, a fresh code from
        their authenticator (two components, 21 CFR 11.200(a); D-279), each failure counting toward the lockout of
        that address, and acknowledges the meaning; the printed name is the one on the delegation log. ``proved``
        (T-205): a directory account re-authenticated at the identity provider just before (``oidc+mfa``). Every
        refusal is audited (D-281, SEC-7); the signature records how the signer re-authenticated."""
        rid = study_or_404(sess, rs, "sign", path)
        rec = body.record
        if not _VISIT.match(body.visit):
            raise refuse(sess, rid, 400, "edc.err.edc.visit", rec)
        if not proved and oidc_signer(sess):  # its password is the provider's: the review page sends it there
            raise refuse(sess, rid, 409, "edc.err.edc.sign_oidc_page", rec)
        if not proved and h.users.is_sso(sess.user.username):
            raise refuse(sess, rid, 409, "edc.err.edc.sign_sso", rec)
        if not body.meaning_ack:
            raise refuse(sess, rid, 400, "edc.err.edc.meaning_ack", rec)
        method = proved or reauth(sess, rid, body.password, body.otp, source, rec)
        entry = sign_checks(sess, rid, body)
        out = act(sess, "POST", f"/studies/{rid}/edc/sign", {
            "record": body.record.strip().upper(), "visit": body.visit, "printed_name": entry.name,
            "meaning": "transcribed", "lang": sess.lang, "meaning_text": translate(sess.lang, "edc.sign.meaning"),
            "method": method, "seen": {str(k): v for k, v in body.seen.items()}},
            session="reauth-" + secrets.token_hex(8))  # fmt: skip
        return dict(out)

    def do_send(sess: Session, path: str, rs: str, record: str | None) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "send", path)
        rec = record.strip().upper() if record else None
        if rec is not None and not _REC.match(rec):
            raise h.problem(400, "edc.err.edc.record")
        return dict(act(sess, "POST", f"/studies/{rid}/edc/send/redcap", {"record": rec}))

    def do_import(sess: Session, path: str, rs: str, body: ApiImport) -> dict[str, Any]:
        """An ODM file read into open drafts that cite it (D-435): proposals a person confirms and signs; the same
        question as a draft run (T-302c)."""
        rid = study_or_404(sess, rs, "draft", path)
        out = dict(act(sess, "POST", f"/studies/{rid}/edc/import/odm", body.model_dump()))
        au.append("console.edc", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "import_odm", "file": str(out.get("file") or "")[:16]})  # fmt: skip
        return out

    def do_export(sess: Session, path: str, rs: str) -> dict[str, Any]:
        rid = study_or_404(sess, rs, "export", path)
        return dict(act(sess, "GET", f"/studies/{rid}/edc/export/odm"))

    # ------------------------------------------------------------------ pages
    def status_page(request: Request, sess: Session, rid: str, err: dict[str, Any] | None = None,
                    status: int = 200) -> Response:  # fmt: skip
        st = call("GET", f"/studies/{rid}/edc")
        nos = {str(n).upper(): p for p, n in store.screening_nos(rid).items()}
        try:
            conns = [c["token_ref"] for c in (call("GET", "/redcap/connections").get("connections") or [])]
        except (Problem, Unavailable):
            conns = []
        resp = h.page(request, "edc.html", sess, rs=rid, st=st, may=may(sess, rid), subjects=sorted(nos),
                      connections=conns, kinds=ACK_KINDS, err=err)  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc")
    def edc_home(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        try:
            return status_page(request, sess, rid)
        except (Problem, Unavailable) as exc:
            return h.page(request, "edc.html", sess, rs=rid, st=None, may=may(sess, rid), subjects=[],
                          connections=[], kinds=ACK_KINDS, err=err_of(exc))  # fmt: skip

    async def form_of(request: Request, sess: Session) -> Any:
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        return form

    def back(rid: str, sess: Session, request: Request, exc: Exception) -> Response:
        return status_page(request, sess, rid, err_of(exc), 409)

    @app.post("/studies/{rs}/edc/switch")
    async def edc_switch(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        on = str(form.get("on") or "") == "1"
        rid = study_or_404(sess, rs, "switch_on" if on else "switch_off", request.url.path)
        try:
            pages = int(str(form.get("reentry_pages") or "0") or 0)
            acc = percent(str(form.get("reentry_accuracy") or ""))
            body = ApiSwitch(on=on, kind=str(form.get("kind") or ""), reference=str(form.get("reference") or ""),
                             ack_date=str(form.get("ack_date") or ""), reentry_pages=pages,
                             reentry_accuracy=min(acc, 1.0), reason=str(form.get("reason") or ""),
                             copy_assist=on and str(form.get("mode") or "") == "copy")  # fmt: skip
        except ValueError:
            return status_page(request, sess, rid, {"code": "edc.reentry", "fields": "", "problems": []}, 400)
        try:
            do_switch(sess, request.url.path, rid, body)
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)
        return RedirectResponse(f"/studies/{rid}/edc?done=switch", status_code=303)

    @app.post("/studies/{rs}/edc/drafts")
    async def edc_draft(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "draft", request.url.path)
        rec, visit = str(form.get("record") or "").strip().upper(), str(form.get("visit") or "").strip()
        try:
            do_draft(sess, request.url.path, rid, ApiDraft(record=rec, visit=visit,
                                                         visit_date=str(form.get("visit_date") or "")))  # fmt: skip
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec}?visit={visit}", status_code=303)

    @app.post("/studies/{rs}/edc/send")
    async def edc_send(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "send", request.url.path)
        rec = str(form.get("record") or "").strip() or None
        try:
            out = do_send(sess, request.url.path, rid, rec)
        except (Problem, Unavailable) as exc:
            if rec:
                return review_page(request, sess, rid, rec, str(form.get("visit") or ""), err_of(exc), 409)
            return back(rid, sess, request, exc)
        q = "&".join(f"{k}={len(out.get(k) or [])}" for k in SEND_RESULTS)
        if rec:
            return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={form.get('visit') or ''}&{q}",
                                    status_code=303)  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/edc?{q}", status_code=303)

    @app.post("/studies/{rs}/edc/import")
    async def edc_import(request: Request, rs: str) -> Response:
        """T-302c: the page of D-435's ODM import. Who, before the file is read."""
        sess = h.need(request)
        rid = study_or_404(sess, rs, "draft", request.url.path)
        demo_guard.guard(request, h.problem)  # T-502: no upload in demo mode
        form = await form_of(request, sess)
        up = form.get("file")
        data = await up.read(ODM_MAX + 1) if isinstance(up, StarletteUpload) else b""
        name = str(getattr(up, "filename", "") or "")[:120]
        if not data or len(data) > ODM_MAX:
            return status_page(request, sess, rid, {"code": "odm.size", "fields": "", "problems": []}, 400)
        try:
            out = do_import(sess, request.url.path, rid,
                            ApiImport(name=name, data=base64.b64encode(data).decode("ascii")))  # fmt: skip
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)
        q = "&".join(f"imp_{key}={len(out.get(key) or [])}" for key in ("drafted", "decided", "same"))
        return RedirectResponse(f"/studies/{rid}/edc?imported=1&{q}", status_code=303)

    @app.get("/studies/{rs}/edc/export.odm.xml")
    def edc_odm(request: Request, rs: str) -> Response:
        sess = h.need(request)
        try:
            out = do_export(sess, request.url.path, rs)
        except (Problem, Unavailable) as exc:
            return back(rs.strip().upper(), sess, request, exc)
        return Response(str(out["text"]), media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{out["name"]}"'})  # fmt: skip

    # ------------------------------------------------------------------ the map
    def map_page(request: Request, sess: Session, rid: str, err: dict[str, Any] | None = None, status: int = 200,
                 rows: list[dict[str, Any]] | None = None) -> Response:  # fmt: skip
        st = call("GET", f"/studies/{rid}/edc")
        fields = {f["name"]: f for f in (call("GET", f"/studies/{rid}/sources").get("fields") or [])}
        saved = {m["item"]: m for m in st.get("map") or []}
        if rows is None:
            rows = st.get("map") or []
            if request.query_params.get("suggest") or not rows:
                sug = {m["item"]: m for m in call("GET", f"/studies/{rid}/edc/map/suggest")}
                rows = [saved.get(i) or sug[i] for i in sug] if not request.query_params.get("suggest") else list(
                    sug.values())  # fmt: skip
        try:
            conns = [c["token_ref"] for c in (call("GET", "/redcap/connections").get("connections") or [])]
        except (Problem, Unavailable):
            conns = []
        bad: dict[str, list[str]] = {}
        for p in (err or {}).get("problems") or []:
            bad.setdefault(str(p.get("item")), []).append(str(p.get("code")))
        resp = h.page(request, "edc_map.html", sess, rs=rid, rows=rows, fields=fields, st=st, sources=SOURCES,
                      what=WHAT, connections=conns, err=err, bad=bad, may=may(sess, rid))  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc/map")
    def edc_map(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "map", request.url.path)
        return map_page(request, sess, rid)

    @app.post("/studies/{rs}/edc/dictionary")
    async def edc_dictionary(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "map", request.url.path)
        try:
            out = do_dictionary(
                sess,
                request.url.path,
                rid,
                ApiEdcDictionary(
                    token_ref=str(form.get("token_ref") or "x")[:32], record_field=str(form.get("record_field") or "")
                ),
            )
        except (Problem, Unavailable) as exc:
            return map_page(request, sess, rid, err_of(exc), 409)
        return RedirectResponse(f"/studies/{rid}/edc/map?suggest=1&fields={out.get('fields', 0)}", status_code=303)

    @app.post("/studies/{rs}/edc/map")
    async def edc_map_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "map", request.url.path)
        items = [str(i) for i in form.getlist("item") if _ITEM.match(str(i))]
        rows = parse_rows(form, items)
        target = ApiTarget(token_ref=str(form.get("token_ref") or "x")[:32] or "x",
                           key_field=str(form.get("key_field") or "tb_screening_no"),
                           id_field=str(form.get("id_field") or "record_id"))  # fmt: skip
        try:
            do_map(sess, request.url.path, rid, ApiMap(items=rows, target=target))
        except (Problem, Unavailable) as exc:
            return map_page(request, sess, rid, err_of(exc), 409, rows)
        return RedirectResponse(f"/studies/{rid}/edc?done=map", status_code=303)

    # ------------------------------------------------------------------ review and sign
    def review_page(request: Request, sess: Session, rid: str, record: str, visit: str,
                    err: dict[str, Any] | None = None, status: int = 200) -> Response:  # fmt: skip
        rec = record.strip().upper()
        if not _REC.match(rec) or not _VISIT.match(visit):
            raise h.problem(404, "notfound")
        pid_of(rid, rec)  # a subject of this study (and not opted out)
        q = f"?record={rec}" + (f"&visit={visit}" if visit else "")
        drafts = list(call("GET", f"/studies/{rid}/edc/drafts{q}"))
        fields = {f["name"]: f for f in (call("GET", f"/studies/{rid}/sources").get("fields") or [])}
        st = call("GET", f"/studies/{rid}/edc")
        _, _, entry = stand(sess, rid)
        name = entry.name if entry is not None and entry.name else ""
        visits = sorted({str(d["visit"]) for d in drafts})
        here = visit or BASE_EVENT  # the sign call signs this one visit: show and count only its values (E-11)
        unsigned = [d for d in drafts if d["fate"] in ("confirmed", "edited") and d["signature_id"] is None
                    and d["visit"] == here]  # fmt: skip
        lang = sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"
        maps = {str(m.get("item")): m for m in (st.get("map") or [])}
        words = {d["id"]: item_words(d, fields.get(d["item"]), maps.get(d["item"]), lang) for d in drafts}
        resp = h.page(request, "edc_review.html", sess, rs=rid, record=rec, visit=visit, visits=visits, drafts=drafts,
                      fields=fields, words=words, st=st, unsigned=unsigned, printed_name=name, err=err,
                      may=may(sess, rid), sso=h.users.is_sso(sess.user.username),
                      oidc_sign=oidc_signer(sess))  # fmt: skip
        resp.status_code = status
        return resp

    @app.get("/studies/{rs}/edc/review/{record}")
    def edc_review(request: Request, rs: str, record: str, visit: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "review", request.url.path)
        try:
            return review_page(request, sess, rid, record, visit)
        except (Problem, Unavailable) as exc:
            return back(rid, sess, request, exc)

    @app.post("/studies/{rs}/edc/decide/{draft_id}")
    async def edc_decide(request: Request, rs: str, draft_id: int) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "review", request.url.path)
        rec, visit = str(form.get("record") or ""), str(form.get("visit") or "")
        body = ApiDecide(action=str(form.get("action") or ""), value=str(form.get("value") or "")[:2000],
                         reason=str(form.get("reason") or "")[:300], source=str(form.get("source") or "")[:300],
                         source_day=str(form.get("source_day") or "")[:10],
                         password=str(form.get("password") or "")[:200],
                         otp=str(form.get("otp") or "")[:12])  # fmt: skip
        try:
            do_decide(sess, request.url.path, rid, draft_id, body,
                      source_of(request.client.host if request.client else None))  # fmt: skip
        except (Problem, Unavailable) as exc:
            return review_page(request, sess, rid, rec, visit, {**err_of(exc), "draft": draft_id}, 409)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={visit}#d{draft_id}", status_code=303)

    @app.post("/studies/{rs}/edc/sign")
    async def edc_sign(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await form_of(request, sess)
        rid = study_or_404(sess, rs, "sign", request.url.path)
        rec, visit = str(form.get("record") or ""), str(form.get("visit") or "")
        body = ApiSign(
            record=rec[:64] or "x",
            visit=visit[:100],
            password=str(form.get("password") or "")[:200] or " ",
            otp=str(form.get("otp") or "")[:12],
            meaning_ack=str(form.get("meaning_ack") or "") == "1",
            seen=parse_seen(str(form.get("seen") or "")[:200000]),
        )
        if oidc_signer(sess):  # T-205: to the identity provider for a fresh sign-in, then back to sign_oidc
            return start_oidc_sign(request, sess, rid, body)
        try:
            do_sign(sess, request.url.path, rid, body, source_of(request.client.host if request.client else None))
        except (Problem, Unavailable) as exc:
            return review_page(request, sess, rid, rec, visit, err_of(exc), 409)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={visit}&signed=1", status_code=303)

    # ------------------------------------------------------------------ signing with a directory account (T-205)
    pending: dict[str, PendingSign] = {}

    def start_oidc_sign(request: Request, sess: Session, rid: str, body: ApiSign) -> Response:
        """Check what can be checked now, keep what the page showed, and send the person to the provider with
        ``prompt=login`` and ``max_age=0``; the provider's answer comes back to :func:`edc_sign_oidc`."""
        sign_checks(sess, rid, body)
        now = time.time()
        for key in [key for key, p in pending.items() if now - p.created > SIGN_TTL]:
            del pending[key]
        if len(pending) > 1000:  # bounded: one console, a handful of signers
            pending.clear()
        ticket = secrets.token_urlsafe(24)
        pending[ticket] = PendingSign(sess.token_sha, rid, body, now)
        assert h.identity is not None
        try:
            resp: Response = h.identity.start_reauth(sess.user.username, f"/studies/{rid}/edc/sign/oidc/{ticket}")
            return resp
        except (OidcError, OSError, ValueError, HTTPError) as exc:
            pending.pop(ticket, None)
            why = str(exc)[:80] if isinstance(exc, OidcError) else type(exc).__name__
            au.append("console.edc_reauth_failed", ruleset=rid, actor=h.actor(sess),
                      detail={"record": body.record.upper()[:64], "factor": "oidc", "reason": why})  # fmt: skip
            raise h.problem(502, "edc.err.edc.idp_unreachable") from exc

    @app.get("/studies/{rs}/edc/sign/oidc/{ticket}")
    def edc_sign_oidc(request: Request, rs: str, ticket: str, reauth: str = "") -> Response:
        """Back from the identity provider: the same session, the same person, a fresh sign-in with a second factor
        (``Identity.take_reauth``, single use, two minutes), then the signature of what the page showed."""
        sess = h.need(request)
        rid = study_or_404(sess, rs, "sign", request.url.path)
        p = pending.pop(ticket[:64], None)
        if p is None or p.rid != rid or p.token_sha != sess.token_sha or time.time() - p.created > SIGN_TTL:
            raise refuse(sess, rid, 409, "edc.err.edc.sign_oidc_expired")
        rec, visit = p.body.record, p.body.visit
        found = h.identity.take_reauth(reauth, sess.user.username) if h.identity is not None and reauth else None
        if found is None:
            au.append("console.edc_reauth_failed", ruleset=rid, actor=h.actor(sess),
                      detail={"record": rec.upper()[:64], "factor": "oidc"})  # fmt: skip
            raise h.problem(401, "edc.err.edc.reauth_oidc")
        try:
            do_sign(sess, request.url.path, rid, p.body, proved=OIDC_METHOD)
        except (Problem, Unavailable) as exc:
            return review_page(request, sess, rid, rec, visit, err_of(exc), 409)
        return RedirectResponse(f"/studies/{rid}/edc/review/{rec.upper()}?visit={visit}&signed=1", status_code=303)

    @app.get("/studies/{rs}/edc/trail/{record}")
    def edc_trail(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        rec = record.strip().upper()
        pid_of(rid, rec)
        trail = call("GET", f"/studies/{rid}/edc/trail/{rec}")
        return h.page(request, "edc_trail.html", sess, rs=rid, record=rec, trail=trail)

    # ------------------------------------------------------------------ /api/v1
    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def api_call(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except Problem as exc:
            status = exc.status if 400 <= exc.status < 500 else 502
            raise h.problem(status, "request.refused", code=exc.code, reason=exc.message,
                            fields=", ".join(exc.fields)) from exc  # fmt: skip
        except Unavailable as exc:
            raise h.problem(503, "unavailable", detail=service_and_status(exc)) from exc

    @app.get("/api/v1/studies/{rs}/edc")
    def api_status(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        return {"study": rid, "may": may(sess, rid), **api_call(call, "GET", f"/studies/{rid}/edc")}

    @app.post("/api/v1/studies/{rs}/edc/switch")
    @before_body(first("switch_on", "switch_off"))
    def api_switch(request: Request, rs: str, body: ApiSwitch) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), "switch": api_call(do_switch, sess, request.url.path, rs, body)}

    @app.post("/api/v1/studies/{rs}/edc/dictionary")
    @before_body(first("map"))
    def api_dictionary(request: Request, rs: str, body: ApiEdcDictionary) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_dictionary, sess, request.url.path, rs, body)}

    @app.get("/api/v1/studies/{rs}/edc/map")
    def api_map(request: Request, rs: str, suggest: bool = False) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "map", request.url.path)
        if suggest:
            return {"study": rid, "items": api_call(call, "GET", f"/studies/{rid}/edc/map/suggest")}
        st = api_call(call, "GET", f"/studies/{rid}/edc")
        return {"study": rid, "items": st.get("map") or [], "target": st.get("target")}

    @app.put("/api/v1/studies/{rs}/edc/map")
    @before_body(first("map"))
    def api_put_map(request: Request, rs: str, body: ApiMap) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_map, sess, request.url.path, rs, body)}

    @app.post("/api/v1/studies/{rs}/edc/drafts")
    @before_body(first("draft"))
    def api_draft(request: Request, rs: str, body: ApiDraft) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), "drafts": api_call(do_draft, sess, request.url.path, rs, body)}

    @app.get("/api/v1/studies/{rs}/edc/drafts")
    def api_drafts(request: Request, rs: str, record: str = "", visit: str = "") -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "review", request.url.path)  # who may look comes before what was asked
        rec = record.strip().upper()
        pid_of(rid, rec)
        if not _VISIT.match(visit):
            raise h.problem(400, "edc.err.edc.visit")
        q = f"?record={rec}" + (f"&visit={visit}" if visit else "")
        return {"study": rid, "record": rec, "drafts": api_call(call, "GET", f"/studies/{rid}/edc/drafts{q}")}

    @app.post("/api/v1/studies/{rs}/edc/drafts/{draft_id}/decide")
    @before_body(first("review"))
    @page_twin("/studies/{rs}/edc/decide/{draft_id}")
    def api_decide(request: Request, rs: str, draft_id: int, body: ApiDecide) -> dict[str, Any]:
        sess = api(request)
        return {
            "study": rs.upper(),
            "draft": api_call(
                do_decide,
                sess,
                request.url.path,
                rs,
                draft_id,
                body,
                source_of(request.client.host if request.client else None),
            ),
        }

    @app.post("/api/v1/studies/{rs}/edc/sign")
    @before_body(first("sign"))
    def api_sign(request: Request, rs: str, body: ApiSign) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(),
                "signature": api_call(do_sign, sess, request.url.path, rs, body,
                                      source_of(request.client.host if request.client else None))}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/edc/import/odm")
    @before_body(first("draft"))  # T-657 (D-444): the session and the row before the body
    @page_twin("/studies/{rs}/edc/import")
    def api_import(request: Request, rs: str, body: ApiImport) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_import, sess, request.url.path, rs, body)}

    @app.post("/api/v1/studies/{rs}/edc/send")
    @before_body(first("send"))
    def api_send(request: Request, rs: str, body: ApiSend) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_send, sess, request.url.path, rs, body.record)}

    @app.get("/api/v1/studies/{rs}/edc/export/odm")
    def api_export(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        return {"study": rs.upper(), **api_call(do_export, sess, request.url.path, rs)}

    @app.get("/api/v1/studies/{rs}/edc/trail/{record}")
    def api_trail(request: Request, rs: str, record: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs, "view", request.url.path)
        rec = record.strip().upper()
        pid_of(rid, rec)
        return {"study": rid, "record": rec, **api_call(call, "GET", f"/studies/{rid}/edc/trail/{rec}")}
