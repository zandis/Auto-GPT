"""The compose test stack as seen from the host (deploy/docker-compose.test.yml).

Every published port can be moved when it is taken on the developer machine: set ``TB_HOST_<NAME>_PORT`` in the
environment or in ``deploy/.env`` (where compose reads it too). ``ensure_ingested()`` loads synthetic site A once, so
the compose integration and e2e tests do not depend on a manual ingest or on test order."""

from __future__ import annotations

import os
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

import httpx
from tb_common.config import _read_dotenv

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "2026-10-04"  # synthetic fixtures' snapshot (tools/synth/generator.py: reference date minus one day)

DEFAULT_PORTS = {
    "SMTP": 3025,  # GreenMail SMTP (mail into the box)
    "IMAP": 3143,  # GreenMail IMAP
    "MAILHOG": 8025,  # Mailpit UI/API (mail out of the box; the name is kept for existing deploy/.env files)
    "ORCH": 8010,
    "PARSER": 8011,
    "COMPILER": 8012,
    "LAKE": 8013,
    "MAIL_GATEWAY": 8015,
    "ADAPTER": 8016,
    "FHIR": 8080,
    "GATEWAY": 8020,  # tb-gateway: the only model path (llm-stub / llm-service are not published)
    "WORKFLOW_DB": 5433,  # the box's one Postgres, database trialbox_wf (outbox, recall ledger)
}


def host_port(name: str) -> int:
    key = f"TB_HOST_{name}_PORT"
    raw = os.environ.get(key) or _read_dotenv(ROOT / "deploy" / ".env").get(key) or str(DEFAULT_PORTS[name])
    return int(raw)


def url(name: str, path: str = "") -> str:
    return f"http://127.0.0.1:{host_port(name)}{path}"


MAILPIT_LIST = "/api/v1/messages"  # Mailpit's API (deploy/docker-compose.test.yml, D-348)


def outbound_mail(limit: int = 500) -> list[EmailMessage]:
    """The box's outbound mail as Mailpit holds it, newest first: the list, then each message's raw source."""
    base = url("MAILHOG")
    listing = httpx.get(f"{base}{MAILPIT_LIST}", params={"limit": limit}, timeout=30).json()
    out = []
    for it in listing.get("messages") or []:
        raw = httpx.get(f"{base}/api/v1/message/{it['ID']}/raw", timeout=30)
        raw.raise_for_status()
        msg = message_from_bytes(raw.content, policy=policy.default)
        assert isinstance(msg, EmailMessage)
        out.append(msg)
    return out


def ensure_ingested(force: bool = False) -> dict[str, object] | None:
    """Run the adapter's CSV ingest unless the lake already has a snapshot; returns the adapter report if it ran."""
    if not force:
        health = httpx.get(url("LAKE", "/healthz"), timeout=30).json()
        if health.get("checks", {}).get("snapshot", "none") != "none":
            return None
    from tb_common.jobpoll import Poll

    resp = httpx.post(url("ADAPTER", "/run"), json={"source": "csv", "snapshot": SNAPSHOT}, timeout=60)
    resp.raise_for_status()  # T-690 (D-472): 202 and a run id; the night is followed, not timed
    run = resp.json()["run"]

    def read() -> dict[str, object]:
        r = httpx.get(url("ADAPTER", f"/run/{run}"), timeout=60)
        r.raise_for_status()
        body: dict[str, object] = r.json()
        return body

    st = Poll().until_done(read, "ingest")
    assert st["state"] == "done", st
    report = st["report"]
    assert isinstance(report, dict)
    return report


if __name__ == "__main__":  # `make ingest-test`
    rep = ensure_ingested(force=True)
    assert rep is not None
    print({k: rep.get(k) for k in ("passed", "counts", "fhir_loaded")})
