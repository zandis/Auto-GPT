"""NEW-EDC-5c (D-801, the follow-up of D-695 and D-686): a value changed in REDCap after TrialBox sent it is marked on
the copy-assist sheet and the monitor's SDV sheet.

D-686 showed REDCap's value on the review page. The copy-assist sheet (a person copies the value by hand) and the SDV
sheet (a monitor verifies it against its source) went on showing TrialBox's value alone, so a monitor could verify a
number that is no longer the EDC's. Both now carry what REDCap holds while the change is open. Synthetic data only."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from console.sdv_page import cited_items
from edc import copyassist

from tests import edc_kit as k
from tests.unit.test_edc_t302b import SCREEN1, _edit_in_redcap, _enter, _service


def _values(sheet: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(v["item"]): v for r in sheet["records"] for vis in r["visits"] for f in vis["forms"]  # type: ignore[attr-defined]
            for v in f["values"]}  # fmt: skip


def test_the_copy_assist_sheet_carries_what_redcap_holds(tmp_path: Path) -> None:
    svc, sim, _token, pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    svc.send_redcap(k.STUDY, "crc")
    _edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": SCREEN1, "weight": "70.1"})
    svc.reconcile(k.STUDY, "crc")
    got = _values(copyassist.sheet(svc, k.STUDY, "S-001", "crc"))
    assert got["weight"]["redcap_now"] == "70.1" and got["urate"]["redcap_now"] is None


def test_the_sdv_sheet_carries_what_redcap_holds() -> None:
    drafts: list[Mapping[str, Any]] = [{"id": 1, "item": "weight", "visit": SCREEN1, "fate": "confirmed", "final": "72.5", "citation": None,
               "final_citation": None, "redcap_now": "70.1"},
              {"id": 2, "item": "urate", "visit": SCREEN1, "fate": "confirmed", "final": "8.4", "citation": None,
               "final_citation": None, "redcap_now": None}]  # fmt: skip
    items = {d["item"]: d for d in cited_items(drafts)}
    assert items["weight"]["redcap_now"] == "70.1" and items["urate"]["redcap_now"] is None


def test_both_sheets_show_it_in_three_languages() -> None:
    from console.i18n_copyassist import EN as CEN
    from console.i18n_copyassist import JA as CJA
    from console.i18n_copyassist import ZH as CZH
    from console.i18n_roles import EN, JA, ZH

    root = Path(__file__).resolve().parents[2] / "services/console/templates"
    assert "redcap_now" in (root / "sdv_subject.html").read_text("utf-8")
    assert "redcap_now" in (root / "edc_copy.html").read_text("utf-8")
    for cat in (EN, JA, ZH):
        assert "sdv.redcap_now" in cat
    for cat in (CEN, CJA, CZH):
        assert "copy.redcap_now" in cat
