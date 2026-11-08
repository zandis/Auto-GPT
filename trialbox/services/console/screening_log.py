"""Logs and lists of build step 2 (D-108).

* **Screening log** (ICH E6(R3) §2.8 / Appendix C "subject screening log", pseudonymous): one line per patient the
  study approached, by screening number (FR-STUDY-08), with the PI's mark, the contact outcomes and the registry
  status. The chart number stays off the log; the site's existing registry export resolves it on the box.
* **Cohort list** for a registry or observational study (RA-BIO, RA-COH, GOUT-COH): the members found by the latest
  run who were not listed before. There is no contact step and no PI mark: a cohort study counts and follows members,
  it does not approach them for a trial (FR-SCR-12).
* **Research office counts** (FR-REP-09): per study and calendar year, how many patients were listed, reviewed by
  the PI, approached, contacted, consented, enrolled, screen-failed and declined, small cells suppressed (k).
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

from fastapi import FastAPI, Request, Response
from tb_contracts import Job

from console import s28
from console import studies as st
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.studies import known_study
from console.timefmt import local_date, site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SMALL_CELL = 5  # FR-REP-09: the site's small-cell threshold (k) for counts that leave the study team
COUNT_KEYS = ("listed", "reviewed", "approached", "contacted", "consented", "enrolled", "screen_fail", "declined")


_RC_NOTE = re.compile(r"^REDCap record (\S+)(?: \((.*)\))?$")


def _rc_note(reason: str) -> tuple[str, str] | None:
    """The read-back writes a language-neutral note "REDCap record <id> (<reason>)" into the registry (D-109); the
    page shows it in the reader's language (step 4, FR-I18N-01)."""
    m = _RC_NOTE.match(reason)
    return (m.group(1), m.group(2) or "") if m else None


def suppress(n: int, k: int) -> int | str:
    return f"<{k}" if 0 < n < k else n


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store
    tz = site_zone(bk)

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        return rid

    def load(job: Job | None, prefix: str) -> dict[str, Any] | None:
        out = st.output(job, prefix, ".json")
        if out is None:
            return None
        try:
            data = json.loads(bk.get_object(out.minio_key))
        except (KeyError, ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def registry_rows(rs: str) -> dict[str, Any]:
        try:
            return {e.pid: e for e in bk.registry_rows(rs)}
        except Exception:
            return {}

    def rc_records(rs: str) -> dict[str, dict[str, Any]]:
        """What the last REDCap read-back found per pid: record id, sponsor subject number (D-109)."""
        if not s28.has_api(bk):
            return {}
        try:
            rows = s28.call(bk, "GET", f"/studies/{rs}/redcap-records")
        except (Problem, Unavailable):
            return {}
        return {str(r["pid"]): r for r in rows or [] if r.get("pid")}

    def rc_link(rs: str) -> dict[str, Any] | None:
        if not s28.has_api(bk):
            return None
        try:
            out = s28.call(bk, "GET", f"/studies/{rs}/redcap-link")
        except (Problem, Unavailable):
            return None
        return out if isinstance(out, dict) else None

    def log_rows(rs: str) -> list[dict[str, Any]]:
        reg = registry_rows(rs)
        rc = rc_records(rs)
        marks: dict[str, list[Any]] = {}
        for m in store.all_marks(rs):
            marks.setdefault(m.pid, []).append(m)
        outs: dict[str, list[Any]] = {}
        for o in store.outcomes(rs):
            outs.setdefault(o.pid, []).append(o)
        seen = store.first_seen(rs)
        rows = []
        for pid, no, at in store.screening_rows(rs):
            e = reg.get(pid)
            mk = [m for m in marks.get(pid, []) if m.mark != "withdrawn"]
            oc = outs.get(pid, [])
            rows.append(
                {
                    "no": no,
                    "pid": pid,
                    "short": pid[:8],
                    "listed": local_date((seen.get(pid) or ("", ""))[1], tz),
                    "assigned": local_date(at, tz),
                    "mark": mk[-1] if mk else None,
                    "outcome": oc[-1] if oc else None,
                    "attempts": len(oc),
                    "status": e.status if e else "candidate",
                    "reason": (e.reason if e else "") or "",
                    "reason_rc": _rc_note((e.reason if e else "") or ""),
                    "updated": local_date(e.updated_at.isoformat(), tz) if e else "",
                    "record_id": (rc.get(pid) or {}).get("record_id") or "",
                    "subject_no": (rc.get(pid) or {}).get("subject_no") or "",
                }
            )
        return rows

    @app.get("/studies/{rs}/screening-log")
    def screening_log(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:
            raise h.problem(403, "forbidden")
        link = rc_link(rid)
        reads = (link or {}).get("reads") or []
        return h.page(
            request,
            "screening_log.html",
            sess,
            rs=rid,
            rows=log_rows(rid),
            link=link,
            last=reads[0] if reads else None,
            back="log",
        )

    @app.get("/studies/{rs}/screening-log.xlsx")
    def screening_log_xlsx(request: Request, rs: str) -> Response:
        from openpyxl import Workbook

        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not sess.user.can_request:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        wb = Workbook()
        ws: Any = wb.active
        ws.title = "screening log"
        ws.append(
            [
                "screening_no",
                "pseudonym",
                "first_listed",
                "number_given",
                "pi_mark",
                "pi_mark_reason",
                "pi_mark_date",
                "last_contact_outcome",
                "contact_attempts",
                "status",
                "reason",
                "status_date",
                "redcap_record_id",
                "subject_no",
            ]
        )
        for r in log_rows(rid):
            mk, oc = r["mark"], r["outcome"]
            ws.append(
                [
                    r["no"],
                    r["pid"],
                    r["listed"],
                    r["assigned"],
                    mk.mark if mk else "",
                    (mk.reason or "") if mk else "",
                    local_date(mk.at, tz) if mk else "",
                    oc.outcome if oc else "",
                    r["attempts"],
                    r["status"],
                    r["reason"],
                    r["updated"],
                    r["record_id"],
                    r["subject_no"],
                ]
            )
        about = wb.create_sheet("about")
        about.append(["study", rid])
        about.append(["made", h.clock().isoformat(timespec="seconds")])
        about.append(["note", "Pseudonymous ICH E6(R3) screening log. Chart numbers are not in this file."])
        buf = io.BytesIO()
        wb.save(buf)
        au.append("console.export", ruleset=rid, actor=h.actor(sess), detail={"filename": "screening_log.xlsx"})
        return Response(
            buf.getvalue(),
            media_type=XLSX,
            headers={"Content-Disposition": f'attachment; filename="screening_log_{rid}.xlsx"'},
        )

    @app.get("/studies/{rs}/cohort")
    def cohort(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:
            raise h.problem(403, "forbidden")
        info = next((r for r in bk.rulesets() if r.id == rid), None)
        kind = info.kind if info else ""
        conf = s28.load(bk, store, rid, st.study_defaults(rid, kind))
        jobs = [
            j
            for j in bk.list_jobs(limit=500)
            if j.ruleset == rid and j.type in ("SCREEN", "MICROBATCH") and j.state == "done"
        ]
        jobs.sort(key=lambda j: j.updated_at or j.received_at)
        job = jobs[-1] if jobs else None
        cl = load(job, "candidate_list_")
        members = [str(r.get("pid")) for r in (cl or {}).get("rows") or [] if r.get("tier") == "high"]
        rows: list[dict[str, Any]] = []
        dropped = 0
        if job is not None:
            seen = store.seen(rid, members, job.job_id, (job.updated_at or job.received_at).isoformat())
            by_pid = {str(r.get("pid")): r for r in (cl or {}).get("rows") or []}
            for pid in members:
                if seen.get(pid) != job.job_id:
                    continue  # FR-SCR-12: new members only; known members stay in the registry, not on the list
                r = by_pid[pid]
                rows.append(
                    {
                        "pid": pid,
                        "short": pid[:8],
                        "visit": (r.get("next_appointment") or "")[:16].replace("T", " "),
                        "department": r.get("department") or "",
                        "met": sum(1 for v in r.get("criteria") or [] if v.get("verdict") == "pass"),
                        "total": len(r.get("criteria") or []),
                    }
                )
            if conf.cohort_kind == "dynamic" and len(jobs) > 1:
                prev = load(jobs[-2], "candidate_list_")
                before = {str(r.get("pid")) for r in (prev or {}).get("rows") or [] if r.get("tier") == "high"}
                dropped = len(before - set(members))
        return h.page(
            request,
            "cohort.html",
            sess,
            rs=rid,
            job=job,
            rows=rows,
            n_members=len(members),
            dropped=dropped,
            conf=conf,
        )

    # ------------------------------------------------------------------ FR-REP-09
    def office_counts(year: int, k: int) -> list[dict[str, Any]]:
        out = []
        for info in bk.rulesets():
            if info.status != "approved":
                continue
            rid = info.id
            y = str(year)
            seen = store.first_seen(rid)
            marks = store.all_marks(rid)
            reg = registry_rows(rid)
            nos = store.screening_rows(rid)
            counts = {
                "listed": sum(1 for _j, a in seen.values() if a.startswith(y)),
                "reviewed": len({m.pid for m in marks if m.at.startswith(y) and m.mark != "withdrawn"}),
                "approached": sum(1 for _p, _n, a in nos if a.startswith(y)),
            }
            rank = {"contacted": 1, "consented": 2, "enrolled": 3}
            yr = [e for e in reg.values() if e.updated_at.year == year]
            counts["contacted"] = sum(1 for e in yr if rank.get(e.status, 0) >= 1 or e.status in ("screen_fail",))
            counts["consented"] = sum(1 for e in yr if rank.get(e.status, 0) >= 2)
            counts["enrolled"] = sum(1 for e in yr if e.status == "enrolled")
            counts["screen_fail"] = sum(1 for e in yr if e.status == "screen_fail")
            counts["declined"] = sum(1 for e in yr if e.status == "declined")
            if not any(counts.values()):
                continue
            out.append({"study": rid, "kind": info.kind or "trial", **{c: suppress(counts[c], k) for c in COUNT_KEYS}})
        return out

    def office_allowed(sess: Session) -> bool:
        return sess.user.role in ("admin", "viewer", "coordinator")  # the CRO never sees the site's own totals

    @app.get("/reports/research-office")
    def research_office(request: Request, year: int = 0) -> Response:
        sess = h.need(request)
        if not office_allowed(sess):
            raise h.problem(403, "forbidden")
        y = year or h.clock().year
        k = SMALL_CELL
        return h.page(request, "research_office.html", sess, year=y, rows=office_counts(y, k), keys=COUNT_KEYS, small=k)

    @app.get("/reports/research-office.xlsx")
    def research_office_xlsx(request: Request, year: int = 0) -> Response:
        from openpyxl import Workbook

        sess = h.need(request)
        if not office_allowed(sess):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        y = year or h.clock().year
        k = SMALL_CELL
        wb = Workbook()
        ws: Any = wb.active
        ws.title = f"counts {y}"
        ws.append(["study", "kind", *COUNT_KEYS])
        for r in office_counts(y, k):
            ws.append([r["study"], r["kind"], *[r[c] for c in COUNT_KEYS]])
        about = wb.create_sheet("about")
        about.append(["year", y])
        about.append(["small cells", f"counts between 1 and {k - 1} are shown as <{k}"])
        about.append(["made", h.clock().isoformat(timespec="seconds")])
        buf = io.BytesIO()
        wb.save(buf)
        name = f"research_office_{y}.xlsx"
        au.append("console.export", actor=h.actor(sess), detail={"filename": name})
        return Response(
            buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )
