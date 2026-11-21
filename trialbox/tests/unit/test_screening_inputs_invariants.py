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
    box = make_box(work, ingested["lake_dir"], site_key_dir, extra_env={"TB_DATA_DIR": str(work)})
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
