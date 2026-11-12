"""G1 B1: a confirmed chart fact counts even when the model leaves its date empty.

In G1 (hospital-ja, 50,000 patients, the real model pair) stage 12 confirmed every chart fact and both chart patients
still needed information: 10000004 should have been ready and 10000005 excluded by its confirmed breast cancer. It
passed in every rehearsal because the rehearsals ran on the stub, whose chart reader copies the date of the dated line
above onto every fact. The prompt asks for the date "as written in the chart, empty when the chart does not say", so
a real model leaves a lab line or "乳癌（2019年手術）" without a full date. Such a fact reached the lake with no date,
and by DUMP-01 an undated record leaves a criterion unknown: confirming it could never settle the criterion. The
patient count had nothing to do with it (the site space has its own lake, the stub run passes at 500 and 5,000).

The fix: a chart fact without a date of its own takes the date of the chart section it is quoted from (the last
dated line at or above the quote), as the stub always did; it is shown on the review list before anyone confirms it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from llm_stub import handlers
from sitesetup import charts, help, mapping, readiness
from sitesetup.ocr import NoOcr
from sitesetup.service import SiteSetup
from sitesetup.store import SetupStore
from tb_common import dates
from tb_common.audit import AuditLog

from tests.unit.test_site_setup import KEY, NOW, TODAY, WS, pid, site_ruleset


class LiteralReader:
    """A chart reader that follows the prompt to the letter, as the real judge did in G1: the stub's facts, but a
    fact's ``date`` is only what its own line writes (a full date, or "2019年" as written), else empty."""

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        assert prompt_id == "chart_facts"
        out = handlers.chart_facts({"chart": variables["text"]})
        for f in out["facts"]:
            own = dates.CHART_SPAN.search(f["quote"])
            year = "2019年" if "2019年" in f["quote"] else ""
            f["date"] = own.group(0) if own else year
        return out


@pytest.fixture
def literal(tmp_path: Path) -> Any:
    s = SiteSetup(
        SetupStore(),
        tmp_path / "setup",
        LakeLocal(tmp_path / "main-lake", HashEmbedder()),
        LiteralReader(),
        AuditLog(tmp_path / "audit"),
        lambda: NOW,
        lambda: TODAY,
        lambda: KEY,
        ocr=NoOcr(),
        mrn_regex=r"^\d{8}$",
    )
    yield s
    s.store.close()


def _states(svc: SiteSetup) -> dict[str, str]:
    return {p["pid"]: p["state"] for p in readiness.patient_check(svc, WS, site_ruleset(), TODAY)}


def test_confirmed_chart_facts_count_when_the_model_gave_no_date(literal: SiteSetup) -> None:
    """Stage 12's path at the service level, with a reader that dates nothing it was not told: once confirmed, the
    malignancy excludes 10000005 and the chart makes 10000004 ready (G1 returned "needs" for both)."""
    inp = help.practice_inputs()
    for no, text in inp["charts"]:
        literal.add_chart(WS, no, "pasted.txt", text.encode(), "crc", "ja", pasted=True)
    literal.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    for c in literal.store.locals(WS):
        target = {"system": c["suggested_system"], "code": c["suggested_code"]}
        if not c["suggested_code"] or c["code"] == "ZI10":
            target = {"system": mapping.ICD10CM, "code": "I10"}
        literal.map_code(WS, c["domain"], c["system"], c["code"], target, "crc")
    proposed = literal.store.facts(WS, "proposed")
    assert proposed and all(f["pid"] in {pid("10000004"), pid("10000005")} for f in proposed)
    assert _states(literal)[pid("10000005")] == "needs"  # proposed: never counts, never excludes (D-135)
    for f in proposed:
        literal.decide(int(f["id"]), "confirm", "crc")
    st = _states(literal)
    assert (st[pid("10000004")], st[pid("10000005")]) == ("ready", "not_eligible"), st


def test_an_undated_chart_fact_takes_the_date_of_its_chart_section() -> None:
    """The date rule itself: the dated line at or above the quote; a date of birth is never the visit's date; a date
    the model gave is kept; a chart without any date leaves the fact undated (unknown, DUMP-01)."""
    text = (
        "外来記録　2026年9月18日\n生年月日 昭和36年4月3日\n診断：痛風\n"
        "再診　2026年10月20日\n検査：尿酸 8.8 mg/dL\n過去病史：乳癌（2019年手術）\n"
    )
    assert charts.section_day(text, "診断：痛風") == "2026-09-18"
    assert charts.section_day(text, "尿酸 8.8 mg/dL") == "2026-10-20"
    assert charts.section_day(text, "乳癌（2019年手術）") == "2026-10-20"
    assert charts.section_day("生年月日 昭和36年4月3日\n診断：痛風\n", "診断：痛風") == ""
    assert charts.section_day("診断：痛風\n", "診断：痛風") == ""
    assert charts.section_day(text, "not in the chart") == ""

    class Reader:
        def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
            return {
                "facts": [
                    {"domain": "condition", "term": "痛風", "code": "M10.9", "system": "icd10cm", "value": "",
                     "unit": "", "date": "", "quote": "診断：痛風"},
                    {"domain": "observation", "term": "尿酸", "code": "3084-1", "system": "loinc", "value": "8.8",
                     "unit": "mg/dL", "date": "2026年10月1日", "quote": "尿酸 8.8 mg/dL"},
                    {"domain": "condition", "term": "乳癌", "code": "C50.919", "system": "icd10cm", "value": "",
                     "unit": "", "date": "2019年", "quote": "乳癌（2019年手術）"},
                    {"domain": "birth_date", "term": "", "code": "", "system": "", "value": "昭和36年4月3日",
                     "unit": "", "date": "", "quote": "生年月日 昭和36年4月3日"},
                ]
            }  # fmt: skip

    kept, dropped = charts.extract(Reader(), text, "ja")
    assert dropped == 0
    assert [(f["domain"], f["day"]) for f in kept] == [
        ("condition", "2026-09-18"),  # no date given: its section's
        ("observation", "2026-10-01"),  # a date the model gave is kept
        ("condition", "2026-10-20"),  # "2019年" is no day: recorded in the visit of 2026-10-20
        ("demographic", ""),  # a date of birth has no day
    ]
