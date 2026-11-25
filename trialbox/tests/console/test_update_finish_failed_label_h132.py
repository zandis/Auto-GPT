"""H-132 (LR-10, D-1460): the audit page shows the label of ``update.finish_failed`` in every shipped language.

An update cut short after its check that could not be finished forward is audited ``update.finish_failed``; the
integrator's ruling 7140759290 asks that the audit page show its label, not the bare code alone."""

from __future__ import annotations

import re
from typing import Any

from console import i18n_audit

from tests.console.test_audit_browser import _dpo
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf

EVENT = "update.finish_failed"


def test_the_audit_page_shows_the_label_of_an_update_not_finished(box: dict[str, Any]) -> None:  # noqa: F811
    box["audit"].append(EVENT, actor="update", detail={"bundle_id": "synthetic-1", "interrupted_at": "refdata",
                                                       "next": "tools/apply_update.sh rollback synthetic-1"})  # fmt: skip
    dpo = _dpo(box)
    for i, lang in enumerate(("en", "ja", "zh-TW")):
        dpo.post("/lang", data={"csrf": _csrf(dpo.get("/audit").text), "lang": lang, "back": "/audit"})
        page = dpo.get("/audit", params={"event": EVENT}).text
        assert re.findall(r'<tr data-event="([^"]+)">', page) == [EVENT], lang
        label = i18n_audit.EVENTS[EVENT][i]
        assert label and label in page, lang  # the label in the page's language, beside the code
