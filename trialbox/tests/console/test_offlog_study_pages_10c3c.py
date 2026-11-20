"""Card 10C-3c (D-1258), gap 3 and the sweep: the 18 doors of one study that an investigator off its delegation log is
refused, and the lists that pointed at them.

Synthetic data only. The owner's decisions (recorded on PR #1239):

* 2026-11-19, "close all 14": the study's job page and approval page, its state, feasibility, forms, IRB, set-up,
  sources and delegation-log pages, and the ``/api/v1`` delegation, forms, consent-form, IRB and sources answers;
* 2026-11-20, "close all 4": ticking and labelling criteria in the study's approval round, and the job's files and
  views; the break-glass grant on the job stays;
* 2026-11-20, "empty log open, listed = in": while the study's log names nobody, investigators see the study as
  before; once it has any entry, an investigator gets in only with an active entry of their own, ticked or not; an
  ended entry is out. What a task tick allows elsewhere does not change.

The check is ``Helpers.on_log`` (``Helpers.on_log_ok``, ``console.team.listed``). A page answers 403 as the study's
week page does, the API its own JSON refusal (D-125), each with one ``console.denied`` row. The lists that pointed at
these doors leave the study out for the same account: the "criteria waiting" lines, the J-6 opening page's Next line,
``/reports`` and ``/jobs``. The role walk (``test_matrix_role_walk``) holds every other role's answer."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
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
    review_book,
    sub_investigator,
)
from tests.console.test_d280_breakglass import _open

PW = "offlog-10c3c-password-01"
STUDY = "GZQO"
JOB = _ulid(900)  # _done_feas: GZQO's feasibility job (a PDF, a JSON and a patient-level file)
WAIT = _ulid(1258)  # GZQO's criteria waiting for approval (a review workbook)
LOWER = _ulid(1259)  # a job whose study id came in lower case
VIEW = "consent_GZQO_en.html"  # an aggregate page of the feasibility job, for /view
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
FILES = (  # every kind of job file: the aggregate PDF and JSON, the review workbook, an aggregate page
    f"/pilot/jobs/{JOB}/files/feasibility_GZQO_v1.0.0_2026-10-04.pdf",
    f"/pilot/jobs/{JOB}/files/feasibility_GZQO_v1.0.0_2026-10-04.json",
    f"/pilot/jobs/{WAIT}/files/review_GZQO_v1.0.0_r1.xlsx",
    f"/pilot/jobs/{JOB}/view/{VIEW}",
)
#: the 18 rows of route_actions.yaml that ask the log (the owner's two decisions); a 19th needs a decision of its own
ROUTES = (
    "GET /pilot/jobs/{job_id}",
    "GET /pilot/jobs/{job_id}/approval",
    "GET /studies/{rs}/state",
    "GET /studies/{rs}/feasibility",
    "GET /studies/{rs}/forms",
    "GET /studies/{rs}/irb",
    "GET /studies/{rs}/setup",
    "GET /studies/{rs}/sources",
    "GET /studies/{rs}/team",
    "GET /api/v1/studies/{rs}/delegation",
    "GET /api/v1/studies/{rs}/forms",
    "GET /api/v1/studies/{rs}/icf",
    "GET /api/v1/studies/{rs}/irb",
    "GET /api/v1/studies/{rs}/sources",
    "POST /pilot/jobs/{job_id}/approval/tick",
    "POST /pilot/jobs/{job_id}/approval/label",
    "GET /pilot/jobs/{job_id}/files/{filename}",
    "GET /pilot/jobs/{job_id}/view/{filename}",
)
OFF = ("offlog", "nolog", "ended")  # on RA-BIO's log only; on no log; an ended entry on GZQO's log
ON = ("pi", "subg", "subrun", "subnone")  # GZQO's PI; subs ticked "screen", only "run", or nothing


@pytest.fixture(autouse=True)
def _fresh_flags() -> Iterator[None]:
    """The layout flags are read into a process cache: each test starts and ends with none (as test_home_today)."""
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _jobs(box: dict[str, Any]) -> None:  # noqa: F811
    """GZQO's feasibility job with an aggregate page, its criteria waiting for approval, and a job under ``gzqo``."""
    bk = box["backend"]
    feas = _done_feas(bk)
    page = b"<p>synthetic consent explainer</p>"
    bk.objects[f"outputs/{JOB}/{VIEW}"] = page
    view = JobOutput(filename=VIEW, sha256=sha256_bytes(page), minio_key=f"outputs/{JOB}/{VIEW}", recipients=[],
                     tag="aggregate")  # fmt: skip
    bk.jobs[JOB] = feas.model_copy(update={"outputs": [*(feas.outputs or []), view]})
    book = review_book([(f"{STUDY}-INC-01", "inclusion", "structured", "Age 18 or over.", None, None, None)])
    key = f"outputs/{WAIT}/review_GZQO_v1.0.0_r1.xlsx"
    bk.objects[key] = book
    out = JobOutput(filename="review_GZQO_v1.0.0_r1.xlsx", sha256=sha256_bytes(book), minio_key=key, recipients=[],
                    tag="aggregate")  # fmt: skip
    now = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
    bk.add_job(Job(job_id=WAIT, type="FEAS", ruleset=STUDY, ruleset_version="1.0.0", requested_by="crc@hospa.test",
                   received_at=now, updated_at=now, state="awaiting_approval", options={}, inputs=[],
                   outputs=[out]))  # fmt: skip
    bk.add_job(Job(job_id=LOWER, type="FEAS", ruleset="gzqo", ruleset_version="1.0.0", requested_by="crc@hospa.test",
                   received_at=now, updated_at=now, state="done", options={}, inputs=[], outputs=[]))  # fmt: skip


def _accounts(box: dict[str, Any], log: bool = True) -> dict[str, tuple[TestClient, TestClient]]:  # noqa: F811
    """One page client and one API client per account. With ``log``, GZQO's log names ``pi`` as PI, three
    sub-investigators (ticked "screen", only "run", nothing) and one whose entry has ended; without, GZQO's log is
    empty."""
    from console.teamstore import TeamStore

    _jobs(box)
    for name in (*ON, *OFF):
        box["users"].create(name, "investigator", PW, f"{name}@hospa.test")
    if log:
        name_pi(box, "pi")
        sub_investigator(box, "subg", ("screen",))
        sub_investigator(box, "subrun", ("run",))
        sub_investigator(box, "subnone", ())
        team = TeamStore()
        team.add_entry(STUDY, username="ended", name="ended", role="sub_pi", tasks=("screen",), start="2026-01-01",
                       end="2026-01-31", training_day="2025-06-01", training_ref=None, by="pi",
                       at="2026-01-01T00:00:00+00:00")  # fmt: skip
        team.close()
        sub_investigator(box, "offlog", ("screen",), rs="RA-BIO")
    out: dict[str, tuple[TestClient, TestClient]] = {}
    users = box["users"]
    crc, _ = login_crc(box)
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


def _rows(box: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: F811
    return [json.loads(line) for f in sorted(box["backend"].audit_dir.glob("*.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]  # fmt: skip


def _denied(box: dict[str, Any], who: str) -> list[str]:  # noqa: F811
    return [r["detail"]["action"] for r in _rows(box) if r["event"] == "console.denied"
            and r["actor"] == f"console:{who}"]  # fmt: skip


def _statuses(c: tuple[TestClient, TestClient]) -> dict[str, int]:
    got = {p: c[0].get(p, follow_redirects=False).status_code for p in (*PAGES, *FILES)}
    return got | {p: c[1].get(p).status_code for p in APIS}


def _csrf(c: TestClient) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', c.get("/account").text)
    assert m
    return m.group(1)


# ---------------------------------------------------------------------------------------------- the doors
def test_off_the_log_an_investigator_is_refused_the_studys_doors_as_its_week_page(box: dict[str, Any]) -> None:  # noqa: F811
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
        for path in FILES:
            r = page.get(path, follow_redirects=False)
            assert r.status_code == 403 and r.headers["content-type"].startswith("text/html"), (name, path)
            assert "%PDF" not in r.text and "consent explainer" not in r.text, path  # none of the file's bytes
        for path in APIS:
            r = api.get(path)
            assert r.status_code == 403 and r.json() == {"error": "forbidden", "detail": {}}, (name, path, r.text)
        # one row per refusal, naming the route (cut at 80 characters, as every console.denied row)
        assert {p[:80] for p in (*PAGES, *FILES, *APIS)} <= set(_denied(box, name)), name
    assert not [r for r in _rows(box) if r["event"] == "console.download" and r["actor"] != "console:crc"]


def test_on_the_log_an_investigator_is_served_as_before_ticked_or_not(box: dict[str, Any]) -> None:  # noqa: F811
    c = _accounts(box)
    want = _statuses(c["crc"])
    assert all(s not in (401, 403, 404) for s in want.values()), want
    for name in ON:
        assert _statuses(c[name]) == want, name
        assert not _denied(box, name), name


def test_while_the_log_names_nobody_investigators_see_the_study_as_before(box: dict[str, Any]) -> None:  # noqa: F811
    """Decision 2 (i): a doctor reads the study's feasibility report before agreeing to be its investigator."""
    c = _accounts(box, log=False)
    want = _statuses(c["crc"])
    for name in ("nolog", "pi", "subg"):  # nobody is on GZQO's (empty) log
        assert _statuses(c[name]) == want, name
        assert STUDY in _main(c[name][0].get("/reports").text), name


def test_a_break_glass_grant_still_opens_the_job_page_and_its_files(box: dict[str, Any]) -> None:  # noqa: F811
    c = _accounts(box)
    page, _ = c["nolog"]
    assert page.get(f"/pilot/jobs/{JOB}").status_code == 403
    assert _open(page, kind="job", job_id=JOB, reason="incident", note="incident 1258: job check").status_code == 303
    assert page.get(f"/pilot/jobs/{JOB}").status_code == 200
    assert page.get(FILES[0]).status_code == 200 and page.get(FILES[3]).status_code == 200
    assert any(x["event"] == "console.breakglass_use" and x.get("job_id") == JOB for x in _rows(box))  # recorded
    # the grant is for that job only: the study's other doors and its other jobs still refuse
    assert page.get(f"/studies/{STUDY}/state").status_code == 403 and page.get(FILES[2]).status_code == 403


def test_off_the_log_an_investigator_neither_ticks_nor_labels_the_studys_criteria(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_home_today import _lang

    c = _accounts(box)
    store = box["app"].state.helpers.store
    crit = f"{STUDY}-INC-01"
    for name in OFF:
        _lang(c[name][0], "ja")
    for name in OFF:
        page, _ = c[name]
        for what, data in (("tick", {"crit": crit}), ("label", {"crit": crit, "text": "年齢"})):
            r = page.post(f"/pilot/jobs/{WAIT}/approval/{what}", data={"csrf": _csrf(page), **data},
                          follow_redirects=False)  # fmt: skip
            assert r.status_code == 403, (name, what, r.status_code)
            assert f"/pilot/jobs/{WAIT}/approval/{what}"[:80] in _denied(box, name)
        assert store.code_ticks(WAIT) == {} and store.labels(STUDY, "ja") == {}, name  # nothing stored or counted
    assert not [r for r in _rows(box) if r["event"] in ("console.code_tick", "console.criterion_label")]
    # on the log, ticked or not, the round takes them as before (the review's B4: listed with no task, ticked only
    # for "run", the PI)
    for name in ("subnone", "subrun", "pi"):
        page = c[name][0]
        _lang(page, "ja")
        for what, data in (("tick", {"crit": crit}), ("label", {"crit": crit, "text": "年齢"})):
            r = page.post(f"/pilot/jobs/{WAIT}/approval/{what}", data={"csrf": _csrf(page), **data},
                          follow_redirects=False)  # fmt: skip
            assert r.status_code == 303, (name, what, r.status_code)
        assert store.code_ticks(WAIT)[crit][0] == name and store.labels(STUDY, "ja") == {crit: "年齢"}, name


def test_while_the_log_names_nobody_an_investigator_ticks_and_labels(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_home_today import _lang

    c = _accounts(box, log=False)
    page = c["nolog"][0]
    _lang(page, "ja")
    crit = f"{STUDY}-INC-01"
    for what, data in (("tick", {"crit": crit}), ("label", {"crit": crit, "text": "年齢"})):
        r = page.post(f"/pilot/jobs/{WAIT}/approval/{what}", data={"csrf": _csrf(page), **data},
                      follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, (what, r.status_code)


def test_a_study_id_in_lower_case_asks_the_same_log(box: dict[str, Any]) -> None:  # noqa: F811
    """The review of D-1258 (F4): the log keeps GZQO; a job filed under ``gzqo`` is the same study, not an empty log."""
    c = _accounts(box)
    for name in OFF:
        assert c[name][0].get(f"/pilot/jobs/{LOWER}", follow_redirects=False).status_code == 403, name
    for name in ("pi", "subnone"):
        assert c[name][0].get(f"/pilot/jobs/{LOWER}", follow_redirects=False).status_code == 200, name


# ---------------------------------------------------------------------------------------------- the lists
@pytest.mark.parametrize("path", ["/week", "/reports", "/jobs"])
def test_the_lists_leave_out_a_study_off_the_log(box: dict[str, Any], path: str) -> None:  # noqa: F811
    c = _accounts(box)
    for name in OFF:
        body = _main(c[name][0].get(path, follow_redirects=False).text)
        assert WAIT not in body and JOB not in body and f"/studies/{STUDY}/" not in body, (name, path)
        assert path != "/reports" or STUDY not in body, name  # the reports page names the study: not this one
    for name in ("crc", "pi", "subnone"):
        body = _main(c[name][0].get(path, follow_redirects=False).text)
        assert {"/week": WAIT, "/reports": STUDY, "/jobs": JOB}[path] in body, (name, path)


def test_the_opening_page_names_no_study_off_the_log(box: dict[str, Any]) -> None:  # noqa: F811
    """J-6 (D-1225) with ``layout.home_today`` on: a study whose participants the account does not read got a Next
    line linking to its feasibility report; for a study off the account's log there is no line at all now."""
    from tests.console.test_home_today import _flag

    c = _accounts(box)
    _flag(box, "on")
    for name in OFF:
        body = _main(c[name][0].get("/home").text)
        assert 'data-testid="next-GZQO"' not in body and f"/studies/{STUDY}/" not in body, name
    for name in ("pi", "subrun", "subnone"):  # on the log, ticked or not: the line stays
        assert 'data-testid="next-GZQO"' in c[name][0].get("/home").text, name


# ---------------------------------------------------------------------------------------------- the walk's ``log:`` key
def test_the_rows_that_ask_the_log_are_exactly_the_owners_18() -> None:
    """A 19th row with ``log:`` needs a decision of its own (D-1258); ``on_log`` is the only value."""
    from tools import role_walk as rw

    declared = rw.load_declared()
    assert len(ROUTES) == len(set(ROUTES)) == 18
    assert {f"{m} {p}" for (m, p), d in declared.items() if d.log} == set(ROUTES)
    assert {d.log for d in declared.values()} == {"", "on_log"}


def test_a_log_value_other_than_on_log_is_refused(tmp_path: Any) -> None:
    from tools import role_walk as rw

    # a wrong value, and a falsy one (YAML reads no, off, false and 0 as such, ~ as none): never "no condition"
    for i, value in enumerate(("on", "pi", "off_log", "true", "no", "off", "false", "0", '""', "~", "On_log")):
        f = tmp_path / f"v{i}.yaml"
        f.write_text(f'routes:\n  "GET /x": {{kind: scope, log: {value}, why: "test"}}\n', "utf-8")
        with pytest.raises(ValueError, match="log is one of on_log"):
            rw.load_declared(f)
    # a misspelled key
    for i, row in enumerate(("Log: on_log", "logs: on_log", "on_log: true", "log_: on_log")):
        f = tmp_path / f"k{i}.yaml"
        f.write_text(f'routes:\n  "GET /x": {{kind: scope, {row}, why: "test"}}\n', "utf-8")
        with pytest.raises(ValueError, match="not keys of a row"):
            rw.load_declared(f)
    f = tmp_path / "ok.yaml"  # the one way to say it
    f.write_text('routes:\n  "GET /x": {kind: scope, log: on_log, why: "test"}\n', "utf-8")
    assert rw.load_declared(f)[("GET", "/x")].log == "on_log"


def test_the_log_key_only_turns_an_allow_into_a_refuse() -> None:
    """``log: on_log`` makes a row's expected answer stricter for some column, never wider for any: over every row of
    the table and every column, and for rows whose actions refuse (the column stays refused)."""
    from dataclasses import replace

    from tools import role_walk as rw

    rows = list(rw.load_declared().items())
    rows += [(("GET", "/studies/{rs}/x"), rw.Declared("actions", (a,), "all", "test"))
             for a in ("ops.view", "breakglass.review", "!phi.view", "task.screen", "request.prepare")]  # fmt: skip
    narrowed = 0
    for (method, path), d in rows:
        with_log, without = replace(d, log="on_log"), replace(d, log="")
        for col in rw.COLUMNS:
            a, b = rw.expected_of(col, method, path, with_log), rw.expected_of(col, method, path, without)  # the
            # template path, as judge_declared passes it (the study-scope rule reads it)
            assert not (a and not b), (method, path, col.name)  # never wider
            narrowed += b and not a
    assert narrowed > 0  # and it does narrow (column inv)


def test_the_walks_rule_is_the_consoles_over_every_role_and_every_log() -> None:
    """``tools.role_walk.on_log_of`` (read from the matrix) answers as ``Helpers.on_log_ok`` over
    ``console.team.listed``, for every role of the matrix and every state of a study's log: empty; others only; the
    account's own active entry as PI, sub-investigator (ticked or not) or monitor; its own ended entry."""
    from types import SimpleNamespace

    from console.auth import ROLES
    from console.home import Helpers
    from console.team import listed

    from tools import role_walk as rw

    day = date(2026, 11, 20)

    def entry(who: str, role: str, active: bool, tasks: tuple[str, ...] = ()) -> Any:
        return SimpleNamespace(username=who, role=role, tasks=tasks, active_on=lambda d, a=active: a)

    logs: dict[str, list[Any]] = {
        "empty": [],
        "others only": [entry("lead", "pi", True), entry("x", "sub_pi", True, ("screen",))],
        "own PI": [entry("me", "pi", True)],
        "own sub, ticked": [entry("lead", "pi", True), entry("me", "sub_pi", True, ("screen", "run"))],
        "own sub, no tick": [entry("lead", "pi", True), entry("me", "sub_pi", True)],
        "own monitor": [entry("lead", "pi", True), entry("me", "monitor", True)],
        "own ended": [entry("lead", "pi", True), entry("me", "sub_pi", False, ("screen",))],
        "own ended, no PI": [entry("me", "sub_pi", False, ("screen",))],
    }
    seen = set()
    for role in ROLES:
        user = SimpleNamespace(username="me", role=role)
        for what, entries in logs.items():
            team = SimpleNamespace(entries=lambda rs, e=entries: e)
            console = SimpleNamespace(listed=lambda u, rid, t=team: listed(t, u, rid, day))
            want = Helpers.on_log_ok(console, user, STUDY)  # type: ignore[arg-type]
            own = any(e.username == "me" and e.active_on(day) for e in entries)
            assert rw.on_log_of(role, log_empty=not entries, listed=own) == want, (role, what)
            seen.add((role, what, want))
    assert ("investigator", "others only", False) in seen and ("investigator", "own ended", False) in seen
    assert ("investigator", "empty", True) in seen and ("investigator", "own sub, no tick", True) in seen
    assert ("coordinator", "others only", True) in seen


def test_every_column_of_the_walk_gets_a_real_job_file_as_its_row_says(box: dict[str, Any]) -> None:  # noqa: F811
    """The review's B5: the role walk asks the file routes for a file named ``1`` and gets 404, so it cannot see these
    doors. Here every column of the walk (its own accounts and GZQO log) asks for the real aggregate outputs of a
    prepared SCREEN run of GZQO (the walk's own kind of job: a feasibility run's files are open to the aggregate-only
    accounts by D-146, which the row does not describe), and each answer is judged against the declared row as the walk
    judges it: a door reopened for any column fails here."""
    from tests.console.test_console_app import _done_screen
    from tests.console.test_matrix_role_walk import clients
    from tools import role_walk as rw

    jid = _ulid(1260)
    job = _done_screen(box["backend"], jid)
    page = b"<p>synthetic list explainer</p>"
    box["backend"].objects[f"outputs/{jid}/screen_GZQO_en.html"] = page
    extra = JobOutput(filename="screen_GZQO_en.html", sha256=sha256_bytes(page),
                      minio_key=f"outputs/{jid}/screen_GZQO_en.html", recipients=[], tag="aggregate")  # fmt: skip
    box["backend"].jobs[jid] = job.model_copy(update={"outputs": [*(job.outputs or []), extra]})
    paths = [f"/pilot/jobs/{jid}/files/{o.filename}" for o in job.outputs or [] if o.tag == "aggregate"]
    paths.append(f"/pilot/jobs/{jid}/view/screen_GZQO_en.html")
    assert len(paths) == 3
    cols = clients(box)
    declared = rw.load_declared()
    judged: dict[str, set[str]] = {"A": set(), "R": set()}
    for path in paths:
        template = re.sub(r"/pilot/jobs/[^/]+/(files|view)/[^/]+$", r"/pilot/jobs/{job_id}/\1/{filename}", path)
        row = declared[("GET", template)]
        for col in rw.COLUMNS:
            r = cols[col.name][0].get(path, follow_redirects=False)
            got, why = rw.decide(col, template, r.status_code, r.headers.get("location", ""))
            want = rw.expected_of(col, "GET", template, row)
            assert got == ("A" if want else "R"), (path, col.name, r.status_code, why)
            judged[got].add(col.name)
    assert "inv" in judged["R"] and {"pi", "sub", "crc"} <= judged["A"]  # the off-log column refused, the rest served
