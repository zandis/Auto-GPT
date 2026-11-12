"""G1 B1 (D-470, proposed): an undated chart fact stays unknown, and stage 12's evidence can settle the cause.

In G1 (hospital-ja, the real model pair) stage 12 confirmed every chart fact and both chart patients still needed
information. Two causes fit the evidence: the model left facts undated (an undated record leaves a criterion unknown,
DUMP-01), or it dropped the demographic facts. Neither is shown. These tests hold the safe state: a confirmed chart
fact without a date never decides an exclusion (it leaves the patient "needs"), including in the two cases where
taking the date of the chart section would have harmed a patient. They also check the stage-12 evidence that will
tell the two causes apart in the next real-model run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from llm_stub import handlers
from sitesetup import help, mapping, readiness
from sitesetup.ocr import NoOcr
from sitesetup.service import SiteSetup
from sitesetup.store import SetupStore
from tb_common import dates
from tb_common.audit import AuditLog
from tb_common.ruleset import Ruleset

from tests.unit import test_site_setup as ts
from tests.unit.test_site_setup import KEY, NOW, TODAY, WS, pid, site_ruleset
from tools.e2e_simple import chart_fact_kinds


class LiteralReader:
    """A chart reader that follows the prompt to the letter: the stub's facts, but a fact's ``date`` is only a full
    date its own line writes, else empty (never a date of birth)."""

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        assert prompt_id == "chart_facts"
        out = handlers.chart_facts({"chart": variables["text"]})
        for f in out["facts"]:
            own = dates.CHART_SPAN.search(f["quote"])
            f["date"] = own.group(0) if own and f["domain"] not in ("birth_date", "sex") else ""
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


def _ruleset_5y() -> Ruleset:
    """The site ruleset with "malignancy in the last 5 years" as its exclusion."""
    orig = ts._crit

    def windowed(cid: str, kind: str, text: str, logic: dict[str, Any]) -> Any:
        if cid == "SITE5B-EXC-01":
            logic = {**logic, "window": {"anchor": "index", "from_days": -1825, "to_days": 0}}
        return orig(cid, kind, text, logic)

    ts._crit = windowed
    try:
        return site_ruleset()
    finally:
        ts._crit = orig


def _confirm_all(svc: SiteSetup, chart5: str | None, rs: Ruleset) -> dict[str, str]:
    """Stage 12's path at the service level: both charts (10000005's replaced by ``chart5``), the dump mapped, every
    chart fact confirmed; the patient states."""
    inp = help.practice_inputs()
    for no, text in inp["charts"]:
        body = chart5 if (chart5 is not None and no == "10000005") else text
        svc.add_chart(WS, no, "pasted.txt", body.encode(), "crc", "ja", pasted=True)
    svc.add_sheet(WS, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    for c in svc.store.locals(WS):
        target = {"system": c["suggested_system"], "code": c["suggested_code"]}
        if not c["suggested_code"] or c["code"] == "ZI10":
            target = {"system": mapping.ICD10CM, "code": "I10"}
        svc.map_code(WS, c["domain"], c["system"], c["code"], target, "crc")
    proposed = svc.store.facts(WS, "proposed")
    assert proposed
    for f in proposed:
        svc.decide(int(f["id"]), "confirm", "crc")
    return {p["pid"]: p["state"] for p in readiness.patient_check(svc, WS, rs, TODAY)}


def test_an_undated_confirmed_malignancy_leaves_the_patient_needing_information(literal: SiteSetup) -> None:
    """The practice chart's "乳癌（2019年手術）" has no full date of its own: confirmed, it stays undated and the
    exclusion stays unknown (DUMP-01). Never a silent "no", never a date the chart does not write."""
    st = _confirm_all(literal, None, site_ruleset())
    mal = [f for f in literal.store.facts(WS) if f["pid"] == pid("10000005") and f["code"].startswith("C")]
    assert mal and all(f["status"] == "confirmed" and f["day"] == "" for f in mal)
    assert st[pid("10000005")] == "needs"


HARM = {
    # a 2010 cancer under a 2026 heading: dated by the heading it would exclude from a 5-year window
    "history_2010": "門診紀錄 2026年9月25日\n主訴：痛風追蹤。\n過去病史：乳癌（2010年手術）\n檢驗：尿酸 8.1 mg/dL\n",
    # a birth date without a label above the cancer: dated by it the cancer falls outside the window, a silent "no"
    "unlabelled_dob": "患者 1961/04/03 (65)\n門診紀錄\n主訴：痛風追蹤。\n過去病史：乳癌\n檢驗：尿酸 8.1 mg/dL\n",
}


@pytest.mark.parametrize("name", sorted(HARM))
def test_no_date_is_taken_from_the_chart_around_a_fact(literal: SiteSetup, name: str) -> None:
    """The adversarial review's two cases (B1, H1): with a 5-year malignancy window, a date taken from the chart
    around the fact turned "needs" into "not_eligible" or "ready". The confirmed cancer stays undated: "needs"."""
    st = _confirm_all(literal, HARM[name], _ruleset_5y())
    mal = [f for f in literal.store.facts(WS) if f["pid"] == pid("10000005") and f["code"].startswith("C")]
    assert mal and all(f["day"] == "" for f in mal)
    assert st[pid("10000005")] == "needs"


def test_stage12_evidence_tells_an_undated_fact_from_a_dropped_one() -> None:
    """The evidence of the stage-12 check: per chart patient, the kinds read with their days, the kinds missing and the
    kinds undated, from structured fields only."""
    p4, p5 = pid("10000004"), pid("10000005")
    facts = [
        {"pid": p4, "domain": "condition", "code": "M10.9", "day": ""},
        {"pid": p4, "domain": "observation", "code": "3084-1", "day": "2026-09-18"},
        {"pid": p4, "domain": "condition", "code": "", "day": ""},
        {"pid": p5, "domain": "condition", "code": "C50.919", "day": ""},
        {"pid": p5, "domain": "condition", "code": "M10.9", "day": "2026-09-25"},
        {"pid": p5, "domain": "observation", "code": "3084-1", "day": "2026-09-25"},
        {"pid": p5, "domain": "demographic", "code": "sex", "day": ""},
    ]
    ev = chart_fact_kinds(facts, {"10000004": p4, "10000005": p5})
    assert ev[p4[:8]] == {
        "read": {"gout": [""], "urate": ["2026-09-18"]},
        "missing": ["birth_date", "sex"],
        "undated": ["gout"],
        "other": {"condition_uncoded": 1},
    }
    assert ev[p5[:8]] == {
        "read": {"malignancy": [""], "gout": ["2026-09-25"], "urate": ["2026-09-25"]},
        "missing": [],
        "undated": ["malignancy"],
        "other": {"sex": 1},
    }
