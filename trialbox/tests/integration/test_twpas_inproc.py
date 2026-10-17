"""Phase 6 in process (CPU CI): ``NAV ONC-OSI dept=ONC`` builds a TWPAS bundle per listed patient (identity from the
in-box pid map), a validation report and the pre-check status; ``SUBMIT`` by a physician returns a dry-run
ClaimResponse, is audited, refuses non-physicians, refuses a live submission without HL7 validation / pre-check, and
POSTs exactly the audited bundle when live (SPEC §8.4, §9.5, §5)."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from adapter.validate.validator import Hl7Validator
from tb_common.crypto import pid_for_mrn

from tests.inproc_box import Box, Sent, ingest_site, make_box, unzip_phi

KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)


@pytest.fixture(scope="module")
def world(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("twpas")
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(synth_dir / "site-a", tmp / "lake", sec, "2026-10-04")
    box = make_box(tmp / "box", tmp / "lake", sec, RUN)
    pts = list(csv.DictReader((synth_dir / "site-a" / "patient.csv").open(encoding="utf-8")))
    states = json.loads((synth_dir / "site-a" / "states.json").read_text(encoding="utf-8"))
    return {
        "box": box,
        "patient": {pid_for_mrn(KEY, p["mrn"]): p for p in pts},
        "state": {pid_for_mrn(KEY, m): s for m, s in states.items()},
    }


def _nav(box: Box) -> tuple[c.Job, dict[str, bytes]]:
    assert box.mail("NAV ONC-OSI dept=ONC", sender="nurse-onc@hospa.test") == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="NAV", ruleset="ONC-OSI")[0]
    assert job.state == "done", job.error
    mail = next(s for s in reversed(box.sent) if s.subject.startswith("NAV ONC-OSI ONC"))
    assert sorted(mail.to) == ["nurse-onc@hospa.test", "onc-dr@hospa.test"]
    return job, unzip_phi(box, mail)


def _reply(box: Box, job_id: str) -> Sent:
    return next(s for s in reversed(box.sent) if job_id in s.subject and s.attachments())


def _live(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings.twpas.dry_run = false and an NHI endpoint, for this test only."""
    from dataclasses import replace

    from tb_common.config import Config

    cfg = box.orch.cfg
    assert cfg.settings.twpas is not None
    tw = cfg.settings.twpas.model_copy(update={"dry_run": False})
    live = Config(
        env=replace(cfg.env, nhi_twpas_base_url="https://nhi.invalid/twpas"),
        settings=cfg.settings.model_copy(update={"twpas": tw}),
    )
    monkeypatch.setattr(box.orch, "cfg", live)


def test_nav_onc_builds_bundles(world: dict[str, Any]) -> None:
    box: Box = world["box"]
    job, files = _nav(box)
    world["nav"] = job
    nav = c.NavLists.model_validate_json(
        next(v for k, v in files.items() if k.startswith("nav_lists") and k.endswith(".json"))
    )
    rows = nav.lists.likely_eligible + nav.lists.renewal_due
    assert rows, {k: len(v) for k, v in nav.lists.model_dump().items()}
    report = json.loads(files["twpas_validation_ONC-OSI.json"])
    assert report["ig"].startswith("tw.gov.mohw.nhi.pas#") and report["validator"] in ("hl7-validator", "structural")
    bundles = {k: json.loads(v) for k, v in files.items() if k.startswith("twpas_ONC-OSI_")}
    with_bundle = [r for r in rows if r.twpas_bundle_key]
    assert len(bundles) == len(with_bundle) >= 10, (len(bundles), len(rows))
    if Hl7Validator.from_env() is not None:  # phase 6 DoD: ≥10 synthetic bundles, 0 errors against the TWPAS IG
        assert report["validator"] == "hl7-validator"
        assert all(not b.get("validator_errors") for b in report["bundles"]), report["bundles"]
    for r in rows:
        assert r.precheck is not None
        st = world["state"][r.pid]
        if r.twpas_bundle_key is None:  # only missing gene evidence stops a bundle
            assert any("EGFR" in i or "gene" in i for i in r.precheck.issues), r.precheck
            continue
        assert st["egfr_mut"] == "pos"
        b = bundles[f"twpas_ONC-OSI_{r.pid[:12]}.json"]
        res = {e["resource"]["resourceType"] + ":" + e["resource"]["id"]: e["resource"] for e in b["entry"]}
        patient = next(v for k, v in res.items() if k.startswith("Patient:"))
        src = world["patient"][r.pid]
        ids = {i["value"] for i in patient["identifier"]}
        assert src["id_no"] in ids and src["mrn"] in ids  # identity from the in-box pid map, not the lake
        assert patient["name"][0]["text"] == src["name"]
        assert r.precheck.validator_errors == 0, r.precheck.issues
        claim = next(v for k, v in res.items() if k.startswith("Claim:"))
        assert claim["diagnosis"][0]["diagnosisCodeableConcept"]["coding"][0]["code"].startswith("C34")
        assert any(k.startswith("Observation:") for k in res)  # gene test result + ECOG
    lake_text = json.dumps(nav.model_dump(mode="json"), ensure_ascii=False)
    assert not any(world["patient"][r.pid]["id_no"] in lake_text for r in rows)  # national id only in bundles


def test_submit_dry_run(world: dict[str, Any]) -> None:
    box: Box = world["box"]
    nav: c.Job = world["nav"]
    out = next(o for o in nav.outputs or [] if o.filename.startswith("twpas_ONC-OSI_"))
    pid = next(p for p in world["patient"] if out.filename == f"twpas_ONC-OSI_{p[:12]}.json")
    # not a physician → refused at intake (permissions.SUBMIT = [physicians])
    box.mail(f"SUBMIT ONC-OSI pid={pid} bundle={nav.job_id}", sender="nurse-onc@hospa.test")
    assert not box.orch.db.find(type_="SUBMIT")
    assert box.mail(f"SUBMIT ONC-OSI pid={pid} bundle={nav.job_id}", sender="onc-dr@hospa.test") == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="SUBMIT")[0]
    assert job.state == "done", job.error
    mail = _reply(box, job.job_id)
    assert mail.to == ["onc-dr@hospa.test"]
    files = unzip_phi(box, mail)
    cr = json.loads(files[f"twpas_claimresponse_ONC-OSI_{pid[:12]}.json"])
    assert cr["resourceType"] == "ClaimResponse" and cr["outcome"] == "queued" and "DRY RUN" in cr["disposition"]
    bundle = box.store.get(out.minio_key)
    sha = hashlib.sha256(bundle).hexdigest()
    events = [
        json.loads(line)
        for p in sorted(box.audit_dir.glob("*.jsonl"))
        for line in p.read_text(encoding="utf-8").splitlines()
    ]
    sub = [e for e in events if e["event"] == "twpas.submit"]
    assert len(sub) == 1 and sub[0]["output_sha"] == sha and sub[0]["detail"]["dry_run"] is True
    assert sub[0]["detail"]["endpoint"] is None
    assert box.orch.db.submissions(sha)[0]["dry_run"] == 1


def test_submit_live_requires_validator_and_precheck(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    box: Box = world["box"]
    nav: c.Job = world["nav"]
    out = next(o for o in nav.outputs or [] if o.filename.startswith("twpas_ONC-OSI_"))
    pid = next(p for p in world["patient"] if out.filename == f"twpas_ONC-OSI_{p[:12]}.json")
    report = json.loads(box.store.get(f"outputs/{nav.job_id}/twpas_validation_ONC-OSI.json"))
    if report["validator"] == "hl7-validator" and box.orch.services.fhir is not None:
        pytest.skip("validator and pre-check both available: nothing to refuse")
    _live(box, monkeypatch)
    box.mail(f"SUBMIT ONC-OSI pid={pid} bundle={nav.job_id}", sender="onc-dr@hospa.test")
    box.orch.drain()
    job = box.orch.db.find(type_="SUBMIT")[0]
    assert job.state == "failed" and job.error is not None
    assert "Not submitted to NHI" in job.error.message and "pre-check did not run" in job.error.message


def test_submit_live_posts_audited_bundle(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A NAV run whose bundles passed the HL7 validator and the pre-check; the live POST carries exactly the stored
    bytes; a second SUBMIT of the same bundle is refused."""
    import httpx
    from orchestrator.precheck import PrecheckResult, PrecheckRunner
    from orchestrator.scenarios import twpas

    box: Box = world["box"]
    monkeypatch.setattr(twpas, "validate", lambda ctx, built: ("hl7-validator", {}))
    monkeypatch.setattr(PrecheckRunner, "run", lambda self, name, bundle: PrecheckResult(True, [], name))
    nav, _files = _nav(box)
    out = next(o for o in nav.outputs or [] if o.filename.startswith("twpas_ONC-OSI_"))
    pid = next(p for p in world["patient"] if out.filename == f"twpas_ONC-OSI_{p[:12]}.json")
    posted: list[tuple[str, bytes]] = []

    def fake_post(url: str, content: bytes, headers: dict[str, str], timeout: float) -> httpx.Response:
        posted.append((url, content))
        assert headers["Content-Type"] == "application/fhir+json"
        cr = {"resourceType": "ClaimResponse", "id": "nhi-1", "status": "active", "outcome": "complete"}
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "collection", "entry": [{"resource": cr}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    _live(box, monkeypatch)
    for attempt in (1, 2):
        box.mail(f"SUBMIT ONC-OSI pid={pid} bundle={nav.job_id}", sender="onc-dr@hospa.test")
        box.orch.drain()
        job = box.orch.db.find(type_="SUBMIT")[0]
        if attempt == 1:
            assert job.state == "done", job.error
            assert posted == [("https://nhi.invalid/twpas/Claim/$submit", box.store.get(out.minio_key))]
            cr = json.loads(box.store.get(f"outputs/{job.job_id}/twpas_claimresponse_ONC-OSI_{pid[:12]}.json"))
            assert cr["id"] == "nhi-1" and cr["outcome"] == "complete"
        else:
            assert job.state == "failed" and job.error is not None
            assert "already submitted" in job.error.message and len(posted) == 1


def _live_ready(box: Box, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """A NAV run whose bundles count as validated + pre-checked, in live mode: (pid, bundle sha) not yet live."""
    from orchestrator.precheck import PrecheckResult, PrecheckRunner
    from orchestrator.scenarios import twpas

    monkeypatch.setattr(twpas, "validate", lambda ctx, built: ("hl7-validator", {}))
    monkeypatch.setattr(PrecheckRunner, "run", lambda self, name, bundle: PrecheckResult(True, [], name))
    nav, _files = _nav(box)
    _live(box, monkeypatch)
    out = []
    for o in nav.outputs or []:
        if o.filename.startswith("twpas_ONC-OSI_") and not box.orch.db.submissions(o.sha256, live_only=True):
            pid = next(p for p in world["patient"] if o.filename == f"twpas_ONC-OSI_{p[:12]}.json")
            out.append((pid, o.sha256))
    world["nav_live"] = nav
    return out


def _submit_job(box: Box, nav: c.Job, pid: str) -> str:
    """Queue a SUBMIT by mail without running it; returns its job id."""
    before = {j.job_id for j in box.orch.db.find(type_="SUBMIT", limit=1000)}
    assert box.mail(f"SUBMIT ONC-OSI pid={pid} bundle={nav.job_id}", sender="onc-dr@hospa.test") == "Processed"
    (jid,) = {j.job_id for j in box.orch.db.find(type_="SUBMIT", limit=1000)} - before
    return jid


def test_live_submit_is_once_under_concurrency_and_restart(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two SUBMITs of one bundle racing on two workers POST once; a SUBMIT re-run after a restart that interrupted
    it mid-POST never POSTs again (SPEC §8.4: one NHI submission per audited bundle)."""
    import threading
    import time

    import httpx

    box: Box = world["box"]
    ready = _live_ready(box, world, monkeypatch)
    assert len(ready) >= 3
    nav = world["nav_live"]
    posted: list[bytes] = []

    def slow_post(url: str, content: bytes, headers: dict[str, str], timeout: float) -> httpx.Response:
        posted.append(content)
        time.sleep(0.3)  # widen the window between the duplicate check and the record
        cr = {"resourceType": "ClaimResponse", "id": "nhi-2", "status": "active", "outcome": "complete"}
        return httpx.Response(200, json=cr)

    monkeypatch.setattr(httpx, "post", slow_post)
    pid, sha = ready[0]
    jobs = [_submit_job(box, nav, pid), _submit_job(box, nav, pid)]
    threads = [threading.Thread(target=box.orch.run, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    states = sorted((box.orch.db.get(j) or pytest.fail(j)).state for j in jobs)
    assert states == ["done", "failed"] and len(posted) == 1
    (row,) = box.orch.db.submissions(sha, live_only=True)
    assert row["outcome"] == "complete"
    # restart recovery: the job had reserved the bundle and was killed during the POST
    pid, sha = ready[1]
    jid = _submit_job(box, nav, pid)
    reserved = box.orch.db.submission_reserve(
        {
            "job_id": jid,
            "ruleset": "ONC-OSI",
            "pid": pid,
            "nav_job_id": nav.job_id,
            "bundle_sha": sha,
            "dry_run": False,
            "outcome": "pending",
            "submitted_by": "onc-dr@hospa.test",
            "submitted_at": "2026-10-05T09:00:00+08:00",
        }
    )
    assert reserved is None
    box.orch.drain()
    job = box.orch.db.get(jid)
    assert job is not None and job.state == "failed" and job.error is not None
    assert "interrupted" in job.error.message and len(posted) == 1


def test_live_submit_failure_classification(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """No connection → nothing was sent, the bundle may be submitted again; a lost answer → the claim may exist at
    NHI, so the bundle stays reserved ('uncertain') and a new SUBMIT is refused without posting."""
    import httpx

    box: Box = world["box"]
    ready = _live_ready(box, world, monkeypatch)
    nav = world["nav_live"]
    pid, sha = ready[0]
    calls: list[str] = []

    def failing(exc: Exception) -> Any:
        def post(url: str, content: bytes, headers: dict[str, str], timeout: float) -> httpx.Response:
            calls.append(type(exc).__name__)
            raise exc

        return post

    monkeypatch.setattr(httpx, "post", failing(httpx.ConnectError("refused")))
    jid = _submit_job(box, nav, pid)
    box.orch.drain()
    job = box.orch.db.get(jid)
    assert job is not None and job.state == "failed" and job.error is not None
    assert "nothing was submitted" in job.error.message and not box.orch.db.submissions(sha, live_only=True)
    monkeypatch.setattr(httpx, "post", failing(httpx.ReadTimeout("no answer")))
    jid = _submit_job(box, nav, pid)
    box.orch.drain()
    job = box.orch.db.get(jid)
    assert job is not None and job.state == "failed" and job.error is not None
    assert "may have been received" in job.error.message
    (row,) = box.orch.db.submissions(sha, live_only=True)
    assert row["outcome"] == "uncertain" and row["job_id"] == jid
    jid = _submit_job(box, nav, pid)
    box.orch.drain()
    job = box.orch.db.get(jid)
    assert job is not None and job.state == "failed" and job.error is not None
    assert "already submitted" in job.error.message and calls == ["ConnectError", "ReadTimeout"]
