"""REDCap write-back (D-123, TB-PLAN-03 step 8): TrialBox imports its own instrument, never a REDCap-owned field.

Checked on the simulator's two fixture projects: the import method (unknown fields, events, auto-numbering, blanks
never erase), the plan (existing / create modes, unchanged rows skipped, duplicates never written), the link checks
(the instrument may not hold a field the link reads) and the whole read-then-write run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rc_bridge import writeback
from rc_bridge.client import RcError, RedcapClient
from rc_bridge.link import LinkError, ProjectLink, validate
from rc_sim.app import create_app, load_projects
from tb_contracts import RegistryUpdate

from tests.rc_kit import LINK_A, LINK_B, PIDS, TOKEN_A, TOKEN_B, sim_edit, study_service

WRITE_A: dict[str, Any] = {**LINK_A, "write_mode": "existing"}


def client(sim: Any, token: str) -> RedcapClient:
    rc = RedcapClient("https://rc.example/", token, http=TestClient(sim, base_url="http://rc"))
    rc.url = "/api/"
    return rc


def export(sim: Any, token: str) -> dict[str, dict[str, str]]:
    rows = client(sim, token).records()
    return {r[next(iter(r))] + "|" + r.get("redcap_event_name", ""): r for r in rows}


def test_sim_import_rules() -> None:
    sim = create_app()
    rc = client(sim, TOKEN_A)
    assert rc.import_records([{"record_id": "1", "tb_status": "3"}]) == ["1"]
    rec = export(sim, TOKEN_A)["1|"]
    assert rec["tb_status"] == "3" and rec["consent_date"] == "2026-10-20"  # other fields untouched
    rc.import_records([{"record_id": "1", "tb_status": "", "tb_status_date": "2026-11-07"}])
    assert export(sim, TOKEN_A)["1|"]["tb_status"] == "3"  # overwriteBehavior=normal: a blank never erases
    with pytest.raises(RcError) as e:
        rc.import_records([{"record_id": "1", "nope": "x"}])
    assert e.value.code == "RC-UPSTREAM" and "nope" in e.value.message
    ids = rc.import_records([{"record_id": "tb-new-1", "tb_screening_no": "GZQO-0042"}], auto_number=True)
    assert ids == ["3"] and export(sim, TOKEN_A)["3|"]["tb_screening_no"] == "GZQO-0042"
    b = client(sim, TOKEN_B)
    with pytest.raises(RcError):  # longitudinal: the event is required
        b.import_records([{"rec_id": "1", "tb_status": "1"}])
    with pytest.raises(RcError):  # a field on a form not designated for the event
        b.import_records([{"rec_id": "1", "redcap_event_name": "m12_arm_1", "tb_status": "1"}])
    assert b.import_records([{"rec_id": "1", "redcap_event_name": "screening_arm_1", "tb_status": "2"}]) == ["1"]


def test_plan_modes_unchanged_and_duplicates() -> None:
    link = ProjectLink.from_dict({**WRITE_A, "ruleset": "GZQO"})
    entries = [writeback.Entry("GZQO-0901", "2026-10-01", "enrolled", "2026-10-21"),
               writeback.Entry("GZQO-0042", "2026-11-01", "candidate", "2026-11-01"),
               writeback.Entry("GZQO-0777", "2026-11-01", "contacted", "2026-11-02")]  # fmt: skip
    existing = {"GZQO-0901": ["1"], "GZQO-0777": ["5", "6"]}
    wp = writeback.plan(link, entries, existing, {}, "record_id")
    assert wp.updates == [{"record_id": "1", "tb_screen_date": "2026-10-01", "tb_status": "4",
                           "tb_status_date": "2026-10-21"}]  # fmt: skip
    assert wp.creates == [] and wp.waiting == ["GZQO-0042"] and wp.skipped_dup == ["GZQO-0777"]
    again = writeback.plan(link, entries, existing, {"GZQO-0901": wp.hashes["GZQO-0901"]}, "record_id")
    assert again.updates == [] and again.unchanged == 1
    link.write_mode = "create"
    wc = writeback.plan(link, entries, existing, {}, "record_id")
    assert wc.creates == [{"record_id": "tb-new-1", "tb_screening_no": "GZQO-0042", "tb_screen_date": "2026-11-01",
                           "tb_status": "1", "tb_status_date": "2026-11-01"}]  # fmt: skip
    for row in wc.updates + wc.creates:  # only TrialBox's fields (and the link field on a new record)
        assert set(row) - {"record_id"} <= {*writeback.values(entries[0]), "tb_screening_no"}


def test_link_refuses_a_write_form_that_holds_read_fields() -> None:
    proj = load_projects()[TOKEN_A]
    meta = json.loads(json.dumps(proj["metadata"]))
    validate(ProjectLink.from_dict({**WRITE_A, "ruleset": "GZQO"}), meta, proj["project"])
    for m in meta:
        if m["field_name"] == "consent_date":
            m["form_name"] = "trialbox_screening"
    with pytest.raises(LinkError) as e:
        validate(ProjectLink.from_dict({**WRITE_A, "ruleset": "GZQO"}), meta, proj["project"])
    assert e.value.code == "RC-LINK-WRITE" and e.value.fields == ["consent_date"]
    with pytest.raises(LinkError) as e:
        validate(ProjectLink.from_dict({**WRITE_A, "ruleset": "GZQO", "write_form": "other_form"}),
                 proj["metadata"], proj["project"])  # fmt: skip
    assert e.value.code == "RC-LINK-FIELD"
    pb = load_projects()[TOKEN_B]
    with pytest.raises(LinkError) as e:  # longitudinal: the event of the instrument is required
        validate(ProjectLink.from_dict({**LINK_B, "ruleset": "RB", "write_mode": "existing"}), pb["metadata"],
                 pb["project"])  # fmt: skip
    assert e.value.fields == ["write_event"]
    with pytest.raises(LinkError):
        ProjectLink.from_dict({**WRITE_A, "ruleset": "GZQO", "write_mode": "always"}).check_shape()


def test_read_then_write_never_touches_redcap_fields(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, _clock):
        before = export(sim, TOKEN_A)
        svc.save_link("GZQO", WRITE_A, "crc")
        screening = {"GZQO-0901": PIDS["GZQO-0901"], "GZQO-0903": PIDS["GZQO-0903"]}
        issued = {"GZQO-0901": "2026-10-01T09:00:00+09:00", "GZQO-0903": "2026-11-01T09:00:00+09:00"}
        out = svc.read("GZQO", screening, "crc", issued=issued)
        w = out["write"]
        assert w["updated"] == 1 and w["created"] == 0 and w["waiting"] == ["GZQO-0903"]
        after = export(sim, TOKEN_A)
        rec = after["1|"]
        assert (rec["tb_screen_date"], rec["tb_status"]) == ("2026-10-01", "4")  # enrolled, read back just now
        for key, old in before.items():  # every REDCap-owned field is as it was
            for f, v in old.items():
                if not f.startswith("tb_") or f == "tb_screening_no":
                    assert after[key][f] == v, (key, f)
        assert svc.read("GZQO", screening, "crc", issued=issued)["write"]["updated"] == 0  # unchanged: none
        sim_edit(sim, 101, [{"record_id": "7", "tb_screening_no": "GZQO-0903"}])  # the CRC creates the record
        w2 = svc.read("GZQO", screening, "crc", issued=issued)["write"]
        assert w2["updated"] == 1 and w2["records"] == {"GZQO-0903": "7"}
        assert export(sim, TOKEN_A)["7|"]["tb_status"] == "1"


def test_create_mode_then_read_back(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, clock):
        svc.save_link("GZQO", {**WRITE_A, "write_mode": "create"}, "crc")
        pid = "ab" * 16
        svc.registry.update("GZQO", RegistryUpdate.model_validate({"pid": pid, "status": "contacted", "by": "crc"}),
                            clock())  # fmt: skip
        issued = {"GZQO-0042": "2026-11-06T10:00:00+09:00"}
        out = svc.read("GZQO", {"GZQO-0042": pid}, "crc", issued=issued)
        rid = out["write"]["records"]["GZQO-0042"]
        rec = export(sim, TOKEN_A)[f"{rid}|"]
        assert rec["tb_screening_no"] == "GZQO-0042" and rec["tb_status"] == "2"
        sim_edit(sim, 101, [{"record_id": rid, "consent_date": "2026-11-07"}])  # the CRC records consent
        nxt = svc.read("GZQO", {"GZQO-0042": pid}, "crc", full=True, issued=issued)
        assert [c["to"] for c in nxt["changes"]] == ["consented"]
        assert nxt["write"]["updated"] == 1  # TrialBox's status follows: consented
        assert export(sim, TOKEN_A)[f"{rid}|"]["tb_status"] == "3"
        last = svc.read("GZQO", {"GZQO-0042": pid}, "crc", issued=issued)["write"]
        assert last["created"] == 0 and last["unchanged"] == 1  # never a second record


def test_write_error_keeps_the_read(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, _clock):
        svc.save_link("GZQO", WRITE_A, "crc")
        sim.state.sim.projects[TOKEN_A]["metadata"] = [
            m for m in sim.state.sim.projects[TOKEN_A]["metadata"] if m["field_name"] != "tb_status_date"
        ]
        with pytest.raises(LinkError):  # the dictionary changed: the link check stops the run before any write
            svc.read("GZQO", {"GZQO-0901": PIDS["GZQO-0901"]}, "crc")
        assert svc.store.link("GZQO")["enabled"] is False


def test_plan_matches_screening_numbers_whatever_their_case_and_spaces() -> None:
    """A screening number typed in REDCap in lower case or with a space is the same number: one record is updated,
    two records that carry it are a duplicate and nothing is written. A record gone from REDCap since the last write
    is not "unchanged": it waits for its record again."""
    link = ProjectLink.from_dict({**WRITE_A, "ruleset": "GZQO"})
    rows = [{"record_id": "5", link.link_field: " gzqo-0777"}, {"record_id": "6", link.link_field: "GZQO-0777 "},
            {"record_id": "1", link.link_field: "gzqo-0901"}]  # fmt: skip
    existing = writeback.existing_index(rows, link, "record_id")
    assert existing == {"GZQO-0777": ["5", "6"], "GZQO-0901": ["1"]}
    entries = [writeback.Entry(" gzqo-0901 ", "2026-10-01", "enrolled", "2026-10-21"),
               writeback.Entry("GZQO-0777", "2026-11-01", "contacted", "2026-11-02")]  # fmt: skip
    wp = writeback.plan(link, entries, existing, {}, "record_id")
    assert [u["record_id"] for u in wp.updates] == ["1"] and wp.skipped_dup == ["GZQO-0777"] and not wp.creates
    gone = writeback.plan(link, entries[:1], {}, {"GZQO-0901": wp.hashes["GZQO-0901"]}, "record_id")
    assert gone.unchanged == 0 and gone.waiting == ["GZQO-0901"]
