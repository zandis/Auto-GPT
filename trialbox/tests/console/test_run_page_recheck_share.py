"""NEW-RUN-1 (D-558): the page of a weekly screening run says how far the run got with the patients whose records
did not match a criterion before.

D-646 keeps a share of a study's night budget for screening those patients again, and its run writes the figures
into the ``microbatch.budget`` event: how many are in scope, the share, how many places were kept, and how many
weekly runs it takes to screen them all again. The page said none of them (the audit table shows a fixed list of an
event's keys, and these are not on it). It now says them in the reader's language, to the accounts that read the
study's list. Every fixture below is a set of figures the run can write (``orchestrator.scenarios.microbatch``:
places kept = the smaller of the share of what was left and the patients waiting; carried = in scope - screened
again; the number of runs is 1 whenever nobody was carried, None when no place can be kept). Synthetic data only."""

from __future__ import annotations

import re
from typing import Any

import pytest
from console.i18n import CATALOGUES
from markupsafe import escape
from tb_common.wording import check_page

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    VIEWER_PW,
    _done_screen,
    _ulid,
    box,
    login,
    login_crc,
)

LANGS = ("en", "ja", "zh-TW")
BUDGET: dict[str, Any] = {
    "trigger": "weekly", "budget": 40, "left": 12, "rechecked": 9, "recheck_carried": 0, "new_screened": 0,
    "excluded_rescreened": 3, "excluded_back": 1, "excluded_carried": 5, "excluded_in_scope": 8,
    "excluded_percent": 25, "excluded_kept": 3, "excluded_full_pass_runs": 3,
}  # fmt: skip


def _run(b: dict[str, Any], n: int, **detail: Any) -> str:
    jid = _ulid(n)
    _done_screen(b["backend"], jid)
    b["audit"].append("microbatch.budget", job_id=jid, ruleset="GZQO", actor="orchestrator",
                      detail={**BUDGET, **detail})  # fmt: skip
    return jid


def _block(page: str) -> str | None:
    m = re.search(r'<section[^>]*data-testid="recheck-share"[^>]*>(.*?)</section>', page, re.S)
    return m.group(1) if m else None


def _said(lang: str, key: str, **kw: Any) -> str:
    return str(escape(CATALOGUES[lang][key].format(**kw)))


@pytest.mark.parametrize("lang", LANGS)
def test_the_run_page_says_the_share_in_the_readers_language(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    jid = _run(box, 961)  # 12 left, a quarter of it is 3 places, 3 of 8 screened again, 5 carried, 3 runs
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None, lang
    for key, kw in (("job.recheck.reached", {"n": 3, "scope": 8}), ("job.recheck.kept", {"kept": 3, "percent": 25}),
                    ("job.recheck.carried", {"n": 5}), ("job.recheck.pass", {"runs": 3})):  # fmt: skip
        assert _said(lang, key, **kw) in block, (lang, key)
    assert _said(lang, "job.recheck.all") not in block
    assert check_page(block) == [], lang  # none of the forbidden words, in any language
    assert "excluded_" not in block  # the event's field names are not the page's words


CASES: dict[str, tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]] = {
    # the commonest: a night budget far larger than the patients waiting, everybody reached. The share is a limit
    # (a quarter of 2000 is 500, the places kept are 8), and the run's "1 run" is not a figure of the share
    "everybody reached": (
        {"left": 2000, "excluded_kept": 8, "excluded_in_scope": 8, "excluded_rescreened": 8, "excluded_carried": 0,
         "excluded_full_pass_runs": 1},
        ("all", "kept"), ("pass", "nopass", "carried", "noshare"),
    ),
    # no night budget on this box: there is no share to speak of
    "no night budget": (
        {"left": None, "excluded_kept": 0, "excluded_in_scope": 8, "excluded_rescreened": 8, "excluded_carried": 0,
         "excluded_full_pass_runs": 1},
        ("all",), ("kept", "pass", "nopass", "carried", "noshare"),
    ),
    # the share is set to 0: some were reached because the others left room; no place is "too small" to keep
    "no share by setting": (
        {"left": 12, "excluded_percent": 0, "excluded_kept": 0, "excluded_in_scope": 8, "excluded_rescreened": 2,
         "excluded_carried": 6, "excluded_full_pass_runs": None},
        ("noshare", "carried"), ("kept", "pass", "nopass", "all"),
    ),
    # a quarter of the 3 left is less than one place
    "allowance too small": (
        {"left": 3, "excluded_kept": 0, "excluded_in_scope": 8, "excluded_rescreened": 0, "excluded_carried": 8,
         "excluded_full_pass_runs": None},
        ("kept", "carried", "nopass"), ("pass", "all", "noshare"),
    ),
    # the run can write "1 run" beside patients carried over (it counts the waiting before the re-checks): the
    # page does not say a number of runs it contradicts in the next line
    "one run and some carried": (
        {"left": 40, "excluded_kept": 2, "excluded_in_scope": 5, "excluded_rescreened": 2, "excluded_carried": 3,
         "excluded_full_pass_runs": 1},
        ("kept", "carried"), ("pass", "nopass", "all", "noshare"),
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_case_of_the_run_is_said_as_the_run_means_it(box: dict[str, Any], case: str) -> None:  # noqa: F811
    detail, said, unsaid = CASES[case]
    jid = _run(box, 970, **detail)
    c, _ = login_crc(box)
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None, case
    for key in said:
        assert str(escape(CATALOGUES["en"][f"job.recheck.{key}"].split("{")[0])) in block, (case, key)
    for key in unsaid:
        head = CATALOGUES["en"][f"job.recheck.{key}"].split("{")[0]
        assert str(escape(head)) not in block, (case, key)
    ev = {**BUDGET, **detail}
    assert _said("en", "job.recheck.reached", n=ev["excluded_rescreened"], scope=ev["excluded_in_scope"]) in block
    if "kept" in said:
        assert _said("en", "job.recheck.kept", kept=ev["excluded_kept"], percent=ev["excluded_percent"]) in block
    if "carried" in said:
        assert _said("en", "job.recheck.carried", n=ev["excluded_carried"]) in block


def test_a_run_with_nobody_in_scope_or_no_weekly_event_says_nothing(box: dict[str, Any]) -> None:  # noqa: F811
    c, _ = login_crc(box)
    nobody = _run(box, 963, excluded_in_scope=0, excluded_rescreened=0, excluded_kept=0, excluded_carried=0,
                  excluded_full_pass_runs=1)  # fmt: skip
    assert _block(c.get(f"/pilot/jobs/{nobody}").text) is None
    after_ingest = _run(box, 964, trigger="ingest")  # the run after an ingest keeps no share: nothing to say
    assert _block(c.get(f"/pilot/jobs/{after_ingest}").text) is None
    plain = _ulid(965)
    _done_screen(box["backend"], plain)  # a run with no budget event (an older run)
    assert _block(c.get(f"/pilot/jobs/{plain}").text) is None
    running = _run(box, 967)  # the event is written before the run ends: the page waits for the end
    job = box["backend"].jobs[running]
    box["backend"].jobs[running] = job.model_copy(update={"state": "reporting"})
    r = c.get(f"/pilot/jobs/{running}")
    assert r.status_code == 200 and _block(r.text) is None


def test_only_an_account_that_reads_the_studys_list_sees_the_block(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _run(box, 966)
    a, _ = login(box["app"])  # the administrator opens the page and sees the summary, not the list (D-280)
    r = a.get(f"/pilot/jobs/{jid}")
    assert r.status_code == 200 and 'data-testid="screen"' in r.text and _block(r.text) is None
    # an investigator the study's PI has not ticked for screening: no rows, so no block
    box["users"].create("inv9", "investigator", VIEWER_PW, "inv9@hospa.test")
    i, _ = login(box["app"], "inv9", VIEWER_PW)
    r = i.get(f"/pilot/jobs/{jid}")
    assert r.status_code in (200, 403, 404)
    assert _block(r.text) is None and (r.status_code != 200 or 'data-testid="screen-rows"' not in r.text)
    c, _ = login_crc(box)
    assert _block(c.get(f"/pilot/jobs/{jid}").text) is not None


def test_the_words_are_in_three_languages_with_the_same_places() -> None:
    for key in ("job.recheck.title", "job.recheck.reached", "job.recheck.all", "job.recheck.kept",
                "job.recheck.noshare", "job.recheck.pass", "job.recheck.nopass", "job.recheck.carried"):  # fmt: skip
        places = {lang: sorted(re.findall(r"\{(\w+)\}", CATALOGUES[lang][key])) for lang in LANGS}
        assert places["en"] == places["ja"] == places["zh-TW"], key
        for lang in LANGS:
            assert check_page(f"<p>{CATALOGUES[lang][key]}</p>") == [], (lang, key)
