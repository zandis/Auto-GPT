"""ICD-04 conformance (TB-DS-08 §4.1a, FR-RC-10/14/15/16) on the REDCap simulator's two fixture projects.

Project A is classic (``consent_date`` / ``enrolled`` / ``sf_reason`` choice list); project B is longitudinal with
events and a DAG (``icf_dt`` / ``rand_yn`` / ``withdrawn``). Both are linked in the ``tb_screening_no`` mode (the
``mrn`` mode is a hospital-stage mode and is refused). Expected: statuses mapped correctly, a duplicate link value
raises RC-LINK-DUP and changes nothing, a renamed field raises RC-LINK-FIELD and disables the link.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rc_bridge.client import RcError, RedcapClient, check_token, major_of
from rc_bridge.link import LinkError, ProjectLink, choices, validate
from rc_sim.app import create_app
from tb_contracts import RegistryUpdate

from tests.rc_kit import LINK_A, LINK_B, PIDS, TOKEN_A, TOKEN_B, TZ, sim_edit, study_service

SCREENING = {n: p for n, p in PIDS.items()}


def statuses(svc: object, rs: str) -> dict[str, tuple[str, str | None]]:
    return {e.pid: (e.status, e.reason) for e in svc.registry.rows(rs)}  # type: ignore[attr-defined]


def test_client_reads_all_five_methods() -> None:
    http = TestClient(create_app(), base_url="http://rc")
    rc = RedcapClient("https://rc.example/", TOKEN_B, http=http)
    rc.url = "/api/"
    assert rc.check_version() == "16.0.10"
    assert rc.project()["is_longitudinal"] == 1
    assert len(rc.metadata()) == 5
    assert [d["unique_group_name"] for d in rc.dags()] == ["cgmh_linkou", "jp_head"]
    rows = rc.records(fields=["tb_screening_no"], events=["screening_arm_1"], dags=True)
    assert {r["redcap_data_access_group"] for r in rows} == {"cgmh_linkou", "jp_head"}


def test_error_register_mapping() -> None:
    def client(app: object, token: str = TOKEN_A) -> RedcapClient:
        rc = RedcapClient("https://rc.example", token, http=TestClient(app, base_url="http://rc"))  # type: ignore[arg-type]
        rc.url = "/api/"
        return rc

    with pytest.raises(RcError) as e:
        client(create_app(), "F" * 32).project()
    assert (e.value.code, e.value.status) == ("RC-TOKEN", 409)
    with pytest.raises(RcError) as e:
        client(create_app(version="12.4.1")).check_version()
    assert e.value.code == "RC-VERSION"
    limited = client(create_app(rate_limit=1))
    limited.version()
    with pytest.raises(RcError) as e:
        limited.version()
    assert (e.value.code, e.value.status) == ("RC-RATE", 503)
    with pytest.raises(RcError) as e:
        client(create_app())._post("file")
    assert (e.value.code, e.value.status) == ("RC-UPSTREAM", 502)
    with pytest.raises(RcError):
        check_token("not-a-token")
    with pytest.raises(RcError):
        RedcapClient("ftp://rc.example", TOKEN_A)
    assert major_of("16.0.10") == 16


def test_project_a_classic_statuses(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, _sim, _clock):
        svc.save_link("GZQO", LINK_A, "crc")
        out = svc.read("GZQO", SCREENING, "crc")
        st = statuses(svc, "GZQO")
        assert st[PIDS["GZQO-0901"]][0] == "enrolled"  # consent date + enrolled=1, recorded via consented
        assert st[PIDS["GZQO-0902"]] == ("screen_fail", "REDCap record 2 (REDCap: exclusion)")  # choice map
        assert {(c["record_id"], c["to"]) for c in out["changes"]} == {("1", "enrolled"), ("2", "screen_fail")}
        steps = sorted(e.status for e in svc.registry.events("GZQO", PIDS["GZQO-0901"]))
        assert steps == ["consented", "enrolled"]
        assert all(e.by == "rc-bridge" for e in svc.registry.events("GZQO"))
        assert {e.source for e in svc.registry.rows("GZQO")} == {"import"}
        recs = {r["record_id"]: r for r in svc.store.records("GZQO")}
        assert recs["1"]["subject_no"] == "S-0001" and recs["1"]["consent_date"] == "2026-10-20"
        assert out["duplicates"] == [] and out["conflicts"] == [] and out["unmatched"] == []
        again = svc.read("GZQO", SCREENING, "crc")  # idempotent: nothing new to record
        assert again["changes"] == [] and again["since"] is not None


def test_project_b_longitudinal_with_dag(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, _sim, _clock):
        svc.save_link("RABIO", LINK_B, "crc")
        out = svc.read("RABIO", SCREENING, "crc")
        st = statuses(svc, "RABIO")
        assert st[PIDS["RB0901"]] == ("withdrawn", "REDCap record 7 (REDCap: withdrawn)")  # withdrawn at month 12
        assert PIDS["RB0902"] not in st  # record 8 is in another DAG
        assert out["outside_dag"] == 1
        rec = svc.store.records("RABIO")[0]
        assert (rec["record_id"], rec["consent_date"]) == ("7", "2026-10-02")


def test_consent_event_is_respected(tmp_path: Path) -> None:
    link = {**LINK_B, "dag": ""}
    with study_service(tmp_path) as (svc, sim, _clock):
        sim_edit(sim, 202, [{"rec_id": "9", "redcap_event_name": "m12_arm_1", "tb_screening_no": "RB0903",
                             "icf_dt": "2026-11-01"}])  # fmt: skip
        svc.save_link("RABIO", link, "crc")
        svc.read("RABIO", {**SCREENING, "RB0903": "ab" * 16}, "crc")
        st = statuses(svc, "RABIO")
        assert "ab" * 16 not in st  # a consent date on the wrong event is not a consent
        assert st[PIDS["RB0902"]][0] == "consented"  # rand_yn=0: consented, not enrolled


def test_duplicate_link_value_raises_rc_link_dup(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, _clock):
        sim_edit(sim, 101, [{"record_id": "3", "tb_screening_no": "GZQO-0901", "consent_date": "2026-11-01"}])
        svc.save_link("GZQO", LINK_A, "crc")
        out = svc.read("GZQO", SCREENING, "crc")
        assert out["duplicates"] == [{"code": "RC-LINK-DUP", "link_value": "GZQO-0901", "record_ids": ["1", "3"]}]
        assert PIDS["GZQO-0901"] not in statuses(svc, "GZQO")  # never resolved automatically


def test_duplicate_across_reads(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, clock):
        svc.save_link("GZQO", LINK_A, "crc")
        svc.read("GZQO", SCREENING, "crc")
        clock.at = datetime(2026, 11, 8, 21, 0, tzinfo=TZ)
        sim_edit(sim, 101, [{"record_id": "4", "tb_screening_no": "GZQO-0902"}], at="2026-11-08T10:00:00")
        out = svc.read("GZQO", SCREENING, "crc")
        assert out["since"] == "2026-11-06 21:00:00"  # the watermark minus one day
        assert out["duplicates"] == [{"code": "RC-LINK-DUP", "link_value": "GZQO-0902", "record_ids": ["2", "4"]}]


def test_renamed_field_raises_rc_link_field(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, _clock):
        svc.save_link("GZQO", LINK_A, "crc")
        TestClient(sim).post("/sim/metadata/rename", json={"project_id": 101, "old": "consent_date", "new": "icf_date"})
        with pytest.raises(LinkError) as e:
            svc.read("GZQO", SCREENING, "crc")
        assert e.value.code == "RC-LINK-FIELD" and e.value.fields == ["consent_date"]
        row = svc.store.link("GZQO")
        assert row["enabled"] is False and "RC-LINK-FIELD" in row["problem"]
        assert svc.store.last_reads("GZQO")[0]["ok"] is False
        with pytest.raises(LinkError):
            svc.save_link("GZQO", LINK_A, "crc")  # the link cannot be saved against the renamed dictionary
        svc.save_link("GZQO", {**LINK_A, "consent_field": "icf_date"}, "crc")
        assert svc.store.link("GZQO")["enabled"] is True


def test_link_shape_and_choice_checks() -> None:
    meta = TestClient(create_app()).post("/api/", data={"token": TOKEN_A, "content": "metadata"}).json()
    validate(ProjectLink.from_dict({**LINK_A, "ruleset": "GZQO"}), meta)
    assert choices(next(m for m in meta if m["field_name"] == "sf_reason"))["9"] == "Other"
    bad: list[tuple[dict[str, Any], str]] = [
        ({"link_mode": "mrn"}, "RC-LINK-MODE"),
        ({"screenfail_choice_map": {"7": "exclusion"}}, "RC-LINK-FIELD"),
        ({"screenfail_choice_map": {"1": "bad-category"}}, "RC-LINK-FIELD"),
        ({"enrol_value": "5"}, "RC-LINK-FIELD"),
        ({"enrol_field": ""}, "RC-LINK-FIELD"),
        ({"project_id": 0}, "RC-LINK-FIELD"),
    ]
    for change, code in bad:
        with pytest.raises(LinkError) as e:
            validate(ProjectLink.from_dict({**LINK_A, **change, "ruleset": "GZQO"}), meta)
        assert e.value.code == code, change
    with pytest.raises(LinkError) as e:
        validate(ProjectLink.from_dict({**LINK_A, "ruleset": "GZQO"}), meta, {"project_id": 202})
    assert "project 202" in e.value.message


def test_conflict_is_listed_not_forced(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, _sim, clock):
        pid = PIDS["GZQO-0901"]
        svc.registry.update("GZQO", RegistryUpdate(pid=pid, status="declined", by="crc"), clock())
        svc.save_link("GZQO", LINK_A, "crc")
        out = svc.read("GZQO", SCREENING, "crc")
        assert out["conflicts"] == [
            {"link_value": "GZQO-0901", "record_id": "1", "pid": pid, "trialbox": "declined", "redcap": "enrolled"}
        ]
        assert statuses(svc, "GZQO")[pid][0] == "declined"


def test_unmatched_records_are_listed(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, _sim, _clock):
        svc.save_link("GZQO", LINK_A, "crc")
        out = svc.read("GZQO", {"GZQO-0901": PIDS["GZQO-0901"]}, "crc")
        assert out["unmatched"] == [{"record_id": "2", "link_value": "GZQO-0902"}]


def test_token_stays_in_the_secret_store(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, _sim, _clock):
        p = svc.store.token_path("proj-a")
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
        conn = svc.store.connection("proj-a")
        assert TOKEN_A not in str(conn) and conn["token_hint"] == "••••8F90"
        assert svc.test_connection("proj-a")["project_id"] == 101
        svc.save_link("GZQO", LINK_A, "crc")
        svc.read("GZQO", SCREENING, "crc")
        dump = "\n".join(sqlite3.connect(svc.store.path).iterdump())
        assert TOKEN_A not in dump and TOKEN_B not in dump
        audit = "".join(f.read_text() for f in (tmp_path / "audit").glob("*.jsonl"))
        assert TOKEN_A not in audit and "redcap.read" in audit
