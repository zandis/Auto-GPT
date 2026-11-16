"""EDC-023 (D-859): the TFDA guideline's §4.7 on the box's EDC prefill.

TFDA, 「電腦化系統與電子數據應用於藥品臨床試驗指引」 (May 2024), §4.7 「數據擷取」 (p. 18): the protocol or its
documents describe each transfer of electronic data (¶3), and the protocol names the data recorded directly in the
data collection tool as source data (¶2). So the REDCap send goes on only with the reference to the protocol's or
the data-management plan's section that describes TrialBox's data flow, and a field the protocol names as recorded
directly in the tool is never a prefill target: the map refuses it, the send holds a value back, the copy sheet
leaves it out."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc import copyassist
from edc.store import EdcError

from tests import edc_kit as k

ACK_NO_FLOW = {key: v for key, v in k.ACK.items() if key != "dataflow_ref"}


def _signed(svc: Any) -> None:
    for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc"):
        if r["state"] == "drafted":
            svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc))  # fmt: skip


@pytest.mark.parametrize("ref", ["", "   "])
def test_prefill_on_needs_the_data_flow_reference(tmp_path: Path, ref: str) -> None:
    svc, _, _ = k.service(tmp_path)
    with pytest.raises(EdcError) as e:
        svc.set_switch(k.STUDY, True, by="pi", role="investigator", **ACK_NO_FLOW, dataflow_ref=ref)
    assert e.value.code == "edc.dataflow_ref" and not svc.store.switch(k.STUDY).on
    assert svc.store.switch_events(k.STUDY) == []


def test_the_data_flow_reference_is_kept_with_the_switch_and_its_event(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    svc.set_switch(k.STUDY, True, by="pi", role="investigator", **k.ACK)
    sw = svc.store.switch(k.STUDY)
    assert sw.on and sw.dataflow_ref == k.ACK["dataflow_ref"] and sw.as_dict()["dataflow_ref"] == sw.dataflow_ref
    svc.set_switch(k.STUDY, False, by="admin", role="admin", reason="sponsor withdrew")
    assert svc.store.switch(k.STUDY).dataflow_ref == k.ACK["dataflow_ref"]  # off keeps it, as the acknowledgement
    assert [e["dataflow_ref"] for e in svc.store.switch_events(k.STUDY)] == [k.ACK["dataflow_ref"]] * 2


def test_copy_assist_needs_no_data_flow_reference(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    sw = svc.set_switch(k.STUDY, True, by="pi", role="investigator", reentry_pages=30, reentry_accuracy=0.985,
                        copy=True)  # fmt: skip
    assert sw["state"] == "copy" and sw["dataflow_ref"] == ""  # a person types the values: no electronic transfer


def test_a_direct_source_field_is_refused_as_a_map_target(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc, on=False)
    svc.set_direct_source(k.STUDY, ["weight", "tophus"], "Protocol v2.0 §8.1", "pi")
    with pytest.raises(EdcError) as e:
        svc.put_map(k.STUDY, k.MAP, k.TARGET, "crc")
    assert e.value.code == "edc.direct_source"
    assert sorted(p["item"] for p in e.value.problems) == ["tophus", "weight"]  # type: ignore[attr-defined]
    # an undrafted row of such a field is no prefill target and stays allowed
    rows = [m if m["item"] not in ("weight", "tophus") else {"item": m["item"]} for m in k.MAP]
    assert svc.put_map(k.STUDY, rows, k.TARGET, "crc")["drafted"] == 5


def test_a_field_named_direct_source_after_signing_is_held_back_and_left_off_the_copy_sheet(tmp_path: Path) -> None:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    _signed(svc)

    def waiting() -> list[int]:
        sheet = copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
        return [v["waiting"] for r in sheet["records"] for v in r["visits"]]

    before = waiting()
    listed = svc.set_direct_source(k.STUDY, ["weight"], "Protocol v2.1 §8.1", "pi")
    assert listed["fields"] == ["weight"] and listed["mapped"] == ["weight"]  # the map row the list now stops
    out = svc.send_redcap(k.STUDY, "crc")
    assert [d["item"] for d in out["direct_source"]] == ["weight"] and out["count"] == 5
    assert k.client_for(sim, token).records()[0]["weight"] == ""
    sheet = copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
    shown = [x["item"] for r in sheet["records"] for v in r["visits"] for f in v["forms"] for x in f["values"]]
    assert "weight" not in shown and "urate" in shown and sheet["direct_source"] == ["weight"]
    assert waiting() == before  # left out, not counted as waiting for a signature


def test_the_direct_source_list_is_kept_with_its_reference_and_audited(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    k.ready(svc, on=False)
    svc.set_direct_source(k.STUDY, ["tophus"], "Protocol v2.0 §8.1", "pi")
    svc.set_direct_source(k.STUDY, [], "Protocol v3.0 §8.1", "pi")  # the protocol's next version names none
    assert svc.store.direct_source(k.STUDY) == set()
    assert [(e["fields"], e["reference"]) for e in svc.store.direct_source_events(k.STUDY)] == [
        (["tophus"], "Protocol v2.0 §8.1"), ([], "Protocol v3.0 §8.1")]  # fmt: skip
    with pytest.raises(EdcError) as e:
        svc.set_direct_source(k.STUDY, ["tophus"], " ", "pi")
    assert e.value.code == "edc.direct_source_ref"
    with pytest.raises(EdcError) as e:
        svc.set_direct_source(k.STUDY, ["nope"], "Protocol v3.0 §8.1", "pi")
    assert e.value.code == "edc.direct_source_field"
