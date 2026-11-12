"""S21 Study set-up (three sections in build step 3) and S36 REDCap connection (D-109).

S21 sections: (1) Study: type, cohort kind, consent; (2) REDCap link: the per-study field map (ICD-04 §4.1a), Test
link, and the read-back (last read, Run now, duplicates, unmatched records, conflicts); (3) Screening log: the
screening-number prefix and next number, and the "Not suitable" reason list. Everything is saved in the orchestrator's
S-28 study store through its API; the coordinator edits, everyone on the study reads.

S36 (administrators): the REDCap base URL and the API tokens, entered once and shown masked, with Test connection.

D-386 (T-622, LIFE-008, LIFE-013): ``/studies/{rs}/state`` holds the study's state (start-up, open, paused, closed)
and its identifiers (sponsor, protocol number, SIV date, registry ids). Everyone who reads the set-up reads it; the
coordinator and the study's PI change it (``tb_common.authz.permit``, action ``study.state``). Each change is
audited (``console.study_state``, ``console.study_identity``).

D-395 (T-310b, RSK-42): the same page holds the IRB-text record: the study's PI records whether the approved IRB text
covers "identified pre-screening across departments by the investigator before referral", with the approval number,
the text's version and its date (``permit``, action ``study.irb_text``; audited ``console.irb_text`` in the store's
transaction). The whole-hospital candidate view (``console.team``) opens only while the record says it does.

The nightly read-back is ``python -m console.rc_read`` (cron on the box), the same call as Run now.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from datacore import lifecycle as lc
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from tb_common.authz import permit

from console import actor, s28
from console import studies as st
from console.auth import Session, User
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.sitestore import (
    ALL_REASONS,
    COHORT_KINDS,
    IRB_SENTENCE_EN,
    REGISTRIES,
    STATE_MOVES,
    STUDY_STATES,
    STUDY_TYPES,
    IrbText,
    StudyIdentity,
    StudySettings,
    StudyState,
)
from console.studies import known_study
from console.timefmt import site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_PRACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
CONSENT_SCOPES = ("opt-in", "opt-out", "waiver")
LINK_TEXT = (
    "dag",
    "link_field",
    "consent_field",
    "consent_event",
    "enrol_field",
    "enrol_value",
    "screenfail_field",
    "withdraw_field",
    "withdraw_value",
    "subject_no_field",
    "write_mode",
    "write_form",
    "write_event",
)


def parse_map(text: str) -> dict[str, str]:
    """``"1=inclusion, 2=exclusion"`` (commas, semicolons or new lines) -> ``{"1": "inclusion", ...}``."""
    out: dict[str, str] = {}
    for part in re.split(r"[,;\n]", text or ""):
        code, sep, cat = part.partition("=")
        if sep and code.strip():
            out[code.strip()] = cat.strip()
    return out


def show_map(m: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in m.items())


def can_change_setup(user: User) -> bool:
    """Who changes a study's set-up (S21) and its data sources, forms and conflicts: the study's coordinator."""
    return permit(user.role, "study.setup").allowed  # T-102c (D-425): the matrix row


REASON_STATES = ("paused", "closed")  # D-386: a move to these takes a reason
# T-629 (FIT-U06, D-415): the study types that report serious adverse events; a study of one of them opens only once
# its type for SAE reporting (the rule set, which selects the reporting table) is chosen and confirmed
SAE_STUDY_TYPES = ("trial", "observational")


def site_country(bk: object) -> str:
    """The site's country (JP, TW) from ``site.tz``; empty when the zone names none."""
    from tb_common.derived import country_of

    try:
        return country_of(str(site_zone(bk))) or ""
    except Exception:
        return ""


def sae_sets_for(country: str) -> dict[str, lc.RuleSet]:
    """FIT-U06: the study types of the site's country (its SAE rule sets); every set when the country is unknown."""
    return {k: v for k, v in lc.RULE_SETS.items() if not country or v.country == country}


def _permit(h: Helpers, user: User, rid: str, action: str) -> bool:
    """``permit`` over ``action`` with the account's standing in the study (the delegation log, for the
    investigator's ``pi`` condition)."""
    return h.permit(user, action, rid).allowed


def may_change_state(h: Helpers, user: User, rid: str) -> bool:
    """D-386: may this account change the study's state and identifiers?"""
    return _permit(h, user, rid, "study.state")


def may_record_irb_text(h: Helpers, user: User, rid: str) -> bool:
    """D-395: may this account record the IRB text's coverage? The study's PI only."""
    return _permit(h, user, rid, "study.irb_text")


def screening_map(store: Any, rs: str) -> dict[str, str]:
    """Screening number -> pid for the read-back join (the console's site store issues the numbers)."""
    return {no: pid for pid, no in store.screening_nos(rs).items()}


def read_now(h: Helpers, rs: str, by: str) -> dict[str, Any]:
    """Run now and the nightly job: the orchestrator reads REDCap through the study's link and updates the log."""
    issued = {no: at for _pid, no, at in h.store.screening_rows(rs)}
    body = {"screening": screening_map(h.store, rs), "issued": issued, "by": by}
    out = s28.call(h.bk, "POST", f"/studies/{rs}/redcap-read", body)
    return dict(out)


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.sponsor_form or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not sess.user.can_view_phi:  # D-146 (review J-05): a viewer reads aggregate reports, not a study's set-up
            au.append("console.denied", actor=h.actor(sess), detail={"action": f"setup {rid}"})
            raise h.problem(403, "forbidden")
        return rid

    def can_edit(sess: Session) -> bool:
        return can_change_setup(sess.user)

    def need_edit(request: Request, sess: Session, csrf: str) -> None:
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not can_edit(sess):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    def err_of(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, Problem):
            return {"code": exc.code, "msg": exc.message, "fields": ", ".join(exc.fields)}
        return {"code": "unavailable", "msg": "", "fields": ""}

    def get_or_none(path: str) -> Any:
        try:
            return s28.call(bk, "GET", path)
        except (Problem, Unavailable):
            return None

    def defaults(rid: str) -> StudySettings:
        kind = next((r.kind for r in bk.rulesets() if r.id == rid), "trial")
        return st.study_defaults(rid, kind)

    def setup_page(
        request: Request, sess: Session, rid: str, form_conf: StudySettings | None = None, **extra: Any
    ) -> Response:
        conf = form_conf or s28.load(bk, store, rid, defaults(rid))
        row = s28.remote(bk, rid) if s28.has_api(bk) else None
        link = get_or_none(f"/studies/{rid}/redcap-link")
        conns = get_or_none("/redcap/connections") or {}
        reads = (link or {}).get("reads") or []
        lk = (link or {}).get("link") or {}
        return h.page(
            request,
            "setup.html",
            sess,
            rs=rid,
            conf=conf,
            row=row,
            api=s28.has_api(bk),
            editable=can_edit(sess),
            link=link,
            lk=lk,
            sf_map=show_map(lk.get("screenfail_choice_map") or {}),
            tokens=[c["token_ref"] for c in conns.get("connections") or []],
            screen_scope=get_or_none(f"/studies/{rid}/screen-scope") if s28.has_api(bk) else None,
            sae_rule=get_or_none(f"/studies/{rid}/sae-rule") if s28.has_api(bk) else None,
            sae_country=site_country(bk),  # T-629 (FIT-U06): only this country's study types are offered
            contact_rule=get_or_none(f"/studies/{rid}/contact-rule") if s28.has_api(bk) else None,
            last=reads[0] if reads else None,
            all_reasons=ALL_REASONS,
            study_types=STUDY_TYPES,
            cohort_kinds=COHORT_KINDS,
            scopes=CONSENT_SCOPES,
            example=f"{conf.screening_prefix or rid + '-'}{max(conf.first_no, 1):04d}",
            **{
                "saved": request.query_params.get("saved", ""),
                "err": None,
                "test": None,
                "read": None,
                "rc_dict": None,
                "scope_form": None,
                **extra,
            },
        )

    @app.get("/studies/{rs}/setup")
    def setup(request: Request, rs: str) -> Response:
        sess = h.need(request)
        return setup_page(request, sess, study_or_404(sess, rs))

    def save_settings(request: Request, sess: Session, rid: str, s: StudySettings, extra: dict[str, Any],
                      section: str) -> Response:  # fmt: skip
        try:
            s28.save(bk, rid, s, h.actor(sess), extra)
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail={"section": section})
        return RedirectResponse(f"/studies/{rid}/setup?saved={section}#{section}", status_code=303)

    @app.post("/studies/{rs}/setup/study")
    def save_study(
        request: Request,
        rs: str,
        csrf: str = Form(""),
        study_type: str = Form("trial"),
        cohort_kind: str = Form("enrolled"),
        consent_scope: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_edit(request, sess, csrf)
        if study_type not in STUDY_TYPES or cohort_kind not in COHORT_KINDS:
            raise h.problem(400, "request.refused", reason="unknown study type or cohort kind")
        conf = s28.load(bk, store, rid, defaults(rid))
        row = s28.remote(bk, rid) or {}
        s = StudySettings(study_type, cohort_kind, conf.reasons, conf.screening_prefix, conf.first_no)
        scope = consent_scope if consent_scope in CONSENT_SCOPES else None
        return save_settings(request, sess, rid, s, {"consent_scope": scope,
                             "introduce_rule": row.get("introduce_rule")}, "study")  # fmt: skip

    @app.post("/studies/{rs}/setup/sae")
    def save_sae_rule(request: Request, rs: str, csrf: str = Form(""), rule_set: str = Form("")) -> Response:
        """D-277 (LIFE-023): the study's SAE rule set, one of the named sets; the coordinator who saves it confirms
        it, and the SAE pages name the set and who confirmed it."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_edit(request, sess, csrf)
        country = site_country(bk)
        if rule_set.strip() in lc.RULE_SETS and rule_set.strip() not in sae_sets_for(country):
            # T-629 (FIT-U06): a study type of another country would select another country's reporting table
            return setup_page(request, sess, rid, err={"code": "SAE-COUNTRY", "msg": country, "fields": ""})
        try:
            actor.call(h, sess, "study.setup", rid, "PUT", f"/studies/{rid}/sae-rule",
                       {"rule_set": rule_set.strip()[:40]})  # fmt: skip
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        detail = {"section": "sae", "rule_set": rule_set[:40]}
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail=detail)
        return RedirectResponse(f"/studies/{rid}/setup?saved=sae#sae", status_code=303)

    @app.post("/studies/{rs}/setup/contact")
    def save_contact_rule(request: Request, rs: str, csrf: str = Form(""), max_attempts: str = Form(""),
                          min_days: str = Form("")) -> Response:  # fmt: skip
        """D-407 (LIFE-017): the study's contact-attempt limit and the days between two attempts; after the limit
        the coordinator's list asks the investigator."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_edit(request, sess, csrf)
        try:
            body = {"max_attempts": int(max_attempts), "min_days": int(min_days)}
        except ValueError:
            raise h.problem(400, "request.refused", reason="attempts and days are whole numbers") from None
        try:
            actor.call(h, sess, "study.setup", rid, "PUT", f"/studies/{rid}/contact-rule", body)
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        au.append(
            "console.study_setup",
            ruleset=rid,
            actor=h.actor(sess),
            detail={"section": "contact", "max_attempts": body["max_attempts"], "min_days": body["min_days"]},
        )
        return RedirectResponse(f"/studies/{rid}/setup?saved=contact#contact", status_code=303)

    @app.post("/studies/{rs}/setup/log")
    async def save_log(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        need_edit(request, sess, str(form.get("csrf") or ""))
        reasons = tuple(r for r in ALL_REASONS if r in form.getlist("reasons"))
        prefix = str(form.get("screening_prefix") or "").strip()[:16]
        try:
            first = max(1, min(999999, int(str(form.get("first_no") or "1"))))
        except ValueError:
            first = 1
        if not reasons:
            return setup_page(
                request, sess, rid, err={"code": "STUDY-FIELD", "msg": "at least one reason", "fields": ""}
            )
        conf = s28.load(bk, store, rid, defaults(rid))
        row = s28.remote(bk, rid) or {}
        s = StudySettings(conf.study_type, conf.cohort_kind, reasons, prefix, first)
        return save_settings(request, sess, rid, s, {"consent_scope": row.get("consent_scope"),
                             "introduce_rule": row.get("introduce_rule")}, "log")  # fmt: skip

    # ------------------------------------------------------------------ D-146 (review J-26): who to screen
    @app.post("/studies/{rs}/setup/scope")
    def save_screen_scope(
        request: Request, rs: str, csrf: str = Form(""), mode: str = Form(""), practitioners: str = Form("")
    ) -> Response:
        """The study's screening scope: the whole hospital (the owner's aim) or some doctors' patients. A SCREEN of
        the study uses it unless the request names ``pract=``."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_edit(request, sess, csrf)
        ids = [p for p in re.split(r"[\s,、，]+", practitioners.strip()) if p][:200]
        if mode not in ("hospital", "practitioners"):
            raise h.problem(400, "request.refused", reason="choose the whole hospital or some doctors")
        if mode == "practitioners" and (not ids or not all(_PRACT.match(p) for p in ids)):
            raise h.problem(400, "request.refused", reason="practitioner ids are letters and digits, comma separated")
        try:
            body = {"mode": mode, "practitioners": ids if mode == "practitioners" else [], "by": h.actor(sess)}
            s28.call(bk, "PUT", f"/studies/{rid}/screen-scope", body)
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess),
                  detail={"section": "screen_scope", "mode": mode, "practitioners": len(ids)})  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/setup?saved=scope#who", status_code=303)

    # ------------------------------------------------------------------ D-133: the whole set-up in one form
    @app.post("/studies/{rs}/setup")
    async def save_all(request: Request, rs: str) -> Response:
        """One form, one Save (review F-04: saving one section used to discard what was typed in the others).
        ``action=read`` reads the REDCap project's fields for the pickers and shows the page again with everything
        typed so far kept; nothing is saved. ``action=save`` saves the study, the numbering and, when a REDCap key
        and project are chosen, the link (checked against the data dictionary)."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        need_edit(request, sess, str(form.get("csrf") or ""))
        study_type = str(form.get("study_type") or "trial")
        cohort_kind = str(form.get("cohort_kind") or "enrolled")
        if study_type not in STUDY_TYPES or cohort_kind not in COHORT_KINDS:
            raise h.problem(400, "request.refused", reason="unknown study type or cohort kind")
        scope_in = str(form.get("consent_scope") or "")
        scope = scope_in if scope_in in CONSENT_SCOPES else None
        reasons = tuple(r for r in ALL_REASONS if r in form.getlist("reasons"))
        prefix = str(form.get("screening_prefix") or "").strip()[:16]
        try:
            first = max(1, min(999999, int(str(form.get("first_no") or "1"))))
        except ValueError:
            first = 1
        conf = StudySettings(study_type, cohort_kind, reasons, prefix, first)
        body = link_from_form(rid, form)
        keep: dict[str, Any] = {"form_conf": conf, "lk_form": body, "scope_form": scope or ""}
        if str(form.get("action") or "") == "read":
            ref = body["token_ref"]
            if not _REF.match(ref):
                return setup_page(request, sess, rid, err={"code": "RC-TOKEN", "msg": "", "fields": ""}, **keep)
            try:
                d = s28.call(bk, "GET", f"/redcap/connections/{ref}/dictionary")
            except (Problem, Unavailable) as exc:
                return setup_page(request, sess, rid, err=err_of(exc), **keep)
            if d.get("project_id") and not body["project_id"]:
                body["project_id"] = int(d["project_id"])
            return setup_page(request, sess, rid, rc_dict=d, **keep)
        if not reasons:
            return setup_page(
                request, sess, rid, err={"code": "STUDY-FIELD", "msg": "at least one reason", "fields": ""}, **keep
            )
        row = s28.remote(bk, rid) or {}
        try:
            s28.save(
                bk, rid, conf, h.actor(sess), {"consent_scope": scope, "introduce_rule": row.get("introduce_rule")}
            )
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc), **keep)
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail={"section": "all"})
        cur = (get_or_none(f"/studies/{rid}/redcap-link") or {}).get("link") or {}
        same = bool(cur) and all(str(cur.get(k) or "") == str(v or "") for k, v in body.items() if k != "ruleset")
        if body["token_ref"] and body["project_id"] and not same:  # a changed link is checked against REDCap
            try:
                s28.call(bk, "PUT", f"/studies/{rid}/redcap-link", {"link": body, "by": h.actor(sess)})
            except (Problem, Unavailable) as exc:  # the study and numbering are saved; the link is shown to fix
                return setup_page(request, sess, rid, err=err_of(exc), saved="study", **keep)
            au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail={"section": "redcap"})
        return RedirectResponse(f"/studies/{rid}/setup?saved=all", status_code=303)

    def link_from_form(rid: str, form: Any) -> dict[str, Any]:
        body: dict[str, Any] = {k: str(form.get(k) or "").strip() for k in LINK_TEXT}
        body["ruleset"] = rid
        body["link_mode"] = "tb_screening_no"
        body["token_ref"] = str(form.get("token_ref") or "").strip()
        try:
            body["project_id"] = int(str(form.get("project_id") or "0").strip() or 0)
        except ValueError:
            body["project_id"] = 0
        body["screenfail_choice_map"] = parse_map(str(form.get("screenfail_choice_map") or ""))
        body["link_field"] = body["link_field"] or "tb_screening_no"
        body["enrol_value"] = body["enrol_value"] or "1"
        body["withdraw_value"] = body["withdraw_value"] or "1"
        body["write_mode"] = body["write_mode"] if body["write_mode"] in ("off", "existing", "create") else "off"
        body["write_form"] = body["write_form"] or "trialbox_screening"
        return body

    @app.post("/studies/{rs}/setup/redcap")
    async def save_link(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        need_edit(request, sess, str(form.get("csrf") or ""))
        body = link_from_form(rid, form)
        try:
            s28.call(bk, "PUT", f"/studies/{rid}/redcap-link", {"link": body, "by": h.actor(sess)})
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc), lk_form=body)
        au.append("console.study_setup", ruleset=rid, actor=h.actor(sess), detail={"section": "redcap"})
        return RedirectResponse(f"/studies/{rid}/setup?saved=redcap#redcap", status_code=303)

    @app.post("/studies/{rs}/setup/redcap/test")
    def test_link(request: Request, rs: str, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_request:
            raise h.problem(403, "forbidden")
        try:
            out = s28.call(bk, "POST", f"/studies/{rid}/redcap-link/test", {"screening": screening_map(store, rid)})
        except (Problem, Unavailable) as exc:
            return setup_page(request, sess, rid, err=err_of(exc))
        nos = {pid: no for no, pid in screening_map(store, rid).items()}
        for j in out.get("sample") or []:
            j["no"] = nos.get(j.get("pid") or "", j.get("link_value"))
        return setup_page(request, sess, rid, test=out)

    @app.post("/studies/{rs}/redcap-read")
    def run_now(request: Request, rs: str, csrf: str = Form(""), back: str = Form("setup")) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_request:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        target = f"/studies/{rid}/screening-log" if back == "log" else f"/studies/{rid}/setup"
        try:
            out = read_now(h, rid, h.actor(sess))
        except (Problem, Unavailable) as exc:
            e = err_of(exc)
            return RedirectResponse(f"{target}?rc_err={quote(e['code'])}#redcap", status_code=303)
        au.append("console.redcap_read", ruleset=rid, actor=h.actor(sess), detail={"changes": len(out["changes"])})
        return RedirectResponse(f"{target}?read={len(out['changes'])}#redcap", status_code=303)

    # ------------------------------------------------------------------ D-386: study state and identifiers
    def state_page(request: Request, sess: Session, rid: str, status: int = 200, ident: StudyIdentity | None = None,
                   irbt: IrbText | None = None, **extra: Any) -> Response:  # fmt: skip
        cur = store.study_state(rid)
        return h.page(
            request,
            "study_state.html",
            sess,
            status=status,
            rs=rid,
            cur=cur,
            moves=STATE_MOVES.get(cur.state, ()),
            states=STUDY_STATES,
            history=list(reversed(store.state_history(rid))),
            ident=ident or store.study_identity(rid),
            registries=REGISTRIES,
            editable=may_change_state(h, sess.user, rid),
            irbt=irbt or store.irb_text(rid),
            irbt_history=list(reversed(store.irb_text_history(rid))),
            irbt_edit=may_record_irb_text(h, sess.user, rid),
            irb_gate=h.irb_gate,
            sentence_en=IRB_SENTENCE_EN,
            **{
                "saved": request.query_params.get("saved", ""),
                "err": None,
                "bad": [],
                "irbt_err": None,
                "irbt_bad": [],
                **extra,
            },
        )

    def need_state_edit(request: Request, sess: Session, rid: str, csrf: str) -> None:
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not may_change_state(h, sess.user, rid):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    def sae_type_missing(rid: str) -> str:
        """T-629 (FIT-U06, D-415): why the study may not open yet, or "". A study that reports serious adverse events
        opens only with its type for SAE reporting chosen and confirmed on the set-up page, since the type selects
        the reporting table (who is told, by when). Without the study store there is no SAE register to gate."""
        if not s28.has_api(bk) or s28.load(bk, store, rid, defaults(rid)).study_type not in SAE_STUDY_TYPES:
            return ""
        try:
            row = s28.call(bk, "GET", f"/studies/{rid}/sae-rule")
        except (Problem, Unavailable):
            return "sstate.sae_unknown"
        problems = set((row.get("rules") or {}).get("problems") or ())
        if not row.get("rule_set") or problems & set(lc.RULE_ALERTS):
            return "sstate.sae_type"
        return ""

    @app.get("/studies/{rs}/state")
    def study_state(request: Request, rs: str) -> Response:
        sess = h.need(request)
        return state_page(request, sess, study_or_404(sess, rs))

    @app.post("/studies/{rs}/state")
    def change_state(
        request: Request, rs: str, csrf: str = Form(""), state: str = Form(""), reason: str = Form("")
    ) -> Response:
        """Move the study to ``state`` (D-386). Pausing or closing takes a reason. The audit event is written in the
        store's transaction, so a change is never kept without it."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_state_edit(request, sess, rid, csrf)
        why = " ".join(reason.split())[:200]
        cur = store.study_state(rid)
        if state not in STATE_MOVES.get(cur.state, ()):
            return state_page(request, sess, rid, status=400, err="sstate.bad_move")
        if state in REASON_STATES and not why:
            return state_page(request, sess, rid, status=400, err="sstate.need_reason")
        if state == "open" and (refused := sae_type_missing(rid)):
            return state_page(request, sess, rid, status=409, err=refused)

        def audit(new: StudyState) -> None:
            au.append("console.study_state", ruleset=rid, actor=h.actor(sess),
                      detail={"state": new.state, "prev": new.prev, "reason": why})  # fmt: skip

        try:
            store.set_study_state(rid, state, why, h.actor(sess), h.clock().isoformat(), before_commit=audit)
        except ValueError:  # another person changed it first
            return state_page(request, sess, rid, status=409, err="sstate.bad_move")
        return RedirectResponse(f"/studies/{rid}/state?saved=state", status_code=303)

    @app.post("/studies/{rs}/identity")
    async def save_identity(request: Request, rs: str) -> Response:
        """The study's sponsor, protocol number, SIV date and registry ids (D-386, LIFE-013). A malformed field is
        shown again with what was typed; nothing is saved."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        need_state_edit(request, sess, rid, str(form.get("csrf") or ""))

        def text(name: str, n: int) -> str:
            return " ".join(str(form.get(name) or "").split())[:n]

        ident = StudyIdentity(
            sponsor=text("sponsor", 200),
            protocol_no=text("protocol_no", 60),
            siv_date=text("siv_date", 20),
            registry_ids={r: text(f"registry_{r}", 60) for r in REGISTRIES if text(f"registry_{r}", 60)},
        )
        bad = ident.problems()
        if bad:
            return state_page(request, sess, rid, status=400, ident=ident, bad=bad, err="sid.bad")
        saved = store.save_study_identity(rid, ident, h.actor(sess), h.clock().isoformat())
        au.append("console.study_identity", ruleset=rid, actor=h.actor(sess),
                  detail={"fields": [k for k, _v in saved.lines()], **saved.registry_ids})  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/state?saved=identity", status_code=303)

    @app.post("/studies/{rs}/irb-text")
    async def record_irb_text(request: Request, rs: str) -> Response:
        """D-395 (RSK-42): the PI records whether the study's approved IRB text covers the cross-department identified
        view, with the approval number of that text (required to cover), its version and date. Taking it back needs a
        note. The audit event is written in the store's transaction. A wrong field is shown again; nothing is kept."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        if not may_record_irb_text(h, sess.user, rid):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

        def text(name: str, n: int) -> str:
            return " ".join(str(form.get(name) or "").split())[:n]

        rec = IrbText(covers=str(form.get("covers") or "") == "1", approval_ref=text("approval_ref", 80),
                      text_version=text("text_version", 60), approved_on=text("approved_on", 20),
                      note=text("note", 260))  # fmt: skip
        bad = rec.problems(h.today())
        if bad:
            return state_page(request, sess, rid, status=400, irbt=rec, irbt_bad=bad, irbt_err="irbt.bad")

        def audit(new: IrbText) -> None:
            au.append("console.irb_text", ruleset=rid, actor=h.actor(sess),
                      detail={"covers": new.covers, "sentence": new.sentence, "approval_ref": new.approval_ref,
                              "text_version": new.text_version, "approved_on": new.approved_on or None,
                              "note": new.note})  # fmt: skip

        store.record_irb_text(rid, rec, h.actor(sess), h.clock().isoformat(), h.today(), before_commit=audit)
        return RedirectResponse(f"/studies/{rid}/state?saved=irb_text#irb-text", status_code=303)

    # ------------------------------------------------------------------ S36
    def need_admin_view(sess: Session) -> None:
        """S36 holds the REDCap addresses and key names: administrators only (D-146, review J-05)."""
        if not sess.user.is_admin:
            au.append("console.denied", actor=h.actor(sess), detail={"action": "/admin/redcap"})
            raise h.problem(403, "forbidden")

    def s36_page(request: Request, sess: Session, **extra: Any) -> Response:
        conns = get_or_none("/redcap/connections")
        return h.page(
            request,
            "redcap.html",
            sess,
            conns=(conns or {}).get("connections") or [],
            api=conns is not None,
            **{"saved": request.query_params.get("saved", ""), "err": None, "tested": None, **extra},
        )

    @app.get("/admin/redcap")
    def s36(request: Request) -> Response:
        sess = h.need(request)
        need_admin_view(sess)
        return s36_page(request, sess)

    @app.post("/admin/redcap")
    def s36_save(
        request: Request,
        csrf: str = Form(""),
        token_ref: str = Form("main"),
        url: str = Form(""),
        token: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        ref = token_ref.strip().lower()
        if not _REF.match(ref):
            return s36_page(
                request, sess, err={"code": "RC-FIELD", "msg": "token name: a-z, 0-9, - and _", "fields": ""}
            )
        body = {"url": url.strip(), "token": token.strip() or None, "by": h.actor(sess)}
        try:
            s28.call(bk, "PUT", f"/redcap/connections/{ref}", body)
        except (Problem, Unavailable) as exc:
            return s36_page(request, sess, err=err_of(exc))
        au.append("console.redcap_connection", actor=h.actor(sess), detail={"token_ref": ref})
        return RedirectResponse("/admin/redcap?saved=1", status_code=303)

    @app.post("/admin/redcap/{ref}/test")
    def s36_test(request: Request, ref: str, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            raise h.problem(403, "forbidden")
        if not _REF.match(ref):
            raise h.problem(404, "notfound")
        try:
            out = s28.call(bk, "POST", f"/redcap/connections/{ref}/test")
        except (Problem, Unavailable) as exc:
            return s36_page(request, sess, err=err_of(exc), tested=ref)
        return s36_page(request, sess, tested=ref, result=out)
