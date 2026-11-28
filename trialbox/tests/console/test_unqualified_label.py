"""SAFE-1 A1: a note answer given by a model pair with no qualification record on this box says so on the patient
page, in the three languages, beside the quote; an answer from a qualified pair shows no such label."""

from __future__ import annotations

import json
from typing import Any

import pytest
from console.i18n_review import EN, JA, ZH
from tb_common.wording import FORBIDDEN, LATER, check

import tests.console.test_console_app as _app
from tests.console.test_coded_criterion_row import CRITERIA, _client, _put, _rows
from tests.console.test_criterion_labels import _gzqo

box = _app.box  # the fixture, found by name
_done_screen, _ulid = _app._done_screen, _app._ulid

A = "a" * 32
WORDS = {"en": EN["model.unqualified"], "ja": JA["model.unqualified"], "zh-TW": ZH["model.unqualified"]}


def _run(b: dict[str, Any]) -> None:
    _gzqo(b)
    jid = _done_screen(b["backend"], _ulid(963)).job_id
    cl = json.loads(b["backend"].objects[f"outputs/{jid}/candidate_list_GZQO_v1.0.0.json"])
    crits = json.loads(json.dumps(CRITERIA))
    for c in crits:
        if c["id"] == "GZQO-INC-05":  # the note answer
            c["evidence"]["qualification"] = "unqualified"
    cl["rows"][0]["criteria"] = crits
    _put(b, jid, "candidate_list_GZQO_v1.0.0.json", cl)


@pytest.mark.parametrize("lang", sorted(WORDS))
def test_the_patient_page_labels_an_unqualified_answer(
    box: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
) -> None:
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    monkeypatch.setenv("TB_LLM_MODE", "gateway")  # a real model pair: not the test model
    _run(box)
    rows = _rows(_client(box, lang).get(f"/studies/GZQO/patients/{A}").text)
    note = rows["GZQO-INC-05"]
    assert 'data-testid="unqualified-GZQO-INC-05"' in note and WORDS[lang] in note
    assert "two flares this spring" in note  # the quote stays
    assert not any('data-testid="unqualified-' in tr for cid, tr in rows.items() if cid != "GZQO-INC-05")


def test_the_label_is_in_three_languages_and_gives_no_verdict() -> None:
    for cat in (EN, JA, ZH):
        words = [cat["model.unqualified"], cat["model.unqualified.why"]]
        assert all(words) and check(" ".join(words), (*FORBIDDEN, *LATER)) == [], words
