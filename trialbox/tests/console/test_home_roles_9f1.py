"""9f-1, home half (D-1391): "Your role in each study" on the home page; moving ``my_roles`` out of the account route's
closure into one reader (``console.own_roles``) changes nothing the account page shows; the home shows a person only
what the home already showed them.

The invariant (D-1391), named: ``test_the_home_is_master_s_home_plus_a_card_of_the_account_s_own_roles``. For every
column of the role walk (the seven roles of the matrix, the log's PI, sub-investigator and monitor, the scoped SMO and CRO
accounts), with the flag ``layout.home_today`` off and on, in en, ja and zh-TW, the studies, the links (hrefs), the
counts and the patient-linked values on the home are a subset of what that column's home showed on origin/master, the
home outside the card is master's own, and every line of the card is a line of the same account's roles section on its
account page. What master showed is data: ``home_roles_9f1_master.json``, captured by this file (``HOME_ROLES_CAPTURE_TO``) from a
clean ``git archive`` copy of origin/master. The same capture on this branch gives the account page's roles section,
which is compared with master's byte for byte (``test_my_roles_gives_every_column_what_it_gave_on_master``).

Regenerating the data, when another card changes the home page and this test says so:
``git archive origin/master | tar -x -C <dir>``, copy this file into ``<dir>/trialbox/tests/console/``, and from
``<dir>/trialbox`` run it with ``HOME_ROLES_CAPTURE_TO=<path of home_roles_9f1_master.json>`` and a TB_TEST_ROOT of its
own: ``pytest tests/console/test_home_roles_9f1.py -k capture`` (start from no file). Any later card that changes the
home page makes the invariant fail until this is done again from the master that has it.

Synthetic data only."""

from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from console import phone
from console.teamstore import TeamStore
from tb_common import flags as fl

from tests.console import test_matrix_role_walk as mw
from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box  # noqa: F401
from tests.console.test_home_today import _flag as _set_flag
from tests.console.test_home_today import _lang, _participant_with_saes
from tests.console.test_lifecycle_pages import lb  # noqa: F401
from tools import role_walk as rw

SNAP = Path(__file__).with_name("home_roles_9f1_master.json")
CAPTURE = "HOME_ROLES_CAPTURE_TO"
LANGS = ("en", "ja", "zh-TW")
FLAGS = ("off", "on")
STUDIES = ("GZQO", "RA-BIO", rw.OTHER)  # the box's two rule sets and the study no column's data is in
AT = "2026-01-01T00:00:00+00:00"
NOON = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)  # the site's day: 2026-11-10 in Tokyo, Taipei and UTC


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags; a flag already at the value (the default, off) is left as it is."""
    try:
        _set_flag(b, value)
    except ValueError as e:
        assert "already" in str(e), e


def _log(
    team: TeamStore, rs: str, user: str, role: str, start: str, end: str | None, tasks: tuple[str, ...] = ()
) -> None:
    team.add_entry(rs, username=user, name=user, role=role, tasks=tasks, start=start, end=end, training_day="2026-01-01",
                   training_ref="GCP-1" if role != "monitor" else "MV-1", by="wpi", at=AT)  # fmt: skip


@pytest.fixture
def seeded(box: dict[str, Any], tmp_path: Path) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:  # noqa: F811
    """The role walk's seeded synthetic box (a finished feasibility run, a screening run with candidates, the study
    store, one account per column, the GZQO log naming a PI, a sub-investigator and a monitor), and more log entries:
    every role the home may name, an ended and a not-yet-started entry, one ending in ten days, and entries in a rule
    set that is not a trial (RA-BIO) and in one the box does not know (ZZQX), which the account page may list and the
    home must not."""
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])
    mw.faithful_reads(box)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    store = mw.study_store(box, tmp_path)
    next(store)
    cl = mw.clients(box)
    box["app"].state.helpers.clock = lambda: NOON
    team = TeamStore()
    _log(team, "GZQO", "wcrc", "crc", "2026-01-01", None, ("enter_data", "refer"))
    _log(team, "GZQO", "wsmoin", "crc", "2026-01-01", "2026-12-31", ("enter_data",))
    _log(team, "GZQO", "winv", "other", "2026-01-01", "2026-11-20", ("screen",))
    _log(team, "GZQO", "wsub", "crc", "2025-01-01", "2025-12-31", ("screen",))  # over
    _log(team, "GZQO", "wsub", "other", "2099-01-01", None, ("screen",))  # not yet
    _log(team, "GZQO", "admin", "other", "2026-01-01", None, ("enter_data",))
    _log(team, "GZQO", "viewer", "other", "2026-01-01", None, ("enter_data",))
    _log(team, "GZQO", "wsteward", "other", "2026-01-01", None, ("enter_data",))
    _log(team, "GZQO", "wprivacy", "other", "2026-01-01", None, ("enter_data",))
    _log(team, "GZQO", "wcroin", "monitor", "2026-01-01", None)
    _log(team, "GZQO", "wother", "pi", "2026-01-01", None)  # other people's entries: on no card but their own
    _log(team, "GZQO", "wghost", "sub_pi", "2026-01-01", None, ("screen", "run"))
    _log(team, "RA-BIO", "wpi", "sub_pi", "2026-01-01", None, ("screen",))
    _log(team, "RA-BIO", "wcrc", "crc", "2026-01-01", None, ("enter_data",))
    _log(team, rw.OTHER, "wpi", "pi", "2026-01-01", None)
    team.close()
    yield box, cl
    next(store, None)


@pytest.fixture
def lb_seeded(lb: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:  # noqa: F811
    """The life-cycle box with a participant, two visits (one due today, one overdue) and a serious adverse event, so
    the coordinator's home carries patient-linked links and screening numbers; the coordinator also has a log entry."""
    crc, pi, _no = _participant_with_saes(lb, 1)
    team = TeamStore()
    _log(team, "GZQO", "crc", "crc", "2026-01-01", None, ("enter_data", "refer"))
    team.close()
    yield lb, {"crc": (crc, "", None), "pi": (pi, "", None)}


SCENES = ("walk", "lb")


def _features(page: str) -> dict[str, Any]:
    """What the page shows of studies, links, counts and patient-linked values, as sets: the study ids it names (in
    its text or its links), every href, every number in its text (dates and times left out: the day is fixed, the seed's
    stamps are not), and every token that looks like a pseudonym, screening number or record id."""
    main = page.split("<main", 1)[1].split("</main>", 1)[0] if "<main" in page else page
    text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)\b.*?</\1>", " ", main, flags=re.S)))
    plain = re.sub(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?|\b\d{1,2}:\d{2}\b", " ", text)
    hrefs = sorted(set(html.unescape(x) for x in re.findall(r'href="([^"]*)"', main)))
    studies = sorted({s for s in STUDIES if re.search(rf"(?<![A-Za-z0-9-]){re.escape(s)}(?![A-Za-z0-9-])", text)}
                     | set(re.findall(r"/studies/([A-Za-z0-9-]+)", " ".join(hrefs))))  # fmt: skip
    numbers = sorted(set(re.findall(r"\d+", plain)))
    values = sorted(set(re.findall(r"\b(?:[0-9a-f]{8,}|[A-Z][A-Za-z0-9]*-\d{2,}|[A-Z]{2,}\d{3,})\b", plain)))
    return {"studies": studies, "hrefs": hrefs, "numbers": numbers, "values": values, "rest": _rest(main)}


def _rest(main: str) -> str:
    """The page's content without the roles card, as written (the CSRF token and the session clock left out, runs of
    white space as one: the empty line where no card stands is not content)."""
    main = re.sub(r'<section class="card" data-testid="home-roles">.*?</section>', "", main, flags=re.S)
    main = re.sub(r'name="csrf" value="[^"]+"|data-(?:idle|abs)-left="\d+"', "", main)
    return re.sub(r"\s+", " ", main).strip()


def _roles_section(page: str) -> str:
    """The account page's roles section, as the page wrote it (the CSRF token and the session clock left out)."""
    sec = page.split('data-testid="account-roles"', 1)[1].split("</section>", 1)[0]
    return re.sub(r'name="csrf" value="[^"]+"|data-(?:idle|abs)-left="\d+"', "", sec)


def _home_roles(page: str) -> str:
    return (
        page.split('data-testid="home-roles"', 1)[1].split("</section>", 1)[0]
        if 'data-testid="home-roles"' in page
        else ""
    )


def _capture(b: dict[str, Any], cl: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for flag in FLAGS:
        _flag(b, flag)
        for lang in LANGS:
            for name, (page, _csrf, _api) in cl.items():
                if name == "anon":
                    continue
                _lang(page, lang)
                paths = ["/home"] + (["/home?view=studies"] if name == "admin" else [])
                for path in paths:
                    r = page.get(path, follow_redirects=False)
                    entry: dict[str, Any] = {"status": r.status_code, "location": r.headers.get("location", "")}
                    if r.status_code == 200:
                        entry |= _features(r.text)
                        entry["roles_card"] = _home_roles(r.text)
                    out[f"{name}|{flag}|{lang}|{path}"] = entry
                a = page.get("/account")
                out[f"{name}|{flag}|{lang}|/account"] = {"status": a.status_code, "roles": _roles_section(a.text)}
    return out


def _scene(request: pytest.FixtureRequest, scene: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return request.getfixturevalue("seeded" if scene == "walk" else "lb_seeded")  # type: ignore[no-any-return]


@pytest.mark.parametrize("scene", SCENES)
def test_capture(request: pytest.FixtureRequest, scene: str) -> None:
    """With ``HOME_ROLES_CAPTURE_TO`` set, adds what this tree shows to that file under the scene's name (run from the
    origin/master copy, starting from no file, it makes the data the other tests compare with); without it, only
    checks that the capture runs and covers every column."""
    got = _capture(*_scene(request, scene))
    to = os.environ.get(CAPTURE)
    if to:
        path = Path(to)
        data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        data[scene] = got
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", "utf-8")
    cols = {c.name for c in rw.COLUMNS if c.role is not None} if scene == "walk" else {"crc", "pi"}
    assert {k.split("|")[0] for k in got} == cols
    assert len(got) >= len(cols) * len(FLAGS) * len(LANGS)


@pytest.fixture(scope="module")
def master() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SNAP.read_text("utf-8"))
    return data


_NOW: dict[str, dict[str, Any]] = {}


def _now(request: pytest.FixtureRequest, scene: str) -> dict[str, Any]:
    """This tree's capture of a scene, made once for the module (the box is seeded by the first test that asks)."""
    if scene not in _NOW:
        _NOW[scene] = _capture(*_scene(request, scene))
    return _NOW[scene]


@pytest.fixture
def now(request: pytest.FixtureRequest) -> dict[str, Any]:
    return _now(request, "walk")


@pytest.mark.parametrize("scene", SCENES)
def test_the_home_is_master_s_home_plus_a_card_of_the_account_s_own_roles(
    request: pytest.FixtureRequest, scene: str, master: dict[str, Any]
) -> None:
    """The invariant of D-1391. For every column, flag and language: a home that answers on master answers here with the
    same status and place (a redirect goes where it went); (a) outside the card the home is master's, so nothing
    disappears; its studies, links, counts and patient-linked values are within master's (the four sets); (b) every
    line of the card is a line of this same account's roles section on its account page (up to the dates and the
    warning, which the card leaves out), and no other person's username appears in it."""
    now, master = _now(request, scene), master[scene]
    assert set(now) == set(master)
    others = {c.name for c in rw.COLUMNS}
    names = {f"w{n.replace('_', '')}" for n in others} | {"wother", "wghost", "admin", "viewer"}
    shown = 0
    for key, was in master.items():
        if key.endswith("/account"):
            continue
        got = now[key]
        assert (got["status"], got["location"]) == (was["status"], was["location"]), key
        if got["status"] != 200:
            continue
        assert got["rest"] == was["rest"], key
        for what in ("studies", "hrefs", "numbers", "values"):
            assert set(got[what]) <= set(was[what]), (key, what, sorted(set(got[what]) - set(was[what])))
        card = got["roles_card"]
        shown += bool(card)
        account = now[key.rsplit("|", 1)[0] + "|/account"]["roles"]
        for li in re.findall(r"<li .*?</li>", card, flags=re.S):
            assert li.removesuffix("</li>") in account, (key, li)
        assert not any(re.search(rf"(?<![A-Za-z0-9]){n}(?![A-Za-z0-9])", card) for n in names), key
    assert shown, "no role was shown on any home: the test proves nothing"
    if scene == "lb":  # the home that carries a participant's links and screening numbers on master
        assert any(w.get("values") and w["status"] == 200 for k, w in master.items() if not k.endswith("/account"))
        assert any(any("/sae/" in h for h in w.get("hrefs", ())) for w in master.values())


def test_every_role_sees_its_own_roles_on_the_home_and_only_where_the_home_names_the_study(
    now: dict[str, Any],
) -> None:
    """A page test per role: the person's roles of the studies the home names, the ticked tasks of a sub-investigator,
    nothing of another person's entry and nothing of an RA-BIO or ZZQX entry (not a trial the home shows)."""

    def card(col: str, flag: str, lang: str = "en", path: str = "/home") -> str:
        return str(now[f"{col}|{flag}|{lang}|{path}"].get("roles_card", ""))

    for flag in FLAGS:
        crc = card("crc", flag)
        assert 'data-testid="role-GZQO-crc"' in crc and "RA-BIO" not in crc, flag  # the coordinator's own line only
        assert "Enter data" in crc
        assert 'data-testid="role-GZQO-crc"' in card("smo_in", flag)
        assert card("admin", flag, path="/home?view=studies").count("<li") == 1 and "role-GZQO-other" in card(
            "admin", flag, path="/home?view=studies"
        )
        for col in ("smo_out", "cro_out"):  # no study seen: no card
            assert card(col, flag) == "", (col, flag)
        assert "all study tasks" not in crc and "ZZQX" not in crc
    # the pages the opening page only shows with the flag on
    for col in ("pi", "sub", "inv", "viewer", "cro_mon", "cro_in"):
        assert now[f"{col}|off|en|/home"]["status"] in (200, 303), col
        if now[f"{col}|off|en|/home"]["status"] == 303:  # sent on to its own page: no home, no card
            assert now[f"{col}|off|en|/home"].get("roles_card", "") == "", col
    pi, sub, inv = card("pi", "on"), card("sub", "on"), card("inv", "on")
    assert 'data-testid="role-GZQO-pi"' in pi and "all study tasks" in pi and "RA-BIO" not in pi and "ZZQX" not in pi
    assert 'data-testid="role-GZQO-sub_pi"' in sub and "See candidates, Ask a treating doctor" in sub
    assert "role-GZQO-crc" not in sub and "role-GZQO-other" not in sub  # an ended and a not-yet entry are no roles
    assert 'data-testid="role-GZQO-other"' in inv  # the days left stay on the account page
    mon = card("cro_mon", "on")
    assert 'data-testid="role-GZQO-monitor"' in mon
    for col in ("steward", "privacy"):
        assert card(col, "on") == "" and now[f"{col}|on|en|/home"]["status"] == 303
    for flag in FLAGS:
        for lang in LANGS:  # the words are the account page's, in each language
            assert card("crc", flag, lang).count('data-testid="role-GZQO-crc"') == 1


def _no_id(card: str) -> str:
    """The card's text without the study ids it names (an id may hold digits, as AB12): what is left shows no count."""
    return re.sub(r"<[^>]+>", " ", re.sub(r'<strong class="mono">.*?</strong>', " ", card))


@pytest.mark.parametrize("scene", SCENES)
def test_the_home_card_carries_no_link_no_count_no_date_and_no_warning(
    request: pytest.FixtureRequest, scene: str
) -> None:
    for key, got in _now(request, scene).items():
        card = got.get("roles_card", "")
        if not card:
            continue
        assert "href=" not in card and not re.search(r"\d", _no_id(card)), key
        assert "pill" not in card and "role-ending" not in card, key


def _card_of(roles: list[dict[str, Any]]) -> str:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(Path(__file__).parents[2] / "services/console/templates"), autoescape=True
    )
    env.globals["t"] = lambda key, **kw: key
    return str(
        env.from_string('{% from "_roles.html" import home_roles_card %}{{ home_roles_card(x) }}').render(x=roles)
    )


def test_a_study_id_with_digits_is_named_and_no_count_is_shown_and_the_order_is_the_pages() -> None:
    """Study ids may hold digits (AB12): the card names the id and shows no count; its lines follow the order the page
    lists its studies in (not the id's alphabetical order), the log's order within one study."""
    from datetime import date
    from types import SimpleNamespace

    from console.own_roles import own_roles

    def entry(rs: str, role: str, tasks: tuple[str, ...] = ()) -> Any:
        return SimpleNamespace(ruleset=rs.lower(), role=role, tasks=tasks, start="2026-01-01", end="2026-11-12", days_left=lambda d: 2,
                  active_on=lambda d: True)  # fmt: skip

    team = SimpleNamespace(entries_for=lambda user: [entry("AB12", "pi"), entry("MM3", "sub_pi", ("screen",)), entry("ZZ1", "crc", ("run",)),
                                         entry("AB12", "sub_pi", ("refer",)), entry("OFF9", "pi")])  # fmt: skip
    seen = {"AB12", "MM3", "ZZ1"}
    plain = own_roles(team, "u", date(2026, 11, 10), seen)
    ordered = own_roles(team, "u", date(2026, 11, 10), seen, ["ZZ1", "AB12", "MM3"])
    assert [ln["rs"] for ln in plain] == ["AB12", "MM3", "ZZ1", "AB12"]  # the account page's order: the log's
    assert [(ln["rs"], ln["role"]) for ln in ordered] == [
        ("ZZ1", "crc"),
        ("AB12", "pi"),
        ("AB12", "sub_pi"),
        ("MM3", "sub_pi"),
    ]
    card = _card_of(ordered)
    assert (
        card.index("role-ZZ1-crc")
        < card.index("role-AB12-pi")
        < card.index("role-AB12-sub_pi")
        < card.index("role-MM3-sub_pi")
    )
    assert "OFF9" not in card and ">AB12<" in card and "href=" not in card and "pill" not in card
    assert not re.search(r"\d", _no_id(card)) and "2026" not in card and "role-ending" not in card


def test_my_roles_gives_every_column_what_it_gave_on_master(
    request: pytest.FixtureRequest, master: dict[str, Any]
) -> None:
    """Moving ``my_roles`` out of the route's closure: the account page's roles section, which is its whole output
    (rule set, role, ticked tasks, dates, days left), is byte for byte what master wrote, for every column, flag
    and language, on a box with an ended and a not-yet entry, an entry ending in ten days, and entries of two rule
    sets the account does not see as trials."""
    for scene in SCENES:
        was, now = master[scene], _now(request, scene)
        keys = [k for k in was if k.endswith("/account")]
        assert keys and set(keys) == {k for k in now if k.endswith("/account")}
        for k in keys:
            assert now[k] == was[k], (scene, k)
    now, master = _now(request, "walk"), master["walk"]
    keys = [k for k in master if k.endswith("/account")]
    ending = [k for k in keys if "role-ending-GZQO-other" in master[k]["roles"]]
    assert ending, "no column showed an ending warning: the days left were not compared"
    assert any("role-GZQO-sub_pi" in master[k]["roles"] and "role-GZQO-crc" not in master[k]["roles"] for k in keys)


def test_my_roles_helper_is_the_one_reader_of_both_pages() -> None:
    import inspect

    from console import home, own_roles, step4

    assert "own_roles(" in inspect.getsource(step4) and "own_roles(" in inspect.getsource(home)
    assert ".entries_for(" in inspect.getsource(own_roles)
    assert ".entries_for(" not in inspect.getsource(step4) and ".entries_for(" not in inspect.getsource(home)
