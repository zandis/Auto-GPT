"""Logs and lists of build step 2 (D-108).

* **Screening log** (ICH E6(R3) §2.8 / Appendix C "subject screening log", pseudonymous): one line per patient the
  study approached, by screening number (FR-STUDY-08), with the PI's mark, the contact outcomes and the registry
  status. The chart number stays off the log; the site's existing registry export resolves it on the box. D-387
  (LIFE-015, LIFE-016) adds the criteria version of the mark, the criterion not met on a screen failure with its
  version ("GZQO-EXC-06 (v3.0.0)"), the day of consent, the consent form version and the day of enrolment.
* **Pre-screen log** (D-387, LIFE-015): one pseudonymous line per investigator mark, approached or not, so a patient
  set aside or not approached is on a per-patient log too: first listed, the criteria version the mark was made on,
  the mark and its reason, a later mark or withdrawal, the screening number if one was given, the referral answer
  and the screening-log status and reason. No screening number is needed. Same page and XLSX as the screening log.
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

from datacore import sponsor
from datacore.lifecycle import failed_label
from fastapi import FastAPI, Request, Response
from tb_common import sheets
from tb_common.authz import permit
from tb_contracts import Job

from console import s28
from console import studies as st
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import translate
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


def criteria_choices(bk: Any, rid: str) -> tuple[str, list[str]]:
    """The criteria a "not eligible" screen failure can name (D-387, LIFE-016): the ids on the latest candidate list
    of the study and the criteria version it screened under. ``("", [])`` when no list has run."""
    try:
        job = st.latest_job(bk.list_jobs(limit=500), rid, ("SCREEN", "MICROBATCH"))
        out = st.output(job, "candidate_list_", ".json")
        data = json.loads(bk.get_object(out.minio_key)) if out is not None else None
    except (KeyError, ValueError, OSError, Unavailable):
        return "", []
    if not isinstance(data, dict):
        return "", []
    ids: list[str] = []
    for r in data.get("rows") or []:
        for v in r.get("criteria") or []:
            cid = str(v.get("id") or "")
            if cid and cid not in ids:
                ids.append(cid)
    version = str(data.get("version") or (job.ruleset_version if job is not None else "") or "")
    return version, ids


def prescreen_rows(marks: list[Any], numbers: dict[str, str], seen: dict[str, tuple[str, str]],
                   reg: dict[str, Any], refs: dict[str, Any], gone: set[str]) -> list[dict[str, Any]]:  # fmt: skip
    """The pre-screen log (D-387, LIFE-015): one row per investigator mark, oldest first. A withdrawal is not a mark
    of its own: it shows on the mark it took back (``later`` "withdrawn"); a newer mark shows as "replaced"."""
    rows: list[dict[str, Any]] = []
    by_pid: dict[str, list[dict[str, Any]]] = {}
    for m in marks:
        if m.pid in gone:
            continue
        mine = by_pid.setdefault(m.pid, [])
        if m.mark == "withdrawn":
            if mine and not mine[-1]["later"]:
                mine[-1]["later"] = "withdrawn"
            continue
        if mine and not mine[-1]["later"]:
            mine[-1]["later"] = "replaced"
        e = reg.get(m.pid)
        row = {
            "pid": m.pid,
            "short": m.pid[:8],
            "listed": (seen.get(m.pid) or ("", ""))[1],
            "version": m.version or "",
            "mark": m,
            # a "not now" mark's reason is the recheck date, a plan rather than something that happened: this log
            # records what happened (nothing after today, T-513), so the date stays on the patient page and week list
            "mark_reason": "" if m.mark == "not_now" else (m.reason or ""),
            "later": "",
            "no": numbers.get(m.pid, ""),
            "referral": refs.get(m.pid),
            "status": e.status if e else "",
            "reason": (e.reason if e else "") or "",
            "reason_rc": _rc_note((e.reason if e else "") or ""),  # DEMO-JA: in the reader's language, as above
        }
        mine.append(row)
        rows.append(row)
    return rows


def suppress(n: int, k: int) -> int | str:
    return f"<{k}" if 0 < n < k else n


def study_lines(store: Any, rid: str) -> list[list[str]]:
    """D-386 (LIFE-008, LIFE-013): the rows the log's "about" sheet prints for the study: its sponsor, protocol
    number, SIV date and registry ids (as entered, each checked against its registry's format when saved), the state
    now, and every state change with its date, who and why."""
    out = [[k, v] for k, v in store.study_identity(rid).lines()]
    cur = store.study_state(rid)
    out.append(["state", cur.state])
    for e in store.state_history(rid):
        out.append([f"state.{e.state}", e.at, e.by, e.reason])
    return out


#: NEW-UX-3: a column whose machine word a person reads in their language, by its catalogue prefix
WORDS = {"pi_mark": "mark.", "pi_mark_reason": "reason.", "last_contact_outcome": "outcome.",
         "status": "registry.status.", "referral_route": "team.route.", "referral_outcome": "team.state.",
         "referral_reason": "team.decline."}  # fmt: skip
#: a column that lists machine words (comma-separated): the IRB warnings an approach went ahead despite
LISTS = {"approach_irb_override": "team.irb.w."}


def _word(lang: str, prefix: str, code: str) -> str:
    key = prefix + code
    word = translate(lang, key)
    return word if word != key else code


def _width(text: str) -> int:
    """How wide a text prints: a CJK (wide or full-width) character is about two widths."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def printable(wb: Any, lang: str, table: list[list[Any]]) -> Any:
    """NEW-UX-3 (D-698, UX-003): the screening log as a person reads and prints it, put first in the workbook: the
    headings and the words of the reader's language, dates as dates, the header frozen and printed on every page,
    landscape and one page wide. The machine-readable sheets stay as they are, for the systems that read them."""
    from datetime import date

    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    keep = wb.active  # the machine sheet stays the one the workbook opens on (readers take the active sheet)
    ws = wb.create_sheet(translate(lang, "log.xlsx.sheet")[:31], 0)
    wb.active = wb.index(keep)
    heads = [translate(lang, "log.no" if c == "screening_no" else f"log.xlsx.col.{c}") for c in sponsor.LOG_COLUMNS]
    ws.append(heads)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for line in table:
        out: list[Any] = []
        for col, v in zip(sponsor.LOG_COLUMNS, line, strict=False):
            if col in WORDS and isinstance(v, str) and v:
                out.append(_word(lang, WORDS[col], v))
            elif col in LISTS and isinstance(v, str) and v:
                sep = ", " if lang == "en" else "、"
                out.append(sep.join(_word(lang, LISTS[col], w.strip()) for w in v.split(",") if w.strip()))
            elif col in sponsor.DATE_COLUMNS and isinstance(v, str) and len(v) >= 10:
                try:
                    out.append(date.fromisoformat(v[:10]))
                except ValueError:
                    out.append(v)
            else:
                out.append(v)
        ws.append(out)
    for i, head in enumerate(heads, 1):
        letter = get_column_letter(i)
        longest = max([_width(str(head))] + [_width(str(c.value or "")) for c in ws[letter][1:]])
        ws.column_dimensions[letter].width = min(max(longest + 2, 10), 40)
        for c in ws[letter][1:]:
            if isinstance(c.value, date):
                c.number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    ws.print_title_rows = "1:1"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws


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

    def life_detail(rs: str) -> dict[str, dict[str, Any]]:
        """Per screening number, the lifecycle's consent, enrolment and screen-failure detail (D-387)."""
        if not s28.has_api(bk):
            return {}
        try:
            out = s28.call(bk, "GET", f"/studies/{rs}/subjects")
        except (Problem, Unavailable):
            return {}
        return {str(x.get("record")): x for x in (out or {}).get("subjects") or [] if isinstance(x, dict)}

    def prescreen(rs: str) -> list[dict[str, Any]]:
        refs: dict[str, Any] = h.team.latest_referrals(rs) if h.team is not None else {}
        gone = h.gone()
        return prescreen_rows(store.all_marks(rs), store.screening_nos(rs), store.first_seen(rs), registry_rows(rs),
                              refs, set(gone))  # fmt: skip

    def log_rows(rs: str) -> list[dict[str, Any]]:
        reg = registry_rows(rs)
        rc = rc_records(rs)
        life = life_detail(rs)
        marks: dict[str, list[Any]] = {}
        for m in store.all_marks(rs):
            marks.setdefault(m.pid, []).append(m)
        outs: dict[str, list[Any]] = {}
        for o in store.outcomes(rs):
            outs.setdefault(o.pid, []).append(o)
        seen = store.first_seen(rs)
        # D-147: the referral route and outcome per row, Approach marked despite an IRB warning. NEW-LIFE-5 (D-762):
        # an opted-out patient with a screening number keeps the row (number, dates, status, the day of the
        # opt-out) without the pseudonym or the contact work; one never numbered is on no list (D-147, D-273)
        refs: dict[str, Any] = h.team.latest_referrals(rs) if h.team is not None else {}
        overrides: dict[str, tuple[str, list[str], str, str]] = {}
        for o in h.team.overrides(rs) if h.team is not None else []:
            overrides[o[0]] = o
        gone = h.opted_out_on()
        rows = []
        for pid, no, at in store.screening_rows(rs):
            e = reg.get(pid)
            mk = [m for m in marks.get(pid, []) if m.mark != "withdrawn"]
            oc = outs.get(pid, [])
            lf = life.get(no) or {}
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
                    "referral": refs.get(pid),
                    "override": overrides.get(pid),
                    "version": (mk[-1].version or "") if mk else "",
                    "failed": failed_label(str(lf.get("criterion") or ""), str(lf.get("criteria_version") or "")),
                    "consented": str(lf.get("consented") or ""),
                    "icf_version": str(lf.get("icf_version") or ""),
                    "enrolled": str(lf.get("enrolled") or ""),
                    "randomised": str(lf.get("randomised") or ""),  # D-407 (LIFE-020): in the sponsor's IRT
                    "gone": pid in gone,
                    "opted_out": gone.get(pid, ""),
                }
            )
            if pid in gone:  # what stays of the trial record: never who, nor the contact work
                rows[-1].update(pid="", short="", mark=None, outcome=None, attempts=0, referral=None, override=None,
                                version="")  # fmt: skip
        return rows

    @app.get("/studies/{rs}/screening-log")
    def screening_log(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        h.need_rows(sess, rid, request.url.path)  # D-273 (PV-3), ROLE-017: one question with the XLSX and /api/v1
        link = rc_link(rid)
        reads = (link or {}).get("reads") or []
        return h.page(
            request,
            "screening_log.html",
            sess,
            rs=rid,
            rows=log_rows(rid),
            pre=prescreen(rid),
            link=link,
            last=reads[0] if reads else None,
            back="log",
            sstate=store.study_state(rid),  # D-386: the study's state and identifiers above the log
            sident=store.study_identity(rid),
            sponsor_cols=current_layout(rid) is not None,  # T-302c: the link to the log in the sponsor's columns
        )

    def current_layout(rs: str) -> dict[str, Any] | None:
        """The study's sponsor layout in force (D-435) when it names the log's columns, else None."""
        cur = None
        if s28.has_api(bk):
            try:
                cur = (s28.call(bk, "GET", f"/studies/{rs}/sponsor/layout") or {}).get("current")
            except (Problem, Unavailable):
                cur = None
        return cur if isinstance(cur, dict) and (cur.get("layout") or {}).get("log") else None

    def sponsor_layout(rs: str) -> dict[str, Any]:
        """The study's sponsor layout (D-435), or 404 when none is saved."""
        cur = current_layout(rs)
        if cur is None:
            raise h.problem(404, "notfound")
        return cur

    @app.get("/studies/{rs}/screening-log.xlsx")
    def screening_log_xlsx(request: Request, rs: str, layout: str = "") -> Response:
        from openpyxl import Workbook

        sess = h.need(request)
        rid = study_or_404(sess, rs)
        h.need_rows(sess, rid, request.url.path)  # ROLE-017: the page's question (it holds pseudonyms, D-280)
        if layout not in ("", "sponsor"):
            raise h.problem(404, "notfound")
        wb = Workbook()
        ws: Any = wb.active
        ws.title = "screening log"
        table: list[list[Any]] = []
        for r in log_rows(rid):
            mk, oc, rf, ov = r["mark"], r["outcome"], r["referral"], r["override"]
            table.append(
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
                    rf.route if rf else "",
                    rf.state if rf else "",
                    rf.reason if rf else "",
                    local_date(rf.requested_at, tz) if rf else "",
                    local_date(rf.answered_at, tz) if rf and rf.answered_at else "",
                    ",".join(ov[1]) if ov else "",
                    r["version"],
                    r["failed"],
                    r["consented"],
                    r["icf_version"],
                    r["enrolled"],
                    r["randomised"],
                    r["opted_out"] or ("yes" if r["gone"] else ""),
                ]
            )
        if layout == "sponsor":  # D-435: the same rows in the sponsor's columns, words and date format
            cur = sponsor_layout(rid)
            heads, body = sponsor.log_table(cur["layout"], table)
            ws.append(heads)
            for line in body:
                ws.append(line)
            about = wb.create_sheet("about")
            about.append(["study", rid])
            about.append(["made", h.clock().astimezone(tz).isoformat(timespec="seconds")])
            about.append(
                ["layout", f"{cur['layout'].get('sponsor', '')} (layout {cur.get('id', '')}, {cur.get('at', '')})"]
            )
            about.append(["note", "Pseudonymous ICH E6(R3) screening log. Chart numbers are not in this file."])
            buf = io.BytesIO()
            sheets.no_formulas(wb)  # NEW-CSV-1 (D-549): a typed reason stays text
            wb.save(buf)
            name = f"screening_log_{rid}_sponsor.xlsx"
            au.append("console.export", ruleset=rid, actor=h.actor(sess),
                      detail={"filename": name, "layout": cur.get("id")})  # fmt: skip
            return Response(buf.getvalue(), media_type=XLSX,
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})  # fmt: skip
        ws.append(list(sponsor.LOG_COLUMNS))
        for line in table:
            ws.append(line)
        printable(wb, sess.lang, table)  # NEW-UX-3 (D-698): the first sheet is the log for people
        pre = wb.create_sheet("pre-screen log")  # D-387 (LIFE-015): one row per investigator mark
        pre.append(["pseudonym", "first_listed", "criteria_version", "pi_mark", "pi_mark_reason", "pi_mark_date",
                    "pi_mark_by", "later", "screening_no", "referral_outcome", "referral_reason", "status",
                    "reason"])  # fmt: skip
        for p in prescreen(rid):
            mk, rf = p["mark"], p["referral"]
            pre.append([p["pid"], local_date(p["listed"], tz), p["version"], mk.mark, mk.reason or "",
                        local_date(mk.at, tz), mk.by, p["later"], p["no"], rf.state if rf else "",
                        rf.reason if rf else "", p["status"], p["reason"]])  # fmt: skip
        about = wb.create_sheet("about")
        about.append(["study", rid])
        about.append(["made", h.clock().astimezone(tz).isoformat(timespec="seconds")])  # NEW-UX-3: the site's zone
        about.append(["note", "Pseudonymous ICH E6(R3) screening log. Chart numbers are not in this file."])
        for row in study_lines(store, rid):  # D-386 (LIFE-008, LIFE-013): identifiers and the state's dates
            about.append(row)
        about.append(["pre-screen log", "One row per investigator mark, approached or not (D-387)."])
        buf = io.BytesIO()
        sheets.no_formulas(wb)  # NEW-CSV-1 (D-549): a typed reason stays text
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
        h.need_rows(sess, rid, request.url.path)  # D-273 (PV-3), ROLE-017: one question with the XLSX and /api/v1
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
        gone = h.gone()  # D-147: opted-out patients are on no list
        members = [
            str(r.get("pid")) for r in (cl or {}).get("rows") or [] if r.get("tier") == "high"
            and str(r.get("pid")) not in gone
        ]  # fmt: skip
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
        return permit(sess.user.role, "report.office").allowed  # the CRO never sees the site's own totals

    @app.get("/reports/research-office")
    def research_office(request: Request, year: int = 0) -> Response:
        sess = h.need(request)
        if not office_allowed(sess):
            raise h.problem(403, "forbidden")
        y = year or h.today().year  # the site's year (D-270)
        k = SMALL_CELL
        return h.page(request, "research_office.html", sess, year=y, rows=office_counts(y, k), keys=COUNT_KEYS, small=k)

    @app.get("/reports/research-office.xlsx")
    def research_office_xlsx(request: Request, year: int = 0) -> Response:
        from openpyxl import Workbook

        sess = h.need(request)
        if not office_allowed(sess):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        y = year or h.today().year  # the site's year (D-270)
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
        sheets.no_formulas(wb)  # NEW-CSV-1 (D-549): a typed reason stays text
        wb.save(buf)
        name = f"research_office_{y}.xlsx"
        au.append("console.export", actor=h.actor(sess), detail={"filename": name})
        return Response(
            buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )
