"""The ten pages of the console timing walk (D-1245, card 10E-13) on the console test box, synthetic data only.

Picked from the life-cycle walks (``tests/e2e/life_cycle_walk_plan.py``: the weekly page, the patient sheet, the
candidates, the participants, the study's state, a job page, the audit trail, the administrator's Health tab) and from
review 13's list (the home page, the protocol upload): the pages a coordinator opens every working day, the two the
review named for their waits, and one each for the privacy officer and the administrator. Each is opened by an account
that may open it (a ``200``), so the walk times served pages, never a refusal."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_screen, _ulid, login
from tests.console.test_role_pages import PW, _user
from tools.console_timing import Answer, Page

PID = "a" * 32  # the synthetic patient of the finished screening run (``_done_screen``)
JOB = _ulid(900)

#: (name, path, account): the account is a role of the test box
TEN: tuple[tuple[str, str, str], ...] = (
    ("home", "/home", "coordinator"),
    ("week", "/studies/GZQO/week", "coordinator"),
    ("patient sheet", f"/studies/GZQO/patients/{PID}", "coordinator"),
    ("candidates", "/studies/GZQO/candidates", "coordinator"),
    ("participants", "/studies/GZQO/subjects", "coordinator"),
    ("study state", "/studies/GZQO/state", "coordinator"),
    ("job page", f"/pilot/jobs/{JOB}", "coordinator"),
    ("protocol upload", "/pilot/protocol", "coordinator"),
    ("audit trail", "/audit", "privacy"),
    ("health tab", "/admin/ops", "admin"),
)


def getter(c: TestClient) -> Any:
    def get(path: str) -> Answer:
        r = c.get(path, follow_redirects=False)
        return r.status_code, r.headers

    return get


def clients(box: dict[str, Any]) -> dict[str, TestClient]:
    """One signed-in client per role of the walk, and the finished screening run its job page opens."""
    if JOB not in box["backend"].jobs:
        _done_screen(box["backend"], JOB)
    out: dict[str, TestClient] = {}
    for role in ("coordinator", "privacy"):
        name = f"tw-{role[:5]}"
        out[role] = login(box["app"], name, PW)[0] if box["users"].get(name) else _user(box, name, role)
    out["admin"], _ = login(box["app"])
    return out


def ten_pages(box: dict[str, Any]) -> list[Page]:
    cs = clients(box)
    return [Page(name, path, getter(cs[who])) for name, path, who in TEN]
