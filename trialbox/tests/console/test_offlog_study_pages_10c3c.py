"""Card 10C-3c (D-1258), gap 3 and the sweep: a study's job, approval, state, feasibility, set-up, forms, sources, IRB,
consent-form and delegation-log pages, and their ``/api/v1`` twins, for an investigator off the study's log.

Synthetic data only. The owner decided on 2026-11-19 (recorded on PR #1239): an investigator who is not on a study's
delegation log is refused every one of these 14 routes of that study, as its week and patient pages are refused;
the break-glass grant on the job page stays. The check is ``Helpers.on_log`` (D-147's ``Helpers.delegated`` with any
study task). The page answers 403 (``problem.html``) and the API its own JSON refusal (D-125), each with one
``console.denied`` row. The PI, a sub-investigator on the log (whatever task is ticked) and the coordinator are
served as before. The role walk (``test_matrix_role_walk``) holds every other role's answer.

The lists that link to these pages leave the study out for the same account: the "criteria waiting" lines, the J-6
opening page's Next line and ``/reports``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from console import phone
from fastapi.testclient import TestClient
from tb_common import flags as fl
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    _done_feas,
    _ulid,
    box,
    login,
    login_crc,
    name_pi,
    sub_investigator,
)
from tests.console.test_d280_breakglass import _open

PW = "offlog-10c3c-password-01"
STUDY = "GZQO"
JOB = _ulid(900)  # _done_feas: GZQO's feasibility job
PAGES = (
    f"/pilot/jobs/{JOB}",
    f"/pilot/jobs/{JOB}/approval",
    f"/studies/{STUDY}/state",
    f"/studies/{STUDY}/feasibility",
    f"/studies/{STUDY}/forms",
    f"/studies/{STUDY}/irb",
    f"/studies/{STUDY}/setup",
    f"/studies/{STUDY}/sources",
    f"/studies/{STUDY}/team",
)
APIS = tuple(f"/api/v1/studies/{STUDY}/{x}" for x in ("delegation", "forms", "icf", "irb", "sources"))
OFF = ("offlog", "nolog")  # on RA-BIO's log only; on no log
ON = ("pi", "subg", "subrun")  # GZQO's PI; sub-investigators ticked "screen", or only "run"


@pytest.fixture(autouse=True)
def _fresh_flags() -> Iterator[None]:
    """The layout flags are read into a process cache: each test starts and ends with none (as test_home_today)."""
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _accounts(box: dict[str, Any]) -> dict[str, tuple[TestClient, TestClient]]:  # noqa: F811
    """One page client and one API client per account; GZQO's log names ``pi`` as PI."""
    _done_feas(box["backend"])
    for name in (*ON, *OFF):
        box["users"].create(name, "investigator", PW, f"{name}@hospa.test")
    name_pi(box, "pi")
    sub_investigator(box, "subg", ("screen",))
    sub_investigator(box, "subrun", ("run",))
    sub_investigator(box, "offlog", ("screen",), rs="RA-BIO")
    out: dict[str, tuple[TestClient, TestClient]] = {}
    crc, _ = login_crc(box)
    users = box["users"]
    token, _ = users.new_session(users.get("crc"), via="api")
    out["crc"] = (crc, TestClient(box["app"], headers={"Authorization": f"Bearer {token}"}))
    for name in (*ON, *OFF):
        page, _ = login(box["app"], name, PW)
        token, _ = users.new_session(users.get(name), via="api")
        out[name] = (page, TestClient(box["app"], headers={"Authorization": f"Bearer {token}"},
                                      raise_server_exceptions=False))  # fmt: skip
    return out


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _denied(box: dict[str, Any], who: str) -> list[str]:  # noqa: F811
    rows = [json.loads(line) for f in sorted(box["backend"].audit_dir.glob("*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]  # fmt: skip
    return [r["detail"]["action"] for r in rows if r["event"] == "console.denied" and r["actor"] == f"console:{who}"]


def test_the_off_log_investigator_is_refused_the_14_routes_as_the_week_page(box: dict[str, Any]) -> None:  # noqa: F811
    c = _accounts(box)
    for name in OFF:
        page, api = c[name]
        week = page.get(f"/studies/{STUDY}/week", follow_redirects=False)
        assert week.status_code == 403  # the control
        refused = _main(week.text).replace(f"/studies/{STUDY}/week", "<path>")
        for path in PAGES:
            r = page.get(path, follow_redirects=False)
            assert r.status_code == 403, (name, path, r.status_code)
            # the week page's own refusal, word for word (the feedback form names the page it was sent from)
            assert _main(r.text).replace(path, "<path>") == refused, path
        for path in APIS:
            r = api.get(path)
            assert r.status_code == 403 and r.json() == {"error": "forbidden", "detail": {}}, (name, path, r.text)
        # one console.denied row per refusal, naming the route
        assert set(PAGES) | set(APIS) <= set(_denied(box, name)), name


def test_the_on_log_accounts_are_served_as_before(box: dict[str, Any]) -> None:  # noqa: F811
    c = _accounts(box)
    want = {path: c["crc"][0].get(path, follow_redirects=False).status_code for path in PAGES}
    want |= {path: c["crc"][1].get(path).status_code for path in APIS}
    assert all(s not in (401, 403, 404) for s in want.values()), want
    for name in ON:
        page, api = c[name]
        got = {path: page.get(path, follow_redirects=False).status_code for path in PAGES}
        got |= {path: api.get(path).status_code for path in APIS}
        assert got == want, (name, got)
        assert not _denied(box, name), name


def test_a_break_glass_grant_still_opens_the_job_page(box: dict[str, Any]) -> None:  # noqa: F811
    c = _accounts(box)
    page, _ = c["nolog"]
    assert page.get(f"/pilot/jobs/{JOB}").status_code == 403
    assert _open(page, kind="job", job_id=JOB, reason="incident", note="incident 1258: job check").status_code == 303
    r = page.get(f"/pilot/jobs/{JOB}")
    assert r.status_code == 200, r.status_code
    rows = [json.loads(line) for f in sorted(box["backend"].audit_dir.glob("*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]  # fmt: skip
    assert any(x["event"] == "console.breakglass_use" and x.get("job_id") == JOB for x in rows)  # the use, recorded
    # the grant is for the job only: the study's other pages still refuse
    assert page.get(f"/studies/{STUDY}/state").status_code == 403


def _waiting_criteria(box: dict[str, Any]) -> str:  # noqa: F811
    jid = _ulid(1258)
    key = f"outputs/{jid}/review_GZQO_v1.0.0_r1.xlsx"
    box["backend"].objects[key] = b"PK synthetic"
    out = JobOutput(filename="review_GZQO_v1.0.0_r1.xlsx", sha256=sha256_bytes(b"PK synthetic"), minio_key=key,
                    recipients=[], tag="aggregate")  # fmt: skip
    now = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
    box["backend"].add_job(Job(job_id=jid, type="FEAS", ruleset=STUDY, ruleset_version="1.0.0",
                               requested_by="crc@hospa.test", received_at=now, updated_at=now,
                               state="awaiting_approval", options={}, inputs=[], outputs=[out]))  # fmt: skip
    return jid


@pytest.mark.parametrize("path", ["/week", "/reports"])
def test_the_lists_leave_out_a_study_off_the_log(box: dict[str, Any], path: str) -> None:  # noqa: F811
    c = _accounts(box)
    jid = _waiting_criteria(box)
    for name in OFF:
        body = c[name][0].get(path, follow_redirects=False).text.split("<main", 1)[-1]
        assert jid not in body and f"/studies/{STUDY}/" not in body, (name, path)
    for name in ("crc", "pi"):
        body = c[name][0].get(path, follow_redirects=False).text.split("<main", 1)[-1]
        assert (jid in body) if path == "/week" else (STUDY in body), (name, path)


def test_the_opening_page_names_no_study_off_the_log(box: dict[str, Any]) -> None:  # noqa: F811
    """J-6 (D-1225) with ``layout.home_today`` on: a study whose participants the account does not read got a Next
    line linking to its feasibility report; for a study off the account's log there is no line at all now."""
    from tests.console.test_home_today import _flag

    c = _accounts(box)
    _flag(box, "on")
    for name in OFF:
        body = _main(c[name][0].get("/home").text)
        assert 'data-testid="next-GZQO"' not in body and f"/studies/{STUDY}/" not in body, name
    for name in ("pi", "subrun"):  # on the log: the line stays (the PI reads the participants; "run" does not)
        assert 'data-testid="next-GZQO"' in c[name][0].get("/home").text, name
