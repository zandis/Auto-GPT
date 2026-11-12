"""S20 criteria approval (D-108, FR-FEAS-12, FR-AUTH-13): one page, one **Approve all**, for the investigator only.

* Every criterion is one row: what it says, how the box checks it (filter / model on notes / a person) and, folded
  under the row, the codes it uses.
* Amber rows need the investigator's eyes (compiler flags, CQL and SQL not fully equivalent, left to a person, new or
  changed since the approved version). Opening an amber row is recorded on the server (the console has no script);
  **Approve all** is offered once every amber row was opened by the investigator who approves.
* Only the investigator ticks the criteria and approves them (owner decision 2026-11-09, D-146, review J-27): a tick
  is its own audit event (``console.code_tick``); the page says who may. A coordinator (or administrator) prepares:
  reads the draft and gives each criterion the site's own label.
* A re-approval shows **Changes since vN**: criteria added, with new text or check class, and removed.
* **Approval needed** (D-318): the approved version pins its judge prompt and terminology release; when the box has a
  newer prompt or another release, the page says so and that SCREEN keeps the approved prompt until this approval.
* **Planted instruction** (T-606, D-359): a criterion whose text the guard's screen flags as written to a model
  ("ignore the above criteria", a note to the AI) is amber with its own warning: the investigator opens it and
  checks it against the protocol before approval.
* **Approve all** sends ``APPROVE <study> version=<v>`` with the review workbook the compiler wrote, exactly what a
  reply to the review mail does; the orchestrator checks the approver's role (D-146).
* **Amendment record** (D-364, LIFE-009): the investigator may give the day the version takes effect and the IRB
  approval number and date of the protocol version. They travel on the APPROVE line (``effective=``, ``irb=``,
  ``irbdate=``) into the approved manifest. The IRB fields are a record, not a gate (D-311); the box screens on the
  version before until the effective day.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from guard.injection import screen
from tb_contracts import Job

from console import ruleset_labels
from console import studies as st
from console.auth import Session
from console.home import Helpers
from console.i18n import translate

_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_CRIT = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_IRB = re.compile(r"^[A-Za-z0-9,.:\-]{1,32}$")  # the APPROVE line's value grammar (tb_common.subject)


def amendment_line(effective_from: str, irb_reference: str, irb_approved_on: str, today: date) -> str:
    """D-364: the APPROVE options of the amendment record, checked the way the compiler will check them; a plain
    refusal (``ValueError``) names the field. Empty fields add nothing."""
    out: list[str] = []
    for key, text in (("effective", effective_from), ("irbdate", irb_approved_on)):
        text = text.strip()
        if not text:
            continue
        try:
            day = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"amend.bad_date.{key}") from exc
        if key == "effective" and day < today:
            raise ValueError("amend.past_effective")
        if key == "irbdate" and day > today:
            raise ValueError("amend.future_irb")
        out.append(f"{key}={day.isoformat()}")
    irb = irb_reference.strip()
    if irb:
        if not _IRB.match(irb):
            raise ValueError("amend.bad_irb")
        out.append(f"irb={irb}")
    return " ".join(out)


def review_rows(data: bytes) -> list[dict[str, Any]]:
    """Rows of the compiler's review workbook (sheet ``review``) as dicts keyed by its header."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if "review" not in wb.sheetnames:
        return []
    rows = list(wb["review"].iter_rows(values_only=True))
    if not rows:
        return []
    head = [str(c or "") for c in rows[0]]
    out = []
    for r in rows[1:]:
        d: dict[str, Any] = dict(zip(head, r, strict=False))
        if d.get("id"):
            d["codes_list"] = [
                c.strip() for part in str(d.get("codes") or "").split("\n") for c in part.split("; ") if c.strip()
            ]
            out.append(d)
    return out


def register(app: FastAPI, h: Helpers, submit: Callable[[Session, str, list[tuple[str, bytes, str]]], Job]) -> None:
    bk, au, store = h.bk, h.au, h.store

    def waiting_job(sess: Session, job_id: str) -> tuple[Job, Any]:
        if not _ULID.match(job_id):
            raise h.problem(404, "notfound")
        job = bk.get_job(job_id)
        if job is None or not job.ruleset or not sess.user.sees_study(job.ruleset):
            raise h.problem(404, "notfound")
        books = sorted(
            (o for o in job.outputs or [] if o.filename.startswith("review_") and o.filename.endswith(".xlsx")),
            key=lambda o: o.filename,
        )
        if job.state != "awaiting_approval" or not books or not job.ruleset_version:
            raise h.problem(409, "request.refused", reason="this job is not waiting for approval")
        return job, books[-1]

    def label_step(job: Job, rows: list[dict[str, Any]], lang: str) -> dict[str, Any]:
        """D-309 (T-507): on a Japanese or Chinese page every criterion needs a short label in that language before
        **Approve all**: the one the site saved (D-120) or, until then, the one the ruleset ships for exactly this
        text (``console.ruleset_labels``). ``unlabelled`` lists the rows still without one."""
        if lang == "en":
            return {"labels": {}, "shipped": set(), "unlabelled": []}
        rs = job.ruleset or ""
        mine = store.labels(rs, lang)
        texts = {str(r["id"]): str(r.get("text") or "") for r in rows}
        box_dir = getattr(getattr(getattr(bk, "cfg", None), "env", None), "rulesets_path", None)
        given = ruleset_labels.labels_for(rs, lang, texts, box_dir)
        labels = {**given, **mine}
        return {
            "labels": labels,
            "shipped": {c for c in given if c not in mine},
            "unlabelled": [str(r["id"]) for r in rows if not labels.get(str(r["id"]))],
        }

    def context(sess: Session, job: Job, book: Any) -> dict[str, Any]:
        rows = review_rows(bk.get_object(book.minio_key))
        fn = getattr(bk, "criteria", None)
        approved = fn(job.ruleset) if fn else []
        prev = next((r.version for r in bk.rulesets() if r.id == job.ruleset and r.status == "approved"), None)
        diff = st.diff_since(rows, approved) if approved else {"added": [], "text": [], "class": [], "removed": []}
        changed = set(diff["added"]) | set(diff["text"]) | set(diff["class"])
        for r in rows:
            r["amber"] = st.amber(r, changed)
            if screen(str(r.get("text") or "")).hit:  # T-606 (D-359): a criterion that reads as an order to a model
                r["amber"].append("instruction")
        ambers = [str(r["id"]) for r in rows if r["amber"]]
        opened = store.opened_rows(job.job_id, sess.user.username)
        old = {str(a["id"]): a for a in approved}
        pins = getattr(bk, "approval_state", None)  # D-318: why the approved version needs the investigator again
        return {
            "pin_state": pins(job.ruleset) if pins else None,
            "job": job,
            "rs": job.ruleset,
            "version": job.ruleset_version,
            "prev": prev if approved else None,
            "rows": rows,
            "diff": diff,
            "old": old,
            "ambers": ambers,
            "opened": opened,
            "missing": [a for a in ambers if a not in opened],
            "ticks": store.code_ticks(job.job_id),
            **label_step(job, rows, sess.lang),
            "split": {c: sum(1 for r in rows if r.get("class") == c) for c in ("structured", "note", "mixed", "human")},
            # D-147: a sub-investigator never approves; the study's PI does
            "approver": h.may_approve is None or h.may_approve(sess.user, (job.ruleset or "").upper()),
            # NEW-JRN-1 (D-540): nobody approves until the steward names the study's PI; the page says so
            "needs_pi": h.pi_missing is not None and (job.ruleset or "").upper() in h.pi_missing(sess.user),
        }

    @app.get("/pilot/jobs/{job_id}/approval")
    def approval(request: Request, job_id: str, open: str = "", done: str = "") -> Response:
        sess = h.need(request)
        if sess.user.aggregate_only:
            raise h.problem(403, "forbidden")
        seen = bk.get_job(job_id) if _ULID.match(job_id) else None
        if (
            seen is not None
            and seen.ruleset
            and sess.user.sees_study(seen.ruleset)
            and seen.state != "awaiting_approval"
        ):
            # an old link (the review mail, a bookmark) after the round is decided: show the job, not a refusal
            return RedirectResponse(f"/pilot/jobs/{job_id}", status_code=303)
        job, book = waiting_job(sess, job_id)
        ctx = context(sess, job, book)
        if open and _CRIT.match(open) and open in ctx["ambers"] and sess.user.can_approve and open not in ctx["opened"]:
            store.open_row(job.job_id, open, sess.user.username, h.clock().isoformat())
            au.append(
                "console.approval_open",
                job_id=job.job_id,
                ruleset=job.ruleset,
                actor=h.actor(sess),
                detail={
                    "action": open,
                    "reason": ",".join(next(r["amber"] for r in ctx["rows"] if r["id"] == open)),
                },
            )
            ctx = context(sess, job, book)
        return h.page(request, "approval.html", sess, open_row=open, done=done, **ctx)

    @app.post("/pilot/jobs/{job_id}/approval/tick")
    def tick(request: Request, job_id: str, csrf: str = Form(""), crit: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_approve:  # D-146 (review J-27): the investigator ticks, as only the investigator approves
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        job, book = waiting_job(sess, job_id)
        ids = {str(r["id"]) for r in review_rows(bk.get_object(book.minio_key))}
        if crit not in ids:
            raise h.problem(404, "notfound")
        store.tick_codes(job.job_id, crit, sess.user.username, h.clock().isoformat())
        au.append(
            "console.code_tick",
            job_id=job.job_id,
            ruleset=job.ruleset,
            actor=h.actor(sess),
            detail={"action": crit, "role": sess.user.role},
        )
        return RedirectResponse(f"/pilot/jobs/{job_id}/approval?done=tick#{crit}", status_code=303)

    @app.post("/pilot/jobs/{job_id}/approval/label")
    def label(
        request: Request, job_id: str, csrf: str = Form(""), crit: str = Form(""), text: str = Form("")
    ) -> Response:
        """D-120: a criterion's label in the site's language, given at approval. The study's own label and text stay
        on every page beside it; the label is the site's words, not the protocol's."""
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not (sess.user.can_request or sess.user.can_approve):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        if sess.lang == "en":
            raise h.problem(400, "request.refused", reason="choose the page language the label is in first")
        job, book = waiting_job(sess, job_id)
        ids = {str(r["id"]) for r in review_rows(bk.get_object(book.minio_key))}
        if crit not in ids:
            raise h.problem(404, "notfound")
        words = " ".join(text.split())[:80]
        store.save_label(job.ruleset or "", crit, sess.lang, words, sess.user.username, h.clock().isoformat())
        au.append(
            "console.criterion_label",
            job_id=job.job_id,
            ruleset=job.ruleset,
            actor=h.actor(sess),
            detail={"action": crit, "role": sess.user.role, "lang": sess.lang},
        )
        return RedirectResponse(f"/pilot/jobs/{job_id}/approval?done=label#{crit}", status_code=303)

    @app.post("/pilot/jobs/{job_id}/approve")
    def approve(
        request: Request,
        job_id: str,
        csrf: str = Form(""),
        confirm: str = Form(""),
        effective_from: str = Form(""),
        irb_reference: str = Form(""),
        irb_approved_on: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_approve:  # FR-AUTH-13: administrators and coordinators never approve
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        job, book = waiting_job(sess, job_id)
        if job.ruleset and h.may_approve is not None and not h.may_approve(sess.user, job.ruleset.upper()):
            # D-147: once the study's delegation log names its PI, only that PI approves (never a sub-investigator)
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        ctx = context(sess, job, book)
        if ctx["missing"]:
            raise h.problem(
                409, "request.refused", reason="open every amber row first: " + ", ".join(ctx["missing"][:5])
            )
        if ctx["unlabelled"]:  # D-309: the label step comes before approval
            raise h.problem(
                409,
                "request.refused",
                reason="give every criterion a short label first: " + ", ".join(ctx["unlabelled"][:5]),
            )
        try:
            amend = amendment_line(effective_from, irb_reference, irb_approved_on, h.today())
        except ValueError as exc:
            raise h.problem(400, "request.refused", reason=translate(sess.lang, str(exc))) from exc
        if confirm != "yes" and h.confirm is not None:  # P-10 (D-143): the consequence first
            text = translate(sess.lang, "confirm.approve_all", n=len(ctx["rows"]))
            if effective_from.strip():
                text += " " + translate(sess.lang, "amend.confirm_effective", day=effective_from.strip())
            fields = {
                "effective_from": effective_from,
                "irb_reference": irb_reference,
                "irb_approved_on": irb_approved_on,
            }
            return h.confirm(request, sess, text, request.url.path, fields, f"/pilot/jobs/{job.job_id}/approval")
        au.append(
            "console.approve_all",
            job_id=job.job_id,
            ruleset=job.ruleset,
            actor=h.actor(sess),
            detail={
                "action": f"{job.ruleset} v{job.ruleset_version}",
                "rows": len(ctx["rows"]),
                "amber": len(ctx["ambers"]),
                "ticked": len(ctx["ticks"]),
                "since": ctx["prev"] or "",
                "amendment": amend,
            },
        )
        data = bk.get_object(book.minio_key)
        line = f"APPROVE {job.ruleset} version={job.ruleset_version}" + (f" {amend}" if amend else "")
        new = submit(sess, line, [("review.xlsx", data, XLSX)])
        return RedirectResponse(f"/pilot/jobs/{new.job_id}", status_code=303)
