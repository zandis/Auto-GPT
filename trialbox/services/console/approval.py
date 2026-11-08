"""S20 criteria approval (D-108, FR-FEAS-12, FR-AUTH-13): one page, one **Approve all**, for the investigator only.

* Every criterion is one row: what it says, how the box checks it (filter / model on notes / a person) and, folded
  under the row, the codes it uses.
* Amber rows need the investigator's eyes (compiler flags, CQL and SQL not fully equivalent, left to a person, new or
  changed since the approved version). Opening an amber row is recorded on the server (the console has no script);
  **Approve all** is offered once every amber row was opened by the investigator who approves.
* A coordinator (or administrator) prepares the approval: ticking a row's codes as checked is its own audit event
  (``console.code_tick``) and is shown to the investigator; it never approves.
* A re-approval shows **Changes since vN**: criteria added, with new text or check class, and removed.
* **Approve all** sends ``APPROVE <study> version=<v>`` with the review workbook the compiler wrote, exactly what a
  reply to the review mail does; the orchestrator still checks the approver against the site's reviewers.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from tb_contracts import Job

from console import studies as st
from console.auth import Session
from console.home import Helpers

_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_CRIT = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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

    def context(sess: Session, job: Job, book: Any) -> dict[str, Any]:
        rows = review_rows(bk.get_object(book.minio_key))
        fn = getattr(bk, "criteria", None)
        approved = fn(job.ruleset) if fn else []
        prev = next((r.version for r in bk.rulesets() if r.id == job.ruleset and r.status == "approved"), None)
        diff = st.diff_since(rows, approved) if approved else {"added": [], "text": [], "class": [], "removed": []}
        changed = set(diff["added"]) | set(diff["text"]) | set(diff["class"])
        for r in rows:
            r["amber"] = st.amber(r, changed)
        ambers = [str(r["id"]) for r in rows if r["amber"]]
        opened = store.opened_rows(job.job_id, sess.user.username)
        old = {str(a["id"]): a for a in approved}
        return {
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
            "split": {c: sum(1 for r in rows if r.get("class") == c) for c in ("structured", "note", "mixed", "human")},
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
        if not sess.user.can_request:
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

    @app.post("/pilot/jobs/{job_id}/approve")
    def approve(request: Request, job_id: str, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_approve:  # FR-AUTH-13: administrators and coordinators never approve
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        job, book = waiting_job(sess, job_id)
        ctx = context(sess, job, book)
        if ctx["missing"]:
            raise h.problem(
                409, "request.refused", reason="open every amber row first: " + ", ".join(ctx["missing"][:5])
            )
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
            },
        )
        data = bk.get_object(book.minio_key)
        new = submit(sess, f"APPROVE {job.ruleset} version={job.ruleset_version}", [("review.xlsx", data, XLSX)])
        return RedirectResponse(f"/pilot/jobs/{new.job_id}", status_code=303)
