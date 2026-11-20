"""In-product feedback (T-510, D-331; UX-006): a flag, a rating and a comment on every page of the console.

Every page carries the control (``templates/_feedback.html``, one include in ``base.html``) in the page's language:
a flag (what kind of problem: wrong result, confusing, wording, missing, slow, other), a rating from 1 to 5 and a
comment. The comment box says, beside it, that no patient details go there, and no field asks for a patient example.
One post to ``/feedback`` stores one entry; the product adds the page's path, the language, the account's role, the
account and the time. Nothing else changes: the tester goes back to the same page with a thank-you.

Stored in the trial database (PostgreSQL ``trialbox_wf``, schema ``feedback``; D-126). The demo's scan of stored input
(``python -m console.demo_guard scan --db``) reads every text column of that database, and names
``feedback.entry.comment`` as a column it must reach (:data:`console.demo_guard.MUST_SCAN`).

The owner exports the entries as one CSV, one row per future issue (title, body, labels and the raw fields), from
``/feedback/export.csv`` (an admin account) or ``python -m console.feedback export``. The export names a tester by a
code (T1, T2, ... in the order of their first entry), never by the account name, and runs the data-handling scan
(``tools/data_scan``) over each comment: a comment with a hit is withheld from the file and its row says which
pattern was found.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from starlette.routing import Match
from tb_common import sheets
from tb_common.authz import in_support_session
from tb_common.csvfile import for_spreadsheet

from console import i18n_feedback
from console.home import Helpers
from console.i18n import CATALOGUES
from console.storedb import open_db

for _lang, _cat in (("en", i18n_feedback.EN), ("ja", i18n_feedback.JA), ("zh-TW", i18n_feedback.ZH)):
    CATALOGUES[_lang].update(_cat)

FLAGS = ("wrong", "confusing", "wording", "missing", "slow", "other")
RATINGS = (1, 2, 3, 4, 5)
COMMENT_MAX = 1000
PATH_MAX = 200
EVENT = "feedback.add"
SAFE = "/-_.~:@!$&'()*+,;="  # what stays as it is in the path of the page to go back to
THANKS = "thanks"  # the query value that shows the thank-you on the page the tester came from

SCHEMA_V1 = """
CREATE TABLE entry (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at TEXT COLLATE "C" NOT NULL,
  path TEXT NOT NULL,
  lang TEXT NOT NULL,
  role TEXT NOT NULL,
  account TEXT NOT NULL,
  flag TEXT,
  rating SMALLINT,
  comment TEXT
);
CREATE INDEX entry_at ON entry (at)
"""
MIGRATIONS = (SCHEMA_V1,)
_COLS = "id, at, path, lang, role, account, flag, rating, comment"

CSV_COLUMNS = ("title", "body", "labels", "id", "time", "path", "lang", "role", "tester", "flag", "rating",
               "comment", "scan")  # fmt: skip


@dataclass(frozen=True)
class Entry:
    id: int
    at: str
    path: str
    lang: str
    role: str
    account: str
    flag: str | None
    rating: int | None
    comment: str | None


class FeedbackError(ValueError):
    """An entry that cannot be stored: the key of the message to show."""


def clean_path(value: str) -> str:
    """The page an entry is about: a local path, without its query, at most :data:`PATH_MAX` characters."""
    v = (value or "").split("?", 1)[0].split("#", 1)[0].strip()
    if not v.startswith("/") or v.startswith("//") or "\\" in v or any(ord(c) < 32 for c in v):
        return "/"
    return v[:PATH_MAX]


class FeedbackStore:
    """Schema ``feedback`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "feedback", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    def add(self, *, path: str, lang: str, role: str, account: str, flag: str | None, rating: int | None,
            comment: str | None, at: datetime | None = None) -> int:  # fmt: skip
        """Store one entry and return its id. At least one of the flag, the rating and the comment is needed."""
        flag = flag or None
        comment = (comment or "").strip() or None
        if flag is not None and flag not in FLAGS:
            raise FeedbackError("feedback.bad")
        if rating is not None and rating not in RATINGS:
            raise FeedbackError("feedback.bad")
        if comment is not None and len(comment) > COMMENT_MAX:
            raise FeedbackError("feedback.long")
        if flag is None and rating is None and comment is None:
            raise FeedbackError("feedback.empty")
        when = (at or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
        with self.db.transaction() as tx:
            return int(
                tx.fetchval(
                    "INSERT INTO entry (at, path, lang, role, account, flag, rating, comment) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (when, clean_path(path), lang, role, account, flag, rating, comment),
                )
            )

    def entries(self) -> list[Entry]:
        rows = self.db.fetchall(f"SELECT {_COLS} FROM entry ORDER BY id")
        return [Entry(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], None if r[7] is None else int(r[7]), r[8])
                for r in rows]  # fmt: skip


# ---------------------------------------------------------------------------------------------- the export
def _scanner() -> Any:
    """``text -> pattern ids`` with the repository's data-handling scan; None when the scan is not installed."""
    try:
        from tools import data_scan as ds
    except ImportError:
        return None
    patterns, allow = ds.load_patterns(exits=True), ds.load_allow()  # D-747: the export leaves the box
    return lambda text: sorted({h.pattern for h in ds.scan_text(text, "feedback", patterns, allow)})


def export_rows(entries: list[Entry]) -> list[dict[str, str]]:
    """One row per entry, ready to become one issue: tester codes for accounts, scanned comments withheld."""
    scan = _scanner()
    codes: dict[str, str] = {}
    out = []
    for e in entries:
        tester = codes.setdefault(e.account, f"T{len(codes) + 1}")
        found = scan(e.comment) if (scan is not None and e.comment) else []
        if scan is None and e.comment:
            found = ["not-scanned"]
        comment = "" if found else (e.comment or "")
        what = e.flag or (f"rating {e.rating}" if e.rating is not None else "comment")
        title = f"[poc] {what} · {e.path} ({e.lang})"
        body = "\n".join(
            [
                f"Page: {e.path}",
                f"Language: {e.lang} · role: {e.role} · tester: {tester} · time (UTC): {e.at}",
                f"Flag: {e.flag or '-'} · rating: {e.rating if e.rating is not None else '-'}",
                "",
                comment if comment else ("(comment withheld: " + ", ".join(found) + ")" if found else "(no comment)"),
            ]
        )
        labels = ",".join(["poc", "feedback", f"lang:{e.lang}"] + ([f"flag:{e.flag}"] if e.flag else []))
        out.append({"title": title, "body": body, "labels": labels, "id": str(e.id), "time": e.at, "path": e.path,
                    "lang": e.lang, "role": e.role, "tester": tester, "flag": e.flag or "",
                    "rating": "" if e.rating is None else str(e.rating), "comment": comment,
                    "scan": ";".join(found)})  # fmt: skip
    return out


def export_csv(entries: list[Entry]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    # NEW-CSV-1 (D-549): a comment is typed text; no cell of the file runs as a formula in a spreadsheet
    w.writerows({k: sheets.csv_cell(v) for k, v in row.items()} for row in export_rows(entries))
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------- the routes
def _get_route(app: FastAPI, path: str) -> bool:
    """A page the tester can be sent back to: ``path`` answers a GET."""
    scope = {"type": "http", "path": path, "method": "GET"}
    return any(r.matches(scope)[0] == Match.FULL for r in app.router.routes)


def register(app: FastAPI, h: Helpers, store: FeedbackStore | None = None) -> FeedbackStore:
    """The post of the control on every page and the owner's CSV export."""
    fb = store if store is not None else FeedbackStore()
    app.state.feedback = fb

    def signed_in(request: Request) -> Any:
        """Any signed-in account may give feedback on the page it sees, a CRO account too (whose role scope opens
        the reports pages only). Without a session, or before a set password is changed: what ``h.need`` does."""
        from console.app import COOKIE  # console.app imports this module

        sess = h.users.session(request.cookies.get(COOKIE), touch=False)
        if sess is None or h.users.must_change(sess.user.username):
            return h.need(request)
        return sess

    @app.post("/feedback")
    def feedback_post(
        request: Request,
        csrf: str = Form(""),
        path: str = Form("/"),
        flag: str = Form(""),
        rating: str = Form(""),
        comment: str = Form(""),
    ) -> Response:
        sess = signed_in(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        page = clean_path(path)
        try:
            stars = int(rating) if rating.strip() else None
        except ValueError:
            raise h.problem(400, "feedback.bad") from None
        try:
            fid = fb.add(path=page, lang=sess.lang, role=sess.user.role, account=sess.user.username,
                         flag=flag.strip() or None, rating=stars, comment=comment)  # fmt: skip
        except FeedbackError as e:
            raise h.problem(400, str(e)) from None
        # the audit names the entry and the page, never the comment
        h.au.append(EVENT, actor=h.actor(sess), detail={"id": fid, "path": page[:120]})
        back = page if _get_route(app, page) else "/"
        return RedirectResponse(f"{quote(back, safe=SAFE)}?feedback={THANKS}#feedback", status_code=303)

    @app.get("/feedback/export.csv")
    def feedback_export(request: Request) -> Response:
        sess = h.need(request)
        # 10K-15 (D-1364): closed during a support session too; the entries hold the paths of the pages they were
        # given on (a patient page's pseudonym) and free text. A check that only narrows: no matrix row of its own
        if not sess.user.is_admin or in_support_session():
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        rows = fb.entries()
        h.au.append("feedback.export", actor=h.actor(sess), detail={"entries": len(rows)})
        return Response(
            for_spreadsheet(export_csv(rows)),
            media_type="text/csv; charset=utf-8",
            headers={"content-disposition": 'attachment; filename="feedback.csv"'},
        )

    return fb


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m console.feedback", description="the in-product feedback (T-510)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write the entries as one CSV, one row per issue (TB_DB_URL)")
    ex.add_argument("--out", help="the file to write (default: standard output)")
    a = ap.parse_args(argv)
    store = FeedbackStore()
    try:
        entries = store.entries()
    finally:
        store.close()
    text = export_csv(entries)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(for_spreadsheet(text))  # a file the owner opens in a spreadsheet; the pipe below has no mark
        print(f"feedback export: {len(entries)} entr(y/ies) written to {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
