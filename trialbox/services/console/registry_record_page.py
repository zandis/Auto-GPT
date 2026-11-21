"""One study's jRCT record from a file the person downloaded themself (plan 10 card 10D-16, file half "10D-16a",
D-1373; Decision 52: one record at a time, started by a person; D-317: TrialBox never fetches jRCT data).

``/studies/{rs}/registry-record`` (and ``GET /api/v1/studies/{rs}/registry-record``) shows the study's record; the
page takes one CSV file and ``POST /api/v1/studies/{rs}/registry-record`` takes the same file as its body
(``text/csv``). **No network:** nothing here opens a connection, builds an address or reads a number a person types;
the page names jRCT's website in words (not a link). The other half of the card (a typed number making the box fetch a
record) is the owner's question and is not built.

* **Who reads:** exactly the readers of the study's state page (``/studies/{rs}/state``, the only page on master that
  shows the study's registry numbers and who changed them): the page and its API twin ask that page's own check
  (``Helpers.state_reader``, set by ``console.study_setup``), so the two never differ.
* **Who reads a file in:** the matrix's ``study.state`` row as it is (D-386: "change the study's state ... and its
  identifiers"): every hospital or study-scoped coordinator who reads the study, and the PI the study's log names (the
  log decides only for the investigator). Asked before a byte of the body is read; a refusal is audited
  (``console.denied``).
* **The file is hostile:** the API checks the content type before it reads the body; the body is read up to
  :data:`BODY_MAX` and no further (a larger one is refused before it is parsed, so the form parser never spools it to
  disk); then ``tb_common.registry_file.read_record``. The upload's name is never used: not on disk, not in the
  audit, not on the page.
* **Kept:** not the file: the record's six kept fields with the file's SHA-256, who and when, as one JSON file named
  ``<sha256 of the file>.json`` (a name the server chooses) in ``<TB_CONSOLE_DIR>/registry_records/<STUDY>/``, folders
  0700 and files 0600 owned by the console's own user. Written to a temporary name in the same folder and linked into
  place without replacing: the same file twice is kept once. A file in the folder that the box did not write (a link,
  or content whose study or SHA-256 is not its name) is never shown and makes a later write refuse.
* **The current record** is the record of the file first read most recently (by the time it was read); reading an
  older file again changes nothing (audited ``same``) and the page says which record stays current. No record is
  removed here.
* **Audited before the page says so:** ``console.registry_record`` (``taken``, with the jRCT number and the kept
  fields' names, or ``same``) or ``console.registry_record_refused`` (with the rule's code), each with the account,
  the study, and the file's SHA-256 and size when a file was read; a body over the cap records ``more_than``. A
  request with a wrong CSRF token is refused (400) without an audit event, as every console form on master refuses
  one: it is a request the page did not make, and nothing of it is read.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from tb_common import registry_file as rf

from console import demo_guard, i18n_registry_record
from console.api_first import before_body
from console.auth import Session
from console.form_errors import FAILED, FieldError, FormErrors
from console.home import Helpers
from console.i18n import CATALOGUES, translate

for _lang, _cat in (("en", i18n_registry_record.EN), ("ja", i18n_registry_record.JA),
                    ("zh-TW", i18n_registry_record.ZH)):  # fmt: skip
    CATALOGUES[_lang].update(_cat)

_RS = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,31}")  # always with fullmatch: no trailing line end
_SHA = re.compile(r"[0-9a-f]{64}")
EVENT = "console.registry_record"  # a file read: taken, or the same file again
REFUSED_EVENT = "console.registry_record_refused"  # a file refused, with the rule it broke
ACTION = "study.state"  # D-386: the study's state and its identifiers
FOLDER = "registry_records"
#: the request body read at most (the file and the form's few fields); a larger body is refused unread
BODY_MAX = rf.MAX_BYTES + 16 * 1024
FORM = "rrec"  # the form's data-fields name and the prefix of its fields' ids
FIELD = "record"  # the file field
EARLIER_SHOWN = 20  # the files read before, newest first, shown on the page (each file's record stays on disk)
SHOWN_SHA = 12  # the characters of a file's SHA-256 in the page's address after a read


class TooLarge(Exception):
    """The request body is larger than :data:`BODY_MAX`."""


class NotOurs(OSError):
    """The study's folder holds, under the name a record would take, something the box did not write."""


async def read_capped(request: Request) -> bytes:
    """The request body, or :class:`TooLarge` as soon as more than :data:`BODY_MAX` bytes came. The body read is put
    where Starlette's own form parser reads it, so a parsed form never comes from a second, unbounded read."""
    chunks: list[bytes] = []
    n = 0
    async for chunk in request.stream():
        n += len(chunk)
        if n > BODY_MAX:
            raise TooLarge
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body  # starlette's Request.form() and .body() read this instead of the stream
    return body


def _when(at: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else None


class Store:
    """The kept records of each study, one JSON file per file read, under ``root`` (the box's own folder)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _folder(self, rid: str, make: bool) -> Path | None:
        if not isinstance(rid, str) or not _RS.fullmatch(rid):
            raise ValueError("not a study code")
        folder = self.root / rid
        for d in (self.root, folder):
            if make and not d.is_symlink():
                d.mkdir(mode=0o700, parents=d is self.root, exist_ok=True)
            if d.is_symlink() or (d.exists() and not d.is_dir()):
                raise OSError(f"{d.name} is not a folder of the box")
            if make and stat.S_IMODE(d.stat().st_mode) != 0o700:
                os.chmod(d, 0o700)  # whatever the umask: the console's own user only
        return folder if folder.is_dir() else None

    @staticmethod
    def _read(p: Path, rid: str) -> dict[str, Any] | None:
        """One kept record, or None when the file is not one the box wrote for this study: not a plain file, or its
        study, SHA-256, fields or time not what its folder and name say."""
        try:
            st = p.lstat()
            if not stat.S_ISREG(st.st_mode) or not _SHA.fullmatch(p.name[:-5]) or not p.name.endswith(".json"):
                return None
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("study") != rid or d.get("file_sha256") != p.name[:-5] or d.get("registry") != "jRCT":
                return None
            rec = d["record"]
            if not isinstance(rec, dict) or set(rec) != set(rf.KEPT):
                return None
            if not all(isinstance(v, str) for v in rec.values()):
                return None
            when = _when(str(d["at"]))
            if when is None:
                return None
            return {"record": {k: rec[k] for k in rf.KEPT}, "sha": d["file_sha256"], "by": str(d["by"]),
                    "at": str(d["at"]), "when": when}  # fmt: skip
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            return None

    def keep(self, rid: str, sha: str, rec: rf.Record, by: str, at: str) -> bool:
        """Keep the record of the file ``sha``; False when that file was kept before (nothing is written);
        :class:`NotOurs` when the name is taken by something the box did not write."""
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValueError("not a SHA-256")
        folder = self._folder(rid, make=True)
        assert folder is not None
        target = folder / f"{sha}.json"
        if os.path.lexists(target):  # a dangling link counts: it is not a record
            if self._read(target, rid) is None:
                raise NotOurs(target.name)
            return False
        payload = json.dumps({"study": rid, "registry": "jRCT", "record": rec.as_dict(), "file_sha256": sha,
                              "by": by, "at": at}, ensure_ascii=False, sort_keys=True).encode("utf-8")  # fmt: skip
        tmp = folder / f".{sha}.{secrets.token_hex(8)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(fd, 0o600)  # whatever the umask
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, target)  # never replaces: the same file read twice at once is kept once
            except FileExistsError:
                if self._read(target, rid) is None:
                    raise NotOurs(target.name) from None
                return False
            return True
        finally:
            tmp.unlink(missing_ok=True)

    def records(self, rid: str) -> list[dict[str, Any]]:
        """The kept records of the study, the current one first (newest time read, compared as times); a file the box
        did not write is left out."""
        folder = self._folder(rid, make=False)
        if folder is None:
            return []
        out = [r for p in folder.iterdir() if p.name.endswith(".json") and (r := self._read(p, rid)) is not None]
        return sorted(out, key=lambda r: (r["when"], r["sha"]), reverse=True)


def register(app: FastAPI, h: Helpers, root: Path) -> None:
    au = h.au
    store = Store(root)
    app.state.registry_records = store

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def readable(sess: Session, rs: str) -> str:
        """The study state page's own check (console.study_setup), so the two pages have the same readers."""
        assert h.state_reader is not None, "console.study_setup registers first"
        return h.state_reader(sess, rs)

    def may_take(sess: Session, rid: str) -> bool:
        return bool(h.permit(sess.user, ACTION, rid).allowed)

    def takeable(sess: Session, rs: str, path: str) -> str:
        """The right first, before any byte of the body: the study as its state page reads it, then ``study.state``."""
        rid = readable(sess, rs)
        if not may_take(sess, rid):
            raise deny(sess, path)
        return rid

    def recorded_jrct(rid: str) -> str:
        try:
            return str(h.store.study_identity(rid).registry_ids.get("jrct", ""))
        except Exception:  # no study store on this box: no recorded number to compare with
            return ""

    def audit(sess: Session, rid: str, outcome: str, data: bytes | None, **more: Any) -> None:
        detail: dict[str, Any] = {"action": outcome, "file_sha256": rf.sha256(data) if data else ""}
        if data is not None:
            detail["bytes"] = len(data)
        au.append(REFUSED_EVENT if outcome == "refused" else EVENT, ruleset=rid, actor=h.actor(sess),
                  detail={**detail, **more})  # fmt: skip

    def take(sess: Session, rid: str, data: bytes) -> tuple[str, str, rf.Record | None]:
        """Read and keep one file: ``(outcome, code, record)``; outcome ``taken``, ``same`` or ``refused`` (with the
        rule's code). Audited before it returns."""
        try:
            rec = rf.read_record(data)
        except rf.Refused as exc:
            audit(sess, rid, "refused", data, code=exc.code, field=exc.field)
            return "refused", exc.code, None
        want = recorded_jrct(rid)
        if want and want.lower() != rec.id.lower():
            audit(sess, rid, "refused", data, code="other_study", jrct=rec.id)
            return "refused", "other_study", None
        sha = rf.sha256(data)
        try:
            new = store.keep(rid, sha, rec, sess.user.username, h.clock().isoformat())
        except OSError:  # the folder holds what the box did not write: nothing is kept, the administrator is told
            audit(sess, rid, "refused", data, code="store")
            return "refused", "store", None
        audit(sess, rid, "taken" if new else "same", data, jrct=rec.id, kept=",".join(rf.KEPT))
        return ("taken" if new else "same"), "", rec

    def show(request: Request, sess: Session, rid: str, status: int = 200, fe: FormErrors | None = None) -> Response:
        recs = store.records(rid)
        given = str(request.query_params.get("saved") or "")
        read = next((r for r in recs if len(given) == SHOWN_SHA and r["sha"].startswith(given)), None)
        return h.page(request, "registry_record.html", sess, status, rs=rid, fe=fe, current=recs[0] if recs else None,
                      earlier=recs[1 : 1 + EARLIER_SHOWN], can_take=may_take(sess, rid), want=recorded_jrct(rid),
                      fields=rf.KEPT, read=read, read_current=bool(read and read is recs[0]),
                      nofile=request.query_params.get("nofile") == "1")  # fmt: skip

    def failed(request: Request, sess: Session, rid: str, code: str) -> Response:
        fe = FormErrors(FORM, FORM, (FieldError(FIELD, f"rrec.err.{code}"),))
        return show(request, sess, rid, FAILED, fe)

    @app.get("/studies/{rs}/registry-record")
    def registry_record_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        return show(request, sess, readable(sess, rs))

    @app.get("/api/v1/studies/{rs}/registry-record")
    def api_registry_record(request: Request, rs: str) -> dict[str, Any]:
        assert h.api_session is not None
        sess = h.api_session(request)
        rid = readable(sess, rs)
        recs = store.records(rid)

        def one(r: dict[str, Any]) -> dict[str, Any]:
            return {"record": r["record"], "file_sha256": r["sha"], "by": r["by"], "at": r["at"]}

        return {"study": rid, "current": one(recs[0]) if recs else None, "earlier": [one(r) for r in recs[1:]]}

    @app.post("/studies/{rs}/registry-record")
    async def registry_record_take(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = takeable(sess, rs, request.url.path)
        demo_guard.guard(request, h.problem)  # T-502: no upload in demo mode
        try:
            await read_capped(request)
        except TooLarge:  # refused unread: the only thing written is the audit line
            audit(sess, rid, "refused", None, code="too_large", more_than=BODY_MAX)
            return failed(request, sess, rid, "too_large")
        try:
            form = await request.form(max_files=1, max_fields=16)
        except StarletteHTTPException:  # two file parts, too many fields, a part too large: nothing read
            audit(sess, rid, "refused", None, code="bad_form")
            return failed(request, sess, rid, "bad_form")
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        up = form.get(FIELD)
        if up is None:  # no file field at all (not a browser's form): nothing to read
            audit(sess, rid, "refused", None, code="no_file")
            return RedirectResponse(f"/studies/{rid}/registry-record?nofile=1", status_code=303)
        if not isinstance(up, UploadFile) or not up.filename:
            audit(sess, rid, "refused", None, code="no_file")
            return failed(request, sess, rid, "no_file")
        data = await up.read(rf.MAX_BYTES + 1)
        outcome, code, _rec = take(sess, rid, data)
        if outcome == "refused":
            return failed(request, sess, rid, code)
        return RedirectResponse(f"/studies/{rid}/registry-record?saved={rf.sha256(data)[:SHOWN_SHA]}", status_code=303)

    def first(sess: Session, request: Request) -> None:
        takeable(sess, request.path_params["rs"], request.url.path)

    @app.post("/api/v1/studies/{rs}/registry-record")
    @before_body(first)
    async def api_registry_record_take(request: Request, rs: str) -> dict[str, Any]:
        assert h.api_session is not None
        sess = h.api_session(request)
        rid = takeable(sess, rs, request.url.path)
        demo_guard.guard(request, h.problem)
        ctype = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if ctype != "text/csv":  # before a byte of the body is read
            audit(sess, rid, "refused", None, code="api_type")
            raise h.problem(415, "request.refused", reason=translate(sess.lang, "rrec.err.api_type"))
        try:
            data = await read_capped(request)
        except TooLarge:
            audit(sess, rid, "refused", None, code="too_large", more_than=BODY_MAX)
            raise h.problem(413, "request.refused", reason=translate(sess.lang, "rrec.err.too_large")) from None
        outcome, code, rec = take(sess, rid, data)
        if outcome == "refused" or rec is None:
            raise h.problem(400, "request.refused", reason=translate(sess.lang, f"rrec.err.{code}"))
        return {"study": rid, "outcome": outcome, "file_sha256": rf.sha256(data), "record": rec.as_dict()}
