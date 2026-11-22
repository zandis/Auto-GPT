"""10F-1 (D-1387): a person's own preferences (density, text size, colour mode, language), without quiet hours.

* The closed sets: four keys, each a short list of fixed words; nothing else is stored, so no value can hold a
  pseudonym or any free text (the table ``auth.user_pref`` is not patient-linked in ``tb_common.erasure``).
* A choice survives sign-out, reaches every page as a data attribute on ``<html>`` (only a value other than the
  default: a page of a person who chose nothing is the page as it was) and its language starts the next session.
* Every change is audited as ``console.pref_set`` (who, key, from, to); a save that changes nothing writes nothing.
* A person changes only their own preferences: the name is the session's, a posted name is ignored. CSRF is checked;
  a value outside its set answers 400 with the summary and stores nothing; every role saves its own.
* The account is disabled: its preferences go. The migration is a new table only: run again on a store with rows,
  nothing changes.
* **The invariant** (``test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not``): for every
  role and every combination of the closed sets (2 x 3 x 4 x 4 = 96), the set of GET routes that answer 200 and the
  set of seeded patient values (pseudonyms) each route renders are subsets of those with the default preferences;
  and ``test_no_sae_notice_recipient_changes_with_a_preference``: the morning notices (N1 with its serious-AE alert,
  N2, the weekend's SAE-only digest) go to the same people with the same words whatever anyone chose.

Synthetic data only.
"""

from __future__ import annotations

import ast
import itertools
import json
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio.from_thread
import pytest
from console import notify, prefs
from console.auth import SCHEMA_V9, AuthError, Role, UserStore
from console.sitestore import NotifyPerson, SiteStore
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401 - box: fixture
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_matrix_role_walk import clients, faithful_reads
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_step2 import _row
from tools import role_walk as rw

COMBOS: list[dict[str, str]] = [
    dict(zip(prefs.KEYS, vals, strict=True)) for vals in itertools.product(*prefs.KEYS.values())
]
#: one column of the role walk per role (the one with the most rights where a role has several: the PI, a CRO account
#: with a monitor grant), so every role of the matrix is walked
ROLE_COLUMNS = ("admin", "crc", "pi", "viewer", "cro_mon", "steward", "privacy")


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _html_tag(text: str) -> str:
    m = re.search(r"<html[^>]*>", text)
    assert m
    return m.group(0)


def _save(c: TestClient, values: dict[str, str]) -> Any:
    page = c.get("/account")
    assert page.status_code == 200, page.status_code
    return c.post("/account/prefs", data={"csrf": _csrf(page.text), **values}, follow_redirects=False)


# ---------------------------------------------------------------------------------------------- the closed sets
def test_the_closed_sets_hold_no_free_text_and_no_patient_value() -> None:
    assert len(COMBOS) == 2 * 3 * 4 * 4
    assert set(prefs.KEYS) == {"density", "text_size", "mode", "lang"}  # no quiet hours, nothing about a notice
    for key, values in prefs.KEYS.items():
        assert prefs.DEFAULTS[key] == values[0] and len(set(values)) == len(values)
        for v in values:
            assert re.fullmatch(r"[A-Za-z0-9-]{2,12}", v), (key, v)  # a fixed word, never typed text
            assert set(prefs.LABELS[key]) == set(values)
    for value in ("a" * 8, "b" * 8, "a" * 32, "", " compact", "Compact", "<b>", "x" * 500):
        assert all(not prefs.valid(k, value) for k in prefs.KEYS), value
    assert not prefs.valid("quiet_hours", "20:00-07:00") and not prefs.valid("username", "admin")
    assert prefs.problems({"density": "dense", "mode": "dark"}) == [("density", "fe.pref.density")]
    assert prefs.of({"density": "compact", "mode": "neon", "other": "x"}) == {**prefs.DEFAULTS, "density": "compact"}
    assert prefs.html_attrs(prefs.DEFAULTS) == {}  # the defaults: the page as it was
    assert prefs.html_attrs({"density": "compact", "text_size": "150", "mode": "contrast"}) == {
        "data-density": "compact", "data-text-size": "150", "data-mode": "contrast"}  # fmt: skip
    assert prefs.AUDIT_EVENT == "console.pref_set"


def test_the_store_refuses_a_value_outside_the_set_and_keeps_only_what_differs() -> None:
    users = UserStore()
    users.create("syn-crc", "coordinator", PW, "syn-crc@hospa.test")
    with pytest.raises(AuthError):
        users.set_prefs("syn-crc", {"density": "dense"})
    with pytest.raises(AuthError):
        users.set_prefs("syn-crc", {"note": "anything"})
    assert users.prefs("syn-crc") == prefs.DEFAULTS
    assert users.set_prefs("syn-crc", {"density": "compact", "mode": "system"}) == [
        ("density", "comfortable", "compact")
    ]
    assert users.db.fetchall("SELECT name, value FROM user_pref WHERE username = ?", ("syn-crc",)) == [
        ("density", "compact")]  # fmt: skip
    assert users.set_prefs("syn-crc", {"density": "compact"}) == []  # no change: nothing to audit
    assert users.set_prefs("syn-crc", {"density": "comfortable"}) == [("density", "compact", "comfortable")]
    assert users.db.fetchall("SELECT name FROM user_pref WHERE username = ?", ("syn-crc",)) == []  # default: no row


def test_the_migration_is_a_new_table_and_runs_again_on_a_store_with_rows() -> None:
    users = UserStore()
    users.create("syn-pi", "investigator", PW, "syn-pi@hospa.test")
    users.set_prefs("syn-pi", {"text_size": "150", "lang": "ja"})
    assert "CREATE TABLE IF NOT EXISTS user_pref" in SCHEMA_V9 and "DROP" not in SCHEMA_V9 and "ALTER" not in SCHEMA_V9
    for stmt in SCHEMA_V9.split(";"):  # the script itself, run again by hand on the store with rows
        if stmt.strip():
            users.db.execute(stmt)
    again = UserStore()  # a second start migrates again: the recorded versions are checked, nothing is applied
    assert again.prefs("syn-pi") == {**prefs.DEFAULTS, "text_size": "150", "lang": "ja"}
    assert again.get("syn-pi") is not None


def test_disabling_an_account_removes_its_preferences() -> None:
    users = UserStore()
    users.create("syn-stw", "steward", PW, "syn-stw@hospa.test")
    users.create("syn-other", "coordinator", PW, "syn-other@hospa.test")
    users.set_prefs("syn-stw", {"mode": "contrast"})
    users.set_prefs("syn-other", {"mode": "dark"})
    users.disable("syn-stw")
    assert users.db.fetchall("SELECT name FROM user_pref WHERE username = ?", ("syn-stw",)) == []
    users.enable("syn-stw")
    assert users.prefs("syn-stw") == prefs.DEFAULTS  # enabled again: the defaults
    assert users.prefs("syn-other")["mode"] == "dark"  # nobody else's


# ---------------------------------------------------------------------------------------------- the page and the route
def test_a_choice_survives_sign_out_is_audited_and_reaches_every_page(box: dict[str, Any]) -> None:  # noqa: F811
    c = _user(box, "syn-crc1", "coordinator")
    home = c.get("/home")
    assert home.status_code == 200 and "data-mode" not in _html_tag(home.text)  # nothing chosen: as before
    r = _save(c, {"density": "compact", "text_size": "125", "mode": "contrast", "lang": "ja"})
    assert r.status_code == 303 and r.headers["location"] == "/account?saved=prefs"
    page = c.get("/account?saved=prefs").text
    assert 'data-testid="prefs-saved"' in page and 'lang="ja"' in _html_tag(page)  # the language at once
    got = sorted((e["detail"]["key"], e["detail"]["from"], e["detail"]["to"]) for e in _events(box, "console.pref_set"))
    assert got == [("density", "comfortable", "compact"), ("lang", "auto", "ja"), ("mode", "system", "contrast"),
                   ("text_size", "100", "125")]  # fmt: skip
    assert {e["actor"] for e in _events(box, "console.pref_set")} == {"console:syn-crc1"}
    assert {e["detail"]["user"] for e in _events(box, "console.pref_set")} == {"syn-crc1"}
    assert _save(c, {"density": "compact"}).status_code == 303
    assert len(_events(box, "console.pref_set")) == 4  # no change, no line
    c.post("/logout", data={"csrf": _csrf(c.get("/home").text)})
    c2, _ = login(box["app"], "syn-crc1", PW)
    for path in ("/home", "/account", "/help"):
        tag = _html_tag(c2.get(path).text)
        assert 'data-density="compact"' in tag and 'data-text-size="125"' in tag and 'data-mode="contrast"' in tag
        assert 'lang="ja"' in tag, path
    # the header's language switch still changes this session only; the next sign-in starts in the chosen one
    c2.post("/lang", data={"csrf": _csrf(c2.get("/home").text), "lang": "en", "back": "/"})
    assert 'lang="en"' in _html_tag(c2.get("/home").text)
    c3, _ = login(box["app"], "syn-crc1", PW)
    assert 'lang="ja"' in _html_tag(c3.get("/home").text)


def test_a_person_changes_only_their_own_preferences(box: dict[str, Any]) -> None:  # noqa: F811
    a = _user(box, "syn-crc2", "coordinator")
    _user(box, "syn-pi2", "investigator")
    r = _save(a, {"mode": "dark", "username": "syn-pi2", "user": "syn-pi2"})
    assert r.status_code == 303
    assert box["users"].prefs("syn-crc2")["mode"] == "dark"
    assert box["users"].prefs("syn-pi2") == prefs.DEFAULTS
    assert box["users"].prefs("admin") == prefs.DEFAULTS


def test_csrf_and_a_value_outside_the_set_store_nothing(box: dict[str, Any]) -> None:  # noqa: F811
    c = _user(box, "syn-crc3", "coordinator")
    for token in ("", "x" * 32):
        r = c.post("/account/prefs", data={"csrf": token, "mode": "dark"}, follow_redirects=False)
        assert r.status_code == 400
    r = _save(c, {"mode": "dark", "text_size": "999"})  # one bad value: nothing of the form is stored
    assert r.status_code == 400 and 'data-testid="prefs-error"' in r.text
    assert box["users"].prefs("syn-crc3") == prefs.DEFAULTS and _events(box, "console.pref_set") == []
    anon = TestClient(box["app"])
    r = anon.post("/account/prefs", data={"mode": "dark"}, follow_redirects=False)
    assert r.status_code in (303, 401) and box["users"].prefs("syn-crc3") == prefs.DEFAULTS


def test_every_role_sees_the_form_and_saves_its_own(box: dict[str, Any]) -> None:  # noqa: F811
    cl = clients(box)
    for col in rw.COLUMNS:
        if col.role is None:
            continue
        page, csrf, _api = cl[col.name]
        a = page.get("/account")
        assert a.status_code == 200 and 'data-fields="prefs"' in a.text, col.name
        r = page.post("/account/prefs", data={"csrf": csrf, "density": "compact"}, follow_redirects=False)
        assert r.status_code == 303, (col.name, r.status_code)
        name = {"admin": "admin", "viewer": "viewer"}.get(col.name, f"w{col.name.replace('_', '')}")
        assert box["users"].prefs(name)["density"] == "compact", col.name
    assert len(_events(box, "console.pref_set")) == len([c for c in rw.COLUMNS if c.role is not None])


# ---------------------------------------------------------------------------------------------- the invariant
#: the seeded patient-linked values, each a distinct marker (the screening job's rows, ``_done_screen``: the three
#: pseudonyms, the next appointment's day and time, the quoted evidence and its date, the action to take; the chart
#: number the stand-in reveals). Counted per route, with the patient rows and their cells (M-2 of the review)
PATIENT_MARKERS = (
    "a" * 8, "b" * 8, "c" * 8, "2026-10-07", "09:30", "two flares this spring", "2026-04-02", "confirm flare dates",
    "MRN-000123",
)  # fmt: skip
Measure = dict[str, int]


#: H73-01: the run's own time. A page prints when things happened in this run (an audit row, a flag's seeding, an
#: entry of the team log), and such a stamp can hold a marker: the CSV of the audit report wrote 10:09:30, which holds
#: the appointment's "09:30" (train 123). Every walk's requests are written at another second, so the defaults' walk
#: and a preference's differ by the clock alone. A stamp whose instant falls in this run is the page's own and is
#: masked before counting; a seeded value (the appointment, 2026-10-07 09:30) is never in the run and is counted.
RUN_STARTED = datetime.now(UTC)
#: a date with a time of day, as the pages print one: "2026-11-22 20:43", "2026-11-22 20:43:47",
#: "2026-11-22T20:43:47.416+08:00"
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?")
#: a stamp without an offset is in the site's zone, whichever that is: any offset from UTC-12 to UTC+14
NO_OFFSET_SLACK = timedelta(hours=14)


def _in_run(m: re.Match[str], window: tuple[datetime, datetime]) -> bool:
    """Is this stamp an instant of the run (``window``, from the minute a stamp may be cut to)?"""
    try:
        at = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}{m.group(4) or ''}")
    except ValueError:
        return False
    start, end = window[0].replace(second=0, microsecond=0), window[1]
    if at.tzinfo is None:
        at, start, end = at.replace(tzinfo=UTC), start - NO_OFFSET_SLACK, end + NO_OFFSET_SLACK
    return start <= at <= end


def _own_stamps_masked(text: str, window: tuple[datetime, datetime] | None = None) -> str:
    """The text with every stamp of the run replaced by one fixed word: the page's own time, never a patient's."""
    window = window or (RUN_STARTED, datetime.now(UTC))
    return STAMP.sub(lambda m: "[run-time]" if _in_run(m, window) else m.group(0), text)


def _measure(r: Any, window: tuple[datetime, datetime] | None = None) -> Measure:
    """How much patient-linked content a 2xx text answer holds: each marker's count, the rows that name a patient
    (a ``data-pid`` or a marker in the row) and their cells. Empty for any other answer. The page's own stamps of
    this run are masked first (``_own_stamps_masked``): the clock is not a patient value."""
    kind = r.headers.get("content-type", "")
    if not 200 <= r.status_code < 300 or not kind.startswith(("text/", "application/json")):
        return {}
    text = _own_stamps_masked(r.text, window)
    out = {m: text.count(m) for m in PATIENT_MARKERS}
    rows = [
        row
        for row in re.findall(r"<tr\b.*?</tr>", text, re.S)
        if "data-pid" in row or any(m in row for m in PATIENT_MARKERS)
    ]
    out["patient_rows"] = len(rows)
    out["patient_cells"] = sum(len(re.findall(r"<t[dh]\b", row)) for row in rows)
    out["data_pid"] = text.count("data-pid=")
    return {k: v for k, v in out.items() if v}


def _gets(cl: TestClient, job_id: str) -> tuple[frozenset[str], dict[str, Measure]]:
    """Every walked GET route: (the routes that answer 200, the patient-linked content of each)."""
    ok: set[str] = set()
    shown: dict[str, Measure] = {}
    for route in rw.console_routes(cl.app):
        if route["method"] != "GET" or not route["walked"]:
            continue
        r = cl.get(rw.fill(route["path"], job_id), follow_redirects=False)
        if r.status_code == 200:
            ok.add(route["path"])
        shown[route["path"]] = _measure(r)
    return frozenset(ok), shown


def _kind(r: Any) -> str:
    """An answer's class: denied (401, 403, 404, sent to sign in), invalid (another 4xx: nothing done), error (5xx)
    or ok (done: 2xx, or a redirect onward)."""
    if r.status_code in (401, 403, 404) or (300 <= r.status_code < 400 and "/login" in r.headers.get("location", "")):
        return "denied"
    if 400 <= r.status_code < 500:
        return "invalid"
    return "error" if r.status_code >= 500 else "ok"


def _posts(cl: TestClient, csrf: str, job_id: str, only: set[str] | None = None) -> dict[str, str]:
    """Every walked changing route (POST, PUT, PATCH, DELETE), sent with the CSRF token and the route table's form
    fields (``tools.role_walk``): its answer's class, by "METHOD path"."""
    out: dict[str, str] = {}
    for route in rw.console_routes(cl.app):
        key = f"{route['method']} {route['path']}"
        if route["method"] not in rw.CHANGING or not route["walked"] or (only is not None and key not in only):
            continue
        data = {"csrf": csrf, **rw.FORM_FIELDS.get(route["path"], {})}
        r = cl.request(route["method"], rw.fill(route["path"], job_id), data=data, follow_redirects=False)
        out[key] = _kind(r)
    return out


#: what a class may become under a preference: a refusal stays a refusal (denied stays denied; invalid may only be
#: denied or invalid), an error never becomes a success
ALLOWED_UNDER_PREF = {"denied": {"denied"}, "invalid": {"denied", "invalid"}, "error": {"denied", "invalid", "error"}}


class _AuditSnapshot:
    """M-3 of the review: every walk starts from the same audit trail. The trail as seeded is kept, and put back
    before each walk, so a page that lists audit lines (``/audit``) shows exactly what it showed the defaults' walk,
    plus only what a preference itself would add."""

    def __init__(self, folder: Path, keep: Path) -> None:
        self.folder, self.keep = folder, keep
        shutil.copytree(folder, keep)

    def restore(self) -> None:
        shutil.rmtree(self.folder)
        shutil.copytree(self.keep, self.folder)


def _wider(base: dict[str, Measure], now: dict[str, Measure]) -> dict[str, dict[str, tuple[int, int]]]:
    """Per route, each measure that went up from the defaults' (default, now)."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for path, m in now.items():
        up = {k: (base.get(path, {}).get(k, 0), v) for k, v in m.items() if v > base.get(path, {}).get(k, 0)}
        if up:
            out[path] = up
    return out


#: H73-01: the 96 combinations in four groups, one per language (24 each), so the xdist workers share one role's walk
#: (seven roles x four groups); ``test_the_groups_hold_every_combination_once`` holds that none is left out
COMBO_GROUPS: dict[str, list[dict[str, str]]] = {
    lang: [c for c in COMBOS if c["lang"] == lang] for lang in prefs.KEYS["lang"]
}


def test_the_groups_hold_every_combination_once() -> None:
    walked = [c for group in COMBO_GROUPS.values() for c in group]
    assert len(walked) == len(COMBOS) == 96
    assert sorted(map(repr, walked)) == sorted(map(repr, COMBOS))


@contextmanager
def _one_event_loop(c: TestClient) -> Iterator[None]:
    """H73-01: the client's requests share one event loop, as a server's do. Without it the test client starts a new
    loop in a new thread for every request (``TestClient._portal_factory``), about two thirds of the walk's time. The
    app's startup and shutdown are not run (``with TestClient`` would run them): the same app, the same requests."""
    with anyio.from_thread.start_blocking_portal(**c.async_backend) as portal:
        c.portal = portal
        try:
            yield
        finally:
            c.portal = None


@pytest.mark.parametrize("group", list(COMBO_GROUPS))
@pytest.mark.parametrize("column", ROLE_COLUMNS)
def test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not(
    box: dict[str, Any],  # noqa: F811
    column: str,
    group: str,
    tmp_path: Path,
) -> None:
    """For every combination of the closed sets, against the defaults on the same seeded state:
    * the GET routes that answer 200 are a subset, and no route renders more of any patient-linked value, more rows
      naming a patient or more cells in them (M-2);
    * every changing route the defaults' walk could not use (refused, invalid, an error) is still refused: denied
      stays denied (M-1).
    Each walk starts from the seeded audit trail (M-3), and two walks with the defaults give the same answers, so a
    difference is the preference's. One case per role and language group (H73-01), each on its own seeded box with
    its own defaults' walk; the page's own stamps of this run are not patient values (``_measure``)."""
    faithful_reads(box)
    _done_feas(box["backend"])
    job_id = _ulid(990)
    _done_screen(box["backend"], job_id)
    page, csrf, _api = clients(box)[column]
    with _one_event_loop(page):
        _walk_every_combination(box, page, csrf, column, job_id, COMBO_GROUPS[group], tmp_path)


def _walk_every_combination(
    b: dict[str, Any],
    page: TestClient,
    csrf: str,
    column: str,
    job_id: str,
    combos: list[dict[str, str]],
    tmp_path: Path,
) -> None:
    users = b["users"]
    name = {"admin": "admin", "viewer": "viewer"}.get(column, f"w{column.replace('_', '')}")  # as clients() names
    assert users.prefs(name) == prefs.DEFAULTS
    posts0 = _posts(page, csrf, job_id)  # the defaults: what each changing route answers (a success may change data)
    assert page.get("/account").status_code == 200  # the walk did not end the session
    refused = {k for k, v in posts0.items() if v != "ok"}
    assert refused  # the defaults are refused somewhere: there is something a preference must not open
    trail = _AuditSnapshot(b["dir"] / "audit", tmp_path / "audit-seeded")
    _gets(page, job_id)  # the stores a GET fills once (first seen, views) are filled before the comparison
    trail.restore()
    ok0, shown0 = _gets(page, job_id)
    trail.restore()
    assert _gets(page, job_id) == (ok0, shown0)  # the same state gives the same answers: a difference is a preference's
    assert ok0  # the walk reached pages
    for combo in combos:
        r = page.post("/account/prefs", data={"csrf": csrf, **combo}, follow_redirects=False)
        assert r.status_code == 303, combo
        assert users.prefs(name) == combo
        trail.restore()
        ok, shown = _gets(page, job_id)
        assert ok <= ok0, (combo, sorted(ok - ok0))
        assert _wider(shown0, shown) == {}, combo
        after = _posts(page, csrf, job_id, refused)
        opened = {k: (posts0[k], v) for k, v in after.items() if v not in ALLOWED_UNDER_PREF[posts0[k]]}
        assert opened == {}, (combo, opened)


def test_the_invariant_sees_an_extra_patient_column_and_a_denial_turned_into_a_success() -> None:
    """The comparison itself (the review's mutations, as data): one more cell in a row that already names the patient
    is wider; so is the same marker twice; a 403 that becomes a 303 is opened; a 400 that becomes 403 is not."""
    row = '<table><tr data-pid="{p}"><td>aaaaaaaa</td><td>2026-10-07</td></tr></table>'.format(p="a" * 32)
    wide = row.replace("</tr>", "<td>two flares this spring</td></tr>")
    resp = SimpleNamespace(status_code=200, headers={"content-type": "text/html"}, text=row)
    more = SimpleNamespace(status_code=200, headers={"content-type": "text/html"}, text=wide)
    base, now = {"/x": _measure(resp)}, {"/x": _measure(more)}
    assert _wider(base, now)["/x"]["patient_cells"] == (2, 3)
    twice = SimpleNamespace(status_code=200, headers={"content-type": "text/html"}, text=row + "aaaaaaaa")
    up = _wider(base, {"/x": _measure(twice)})["/x"]
    assert list(up) == ["a" * 8] and up["a" * 8][1] == up["a" * 8][0] + 1
    assert _wider(base, base) == {}
    ok = SimpleNamespace(status_code=303, headers={"location": "/?notice=ingested"})
    denied = SimpleNamespace(status_code=403, headers={})
    assert _kind(ok) not in ALLOWED_UNDER_PREF[_kind(denied)]
    assert _kind(denied) in ALLOWED_UNDER_PREF[_kind(SimpleNamespace(status_code=400, headers={}))]
    assert _kind(SimpleNamespace(status_code=303, headers={"location": "/login"})) == "denied"


def test_the_invariant_is_blind_to_the_clock_and_still_sees_a_patient_time() -> None:
    """H73-01 (train 123's red, ``[steward]``): the audit report's CSV printed a row written at 10:09:30, which holds
    the appointment's "09:30". A stamp of the run is the page's own, in every form a page prints it; the seeded
    appointment, in a cell or in the CSV, is still a patient value, and one more of it is still wider."""
    run = (datetime(2026, 11, 22, 2, 9, 12, tzinfo=UTC), datetime(2026, 11, 22, 2, 10, 5, tzinfo=UTC))

    def csv(*lines: str) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=200, headers={"content-type": "text/csv"}, text="ts,event\n" + "".join(lines)
        )

    base = {"/r.csv": _measure(csv("2026-11-22T10:09:12.401+08:00,console.audit_report\n"), run)}
    for own in ("2026-11-22T10:09:30.512+08:00", "2026-11-22T02:09:30Z", "2026-11-22 10:09:30", "2026-11-22 10:09"):
        assert _wider(base, {"/r.csv": _measure(csv(f"{own},console.audit_report\n"), run)}) == {}, own
    shown = csv("2026-11-22T10:09:30.512+08:00,console.audit_report\n", "2026-10-07T09:30:00+08:00,appointment\n")
    assert _wider(base, {"/r.csv": _measure(shown, run)}) == {"/r.csv": {"09:30": (0, 1), "2026-10-07": (0, 1)}}
    cell = SimpleNamespace(status_code=200, headers={"content-type": "text/html"},
                           text='<p>2026-11-22 10:09</p><td class="num">2026-10-07 09:30</td>')  # fmt: skip
    assert _measure(cell, run) == {"09:30": 1, "2026-10-07": 1}


# ---------------------------------------------------------------------------------------------- the structural guard
CONSOLE_DIR = Path(__file__).resolve().parents[2] / "services" / "console"
LIBS_DIR = Path(__file__).resolve().parents[2] / "libs" / "tb_common"
#: the only modules that may name the preferences (the store, the account page, the page frame), and where in them
PREF_USERS = {
    "auth.py": {"new_session", "prefs", "set_prefs", "disable"},
    "step4.py": {"account_page", "account_prefs", "audited"},
    "app.py": {"page"},
    "prefs.py": None,  # the module itself
}
#: the permission checks: the matrix, the account's rights, the session and scope checks, the study's log
PERMISSION_FUNCS = {
    "app.py": {"need", "_scope_check", "_aggregate_denied", "_need_role", "need_admin", "need_requester",
               "need_runner", "session_of"},
    "home.py": {"delegated_ok", "reads", "may_run"},
    "team.py": {"standing"},
}  # fmt: skip
#: a name or attribute that reads a preference or what it sets (the session's language), and a text naming the table
#: or the page attributes
PREF_STRINGS = {"user_pref", "data-mode", "data-density", "data-text-size"}
PREF_WORDS = {"prefs", "set_prefs", "ui_attrs", "lang", "html_attrs", "session_lang", "set_lang", *PREF_STRINGS}


def _named(node: ast.AST) -> set[str]:
    """Every name, attribute and string a piece of code mentions."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out |= {w for w in PREF_STRINGS if w in n.value}
        elif isinstance(n, ast.alias):
            out.add(n.name.rsplit(".", 1)[-1])
    return out


def _functions(tree: ast.AST) -> dict[str, list[ast.AST]]:
    out: dict[str, list[ast.AST]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            out.setdefault(n.name, []).append(n)
    return out


def test_no_permission_check_reads_a_preference() -> None:
    """M-1 and L-9 of the review: a preference cannot open anything because nothing that decides what a person may
    do or is told reads it. The matrix (``tb_common.authz``), the account's rights (``User``), the session and scope
    checks, the study's log and every notice module name no preference, no session language, no ``user_pref``; only
    the store, the account page and the page frame name the preferences at all, each in the functions listed."""
    authz = (LIBS_DIR / "authz.py").read_text(encoding="utf-8")
    assert not _named(ast.parse(authz)) & PREF_WORDS
    auth_tree = ast.parse((CONSOLE_DIR / "auth.py").read_text(encoding="utf-8"))
    user = next(n for n in ast.walk(auth_tree) if isinstance(n, ast.ClassDef) and n.name == "User")
    assert not _named(user) & PREF_WORDS
    for file, names in PERMISSION_FUNCS.items():
        funcs = _functions(ast.parse((CONSOLE_DIR / file).read_text(encoding="utf-8")))
        for fn in names:
            assert fn in funcs, (file, fn)
            for node in funcs[fn]:
                assert not _named(node) & PREF_WORDS, (file, fn, sorted(_named(node) & PREF_WORDS))
    for path in sorted(CONSOLE_DIR.glob("*.py")) + sorted(LIBS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        mentions = {
            n.lineno
            for n in ast.walk(tree)
            if (isinstance(n, ast.ImportFrom) and any(a.name == "prefs" for a in n.names) and n.module == "console")
            or (isinstance(n, ast.Import) and any(a.name == "console.prefs" for a in n.names))
            or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "user_pref" in n.value)
        }
        if path.parent == LIBS_DIR:
            assert not mentions or path.name == "erasure.py", path.name  # the inventory names the table
            continue
        if path.name not in PREF_USERS:
            assert not mentions, (path.name, sorted(mentions))
            continue
        allowed = PREF_USERS[path.name]
        if allowed is None:
            continue
        inside = {  # the store's schema version names its table
            getattr(n, "lineno", 0)
            for stmt in tree.body
            if isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SCHEMA_V9" for t in stmt.targets)
            for n in ast.walk(stmt)
        }
        for fn in allowed:
            for node in _functions(tree).get(fn, []):
                inside |= {getattr(n, "lineno", 0) for n in ast.walk(node)}
        module_level_import = {n.lineno for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)}
        uses = {
            n.lineno
            for n in ast.walk(tree)
            if (isinstance(n, ast.Name) and n.id == "prefs")
            or (isinstance(n, ast.Attribute) and n.attr in ("prefs", "set_prefs"))
            or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "user_pref" in n.value)
        }
        stray = uses - inside - module_level_import
        assert not stray, (path.name, sorted(stray))


def test_the_structural_guard_finds_a_planted_read(tmp_path: Path) -> None:
    """The guard's own check, on the review's M-1 mutation written as code: a permission function that reads the
    session's language is found."""
    planted = (
        "def need_admin(request, csrf):\n    sess = need(request)\n    return sess.user.is_admin or sess.lang == 'ja'\n"
    )
    node = _functions(ast.parse(planted))["need_admin"][0]
    assert _named(node) & PREF_WORDS == {"lang"}


def _notify_helpers(store: SiteStore, users: UserStore, life: dict[str, Any]) -> Any:
    rows = [_row("1" * 16, "2026-11-02T09:00:00+08:00"), _row("2" * 16, "2026-11-04T10:00:00+08:00")]
    return SimpleNamespace(
        store=store,
        users=users,
        trials=lambda _sess: [SimpleNamespace(id="GZQO")],
        week_bundle=lambda _sess, _rs: {"rows": [dict(r) for r in rows], "cl": None},
        life_mail=lambda _rs, _day: life,
        bk=SimpleNamespace(registry_rows=lambda _rs: []),
        delegated_ok=lambda _u, _rs, *_: True,
    )


def test_no_sae_notice_recipient_changes_with_a_preference() -> None:
    store, users = SiteStore(), UserStore()
    accounts: tuple[tuple[str, Role], ...] = (
        ("syn-pi9", "investigator"), ("syn-crc9", "coordinator"), ("syn-sub9", "investigator"))  # fmt: skip
    for name, role in accounts:
        users.create(name, role, PW, f"{name}@hospa.test")
        store.save_notify_person(NotifyPerson(name, None, lang="en"))
    life = {"today": [], "week": [], "overdue": [], "reports": [], "sae": 1}
    h = _notify_helpers(store, users, life)
    days = (date(2026, 11, 2), date(2026, 11, 7))  # a Monday, and a Saturday (the SAE-only weekend digest)

    def sent() -> list[tuple[Any, ...]]:
        out = []
        for day in days:
            for n in notify.collect(h, day, ("N1", "N2")):
                out.append((day, n.kind, n.username, n.to, n.subject, n.body, sorted(n.counts.items()), n.log_kind))
        return sorted(out, key=repr)

    before = sent()
    assert any(k == "N1" and dict(c).get("sae") == 1 for _d, k, _u, _t, _s, _b, c, _l in before)  # the SAE alert goes
    for combo in COMBOS:
        for name in ("syn-pi9", "syn-crc9"):
            users.set_prefs(name, combo)
        assert sent() == before, combo
    assert {"syn-pi9", "syn-sub9"} <= {u for _d, k, u, *_ in before if k == "N1"}  # both investigators alerted


# ---------------------------------------------------------------------------------------------- the review's Lows
def test_l1_a_change_whose_audit_line_fails_is_not_stored(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """L-1: the audit line is written inside the store's transaction; an audit that cannot take it leaves the stored
    preferences as they were (no change without its line)."""
    _user(box, "syn-crc5", "coordinator")
    c = TestClient(box["app"], raise_server_exceptions=False)
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    c.post("/login", data={"username": "syn-crc5", "password": PW, "login_csrf": token.group(1)})
    original = box["audit"].append

    def refuse(event: str, *a: Any, **kw: Any) -> Any:
        if event == "console.pref_set":
            raise OSError("the audit cannot take the line")
        return original(event, *a, **kw)

    monkeypatch.setattr(box["audit"], "append", refuse)
    r = _save(c, {"mode": "dark"})
    assert r.status_code >= 500
    assert box["users"].prefs("syn-crc5") == prefs.DEFAULTS


def test_l2_an_account_that_must_change_its_password_or_acknowledge_the_demo_can_save(box: dict[str, Any]) -> None:  # noqa: F811
    """L-2: the form the account page shows can be saved where the page is open: an account whose password someone
    else set, and a demo tester before the acknowledgement, as the language card it replaced (/lang)."""
    from console import demo_guard, identity

    assert "/account/prefs" in identity.MUST_CHANGE_OPEN and "/account/prefs" in demo_guard.ACK_OPEN
    c = _user(box, "syn-crc6", "coordinator")
    box["users"].set_password("syn-crc6", PW + "-x", must_change=True)
    c, _ = login(box["app"], "syn-crc6", PW + "-x")
    assert 'data-fields="prefs"' in c.get("/account").text
    assert _save(c, {"mode": "contrast"}).status_code == 303
    assert box["users"].prefs("syn-crc6")["mode"] == "contrast"
    assert c.get("/home", follow_redirects=False).status_code == 303  # nothing else opens before the new password


def test_l3_l4_the_language_rules_are_stated_and_auto_takes_effect_at_once(box: dict[str, Any]) -> None:  # noqa: F811
    """L-3: a stored language starts every sign-in, whatever the sign-in page shows, and the account page says so.
    L-4: saving "auto" switches this session at once to the browser's language."""
    from console.i18n import CATALOGUES

    c = _user(box, "syn-crc7", "coordinator")
    assert _save(c, {"lang": "ja"}).status_code == 303
    page = c.get("/account").text
    assert CATALOGUES["ja"]["pref.lang.rule"] in page and 'data-testid="prefs-lang-rule"' in page
    c2 = TestClient(box["app"])
    token = re.search(r'name="login_csrf" value="([^"]+)"', c2.get("/login?lang=zh-TW").text)
    assert token
    c2.post("/login", data={"username": "syn-crc7", "password": PW, "login_csrf": token.group(1)})
    assert 'lang="ja"' in _html_tag(c2.get("/home").text)  # the stored one, as the page says
    page = c2.get("/account", headers={"accept-language": "en"}).text
    r = c2.post("/account/prefs", data={"csrf": _csrf(page), "lang": "auto"}, headers={"accept-language": "en"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert 'lang="en"' in _html_tag(c2.get("/home", headers={"accept-language": "en"}).text)  # at once


def test_l5_error_only_in_the_tab_title(box: dict[str, Any]) -> None:  # noqa: F811
    from console.i18n import CATALOGUES

    c = _user(box, "syn-crc8", "coordinator")
    r = _save(c, {"mode": "neon"})
    assert r.status_code == 400
    title = re.search(r"<title>(.*?)</title>", r.text, re.S)
    h1 = re.search(r"<h1>(.*?)</h1>", r.text, re.S)
    assert title and h1
    assert title.group(1).startswith(CATALOGUES["en"]["fe.title"].format(title=CATALOGUES["en"]["account.title"]))
    assert h1.group(1) == CATALOGUES["en"]["account.title"]


CSS_FILE = Path(__file__).resolve().parents[2] / "services" / "console" / "static" / "console.css"


def test_l6_print_uses_the_paper_colours_for_a_card() -> None:
    css = re.sub(r"/\*.*?\*/", "", CSS_FILE.read_text(encoding="utf-8"), flags=re.S)
    assert "@media print { .card { background: var(--print-bg); color: var(--print-ink); } }" in css


def test_l7_every_size_written_as_a_number_scales_with_the_text_size() -> None:
    """L-7: a font size written in px outside the type tokens has its 125 % and 150 % rule, so a new fixed size
    fails here until it scales too."""
    css = re.sub(r"/\*.*?\*/", "", CSS_FILE.read_text(encoding="utf-8"), flags=re.S)
    fixed = set()
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        sel = m.group(1).strip()
        if sel.startswith(":root") or not re.search(r"font(?:-size)?:[^;]*\b\d+px", m.group(2)):
            continue
        if re.search(r"font(?:-size)?:\s*calc\(", m.group(2)):
            continue
        fixed.add(sel)
    assert fixed == {"svg .ax", ".big", ".pipe b", ".otp", "nav.ptabs .ptabs-lists a"}, fixed
    for sel in fixed:
        for size, factor in (("125", "1.25"), ("150", "1.5")):
            assert re.search(
                rf':root\[data-text-size="{size}"\] {re.escape(sel)} \{{ font-size: calc\(\d+px \* {factor}\); \}}', css
            ), (sel, size)


#: every value of every key at least once: the defaults, and three combinations that together hold every other value
L9_PICKS = [prefs.DEFAULTS] + [{k: v[min(i, len(v) - 1)] for k, v in prefs.KEYS.items()} for i in (1, 2, 3)]


@pytest.mark.parametrize("pick", range(len(L9_PICKS)))
def test_l9_the_sae_notice_at_once_goes_to_the_same_people_whatever_the_pi_chose(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    pick: int,
) -> None:
    """L-9: the SAE notice sent at once (the trial office and the study's PI, D-764) goes to the same two addresses,
    in the same words (English, the notice's own language, never the PI's chosen page language), whatever the PI
    chose: every value of every key at least once. The escalation of an unacknowledged SAE (9f-4 b, D-1383) is not
    on master: the structural guard (``test_no_permission_check_reads_a_preference``) holds every notice module, that
    one included when it lands."""
    from tests.console.test_an_sae_is_told_at_once import _new_case

    assert {(k, d[k]) for d in L9_PICKS for k in d} == {(k, v) for k, vs in prefs.KEYS.items() for v in vs}
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "trial-office@hospa.test")
    sent = _new_case(lb, before_sync=lambda: lb["users"].set_prefs("pi", L9_PICKS[pick]))
    assert lb["users"].prefs("pi") == L9_PICKS[pick]
    assert len(sent) == 1
    _kind, to, subject, body = sent[0]
    assert sorted(to) == ["pi@hospa.test", "trial-office@hospa.test"]
    assert "due" in body and "Myocardial" not in subject + body
