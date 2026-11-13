"""``/audit``: the audit browser of the privacy office and the steward (T-211c, D-451; ROLE-013).

**Who.** One matrix row, ``audit.browse`` (the privacy office and the steward). Every other role gets 403 and a
``console.denied`` event on each route here: the browser, one patient's report, its file and the verification.

**Reading.** The console reads the hash chain's day files (the audit volume, read-only for the console since D-394:
the services write through ``audit.append`` into ``audit.journal`` and the ``audit-writer`` alone writes the chain).
Nothing here writes the chain but the console's own reading events, through the one writer every page uses.
:func:`search` reads newest first and stops at one page plus one event: a day file outside the period is not opened,
a line that cannot match is skipped before it is parsed, and the next page is a cursor (day file and line). The page
never holds the chain, and there is no 1,000-event horizon (the old ``AUDIT_PAGES``).

**One patient.** ``/audit/patients/{pid}`` lists every event that names the pseudonym in any field but the hashes:
reveals (D-438: ``console.reveal_patient`` and ``console.reveal_refused``; before it ``console.view_id``, the
orchestrator's ``screen.reveal``), break-glass uses (D-430), exports and downloads. It shows what the events hold and
joins in nothing: no name, no chart number. ``/audit/patients/{pid}/report.csv`` is the same report as a file,
through the same guard.

**Audited.** One ``console.audit_search`` per browser page, one ``console.audit_report`` per report or file, one
``console.audit_verify`` per verification: each with the filter, never the result.

**Verify.** :func:`verify_now` calls the existing check, ``tb_common.audit.verify``, with the signed heads of every
off-box anchor folder (``TB_AUDIT_ANCHOR_TARGETS``), as ``tools/audit_verify.py --heads`` does, and returns what the
page shows: the chain state, the last signed head and each anchor folder's newest head.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from tb_common import audit as tb_audit
from tb_common.authz import permit

from console import i18n_audit
from console.auth import Session
from console.i18n import CATALOGUES

for _lang, _cat in (("en", i18n_audit.EN), ("ja", i18n_audit.JA), ("zh-TW", i18n_audit.ZH)):
    CATALOGUES[_lang].update(_cat)

BROWSE = "audit.browse"
PAGE = 50
REPORT_PAGE = 200
PID = re.compile(r"^[0-9a-f]{32}$")
_PSEUDONYM = re.compile(r"\b[0-9a-f]{32}\b")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURSOR = re.compile(r"^(\d{4}-\d{2}-\d{2}):(\d{1,9})$")
_HASHES = ("hash", "prev_hash", "input_sha", "output_sha")

#: The kinds of the filter and of one patient's counts. An event outside every kind is "other".
KINDS: dict[str, frozenset[str]] = {
    "reveal": frozenset({
        "console.reveal_patient", "console.reveal_refused", "console.view_id", "console.view_id_refused",
        "screen.reveal", "screen.reveal_refused", "console.chart_lookup", "console.site_chart", "screen.to_pid",
    }),
    "breakglass": frozenset({
        "console.breakglass_open", "console.breakglass_use", "console.breakglass_end", "console.breakglass_review",
        "console.breakglass_notice",
    }),
    "export": frozenset({
        "console.export", "console.download", "console.data_export", "data.export", "registry.export",
        "registry.export_refused", "edc.export", "feedback.export", "console.registry",
    }),
    "signin": frozenset({
        "console.login", "console.login_failed", "console.logout", "console.lockout", "console.sso_rejected",
        "console.reauth_failed", "console.totp_enrolled", "console.totp_reset", "console.unlock",
    }),
    "refusal": frozenset({
        "console.denied", "console.refused", "console.rate_limited", "console.edc_refused", "console.reveal_refused",
        "console.view_id_refused", "screen.reveal_refused", "registry.export_refused", "actor.refused",
        "edc.refused", "life.refused",
    }),
    "audit": frozenset({
        "console.audit_search", "console.audit_report", "console.audit_verify", "audit.anchored", "audit.reanchored",
        "audit.repaired", "audit.head_signed", "audit.signing_key_rotated", "audit.journal_resync",
    }),
}  # fmt: skip
#: one patient's counts, in this order
REPORT_KINDS = ("reveal", "breakglass", "export")

#: detail keys the browser shows (scalars only; a list is shown as its length). Free text that a person typed beyond
#: these (an "other" reveal's note, a request's body) is not shown; every value is masked again on the page.
SHOWN = (
    "pid", "study", "purpose", "reason", "basis", "via", "cap", "count", "refused", "grant", "kind", "what", "where",
    "role", "affiliation", "action", "filename", "tag", "type", "format", "from", "to", "event", "who", "job",
    "lines", "ok", "head", "key_id", "anchors", "source", "run", "subject", "line", "bytes", "records", "patients",
    "breakglass", "page",
)  # fmt: skip


@dataclass(frozen=True)
class Filter:
    kind: str = ""
    event: str = ""
    who: str = ""
    pid: str = ""
    job: str = ""
    since: str = ""
    until: str = ""

    def audit_detail(self) -> dict[str, str]:
        """What the reading event records: the filter, never the result."""
        names = {"kind": self.kind, "event": self.event, "who": self.who, "pid": self.pid, "job": self.job,
                 "from": self.since, "to": self.until}  # fmt: skip
        return {k: v for k, v in names.items() if v}

    def query(self, with_pid: bool = True) -> str:
        """The filter as a query string (for the next page's link); ``with_pid`` False for a report's own path."""
        from urllib.parse import urlencode

        pairs = {"kind": self.kind, "event": self.event, "who": self.who, "pid": self.pid if with_pid else "",
                 "job": self.job, "since": self.since, "until": self.until}  # fmt: skip
        return urlencode({k: v for k, v in pairs.items() if v})


def make_filter(kind: str = "", event: str = "", who: str = "", pid: str = "", job: str = "", since: str = "",
                until: str = "") -> Filter:  # fmt: skip
    """A filter from the query string: an unknown kind or a malformed date or pseudonym is dropped, never guessed."""
    pid = pid.strip().lower()
    since, until = since.strip(), until.strip()
    return Filter(
        kind=kind if kind in KINDS else "",
        event=event.strip()[:80] if re.fullmatch(r"[a-z][a-z0-9_.]{0,79}", event.strip()) else "",
        who=" ".join(who.split())[:80],
        pid=pid if PID.match(pid) else "",
        job=job.strip()[:40] if re.fullmatch(r"[0-9A-Za-z_-]{1,40}", job.strip()) else "",
        since=since if _valid_day(since) else "",
        until=until if _valid_day(until) else "",
    )


def _valid_day(text: str) -> bool:
    if not _DAY.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


@dataclass
class Row:
    ts: str
    event: str
    actor: str | None
    job_id: str | None
    ruleset: str | None
    hash: str
    at: str  # the cursor of this event: day file and line
    detail: dict[str, Any] = field(default_factory=dict)


def _shown(det: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in SHOWN:
        v = det.get(k)
        if isinstance(v, bool):
            out[k] = "yes" if v else "no"
        elif isinstance(v, str | int | float) and v != "":
            out[k] = v
        elif isinstance(v, list | tuple):
            out[k] = len(v)
    return out


def _names_pid(rec: Mapping[str, Any], pid: str) -> bool:
    body = {k: v for k, v in rec.items() if k not in _HASHES}
    return pid in json.dumps(body, ensure_ascii=False, default=str)


def _matches(rec: Mapping[str, Any], f: Filter, events: frozenset[str] | None) -> bool:
    ev = str(rec.get("event", ""))
    if events is not None and ev not in events:
        return False
    if f.event and ev != f.event:
        return False
    if f.who and f.who.lower() not in str(rec.get("actor") or "").lower():
        return False
    if f.job and str(rec.get("job_id") or "") != f.job:
        return False
    return not (f.pid and not _names_pid(rec, f.pid))


def _cheap(raw: str, f: Filter, events: frozenset[str] | None) -> bool:
    """A test on the raw line before it is parsed: False means the line cannot match."""
    if f.pid and f.pid not in raw:
        return False
    if f.event and f'"{f.event}"' not in raw:
        return False
    if f.job and f.job not in raw:
        return False
    return not (events is not None and not any(f'"{e}"' in raw for e in events))


def iter_events(directory: Path, f: Filter, before: str = "") -> Iterator[Row]:
    """The chain's events that match ``f``, newest first, from just before the cursor ``before`` (``day:line``)."""
    events = KINDS.get(f.kind)
    m = _CURSOR.match(before or "")
    stop_day, stop_line = (m.group(1), int(m.group(2))) if m else ("", 0)
    files = sorted((p for p in directory.glob("*.jsonl") if _DAY.match(p.stem)), reverse=True)
    for path in files if directory.is_dir() else []:
        day = path.stem
        if f.since and day < f.since:
            break  # newest first: every later file is older still
        if (f.until and day > f.until) or (stop_day and day > stop_day):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        end = stop_line - 1 if day == stop_day else len(lines)
        for i in range(min(end, len(lines)) - 1, -1, -1):
            raw = lines[i]
            if not raw or not _cheap(raw, f, events):
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict) or not _matches(rec, f, events):
                continue
            det = rec.get("detail")
            det = det if isinstance(det, dict) else {}
            yield Row(
                ts=str(rec.get("ts", "")),
                event=str(rec.get("event", "")),
                actor=rec.get("actor") if isinstance(rec.get("actor"), str) else None,
                job_id=rec.get("job_id") if isinstance(rec.get("job_id"), str) else None,
                ruleset=rec.get("ruleset") if isinstance(rec.get("ruleset"), str) else None,
                hash=str(rec.get("hash", ""))[:12],
                at=f"{day}:{i + 1}",
                detail=_shown(det),
            )


def search(directory: Path, f: Filter, limit: int = PAGE, before: str = "") -> tuple[list[Row], str]:
    """One page of matching events, newest first, and the cursor of the next page ("" when there is none)."""
    rows: list[Row] = []
    for row in iter_events(directory, f, before):
        rows.append(row)
        if len(rows) > limit:
            break
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (rows[-1].at if more and rows else "")


def hide_pids(row: Row) -> Row:
    """The row with every pseudonym of its detail hidden (``pid`` and any 32-hex run); the event itself stays."""

    def one(k: str, v: Any) -> Any:
        if k in ("pid", "pids"):
            return tb_audit.ID_MASK
        return _PSEUDONYM.sub(tb_audit.ID_MASK, v) if isinstance(v, str) else v

    return replace(row, detail={k: one(k, v) for k, v in row.detail.items()})


def kind_of(event: str) -> str:
    for k in REPORT_KINDS:
        if event in KINDS[k]:
            return k
    return "other"


# ------------------------------------------------------------------------------------------------ the file
_FORMULA = ("=", "+", "-", "@", "\t", "\r")
CSV_COLUMNS = ("time", "event", "label", "kind", "actor", "study", "job", "pid", "purpose", "reason", "basis", "via",
               "cap", "refused", "grant", "detail", "hash")  # fmt: skip


def cell(value: Any) -> str:
    """A CSV cell a spreadsheet will not run as a formula."""
    text = tb_audit.mask_ids(str(value if value is not None else ""))
    return "'" + text if text.startswith(_FORMULA) else text


def csv_lines(rows: Iterator[Row], label: Any) -> Iterator[str]:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    def flush() -> str:
        out = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return out

    w.writerow(CSV_COLUMNS)
    yield flush()
    named = ("pid", "purpose", "reason", "basis", "via", "cap", "refused", "grant")
    for r in rows:
        rest = "; ".join(f"{k}={v}" for k, v in r.detail.items() if k not in named)
        w.writerow([cell(x) for x in (r.ts, r.event, label(r.event), kind_of(r.event),
                                      (r.actor or "").removeprefix("console:"), r.ruleset, r.job_id,
                                      *(r.detail.get(k, "") for k in named), rest, r.hash)])  # fmt: skip
        yield flush()


# ------------------------------------------------------------------------------------------------ verify
def verify_now(directory: Path, targets: list[Path] | None = None) -> dict[str, Any]:
    """The existing verification (``tb_common.audit.verify``) with the signed heads of every off-box anchor folder,
    as ``tools/audit_verify.py --heads`` runs it; the trusted keys are the anchor folders' ``keys/`` (a note says
    so, as the tool does). Returns what the page shows."""
    targets = tb_audit.anchor_targets() if targets is None else targets
    anchors: list[dict[str, Any]] = []
    heads: list[dict[str, Any]] = []
    for t in targets:
        if not t.is_dir():
            anchors.append({"name": t.name or str(t), "reachable": False, "newest": None, "count": 0})
            continue
        got = tb_audit.read_signed_heads(t)
        heads.extend(got)
        newest = got[-1] if got else None
        anchors.append({"name": t.name or str(t), "reachable": True, "count": len(got),
                        "newest": _head_view(newest) if newest else None})  # fmt: skip
    signed = None
    notes: list[str] = []
    if targets:
        keys = [t / "keys" for t in targets if (t / "keys").is_dir()]
        trusted = tb_audit.read_public_keys(keys)
        res = tb_audit.verify(directory, signed_heads=heads, trusted_keys=trusted)
        notes.append("keys")
        good = [h for h in heads if isinstance(h.get("lines"), int)]
        if good:
            signed = _head_view(max(good, key=lambda h: (int(h["lines"]), str(h.get("ts")))))
    else:
        res = tb_audit.verify(directory)
        notes.append("no_anchor")
    return {
        "ok": res.ok,
        "files": res.files,
        "lines": res.lines,
        "head": res.last_hash[:16],
        "errors": res.errors[:10],
        "more_errors": max(0, len(res.errors) - 10),
        "notes": res.notes[:10],
        "signed": signed,
        "anchors": anchors,
        "say": notes,
    }


def _head_view(h: Mapping[str, Any]) -> dict[str, Any]:
    return {"ts": str(h.get("ts") or ""), "lines": h.get("lines"), "key_id": str(h.get("key_id") or "")[:16]}


# ------------------------------------------------------------------------------------------------ routes
@dataclass(frozen=True)
class Hooks:
    """What the routes need from ``console.app``; the browser is registered with or without the pilot workspace."""

    need: Callable[[Request], Session]
    page: Callable[..., Response]
    problem: Callable[..., Exception]
    csrf_ok: Callable[[Session, str], bool]
    actor: Callable[[Session], str]
    au: Any


def register(app: FastAPI, h: Hooks) -> None:
    def directory() -> Path:
        return Path(h.au.directory)

    def guard(request: Request) -> Session:
        sess = h.need(request)
        if not permit(sess.user.role, BROWSE):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def shown_to(sess: Session, rows: list[Row]) -> list[Row]:
        """D-380 (CR-023): a reader without ``audit.ids`` would see every pseudonym hidden. Both roles of
        ``audit.browse`` hold it today; the rule stays so a later row cannot widen what a reader sees."""
        return rows if permit(sess.user.role, "audit.ids") else [hide_pids(r) for r in rows]

    def label_of(lang: str) -> Any:
        return lambda event: i18n_audit.event_label(lang, event)

    @app.get("/audit", response_class=HTMLResponse)
    def audit_view(
        request: Request,
        kind: str = "",
        event: str = "",
        who: str = "",
        pid: str = "",
        job: str = "",
        since: str = "",
        until: str = "",
        before: str = Query("", max_length=40),
        bad: str = "",
    ) -> Response:
        """The browser: newest first, filtered and cut by the reader, one ``console.audit_search`` per page."""
        sess = guard(request)
        f = make_filter(kind, event, who, pid, job, since, until)
        rows, nxt = search(directory(), f, PAGE, before)
        rows = shown_to(sess, rows)
        h.au.append("console.audit_search", actor=h.actor(sess),
                    detail={**f.audit_detail(), **({"page": "next"} if before else {})})  # fmt: skip
        return h.page(request, "audit.html", sess, records=rows, f=f, next_before=nxt, kinds=tuple(KINDS),
                      events=i18n_audit.event_names(), bad_pid=bad == "pid" or (bool(pid.strip()) and not f.pid),
                      first=not before)  # fmt: skip

    def report_filter(pid: str, since: str, until: str, kind: str) -> Filter:
        f = make_filter(kind=kind, pid=pid, since=since, until=until)
        if not f.pid:
            raise h.problem(404, "notfound")
        return f

    @app.get("/audit/patients")
    def audit_patient_box(request: Request, pid: str = "") -> Response:
        """The patient box of the browser (step one): a pseudonym goes straight to its report (step two)."""
        guard(request)
        f = make_filter(pid=pid)
        if not f.pid:  # what was typed is not echoed into a URL: it may be a chart number
            return RedirectResponse("/audit?bad=pid", status_code=303)
        return RedirectResponse(f"/audit/patients/{f.pid}", status_code=303)

    @app.get("/audit/patients/{pid}", response_class=HTMLResponse)
    def audit_patient(
        request: Request,
        pid: str,
        kind: str = "",
        since: str = "",
        until: str = "",
        before: str = Query("", max_length=40),
    ) -> Response:
        """One patient's report: every event that names the pseudonym, with counts per kind on this page."""
        sess = guard(request)
        f = report_filter(pid, since, until, kind)
        rows, nxt = search(directory(), f, REPORT_PAGE, before)
        rows = shown_to(sess, rows)
        h.au.append("console.audit_report", actor=h.actor(sess), detail={**f.audit_detail(), "format": "page"})
        counts = {k: 0 for k in (*REPORT_KINDS, "other")}
        for r in rows:
            counts[kind_of(r.event)] += 1
        return h.page(request, "audit_patient.html", sess, records=rows, f=f, next_before=nxt, counts=counts,
                      kinds=REPORT_KINDS, rq=f.query(with_pid=False))  # fmt: skip

    @app.get("/audit/patients/{pid}/report.csv")
    def audit_patient_csv(request: Request, pid: str, kind: str = "", since: str = "", until: str = "") -> Response:
        """The same report as a file: the same guard, the same filter, one ``console.audit_report`` (format csv)."""
        sess = guard(request)
        f = report_filter(pid, since, until, kind)
        h.au.append("console.audit_report", actor=h.actor(sess), detail={**f.audit_detail(), "format": "csv"})
        lang = sess.lang if sess.lang in CATALOGUES else "en"
        name = f"audit-{f.pid[:8]}.csv"
        return StreamingResponse(
            csv_lines(iter_events(directory(), f), label_of(lang)),
            media_type="text/csv; charset=utf-8",
            headers={"content-disposition": f'attachment; filename="{name}"', "cache-control": "no-store"},
        )

    @app.post("/audit/verify", response_class=HTMLResponse)
    def audit_verify(request: Request, csrf: str = Form("")) -> Response:
        """The chain's verification, as ``tools/audit_verify.py`` runs it, shown on the browser page."""
        sess = guard(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        result = verify_now(directory())
        done = {"ok": result["ok"], "lines": result["lines"], "anchors": len(result["anchors"])}
        h.au.append("console.audit_verify", actor=h.actor(sess), detail=done)
        rows, nxt = search(directory(), Filter(), PAGE)
        rows = shown_to(sess, rows)
        return h.page(request, "audit.html", sess, records=rows, f=Filter(), next_before=nxt, kinds=tuple(KINDS),
                      events=i18n_audit.event_names(), bad_pid=False, first=True, verified=result)  # fmt: skip


def register_api(app: FastAPI, h: Hooks, api_session: Callable[[Request], Session]) -> None:
    """``POST /api/v1/audit/verify``, the twin of the page's "Verify the chain" (FIT-019, T-657): the session and
    ``audit.browse`` before the body (``api_first``), the same check, the same ``console.audit_verify`` event. Only in
    the pilot workspace, where the bearer sign-in exists."""
    from console.api_first import before_body

    def may(sess: Session, request: Request) -> None:
        if not permit(sess.user.role, BROWSE):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    @app.post("/api/v1/audit/verify")
    @before_body(may)
    def api_audit_verify(request: Request) -> dict[str, Any]:
        sess = api_session(request)
        may(sess, request)
        result = verify_now(Path(h.au.directory))
        done = {"ok": result["ok"], "lines": result["lines"], "anchors": len(result["anchors"])}
        h.au.append("console.audit_verify", actor=h.actor(sess), detail=done)
        return result
