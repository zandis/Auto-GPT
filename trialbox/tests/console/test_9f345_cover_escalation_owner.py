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
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from console import notify
from console.auth import User
from console.sitestore import NotifyPerson
from console.team import standing
from console.teamstore import COVER_MAX_DAYS, COVER_RIGHTS, COVER_WITHHELD, SCHEMA_V5, TeamError, TeamStore
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
        pi = standing(team, _user("drpi"), RS, d).grant()
        assert replace(now.grant(), pi_rights=None) == pi  # the PI's own standing, nothing more ...
        assert now.grant().pi_rights == COVER_RIGHTS  # ... and of the PI's rows only the cover's allow-list
        assert now.entry is not None and now.entry.role == "sub_pi"  # signs and is named as itself, never the PI
        for a in {a for a in COVER_WITHHELD & set(MATRIX) if isinstance(MATRIX[a][role], tuple)}:  # the PI's rows
            assert not permit(role, a, now.grant()).allowed, a
        assert not permit(role, "delegation.keep", now.own_grant()).allowed  # the log stays the PI's
        gained = {a for a in MATRIX if permit(role, a, now.grant()) and not permit(role, a, before.grant())}
        assert gained and all(isinstance(MATRIX[a][role], tuple) for a in gained)  # only rows the log decides
        assert {a for a in MATRIX if permit(role, a, pi)} >= gained  # nothing the PI's own standing lacks
        assert not gained & COVER_WITHHELD
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
    # the log's monthly check stays the PI's (D-1383: refused under a cover until the owner rules otherwise)
    assert cov.post("/studies/GZQO/team/check", data={"csrf": ccsrf, "result": "match"},
                    follow_redirects=False).status_code == 403  # fmt: skip
    assert not [e for e in _events(cb, "console.delegation") if e["detail"].get("action") == "compare"]
    # a task's owner is not a cover's to set (the owner's ruling, 2026-11-20: only as the person's own role allows)
    assert (
        cov.post(
            "/studies/GZQO/tasks/owner",
            data={"csrf": ccsrf, "kind": "cover_irb", "ref": "1", "owner": "crc"},
            follow_redirects=False,
        ).status_code
        == 403
    )
    # an act under the cover in the study (an event the console writes for the covering person): the actor is the
    # covering person, both names noted
    cb["h"].au.append("console.view", actor="console:cov", ruleset="GZQO", detail={"page": "week"})
    (ev,) = _events(cb, "console.view")
    assert ev["actor"] == "console:cov"
    assert ev["detail"]["covering_for"] == {"pi": "lpi", "pi_name": "Dr L", "name": "Dr C", "cover": 1}
    # the log stays the PI's: no entry added or changed, no cover entered, by the covering person
    for path, data in (
        ("/studies/GZQO/team", {"role": "sub_pi", "name": "X", "start": _days(0)}),
        ("/studies/GZQO/team/2", {"end": _days(1)}),
        ("/studies/GZQO/cover", {"username": "cov", "start": _days(0), "end": _days(1)}),
    ):
        assert cov.post(path, data={"csrf": ccsrf, **data}, follow_redirects=False).status_code == 403, path
    # after the cover: the PI's standing is gone
    cb["clock"]["now"] = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)  # the day after the last day
    assert not cb["h"].stand(cb["users"].get("cov"), "GZQO").pi
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

    def post(c: Any, k: str, owner: str) -> Any:
        return c.post(
            "/studies/GZQO/tasks/owner",
            data={"csrf": k, "kind": "delegation", "ref": "", "owner": owner},
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
def _case(lb: dict[str, Any], before_sync: Any = None) -> str:  # noqa: F811
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
    if before_sync is not None:
        before_sync(h)
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)
    return str(no)


def _sync(lb: dict[str, Any], hours: float) -> list[tuple[str, list[str], str, str]]:  # noqa: F811
    lb["clock"]["now"] = datetime(2026, 11, 10, 1, 0, tzinfo=UTC) + timedelta(hours=hours)
    c, csrf = login(lb["app"], "crc", PW)
    before = len(lb["backend"].notices)
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)
    return [n for n in lb["backend"].notices[before:] if "waited" in n[2] or "時間" in n[2] or "小時" in n[2]]


def test_an_unacknowledged_sae_is_told_once_at_n_hours_to_the_logs_sub_investigators_and_coordinators(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
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


def _hours(lb: dict[str, Any], n: str) -> None:  # noqa: F811
    """The console's own settings (``create_app(env=...)``), where the escalation reads its threshold (D2-L6)."""
    lb["app"].state.sae_env["TB_SAE_ESCALATE_HOURS"] = n


def test_the_threshold_is_the_declared_setting(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv("TB_SAE_ESCALATE_HOURS", "48")  # the process environment: not the console's settings (D2-L6)
    _hours(lb, "6")
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


# ---------------------------------------------------------------------------------------------- the reviews of 813c47eb
def test_two_covers_entered_at_once_never_share_a_day(team: TeamStore) -> None:
    """Item 1: two requests at once (two connections, the second run while the first is inside its transaction): the
    check and the insert are one transaction under the study's lock, so exactly one cover is stored."""
    _entry(team, "drc", "sub_pi")
    other = TeamStore()  # a second connection to the same store
    errors: list[Exception] = []
    real = team.db.transaction

    def second() -> None:
        try:
            other.add_cover(RS, username="drc", start=_days(2), end=_days(8), today=DAY, by="drpi", at=AT)
        except TeamError as exc:
            errors.append(exc)

    class AtInsert:
        """The first request's transaction: when it is about to insert (its check done), the second request runs."""

        def __init__(self, tx: Any) -> None:
            self.tx = tx

        def fetchone(self, text: str, params: Any = ()) -> Any:
            if text.startswith("INSERT INTO pi_cover"):
                t = threading.Thread(target=second)
                t.start()
                t.join(timeout=3)  # without the lock it inserts now; with it, it waits for this transaction
                threads.append(t)
            return self.tx.fetchone(text, params)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.tx, name)

    threads: list[threading.Thread] = []

    @contextmanager
    def interleaved() -> Any:
        with real() as tx:
            yield AtInsert(tx)

    team.db.transaction = interleaved  # type: ignore[method-assign]
    try:
        try:
            team.add_cover(RS, username="drb", start=_days(0), end=_days(6), today=DAY, by="drpi", at=AT)
        except TeamError as exc:
            errors.append(exc)
    finally:
        team.db.transaction = real  # type: ignore[method-assign]
    for t in threads:
        t.join(timeout=10)
    fresh = TeamStore()
    covers = fresh.covers(RS)
    fresh.close()
    assert len(covers) == 1, [(c.username, c.start, c.end) for c in covers]
    assert len(errors) == 1 and "another cover" in str(errors[0]), [(c.username, c.id) for c in covers]
    other.close()


def _edges(au: Any) -> list[dict[str, Any]]:
    return [kw["detail"] for _e, kw in au.rows]


class _Au:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **kw: Any) -> dict[str, Any]:
        self.rows.append((event, kw))
        return kw


def test_a_lapse_is_recorded_once_when_first_seen_and_the_cover_never_revives(team: TeamStore) -> None:
    """Item 2: no ``start`` for a cover that never took effect; a lapse written once, when first observed, with its
    reason and its true last day in effect; no ``end`` later; a PI named again does not bring the cover back."""
    from console.cover_pages import record_edges

    au = _Au()
    # (a) the PI changes before the cover's first day: never in effect, no start, a lapse with no last day
    c = team.add_cover(RS, username="drb", start=_days(3), end=_days(9), today=DAY, by="drpi", at=AT)
    pi = next(e for e in team.entries(RS) if e.username == "drpi")
    team.update_entry(RS, pi.id, tasks=(), end=_days(1), training_day=None, training_ref=None, by="stw", at=AT)
    _entry(team, "drnew", "pi", start=DAY + timedelta(days=2))
    assert record_edges(team, au, DAY + timedelta(days=4), AT, [RS]) == [f"{RS}:{c.id}:lapsed"]
    (ev,) = _edges(au)
    assert ev["action"] == "lapsed" and ev["reason"] == "pi_changed" and ev["last_day"] is None
    assert not ev["took_effect"]
    assert record_edges(team, au, DAY + timedelta(days=10), AT, [RS]) == []  # once; no end at the original end
    # the old PI named again: the lapsed cover stays ended (stored), a new cover must be entered
    _entry(team, "drpi", "pi", start=DAY + timedelta(days=5))
    assert not standing(team, _user("drb"), RS, DAY + timedelta(days=6)).pi
    stored = team.cover(RS, c.id)
    assert stored is not None and stored.lapse_reason == "pi_changed" and stored.last_day() == ""


def test_a_lapse_of_the_covering_persons_entry_names_its_true_last_day(team: TeamStore) -> None:
    from console.cover_pages import record_edges

    au = _Au()
    c = team.add_cover(OTHER, username="drb", start=_days(0), end=_days(9), today=DAY, by="drpi", at=AT)
    assert record_edges(team, au, DAY, AT, [OTHER]) == [f"{OTHER}:{c.id}:start"]  # in effect: its start
    drb = next(e for e in team.entries(OTHER) if e.username == "drb")
    team.update_entry(OTHER, drb.id, tasks=("refer",), end=_days(3), training_day=None, training_ref=None, by="drpi",
                      at=AT)  # fmt: skip
    # nobody looks until day 6: the lapse is written then, naming day 3 as the last day in effect
    assert record_edges(team, au, DAY + timedelta(days=6), AT, [OTHER]) == [f"{OTHER}:{c.id}:lapsed"]
    ev = _edges(au)[-1]
    assert (ev["action"], ev["reason"], ev["last_day"], ev["took_effect"]) == ("lapsed", "entry_ended", _days(3), True)
    assert record_edges(team, au, DAY + timedelta(days=12), AT, [OTHER]) == []  # no end at the original end
    # the entry made active again: the cover does not come back
    team.update_entry(OTHER, drb.id, tasks=("refer",), end=None, training_day=None, training_ref=None, by="drpi",
                      at=AT)  # fmt: skip
    assert not standing(team, _user("drb"), OTHER, DAY + timedelta(days=7)).pi


def test_a_cover_lapsed_but_not_yet_observed_gives_nothing_and_the_banner_agrees(cb: dict[str, Any]) -> None:
    h = cb["h"]
    h.team.add_cover("GZQO", username="cov", start=_days(0), end=_days(9), today=DAY, by="lpi", at=AT)
    lpi = next(e for e in h.team.entries("GZQO") if e.username == "lpi")
    h.team.update_entry("GZQO", lpi.id, tasks=(), end=_days(1), training_day=None, training_ref=None, by="stw", at=AT)
    _entry(h.team, "lpi", "pi", start=DAY + timedelta(days=3), name="Dr L")  # the same PI named again on day 3
    cb["clock"]["now"] = datetime(2026, 11, 24, 1, 0, tzinfo=UTC)  # day 4: nobody looked on day 2
    assert not h.stand(cb["users"].get("cov"), "GZQO").pi  # broken on day 2: never revived
    cov, _ = login(cb["app"], "cov", PW)
    assert 'data-testid="cover-banner"' not in cov.get("/studies/GZQO/team").text
    acts = [(e["detail"]["action"], e["detail"].get("last_day")) for e in _events(cb, "console.cover")]
    assert acts[-1] == ("lapsed", _days(1)) and [a for a, _d in acts].count("lapsed") == 1


def test_a_cover_carries_the_pis_clinical_rights_and_none_of_the_studys_administration(cb: dict[str, Any]) -> None:
    """Item 3: the allow-list at the one reading of the log; the routes of the withheld rights refuse a cover."""
    h = cb["h"]
    h.team.add_cover("GZQO", username="cov", start=_days(0), end=_days(6), today=DAY, by="lpi", at=AT)
    cov = cb["users"].get("cov")
    assert h.stand(cov, "GZQO").pi
    for a in ("task.screen", "task.approach", "task.refer", "task.enter_data", "command.SCREEN", "edc.view"):
        assert h.permit(cov, a, "GZQO").allowed, a
    for a in ("delegation.check", "study.state", "study.reopen", "irb.edit", "study.irb_text", "edc.switch_off",
              "edc.switch_on", "monitor.grant", "delegation.keep"):  # fmt: skip
        assert not h.permit(cov, a, "GZQO").allowed, a
        assert h.permit(cb["users"].get("lpi"), a, "GZQO").allowed or a == "irb.edit", a
    assert not h.may_approve(cov, "GZQO")  # the criteria's approval is the PI's by their own entry
    page, csrf = login(cb["app"], "cov", PW)
    assert page.post("/studies/GZQO/team/check", data={"csrf": csrf, "result": "match"},
                     follow_redirects=False).status_code == 403  # fmt: skip
    assert page.post("/studies/GZQO/state", data={"csrf": csrf, "state": "paused"},
                     follow_redirects=False).status_code in (403, 404)  # fmt: skip


def test_the_api_twins_refuse_another_studys_pi(cb: dict[str, Any]) -> None:
    """Item 4: create and end by the PI of another study, through /api/v1: refused."""
    b = cb
    b["users"].create("opi", "investigator", PW, "opi@hospa.test")
    _entry(b["h"].team, "opi", "pi", rs="RA-BIO", name="Dr O")
    _entry(b["h"].team, "cov", "sub_pi", rs="RA-BIO", name="Dr C")
    b["h"].team.add_cover("GZQO", username="cov", start=_days(1), end=_days(3), today=DAY, by="lpi", at=AT)
    token, _ = b["users"].new_session(b["users"].get("opi"), via="api")
    from fastapi.testclient import TestClient

    api = TestClient(b["app"], headers={"Authorization": f"Bearer {token}"})
    r = api.post("/api/v1/studies/GZQO/cover", json={"username": "cov", "start": _days(5), "end": _days(6)})
    assert r.status_code in (403, 404), r.text
    r = api.post("/api/v1/studies/GZQO/cover/1/end")
    assert r.status_code in (403, 404), r.text
    assert [c.ended_on for c in b["h"].team.covers("GZQO")] == [None] and len(b["h"].team.covers("GZQO")) == 1


def test_a_tasks_owner_is_set_only_on_a_task_of_that_study_and_shown_lapsed_after_the_owners_entry(
    cb: dict[str, Any],
) -> None:
    """Item 9: (kind, ref) must be one of the study's tasks today; an owner whose own entry ended stays, flagged."""
    lpi, csrf = login(cb["app"], "lpi", PW)
    for kind, ref in (("call", "a1b2c3d4e5f6a001"), ("cover_irb", "7"), ("refer", "99")):
        r = lpi.post("/studies/GZQO/tasks/owner", data={"csrf": csrf, "kind": kind, "ref": ref, "owner": "crc"},
                     follow_redirects=False)  # fmt: skip
        assert r.status_code == 400, (kind, ref)
    cb["h"].team.set_task_owner("GZQO", kind="delegation", ref="", owner="crc", day=DAY, by="lpi", at=AT)
    crc = next(e for e in cb["h"].team.entries("GZQO") if e.username == "crc")
    cb["h"].team.update_entry("GZQO", crc.id, tasks=(), end=_days(0), training_day=None, training_ref=None, by="lpi",
                              at=AT)  # fmt: skip
    cb["clock"]["now"] = datetime(2026, 11, 21, 1, 0, tzinfo=UTC)
    crx, _ = login(cb["app"], "crx", PW)
    page = crx.get("/home").text
    assert 'data-testid="task-owner"' in page and 'data-testid="task-owner-lapsed"' in page and "Ms R" in page


def _second_case(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "ae2", "values": FATAL, "by": "rc:read"})
    c, csrf = login(lb["app"], "crc", PW)
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)


def test_two_cases_told_the_same_day_are_two_mails_with_distinct_keys(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 5: the orchestrator drops a repeat of (day, kind, recipients, subject); each case's mail has its own."""
    from orchestrator.core import send_key

    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    no = _case(lb)
    _second_case(lb)
    told = _sync(lb, 24.5)
    assert len(told) == 4, [n[2] for n in told]  # two cases, two people each
    keys = {send_key("notice:2026-11-11", n[0], list(n[1]), n[2], []) for n in told}
    assert len(keys) == 4  # no mail would be dropped as a duplicate
    full = sorted(n[2] for n in told if n[1] == ["crc@hospa.test"])
    assert full == [f"[TrialBox] SAE GZQO {no} ae1 has waited 24 hours for the PI",
                    f"[TrialBox] SAE GZQO {no} ae2 has waited 24 hours for the PI"]  # fmt: skip
    short = [n[2] for n in told if n[1] == ["subi@hospa.test"]]
    assert all(no not in x and "register case" in x for x in short) and len(set(short)) == 2
    body = next(n[3] for n in told if n[1] == ["crc@hospa.test"])
    assert "still not acknowledged by the PI" in body and "New serious adverse event" not in body


def test_a_round_that_reaches_nobody_is_not_final_and_is_tried_again(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 6: the mail gateway down: no ``escalated`` row, a bounded retry note, the next round mails."""
    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    no = _case(lb)
    real = lb["backend"].send_notice

    def down(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("gateway down")

    lb["backend"].send_notice = down
    for h in (24.5, 25.5, 26.5, 27.5, 28.5):
        assert _sync(lb, h) == []
    from console.saerecord import SaeStore

    store = SaeStore()
    try:
        trail = [t["action"] for t in store.trail("GZQO", no, "ae1")]
    finally:
        store.close()
    assert "escalated" not in trail and trail.count("escalate_retry") == 3  # bounded
    lb["backend"].send_notice = real
    assert len(_sync(lb, 29.5)) == 2  # the next round reaches them
    assert _sync(lb, 30.5) == []
    rows = [json.loads(x) for f in sorted(lb["backend"].audit_dir.glob("*.jsonl")) for x in f.read_text().splitlines()
            if x and json.loads(x).get("event") == "console.sae"]  # fmt: skip
    acts = [r["detail"]["action"] for r in rows if r["detail"].get("record") == no]
    assert acts.count("escalate_unreached") == 3 and acts.count("escalated") == 1
    (un,) = [r["detail"] for r in rows if r["detail"].get("action") == "escalate_unreached"][:1]
    assert un["sent"] == 0 and sorted(un["failed"]) == ["crc", "subi"]


def test_a_later_change_of_n_does_not_tell_a_case_again(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Item 7: once per case, whatever the threshold."""
    _hours(lb, "6")
    _case(lb)
    assert len(_sync(lb, 6.5)) == 2
    _hours(lb, "12")
    assert _sync(lb, 12.5) == [] and _sync(lb, 48) == []


# ---------------------------------------------------------------------------------------------- 9f-3: told at once
def _at_once(lb: dict[str, Any]) -> list[tuple[str, list[str], str, str]]:  # noqa: F811
    return [n for n in lb["backend"].notices if "SAE GZQO" in n[2] and "waited" not in n[2]]


def _audit(lb: dict[str, Any], action: str) -> list[dict[str, Any]]:  # noqa: F811
    rows = [json.loads(x) for f in sorted(lb["backend"].audit_dir.glob("*.jsonl")) for x in f.read_text().splitlines()
            if x and json.loads(x).get("event") == "console.sae"]  # fmt: skip
    return [r["detail"] for r in rows if r["detail"].get("action") == action]


def _cover_for(who: str, start: int, end: int, rs: str = RS, entered: int = 0) -> Any:
    """``before_sync`` of ``_case``: the PI (``pi``) enters a cover of ``who`` from day ``start`` to day ``end`` counted
    from the case's day (2026-11-10), entered ``entered`` days from it."""
    day = date(2026, 11, 10)

    def make(h: Any) -> None:
        h.team.add_cover(rs, username=who, start=(day + timedelta(days=start)).isoformat(),
                         end=(day + timedelta(days=end)).isoformat(), today=day + timedelta(days=entered), by="pi",
                         at=AT)  # fmt: skip

    return make


def test_a_new_case_is_told_at_once_to_the_pi_and_to_the_person_holding_the_cover(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)
    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    no = _case(lb, _cover_for("subi", 0, 2))  # in effect on the case's day
    pi_mail, cover_mail = _at_once(lb)  # in addition to the PI, never instead: a send of its own, after the PI's
    assert pi_mail[1] == ["pi@hospa.test"] and cover_mail[1] == ["subi@hospa.test"]
    assert pi_mail[2] == cover_mail[2] and pi_mail[3] == cover_mail[3]  # the same notice
    assert no in pi_mail[2] and "ae1" in pi_mail[2]  # the subject carries the case: two cases are two mails
    (ev,) = _audit(lb, "office_copy")
    assert ev["pi"] == "pi" and ev["to"] == "pi@hospa.test"  # each send audited as it went
    (cov_ev,) = _audit(lb, "cover_told")
    assert cov_ev["covering"] == "subi" and cov_ev["pi"] == "pi" and cov_ev["to"] == "subi@hospa.test"

    from console.saerecord import SaeStore

    reg = SaeStore()
    assert reg.told_cover_names(RS, no, "ae1") == {"subi"}
    # a second case the same day is its own mail with its own subject
    _second_case(lb)
    mails = _at_once(lb)
    assert len(mails) == 4 and len({m[2] for m in mails}) == 2  # each case: the PI's mail and the cover's
    # the escalation of the first case: the covering person is not mailed again (told at once), the others are
    told = _sync(lb, 24.5)
    assert sorted(n[1][0] for n in told) == ["crc@hospa.test", "crc@hospa.test"]  # crc only: two cases
    assert all("subi@hospa.test" not in n[1] for n in told)
    esc = _audit(lb, "escalated")
    assert len(esc) == 2 and all(e["already_told"] == ["subi"] and e["to"] == "crc" for e in esc)


@pytest.mark.parametrize(
    "case",
    ["the day after the cover ended", "a lapsed cover", "another study's cover", "no cover"],
)
def test_outside_a_cover_only_the_pi_is_told_at_once(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)

    def before(h: Any) -> None:
        if case == "the day after the cover ended":
            _cover_for("subi", -5, -1, entered=-5)(h)  # its last day was yesterday
        elif case == "a lapsed cover":
            _cover_for("subi", 0, 2)(h)
            e = next(x for x in h.team.entries(RS) if x.username == "subi")
            h.team.update_entry(RS, e.id, tasks=(), end="2026-11-09", training_day=None, training_ref=None, by="pi",
                                at=AT)  # fmt: skip  # the covering person's own entry ended: the cover lapsed
        elif case == "another study's cover":
            _entry(h.team, "pi", "pi", rs=OTHER)
            _cover_for("subo", 0, 2, rs=OTHER)(h)

    _case(lb, before)
    (mail,) = _at_once(lb)
    assert mail[1] == ["pi@hospa.test"]
    (ev,) = _audit(lb, "office_copy")
    assert "covering" not in ev and lb["app"].state.helpers.covering_now(RS) is None


# ---------------------------------------------------------------------------------------------- the reviews D1 and D2
#: every file of a study's patients that leaves TrialBox (the owner's ruling, 2026-11-20: a cover gives no export)
EXPORTS = (
    "/studies/GZQO/export.csv",
    "/studies/GZQO/export.xlsx",
    "/studies/GZQO/screening-log.xlsx",
    "/studies/GZQO/edc/export.odm.xml",
    "/studies/GZQO/edc/copy.csv",
    "/pilot/registry/GZQO/export.xlsx?reason=care&note=x",
    "/api/v1/studies/GZQO/export/csv",
)


def test_a_cover_opens_no_export_and_the_clinical_actions_it_is_for_do_open(lb: dict[str, Any]) -> None:  # noqa: F811
    """D1-H1: the seven export URLs and the EDC export and copy rights, without a cover (403) and inside one (still
    403), while the clinical pages and rows the cover is for open inside it."""
    from fastapi.testclient import TestClient

    from tests.console.test_console_app import name_pi

    name_pi(lb, "pi")
    h = lb["app"].state.helpers
    lb["users"].create("cov", "investigator", PW, "cov@hospa.test")
    _entry(h.team, "cov", "sub_pi", name="Dr C")  # no task ticked
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    cov, _ = login(lb["app"], "cov", PW)
    token, _ = lb["users"].new_session(lb["users"].get("cov"), via="api")
    api = TestClient(lb["app"], headers={"Authorization": f"Bearer {token}"})
    u = lb["users"].get("cov")

    def walk() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in EXPORTS:
            r = (api if p.startswith("/api/") else cov).get(p, follow_redirects=False)
            out[p] = (r.status_code, "attachment" in r.headers.get("content-disposition", ""))
        out["rows"] = {a: h.permit(u, a, "GZQO").allowed for a in ("edc.export", "edc.copy")}
        out["export_ok"] = (h.export_ok(u, "GZQO"), h.export_ok(u, "GZQO", ("screen", "enter_data")))
        return out

    def clinical() -> dict[str, Any]:
        return {"entry": cov.get("/studies/GZQO/entry").status_code,
                "records": api.get("/api/v1/studies/GZQO/records").status_code,
                "rows": {a: h.permit(u, a, "GZQO").allowed for a in ("task.screen", "task.enter_data", "edc.view")}}  # fmt: skip

    shut = {p: (403, False) for p in EXPORTS} | {"rows": {"edc.export": False, "edc.copy": False},
                                                 "export_ok": (False, False)}  # fmt: skip
    assert walk() == shut  # without a cover
    assert clinical()["entry"] == 403
    today = h.today()
    h.team.add_cover("GZQO", username="cov", start=today.isoformat(), end=(today + timedelta(days=3)).isoformat(),
                     today=today, by="pi", at=AT)  # fmt: skip
    assert h.stand(u, "GZQO").pi  # the cover is in effect
    inside = walk()
    assert inside == shut, inside  # inside the cover: still no export
    assert clinical() == {"entry": 200, "records": 200,
                          "rows": {"task.screen": True, "task.enter_data": True, "edc.view": True}}  # fmt: skip
    assert not [e for e in _events(lb, "console.data_export") if e["actor"] == "console:cov"]
    assert not [e for e in _events(lb, "console.registry") if e["actor"] == "console:cov"
                and e["detail"].get("action") in ("export", "export_requested")]  # fmt: skip


def test_a_cover_sets_no_tasks_owner_and_does_not_mark_its_own_cover_reported(cb: dict[str, Any]) -> None:
    """D1-H2: beyond the covering person's own role (a sub-investigator sets no owner and marks no IRB task), a cover
    adds nothing; the coordinator on the log still may (the ruling about their own role)."""
    from fastapi.testclient import TestClient

    lpi, csrf = login(cb["app"], "lpi", PW)
    assert lpi.post("/studies/GZQO/cover", data={"csrf": csrf, "username": "cov", "start": _days(0),
                                                  "end": _days(6)}, follow_redirects=False).status_code == 303  # fmt: skip
    assert cb["h"].stand(cb["users"].get("cov"), "GZQO").pi
    cov, ccsrf = login(cb["app"], "cov", PW)
    owner = {"kind": "cover_irb", "ref": "1", "owner": "crc"}
    assert (
        cov.post("/studies/GZQO/tasks/owner", data={"csrf": ccsrf, **owner}, follow_redirects=False).status_code == 403
    )
    assert cov.post("/studies/GZQO/cover/1/irb", data={"csrf": ccsrf}, follow_redirects=False).status_code == 403
    token, _ = cb["users"].new_session(cb["users"].get("cov"), via="api")
    api = TestClient(cb["app"], headers={"Authorization": f"Bearer {token}"})
    assert api.post("/api/v1/studies/GZQO/tasks/owner", json=owner).status_code == 403
    assert api.post("/api/v1/studies/GZQO/cover/1/irb").status_code == 403
    assert 'data-testid="cover-irb-1"' not in cov.get("/studies/GZQO/team").text
    assert not _events(cb, "console.task_owner") and cb["h"].team.cover("GZQO", 1).irb_told_on is None
    crc, kcsrf = login(cb["app"], "crc", PW)  # a coordinator on the study's log: by their own role
    assert (
        crc.post("/studies/GZQO/tasks/owner", data={"csrf": kcsrf, **owner}, follow_redirects=False).status_code == 303
    )
    assert crc.post("/studies/GZQO/cover/1/irb", data={"csrf": kcsrf}, follow_redirects=False).status_code == 303


def test_a_refused_cover_mailbox_never_stops_the_pis_and_the_offices_notice(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1-H3: the covering person's notice is a send of its own; an address the orchestrator refuses loses only that
    mail, and each send's outcome is audited as it was."""
    from console.backend import Refused
    from console.saerecord import SaeStore

    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "office@hospa.test")
    real = lb["backend"].send_notice

    def gate(kind: str, to: list[str], subject: str, body: str, principal: str) -> str:
        if any(not a.endswith("@hospa.test") for a in to):  # the orchestrator's /notices: hospital addresses only
            raise Refused("notices go to hospital addresses only")
        return str(real(kind, to, subject, body, principal))

    lb["backend"].send_notice = gate

    def before(h: Any) -> None:
        _cover_for("subi", 0, 2)(h)
        lb["users"].db.execute("UPDATE users SET mailbox = 'subi@home-mail.test' WHERE username = 'subi'")

    no = _case(lb, before)
    (mail,) = _at_once(lb)
    assert sorted(mail[1]) == ["office@hospa.test", "pi@hospa.test"]  # the PI and the office are told
    (ev,) = _audit(lb, "office_copy")
    assert ev["to"] == "office@hospa.test, pi@hospa.test" and ev["pi"] == "pi"
    (bad,) = _audit(lb, "cover_told_failed")
    assert bad["covering"] == "subi" and bad["error"] == "Refused" and not _audit(lb, "cover_told")
    assert SaeStore().told_cover_names(RS, no, "ae1") == set()  # not told: the escalation still reaches them


def test_the_immediate_notice_goes_to_a_cover_only_while_its_account_holds_it(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1-M1: an account that lost the study (scope) or the investigator role is not told as the PI's cover."""
    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)
    seen: dict[str, Any] = {}

    def before(h: Any) -> None:
        _cover_for("subi", 0, 2)(h)
        lb["users"].set_scope("subi", "hospital", "RA-BIO")  # no longer sees GZQO
        seen["now"] = h.covering_now("GZQO")
        seen["banner"] = h.cover_view("banner", SimpleNamespace(user=lb["users"].get("pi")), "GZQO")

    _case(lb, before)
    assert seen == {"now": None, "banner": None}
    (mail,) = _at_once(lb)
    assert mail[1] == ["pi@hospa.test"] and not _audit(lb, "cover_told")


def test_a_cover_whose_role_changed_is_not_told(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """D1-M1 (b): a directory refresh made the covering person a coordinator: no cover's notice."""
    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)

    def before(h: Any) -> None:
        _cover_for("subi", 0, 2)(h)
        lb["users"].db.execute("UPDATE users SET role = 'coordinator' WHERE username = 'subi'")

    _case(lb, before)
    (mail,) = _at_once(lb)
    assert mail[1] == ["pi@hospa.test"] and lb["app"].state.helpers.covering_now(RS) is None


def test_no_cover_takes_effect_without_its_add_event(cb: dict[str, Any]) -> None:
    """D1-M2: the ``add`` event is written inside the cover's transaction: when it cannot be written, no cover."""
    h = cb["h"]
    inner = h.au._inner
    real = inner.append

    def failing(event: str, **kw: Any) -> Any:
        if event == "console.cover" and (kw.get("detail") or {}).get("action") == "add":
            raise OSError("disk full (emulated)")
        return real(event, **kw)

    inner.append = failing
    lpi, csrf = login(cb["app"], "lpi", PW)
    try:
        with pytest.raises(OSError):
            lpi.post("/studies/GZQO/cover", data={"csrf": csrf, "username": "cov", "start": _days(0),
                                                  "end": _days(6)}, follow_redirects=False)  # fmt: skip
    finally:
        inner.append = real
    assert h.team.covers(RS) == [] and not h.stand(cb["users"].get("cov"), "GZQO").pi
    assert not _events(cb, "console.cover")
    r = lpi.post("/studies/GZQO/cover", data={"csrf": csrf, "username": "cov", "start": _days(0), "end": _days(6)},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and [e["detail"]["action"] for e in _events(cb, "console.cover")] == ["add", "start"]


def test_the_cover_help_says_clinical_rights_no_export_and_only_the_pi(cb: dict[str, Any]) -> None:
    """D1-M3: the cover card's help says what a cover carries, in each language, and who can be covered."""
    from console.i18n import translate

    words = {"en": ("clinical rights", "no export", "Only the PI can be covered"),
             "ja": ("診療上の権限", "エクスポート", "代行できるのは治験責任医師だけ"),
             "zh-TW": ("臨床權限", "匯出", "只有試驗主持人可以被代理")}  # fmt: skip
    for lang, want in words.items():
        text = translate(lang, "cover.help", n=COVER_MAX_DAYS)
        assert all(w in text for w in want), (lang, text)
    lpi, _ = login(cb["app"], "lpi", PW)
    assert "clinical rights" in lpi.get("/studies/GZQO/team").text


def test_an_acknowledgement_after_the_check_stops_the_escalation(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2-M1: the PI acknowledges on another connection after the round's first look, before any mail: the
    acknowledgement is read again under the case's lock, so nobody is told and no ``escalated`` row is written."""
    from console import saerecord

    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    no = _case(lb)
    real = saerecord.SaeStore.case_no
    done = {"n": 0}

    def acked_meanwhile(self: Any, rs: str, record: str, event: str) -> Any:
        if not done["n"]:
            done["n"] = 1
            other = saerecord.SaeStore()
            try:
                other.db.execute("UPDATE sae_case SET pi_ack_by = 'pi', pi_ack_at = ? WHERE ruleset = 'GZQO'", (AT,))
            finally:
                other.close()
        return real(self, rs, record, event)

    monkeypatch.setattr(saerecord.SaeStore, "case_no", acked_meanwhile)
    assert _sync(lb, 24.5) == [] and done["n"] == 1
    store = saerecord.SaeStore()
    try:
        assert not [t for t in store.trail(RS, no, "ae1") if t["action"].startswith("escalat")]
    finally:
        store.close()


def test_a_crash_between_the_mails_and_the_mark_mails_nobody_again_and_the_audit_names_them(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2-M2: the people are claimed before the mails; each mail that went is audited at once; a round cut off before
    its closing row is closed by a later round (``interrupted``), which mails nobody again."""
    from console import saerecord

    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    no = _case(lb)
    real = saerecord.SaeStore._trail
    state = {"crashed": False}

    def trail(self: Any, tx: Any, rs: str, record: str, event: str, action: str, *a: Any, **k: Any) -> Any:
        if action == "escalated" and not state["crashed"]:
            state["crashed"] = True
            raise RuntimeError("synthetic crash between the mails and the mark")
        return real(self, tx, rs, record, event, action, *a, **k)

    monkeypatch.setattr(saerecord.SaeStore, "_trail", trail)
    first = _sync(lb, 24.5)
    assert len(first) == 2 and state["crashed"]
    sent = sorted(d["to"] for d in _audit(lb, "escalate_sent") if d["record"] == no)
    assert sent == ["crc", "subi"]  # the audit names each mail that went, though the round's closing row was lost
    assert _sync(lb, 24.6) == []  # a round still within ESCALATE_STALE of the claim: nothing
    assert _sync(lb, 25.5) == [] and _sync(lb, 48) == []  # never again
    (esc,) = _audit(lb, "escalated")
    assert esc["interrupted"] is True and sorted(esc["claimed"]) == ["crc", "subi"]


def test_an_old_case_is_told_its_real_waiting_time(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """D2-M3: the first round after the update tells a case of ten days its true age, never "24 hours"."""
    monkeypatch.delenv("TB_SAE_ESCALATE_HOURS", raising=False)
    _case(lb)
    told = _sync(lb, 240.5)
    assert len(told) == 2 and all("240 hours" in n[2] and "240 hours" in n[3] for n in told), [n[2] for n in told]
    assert all(" 24 hours" not in n[2] for n in told)
    (esc,) = _audit(lb, "escalated")
    assert esc["hours"] == 24 and esc["waited_hours"] == 240


def test_a_disabled_account_cannot_be_named_a_tasks_owner(cb: dict[str, Any]) -> None:
    """D2-L1."""
    cb["users"].disable("crc")
    lpi, csrf = login(cb["app"], "lpi", PW)
    r = lpi.post("/studies/GZQO/tasks/owner", data={"csrf": csrf, "kind": "delegation", "ref": "", "owner": "crc"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 400 and not _events(cb, "console.task_owner")


def test_the_cover_irb_task_and_the_owner_forms_are_on_the_opening_page_under_the_home_flag(cb: dict[str, Any]) -> None:
    """D2-L2: with ``layout.home_today`` on, the cover's IRB task is a "Needs you today" line with its owner form and
    its done button, as on the classic page."""
    from console import home_today as ht
    from console import phone
    from tb_common import flags as fl

    cb["h"].team.add_cover("GZQO", username="cov", start=_days(0), end=_days(6), today=DAY, by="lpi", at=AT)
    fl.Flags(audit=cb["audit"]).set(ht.FLAG, "on", actor="console:admin", reason="9f-3 test (D-1383)")
    fl.clear_cache()
    phone.clear_cache()
    phone.read_now()
    try:
        crc, kcsrf = login(cb["app"], "crc", PW)
        page = crc.get("/home").text
        assert 'data-testid="today"' in page  # the flag's page
    finally:
        fl.clear_cache()
        phone.clear_cache()
    assert 'data-testid="today-cover_irb"' in page and 'data-testid="task-own-cover_irb"' in page
    assert 'action="/studies/GZQO/cover/1/irb"' in page and 'action="/studies/GZQO/tasks/owner"' in page
    r = crc.post("/studies/GZQO/tasks/owner", data={"csrf": kcsrf, "kind": "cover_irb", "ref": "1", "owner": "cov"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303


def test_the_api_cover_list_says_in_effect_only_while_the_cover_gives_it(cb: dict[str, Any]) -> None:
    """D1-L1: a lapse not yet observed is not ``in_effect``."""
    from fastapi.testclient import TestClient

    t = cb["h"].team
    t.add_cover(RS, username="cov", start=_days(0), end=_days(6), today=DAY, by="lpi", at=AT)
    token, _ = cb["users"].new_session(cb["users"].get("lpi"), via="api")
    api = TestClient(cb["app"], headers={"Authorization": f"Bearer {token}"})
    assert [c["in_effect"] for c in api.get("/api/v1/studies/GZQO/cover").json()["covers"]] == [True]
    e = next(x for x in t.entries(RS) if x.username == "cov")
    t.update_entry(RS, e.id, tasks=(), end=(DAY - timedelta(days=1)).isoformat(), training_day=None, training_ref=None,
                   by="lpi", at=AT)  # fmt: skip
    assert [c["in_effect"] for c in api.get("/api/v1/studies/GZQO/cover").json()["covers"]] == [False]


def test_two_owner_changes_at_once_each_audit_the_true_owner_before(cb: dict[str, Any]) -> None:
    """D2-L7: the read of the owner before and the new row are one transaction under a lock per study."""
    t = cb["h"].team
    t.set_task_owner(RS, kind="delegation", ref="", owner="crc", day=DAY, by="lpi", at=AT)
    others = [TeamStore() for _ in range(2)]
    befores: list[str] = []
    gate = threading.Barrier(2)

    def change(store: TeamStore, who: str) -> None:
        gate.wait()
        before, _after = store.set_task_owner(RS, kind="delegation", ref="", owner=who, day=DAY, by="lpi", at=AT)
        befores.append(before.owner if before else "")

    ts = [threading.Thread(target=change, args=(s, w)) for s, w in zip(others, ("cov", "lpi"), strict=True)]
    for th in ts:
        th.start()
    for th in ts:
        th.join(60)
    for s in others:
        s.close()
    assert sorted(befores) in (["cov", "crc"], ["crc", "lpi"])  # one saw crc, the other the first one's owner
