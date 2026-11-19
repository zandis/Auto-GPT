# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""9g-19 (D-1370): the idle warning's ``keep=1`` is honoured on the two stay pages only (``console.app.STAY_PAGES``).
On every other GET route the parameter changes nothing: the same status and the same audit lines (a refusal's
``console.denied`` included) with and without it, so it is no way past a route's own checks and no existence oracle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from console.app import STAY_PAGES
from fastapi.routing import APIRoute

from tests.console.test_console_app import VIEWER_PW, _done_screen, _ulid, box, login  # noqa: F401 - the fixture
from tests.console.test_role_route_matrix import _fill

PW = "keep-walk-password-01"


def _lines(audit_dir: Path) -> list[str]:
    out: list[str] = []
    for f in sorted(audit_dir.glob("*.jsonl")):
        out += [x for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


def _shape(line: str) -> tuple[str, str, str]:
    """An audit line without its times and chain fields: what was recorded, by whom, about what."""
    e = json.loads(line)
    detail = {k: v for k, v in (e.get("detail") or {}).items() if k not in ("at", "ts", "until")}
    return str(e.get("event")), str(e.get("actor")), json.dumps(detail, sort_keys=True)


def test_keep_changes_nothing_on_any_page_but_the_two_stay_pages(box: dict[str, Any]) -> None:
    users = box["users"]
    users.create("crc", "coordinator", PW, "crc@hospa.test")
    job_id = _ulid(990)
    _done_screen(box["backend"], job_id)
    audit_dir: Path = box["backend"].audit_dir
    routes = sorted({r.path for r in box["app"].routes if isinstance(r, APIRoute) and "GET" in (r.methods or ())})
    assert len(routes) > 150 and {"/help", "/"} == STAY_PAGES
    differ = []
    stay = {}
    for name, pw in (("viewer", ""), ("crc", PW)):
        c, _ = login(box["app"], name, pw or VIEWER_PW)
        for path in routes:
            if path in ("/logout",):
                continue
            url = _fill(path, job_id)
            got = []
            for suffix in ("", "&keep=1" if "?" in url else "?keep=1"):
                before = len(_lines(audit_dir))
                r = c.get(url + suffix, follow_redirects=False)
                got.append((r.status_code, [_shape(x) for x in _lines(audit_dir)[before:]]))
            if path in STAY_PAGES:
                stay[(name, path)] = got[1][0]
            elif got[0] != got[1]:
                differ.append((name, path, got[0][0], got[1][0]))
    assert not differ, differ
    assert set(stay.values()) == {204}, stay  # the stay pages answer the warning with its times


def test_another_studys_job_and_no_job_are_both_404_with_or_without_keep(box: dict[str, Any]) -> None:
    """D-104: for an account scoped to another study, a job of a study it does not have and a job that does not exist
    answer the same, with or without keep=1."""
    users = box["users"]
    users.create("smo", "coordinator", PW, "smo@hospa.test")
    users.set_scope("smo", "smo", "OTHR", None)
    job_id = _ulid(991)
    _done_screen(box["backend"], job_id)  # a GZQO job
    c, _ = login(box["app"], "smo", PW)
    for jid in (job_id, _ulid(992)):
        for q in ("", "?keep=1"):
            assert c.get(f"/pilot/jobs/{jid}{q}", follow_redirects=False).status_code == 404, (jid, q)
