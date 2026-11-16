"""CGRD-B3 (D-841): the record's arm is read from all its rows, and dates go to REDCap as YYYY-MM-DD.

A real REDCap takes, with no error, a row for a record on an event of the other arm: the bridge's own check is the
only guard (the simulator accepts it too, as REDCap does). The send knew a record's arms from the rows it read, and it
reads only the fields it needs: a REDCap that leaves out an event row with nothing in those fields left the record
with no arm, and a value went to the other arm. The arms are now read from the record id alone, which every event
row of the record has. A real REDCap reads an import's date only as Y-M-D or M/D/Y whatever the field shows (a ROC
date ``115/11/01`` was read as day 115): TrialBox sends Y-M-D, and refuses any other form at decide time.
Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from datacore import forms
from rc_bridge.client import RedcapClient

from tests import edc_kit as k
from tests.unit.test_edc_t302b import SCREEN1, SCREEN2, _edit_in_redcap, _enter, _held, _rows, _service


def test_a_record_whose_rows_the_read_leaves_out_is_still_on_its_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = RedcapClient.records

    def sparse(self: RedcapClient, fields: list[str] | None = None, **kw: Any) -> Any:
        rows = real(self, fields=fields, **kw)
        # a REDCap that gives only the event rows holding one of the values asked (the screening-number lookup and
        # the record id alone are read whole)
        if fields and len(fields) > 1 and "tb_screening_no" not in fields:
            rows = [r for r in rows if any(str(r.get(f) or "") for f in fields[1:])]
        return rows

    monkeypatch.setattr(RedcapClient, "records", sparse)
    svc, sim, token, pid = _service(tmp_path)
    # record 3 is on arm 2 with its screening number only: no field the send reads is on that row
    _edit_in_redcap(sim, pid, {"record_id": "3", "redcap_event_name": SCREEN2, "tb_screening_no": "S-003"})
    _enter(svc, "S-003", SCREEN1, {}, confirm=frozenset({"weight"}))  # screening_arm_1 is arm 1
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "wrong_arm") == {(SCREEN1, "weight")} and out["count"] == 0
    assert ("3", SCREEN1, "", "") not in _rows(sim, token)


@pytest.mark.parametrize("validation", ["date_ymd", "date_dmy", "date_mdy"])
def test_a_date_goes_to_redcap_as_y_m_d_whatever_the_field_shows(validation: str) -> None:
    f = forms.field_of({"field_name": "d", "form_name": "f", "field_type": "text",
                        "text_validation_type_or_show_slider_number": validation})  # fmt: skip
    assert forms.redcap_value(f, "2026-11-01") == "2026-11-01"
    for other in ("115/11/01", "01-11-2026", "11/01/2026", "2026/11/01"):
        assert (forms.problem(f, other) or {}).get("code") == "date", other
