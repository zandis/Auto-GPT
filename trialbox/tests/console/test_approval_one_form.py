"""HOLISTIC-3 lane H fix 2 (H3-UX §4 fix 2): the approval page is one form. The coordinator gives the 20 short labels
of a Japanese page in one POST (was 20 reloads); the PI records every amber row read and every codes tick in one POST
(was one GET per amber row and one POST per tick). Each criterion keeps its own record and audit event, as the
one-row routes write them, and Approve all still waits for every amber row (D-146, D-309, D-120). Synthetic data."""

from __future__ import annotations

import re
from typing import Any

from console.backend import read_audit

import tests.console.test_console_app as _app
from tests.console.test_criterion_labels import _approval_job, _gzqo_rows

box = _app.box  # the fixture, found by name
login, name_pi = _app.login, _app.name_pi
PW = "approval-one-form-password-01"
IDS = [f"GZQO-INC-{n}" for n in range(31, 51)]
N = len(IDS)  # 20 criteria with no shipped label
AMBER = IDS[:6]  # left to a person at screening: amber


def _rows() -> list[tuple[Any, ...]]:
    return [(i, "inclusion", "human" if i in AMBER else "structured", f"Example criterion {i[-2:]}.", "VS_X: 1 one",
             100, None) for i in IDS]  # fmt: skip


def _events(box: dict[str, Any], event: str) -> list[dict[str, Any]]:
    return [dict(r.detail or {}) for r in read_audit(box["dir"] / "audit") if r.event == event]


def _page_and_csrf(c: Any, job_id: str) -> tuple[str, str]:
    page = c.get(f"/pilot/jobs/{job_id}/approval").text
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return page, m.group(1)


def test_the_coordinator_gives_twenty_labels_in_one_post(box: dict[str, Any]) -> None:
    job = _approval_job(box, _rows())
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    c, csrf = login(box["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    page, csrf = _page_and_csrf(c, job.job_id)
    assert all(f'data-testid="label-missing-{i}"' in page for i in IDS)
    assert "/approval/label" not in page and "/approval/tick" not in page  # no one-row form is left on the page
    assert page.count('action="/pilot/jobs/' + job.job_id + '/approval/save"') == 1
    data = {
        "csrf": csrf,
        "label_lang": "ja",
        "label_id": IDS,
        "label_text": [f"基準{i[-2:]}" for i in IDS],
        "label_was": [""] * N,
    }
    r = c.post(f"/pilot/jobs/{job.job_id}/approval/save", data=data, follow_redirects=False)
    assert r.status_code == 303
    page = c.get(r.headers["location"]).text
    assert "label-missing-" not in page and 'data-testid="site-label-GZQO-INC-31">基準31' in page
    got = _events(box, "console.criterion_label")
    assert sorted(e["action"] for e in got) == sorted(IDS)  # one event per criterion, as before
    # the coordinator neither ticks nor records an amber row read: refused, nothing written
    r = c.post(f"/pilot/jobs/{job.job_id}/approval/save", data={"csrf": csrf, "tick": IDS[:1]})
    assert r.status_code == 403 and not _events(box, "console.code_tick")


def test_an_unchanged_label_is_not_saved_again(box: dict[str, Any]) -> None:
    """A pre-filled label submitted as it is stays the ruleset's (shipped); only what the person changed is saved."""
    job = _approval_job(box, _gzqo_rows("GZQO-INC-01", "GZQO-EXC-01"))
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    c, csrf = login(box["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    page, csrf = _page_and_csrf(c, job.job_id)
    assert 'value="18歳以上"' in page and 'data-testid="label-shipped-GZQO-INC-01"' in page
    ids, shown = ["GZQO-INC-01", "GZQO-EXC-01"], ["18歳以上", ""]
    data = {
        "csrf": csrf,
        "label_lang": "ja",
        "label_id": ids,
        "label_text": ["18歳以上", "別の表示名"],
        "label_was": shown,
    }
    page = c.post(f"/pilot/jobs/{job.job_id}/approval/save", data=data).text
    assert 'data-testid="label-shipped-GZQO-INC-01"' in page
    assert [e["action"] for e in _events(box, "console.criterion_label")] == ["GZQO-EXC-01"]


def test_the_pi_records_amber_rows_and_ticks_in_one_post_then_approves(box: dict[str, Any]) -> None:
    job = _approval_job(box, _rows())
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")
    p, _ = login(box["app"], "pi", PW)
    page, csrf = _page_and_csrf(p, job.job_id)
    assert all(f'data-testid="open-{i}"' in page for i in AMBER) and 'data-testid="approve-missing"' in page
    assert all(f'data-testid="tick-btn-{i}"' in page for i in IDS)
    # an amber row is read inside its own disclosure: the box that records it is only reachable once it is opened
    for i in AMBER:
        row = page[page.index(f'<tr id="{i}"') :]
        row = row[: row.index("</tr>")]
        inside = row[row.index('<details class="codes"') : row.index("</details>")]
        assert f'data-testid="open-{i}"' in inside
    data = {"csrf": csrf, "opened": AMBER, "tick": IDS}
    r = p.post(f"/pilot/jobs/{job.job_id}/approval/save", data=data, follow_redirects=False)
    assert r.status_code == 303
    page = p.get(r.headers["location"]).text
    assert 'data-testid="approve-missing"' not in page and "tick-btn-" not in page
    opened = _events(box, "console.approval_open")
    assert sorted(e["action"] for e in opened) == sorted(AMBER)
    assert all(e["reason"] == "person" for e in opened)  # why the row was amber, as the GET wrote it
    assert sorted(e["action"] for e in _events(box, "console.code_tick")) == sorted(IDS)
    r = p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 200 and 'data-testid="confirm-text"' in r.text  # the confirmation step comes next


def test_approve_still_waits_for_every_amber_row(box: dict[str, Any]) -> None:
    job = _approval_job(box, _rows())
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")
    p, _ = login(box["app"], "pi", PW)
    _, csrf = _page_and_csrf(p, job.job_id)
    p.post(f"/pilot/jobs/{job.job_id}/approval/save", data={"csrf": csrf, "opened": AMBER[:5], "tick": IDS})
    page, _ = _page_and_csrf(p, job.job_id)
    assert 'data-testid="approve-missing"' in page and '<button type="button" disabled' in page
    assert p.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": csrf}).status_code == 409
    # a non-amber row sent as "opened" records nothing; an id not in the round refuses the whole form
    p.post(f"/pilot/jobs/{job.job_id}/approval/save", data={"csrf": csrf, "opened": [IDS[10]]})
    assert IDS[10] not in [e["action"] for e in _events(box, "console.approval_open")]
    r = p.post(f"/pilot/jobs/{job.job_id}/approval/save", data={"csrf": csrf, "opened": [AMBER[5], "GZQO-INC-99"]})
    assert r.status_code == 404 and AMBER[5] not in [e["action"] for e in _events(box, "console.approval_open")]
    assert p.post(f"/pilot/jobs/{job.job_id}/approval/save", data={"csrf": "x", "tick": IDS[:1]}).status_code == 400


def test_a_label_saved_in_another_tab_or_language_is_not_written_over(box: dict[str, Any]) -> None:
    """Review R1, R2: the page's labels are compared with the values it was shown with, in the language it was shown
    in; a label nobody touched on this page is never written, and a page shown in another language is refused."""
    job = _approval_job(box, _rows())
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    c, csrf = login(box["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    _, csrf = _page_and_csrf(c, job.job_id)
    one = {"csrf": csrf, "label_lang": "ja", "label_id": IDS[:1], "label_was": [""]}
    c.post(f"/pilot/jobs/{job.job_id}/approval/save", data={**one, "label_text": ["新しい表示名"]})  # the other tab
    stale = {**one, "label_was": ["旧い表示名"], "label_text": ["旧い表示名"]}  # shown before, not touched
    assert c.post(f"/pilot/jobs/{job.job_id}/approval/save", data=stale, follow_redirects=False).status_code == 303
    page, _ = _page_and_csrf(c, job.job_id)
    assert f'data-testid="site-label-{IDS[0]}">新しい表示名' in page
    assert len(_events(box, "console.criterion_label")) == 1
    r = c.post(f"/pilot/jobs/{job.job_id}/approval/save", data={**one, "label_lang": "zh-TW", "label_text": ["別"]})
    assert r.status_code == 409 and len(_events(box, "console.criterion_label")) == 1
    # untouched labels from a page shown in another language do not hold up the rest of the form
    r = c.post(f"/pilot/jobs/{job.job_id}/approval/save", data={**stale, "label_lang": "zh-TW"}, follow_redirects=False)
    assert r.status_code == 303


def test_a_second_edit_from_the_same_starting_label_does_not_overwrite_the_first(box: dict[str, Any]) -> None:
    """Review R1: two staff edit one label from the same shown value; the second save is told, not written."""
    job = _approval_job(box, _rows())
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    c, csrf = login(box["app"], "crc", PW)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"})
    _, csrf = _page_and_csrf(c, job.job_id)
    form = {"csrf": csrf, "label_lang": "ja", "label_id": IDS[:1], "label_was": [""]}
    c.post(f"/pilot/jobs/{job.job_id}/approval/save", data={**form, "label_text": ["最初の表示名"]})
    r = c.post(f"/pilot/jobs/{job.job_id}/approval/save", data={**form, "label_text": ["二番目の表示名"]},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].endswith("done=conflict")
    page, _ = _page_and_csrf(c, job.job_id)
    assert f'data-testid="site-label-{IDS[0]}">最初の表示名' in page and 'data-testid="approval-conflict"' not in page
    assert len(_events(box, "console.criterion_label")) == 1


def test_the_one_form_has_an_api_twin(box: dict[str, Any]) -> None:
    """FIT-019: the page action's /api/v1 twin records the same, criterion by criterion, and refuses the same."""
    from fastapi.testclient import TestClient

    job = _approval_job(box, _rows())
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "pi", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    r = api.post(f"/api/v1/jobs/{job.job_id}/approval/save", json={"opened": AMBER, "tick": IDS[:2]}, headers=hdr)
    assert r.status_code == 200 and r.json()["recorded"] == {"opened": 6, "labels": 0, "ticks": 2}
    assert sorted(e["action"] for e in _events(box, "console.approval_open")) == sorted(AMBER)
    r = api.post(f"/api/v1/jobs/{job.job_id}/approval/save", json={"tick": ["GZQO-INC-99"]}, headers=hdr)
    assert r.status_code == 404
    assert api.post(f"/api/v1/jobs/{job.job_id}/approval/save", json={"opened": AMBER}).status_code == 401
    # review: one id as a string is one id; a label without the value it was shown with is not an edit
    r = api.post(f"/api/v1/jobs/{job.job_id}/approval/save", json={"tick": IDS[2]}, headers=hdr)
    assert r.status_code == 200 and r.json()["recorded"]["ticks"] == 1
