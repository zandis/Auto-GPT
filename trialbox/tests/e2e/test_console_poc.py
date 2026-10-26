"""POC end to end on the running stack (``make poc``, then ``make test-console-e2e``): the admin console in a real
browser and e-mail in and out, through the same orchestrator path.

* web: an administrator signs in, starts ``FEAS GZQO`` from the web, sees the attrition table and downloads the PDF;
* e-mail: ``FEAS GZQO`` mailed to the box through GreenMail; the reply lands in MailHog and the console shows the
  thread of that job;
* the console's test mailbox sends a request that goes through the normal e-mail intake;
* a viewer sees results but cannot start a job (disabled button, and a forged POST gets 403).

The browser part is ``tests/e2e/console_poc.js`` (Node Playwright, preinstalled Chromium). Test accounts are created
with the console CLI inside the container (``docker exec``); ``TB_CONSOLE_SCREENSHOTS=<dir>`` saves screenshots.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import smtplib
import subprocess
import time
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import httpx
import pytest
from tb_common.subject import is_job_mail

from tests.stack import host_port, url

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("console_poc.js")
CONSOLE = f"http://127.0.0.1:{os.environ.get('TB_HOST_CONSOLE_PORT', '8090')}"
CONTAINER = os.environ.get("TB_CONSOLE_CONTAINER", "trialbox-console-1")
ADMIN_MAILBOX = os.environ.get("TB_POC_ADMIN_EMAIL", "admin@hospa.test")
AUTH = "mx.hospa.test; spf=pass smtp.mailfrom=hospa.test; dkim=pass header.d=hospa.test; dmarc=pass"


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


def _cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-m", "console.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _account(name: str, role: str, mailbox: str = "") -> str:
    pw = secrets.token_urlsafe(18)
    extra = ["--mailbox", mailbox] if mailbox else []
    r = _cli("add-user", name, "--role", role, *extra, "--password-stdin", stdin=pw + "\n")
    if r.returncode != 0:
        assert "exists" in r.stderr, r.stderr
        r = _cli("reset-password", name, "--password-stdin", stdin=pw + "\n")
        assert r.returncode == 0, r.stderr
    return pw


def _shots() -> str:
    d = os.environ.get("TB_CONSOLE_SCREENSHOTS", "")
    if d:
        Path(d).mkdir(parents=True, exist_ok=True)
    return d


def browser(mode: str, **args: Any) -> dict[str, Any]:
    r = subprocess.run(
        ["node", str(SCRIPT), mode, json.dumps({"base": CONSOLE, "shots": _shots(), **args})],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    assert lines, f"no result from the browser script: {r.stdout[-2000:]} {r.stderr[-2000:]}"
    out: dict[str, Any] = json.loads(lines[-1])
    failed = [c["what"] for c in out["checks"] if not c["ok"]]
    assert r.returncode == 0 and not failed, f"browser checks failed: {failed} {r.stderr[-1500:]}"
    return out


def mailhog() -> list[EmailMessage]:
    items = httpx.get(url("MAILHOG", "/api/v2/messages"), params={"limit": 500}, timeout=30).json()["items"]
    out = []
    for it in items:
        msg = message_from_bytes(it["Raw"]["Data"].encode("utf-8", "surrogateescape"), policy=policy.default)
        assert isinstance(msg, EmailMessage)
        out.append(msg)
    return out


def wait_mail(prefix: str, timeout: float = 900) -> EmailMessage:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in mailhog():
            if str(m["Subject"]).startswith(prefix):
                return m
        time.sleep(3)
    raise AssertionError(f"no mail {prefix!r} in MailHog")


def wait_job_mail(kind: str, job_id: str, timeout: float = 900) -> EmailMessage:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in mailhog():
            if is_job_mail(str(m["Subject"]), kind, job_id):
                return m
        time.sleep(3)
    raise AssertionError(f"no {kind} mail for job {job_id} in MailHog")


def job_by_comment(tag: str, timeout: float = 300) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = httpx.get(url("ORCH", "/jobs"), params={"type": "FEAS", "limit": 100}, timeout=30).json()
        job: dict[str, Any] = next((j for j in jobs if j.get("comment") == tag), {})
        if job:
            return job
        time.sleep(2)
    raise AssertionError(f"no job with comment {tag!r}")


@pytest.fixture(scope="module")
def accounts() -> dict[str, str]:
    if not _node_playwright():
        pytest.skip("Node Playwright is not available")
    try:
        assert httpx.get(f"{CONSOLE}/healthz", timeout=5).json()["pilot"] is True
        httpx.get(url("MAILHOG", "/api/v2/messages"), timeout=5).raise_for_status()
    except (httpx.HTTPError, AssertionError, KeyError):
        pytest.skip("POC stack not running (make poc)")
    lake = httpx.get(url("LAKE", "/healthz"), timeout=30).json()
    if lake.get("checks", {}).get("snapshot", "none") == "none":
        assert _cli("ingest").returncode == 0
    return {
        "admin": _account("e2e-admin", "admin", ADMIN_MAILBOX),
        "viewer": _account("e2e-viewer", "viewer"),
    }


def test_web_feas_result_and_pdf(accounts: dict[str, str]) -> None:
    out = browser("web", user="e2e-admin", password=accounts["admin"])
    assert out["pdf"].startswith("feasibility_GZQO") and out["pdf"].endswith(".pdf")
    job = httpx.get(url("ORCH", f"/jobs/{out['job']}"), timeout=30).json()
    assert job["state"] == "done" and job["requested_by"] == ADMIN_MAILBOX  # same orchestrator record as e-mail
    done = wait_job_mail("done", out["job"], 120)  # results still go out by e-mail
    assert any(str(p.get_filename()).endswith(".pdf") for p in done.iter_attachments())


def test_email_feas_reply_in_mailhog_and_console(accounts: dict[str, str]) -> None:
    tag = f"console-e2e-{os.getpid()}-{int(time.time())}"
    m = EmailMessage()
    m["From"] = ADMIN_MAILBOX
    m["To"] = "trialbox@hospa.test"
    m["Subject"] = f"FEAS GZQO -- {tag}"
    m["Message-ID"] = make_msgid(domain="hospa.test")
    m["Authentication-Results"] = AUTH
    m.set_content("POC e-mail request")
    with smtplib.SMTP("127.0.0.1", host_port("SMTP"), timeout=30) as s:
        s.send_message(m)
    job = job_by_comment(tag)
    wait_job_mail("received", job["job_id"], 300)
    done = wait_job_mail("done", job["job_id"], 900)
    assert any(str(p.get_filename()).endswith(".pdf") for p in done.iter_attachments())
    browser("thread", user="e2e-admin", password=accounts["admin"], job=job["job_id"], webmail=url("MAILHOG"))


def test_console_test_mailbox_goes_through_email_intake(accounts: dict[str, str]) -> None:
    tag = f"console-mailbox-{os.getpid()}-{int(time.time())}"
    browser("mailbox", user="e2e-admin", password=accounts["admin"], subject=f"FEAS GZQO -- {tag}")
    job = job_by_comment(tag)
    assert job["requested_by"] == ADMIN_MAILBOX
    wait_job_mail("done", job["job_id"], 900)


def test_viewer_cannot_start_jobs(accounts: dict[str, str]) -> None:
    before = len(httpx.get(url("ORCH", "/jobs"), params={"limit": 500}, timeout=30).json())
    out = browser("viewer", user="e2e-viewer", password=accounts["viewer"])
    assert out["viewer_post"] == 403
    after = len(httpx.get(url("ORCH", "/jobs"), params={"limit": 500}, timeout=30).json())
    assert after == before


def test_protocol_compile_approve_loop_from_the_web(accounts: dict[str, str]) -> None:
    ruleset = f"GZQO-W{os.getpid() % 100000}"
    out = browser("protocol", user="e2e-admin", password=accounts["admin"], ruleset=ruleset)
    wait_mail(f"APPROVE {ruleset} version=1.0.0", 120)  # the review package went out by e-mail as well
    wait_mail(f"[{ruleset}] ruleset v1.0.0 approved", 120)
    assert httpx.get(url("ORCH", f"/jobs/{out['feas']}"), timeout=30).json()["state"] == "done"


def test_cascade_dl1_and_recall_certificate(accounts: dict[str, str]) -> None:
    browser("cascade", user="e2e-admin", password=accounts["admin"])


def test_plain_words_become_a_confirmed_proposal(accounts: dict[str, str]) -> None:
    out = browser(
        "propose", user="e2e-admin", password=accounts["admin"], text="GZQO這個試驗在我們醫院做得起來嗎？回溯三年"
    )
    assert out["line"].startswith("FEAS GZQO")  # classify_intent through tb-gateway (stub model in stub mode)
