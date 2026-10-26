"""Consent explainer by e-mail, in process: ``CONSENT GZQO`` with the ICF attached -> draft review mail -> ``RELEASE``
-> released patient pages (stub draft model; the stub as the second model where a test wires one)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from tb_common.audit import verify
from tb_common.llm import LlmClient

from tests.inproc_box import Box, make_box

ROOT = Path(__file__).resolve().parents[2]
ICF = (ROOT / "tests/fixtures/consent/GZQO_ICF_v2.md").read_bytes()


def _box(tmp_path: Path, site_key_dir: Path, verifier: bool = True) -> Box:
    box = make_box(tmp_path, tmp_path / "lake", site_key_dir)
    if verifier:
        v = LlmClient("http://stub/v1", "stub-verifier", audit=box.orch.audit)
        v.http = TestClient(stub)
        box.orch.services.verifier = v
    return box


def _consent(box: Box, subject: str = "CONSENT GZQO lang=en,ja,zh-TW") -> str:
    assert box.mail(subject, (("GZQO_ICF_v2.md", ICF),)) == "Processed"
    job = box.orch.db.find(type_="CONSENT")[0]
    box.orch.drain()
    got = box.orch.db.get(job.job_id)
    assert got is not None and got.state == "done", got and got.error
    return job.job_id


def test_consent_draft_then_release(tmp_path: Path, site_key_dir: Path) -> None:
    box = _box(tmp_path, site_key_dir)
    jid = _consent(box)
    (mail,) = [s for s in box.sent if s.subject.startswith("[GZQO] CONSENT draft ready for review")]
    assert mail.subject == f"[GZQO] CONSENT draft ready for review: EN, JA, zh-TW · job {jid}"
    assert mail.to == ["crc1@hospa.test"]
    atts = mail.attachments()
    assert sorted(atts) == [
        "consent_GZQO_en_DRAFT.html",
        "consent_GZQO_ja_DRAFT.html",
        "consent_GZQO_review.html",
        "consent_GZQO_zh-TW_DRAFT.html",
    ]
    en = atts["consent_GZQO_en_DRAFT.html"].decode()
    assert "02-2312-3456" in en and "CONTACT_" not in en  # contacts masked for the model, put back after
    assert "DRAFT for the study team" in en and "It is not the consent form, it is not a signature" in en
    assert "治験スタッフ確認用" in atts["consent_GZQO_ja_DRAFT.html"].decode()
    assert "以同意書為準" in atts["consent_GZQO_zh-TW_DRAFT.html"].decode()
    assert f"RELEASE {jid}" in mail.text() and "not the consent form" in mail.text()
    job = box.orch.db.get(jid)
    assert job is not None and job.metrics is not None and job.metrics.llm_calls == 6  # draft, 2 translations, 3 checks
    rec = json.loads(box.store.get(next(o.minio_key for o in job.outputs or [] if o.filename == "consent_GZQO.json")))
    assert rec["languages"] == ["en", "ja", "zh-TW"] and rec["verified"] and rec["missing_sections"] == []
    assert rec["items"] and all(it["removed"] is None for it in rec["items"])
    assert all(t["status"] == "ok" for it in rec["items"] for t in it["texts"].values())
    assert {o.tag for o in job.outputs or []} == {"aggregate"}

    # a sender who is not a reviewer cannot release
    assert box.mail(f"RELEASE {jid}", sender="nurse-rheu@hospa.test") == "Rejected"
    first = rec["items"][0]["id"]
    assert box.mail(f"RELEASE {jid} drop={first}", sender="pi@hospa.test") == "Processed"
    box.orch.drain()
    rel = box.orch.db.find(type_="RELEASE")[0]
    rel = box.orch.db.get(rel.job_id) or rel
    assert rel.state == "done", rel.error
    (out,) = [s for s in box.sent if s.subject.startswith("[GZQO] CONSENT released")]
    assert sorted(out.to) == ["crc1@hospa.test", "pi@hospa.test"]
    page = out.attachments()["consent_GZQO_en.html"].decode()
    assert "DRAFT" not in page and "Reviewed and released by pi@hospa.test" in page
    assert f'data-id="{first}"' not in page and 'data-id="I02"' in page
    assert sorted(out.attachments()) == ["consent_GZQO_en.html", "consent_GZQO_ja.html", "consent_GZQO_zh-TW.html"]
    assert verify(box.audit_dir).ok
    events = [json.loads(ln) for f in sorted(box.audit_dir.glob("*.jsonl")) for ln in f.read_text().splitlines()]
    (ev,) = [e for e in events if e.get("event") == "consent.release"]
    assert ev["actor"] == "pi@hospa.test" and ev["detail"]["drop"] == [first]


def test_consent_without_verifier_is_marked_unverified(tmp_path: Path, site_key_dir: Path) -> None:
    box = _box(tmp_path, site_key_dir, verifier=False)
    jid = _consent(box, "CONSENT GZQO lang=en")
    job = box.orch.db.get(jid)
    assert job is not None
    rec = json.loads(box.store.get(next(o.minio_key for o in job.outputs or [] if o.filename == "consent_GZQO.json")))
    assert rec["languages"] == ["en"] and not rec["verified"]
    assert {t["status"] for it in rec["items"] for t in it["texts"].values()} == {"unverified"}
    (mail,) = [s for s in box.sent if "CONSENT draft ready" in s.subject]
    assert "not configured" in mail.text()


def test_consent_refusals(tmp_path: Path, site_key_dir: Path) -> None:
    box = _box(tmp_path, site_key_dir)
    assert box.mail("CONSENT GZQO") == "Processed"  # no attachment
    box.orch.drain()
    (job,) = box.orch.db.find(type_="CONSENT")
    got = box.orch.db.get(job.job_id)
    assert got is not None and got.state == "failed" and got.error is not None
    assert "informed-consent form" in got.error.message
    # RELEASE of a job that is not a consent explainer, and of an unknown item id
    assert box.mail(f"RELEASE {job.job_id}", sender="pi@hospa.test") == "Processed"
    jid = _consent(box, "CONSENT GZQO lang=en")
    assert box.mail(f"RELEASE {jid} keep=I99", sender="pi@hospa.test") == "Processed"
    box.orch.drain()
    errors = sorted((j.error.message if j.error else "") for j in box.orch.db.find(type_="RELEASE"))
    assert any("is failed, not done" in e or "not a consent explainer" in e for e in errors), errors
    assert any("no item I99" in e for e in errors), errors


@pytest.mark.parametrize("bad", ["lang=fr", "lang=en,xx"])
def test_consent_unknown_language(tmp_path: Path, site_key_dir: Path, bad: str) -> None:
    box = _box(tmp_path, site_key_dir)
    assert box.mail(f"CONSENT GZQO {bad}", (("GZQO_ICF_v2.md", ICF),)) == "Processed"
    box.orch.drain()
    (job,) = box.orch.db.find(type_="CONSENT")
    got = box.orch.db.get(job.job_id)
    assert got is not None and got.state == "failed" and got.error is not None
    assert "supported languages" in got.error.message
