# ruff: noqa: F811 - the box fixture is imported and taken by name
"""D-1245 (card 10E-13, review 13 item 13-14 section 7.1): a finished screening run's page says how far the first load
of the study's new patients has come: the new patients screened on this run, those still waiting, and an estimate of
the nights left at this run's night budget. From the run's own ``microbatch.budget`` event, which the page already
reads for the re-check card, under the same rule (the accounts that read the study's list). Nothing is shown when a
number is missing, when nobody waits, or to an account that does not read the study's list. Synthetic data only."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from console.i18n import CATALOGUES
from markupsafe import escape
from tb_common.wording import check_page

from tests.console.test_console_app import _done_screen, _ulid, box, login_crc  # noqa: F401
from tests.console.test_role_pages import _user

LANGS = ("en", "ja", "zh-TW")
WAITING: dict[str, Any] = {"trigger": "ingest", "budget": 40, "left": 0, "new_screened": 40, "new_carried": 95}


def _run(b: dict[str, Any], n: int, **detail: Any) -> str:
    jid = _ulid(n)
    _done_screen(b["backend"], jid)
    b["audit"].append("microbatch.budget", job_id=jid, ruleset="GZQO", actor="orchestrator",
                      detail={**WAITING, **detail})  # fmt: skip
    return jid


def _block(page: str) -> str | None:
    m = re.search(r'<section[^>]*data-testid="first-load"[^>]*>(.*?)</section>', page, re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("lang", LANGS)
def test_the_run_page_says_the_first_load_in_the_readers_language(box: dict[str, Any], lang: str) -> None:
    jid = _run(box, 971)  # 95 waiting at 40 a night: 3 nights (rounded up)
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None, lang
    cat = CATALOGUES[lang]
    assert str(escape(cat["job.firstload.title"])) in block
    assert str(escape(cat["job.firstload.line"].format(n=40, waiting=95))) in block
    assert str(escape(cat["job.firstload.nights"].format(n=40, nights=3))) in block
    assert check_page(block) == [], lang
    assert "new_carried" not in block and "new_screened" not in block  # the event's field names are not its words


@pytest.mark.parametrize(
    "detail",
    [
        {"new_carried": 0},  # nobody waits: the first load is done
        {"new_carried": None},  # the run did not say
        {"new_screened": None},
    ],
    ids=["none-waiting", "no-waiting-figure", "no-screened-figure"],
)
def test_nothing_is_shown_when_a_number_is_missing_or_nobody_waits(box: dict[str, Any], detail: dict[str, Any]) -> None:
    jid = _run(box, 972, **detail)
    c, _ = login_crc(box)
    page = c.get(f"/pilot/jobs/{jid}")
    assert page.status_code == 200 and _block(page.text) is None


def test_an_account_that_does_not_read_the_studys_list_is_not_shown_it(box: dict[str, Any]) -> None:
    jid = _run(box, 973)
    privacy = _user(box, "priv-fl", "privacy")  # opens the run's page, does not read the study's list
    page = privacy.get(f"/pilot/jobs/{jid}")
    assert page.status_code == 200 and _block(page.text) is None


def test_a_run_not_finished_shows_nothing(box: dict[str, Any]) -> None:
    jid = _run(box, 974)
    job = box["backend"].jobs[jid]
    box["backend"].jobs[jid] = job.model_copy(update={"state": "running"})
    c, _ = login_crc(box)
    assert _block(c.get(f"/pilot/jobs/{jid}").text) is None


# ---------------------------------------------------------------------------------------------- reading a protocol
def _reading(b: dict[str, Any], n: int, state: str = "compiling") -> str:
    jid = _ulid(n)
    job = _done_screen(b["backend"], jid)
    b["backend"].jobs[jid] = job.model_copy(update={"type": "FEAS", "state": state, "outputs": []})
    return jid


def _answers(page: str) -> str | None:
    m = re.search(r'<p[^>]*data-testid="compile-answers"[^>]*>(.*?)</p>', page, re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("lang", LANGS)
def test_while_a_protocol_is_read_the_page_counts_the_models_answers_since_the_latest_start(
    box: dict[str, Any], lang: str
) -> None:
    _three_answers_since_the_latest_start(box, lang)


@pytest.fixture
def one_millisecond(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every audit row this test writes carries one and the same timestamp (the log's resolution is a millisecond):
    only the order the rows were written in can tell the latest compile.start from the answers after it."""
    au = box["audit"]
    real, now = au.append, datetime.now(UTC).replace(microsecond=0)
    monkeypatch.setattr(au, "append", lambda event, **fields: real(event, **{**fields, "ts": now}))
    return box


@pytest.mark.parametrize("lang", LANGS)
def test_rows_written_in_one_millisecond_are_counted_in_the_order_they_were_written(
    one_millisecond: dict[str, Any], lang: str
) -> None:
    """10E-13b: the count follows the audit log's own order, never a tie of timestamps (CI saw 2 for 3)."""
    _three_answers_since_the_latest_start(one_millisecond, lang)


def _three_answers_since_the_latest_start(box: dict[str, Any], lang: str) -> None:
    jid = _reading(box, 981)
    au = box["audit"]
    au.append("compile.start", job_id=jid, ruleset="GZQO", actor="criteria-compiler")  # an earlier, failed attempt
    au.append("llm.call", job_id=jid, actor="criteria-compiler")
    au.append("compile.start", job_id=jid, ruleset="GZQO", actor="criteria-compiler")  # the attempt now running
    for _ in range(3):
        au.append("llm.call", job_id=jid, actor="criteria-compiler")
    au.append("llm.call", job_id=_ulid(982), actor="criteria-compiler")  # another job's answer
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    got = _answers(c.get(f"/pilot/jobs/{jid}").text)
    cat = CATALOGUES[lang]
    assert got is not None and str(escape(cat["job.compile.answers"].format(n=3))) in got, lang
    assert str(escape(cat["job.compile.answers.what"])) in got and check_page(got) == []


def test_before_the_compile_starts_and_after_the_job_is_past_reading_nothing_is_shown(box: dict[str, Any]) -> None:
    c, _ = login_crc(box)
    waiting = _reading(box, 983, "parsing")  # no compile.start yet
    assert _answers(c.get(f"/pilot/jobs/{waiting}").text) is None
    done = _reading(box, 984, "awaiting_approval")
    box["audit"].append("compile.start", job_id=done, ruleset="GZQO", actor="criteria-compiler")
    assert _answers(c.get(f"/pilot/jobs/{done}").text) is None
    started = _reading(box, 985, "parsing")
    box["audit"].append("compile.start", job_id=started, ruleset="GZQO", actor="criteria-compiler")
    got = _answers(c.get(f"/pilot/jobs/{started}").text)
    assert got is not None and str(escape(CATALOGUES["en"]["job.compile.answers"].format(n=0))) in got


# ---------------------------------------------------------------------------------------------- the page otherwise
#: the two blocks this card adds to job.html, as written there
_ADDED = (
    re.compile(r"\{% if compile_answers is not none %\}.*?\{% endif %\}", re.S),
    re.compile(r"\{% if first_load %\}<section.*?</section>\n\{% endif %\}", re.S),  # with its inner if
)


def test_a_job_page_without_progress_is_byte_for_byte_the_page_without_the_new_blocks(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The render comparison: the job page rendered from job.html as shipped and from job.html with this card's two
    blocks cut out are the same bytes when there is no progress to say: the blocks add nothing, not even a line.
    (What it cannot see, text outside the two blocks, was compared with master's own render of the same pages across
    two worktrees; the pull request has the method.)"""
    from jinja2 import FileSystemLoader

    real = FileSystemLoader.get_source
    strip = {"on": True}

    def get_source(self: FileSystemLoader, env: Any, name: str) -> tuple[str, str | None, Any]:
        src, filename, _ = real(self, env, name)
        if name == "job.html" and strip["on"]:
            for rx in _ADDED:
                src, n = rx.subn("", src)
                assert n == 1, rx.pattern
        return src, filename, lambda: False  # read again at each render: the switch below takes effect

    monkeypatch.setattr(FileSystemLoader, "get_source", get_source)
    weekly = _ulid(991)  # a finished weekly run with the re-check card and no new patient waiting
    _done_screen(box["backend"], weekly)
    box["audit"].append("microbatch.budget", job_id=weekly, ruleset="GZQO", actor="orchestrator",
                        detail={"trigger": "weekly", "budget": 40, "left": 12, "new_screened": 0, "new_carried": 0,
                                "excluded_rescreened": 3, "excluded_carried": 5, "excluded_in_scope": 8,
                                "excluded_percent": 25, "excluded_kept": 3, "excluded_full_pass_runs": 3})  # fmt: skip
    reading = _reading(box, 992, "parsing")  # a protocol not yet compiling
    c, _ = login_crc(box)
    for jid in (weekly, reading):
        before = c.get(f"/pilot/jobs/{jid}").content
        strip["on"] = False
        after = c.get(f"/pilot/jobs/{jid}").content
        strip["on"] = True
        assert b'data-testid="recheck-share"' in before or jid == reading
        assert after == before, jid


# ---------------------------------------------------------------------------------------------- who is told
def _accounts(b: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    """(username, signed-in client) per account; the investigator has no row of GZQO's delegation log."""
    from tests.console.test_console_app import VIEWER_PW, login

    return {
        "coordinator": ("crc", login_crc(b)[0]),
        "investigator off the log": ("pi-off", _user(b, "pi-off", "investigator")),
        "viewer": ("viewer", login(b["app"], "viewer", VIEWER_PW)[0]),
        "privacy": ("priv-who", _user(b, "priv-who", "privacy")),
    }


def test_the_first_load_follows_the_candidate_lists_own_check(box: dict[str, Any]) -> None:
    """``Helpers.admits_candidates`` answers as the candidate list page does, for each account (the same check)."""
    h = box["app"].state.helpers
    answers = {}
    for name, (username, c) in _accounts(box).items():
        listed = c.get("/studies/GZQO/candidates", follow_redirects=False).status_code == 200
        assert h.admits_candidates(box["users"].get(username), "GZQO") is listed, name
        answers[name] = listed
    assert answers == {"coordinator": True, "investigator off the log": False, "viewer": False, "privacy": False}


def test_an_account_the_list_refuses_gets_none_of_the_numbers_and_no_read(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    jid = _run(box, 975, new_screened=4013, new_carried=9587, budget=4021)  # figures no other part of the page has
    reads: list[str] = []
    real = box["backend"].recheck_share

    def spy(job_id: str) -> Any:
        reads.append(job_id)
        return real(job_id)

    monkeypatch.setattr(box["backend"], "recheck_share", spy)
    accounts = _accounts(box)
    for name in ("investigator off the log", "viewer", "privacy"):
        reads.clear()
        r = accounts[name][1].get(f"/pilot/jobs/{jid}", follow_redirects=False)
        assert _block(r.text) is None, name
        for figure in ("4013", "9587", "4021", "3 more"):
            assert figure not in r.text, (name, figure)
        assert reads == [], (name, r.status_code)  # the event was not read for this account
    reads.clear()
    shown = accounts["coordinator"][1].get(f"/pilot/jobs/{jid}").text
    assert _block(shown) is not None and "9587" in shown and reads  # the list admits the coordinator


# ---------------------------------------------------------------------------------------------- the estimate
def test_the_estimate_is_at_this_runs_pace_never_the_boxs_budget(box: dict[str, Any]) -> None:
    """The review's probe: a box budget of 100 a night, of which this run reached 10 new patients, 500 waiting. At
    the box's budget it would say 5 nights; at the pace the run reached it is 50."""
    jid = _run(box, 976, budget=100, left=10, new_screened=10, new_carried=500)
    c, _ = login_crc(box)
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None
    assert str(escape(CATALOGUES["en"]["job.firstload.nights"].format(n=10, nights=50))) in block
    assert "about 5 more" not in block and "100" not in block  # nothing from the box's night budget


@pytest.mark.parametrize("lang", LANGS)
def test_a_run_that_screened_no_new_patient_gives_no_estimate(box: dict[str, Any], lang: str) -> None:
    jid = _run(box, 977, new_screened=0, new_carried=500)
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None and 'data-testid="first-load-nights"' not in block  # no pace, no estimate
    assert str(escape(CATALOGUES[lang]["job.firstload.line"].format(n=0, waiting=500))) in block


def test_the_runs_budget_event_is_read_once_a_page(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    jid = _run(box, 978, trigger="weekly", excluded_in_scope=8, excluded_rescreened=3, excluded_carried=5,
               excluded_percent=25, excluded_kept=3, excluded_full_pass_runs=3, left=12)  # fmt: skip
    reads: list[str] = []
    real = box["backend"].recheck_share

    def spy(job_id: str) -> Any:
        reads.append(job_id)
        return real(job_id)

    monkeypatch.setattr(box["backend"], "recheck_share", spy)
    c, _ = login_crc(box)
    page = c.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="recheck-share"' in page and _block(page) is not None  # both cards from the one read
    assert reads == [jid]


def test_a_long_compile_keeps_its_count_past_the_tables_window(box: dict[str, Any]) -> None:
    """More model answers than the page's table shows (200): the count still starts at the compile's start."""
    jid = _reading(box, 986)
    au = box["audit"]
    au.append("compile.start", job_id=jid, ruleset="GZQO", actor="criteria-compiler")
    for _ in range(260):
        au.append("llm.call", job_id=jid, actor="criteria-compiler")
    c, _ = login_crc(box)
    page = c.get(f"/pilot/jobs/{jid}").text
    got = _answers(page)
    assert got is not None and str(escape(CATALOGUES["en"]["job.compile.answers"].format(n=260))) in got
    assert CATALOGUES["en"]["job.audit.show"].format(n=200) in page  # the table still shows its newest 200
