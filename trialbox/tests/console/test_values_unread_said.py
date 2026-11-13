"""NEW-CAND-1 (D-713): the patient's page and the PI's weekly sample say when the run could not read the values
behind its coded answers.

D-652 made the run record it (``coded_values: not read`` in the run's stored list) and the page "Criteria not
matched" say it. The two other places a person reads a run's coded answers one by one did not: the criteria table
of a patient (the PI's patient page and the team's candidate page share it) and the weekly sample. A coded answer
there showed no value, with nothing to say why. Synthetic data only."""

from __future__ import annotations

import json
from typing import Any

import pytest
from console import i18n_review
from markupsafe import escape
from tb_common.crypto import sha256_bytes
from tb_common.wording import check
from tb_contracts import JobOutput

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401
from tests.console.test_not_matched_sample import DOC

PW = "values-unread-password-01"
A = "a" * 32
WORDS = {"en": i18n_review.EN, "ja": i18n_review.JA, "zh-TW": i18n_review.ZH}


def _run(b: dict[str, Any], doc: dict[str, Any] | None, n: int = 971) -> str:
    """A finished screening run; with ``doc``, its stored "not matched" list (where the run keeps the flag)."""
    job = _done_screen(b["backend"], _ulid(n))
    if doc is not None:
        data = json.dumps(doc).encode()
        key = f"outputs/{job.job_id}/excluded_GZQO_v1.0.0.json"
        b["backend"].objects[key] = data
        out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key,
                        recipients=[], tag="phi")  # fmt: skip
        b["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})
    return job.job_id


def _pi(b: dict[str, Any]) -> tuple[Any, str]:
    b["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(b, "pi")
    return login(b["app"], "pi", PW)


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_patients_page_says_the_values_were_not_read(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    _run(box, {**DOC, "coded_values": "not read"})
    pi, csrf = _pi(box)
    pi.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    page = pi.get(f"/studies/GZQO/patients/{A}")
    assert page.status_code == 200
    said = str(escape(WORDS[lang]["ex.unread.values"]))
    assert 'data-testid="values-unread"' in page.text and said in page.text
    # in the criteria card, above its table: where the reader looks for the values
    card = page.text.split('data-testid="values-unread"')[1]
    assert 'data-testid="criteria"' in card
    assert not check(WORDS[lang]["ex.unread.values"])


@pytest.mark.parametrize("doc", [{**DOC, "coded_values": "read"}, DOC, None],
                         ids=["read", "a list from before the flag", "a run with no stored list"])  # fmt: skip
def test_a_run_that_read_them_or_does_not_say_shows_no_such_sentence(
    box: dict[str, Any],  # noqa: F811
    doc: dict[str, Any] | None,
) -> None:
    _run(box, doc)
    pi, _ = _pi(box)
    page = pi.get(f"/studies/GZQO/patients/{A}")
    assert page.status_code == 200 and "values-unread" not in page.text


def test_the_weekly_sample_says_it_for_the_run_it_was_drawn_from(box: dict[str, Any]) -> None:  # noqa: F811
    _run(box, {**DOC, "coded_values": "not read"})
    pi, _ = _pi(box)
    page = pi.get("/studies/GZQO/not-matched/sample")
    assert page.status_code == 200 and "nm-counter" in page.text
    assert 'data-testid="nm-values-unread"' in page.text
    assert str(escape(i18n_review.EN["ex.unread.values"])) in page.text


def test_the_weekly_sample_of_a_run_that_read_them_says_nothing(box: dict[str, Any]) -> None:  # noqa: F811
    _run(box, {**DOC, "coded_values": "read"})
    pi, _ = _pi(box)
    page = pi.get("/studies/GZQO/not-matched/sample")
    assert page.status_code == 200 and "nm-counter" in page.text and "nm-values-unread" not in page.text
