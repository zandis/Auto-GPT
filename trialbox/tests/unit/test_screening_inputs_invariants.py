"""Drive the real SCREEN worker and check its published list as well as both lake pointers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from lake.client import LakeHttp, LakeLocal
from orchestrator import scheduler
from orchestrator.i18n import t
from tb_common.db import DatabaseError
from tb_common.flags import Flags
from tb_common.screening_inputs import REFUSAL
from tb_contracts import Job, JobCreate

from tests.inproc_box import Box, make_box
from tests.screening_site import accept_fixture


@pytest.fixture(scope="module")
def site(
    ingested: dict[str, Any], site_key_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Box, Path, Path]:
    work = tmp_path_factory.mktemp("admission")
    box = make_box(
        work,
        ingested["lake_dir"],
        site_key_dir,
        settings_update={"rate_limits_per_day": {"SCREEN": 40}},
        extra_env={"TB_DATA_DIR": str(work)},
    )
    record, clearance = accept_fixture(box, "GZQO")
    return box, record, clearance


@pytest.fixture
def evidence(site: tuple[Box, Path, Path]) -> Iterator[tuple[Box, Path, Path]]:
    box, record, clearance = site
    before = record.read_bytes(), clearance.read_bytes()
    yield box, record, clearance
    record.write_bytes(before[0])
    clearance.write_bytes(before[1])


def run(box: Box, lang: str = "en", **options: str) -> Job:
    job = box.orch.create(
        JobCreate(type="SCREEN", requested_by="crc1@hospa.test", ruleset="GZQO", options={"lang": lang, **options})
    )
    box.orch.drain()
    saved = box.orch.db.get(job.job_id)
    assert saved is not None
    return saved


def pointers(box: Box) -> tuple[str | None, str | None]:
    reader = box.orch.services.lake
    assert isinstance(reader, LakeLocal)
    return reader.snapshot(), reader.generation()


def test_complete_record_reaches_the_real_candidate_list(evidence: tuple[Box, Path, Path]) -> None:
    box, record, _ = evidence
    use = json.loads(record.read_bytes())["use"]
    before = pointers(box)
    job = run(box)
    assert job.state == "done", job.error
    assert job.options and job.options["lake_generation"] == before[1] == use["generation"]
    assert job.ruleset_version == use["rule_version"]
    candidate_list = next(o for o in job.outputs or [] if o.filename.startswith("candidate_list_"))
    assert json.loads(box.store.get(candidate_list.minio_key))["rows"]
    assert pointers(box) == before


@pytest.mark.parametrize(
    "fault",
    [
        "inventory",
        "owner_rule_stamp",
        "accepted_digest",
        "recipients",
        "scope",
        "held",
        "external_clearance",
        "audit",
        "silent_audit",
        "state_outage",
        "missing_flag",
        "unconfirmed_pin",
        "changed_scope",
        "forged_options",
    ],
)
def test_missing_evidence_never_lists_or_moves_the_pointer(
    evidence: tuple[Box, Path, Path], fault: str, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    box, record_path, external = evidence
    record = json.loads(record_path.read_bytes())
    extra: dict[str, str] = {}
    if fault == "inventory":
        record["inventory"]["lake"].pop()
    elif fault == "owner_rule_stamp":
        del record["rows"][0]["owner_rule_stamp"]
    elif fault == "accepted_digest":
        del record["accepted_digest"]
    elif fault == "recipients":
        del record["use"]["list_to"]
    elif fault == "scope":
        del record["use"]["scope"]
    elif fault == "held":
        record["rows"][1]["review_tag"] = "held"
    elif fault == "external_clearance":
        external.unlink()
    elif fault == "changed_scope":
        extra["scope"] = "hospital"
    elif fault == "forged_options":
        extra["screening_inputs"] = json.dumps(record)
        record_path.unlink()
    elif fault == "state_outage":

        def unavailable(*_: object) -> str:
            raise DatabaseError("synthetic outage")

        monkeypatch.setattr(scheduler, "study_state", unavailable)
    elif fault == "missing_flag":
        monkeypatch.setattr(Flags, "row", lambda *_: None)
    elif fault == "unconfirmed_pin":
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"generation": None}))
        http = LakeHttp("http://fixture")
        http.client.close()
        http.client = httpx.Client(transport=transport)
        request.addfinalizer(http.client.close)
        monkeypatch.setattr(box.orch.services.lake, "hold", http.hold)
    elif fault in ("audit", "silent_audit"):
        append = box.orch.audit.append

        def fail_admission_write(event: str, **fields: Any) -> dict[str, Any]:
            if event == "screen.inputs_admitted":
                if fault == "silent_audit":
                    return {}
                raise OSError
            return append(event, **fields)

        monkeypatch.setattr(box.orch.audit, "append", fail_admission_write)

    if record_path.exists() and external.exists():
        # Attest even to the changed bytes: each individual missing input must independently refuse.
        record_path.write_text(json.dumps(record))
        grant = json.loads(external.read_bytes())
        grant["accepted_records"] = [hashlib.sha256(record_path.read_bytes()).hexdigest()]
        external.write_text(json.dumps(grant))
    before = pointers(box)
    pool = box.orch.db.pool("GZQO")
    job = run(box, "ja", **extra)
    assert job.state == "failed" and job.error and job.error.detail == REFUSAL
    assert job.error.message == t("ja", REFUSAL)
    assert not job.outputs and not list(box.store.list(f"outputs/{job.job_id}/"))
    assert box.orch.db.pool("GZQO") == pool
    assert pointers(box) == before


def test_restored_database_release_needs_a_fresh_external_clearance(site: tuple[Box, Path, Path]) -> None:
    box, _, _ = site
    before = pointers(box)
    pool = box.orch.db.pool("GZQO")
    flags = Flags(url=box.orch.db.url, audit=box.orch.audit)
    flags.set(scheduler.RESTORE_FLAG, "held", "fixture-steward", "synthetic restore")
    flags.set(scheduler.RESTORE_FLAG, "released", "fixture-steward", "database released")
    try:
        job = run(box)
        assert job.error and job.error.detail == REFUSAL
        assert not job.outputs and box.orch.db.pool("GZQO") == pool
        assert pointers(box) == before
    finally:
        accept_fixture(box, "GZQO")


def attest(record: Path, clearance: Path, data: dict[str, Any]) -> None:
    record.write_text(json.dumps(data))
    grant = json.loads(clearance.read_bytes())
    grant["accepted_records"].append(hashlib.sha256(record.read_bytes()).hexdigest())
    clearance.write_text(json.dumps(grant))


def test_inventory_omitted_from_both_lists(evidence: tuple[Box, Path, Path]) -> None:
    box, path, clearance = evidence
    data = json.loads(path.read_bytes())
    data["inventory"] = {"lake": [], "derived": [], "omop": []}
    data["rows"] = []
    attest(path, clearance, data)
    job = run(box)
    assert job.error and job.error.detail == REFUSAL and not job.outputs


def test_missing_lifecycle_table(evidence: tuple[Box, Path, Path]) -> None:
    from console.sitestore import SiteStore

    box, _, _ = evidence
    site_store = SiteStore(box.orch.db.url)
    site_store.db.execute("ALTER TABLE study_state RENAME TO saved_lifecycle")
    try:
        job = run(box)
        assert job.error and job.error.detail == REFUSAL and not job.outputs
    finally:
        site_store.db.execute("ALTER TABLE saved_lifecycle RENAME TO study_state")
        site_store.close()


def test_stored_score_setting_unavailable(evidence: tuple[Box, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    box, path, clearance = evidence
    data = json.loads(path.read_bytes())
    data["use"]["stored_read"] = "on"
    attest(path, clearance, data)
    flags = Flags(url=box.orch.db.url, audit=box.orch.audit)
    flags.set("derived.stored_read", "on", "fixture-steward", "verify stored scores")
    read = Flags.row

    def row(flags: Flags, name: str) -> str | None:
        if name == "derived.stored_read":
            raise DatabaseError("unavailable")
        return read(flags, name)

    monkeypatch.setattr(Flags, "row", row)
    try:
        job = run(box)
        assert job.error and job.error.detail == REFUSAL and not job.outputs
    finally:
        flags.set("derived.stored_read", "off", "fixture-steward", "restore test setting")


def test_replay_requires_original_accepted_bytes(evidence: tuple[Box, Path, Path]) -> None:
    from orchestrator.rerun import rerun

    box, path, clearance = evidence
    job = run(box)
    assert job.state == "done", job.error
    data = json.loads(path.read_bytes())
    from orchestrator.studystore import StudyStore

    study = StudyStore(path.parent, box.orch.db.url)
    try:
        study.save_screen_scope("GZQO", "hospital", [], "coordinator", "2026-10-05")
        data["use"]["scope"]["practitioners"] = None
        attest(path, clearance, data)
        replay = rerun(box.orch, job.job_id)
        assert replay.error and t("en", REFUSAL) in replay.error
    finally:
        study._db.execute("DELETE FROM screen_scope WHERE ruleset = ?", ("GZQO",))
        study.close()


def test_cohort_routes_to_requester(evidence: tuple[Box, Path, Path]) -> None:
    box, _, _ = evidence
    path, clearance = accept_fixture(box, "RA-COH")
    data = json.loads(path.read_bytes())
    data["use"]["scope"]["practitioners"] = None
    data["use"]["list_to"] = ["pi@hospa.test"]
    data["use"]["aggregate_to"] = sorted({*data["use"]["aggregate_to"], "pi@hospa.test"})
    attest(path, clearance, data)
    job = box.orch.create(
        JobCreate(type="SCREEN", requested_by="pi@hospa.test", ruleset="RA-COH", options={"scope": "hospital"})
    )
    box.orch.drain()
    saved = box.orch.db.get(job.job_id)
    assert saved and saved.state == "done", saved.error if saved else None
    output = next(o for o in saved.outputs or [] if o.filename.startswith("candidate_list_"))
    assert output.recipients == ["pi@hospa.test"]


def test_restore_of_secrets_cannot_reinstate_a_revoked_grant(evidence: tuple[Box, Path, Path]) -> None:
    box, _, grant = evidence
    # Restore the release in the DB (identical to the current row) and every backed-up secret.
    secrets = Path(box.orch.cfg.env.secrets_dir)
    backup = {p: p.read_bytes() for p in secrets.rglob("*") if p.is_file()}
    grant.unlink()
    for path, body in backup.items():
        path.write_bytes(body)
    job = run(box)
    assert job.error and job.error.detail == REFUSAL and not job.outputs


@pytest.mark.parametrize("matching", [True, False], ids=["verified", "wrong-hash"])
def test_first_screen_of_restored_date_needs_matching_generation_hash(
    evidence: tuple[Box, Path, Path], matching: bool
) -> None:
    from lake.store import gen_dir

    box, _, _ = evidence
    client = box.orch.services.lake
    assert isinstance(client, LakeLocal)
    gen = client.generation()
    assert gen is not None
    folder = gen_dir(client.lake.dir)
    physical = folder / f"{gen}.duckdb"
    metadata = physical.with_suffix(".json")
    saved = physical.with_suffix(".saved")
    before = metadata.read_bytes()
    physical.rename(saved)
    try:
        if not matching:
            metadata.write_text(json.dumps({**json.loads(before), "sha256": "0" * 64}))
        assert client.generation() is None
        job = run(box)
        if matching:
            assert job.state == "done" and job.options and job.options["lake_generation"] == gen, job.error
        else:
            assert job.error and job.error.detail == REFUSAL and not job.outputs
            assert client.generation() is None
    finally:
        physical.unlink(missing_ok=True)
        saved.replace(physical)
        metadata.write_bytes(before)


def test_unavailable_optout_register_refuses_screen(evidence: tuple[Box, Path, Path]) -> None:
    from tb_common.optout import OptOutRegister

    box, _, _ = evidence
    good = run(box)
    candidate = next(o for o in good.outputs or [] if o.filename.startswith("candidate_list_"))
    pid = json.loads(box.store.get(candidate.minio_key))["rows"][0]["pid"]
    register = OptOutRegister(box.orch.db.url)
    register.add(pid, "patient", "declined", "coordinator", "2026-10-01T12:00:00Z")
    register.db.execute("ALTER TABLE optout_events RENAME TO saved_optout")
    try:
        job = run(box)
        assert job.error and job.error.detail == REFUSAL and not job.outputs
    finally:
        register.db.execute("ALTER TABLE saved_optout RENAME TO optout_events")
        register.close()


def test_finished_stored_batch_with_failed_patient_refuses(evidence: tuple[Box, Path, Path]) -> None:
    from datacore.generations import guarded
    from tb_common.derived_store import DerivedStore, Report

    box, path, external = evidence
    data = json.loads(path.read_bytes())
    data["use"]["stored_read"] = "on"
    attest(path, external, data)
    url = box.orch.db.url
    flags = Flags(url=url, audit=box.orch.audit)
    flags.set("derived.stored_read", "on", "coordinator", "read stored scores")
    st = DerivedStore(url)
    generation = data["use"]["generation"]

    def partial_batch() -> int:
        batch = st.begin_batch(generation.split(".")[0], "mapping-v1")
        st.finish_batch(batch, Report(failed=1, failed_pids=["patient-7"]), patients=1)
        return batch

    try:
        guarded("derived", generation, partial_batch, url, ref=str)
        job = run(box)
        assert job.error and job.error.detail == REFUSAL and not job.outputs
    finally:
        st.close()
        flags.set("derived.stored_read", "off", "coordinator", "restore setting")
