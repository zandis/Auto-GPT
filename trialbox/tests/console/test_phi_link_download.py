"""T-212a (D-369, PV-18): link mode can deliver patient files. The mail of link mode says "sign in to download"; the
console then gives a job's patient-level file to the people the job named as its recipients, and to nobody else."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from console.backend import read_audit
from fastapi.testclient import TestClient
from tb_common.crypto import sha256_bytes
from tb_common.flowledger import exports
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    _ulid,
    box,
    login,
)

PW = "phi-link-password-0001"
LIST = "candidates_GZQO_v1.0.0.xlsx"


def _user(b: dict[str, Any], name: str, role: str, mailbox: str | None) -> TestClient:
    b["users"].create(name, role, PW, mailbox)
    c, _ = login(b["app"], name, PW)
    return c


def _screen_job(b: dict[str, Any]) -> Job:
    jid = _ulid(777)
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    data = b"PK synthetic candidate list"
    key = f"outputs/{jid}/{LIST}"
    b["backend"].objects[key] = data
    out = JobOutput(filename=LIST, sha256=sha256_bytes(data), minio_key=key, recipients=["crc-a@hospa.test"], tag="phi")
    job = Job(
        job_id=jid,
        type="SCREEN",
        ruleset="GZQO",
        ruleset_version="1.0.0",
        requested_by="crc-a@hospa.test",
        received_at=now,
        updated_at=now,
        state="done",
        options={},
        inputs=[],
        outputs=[out],
    )
    b["backend"].add_job(job)
    return job


def test_a_named_recipient_downloads_the_patient_file_after_sign_in(box: dict[str, Any]) -> None:  # noqa: F811
    job = _screen_job(box)
    c = _user(box, "crca", "coordinator", "CRC-A@hospa.test")  # the mailbox matches whatever its case
    page = c.get(f"/pilot/jobs/{job.job_id}").text
    assert 'data-testid="phi-download"' in page
    r = c.get(f"/pilot/jobs/{job.job_id}/files/{LIST}")
    assert r.status_code == 200 and r.content == b"PK synthetic candidate list"
    assert "attachment" in r.headers["content-disposition"]
    rows = read_audit(box["dir"] / "audit")
    dl = [x for x in rows if x.event == "console.download"]
    assert dl and dl[-1].actor == "console:crca" and dl[-1].detail["tag"] == "phi"
    flow = exports(box["dir"] / "audit")
    assert flow[-1].identifier_level == "identified" and flow[-1].recipients == ["crc-a@hospa.test"]


def test_nobody_else_gets_the_patient_file(box: dict[str, Any]) -> None:  # noqa: F811
    job = _screen_job(box)
    url = f"/pilot/jobs/{job.job_id}/files/{LIST}"
    others = [
        _user(box, "crcb", "coordinator", "crc-b@hospa.test"),  # a coordinator the job did not name
        _user(box, "viewer2", "viewer", "crc-a@hospa.test"),  # the right mailbox, a role that reads no patient data
        _user(box, "nobox", "coordinator", None),  # no mailbox: nothing to match
        login(box["app"])[0],  # the administrator (D-280: never patient data without break-glass)
    ]
    for c in others:  # 404 (not found for this account) or 403 (the viewer's role refusal, D-146)
        assert c.get(url).status_code in (403, 404)
        assert 'data-testid="phi-download"' not in c.get(f"/pilot/jobs/{job.job_id}").text
    box["users"].create("crcc", "coordinator", PW, "crc-a@hospa.test")
    box["users"].set_scope("crcc", studies="RA-BIO")  # named, but not on this study
    c, _ = login(box["app"], "crcc", PW)
    assert c.get(url).status_code in (403, 404)
