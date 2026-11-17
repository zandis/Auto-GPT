"""D-989 (lane C2's card): the excluded list names the model calls behind each exclusion.

The console's "this is wrong, send to review" is a person's decision on the answers that excluded a patient, written
as ``ai.confirmed`` with those answers' call ids. Excluded patients are on no candidate list, so the excluded list
itself carries each failing verdict's ``prov``: the calls of a note answer, an empty list for a coded one ("no model"
stated), and nothing on a verdict from before the field. Synthetic data only."""

from __future__ import annotations

from datetime import date

from orchestrator.scenarios.screen import ScreenRun, excluded_doc
from tb_contracts import CandidateRow, CriterionVerdict, Evidence

from tests.unit.test_lake_read_failed_is_said import CODED_EXC, GZQO, _ctx, _Lake

NOTE_EXC = next(c.id for c in GZQO.active() if c.kind == "exclusion" and c.id != CODED_EXC)


def test_each_failing_verdict_keeps_its_calls() -> None:
    note = CriterionVerdict(id=NOTE_EXC, verdict="fail", basis="pair", final=True, prov=["call-j", "call-v"],
                            evidence=Evidence(resource_refs=[], quote="history of breast cancer 2019", reason="note"))  # fmt: skip
    coded = CriterionVerdict(id=CODED_EXC, verdict="fail", basis="coded", prov=[],
                             evidence=Evidence(resource_refs=["C/f-1"]))  # fmt: skip
    old = CriterionVerdict(id=CODED_EXC, verdict="fail", basis="coded", evidence=Evidence(resource_refs=["C/f-2"]))
    rows = [CandidateRow(pid="P1", tier="excluded", actions=[], criteria=[note, coded]),
            CandidateRow(pid="P2", tier="excluded", actions=[], criteria=[old])]  # fmt: skip
    run = ScreenRun(GZQO, date(2026, 10, 5), "2026-10-05", [], {}, rows, [], [], 7, None)
    doc = excluded_doc(_ctx(_Lake({"site_fact": []})), run)
    got = {(r["pid"], c["id"]): c.get("prov") for r in doc["rows"] for c in r["criteria"]}
    assert got == {("P1", NOTE_EXC): ["call-j", "call-v"], ("P1", CODED_EXC): [], ("P2", CODED_EXC): None}
