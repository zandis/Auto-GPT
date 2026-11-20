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

import itertools
import json
import re
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from console import notify, prefs
from console.auth import SCHEMA_V9, AuthError, Role, UserStore
from console.sitestore import NotifyPerson, SiteStore
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401 - box: fixture
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
def _walk(cl: TestClient, job_id: str) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """(the GET routes that answer 200, the seeded pseudonyms each 2xx route renders)."""
    ok: set[str] = set()
    shown: dict[str, frozenset[str]] = {}
    for route in rw.console_routes(cl.app):
        if route["method"] != "GET" or not route["walked"]:
            continue
        r = cl.get(rw.fill(route["path"], job_id), follow_redirects=False)
        if r.status_code == 200:
            ok.add(route["path"])
        shown[route["path"]] = frozenset(rw.shows(r))
    return frozenset(ok), shown


@pytest.mark.parametrize("column", ROLE_COLUMNS)
def test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not(
    box: dict[str, Any],  # noqa: F811
    column: str,
) -> None:
    faithful_reads(box)
    _done_feas(box["backend"])
    job_id = _ulid(990)
    _done_screen(box["backend"], job_id)
    page, csrf, _api = clients(box)[column]
    users = box["users"]
    name = {"admin": "admin", "viewer": "viewer"}.get(column, f"w{column.replace('_', '')}")  # as clients() names
    assert users.prefs(name) == prefs.DEFAULTS
    # the walk writes audit lines of its own (a read of a patient, a refusal), which the audit page then lists: one
    # walk first, so the defaults' answers already hold what any later walk adds
    _walk(page, job_id)
    ok0, shown0 = _walk(page, job_id)
    assert ok0  # the walk reached pages
    for combo in COMBOS:
        r = page.post("/account/prefs", data={"csrf": csrf, **combo}, follow_redirects=False)
        assert r.status_code == 303, combo
        assert users.prefs(name) == combo
        ok, shown = _walk(page, job_id)
        assert ok <= ok0, (combo, sorted(ok - ok0))
        wider = {p: sorted(v - shown0[p]) for p, v in shown.items() if not v <= shown0.get(p, frozenset())}
        assert wider == {}, (combo, wider)


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
