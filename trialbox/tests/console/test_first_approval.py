"""NEW-JRN-1 (JRN-001, D-540): a new study gets its first approval through the console.

A study whose protocol was just read has a job waiting for approval and no ruleset folder yet. The steward must be
able to open its delegation log and name the PI (D-380), the PI must be told what is missing, and then the PI
approves: every step through a page, none through ``TeamStore`` (the tests and demos used to write the PI entry
into the database, so nothing caught that no page could).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import STW_PW, _ulid, box, login, review_book  # noqa: F401 - fixture by name
from tests.console.test_role_pages import _csrf, _user

NEW = "NEWRA"  # a study the box has no ruleset folder for


def _waiting(b: dict[str, Any], n: int, rs: str = NEW) -> str:
    book = review_book([(f"{rs}-INC-01", "inclusion", "structured", "Age 18 or over.", None, 100, None)])
    jid = _ulid(n)
    key = f"outputs/{jid}/review_{rs}_v1.0.0_r1.xlsx"
    b["backend"].objects[key] = book
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    out = JobOutput(filename=f"review_{rs}_v1.0.0_r1.xlsx", sha256=sha256_bytes(book), minio_key=key, recipients=[],
                    tag="aggregate")  # fmt: skip
    b["backend"].add_job(Job(job_id=jid, type="FEAS", ruleset=rs, ruleset_version="1.0.0",
                             requested_by="admin@hospa.test", received_at=now, updated_at=now,
                             state="awaiting_approval", options={}, outputs=[out]))  # fmt: skip
    return jid


def test_a_new_study_goes_from_waiting_to_approved_through_the_pages(box: dict[str, Any]) -> None:  # noqa: F811
    assert all(r.id != NEW for r in box["backend"].rulesets())  # the study has no ruleset folder yet
    jid = _waiting(box, 971)
    pi = _user(box, "drsato", "investigator")
    box["users"].create("stw1", "steward", STW_PW, "stw1@hospa.test")
    stw, _ = login(box["app"], "stw1", STW_PW)

    # the PI is told what is missing, and has no approve control yet
    page = pi.get(f"/pilot/jobs/{jid}/approval")
    assert page.status_code == 200
    assert 'data-testid="approve-needs-pi"' in page.text and 'data-testid="approve"' not in page.text
    assert pi.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page.text)}).status_code == 403

    # the steward sees the task on their own pages and opens the study's delegation log
    home = stw.get("/site/staff")
    assert home.status_code == 200 and f'data-testid="task-name-pi-{NEW}"' in home.text
    assert f'href="/studies/{NEW}/team"' in home.text
    log = stw.get(f"/studies/{NEW}/team")
    assert log.status_code == 200, log.text[-300:]
    r = stw.post(f"/studies/{NEW}/team", data={"csrf": _csrf(log.text), "username": "drsato", "role": "pi",
                                               "start": "2026-01-01", "training_day": "2025-06-01"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    assert f'data-testid="task-name-pi-{NEW}"' not in stw.get("/site/staff").text  # the task is done

    # the PI now approves
    page = pi.get(f"/pilot/jobs/{jid}/approval")
    assert 'data-testid="approve"' in page.text and 'data-testid="approve-needs-pi"' not in page.text
    r = pi.post(f"/pilot/jobs/{jid}/approval/tick", data={"csrf": _csrf(page.text), "crit": f"{NEW}-INC-01"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code in (200, 303), r.text[-300:]
    r = pi.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page.text)}, follow_redirects=False)
    assert r.status_code == 200, r.text[-300:]  # P-10: the consequence first
    r = pi.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page.text), "confirm": "yes"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    assert [(req.type, req.ruleset) for req in box["backend"].created] == [("APPROVE", NEW)]


def test_a_study_nobody_asked_for_is_still_unknown(box: dict[str, Any]) -> None:  # noqa: F811
    """D-133 stays: a mistyped code gets the 404 page, and a study is not made known by a finished or failed job."""
    box["users"].create("stw1", "steward", STW_PW, "stw1@hospa.test")
    stw, _ = login(box["app"], "stw1", STW_PW)
    assert stw.get("/studies/NOSUCH/team").status_code == 404
    jid = _waiting(box, 972, "GONE")
    box["backend"].jobs[jid] = box["backend"].jobs[jid].model_copy(update={"state": "rejected"})
    assert stw.get("/studies/GONE/team").status_code == 404
    assert 'data-testid="task-name-pi-GONE"' not in stw.get("/site/staff").text


def test_only_the_steward_sees_the_task_and_other_roles_get_no_new_page(box: dict[str, Any]) -> None:  # noqa: F811
    _waiting(box, 973)
    crc = _user(box, "crc9", "coordinator")
    smo = _user(box, "smo9", "coordinator", affiliation="smo", studies="GZQO")
    for c in (crc, smo):
        assert f'data-testid="task-name-pi-{NEW}"' not in c.get("/home").text
    assert smo.get(f"/studies/{NEW}/team").status_code == 404  # another study than its own: as before


def test_the_log_says_when_no_investigator_account_can_open_the_study(box: dict[str, Any]) -> None:  # noqa: F811
    """What a rehearsal saw: the PI's account was limited to other studies, so the approval page was 404 for the PI
    (D-104, as it must be) and the steward had nobody to name. The log now says what the administrator must do."""
    jid = _waiting(box, 974)
    scoped = _user(box, "drkato", "investigator", affiliation="hospital", studies="GZQO")
    assert scoped.get(f"/pilot/jobs/{jid}/approval").status_code == 404
    box["users"].create("stw1", "steward", STW_PW, "stw1@hospa.test")
    stw, _ = login(box["app"], "stw1", STW_PW)
    log = stw.get(f"/studies/{NEW}/team").text
    assert 'data-testid="pi-no-account"' in log and 'value="drkato"' not in log
    _user(box, "drsato", "investigator")  # an investigator account that sees every study
    log = stw.get(f"/studies/{NEW}/team").text
    assert 'data-testid="pi-no-account"' not in log and 'value="drsato"' in log


def test_a_scoped_coordinator_is_told_why_a_new_study_is_refused(box: dict[str, Any]) -> None:  # noqa: F811
    """The rehearsal: a study-scoped coordinator posting a protocol for a new study got "this page does not exist".
    It is a refusal of the request, with the reason, and the same answer for a study that exists (no leak)."""
    smo = _user(box, "smo9", "coordinator", affiliation="smo", studies="GZQO")
    page = smo.get("/pilot/request").text
    for rs in (NEW, "RA-BIO"):  # a study the box does not have, and one it has
        r = smo.post("/pilot/request", data={"csrf": _csrf(page), "kind": "FEAS", "ruleset": rs})
        assert r.status_code == 403, (rs, r.status_code)
        assert "limited to its own studies (GZQO)" in r.text and "does not exist" not in r.text
    assert box["backend"].created == []
