"""D-1158, the review: the note typed with a lifecycle undo (``life.step``, source ``undo``) reaches the data core's
chain masked; the step row itself keeps what was typed (it is not the chain). Synthetic values only."""

from __future__ import annotations

from typing import Any

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_reason_for_change_and_append_only_trails import _events

CHART = "".join(("7", "0", "0", "0", "4", "2", "1", "9"))
MAIL = "synthia.testperson" + "@" + "example.invalid"


def test_the_undo_note_is_masked_in_the_chain(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    assert 'data-testid="life-saved"' in r.text, r.text[-800:]
    r = lb["oc"].post(f"/studies/GZQO/subjects/{no}/undo", json={"note": f"wrong patient, chart {CHART}, mail {MAIL}"})
    assert r.status_code == 200, r.text
    ev = [e for e in _events(lb, "life.step") if e["detail"].get("source") == "undo"]
    assert ev and ev[-1]["detail"]["reason"].startswith("wrong patient, chart ")
    assert CHART not in str(ev) and MAIL not in str(ev), ev[-1]["detail"]
