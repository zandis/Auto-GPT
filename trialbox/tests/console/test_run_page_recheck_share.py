"""NEW-RUN-1 (D-558): the page of a weekly screening run says how far the run got with the patients whose criteria
were not matched before.

D-646 keeps a share of a study's night allowance for screening those patients again, and its run writes four
figures into the ``microbatch.budget`` event: how many are in scope, the share, how many places were kept, and how
many weekly runs a full pass takes. The page showed them only as raw ``key=value`` in the audit table. It now
says them in the reader's language, with "screened again / in scope", to the accounts that may read the study's
list (the figures are patient counts; those accounts see the list itself). Synthetic data only."""

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


@pytest.mark.parametrize("lang", LANGS)
def test_the_run_page_says_the_share_in_the_readers_language(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    jid = _run(box, 961)
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None, lang
    cat = CATALOGUES[lang]
    for key, kw in (("job.recheck.reached", {"n": 3, "scope": 8}), ("job.recheck.kept", {"kept": 3, "percent": 25}),
                    ("job.recheck.pass", {"runs": 3})):  # fmt: skip
        assert str(escape(cat[key].format(**kw))) in block, (lang, key)
    assert check_page(block) == [], lang  # none of the forbidden words, in any language
    assert "excluded_" not in block  # the event's field names are not the page's words


def test_a_run_that_could_keep_no_place_says_so_and_a_run_with_nobody_in_scope_says_nothing(
    box: dict[str, Any],  # noqa: F811
) -> None:
    c, _ = login_crc(box)
    none_kept = _run(box, 962, excluded_kept=0, excluded_rescreened=0, excluded_full_pass_runs=None)
    block = _block(c.get(f"/pilot/jobs/{none_kept}").text)
    assert block is not None and str(escape(CATALOGUES["en"]["job.recheck.nopass"])) in block
    assert CATALOGUES["en"]["job.recheck.pass"].split("{")[0] not in block
    nobody = _run(box, 963, excluded_in_scope=0, excluded_rescreened=0, excluded_kept=0, excluded_full_pass_runs=None)
    assert _block(c.get(f"/pilot/jobs/{nobody}").text) is None
    after_ingest = _run(box, 964, trigger="ingest")  # the run after an ingest keeps no share: nothing to say
    assert _block(c.get(f"/pilot/jobs/{after_ingest}").text) is None
    plain = _ulid(965)
    _done_screen(box["backend"], plain)  # a run with no budget event (an older run)
    assert _block(c.get(f"/pilot/jobs/{plain}").text) is None


def test_only_an_account_that_reads_the_studys_list_sees_the_block(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _run(box, 966)
    a, _ = login(box["app"])  # the administrator: the summary, not the list (D-280)
    assert _block(a.get(f"/pilot/jobs/{jid}").text) is None
    box["users"].create("viewer9", "viewer", VIEWER_PW, "viewer9@hospa.test")
    v, _ = login(box["app"], "viewer9", VIEWER_PW)
    assert _block(v.get(f"/pilot/jobs/{jid}").text) is None
    c, _ = login_crc(box)
    assert _block(c.get(f"/pilot/jobs/{jid}").text) is not None


def test_the_words_are_in_three_languages_with_the_same_places() -> None:
    for key in ("job.recheck.title", "job.recheck.reached", "job.recheck.kept", "job.recheck.pass",
                "job.recheck.nopass", "job.recheck.carried"):  # fmt: skip
        places = {lang: sorted(re.findall(r"\{(\w+)\}", CATALOGUES[lang][key])) for lang in LANGS}
        assert places["en"] == places["ja"] == places["zh-TW"], key
        for lang in LANGS:
            assert check_page(f"<p>{CATALOGUES[lang][key]}</p>") == [], (lang, key)
