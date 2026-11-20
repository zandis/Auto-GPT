# ruff: noqa: F811 - the fixtures are imported and taken by name
"""D-1253 on the console. The data-ops batch page shows a night's record-id counts:
- id collisions per record type;
- links left out because the number was only another patient's;
- deletes without a chart number;
- rows rejected for no chart number.
Counts only, never a number, an id or a patient, in en, ja and zh-TW. With every count zero the page is the page
without the card. A study frozen for EDC prefill (its kept values cite the earlier rule's records) says why on its
EDC page; any other study's page is unchanged. Synthetic data only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from console import dataops_page, i18n_dataops
from datacore.dataops import DataOps
from tb_common.audit import AuditLog

from tests.console.test_console_app import box, login  # noqa: F401
from tests.console.test_edc_pages import PW, _ready, eb  # noqa: F401
from tests.console.test_role_pages import PW as STEWARD_PW
from tests.console.test_role_pages import _user
from tests.unit.test_edc import _confirm_all

AT = "2026-11-11T02:00:00+09:00"
IDS = {"id_collisions": {"Condition": 2, "Observation": 5}, "links_to_absent_records": {"diagnosis": 1},
       "deletes_without_patient": {"diagnosis": 3}, "rejected_no_patient": {"lab": 4}}  # fmt: skip


def _night(b: dict[str, Any], snap: str, extra: dict[str, Any]) -> int:
    ops = DataOps()
    try:
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.done", source="csv",
                                    snapshot=snap, passed=True, held=False, by="adapter", at=AT, actor="adapter",
                                    detail={"counts": {"Observation": 10}, **extra})  # fmt: skip
        return batch.id
    finally:
        ops.close()


def _steward(b: dict[str, Any]) -> Any:
    _user(b, "stwi", "steward")
    c, _ = login(b["app"], "stwi", STEWARD_PW)
    return c


def test_the_night_shows_its_id_counts_largest_first_counts_only(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10", IDS)
    page = _steward(box).get(f"/data-ops/batches/{bid}").text
    m = re.search(r'<section class="card" data-testid="batch-ids">(.*?)</section>', page, re.S)
    assert m
    rows = re.findall(r'data-kind="([a-z_]+)" data-where="([A-Za-z_]+)"><td>[^<]*</td><td class="mono">[^<]*</td>'
                      r'<td class="num">([0-9,]+)</td>', m.group(1))  # fmt: skip
    assert rows == [("collisions", "Observation", "5"), ("collisions", "Condition", "2"),
                    ("absent", "diagnosis", "1"), ("deletes", "diagnosis", "3"), ("no_patient", "lab", "4")]  # fmt: skip
    assert i18n_dataops.EN["dataops.ids.title"] in page


@pytest.mark.parametrize("extra", [{}, {k: {t: 0 for t in v} for k, v in IDS.items()}, {"id_collisions": None}])
def test_with_no_count_above_zero_the_page_is_the_page_without_the_card(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, extra: dict[str, Any]
) -> None:
    bid = _night(box, "2026-11-10", extra)
    c = _steward(box)
    shown = c.get(f"/data-ops/batches/{bid}").text
    monkeypatch.setattr(dataops_page, "ids_of", lambda _d: [])  # the page as it was before the card
    assert 'data-testid="batch-ids"' not in shown and shown == c.get(f"/data-ops/batches/{bid}").text


def test_a_name_that_is_not_a_table_or_a_type_is_never_shown() -> None:
    got = dataops_page.ids_of({"id_collisions": {"Condition": 1, "10000001": 2, "a b": 3, "x": "7", "y": True}})
    assert got == [("collisions", "Condition", 1)]


def test_every_kind_has_its_words_in_three_languages() -> None:
    for kind, _ in dataops_page.ID_COUNTS:
        for cat in (i18n_dataops.EN, i18n_dataops.JA, i18n_dataops.ZH):
            assert cat[f"dataops.ids.kind.{kind}"].strip()


def test_a_frozen_study_says_why_on_its_edc_page_and_another_page_is_unchanged(eb: dict[str, Any]) -> None:
    _ready(eb)
    crc, _ = login(eb["app"], "crc", PW)
    before = crc.get("/studies/GZQO/edc").text
    assert 'data-testid="edc-id-rule-frozen"' not in before
    _confirm_all(eb["svc"])  # a decided value: the study's trail (stamped at its draft run: not frozen)
    assert 'data-testid="edc-id-rule-frozen"' not in crc.get("/studies/GZQO/edc").text
    eb["svc"].store.db.execute("UPDATE tb_id_rule_study SET rule = 1")  # as the migration stamps a study before D-1253
    page = crc.get("/studies/GZQO/edc").text
    assert 'data-testid="edc-id-rule-frozen"' in page and "D-1253" in page
