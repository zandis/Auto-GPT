"""SPEC §11.2 "same inputs + same versions → identical output hashes" (D-82): every read-only scenario re-executed
by ``orchestrator.rerun`` on the job's snapshot reproduces each output byte for byte; a changed output is detected;
jobs with side effects are never re-run."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from orchestrator.rerun import rerun
from tb_contracts import JobCreate, JobOutput

from tests.inproc_box import Box, ingest_site, make_box

KEY = b"trialbox-test-site-key-0123456789abcdef"


@pytest.fixture(scope="module")
def box(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Box:
    tmp = tmp_path_factory.mktemp("rerun")
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(synth_dir / "site-a", tmp / "lake", sec, "2026-10-04")
    b = make_box(tmp / "box", tmp / "lake", sec, date(2026, 10, 5))
    for subject, sender in (
        ("FEAS GZQO", "crc1@hospa.test"),
        ("SCREEN GZQO version=1.0.0", "crc1@hospa.test"),
        ("NAV ONC-OSI dept=ONC", "nurse-onc@hospa.test"),
        ("COHORT GOUT-COH lookback=2", "crc1@hospa.test"),
    ):
        assert b.mail(subject, sender=sender) == "Processed"
        b.orch.drain()
    b.orch.create(JobCreate(type="MICROBATCH", ruleset="GZQO", requested_by="scheduler"))
    b.orch.drain()
    return b


@pytest.mark.parametrize("jtype", ["FEAS", "SCREEN", "NAV", "COHORT", "MICROBATCH"])
def test_rerun_is_byte_identical(box: Box, jtype: str) -> None:
    job = box.orch.db.find(type_=jtype)[0]
    assert job.state == "done", job.error
    res = rerun(box.orch, job.job_id)
    assert res.error is None, res.error
    assert res.files and all(f["same"] for f in res.files), [f for f in res.files if not f["same"]]
    assert res.identical
    # the sandbox wrote nothing back: the original job and its outputs are untouched
    again = box.orch.db.get(job.job_id)
    assert again is not None and [o.sha256 for o in again.outputs or []] == [o.sha256 for o in job.outputs or []]


def test_changed_output_is_detected(box: Box) -> None:
    job = box.orch.db.find(type_="FEAS")[0]
    outs: list[Any] = list(job.outputs or [])
    tampered = [*outs[:-1], JobOutput.model_validate({**outs[-1].model_dump(), "sha256": "0" * 64})]
    box.orch.db.put(job.model_copy(update={"outputs": tampered}))
    try:
        res = rerun(box.orch, job.job_id)
        assert not res.identical and [f["filename"] for f in res.files if not f["same"]] == [outs[-1].filename]
    finally:
        box.orch.db.put(job)


def test_side_effect_jobs_are_not_rerun(box: Box) -> None:
    nav = box.orch.db.find(type_="NAV")[0]
    out = next(o for o in nav.outputs or [] if o.filename.startswith("twpas_ONC-OSI_"))
    pid12 = out.filename.split("_")[-1].removesuffix(".json")
    pid = next(
        r["pid"]
        for r in box.orch.services.lake.query("SELECT pid FROM patient").to_pylist()
        if r["pid"].startswith(pid12)
    )
    box.mail(f"SUBMIT ONC-OSI pid={pid} bundle={nav.job_id}", sender="onc-dr@hospa.test")
    box.orch.drain()
    sub = box.orch.db.find(type_="SUBMIT")[0]
    assert sub.state == "done", sub.error
    res = rerun(box.orch, sub.job_id)
    assert not res.identical and res.error and "side effects" in res.error
    assert rerun(box.orch, "NO-SUCH-JOB").error == "no such job"
