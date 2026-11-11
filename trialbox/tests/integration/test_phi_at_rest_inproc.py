"""T-210c acceptance (CR-041 last third; T-210 acceptance 3 of TB-ASSESS-01, D-354): after a run on a sealed box no
`phi` output and no upload is plaintext on disk. The in-process box takes a chart upload by mail (CASE), writes the
eligibility sheet and its record (`phi`), and mails them; then every file of the object store is read raw."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from tb_common import objstore as O
from tb_common.audit import verify

from tests.inproc_box import Box, ingest_site, make_box
from tests.integration.test_case_inproc import CHART, KEY, _sheet
from tools import keys as keys_cli

RUN = date(2026, 10, 5)
MRN_IN_CHART = "病歷號 88123456"  # a synthetic chart number written in the uploaded chart


@pytest.fixture(scope="module")
def world(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("phi-at-rest")
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    with pytest.MonkeyPatch.context() as mp:
        for var in ("TB_KEK_PASSPHRASE", "CREDENTIALS_DIRECTORY", "TB_OBJECT_STORE"):
            mp.delenv(var, raising=False)
        mp.setenv("TB_KEK_FILE", str(tmp / "run" / "kek"))
        (tmp / "run").mkdir()
        kek_out = tmp / "usb" / "trialbox.kek"
        assert keys_cli.main(["init", "--secrets", str(sec), "--backend", "file", "--kek-out", str(kek_out)]) == 0
        assert keys_cli.main(["unseal", "--secrets", str(sec), "--from", str(kek_out)]) == 0
        ingest_site(synth_dir / "site-a", tmp / "lake", sec, "2026-10-04")
        (tmp / "box" / "obj").mkdir(parents=True)  # the objects volume of a fresh install
        assert keys_cli.main(["seal-objects", "--secrets", str(sec), "--store", str(tmp / "box" / "obj")]) == 0
        box = make_box(tmp / "box", tmp / "lake", sec, RUN)
        yield {"tmp": tmp, "box": box, "sec": sec}


def _run(box: Box, subject: str, chart: bytes) -> Any:
    assert box.mail(subject, (("chart.md", chart),)) == "Processed"
    job = max(box.orch.db.find(type_="CASE"), key=lambda j: (j.received_at, j.job_id))
    box.orch.drain()
    return box.orch.db.get(job.job_id)


def test_no_phi_output_or_upload_is_plaintext_on_disk_after_a_run(world: dict[str, Any]) -> None:
    box: Box = world["box"]
    chart = (CHART + f"\n{MRN_IN_CHART}\n").encode()
    job = _run(box, "CASE GZQO lang=zh-TW", chart)
    assert job is not None and job.state == "done", job and job.error
    assert {o.tag for o in job.outputs or []} == {"phi"}
    # the sheet still reaches the study team, and the record reads back through the store
    html, rec = _sheet(box, job.job_id)
    assert "適格性檢核表" in html and rec["counts"]["total"] == len(rec["criteria"])
    assert box.store.get(f"attachments/{job.job_id}/chart.md") == chart
    root = box.store.root
    sealed = [p for b in O.SEALED_BUCKETS if (root / b).is_dir() for p in (root / b).rglob("*") if p.is_file()]
    names = {p.relative_to(root).as_posix() for p in sealed}
    assert f"attachments/{job.job_id}/chart.md" in names and f"attachments/{job.job_id}/message.eml" in names
    assert {f"outputs/{job.job_id}/{o.filename}" for o in job.outputs or []} <= names
    assert not O.plain_objects(root), "a plaintext file in a sealed bucket"
    # the acceptance grep: no patient text anywhere in the object store, as bytes or as UTF-8
    needles = [s.encode() for s in ("急性痛風發作", "88123456", "allopurinol", "適格性檢核表")]
    for p in root.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            assert not any(n in data for n in needles), f"patient text in {p.relative_to(root)}"
    assert json.loads((root / O.SEAL_FILE).read_text())["buckets"] == list(O.SEALED_BUCKETS)
    assert verify(box.audit_dir).ok


def test_the_box_with_the_kek_locked_refuses_new_uploads(world: dict[str, Any], tmp_path: Path) -> None:
    box: Box = world["box"]
    locked = O.FsStore(box.store.root, world["sec"], {"TB_KEK_FILE": str(tmp_path / "absent")})
    with pytest.raises(O.K.KekLockedError):
        locked.put("attachments/JX/chart.md", b"chart")
    assert not (box.store.root / "attachments/JX").exists()
