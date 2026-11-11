"""``/data/items``: the clinical item catalogue for the data steward (T-107, WS-04.1, D-353).

The data steward (D-380; the administrator before) sees every item of ``catalogue/items.csv`` grouped by specialty,
in the page's language (English, Japanese or Traditional Chinese names): its id, type, unit, code (LOINC, or the local
TrialBox concept id), what a site may store (``storable``), whether the code was checked and how well it fits, and
whether the code may ever exclude a patient (``may_exclude``; unknown never excludes). ``?specialty=RHEU`` shows one
specialty. Anyone else gets 403 and a ``console.denied`` audit event. A catalogue that cannot be read (missing, or a
file that breaks the id rules) is a 503 page, never a 500.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from tb_common import catalogue
from tb_common.authz import permit

from console import i18n_items
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.items")

for _lang, _cat in (("en", i18n_items.EN), ("ja", i18n_items.JA), ("zh-TW", i18n_items.ZH)):
    CATALOGUES[_lang].update(_cat)

GENERAL = "GEN"  # items every specialty uses (vital signs, demographics); not a row of specialties.csv


def sections(spec: str = "") -> list[dict[str, Any]]:
    """One section per specialty (file order, the general items first), each with its items in file order."""
    items = catalogue.items()
    order = [{"id": GENERAL, "names": {}}] + [{"id": s["id"], "names": s} for s in catalogue.specialties()]
    out = []
    for s in order:
        if spec and s["id"] != spec:
            continue
        rows = [i for i in items if s["id"] in i.specialties]
        if rows:
            out.append({**s, "items": rows})
    return out


def register(app: FastAPI, h: Helpers) -> None:
    @app.get("/data/items", response_class=HTMLResponse)
    def items_view(request: Request, specialty: str = "") -> Response:
        sess = h.need(request)
        if not permit(sess.user.role, "items.view"):  # D-380: the steward's page (T-102a found it the admin's)
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        spec = specialty.strip().upper()[:8]
        try:
            all_sections = sections()
            total = len(catalogue.items())
        except (OSError, catalogue.CatalogueError) as e:
            log.warning("catalogue unreadable on /data/items (%s: %s)", type(e).__name__, e)
            raise h.problem(503, "items.err.catalogue") from e
        known = [s["id"] for s in all_sections]
        if spec and spec not in known:
            raise h.problem(404, "notfound")
        shown = [s for s in all_sections if not spec or s["id"] == spec]
        return h.page(request, "items.html", sess, sections=shown, specialties=all_sections, spec=spec, total=total)
