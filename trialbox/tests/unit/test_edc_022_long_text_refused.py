"""EDC-022 (D-854): a reason for change or a citation's text longer than 300 characters is refused, never cut.

Deep review EDC-022 (Low): the store cut a reason and a citation text at 300 characters without a word, so a long
reason was stored incomplete in a regulated trail. The person is now told and nothing is stored; 300 characters
still go in whole."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc.store import TEXT_MAX, EdcError

from tests import edc_kit as k

SHEET = {"text": "ward scale sheet", "day": "2026-11-05"}


def _drafts(svc: Any) -> dict[str, dict[str, Any]]:
    svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    return {d["item"]: d for d in svc.store.drafts(k.STUDY, k.RECORD)}


def test_a_reason_of_301_characters_is_refused_and_nothing_is_stored(tmp_path: Path) -> None:
    svc, _sim, _tok = k.service(tmp_path)
    k.ready(svc)
    d = _drafts(svc)["weight"]
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "edit", value="73", reason="r" * (TEXT_MAX + 1), citation=SHEET, by="crc")
    assert e.value.code == "edc.too_long" and e.value.status == 400
    now = svc.store.draft(k.STUDY, d["id"])
    assert now is not None and now["fate"] == d["fate"]  # nothing changed


def test_a_reason_of_300_characters_is_kept_whole(tmp_path: Path) -> None:
    svc, _sim, _tok = k.service(tmp_path)
    k.ready(svc)
    d = _drafts(svc)["weight"]
    reason = "scale re-read " + "x" * (TEXT_MAX - 14)
    svc.decide(k.STUDY, d["id"], "edit", value="73", reason=reason, citation=SHEET, by="crc")
    now = svc.store.draft(k.STUDY, d["id"])
    assert now is not None and now["reason"] == reason


def test_a_citation_text_of_301_characters_is_refused(tmp_path: Path) -> None:
    svc, _sim, _tok = k.service(tmp_path)
    k.ready(svc)
    d = _drafts(svc)["weight"]
    cite = {"text": "c" * (TEXT_MAX + 1), "day": "2026-11-05"}
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "edit", value="73", reason="scale re-read", citation=cite, by="crc")
    assert e.value.code == "edc.too_long"


def test_the_switchs_reason_is_refused_too(tmp_path: Path) -> None:
    svc, _sim, _tok = k.service(tmp_path)
    k.ready(svc)
    with pytest.raises(EdcError) as e:
        svc.set_switch(k.STUDY, False, by="pi", role="investigator", reason="s" * (TEXT_MAX + 1))
    assert e.value.code == "edc.too_long"
