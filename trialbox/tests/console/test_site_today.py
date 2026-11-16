"""D-270 (integrity review DI-1, DI-2): the console's "today" is the site's calendar date, never the UTC date.

At 00:30 in Tokyo the UTC date is still yesterday. A delegation that starts today must count, one that ended
yesterday must not, and the 07:00 / 07:30 notices must be built for the site's day (a Monday digest on Monday).
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from console import notify, timers
from console.timefmt import SiteZoneError, site_zone
from tb_common.config import ConfigError, load_settings

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    PILOT_ENV,
    _done_screen,
    _ulid,
    box,
    login,
)
from tests.console.test_edc_pages import PW as EDC_PW
from tests.console.test_edc_pages import _csrf, _ready, eb  # noqa: F401
from tests.console.test_lifecycle_pages import PW as LIFE_PW
from tests.console.test_lifecycle_pages import _save, lb  # noqa: F401
from tests.console.test_role_pages import _user

CONSOLE = Path(__file__).resolve().parents[2] / "services" / "console"
EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "settings.example.yaml"
# 00:30 on 2026-11-10 at the site; in UTC it is still 2026-11-09
ZONES = [
    ("Asia/Tokyo", datetime(2026, 11, 9, 15, 30, tzinfo=UTC)),
    ("Asia/Taipei", datetime(2026, 11, 9, 16, 30, tzinfo=UTC)),
]


@pytest.fixture
def zone(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Sets the site's zone before the box is built; gives the instant that is 00:30 on 2026-11-10 there."""
    name, half_past_midnight = request.param
    monkeypatch.setenv("TB_TZ", name)
    assert isinstance(half_past_midnight, datetime)
    return half_past_midnight


def _entry(h: Any, user: str, role: str, start: str, end: str | None, tasks: tuple[str, ...] = ()) -> None:
    h.team.add_entry("GZQO", username=user, name=user, role=role, tasks=tasks, start=start, end=end,
                     training_day="2026-01-01", training_ref="GCP-1", by="admin", at="2026-01-01T00:00:00+00:00")  # fmt: skip


@pytest.mark.parametrize("zone", ZONES, indirect=True, ids=["tokyo", "taipei"])
def test_a_delegation_counts_from_0000_on_its_start_day(zone: datetime, box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(961))
    h = box["app"].state.helpers
    new_pi = _user(box, "drsato", "investigator")
    _entry(h, "drold", "pi", "2026-01-01", None)  # the PI until today
    _entry(h, "drsato", "pi", "2026-11-10", None)  # the PI from today
    h.clock = lambda: zone
    assert h.clock().date() == date(2026, 11, 9)  # the UTC date is still the 9th
    assert new_pi.get("/studies/GZQO/candidates").status_code == 200
    assert new_pi.get("/studies/GZQO/week").status_code == 200


@pytest.mark.parametrize("zone", ZONES, indirect=True, ids=["tokyo", "taipei"])
def test_an_ended_delegation_stops_at_0000_the_day_after(zone: datetime, box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(961))
    h = box["app"].state.helpers
    ended = _user(box, "drkato", "investigator")
    _entry(h, "drold", "pi", "2026-01-01", None)
    _entry(h, "drkato", "sub_pi", "2026-01-01", "2026-11-09", ("screen",))  # the last day was yesterday
    h.clock = lambda: zone.replace(day=8)  # 00:30 on the last day: still delegated
    assert ended.get("/studies/GZQO/candidates").status_code == 200
    h.clock = lambda: zone  # 00:30 on the day after: over, though the UTC date is still the last day
    assert h.clock().date() == date(2026, 11, 9)
    assert ended.get("/studies/GZQO/candidates").status_code == 403
    assert ended.get("/studies/GZQO/week").status_code == 403


@pytest.mark.parametrize("zone", ZONES, indirect=True, ids=["tokyo", "taipei"])
def test_e10_reads_the_log_on_the_site_day(zone: datetime, eb: dict[str, Any]) -> None:  # noqa: F811
    """E-10: only a PI the log names today turns EDC prefill on. The PI whose entry starts today is that PI."""
    _ready(eb, on=False)
    h = eb["app"].state.helpers
    eb["users"].create("drnew", "investigator", EDC_PW, "drnew@hospa.test")
    _entry(h, "drnew", "pi", "2026-11-10", None)
    h.clock = lambda: zone
    pi, _ = login(eb["app"], "drnew", EDC_PW)
    page = pi.get("/studies/GZQO/edc").text
    r = pi.post("/studies/GZQO/edc/switch", data={"csrf": _csrf(page), "on": "1", "kind": "sponsor_letter",
                                                  "reference": "SPN-1", "ack_date": "2026-11-01", "dataflow_ref": "DMP §5", "reentry_pages": "30",
                                                  "reentry_accuracy": "99"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    assert eb["svc"].store.switch("GZQO").on


@pytest.mark.parametrize(
    ("tz", "n1_at", "n2_at"),
    [  # Monday 2026-11-09 07:00 and 07:30 at the site; Sunday in UTC
        ("Asia/Tokyo", datetime(2026, 11, 8, 22, 0, tzinfo=UTC), datetime(2026, 11, 8, 22, 30, tzinfo=UTC)),
        ("Asia/Taipei", datetime(2026, 11, 8, 23, 0, tzinfo=UTC), datetime(2026, 11, 8, 23, 30, tzinfo=UTC)),
    ],
    ids=["tokyo", "taipei"],
)
def test_the_morning_timers_run_for_the_site_day(
    tz: str,
    n1_at: datetime,
    n2_at: datetime,
    monkeypatch: pytest.MonkeyPatch,
    box: dict[str, Any],  # noqa: F811
) -> None:
    h = box["app"].state.helpers
    h.bk.cfg = SimpleNamespace(env=SimpleNamespace(tz=tz))
    calls: list[tuple[date, tuple[str, ...]]] = []

    def send_all(_h: Any, day: date, kinds: tuple[str, ...], by: str) -> list[Any]:
        calls.append((day, kinds))
        return []

    monkeypatch.setattr(notify, "send_all", send_all)
    jobs = timers.jobs(h)
    h.clock = lambda: n1_at
    jobs["notice_n1"]()
    h.clock = lambda: n2_at
    jobs["notice_n2"]()
    monday = date(2026, 11, 9)
    assert monday.weekday() == 0 and calls == [(monday, ("N1",)), (monday, ("N2",))]


def test_the_monday_digest_goes_on_monday(lb: dict[str, Any]) -> None:  # noqa: F811
    """DI-2: at 07:30 JST on Monday the UTC date is Sunday, and a digest for a Sunday is never built."""
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", LIFE_PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-01", "ic_version": "v1", "ic_copy": "1"})
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-01", "en_eligible": "1"})
    lb["oc"].put("/studies/GZQO/schedule", json={"visits": [{"visit": "v1", "day": 7, "before": 1, "after": 1}],
                                                 "by": "crc"})  # fmt: skip
    h = lb["app"].state.helpers
    h.bk.cfg = SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo"))
    lb["clock"]["now"] = datetime(2026, 11, 8, 22, 30, tzinfo=UTC)  # Monday 2026-11-09 07:30 in Tokyo
    sent: Any = timers.jobs(h)["notice_n2"]()
    digest = [n for n in sent if n.kind == "N2" and n.username == "crc"]
    assert len(digest) == 1 and digest[0].day == "2026-11-09"
    assert "Study visits today: 1" in digest[0].body  # v1's window ends on Monday the 9th


def test_the_admin_button_sends_for_the_site_day(monkeypatch: pytest.MonkeyPatch, box: dict[str, Any]) -> None:  # noqa: F811
    h = box["app"].state.helpers
    h.bk.cfg = SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo"))
    h.clock = lambda: datetime(2026, 11, 8, 22, 30, tzinfo=UTC)
    days: list[date] = []

    def send_all(_h: Any, day: date, *a: Any, **kw: Any) -> list[Any]:
        days.append(day)
        return []

    monkeypatch.setattr(notify, "send_all", send_all)
    c, csrf = login(box["app"])
    assert c.post("/ops/notices", data={"csrf": csrf}).status_code == 200
    assert days == [date(2026, 11, 9)]


def test_the_admin_pages_count_30_days_from_the_site_day(box: dict[str, Any]) -> None:  # noqa: F811
    """An account that ends on the 30th day from the site's today is listed (home page and Admin > Health)."""
    h = box["app"].state.helpers
    h.bk.cfg = SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo"))
    box["users"].create("cra1", "cro", "cro-password-0000001", "cra1@cro.test")
    box["users"].set_scope("cra1", affiliation="cro", studies="GZQO", expires="2026-12-10")
    h.clock = lambda: datetime(2026, 11, 9, 15, 30, tzinfo=UTC)  # 00:30 on 2026-11-10 in Tokyo; + 30 days = 12-10
    c, _ = login(box["app"])
    for path in ("/home", "/admin"):
        assert "cra1 (2026-12-10)" in c.get(path).text, path


@pytest.mark.parametrize("zone", ZONES, indirect=True, ids=["tokyo", "taipei"])
def test_an_account_ends_at_0000_the_day_after_its_end_date(zone: datetime, box: dict[str, Any]) -> None:  # noqa: F811
    """An account's end date is a site day: the last day works to midnight there, the next day does not."""
    users = box["users"]
    pw = "cro-password-0000001"
    users.create("cra1", "cro", pw, "cra1@cro.test")
    users.set_scope("cra1", affiliation="cro", studies="GZQO", expires="2026-11-09")
    users.create("cra2", "cro", pw, "cra2@cro.test")
    users.set_scope("cra2", affiliation="cro", studies="GZQO", expires="2026-11-10")
    users.clock = lambda: zone  # 00:30 on 2026-11-10 at the site; still 11-09 in UTC
    assert users.authenticate("cra1", pw) is None  # ended yesterday
    assert users.authenticate("cra2", pw) is not None  # its last day is today
    users.clock = lambda: zone.replace(day=8)  # 00:30 on 11-09, cra1's last day
    assert users.authenticate("cra1", pw) is not None


# ------------------------------------------------------------------------------- the zone itself: never a silent UTC
def test_a_wrong_or_missing_site_zone_is_a_configuration_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_TZ", raising=False)  # tests/conftest.py sets it (D-315); this box has no zone at all
    bad = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Mars/Olympus")))
    with pytest.raises(SiteZoneError, match="Mars/Olympus"):
        site_zone(bad)
    unset = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz=""), settings=SimpleNamespace(site=None)))
    with pytest.raises(SiteZoneError, match="site.tz is not set"):
        site_zone(unset)
    # the settings file: no site.tz, or a name that is no zone, stops every service at start-up. This was already so
    # before D-270 (tb_common.config.load_settings); kept here as the guard that the site zone is never guessed.
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    del data["site"]["tz"]
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="tz"):
        load_settings(p)
    data["site"]["tz"] = "Mars/Olympus"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="time zone"):
        load_settings(p)


def test_the_console_does_not_start_with_a_wrong_site_zone(box: dict[str, Any]) -> None:  # noqa: F811
    from console.app import create_app

    box["backend"].cfg = SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokio"))
    with pytest.raises(SiteZoneError, match="Asia/Tokio"):
        create_app({**PILOT_ENV, "TB_CONSOLE_DIR": str(box["dir"] / "c2")}, backend=box["backend"],
                   audit=box["audit"], users=box["users"])  # fmt: skip


# ------------------------------------------------------------------------------------------------ check_due
def test_the_monthly_log_check_is_counted_in_site_days() -> None:
    """A check made at 08:00 in Tokyo on 10-11 is stored as 10-10 in UTC; 30 site days later it is not yet due."""
    from console.team import check_due
    from console.teamstore import TeamStore

    t = TeamStore()
    t.add_entry("GZQO", username="drsato", name="Dr Sato", role="pi", tasks=(), start="2026-01-01", end=None,
                training_day="2026-01-01", training_ref="GCP-1", by="admin", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    t.add_check("GZQO", "match", "", "crc1", "2026-10-10T23:00:00+00:00")  # 08:00 on 2026-10-11 in Tokyo
    tokyo = ZoneInfo("Asia/Tokyo")
    assert check_due(t, "GZQO", date(2026, 11, 10), tokyo) is False  # 30 site days after the check
    assert check_due(t, "GZQO", date(2026, 11, 11), tokyo) is True  # 31


# ------------------------------------------------------------------------------------------------ the lint
# D-270: nobody is exempt. ``clock()`` and ``datetime.now(...)`` are instants: their date, year or ISO date prefix is
# the UTC (or container) day, not the site's. Convert with ``.astimezone(zone)`` (``timefmt.local_today``) or ask
# ``Helpers.today()`` / ``UserStore.today()``. The check reads the syntax tree, so comments, strings and docstrings
# never count, and a name bound to an instant (``now = h.clock()``) is followed.
# services/omop (load metadata dates, dqd's fallback) and tools/trialbox/logs.py are still open in D-270; add them here
# once fixed. The other tools stamp host files and builds, not site days.
SCANNED = [CONSOLE, CONSOLE.parent / "orchestrator"]
_PARTS = {"date", "year", "month", "day"}
_CONTAINER_DAY = {("date", "today"), ("datetime", "today"), ("datetime", "utcnow")}


def _is_instant(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.BinOp):  # clock() - timedelta(...)
        return _is_instant(node.left, names) or _is_instant(node.right, names)
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id in ("clock", "_utcnow")
    if isinstance(fn, ast.Attribute):
        if fn.attr in ("clock", "_utcnow"):
            return True
        base = fn.value
        if isinstance(base, ast.Name) and base.id in ("datetime", "date"):
            return fn.attr in ("now", "utcnow", "today")
        if fn.attr == "replace":  # clock().replace(...) is still an instant in the same zone
            return _is_instant(base, names)
    return False


def utc_date_reads(source: str) -> list[int]:
    """Lines that take a calendar day from an instant without converting it to the site's zone."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_instant(node.value, set()):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
            and _is_instant(node.value, set())
        ):
            names.add(node.target.id)
    hits: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # date.today / datetime.today / datetime.utcnow, even passed uncalled (a "today" callable)
            uncalled = isinstance(node.value, ast.Name) and (node.value.id, node.attr) in _CONTAINER_DAY
            if uncalled or (node.attr in _PARTS and _is_instant(node.value, names)):  # clock().date(), now.year
                hits.add(node.lineno)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            v = node.value  # clock().isoformat()[:10]
            if (
                isinstance(v, ast.Call)
                and isinstance(v.func, ast.Attribute)
                and v.func.attr == "isoformat"
                and _is_instant(v.func.value, names)
            ):
                hits.add(node.lineno)
    return sorted(hits)


@pytest.mark.parametrize(
    ("code", "caught"),
    [
        ("h.clock().date()", True),
        ("h.clock( ).date()", True),
        ("datetime.now().date()", True),
        ("datetime.now(UTC).date()", True),
        ("datetime.now(tz=UTC).date()", True),
        ("datetime.now(timezone.utc).date()", True),
        ("datetime.today()", True),
        ("date.today()", True),
        ("f = date.today", True),
        ("now = h.clock()\nnow.date()", True),
        ("h.clock().year", True),
        ("(h.clock() - timedelta(days=1)).date()", True),
        ("h.clock().isoformat()[:10]", True),
        ("s = '#'; h.clock().date()", True),
        ("local_today(h.clock(), tz)", False),
        ("h.clock().astimezone(tz).date()", False),
        ("h.clock().isoformat()", False),
        ("'uses date.today() and clock().date()'", False),
        ('"""clock().date() in a docstring"""', False),
        ("# h.clock().date()", False),
        ("visit.date()", False),
    ],
)
def test_the_lint_catches_each_form(code: str, caught: bool) -> None:
    assert bool(utc_date_reads(code)) is caught, code


def test_no_console_file_reads_the_utc_date_as_today() -> None:
    hits = [
        f"{f.relative_to(CONSOLE.parents[1])}:{n}"
        for root in SCANNED
        for f in sorted(root.rglob("*.py"))
        for n in utc_date_reads(f.read_text(encoding="utf-8"))
    ]
    assert hits == [], f"use h.today() (the site's date), not the UTC or container date: {hits}"
