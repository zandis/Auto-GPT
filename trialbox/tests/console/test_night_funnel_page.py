# ruff: noqa: F811 - the box fixture is imported and taken by name
"""10E-12 (D-1259): a finished nightly job's page shows the night's pre-filter funnel of its study, as one more block
for exactly the accounts the first-load card is shown to (the study's candidate list's own check). No new route,
page, export or role. With no record the page is byte-identical to the page without the block. Synthetic data only."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pytest
from console.i18n import CATALOGUES
from markupsafe import escape
from tb_common import prefilter
from tb_common.wording import check_page
from tb_contracts import JobMetrics, PrefilterRecord

from tests.console.test_console_app import _done_screen, _ulid, box, login_crc  # noqa: F401
from tests.console.test_job_page_progress import _accounts

LANGS = ("en", "ja", "zh-TW")
NIGHT = date(2026, 10, 5)


def _rec(trigger: str = "weekly", **c: int) -> PrefilterRecord:
    counts = {s: c.get(s, 0) for s in prefilter.STAGES}
    return PrefilterRecord(trigger=trigger, in_scope=sum(counts.values()), **counts)  # type: ignore[arg-type]


def _nightly(b: dict[str, Any], n: int, rec: PrefilterRecord | None, *, night: date = NIGHT, state: str = "done",
             ruleset: str = "GZQO") -> str:  # fmt: skip
    jid = _ulid(n)
    job = _done_screen(b["backend"], jid)
    b["backend"].jobs[jid] = job.model_copy(
        update={
            "type": "MICROBATCH",
            "run_date": night,
            "state": state,
            "ruleset": ruleset,
            "metrics": JobMetrics(patients_scoped=7, prefilter=rec),
        }
    )
    return jid


def _block(page: str) -> str | None:
    m = re.search(r'<section[^>]*data-testid="night-funnel"[^>]*>(.*?)</section>', page, re.S)
    return m.group(1) if m else None


def _cells(block: str) -> dict[str, tuple[str, str]]:
    return {
        k: (rem.strip(), left.strip())
        for k, rem, left in re.findall(
            r'<tr data-stage="(\w+)"><th scope="row">[^<]*</th><td>([^<]*)</td><td>([^<]*)</td></tr>', block
        )
    }


WEEKLY = _rec(opted_out=3, not_due=4013, carried=211, coded_excluded=967, no_model=41, model_not_listed=59, listed=17)
INGEST = _rec("ingest", not_due=120, coded_excluded=6, listed=2)


@pytest.mark.parametrize("lang", LANGS)
def test_the_nights_funnel_sums_the_nights_jobs_in_the_readers_language(box: dict[str, Any], lang: str) -> None:
    jid = _nightly(box, 901, WEEKLY)
    _nightly(box, 902, INGEST)  # the same study and night: summed
    _nightly(box, 903, _rec(listed=7000), night=date(2026, 10, 4))  # another night
    _nightly(box, 904, _rec(listed=7000), ruleset="ABCD")  # another study
    _nightly(box, 905, _rec(listed=7000), state="running")  # not finished
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None, lang
    cat = CATALOGUES[lang]
    assert str(escape(cat["job.prefilter.title"])) in block
    assert str(escape(cat["job.prefilter.what"].format(study="GZQO", date="2026-10-05", jobs=2))) in block
    assert str(escape(cat["job.prefilter.sums"])) in block  # two runs: the figures are sums, said in one line
    for s in ("in_scope", *prefilter.STAGES):
        assert str(escape(cat[f"job.prefilter.{s}"])) in block, (lang, s)
    assert check_page(block) == [], lang
    total = WEEKLY.in_scope + INGEST.in_scope
    assert _cells(block) == {
        "in_scope": ("", str(total)),
        "opted_out": ("3", str(total - 3)),
        "not_due": ("4133", str(total - 3 - 4133)),
        "carried": ("211", str(total - 3 - 4133 - 211)),
        "coded_excluded": ("973", str(41 + 59 + 19)),
        "no_model": ("41", str(59 + 19)),
        "model_not_listed": ("59", "19"),
        "listed": ("", "19"),
    }  # exact counts: an internal page (D-99); no suppression marks
    assert "7000" not in block and "7019" not in block


def test_the_block_is_the_same_on_every_job_page_of_the_night(box: dict[str, Any]) -> None:
    a = _nightly(box, 906, WEEKLY)
    b = _nightly(box, 907, INGEST)
    c, _ = login_crc(box)
    assert _block(c.get(f"/pilot/jobs/{a}").text) == _block(c.get(f"/pilot/jobs/{b}").text) is not None


def test_only_the_accounts_the_candidate_list_admits_see_it_and_nobody_else_reads_the_nights_jobs(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The role walk: the coordinator on GZQO's delegation log sees the block; an investigator off the log, a viewer
    and the privacy officer open the same job page and get none of its numbers, and the night's other jobs are not
    even read for them (the check comes first)."""
    jid = _nightly(box, 908, WEEKLY)
    _nightly(box, 909, INGEST)
    reads: list[dict[str, Any]] = []
    real = box["backend"].list_jobs

    def spy(*a: Any, **kw: Any) -> Any:
        reads.append(kw)
        return real(*a, **kw)

    monkeypatch.setattr(box["backend"], "list_jobs", spy)
    accounts = _accounts(box)
    for name in ("investigator off the log", "viewer", "privacy"):
        reads.clear()
        r = accounts[name][1].get(f"/pilot/jobs/{jid}", follow_redirects=False)
        assert _block(r.text) is None, name
        for figure in ("4133", "4013", "973", str(WEEKLY.in_scope + INGEST.in_scope)):
            assert figure not in r.text, (name, figure)
        assert not [kw for kw in reads if kw.get("type_") == "MICROBATCH"], name
    reads.clear()
    shown = accounts["coordinator"][1].get(f"/pilot/jobs/{jid}").text
    assert _block(shown) is not None and "4133" in shown
    assert [kw for kw in reads if kw] == [
        {"ruleset": "GZQO", "type_": "MICROBATCH"}
    ]  # one read of the study's finished nightly jobs


@pytest.mark.parametrize("state", ["running", "failed"])
def test_a_nightly_job_not_done_shows_nothing(box: dict[str, Any], state: str) -> None:
    jid = _nightly(box, 910, WEEKLY, state=state)
    c, _ = login_crc(box)
    assert _block(c.get(f"/pilot/jobs/{jid}").text) is None


def test_a_night_that_cannot_be_read_whole_shows_nothing(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The newest finished nightly jobs of the study, as many as the console reads, all of this night or later: an
    earlier job of the night may be missing, so no block (never a short count)."""
    from console import app as console_app

    monkeypatch.setattr(console_app, "NIGHT_JOBS", 2)
    jid = _nightly(box, 911, WEEKLY)
    _nightly(box, 912, INGEST)
    c, _ = login_crc(box)
    assert _block(c.get(f"/pilot/jobs/{jid}").text) is None
    _nightly(box, 913, _rec(listed=1), night=date(2026, 10, 4))  # an earlier night is read: the night is whole
    monkeypatch.setattr(console_app, "NIGHT_JOBS", 3)
    assert _block(c.get(f"/pilot/jobs/{jid}").text) is not None


#: the block this card adds to job.html, as written there
_ADDED = re.compile(r"\{% if night %\}<section.*?</section>\n\{% endif %\}", re.S)


def test_a_job_page_without_a_record_is_byte_for_byte_the_page_without_the_block(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The render comparison: job.html as shipped and job.html with this card's block cut out render the same bytes
    for every job without a record (a nightly job from before the record, a SCREEN job, a failed nightly job), and
    the night's jobs are not read for them. (Text outside the block was compared with master's own render of the
    same pages across two worktrees; the pull request has the method.)"""
    from jinja2 import FileSystemLoader

    real = FileSystemLoader.get_source
    strip = {"on": True}

    def get_source(self: FileSystemLoader, env: Any, name: str) -> tuple[str, str | None, Any]:
        src, filename, _ = real(self, env, name)
        if name == "job.html" and strip["on"]:
            src, n = _ADDED.subn("", src)
            assert n == 1
        return src, filename, lambda: False

    monkeypatch.setattr(FileSystemLoader, "get_source", get_source)
    old = _nightly(box, 921, None)
    screen = _ulid(922)
    _done_screen(box["backend"], screen)
    failed = _nightly(box, 923, WEEKLY, state="failed")
    reads: list[Any] = []
    real_list = box["backend"].list_jobs

    def spy(*a: Any, **kw: Any) -> Any:
        reads.append(kw)
        return real_list(*a, **kw)

    monkeypatch.setattr(box["backend"], "list_jobs", spy)
    c, _ = login_crc(box)
    live = re.compile(rb'data-(?:idle|abs)-left="\d+"')  # the idle warning's live seconds (D-1370)
    for jid in (old, screen, failed):
        before = c.get(f"/pilot/jobs/{jid}").content
        strip["on"] = False
        after = c.get(f"/pilot/jobs/{jid}").content
        strip["on"] = True
        assert live.sub(b"", after) == live.sub(b"", before), jid
    assert not [kw for kw in reads if kw.get("type_") == "MICROBATCH"]


@pytest.mark.parametrize("lang", LANGS)
def test_a_night_of_one_run_does_not_say_the_figures_are_sums(box: dict[str, Any], lang: str) -> None:
    jid = _nightly(box, 931, WEEKLY)
    c, csrf = login_crc(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    block = _block(c.get(f"/pilot/jobs/{jid}").text)
    assert block is not None and 'data-testid="night-funnel-sums"' not in block
    assert str(escape(CATALOGUES[lang]["job.prefilter.what"].format(study="GZQO", date="2026-10-05", jobs=1))) in block


def test_the_card_is_refused_to_an_investigator_off_the_delegation_log_whatever_the_page_answers(
    box: dict[str, Any],
) -> None:
    """Asked directly, not through the page's status (card 10C-3c closes the page itself to that account): the card's
    own rule answers None for the investigator off GZQO's log, and reads no other job for them; the coordinator on
    the log gets the figures."""
    from console.night_funnel import night_card

    jid = _nightly(box, 932, WEEKLY)
    _nightly(box, 933, INGEST)
    job = box["backend"].jobs[jid]
    h = box["app"].state.helpers
    _accounts(box)  # signs the accounts up
    reads: list[Any] = []

    def list_jobs(*a: Any, **kw: Any) -> list[Any]:
        reads.append(kw)
        return box["backend"].list_jobs(*a, **kw)

    off = box["users"].get("pi-off")
    assert off is not None
    assert night_card(job, off, h.admits_candidates, list_jobs) is None and reads == []
    assert night_card(job, off, None, list_jobs) is None and reads == []  # no check wired: nobody
    card = night_card(job, box["users"].get("crc"), h.admits_candidates, list_jobs)
    assert card is not None and card["jobs"] == 2 and card["in_scope"] == WEEKLY.in_scope + INGEST.in_scope


def test_a_record_that_does_not_add_up_is_a_fault_and_nothing_is_shown(
    box: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    jid = _nightly(box, 934, WEEKLY)
    broken = WEEKLY.model_copy(update={"in_scope": WEEKLY.in_scope + 1})  # stored by something else, or damaged
    _nightly(box, 935, broken)
    c, _ = login_crc(box)
    with caplog.at_level("ERROR", logger="console.night_funnel"):
        page = c.get(f"/pilot/jobs/{jid}").text
    assert _block(page) is None
    assert any("1 pre-filter record(s) do not add up" in r.getMessage() for r in caplog.records)
