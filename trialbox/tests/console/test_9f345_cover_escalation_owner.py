"""9f-3, 9f-4 (b), 9f-5 (D-1383): the PI's cover, the escalation of an unacknowledged serious AE, a task's owner.

The owner's limits (2026-11-20): each limited to the study's delegation log and audited where it widens.

* **Cover:** only a sub-investigator already on THAT study's log, entered by the study's PI (never by the covering
  person, never naming the PI), first and last day required, at most ``COVER_MAX_DAYS``; the PI's rights only inside
  the dates (the site's day), only in that study, only while the PI covered is still the PI and the covering
  person's own entry is active; one reading of the log (``teamstore.log_rights``) for the console and the
  orchestrator; every act under the cover audited with both names; entry, early end, start and end audited; the
  log's own rows never under a cover; the morning mail's study only inside the dates.
* **Escalation:** to the study's sub-investigators and coordinators on its log active that day, once per case and
  threshold, at ``TB_SAE_ESCALATE_HOURS`` (default 24) after the register first had the case, not before; the PI's
  own notice of the case and no more (without its screening number for a person who does not read the study's
  serious AEs); audited naming who was told; no notice setting applies.
* **Owner:** a person on that study's log; each change audited; who sees a task does not change.

Synthetic data only."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from console import notify
from console.auth import User
from console.sitestore import NotifyPerson
from console.team import standing
from console.teamstore import COVER_MAX_DAYS, SCHEMA_V5, TeamError, TeamStore
from orchestrator import grants
from tb_common.authz import MATRIX, MATRIX_ROLES, permit
from tb_common.db import Database

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_sae_d277 import FATAL

DAY = date(2026, 11, 20)  # a Friday
RS, OTHER = "GZQO", "RA-BIO"
AT = "2026-11-20T00:30:00+00:00"


def _entry(team: TeamStore, username: str, role: str, tasks: tuple[str, ...] = (), start: date = date(2026, 1, 1),
           end: date | None = None, rs: str = RS, name: str = "") -> int:  # fmt: skip
    return team.add_entry(rs, username=username, name=name or f"Dr {username}", role=role, tasks=tasks,
                          start=start.isoformat(), end=end.isoformat() if end else None, training_day="2025-06-01",
                          training_ref=None, by="stw-setup", at="2026-01-01T00:00:00+00:00")  # fmt: skip


def _user(username: str, role: str = "investigator") -> Any:
    return SimpleNamespace(username=username, role=role, aggregate_only=role == "cro", sees_study=lambda rs: True)


def _days(n: int) -> str:
    return (DAY + timedelta(days=n)).isoformat()


@pytest.fixture
def team() -> Any:
    t = TeamStore()  # the test's own trial database (tests/conftest.py)
    for rs in (RS, OTHER):
        _entry(t, "drpi", "pi", rs=rs)
        _entry(t, "drb", "sub_pi", ("refer",), rs=rs)
    _entry(t, "drcrc", "crc")
    yield t
    t.close()


# ---------------------------------------------------------------------------------------------- who gains what, when
@pytest.mark.parametrize("role", MATRIX_ROLES)
def test_a_cover_gives_the_pis_standing_only_to_an_investigator_inside_its_dates_in_its_study(
    team: TeamStore, role: str
) -> None:
    """For every role of the matrix: with and without the cover, inside and outside its dates, in another study. Only
    the investigator holding the cover gains, and only the PI's standing (``is_pi``); nothing else changes."""
    without = {
        d: standing(team, _user("drb", role), RS, d) for d in (DAY - timedelta(days=1), DAY, DAY + timedelta(days=7))
    }
    team.add_cover(RS, username="drb", start=_days(0), end=_days(6), today=DAY, by="drpi", at=AT)
    for d, before in without.items():
        now = standing(team, _user("drb", role), RS, d)
        inside = d == DAY and role == "investigator"
        assert now.pi is inside and (now.cover is not None) is inside, (role, d)
        if not inside:
            assert now == before, (role, d)  # outside the dates, or another role: exactly as without the cover
            continue
        assert now.grant() == standing(team, _user("drpi"), RS, d).grant()  # the PI's own standing, nothing more
        assert now.entry is not None and now.entry.role == "sub_pi"  # signs and is named as itself, never the PI
        assert permit(role, "delegation.keep", now.grant()).allowed
        assert not permit(role, "delegation.keep", now.own_grant()).allowed  # the log stays the PI's
        gained = {a for a in MATRIX if permit(role, a, now.grant()) and not permit(role, a, before.grant())}
        assert gained and all(isinstance(MATRIX[a][role], tuple) for a in gained)  # only rows the log decides
    other = standing(team, _user("drb", role), OTHER, DAY)  # another study: the same person, the same entries
    assert not other.pi and other.cover is None


def test_the_cover_lapses_when_it_ends_early_when_the_pi_changes_or_the_sub_investigator_leaves(
    team: TeamStore,
) -> None:
    c = team.add_cover(RS, username="drb", start=_days(0), end=_days(10), today=DAY, by="drpi", at=AT)
    assert standing(team, _user("drb"), RS, DAY).pi
    ended = team.end_cover(RS, c.id, today=DAY + timedelta(days=2), by="drpi", at=AT)
    assert ended.ended_on == _days(2) and ended.last_day() == _days(1)
    assert standing(team, _user("drb"), RS, DAY + timedelta(days=1)).pi
    assert not standing(team, _user("drb"), RS, DAY + timedelta(days=2)).pi  # ended: the same day, at once
    with pytest.raises(TeamError, match="already over"):
        team.end_cover(RS, c.id, today=DAY + timedelta(days=3), by="drpi", at=AT)
    c2 = team.add_cover(OTHER, username="drb", start=_days(0), end=_days(10), today=DAY, by="drpi", at=AT)
    assert c2.id and standing(team, _user("drb"), OTHER, DAY).pi
    _entry(team, "drnew", "pi", start=DAY + timedelta(days=1), rs=OTHER)  # another PI from tomorrow
    assert not standing(team, _user("drb"), OTHER, DAY + timedelta(days=1)).pi  # the PI covered is no longer PI
    team.add_cover(RS, username="drb", start=_days(3), end=_days(8), today=DAY, by="drpi", at=AT)
    drb = next(e for e in team.entries(RS) if e.username == "drb")
    team.update_entry(RS, drb.id, tasks=("refer",), end=_days(4), training_day=None, training_ref=None, by="drpi",
                      at=AT)  # fmt: skip
    assert standing(team, _user("drb"), RS, DAY + timedelta(days=4)).pi
    assert not standing(team, _user("drb"), RS, DAY + timedelta(days=5)).pi  # the sub-investigator's entry ended


@pytest.mark.parametrize(
    ("by", "who", "start", "end", "why"),
    [
        ("drb", "drb", 0, 6, "only the PI"),  # the covering person enters their own cover
        ("drcrc", "drb", 0, 6, "only the PI"),  # a coordinator on the log
        ("drpi", "drpi", 0, 6, "another person than the PI"),  # the PI names themselves
        ("drpi", "drx", 0, 6, "sub-investigator on this study's log"),  # not on the log
        ("drpi", "drcrc", 0, 6, "sub-investigator on this study's log"),  # on the log, not a sub-investigator
        ("drpi", "drb", 0, None, "first and its last day"),  # no end
        ("drpi", "drb", -1, 6, "today or later"),
        ("drpi", "drb", 0, COVER_MAX_DAYS, f"at most {COVER_MAX_DAYS} days"),  # 91 days with both ends
        ("drpi", "drb", 5, 4, "before the start"),
    ],
)
def test_a_cover_is_refused(team: TeamStore, by: str, who: str, start: int, end: int | None, why: str) -> None:
    with pytest.raises(TeamError, match=why):
        team.add_cover(RS, username=who, start=_days(start), end=_days(end) if end is not None else "", today=DAY,
                       by=by, at=AT)  # fmt: skip
    assert team.covers(RS) == []


def test_a_cover_longer_than_the_sub_investigators_entry_or_over_another_is_refused(team: TeamStore) -> None:
    _entry(team, "drc", "sub_pi", end=DAY + timedelta(days=3))
    with pytest.raises(TeamError, match="every day of the cover"):
        team.add_cover(RS, username="drc", start=_days(0), end=_days(4), today=DAY, by="drpi", at=AT)
    team.add_cover(RS, username="drc", start=_days(0), end=_days(3), today=DAY, by="drpi", at=AT)
    with pytest.raises(TeamError, match="another cover"):
        team.add_cover(RS, username="drb", start=_days(3), end=_days(9), today=DAY, by="drpi", at=AT)
    assert team.add_cover(RS, username="drb", start=_days(4), end=_days(4 + COVER_MAX_DAYS - 1), today=DAY,
                          by="drpi", at=AT).end == _days(COVER_MAX_DAYS + 3)  # fmt: skip


def test_the_orchestrator_reads_the_cover_as_the_console_does(team: TeamStore) -> None:
    team.add_cover(RS, username="drb", start=_days(1), end=_days(2), today=DAY, by="drpi", at=AT)
    for d, want in ((DAY, False), (DAY + timedelta(days=1), True), (DAY + timedelta(days=3), False)):
        theirs = grants.log_standing("drb", RS, d)
        mine = standing(team, _user("drb"), RS, d).grant()
        assert (theirs.is_pi, theirs.log_names_pi) == (mine.is_pi, mine.log_names_pi) == (want, True), d
        assert grants.own_right("investigator", theirs) == grants.own_right("investigator", mine)


# ---------------------------------------------------------------------------------------------- the console
def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(b["backend"].audit_dir.glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines() if x and json.loads(x).get("event") == name]
    return out


@pytest.fixture
def cb(box: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """The console box on 2026-11-20 (Asia/Taipei): ``lpi`` the GZQO PI, ``cov`` a sub-investigator with no tick,
    ``crc`` a coordinator on the log, ``crx`` a coordinator not on it, ``cra`` a CRO account with a monitor grant."""
    h = box["app"].state.helpers
    clock = {"now": datetime(2026, 11, 20, 1, 0, tzinfo=UTC)}
    h.clock = lambda: clock["now"]
    for name, role in (("lpi", "investigator"), ("cov", "investigator"), ("crc", "coordinator"),
                       ("crx", "coordinator"), ("cra", "cro")):  # fmt: skip
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    box["users"].set_scope("cra", "cro", "GZQO", None)
    _entry(h.team, "lpi", "pi", name="Dr L")
    _entry(h.team, "cov", "sub_pi", name="Dr C")
    _entry(h.team, "crc", "crc", name="Ms R")
    _entry(h.team, "cra", "monitor", end=DAY + timedelta(days=30), name="CRA K")
    return {**box, "h": h, "clock": clock}


def test_the_pi_enters_a_cover_the_banner_shows_and_acts_under_it_name_both(cb: dict[str, Any]) -> None:
    lpi, csrf = login(cb["app"], "lpi", PW)
    assert 'data-testid="cover-form"' in lpi.get("/studies/GZQO/team").text  # the PI's form
    r = lpi.post("/studies/GZQO/cover", data={"csrf": csrf, "username": "cov", "start": _days(0),
                                                   "end": _days(6)}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    (add,) = [e for e in _events(cb, "console.cover") if e["detail"]["action"] == "add"]
    assert add["actor"] == "console:lpi" and add["ruleset"] == "GZQO"
    assert {k: add["detail"][k] for k in ("pi", "pi_name", "username", "name", "start", "end", "max_days")} == {
        "pi": "lpi", "pi_name": "Dr L", "username": "cov", "name": "Dr C", "start": _days(0), "end": _days(6),
        "max_days": COVER_MAX_DAYS}  # fmt: skip
    assert [e["detail"]["action"] for e in _events(cb, "console.cover")] == ["add", "start"]  # from today: at once
    cov, ccsrf = login(cb["app"], "cov", PW)
    page = cov.get("/studies/GZQO/team").text
    assert 'data-testid="cover-banner"' in page and "Dr C" in page and "Dr L" in page
    assert 'data-testid="cover-form"' not in page  # the covering person enters no cover
    # an act under the cover (the PI's row delegation.check): the actor is the covering person, both names noted
    assert cov.post("/studies/GZQO/team/check", data={"csrf": ccsrf, "result": "match"},
                    follow_redirects=False).status_code == 303  # fmt: skip
    (ev,) = [e for e in _events(cb, "console.delegation") if e["detail"].get("action") == "compare"]
    assert ev["actor"] == "console:cov"
    assert ev["detail"]["covering_for"] == {"pi": "lpi", "pi_name": "Dr L", "name": "Dr C", "cover": 1}
    # the log stays the PI's: no entry added or changed, no cover entered, by the covering person
    for path, data in (
        ("/studies/GZQO/team", {"role": "sub_pi", "name": "X", "start": _days(0)}),
        ("/studies/GZQO/team/2", {"end": _days(1)}),
        ("/studies/GZQO/cover", {"username": "cov", "start": _days(0), "end": _days(1)}),
    ):
        assert cov.post(path, data={"csrf": ccsrf, **data}, follow_redirects=False).status_code == 403, path
    # an act of the same person in another study, or after the cover: no note
    cb["clock"]["now"] = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)  # the day after the last day
    assert cov.post("/studies/GZQO/team/check", data={"csrf": ccsrf, "result": "match"},
                    follow_redirects=False).status_code == 403  # fmt: skip
    cb["h"].cover_edges(cb["h"].today())
    assert [e["detail"]["action"] for e in _events(cb, "console.cover")] == ["add", "start", "end"]
    cb["h"].cover_edges(cb["h"].today())  # once each
    assert len(_events(cb, "console.cover")) == 3
    crc, kcsrf = login(cb["app"], "crc", PW)  # the IRB task waits on the opening page until it is marked done
    assert 'data-testid="task-cover_irb"' in crc.get("/home").text
    assert crc.post("/studies/GZQO/cover/1/irb", data={"csrf": kcsrf}, follow_redirects=False).status_code == 303
    assert 'data-testid="task-cover_irb"' not in crc.get("/home").text
    assert _events(cb, "console.cover")[-1]["detail"]["action"] == "irb_told"


def test_a_cover_entered_by_another_than_the_pi_is_refused_and_an_early_end_is_audited(cb: dict[str, Any]) -> None:
    cov, ccsrf = login(cb["app"], "cov", PW)
    data = {"csrf": ccsrf, "username": "cov", "start": _days(0), "end": _days(3)}
    assert cov.post("/studies/GZQO/cover", data=data, follow_redirects=False).status_code == 403  # self-entered
    crc, kcsrf = login(cb["app"], "crc", PW)
    assert crc.post("/studies/GZQO/cover", data={**data, "csrf": kcsrf}, follow_redirects=False).status_code == 403
    lpi, csrf = login(cb["app"], "lpi", PW)
    r = lpi.post("/studies/GZQO/cover", data={**data, "csrf": csrf, "username": "crc"}, follow_redirects=False)
    assert r.status_code == 400  # not an investigator, not a sub-investigator of the log
    api = lpi.post("/api/v1/studies/GZQO/cover", json={"username": "cov", "start": _days(0), "end": ""})
    assert api.status_code in (400, 401, 403)  # no end: refused (the page client has no token: the API answers 401)
    assert cb["h"].team.covers("GZQO") == []
    assert lpi.post("/studies/GZQO/cover", data={**data, "csrf": csrf}, follow_redirects=False).status_code == 303
    assert cb["h"].stand(cb["users"].get("cov"), "GZQO").pi
    assert cov.post("/studies/GZQO/cover/1/end", data={"csrf": ccsrf}, follow_redirects=False).status_code == 303
    assert not cb["h"].stand(cb["users"].get("cov"), "GZQO").pi
    acts = [(e["detail"]["action"], e["actor"]) for e in _events(cb, "console.cover")]
    assert acts == [("add", "console:lpi"), ("start", "system:cover"), ("end_early", "console:cov"),
                    ("end", "system:cover")]  # fmt: skip


def test_the_covering_persons_morning_mail_carries_the_study_only_inside_the_dates(cb: dict[str, Any]) -> None:
    h, cov = cb["h"], cb["users"].get("cov")
    assert not h.delegated_ok(cov, "GZQO")  # no screen tick: N1 leaves the study out
    h.team.add_cover("GZQO", username="cov", start=_days(1), end=_days(2), today=DAY, by="lpi", at=AT)
    assert not h.delegated_ok(cov, "GZQO") and h.cover_lines(cov, DAY) == []
    cb["clock"]["now"] = datetime(2026, 11, 21, 1, 0, tzinfo=UTC)
    assert h.delegated_ok(cov, "GZQO")  # the gate of N1 (D-273): the study's rows go, as to the PI
    assert h.cover_lines(cov, h.today()) == [("GZQO", "Dr L", _days(2))]
    n = notify.build_n1(User("cov", "investigator", "cov@hospa.test"), NotifyPerson("cov", "P1", lang="ja"),
                        h.today(), [("GZQO", [])], {"GZQO": {"sae": 1}}, covers=h.cover_lines(cov, h.today()))  # fmt: skip
    assert n is not None and "Dr L" in n.body and "GZQO" in n.body
    cb["clock"]["now"] = datetime(2026, 11, 23, 1, 0, tzinfo=UTC)
    assert not h.delegated_ok(cov, "GZQO") and h.cover_lines(cov, h.today()) == []


# ---------------------------------------------------------------------------------------------- 9f-5: a task's owner
def test_a_tasks_owner_is_a_person_on_the_log_and_each_change_is_audited(cb: dict[str, Any]) -> None:
    lpi, csrf = login(cb["app"], "lpi", PW)
    post = lambda c, k, owner: c.post(
        "/studies/GZQO/tasks/owner",
        data={
            "csrf": k,
            "kind": "delegation",
            "ref": "",  # noqa: E731
            "owner": owner,
        },
        follow_redirects=False,
    )
    assert post(lpi, csrf, "crc").status_code == 303
    assert post(lpi, csrf, "crx").status_code == 400  # a coordinator not on the log
    assert post(lpi, csrf, "cra").status_code == 400  # a monitor grant owns no task
    assert post(lpi, csrf, "nobody").status_code == 400
    crx, xcsrf = login(cb["app"], "crx", PW)
    assert post(crx, xcsrf, "crc").status_code == 403  # sets no owner: not on the study's log
    cov, ccsrf = login(cb["app"], "cov", PW)
    assert post(cov, ccsrf, "crc").status_code == 403  # a sub-investigator without the cover
    crc, kcsrf = login(cb["app"], "crc", PW)
    assert post(crc, kcsrf, "cov").status_code == 303  # the coordinator on the log
    owners, people = cb["h"].task_owners("GZQO")
    assert owners[("delegation", "")].owner == "cov" and ("cra", "CRA K") not in people
    evs = [e["detail"] for e in _events(cb, "console.task_owner")]
    assert [(d["action"], d["owner"], d["before"]) for d in evs] == [("set", "crc", ""), ("set", "cov", "crc")]
    assert post(crc, kcsrf, "").status_code == 303
    assert _events(cb, "console.task_owner")[-1]["detail"]["action"] == "clear"
    assert ("delegation", "") not in cb["h"].task_owners("GZQO")[0]


def test_the_owner_shows_on_the_task_line_to_whoever_sees_it(cb: dict[str, Any]) -> None:
    cb["h"].team.set_task_owner("GZQO", kind="delegation", ref="", owner="crc", day=DAY, by="lpi", at=AT)
    crc, _ = login(cb["app"], "crc", PW)
    page = crc.get("/home").text
    assert 'data-testid="task-delegation"' in page and 'data-testid="task-owner"' in page and "Ms R" in page
    crx, _ = login(cb["app"], "crx", PW)  # sees the same task (every coordinator sees every study), may not set it
    other = crx.get("/home").text
    assert 'data-testid="task-delegation"' in other and 'data-testid="task-own-delegation"' not in other


def test_the_migration_adds_the_two_tables_and_an_older_release_still_opens_the_store(db_url: str) -> None:
    from console import teamstore

    with Database.connect(db_url, "team_v5") as db:
        db.migrate(list(teamstore.MIGRATIONS[:4]))  # a box before 9f-3
        db.execute("INSERT INTO delegation (ruleset, username, name, role, start_day, signed_by, signed_at, updated_by,"
                   " updated_at) VALUES ('GZQO', 'lpi', 'Dr L', 'pi', '2026-01-01', 's', 'x', 's', 'x')")  # fmt: skip
        assert db.migrate(list(teamstore.MIGRATIONS)) == 5  # up: version 5
        tables = {str(r[0]) for r in db.fetchall(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (db.schema,))}  # fmt: skip
        assert {"pi_cover", "task_owner", "delegation"} <= tables
        assert db.fetchval("SELECT count(*) FROM delegation") == 1
        assert teamstore.MIGRATIONS[4] == SCHEMA_V5
        # down: the product's migrations go forward only (D-204); the release before still opens a version-5 store
        assert db.migrate(list(teamstore.MIGRATIONS[:4])) == 4
        assert db.fetchval("SELECT count(*) FROM pi_cover") == 0


# ---------------------------------------------------------------------------------------------- 9f-4 (b): escalation
def _case(lb: dict[str, Any]) -> str:  # noqa: F811
    from tests.console.test_console_app import name_pi

    name_pi(lb, "pi")
    h = lb["app"].state.helpers
    for name, role in (("subi", "investigator"), ("subx", "investigator"), ("subo", "investigator"),
                       ("crx", "coordinator")):  # fmt: skip
        lb["users"].create(name, role, PW, f"{name}@hospa.test")
    _entry(h.team, "subi", "sub_pi", name="Dr S")  # no tick: does not read the study's serious AEs
    _entry(h.team, "crc", "crc", name="Ms R")
    _entry(h.team, "subx", "sub_pi", end=date(2026, 11, 1))  # ended before the day
    _entry(h.team, "subo", "sub_pi", rs="RA-BIO")  # another study
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["clock"]["now"] = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"}, follow_redirects=True)
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "ae1", "values": FATAL, "by": "rc:read"})
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)
    return str(no)


def _sync(lb: dict[str, Any], hours: float) -> list[tuple[str, list[str], str, str]]:  # noqa: F811
    lb["clock"]["now"] = datetime(2026, 11, 10, 1, 0, tzinfo=UTC) + timedelta(hours=hours)
    c, csrf = login(lb["app"], "crc", PW)
    before = len(lb["backend"].notices)
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)
    return [n for n in lb["backend"].notices[before:] if "waited" in n[2] or "時間" in n[2] or "小時" in n[2]]


def test_an_unacknowledged_sae_is_told_once_at_n_hours_to_the_logs_sub_investigators_and_coordinators(
    lb: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)  # the default, 24 hours
    no = _case(lb)
    lb["app"].state.helpers.store.save_notify_person(NotifyPerson("crc", None, "07:30", False, "en"))  # mail off
    assert _sync(lb, 23.9) == []  # not before
    told = _sync(lb, 24.1)
    assert sorted(n[1][0] for n in told) == ["crc@hospa.test", "subi@hospa.test"]  # nobody else, mail off or not
    by = {n[1][0]: n for n in told}
    assert "24 hours" in by["crc@hospa.test"][2] and no in by["crc@hospa.test"][3]  # the PI's notice of the case
    assert "Myocardial" not in by["crc@hospa.test"][3]  # never the AE term
    assert no not in by["subi@hospa.test"][3] and "/studies/GZQO/subjects" in by["subi@hospa.test"][3]
    assert _sync(lb, 30) == [] and _sync(lb, 72) == []  # once per case and threshold
    rows = [json.loads(x) for f in sorted(lb["backend"].audit_dir.glob("*.jsonl")) for x in f.read_text().splitlines()
            if x and json.loads(x).get("event") == "console.sae"]  # fmt: skip
    (esc,) = [r["detail"] for r in rows if r["detail"].get("action") == "escalated"]
    assert esc["hours"] == 24 and esc["to"] == "crc, subi" and esc["full"] == ["crc"] and esc["short"] == ["subi"]
    assert esc["record"] == no and esc["failed"] == [] and esc["unreachable"] == []


def test_the_threshold_is_the_declared_setting(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("TB_SAE_ESCALATE_HOURS", "6")
    _case(lb)
    assert _sync(lb, 5.5) == []
    assert len(_sync(lb, 6.5)) == 2
    assert _sync(lb, 24.5) == []  # the threshold in force is 6: told at 6, not again at 24
    from console.sae_pages import escalate_hours

    assert escalate_hours({}) == 24 and escalate_hours({"TB_SAE_ESCALATE_HOURS": "48"}) == 48
    for bad in ("0", "-1", "abc", "721", "1.5"):
        with pytest.raises(ValueError, match="TB_SAE_ESCALATE_HOURS"):
            escalate_hours({"TB_SAE_ESCALATE_HOURS": bad})


def test_an_acknowledged_sae_is_not_told(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    _case(lb)
    from console.saerecord import SaeStore

    store = SaeStore()
    try:
        store.db.execute("UPDATE sae_case SET pi_ack_by = 'pi', pi_ack_at = ? WHERE ruleset = 'GZQO'", (AT,))
    finally:
        store.close()
    assert _sync(lb, 30) == []


def test_the_hourly_round_is_a_timer() -> None:
    from console import timers

    jobs = timers.jobs(SimpleNamespace(sae_escalate=lambda: ["GZQO:1/ae1"]))
    assert jobs["sae_escalate"]() == ["GZQO:1/ae1"]
    assert jobs["sae_escalate"].__name__ == "sae_escalate"
