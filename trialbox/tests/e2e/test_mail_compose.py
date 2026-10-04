"""Phase 3 DoD on the compose test stack: a real email ``FEAS GZQO`` -> GreenMail (IMAP intake) -> mail-gateway ->
orchestrator -> FEAS -> mail-gateway -> MailHog (SMTP sink) with the feasibility PDF; and the APPROVE loop over email
(review.xlsx round trip) for a protocol attached to ``FEAS``.

    make up-test && make test-e2e
"""

from __future__ import annotations

import io
import os
import smtplib
import time
from collections.abc import Callable
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import httpx
import pytest
from pypdf import PdfReader

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
MAILHOG = "http://127.0.0.1:8025"
ORCH = "http://127.0.0.1:8010"
AUTH = "mx.hospa.test; spf=pass smtp.mailfrom=hospa.test; dkim=pass header.d=hospa.test; dmarc=pass"


def send(
    subject: str,
    attachments: tuple[tuple[str, bytes], ...] = (),
    sender: str = "crc1@hospa.test",
    in_reply_to: str | None = None,
) -> str:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "trialbox@hospa.test"
    m["Subject"] = subject
    m["Message-ID"] = mid = make_msgid(domain="hospa.test")
    m["Authentication-Results"] = AUTH  # what the hospital MTA adds in front of the intake mailbox
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content("TrialBox E2E")
    for name, data in attachments:
        m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    with smtplib.SMTP("127.0.0.1", 3025, timeout=30) as s:
        s.send_message(m)
    return mid


def outbox() -> list[EmailMessage]:
    items = httpx.get(f"{MAILHOG}/api/v2/messages", params={"limit": 500}, timeout=30).json()["items"]
    out = []
    for it in items:
        msg = message_from_bytes(it["Raw"]["Data"].encode("utf-8", "surrogateescape"), policy=policy.default)
        assert isinstance(msg, EmailMessage)
        out.append(msg)
    return out


def wait_for(pred: Callable[[EmailMessage], bool], timeout: float = 1800) -> EmailMessage:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in outbox():
            if pred(m):
                return m
        time.sleep(3)
    raise AssertionError("expected mail did not arrive")


def attachments(m: EmailMessage) -> dict[str, bytes]:
    out = {}
    for part in m.iter_attachments():
        data = part.get_payload(decode=True)
        assert isinstance(data, bytes)
        out[str(part.get_filename())] = data
    return out


def job_id_from(m: EmailMessage) -> str:
    return str(m["Subject"]).split()[1]


@pytest.fixture(scope="module", autouse=True)
def stack() -> None:
    try:
        assert httpx.get(f"{ORCH}/healthz", timeout=5).status_code == 200
        httpx.get(f"{MAILHOG}/api/v2/messages", timeout=5).raise_for_status()
    except (httpx.HTTPError, AssertionError):
        pytest.skip("compose test stack not running (make up-test)")


def test_feas_email_to_pdf() -> None:
    t0 = time.monotonic()
    tag = f"e2e-{os.getpid()}"
    send(f"FEAS GZQO -- {tag}")
    job: dict[str, object] = {}
    deadline = time.monotonic() + 300
    while not job and time.monotonic() < deadline:  # the gateway polls IMAP every 5 s in the test profile
        jobs = httpx.get(f"{ORCH}/jobs", params={"type": "FEAS", "limit": 50}, timeout=30).json()
        job = next((j for j in jobs if j.get("comment") == tag), {})
        time.sleep(2)
    assert job, "job not created from the email"
    wait_for(lambda m: str(m["Subject"]).startswith(f"Received {job['job_id']}"), 300)
    done = wait_for(lambda m: str(m["Subject"]).startswith(f"Done {job['job_id']}"), 1800)
    elapsed = time.monotonic() - t0
    assert elapsed < 30 * 60  # SPEC phase 3 DoD: PDF within 30 min
    atts = attachments(done)
    pdf = next(v for k, v in atts.items() if k.endswith(".pdf"))
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Eligibility funnel" in text and f"job {job['job_id']}" in text
    assert any(k.endswith(".xlsx") for k in atts) and any(k.endswith(".json") for k in atts)
    final = httpx.get(f"{ORCH}/jobs/{job['job_id']}", timeout=30).json()
    assert final["state"] == "done" and len(final["outputs"]) == 4


def test_approve_loop_by_email() -> None:
    ruleset = f"GZQO-E{os.getpid() % 100000}"
    pdf = (ROOT / "tests/fixtures/protocols/GZQO_protocol_v3.pdf").read_bytes()
    send(f"FEAS {ruleset}", (("GZQO_protocol_v3.pdf", pdf),))
    review = wait_for(lambda m: str(m["Subject"]).startswith(f"APPROVE {ruleset} version=1.0.0"), 1800)
    xlsx = next(v for k, v in attachments(review).items() if k.endswith(".xlsx"))
    send("Approved, thanks", (("review.xlsx", xlsx),), in_reply_to=str(review["Message-ID"]))
    wait_for(lambda m: str(m["Subject"]) == f"Ruleset {ruleset} v1.0.0 approved", 1800)
    feas_id = str(review["Subject"]).rsplit("job ", 1)[1].strip()
    done = wait_for(lambda m: str(m["Subject"]).startswith(f"Done {feas_id}"), 1800)
    assert any(k.endswith(".pdf") for k in attachments(done))


def _unzip(m: EmailMessage) -> dict[str, bytes]:
    import tempfile

    import py7zr

    ((name, data),) = attachments(m).items()
    assert name.endswith(".7z")
    pw = wait_for(lambda x: str(x["Subject"]).startswith("Password") and str(m["Subject"]) in str(x["Subject"]), 120)
    body = pw.get_body(("plain",))
    assert body is not None
    password = next(ln.strip() for ln in str(body.get_content()).splitlines() if ln.startswith("    "))
    with tempfile.TemporaryDirectory() as td, py7zr.SevenZipFile(io.BytesIO(data), password=password) as z:
        z.extractall(td)
        return {p.name: p.read_bytes() for p in Path(td).rglob("*") if p.is_file()}


def test_screen_email_to_encrypted_list() -> None:
    import json

    tag = f"screen-{os.getpid()}"
    send(f"SCREEN GZQO version=1.0.0 -- {tag}")
    job: dict[str, object] = {}
    deadline = time.monotonic() + 300
    while not job and time.monotonic() < deadline:
        jobs = httpx.get(f"{ORCH}/jobs", params={"type": "SCREEN", "limit": 50}, timeout=30).json()
        job = next((j for j in jobs if j.get("comment") == tag), {})
        time.sleep(2)
    assert job
    done = wait_for(lambda m: str(m["Subject"]).startswith(f"Done {job['job_id']}"), 1800)
    assert any(k.endswith(".pdf") for k in attachments(done))
    lst = wait_for(lambda m: str(m["Subject"]) == f"Candidates GZQO v1.0.0 — job {job['job_id']}", 300)
    assert "pi@hospa.test" in str(lst["To"]) and "sponsor" not in str(lst["To"])
    files = _unzip(lst)
    cl = json.loads(next(v for k, v in files.items() if k.endswith(".json")))
    assert cl["rows"] and cl["summary"]["high"] + cl["summary"]["review"] == len(cl["rows"])
    final = httpx.get(f"{ORCH}/jobs/{job['job_id']}", timeout=30).json()
    assert final["state"] == "done" and final["metrics"]["patients_scoped"] > 50
