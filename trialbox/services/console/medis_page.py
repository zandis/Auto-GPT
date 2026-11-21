"""The MEDIS disease-name master step of site set-up (card 10B-22, D-1261): ``/site/codes/medis``.

MEDIS-DC's standard disease-name master is free for a medical institution and may not be passed on without MEDIS's
permission, so TrialBox never ships it. On a site whose country layer uses it (``sitesetup.medis_release.applies``),
this page lets a person of the hospital load it, and later load a newer release the same way:

1. what the master is and why the box needs it, in plain words, with links to MEDIS's download page and its terms
   (opened by the person; the box never fetches them), and what skipping it means;
2. the zip the person downloaded, chosen in the browser (the upload pattern of the other set-up pages: the file is
   read into memory up to a hard cap and sent to the orchestrator; ``sitesetup.medis_release.vet`` caps the members
   and their sizes, reads only the tables by base name, writes and runs nothing);
3. the box reads the release without loading it and shows the version, the release date, the rows of each table
   and the first lines it would leave out and why; the orchestrator records who read which zip, and when;
4. the person ticks the approval (their institution downloaded this release from MEDIS and may use it under MEDIS's
   terms), with their name taken from their sign-in, and chooses the same file again: the console checks that the
   file's SHA-256 is the one on the page, and the orchestrator loads only a zip the same person read in the last
   30 minutes;
5. the load (one transaction, the Load button sent once) and the result; the page then shows the loaded version and
   date, and a reminder when the release is more than seven months old.

The orchestrator writes the audit (``terminology.load``, the event every licensed load writes) with the verified
person: the approval before the load starts, then the result. Who may open the page: the account that changes site
set-up (the matrix row ``site.setup``), answered as ``POST /site/codes`` answers every other account. On a site whose
country layer does not use the master the routes are not registered and every other page is as before.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import FastAPI, Request, Response
from sitesetup import medis_release

from console import demo_guard
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import CATALOGUES
from console.i18n_medis import EN, JA, ZH
from console.timefmt import local_date, site_zone

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

PATH = "/site/codes/medis"
MB = medis_release.MAX_ZIP // (1024 * 1024)
SKIPPED_SHOWN = 50


def state(terms: list[dict[str, Any]], last: dict[str, Any], today: date, zone: Any = None) -> dict[str, Any] | None:
    """The disease-name table as the terminology store says it is loaded (version, rows, when) with the release
    date and the approving person of the step's last load (``last``, when it is the same version), and whether the
    reminder is due; None when it is not loaded."""
    row = medis_release.loaded(terms)
    if row is None:
        return None
    version = str(row.get("version") or "")
    same = str(last.get("version") or "") == version
    released = str(row.get("released") or (last.get("released") if same else "") or "")
    return {
        "version": version,
        "released": released[:10] or "–",
        "dated": bool(released[:10]),  # lane J, L1: a release with no date is said, never silently not reminded
        # lane J, L2: the day of the site, not of UTC
        "day": local_date(row.get("loaded_at"), zone) if zone is not None else str(row.get("loaded_at") or "")[:10],
        "who": str(row.get("loaded_by") or (last.get("by") if same else "") or ""),
        "codes": int(row.get("rows") or 0),  # lane J, L3: exchange codes (concepts) and the table's rows, each named
        "rows": int(row.get("table_rows") or row.get("rows") or 0),
        "remind": medis_release.reminder(released, today),
    }


def register(
    app: FastAPI,
    h: Helpers,
    *,
    need_change: Callable[[Session, str], None],
    signed_post: Callable[[Session, str, dict[str, Any]], Any],
    get: Callable[[str], Any],
) -> None:
    """The step's routes, under the guards of ``console.site_pages`` (``need_change``: the set-up row)."""

    def page(request: Request, sess: Session, status: int = 200, **more: Any) -> Response:
        terms: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        try:
            terms = list(get("/setup/terminology"))
            last = dict(get("/setup/terminology/medis"))
        except (Problem, Unavailable):
            pass
        loaded = state(terms, last, h.today(), site_zone(h.bk))
        return h.page(request, "site_medis.html", sess, status, mb=MB, loaded=loaded,
                      download_url=medis_release.DOWNLOAD_URL, terms_url=medis_release.TERMS_URL,
                      who=h.actor(sess), shown=SKIPPED_SHOWN, **more)  # fmt: skip

    def refused(request: Request, sess: Session, code: str, reason: str = "") -> Response:
        return page(request, sess, 422, err={"code": code[:60], "reason": reason[:300]})

    async def read_file(request: Request, sess: Session) -> tuple[dict[str, Any], bytes | None, str | None]:
        """The posted form, its zip (at most the cap) or the refusal's code."""
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        up = form.get("file")
        if up is None or isinstance(up, str) or not getattr(up, "filename", None):
            return dict(form), None, "LIC-UPLOAD-EMPTY"
        data = await up.read(medis_release.MAX_ZIP + 1)
        if len(data) > medis_release.MAX_ZIP:
            return dict(form), None, "LIC-UPLOAD-SIZE"
        if not data:
            return dict(form), None, "LIC-UPLOAD-EMPTY"
        return dict(form), data, None

    def send(sess: Session, path: str, data: bytes, **more: Any) -> dict[str, Any]:
        return dict(signed_post(sess, path, {"b64": base64.b64encode(data).decode("ascii"), **more}))

    @app.get(PATH)
    def medis(request: Request) -> Response:
        sess = h.need(request)
        need_change(sess, PATH)
        return page(request, sess)

    @app.post(f"{PATH}/check")
    async def medis_check(request: Request) -> Response:
        sess = h.need(request)
        need_change(sess, PATH)
        demo_guard.guard(request, h.problem)  # no upload in demo mode
        _form, data, bad = await read_file(request, sess)
        if bad or data is None:
            return refused(request, sess, bad or "LIC-UPLOAD-EMPTY")
        try:
            found = send(sess, "/setup/terminology/medis/check", data)
        except Problem as exc:
            return refused(request, sess, exc.code, exc.message)
        except Unavailable:
            return refused(request, sess, "unavailable")
        return page(request, sess, found=found)

    @app.post(f"{PATH}/load")
    async def medis_load(request: Request) -> Response:
        sess = h.need(request)
        need_change(sess, PATH)
        demo_guard.guard(request, h.problem)
        form, data, bad = await read_file(request, sess)
        if bad or data is None:
            return refused(request, sess, bad or "LIC-UPLOAD-EMPTY")
        if str(form.get("approved") or "") != "yes":
            return refused(request, sess, "LIC-APPROVAL")
        if hashlib.sha256(data).hexdigest() != str(form.get("sha256") or ""):
            return refused(request, sess, "LIC-UPLOAD-CHANGED")
        try:
            again = str(form.get("again") or "") == "yes"  # D-1261: a second load of the release in use, asked for
            done = send(sess, "/setup/terminology/medis/load", data, approved=True, again=again)
        except Problem as exc:
            return refused(request, sess, exc.code, exc.message)
        except Unavailable:
            return refused(request, sess, "unavailable")
        return page(request, sess, done=done)
