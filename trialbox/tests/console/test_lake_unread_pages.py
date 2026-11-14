"""D-652, the console's side: what a page shows when the run's output says a lake read failed.

The "Criteria not matched" page names where an answer came from to the person who decides. When the confirmed
facts could not be read the run stores the source ``records``; the page says so in its own words, the filter can
select it, and a sentence above the list says what was not read. The feasibility page does not say "no notes in
the box" when the note data could not be read."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from console import i18n_home, i18n_review, studies
from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401

PW = "unread-page-password-01"
UNREAD = {
    "ruleset": "GZQO", "version": "1.0.0", "run_date": "2026-10-05", "snapshot": "2026-10-04",
    "confirmed_facts": "not read", "coded_values": "not read",
    "rows": [
        {"pid": "c" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-02", "source": "notes", "reason": "note", "quote": "history of breast cancer 2019",
             "quote_date": "2025-03-01", "resource_refs": ["DocumentReference/d1"]}]},
        {"pid": "d" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-01", "source": "records", "reason": "coded", "resource_refs": ["cond-1"]}]},
    ],
}  # fmt: skip


def _store(b: dict[str, Any], doc: dict[str, Any], n: int) -> None:
    job = _done_screen(b["backend"], _ulid(n))
    data = json.dumps(doc).encode()
    key = f"outputs/{job.job_id}/excluded_GZQO_v1.0.0.json"
    b["backend"].objects[key] = data
    out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key, recipients=[],
                    tag="phi")  # fmt: skip
    b["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})


def test_the_page_says_the_confirmed_facts_and_the_values_were_not_read(box: dict[str, Any]) -> None:  # noqa: F811
    _store(box, UNREAD, 971)
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")
    pi, csrf = login(box["app"], "pi", PW)
    page = pi.get("/studies/GZQO/excluded").text
    assert 'data-testid="ex-facts-unread"' in page and 'data-testid="ex-values-unread"' in page
    assert i18n_review.EN["ex.src.records"] in page and "ex.src.records" not in page  # words, never the raw key
    pill = page.split('data-testid="ex-source-dddddddd-1">')[1].split("</span>")[0]
    assert pill == i18n_review.EN["ex.src.records"]  # not "the coded records": that says no person confirmed it
    only = pi.get("/studies/GZQO/excluded?src=records").text  # the filter can select it
    assert 'data-testid="ex-dddddddd"' in only and 'data-testid="ex-cccccccc"' not in only
    for lang, words in (("ja", i18n_review.JA), ("zh-TW", i18n_review.ZH)):
        pi.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        page = pi.get("/studies/GZQO/excluded").text
        assert (
            words["ex.src.records"] in page and words["ex.unread.facts"] in page and words["ex.unread.values"] in page
        )


def _reader(b: dict[str, Any]) -> Any:
    b["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(b, "pi")
    return login(b["app"], "pi", PW)[0]


READ = {
    **UNREAD, "confirmed_facts": "read", "coded_values": "read",
    "rows": [{"pid": "d" * 32, "actions": [], "criteria": [
        {"id": "GZQO-EXC-01", "source": "coded", "reason": "coded", "resource_refs": ["cond-1"]}]}],
}  # fmt: skip


def test_a_run_that_read_everything_shows_no_such_sentence(box: dict[str, Any]) -> None:  # noqa: F811
    _store(box, READ, 972)
    page = _reader(box).get("/studies/GZQO/excluded").text
    assert "ex-facts-unread" not in page and "ex-values-unread" not in page and "the coded records" in page


def test_a_list_written_before_the_fields_existed_is_shown_as_before(box: dict[str, Any]) -> None:  # noqa: F811
    """In a box of its own (the review: two lists stored in one box at one time, and the page kept the first)."""
    _store(box, {k: v for k, v in READ.items() if k not in ("confirmed_facts", "coded_values")}, 973)
    page = _reader(box).get("/studies/GZQO/excluded").text
    assert 'data-testid="ex-dddddddd"' in page and "the coded records" in page
    assert "ex-facts-unread" not in page and "ex-values-unread" not in page


def test_an_answer_with_no_source_is_not_called_coded_when_the_facts_were_not_read(box: dict[str, Any]) -> None:  # noqa: F811
    doc = {**UNREAD, "rows": [{"pid": "d" * 32, "actions": [], "criteria": [
        {"id": "GZQO-EXC-01", "reason": "coded", "resource_refs": ["cond-1"]}]}]}  # fmt: skip
    _store(box, doc, 974)
    page = _reader(box).get("/studies/GZQO/excluded").text
    pill = page.split('data-testid="ex-source-dddddddd-1">')[1].split("</span>")[0]
    assert pill == i18n_review.EN["ex.src.records"]


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"appointment_rows": None, "note_chunks": None, "read": False}, "facts.notes.unknown"),
        ({"appointment_rows": None, "note_chunks": None}, "facts.notes.unknown"),  # a report from before D-652
        ({"appointment_rows": 3, "note_chunks": 0, "read": True}, "facts.notes.none"),
        ({"appointment_rows": 3, "note_chunks": 12, "read": True}, "facts.notes"),
    ],
)
def test_the_feasibility_page_does_not_say_no_notes_when_they_could_not_be_read(data: dict[str, Any], key: str) -> None:
    site: Any = SimpleNamespace(entered_at="2026-10-01")
    keys = [k for k, _ in studies.data_facts({"snapshot": "2026-10-04"}, {"data": data}, site)]
    assert key in keys and (key == "facts.notes.none" or "facts.notes.none" not in keys)
    for words in (i18n_home.EN, i18n_home.JA, i18n_home.ZH):
        assert words["facts.notes.unknown"]
