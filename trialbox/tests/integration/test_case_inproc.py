"""CASE in process: one uploaded chart against the approved GZQO ruleset -> eligibility sheet (phi, to the study
team) + counts-only summary to the requester; structured criteria from the lake when the chart number is known,
from the chart text otherwise; the two-model agreement rule on note criteria; refusals."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from orchestrator.scenarios.case import chart_excerpts, find_date
from tb_common.audit import verify
from tb_common.crypto import pid_for_mrn
from tb_common.llm import LlmClient
from tb_contracts import Job

from tests.inproc_box import Box, ingest_site, make_box

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)

# a discharge summary the stub judge can read: two dated acute flares in the last 12 months, no current flare
CHART = """# 出院病摘 Discharge summary

病歷摘要 2026年9月28日
主診斷：痛風（gout）。病人男性，52歲。
2026年3月12日 急性痛風發作，右側第一蹠趾關節紅腫熱痛，給予colchicine。
2026年7月4日 急性痛風發作，左膝，NSAID治療後緩解。
目前無急性痛風發作。持續使用allopurinol 300 mg每日。

檢驗 2026年9月18日
尿酸 7.9 mg/dL，肌酸酐 1.0 mg/dL，HbA1c 6.1%。
"""


@pytest.fixture(scope="module")
def world(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("case")
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(synth_dir / "site-a", tmp / "lake", sec, "2026-10-04")
    box = make_box(tmp / "box", tmp / "lake", sec, RUN)
    mrns = [r["mrn"] for r in csv.DictReader((synth_dir / "site-a" / "patient.csv").open(encoding="utf-8"))]
    return {"tmp": tmp, "box": box, "mrns": mrns}


def _run(
    box: Box, subject: str, files: tuple[tuple[str, bytes], ...] = (("chart.md", CHART.encode()),), **kw: Any
) -> Job:
    assert box.mail(subject, files, **kw) == "Processed"
    job = max(box.orch.db.find(type_="CASE"), key=lambda j: (j.received_at, j.job_id))
    box.orch.drain()
    got = box.orch.db.get(job.job_id)
    assert got is not None
    return got


def _unzip(box: Box, mail: Any, job_id: str) -> dict[str, bytes]:
    """Like ``inproc_box.unzip_phi`` but finds the password mail by job id (long subjects fold differently)."""
    import io
    import tempfile

    import py7zr

    ((name, data),) = mail.attachments().items()
    assert name.endswith(".7z")
    pw_mail = next(
        s for s in box.sent if s.subject.startswith("Password") and job_id in s.subject and s.to == mail.to[:1]
    )
    password = next(ln.strip() for ln in pw_mail.text().splitlines() if ln.startswith("    "))
    with tempfile.TemporaryDirectory() as td, py7zr.SevenZipFile(io.BytesIO(data), password=password) as z:
        z.extractall(td)
        return {p.name: p.read_bytes() for p in Path(td).rglob("*") if p.is_file()}


def _sheet(box: Box, job_id: str) -> tuple[str, dict[str, Any]]:
    mail = next(
        s for s in reversed(box.sent) if f"job {job_id}" in s.subject and "CASE sheet" in s.subject and s.attachments()
    )
    assert mail.to == ["crc1@hospa.test", "pi@hospa.test"]  # the ruleset's list_to (study team), never referral_to
    files = _unzip(box, mail, job_id)
    html = next(v for k, v in files.items() if k.endswith(".html")).decode()
    rec_out = next(o for o in box.orch.db.get(job_id).outputs or [] if o.filename.endswith(".json"))  # type: ignore[union-attr]
    return html, json.loads(box.store.get(rec_out.minio_key))


def test_case_with_chart_number_uses_lake_for_structured(world: dict[str, Any]) -> None:
    box: Box = world["box"]
    mrn = world["mrns"][0]
    job = _run(box, f"CASE GZQO mrn={mrn} lang=zh-TW")
    assert job.state == "done", job.error
    assert job.ruleset_version == "1.0.0" and job.snapshot_date == date(2026, 10, 4)
    html, rec = _sheet(box, job.job_id)
    assert rec["subject"] == {
        "pid": pid_for_mrn(KEY, mrn),
        "in_lake": True,
        "snapshot": "2026-10-04",
        "note": "",
    }
    assert mrn not in json.dumps(rec) and mrn not in html  # the chart number never enters the record
    by_id = {r["id"]: r for r in rec["criteria"]}
    assert by_id["GZQO-INC-01"]["source"] == "lake" and by_id["GZQO-INC-01"]["verdict"] in ("pass", "fail")
    assert by_id["GZQO-INC-05"] == {
        **by_id["GZQO-INC-05"],
        "source": "chart",
        "verdict": "pass",
        "quote_date": "2026-09-28",  # the excerpt's date: the summary paragraph is dated 28 Sep
    }
    assert "急性痛風發作" in by_id["GZQO-INC-05"]["quote"]
    assert by_id["GZQO-EXC-11"]["verdict"] == "pass" and by_id["GZQO-EXC-11"]["source"] == "chart"  # no current flare
    assert by_id["GZQO-INC-07"]["verdict"] == "pending_human" and by_id["GZQO-INC-07"]["resolve"]
    assert rec["counts"]["total"] == len(rec["criteria"]) and rec["counts"]["human"] == 3
    assert "適格性檢核表" in html and "不代表不符合條件" in html and 'data-verdict="pass"' in html
    assert rec["judge"]["mode"] == "single" and rec["judge"]["calls"] >= 2
    # the mail body carries counts only, never a quote; the requester is on list_to so there is no second mail
    sheet_mail = next(s for s in reversed(box.sent) if f"job {job.job_id}" in s.subject and s.attachments())
    assert "急性痛風" not in sheet_mail.text() and "共" in sheet_mail.subject
    assert not [s for s in box.sent if f"job {job.job_id}" in s.subject and "CASE done" in s.subject]
    # a requester who is not on list_to gets the counts-only mail and no sheet
    job2 = _run(box, f"CASE GZQO mrn={mrn} lang=en", sender="nurse-rheu@hospa.test")
    assert job2.state == "done", job2.error
    done = next(s for s in reversed(box.sent) if f"job {job2.job_id}" in s.subject and "CASE done" in s.subject)
    assert done.to == ["nurse-rheu@hospa.test"] and not done.attachments() and "急性痛風" not in done.text()
    assert {o.tag for o in job.outputs or []} == {"phi"}
    assert verify(box.audit_dir).ok


def test_case_without_chart_number_judges_structured_from_chart(world: dict[str, Any]) -> None:
    box: Box = world["box"]
    job = _run(box, "CASE GZQO lang=en")
    assert job.state == "done", job.error
    html, rec = _sheet(box, job.job_id)
    assert rec["subject"]["pid"] is None and not rec["subject"]["in_lake"]
    by_id = {r["id"]: r for r in rec["criteria"]}
    assert by_id["GZQO-INC-01"]["source"] == "chart" and by_id["GZQO-INC-01"]["verdict"] == "unknown"
    assert by_id["GZQO-INC-05"]["verdict"] == "pass"
    assert "should be checked against the record" in html and "Eligibility sheet" in html
    assert by_id["GZQO-INC-01"]["resolve"].startswith("Give the chart number")


def test_case_agreement_rule_with_verifier(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    box: Box = world["box"]
    v = LlmClient("http://stub/v1", "stub-verifier", audit=box.orch.audit)
    v.http = TestClient(stub)
    box.orch.services.verifier = v
    try:
        job = _run(box, "CASE GZQO lang=en")
        assert job.state == "done", job.error
        _, rec = _sheet(box, job.job_id)
        assert rec["judge"]["mode"] == "agreement" and rec["judge"]["verifier"] == "stub-verifier"
        assert rec["judge"]["disagreements"] == 0  # the same stub agrees with itself
        by_id = {r["id"]: r for r in rec["criteria"]}
        assert by_id["GZQO-INC-05"]["verdict"] == "pass"
        monkeypatch.setenv("TB_SCREEN_JUDGE", "single")
        job2 = _run(box, "CASE GZQO lang=en")
        _, rec2 = _sheet(box, job2.job_id)
        assert rec2["judge"]["mode"] == "single"
    finally:
        box.orch.services.verifier = None


def test_case_refusals(world: dict[str, Any]) -> None:
    box: Box = world["box"]
    job = _run(box, "CASE GZQO", files=())
    assert job.state == "failed" and job.error is not None and "Attach the patient's chart" in job.error.message
    job = _run(box, "CASE GZQO mrn=abc")
    assert job.state == "failed" and job.error is not None and "chart number" in job.error.message
    job = _run(box, "CASE GZQO lang=fr")
    assert job.state == "failed" and job.error is not None and "lang=" in job.error.message
    assert box.mail("CASE GZQO", (("chart.md", CHART.encode()),), sender="someone@outside.example") == "Rejected"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("門診 2026-03-14 主訴", date(2026, 3, 14)),
        ("2026/3/4 visit", date(2026, 3, 4)),
        ("民國115年3月14日 門診", date(2026, 3, 14)),
        ("115.03.14 門診", date(2026, 3, 14)),
        ("令和8年3月14日 外来", date(2026, 3, 14)),
        ("R8.3.14 受診", date(2026, 3, 14)),
        ("平成31年4月30日", date(2019, 4, 30)),
        ("no date here", None),
        ("尿酸 7.9 mg/dL 2026-13-45", None),
    ],
)
def test_find_date(text: str, expected: date | None) -> None:
    assert find_date(text) == expected


def test_chart_excerpts_carry_dates_forward_and_flag_undated() -> None:
    ex = chart_excerpts(
        "Undated preamble.\n\n# Progress note\n\n2026-05-01 seen in clinic.\n\nFollow-up text.", "n.txt", RUN
    )
    assert [e["date_source"] for e in ex] == ["upload", "document", "document"]
    assert ex[0]["date"] == RUN.isoformat() and ex[1]["date"] == ex[2]["date"] == "2026-05-01"
    assert ex[1]["note_type"] == "Progress note" and ex[0]["note_type"] == "n"
    assert ex[1]["did"] == "chart:n.txt#2"
    long = chart_excerpts("2026-05-01 " + "句子。" * 1500, "x.txt", RUN)
    assert len(long) > 1 and all(len(e["text"]) <= 1_900 for e in long)
