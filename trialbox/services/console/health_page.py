"""M5 (10K-6, SO-6, 9l-23): the health page (``/admin/health``): what a supervisor watches each morning.

One line per fact, each green or red, and each with its red case:

* **the last good night per source**: the newest ``ingest.done`` of each source the adapter has read. Red when there
  is none, or when it is older than :data:`INGEST_RED_H` hours: a feed that stopped is red the next morning;
* **rows in and held**: the source's newest night (``ingest.done``, ``ingest.held`` or ``ingest.failed``): the rows
  it read, and whether the gate held them. Red when the night was held or failed;
* **jobs waiting and the oldest**: the jobs not yet ended. Red when the oldest has waited more than
  :data:`WAIT_RED_H` hours;
* **the audit drain's lag**: on a box whose services send their events to the journal (``TB_AUDIT_WRITER=db``), how
  long ago the last journal row reached the chain (``tb_common.audit_writer.last_drained``). The page is read by a
  signed-in administrator, whose sign-in event went through the journal, so a working drain reads minutes. Red when
  nothing has been drained or the last row is older than :data:`DRAIN_RED_MIN` minutes. A console that writes the
  chain itself has no drain: the line says so;
* **model latency**: the jobs that ended in the last :data:`LATENCY_WINDOW_H` hours and called a model: their wall
  time over their model calls (an upper bound: the wall time holds the steps around the calls). Red above
  :data:`CALL_RED_S` seconds per call.

Counts, ages and source names only: no patient, no user name. Who may read it: the administrator
(``authz.admin_allowed(role, "ops.view")``), as for the operations pages; anyone else is a ``console.denied`` line.
``GET /api/v1/admin/health`` is the page's twin.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from tb_common.authz import admin_allowed

from console.home import Helpers
from console.i18n import CATALOGUES
from console.i18n_m5 import EN, JA, ZH
from console.screen_now import ACTIVE

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

PATH = "/admin/health"
OK, RED = "ok", "red"
#: a nightly feed: one night plus two hours, so a feed that stopped is red the next morning
INGEST_RED_H = 26
WAIT_RED_H = 6
DRAIN_RED_MIN = 15
CALL_RED_S = 30.0
LATENCY_WINDOW_H = 36
NIGHT_EVENTS = ("ingest.done", "ingest.held", "ingest.failed")
ENDED = frozenset({"done", "failed", "cancelled"})
#: the states of a job not yet ended are ``console.screen_now.ACTIVE``, each read on its own so that a long history
#: of ended jobs does not hide one waiting
JOBS_READ = 500
#: how far back the page reads the audit for the nights
AUDIT_READ = 5000


@dataclass(frozen=True)
class Line:
    kind: str  # ingest, ingest_none, rows, jobs, drain, drain_file, latency, latency_none
    level: str
    values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "level": self.level, **self.values}


def aware(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _rows(detail: Mapping[str, Any]) -> int:
    """The night's rows: the console's audit reader keeps an ingest's total as ``records`` (S24); a record read whole
    carries ``counts`` per type."""
    counts = detail.get("counts")
    if isinstance(counts, Mapping):
        return sum(int(v) for v in counts.values() if isinstance(v, int | float) and not isinstance(v, bool))
    n = detail.get("records")
    return int(n) if isinstance(n, int | float) and not isinstance(n, bool) else 0


def night_lines(records: Iterable[Any], now: datetime) -> list[Line]:
    """The source lines from the audit's night records (any order): per source, the last good night and the newest
    night's rows."""
    last_ok: dict[str, datetime] = {}
    newest: dict[str, tuple[datetime, Any]] = {}
    for r in records:
        if r.event not in NIGHT_EVENTS or (at := aware(r.ts)) is None:
            continue
        src = str((r.detail or {}).get("source") or "csv")
        if r.event == "ingest.done" and (src not in last_ok or at > last_ok[src]):
            last_ok[src] = at
        if src not in newest or at > newest[src][0]:
            newest[src] = (at, r)
    if not newest:
        return [Line("ingest_none", RED)]
    out: list[Line] = []
    for src in sorted(newest):
        ok_at = last_ok.get(src)
        hours = None if ok_at is None else round((now - ok_at).total_seconds() / 3600, 1)
        red = hours is None or hours > INGEST_RED_H
        when = ok_at.isoformat(timespec="minutes") if ok_at else ""
        out.append(Line("ingest", RED if red else OK, {"source": src, "hours": hours, "at": when}))
        at, rec = newest[src]
        state = {"ingest.done": "in", "ingest.held": "held", "ingest.failed": "failed"}[rec.event]
        out.append(Line("rows", OK if state == "in" else RED, {"source": src, "rows": _rows(
            rec.detail or {}), "state": state, "at": at.isoformat(timespec="minutes")}))  # fmt: skip
    return out


def jobs_line(jobs: Iterable[Any], now: datetime) -> Line:
    waiting = [j for j in jobs if j.state not in ENDED]
    oldest = min((a for j in waiting if (a := aware(j.received_at)) is not None), default=None)
    hours = None if oldest is None else round((now - oldest).total_seconds() / 3600, 1)
    red = hours is not None and hours > WAIT_RED_H
    return Line("jobs", RED if red else OK, {"waiting": len(waiting), "hours": hours})


def drain_line(mode: str, drained_at: datetime | None, now: datetime) -> Line:
    if mode != "db":
        return Line("drain_file", OK)
    if drained_at is None:
        return Line("drain", RED, {"minutes": None})
    minutes = round((now - drained_at).total_seconds() / 60, 1)
    return Line("drain", RED if minutes > DRAIN_RED_MIN else OK, {"minutes": minutes})


def latency_line(jobs: Iterable[Any], now: datetime) -> Line:
    since = now - timedelta(hours=LATENCY_WINDOW_H)
    calls, seconds = 0, 0.0
    for j in jobs:
        m = j.metrics
        at = aware(j.updated_at or j.received_at)
        if j.state != "done" or m is None or not m.llm_calls or at is None or at < since:
            continue
        calls += int(m.llm_calls)
        seconds += float(m.wall_seconds or 0)
    if not calls:
        return Line("latency_none", OK)
    per = round(seconds / calls, 1)
    return Line("latency", RED if per > CALL_RED_S else OK, {"seconds": per, "calls": calls})


def lines(records: Iterable[Any], jobs: Sequence[Any], now: datetime, *, mode: str = "file",
          drained_at: datetime | None = None) -> list[Line]:  # fmt: skip
    """Every line of the page at ``now``."""
    return [*night_lines(records, now), jobs_line(jobs, now), drain_line(mode, drained_at, now),
            latency_line(jobs, now)]  # fmt: skip


def register(app: FastAPI, h: Helpers, env: Mapping[str, str] | None = None) -> None:
    e = dict(env or {})
    mode = (e.get("TB_AUDIT_WRITER") or "file").strip().lower()
    audit_dir = Path(e.get("TB_AUDIT_DIR") or "/data/audit")

    def need_admin(request: Request, sess: Any) -> Any:
        if not admin_allowed(sess.user.role, "ops.view"):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def drained() -> datetime | None:
        if mode != "db":
            return None
        from tb_common.audit_writer import last_drained

        try:
            c = last_drained(audit_dir)
        except OSError:
            return None
        return aware(c.at) if c is not None else None

    def now_lines() -> list[Line]:
        now = aware(h.clock()) or datetime.now(UTC)
        jobs = [j for st in ACTIVE for j in h.bk.list_jobs(JOBS_READ, state=st)]
        jobs += h.bk.list_jobs(JOBS_READ, state="done")
        return lines(h.bk.audit(None, AUDIT_READ), jobs, now, mode=mode, drained_at=drained())

    @app.get(PATH)
    def health_page(request: Request) -> Response:
        sess = need_admin(request, h.need(request))
        got = now_lines()
        return h.page(request, "health_page.html", sess, lines=got, red=sum(x.level == RED for x in got))

    @app.get("/api/v1" + PATH, response_model=None)
    def api_health_page(request: Request) -> Any:
        assert h.api_session is not None  # set by register() before any request
        need_admin(request, h.api_session(request))
        got = now_lines()
        return {"level": RED if any(x.level == RED for x in got) else OK, "lines": [x.as_dict() for x in got]}
